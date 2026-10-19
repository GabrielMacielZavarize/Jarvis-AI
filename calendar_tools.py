"""Google Agenda do Jarvis (AGD-27): ler, criar, alterar e apagar eventos por voz.

- Ler ("o que eu tenho hoje?", "e amanhã?", "qual minha próxima reunião?") não pede confirmação.
- Criar, alterar e apagar seguem o padrão do email e da instalação: a ferramenta prepara a
  mudança, mostra um código de 6 dígitos no HUD e só grava quando a ÚLTIMA fala do usuário
  for "confirmar agenda <código>".
- Datas em português ("sexta às 15h", "depois de amanhã às 9", "dia 25 às 14h30") no fuso
  America/Sao_Paulo.
- Login OAuth de app desktop, uma vez só: ``python calendar_tools.py --login`` abre o navegador
  e salva o token em ``google_token.json`` (fora do git).

Outras partes do Jarvis (rotinas, avisos proativos) podem chamar ``eventos_de_hoje()``,
``eventos_do_dia()``, ``proximo_evento()`` e ``resumo_do_dia()`` sem passar pela voz, e usar
``ReminderWatcher`` para saber quando avisar de uma reunião.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from livekit.agents import RunContext, function_tool

from confirmation import (
    confirmation_phrase,
    new_code,
    normalize_code,
    session_state,
    spoken_digits,
    wait_for_user_confirmation,
)
from hud import show_card, tool_status

logger = logging.getLogger("jarvis-calendar")

ROOT = Path(__file__).resolve().parent
# Baixado do Google Cloud (ID do cliente OAuth do tipo "App para computador").
CREDENTIALS_FILE = ROOT / "google_credentials.json"
# Criado pelo --login; renova sozinho. Apague (ou --logout) para desconectar.
TOKEN_FILE = ROOT / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_ID = "primary"
TZ_NAME = "America/Sao_Paulo"
TZ = ZoneInfo(TZ_NAME)

PENDING_CALENDAR_KEY = "pending_calendar"
DEFAULT_DURATION_MIN = 60
MAX_DURATION_MIN = 24 * 60
MAX_LIST_DAYS = 14
# Sem dia citado, "desmarca a reunião das 10" procura de hoje até uma semana à frente.
SEARCH_DAYS = 8
MAX_TITLE = 120
DEFAULT_REMINDER_MIN = 10
LOGIN_HINT = "Rode uma vez no computador: python calendar_tools.py --login"

WEEKDAY_NAMES = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
MONTH_NAMES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
MONTHS = {_plain_name: index for index, _plain_name in enumerate(
    ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"),
    start=1,
)}
# Números falados que aparecem em horários ("às nove e meia", "vinte e uma horas").
NUMBER_WORDS = {
    "vinte e tres": 23,
    "vinte e duas": 22,
    "vinte e dois": 22,
    "vinte e uma": 21,
    "vinte e um": 21,
    "quarenta e cinco": 45,
    "cinquenta": 50,
    "quarenta": 40,
    "trinta": 30,
    "vinte": 20,
    "dezenove": 19,
    "dezoito": 18,
    "dezessete": 17,
    "dezesseis": 16,
    "quinze": 15,
    "quatorze": 14,
    "catorze": 14,
    "treze": 13,
    "doze": 12,
    "onze": 11,
    "dez": 10,
    "nove": 9,
    "oito": 8,
    "sete": 7,
    "seis": 6,
    "cinco": 5,
    "quatro": 4,
    "tres": 3,
    "duas": 2,
    "dois": 2,
    "uma": 1,
    "um": 1,
}
_NUMBER_WORDS_RE = re.compile(r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b")
# Palavras que não ajudam a achar um evento pelo título ("a reunião das 10 de amanhã").
MATCH_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "um", "uma",
    "com", "pra", "para", "meu", "minha", "meus", "minhas", "hoje", "amanha", "depois", "evento", "compromisso",
    "horas", "hora", "h", "manha", "tarde", "noite", "dia", "que", "vem", "proxima", "proximo", "essa", "esse",
}


class CalendarError(RuntimeError):
    """Falha que o Jarvis explica ao usuário como está."""


class CalendarNotConnected(CalendarError):
    pass


# ───────────────────────── datas em português ─────────────────────────


def agora() -> dt.datetime:
    return dt.datetime.now(TZ)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    cleaned = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", cleaned.replace("-", " ").replace(",", " ")).strip()


@dataclass(frozen=True, slots=True)
class When:
    """O que o usuário disse: um dia, talvez um horário, e se o dia foi dito ou suposto (hoje)."""

    date: dt.date
    time: dt.time | None = None
    explicit_date: bool = False

    def start(self) -> dt.datetime | None:
        if self.time is None:
            return None
        return dt.datetime.combine(self.date, self.time, tzinfo=TZ)


def _from_iso(text: str) -> When | None:
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            return When(dt.date.fromisoformat(text), None, True)
        except ValueError:
            return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(TZ)
    if "T" not in text and " " not in text:
        return When(moment.date(), None, True)
    return When(moment.date(), moment.time().replace(second=0, microsecond=0, tzinfo=None), True)


def _spoken_numbers(text: str) -> str:
    text = re.sub(r"\bmeio dia\b", "12h", text)
    text = re.sub(r"\bmeia noite\b", "0h", text)
    return _NUMBER_WORDS_RE.sub(lambda match: str(NUMBER_WORDS[match.group(1)]), text)


_TIME_PATTERNS = (
    # 15h, 15h30, 15:30, 15 horas, 15 horas e 30, 15h e meia
    re.compile(r"\b(\d{1,2})\s*(?:h|:|horas?)\s*(?:e\s+)?(\d{2}|meia)?\b(?!\s*(?:dias?|minutos?)\b)"),
    # às 9, às 9 e meia, às 9 e 15
    re.compile(r"\bas\s+(\d{1,2})(?:\s+e\s+(\d{2}|meia))?\b(?!\s*/)"),
    # 9 da manhã, 3 da tarde
    re.compile(r"\b(\d{1,2})(?:\s+e\s+(\d{2}|meia))?(?=\s+da\s+(?:manha|tarde|noite|madrugada)\b)"),
)


def _parse_time(text: str) -> tuple[dt.time | None, str]:
    """Hour said in the text and the text without it."""
    for pattern in _TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        hour = int(match.group(1))
        raw_minute = match.group(2)
        minute = 30 if raw_minute == "meia" else int(raw_minute or 0)
        if hour > 23 or minute > 59:
            continue
        rest = text[: match.start()] + " " + text[match.end() :]
        if re.search(r"\b(tarde|noite)\b", text) and 1 <= hour < 12:
            hour += 12
        elif not re.search(r"\b(manha|madrugada)\b", text) and 1 <= hour <= 6 and ":" not in match.group(0):
            # "às 3" num compromisso é quase sempre 15h; "às 3 da manhã" e "03:00" ficam como estão.
            hour += 12
        return dt.time(hour, minute), rest
    return None, text


def _next_weekday(today: dt.date, weekday: int, *, strictly_after: bool) -> dt.date:
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0 and strictly_after:
        ahead = 7
    return today + dt.timedelta(days=ahead)


def _month_day(today: dt.date, day: int, month: int | None, year: int | None) -> dt.date | None:
    if year is not None and year < 100:
        year += 2000
    candidates = []
    if month is not None:
        years = [year] if year is not None else [today.year, today.year + 1]
        candidates = [(y, month) for y in years]
    else:
        candidates = [(today.year, today.month)]
        next_month = today.replace(day=1) + dt.timedelta(days=32)
        candidates.append((next_month.year, next_month.month))
    for cand_year, cand_month in candidates:
        try:
            date = dt.date(cand_year, cand_month, day)
        except ValueError:
            continue
        if year is not None or date >= today:
            return date
    return None


def _parse_date(text: str, today: dt.date) -> dt.date | None:
    if re.search(r"\bdepois de amanha\b", text):
        return today + dt.timedelta(days=2)
    if re.search(r"\bamanha\b", text):
        return today + dt.timedelta(days=1)
    if re.search(r"\bhoje\b", text):
        return today
    if re.search(r"\banteontem\b", text):
        return today - dt.timedelta(days=2)
    if re.search(r"\bontem\b", text):
        return today - dt.timedelta(days=1)
    match = re.search(r"\bdaqui a (\d{1,2}) dias?\b", text)
    if match:
        return today + dt.timedelta(days=int(match.group(1)))
    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        if 1 <= month <= 12:
            return _month_day(today, day, month, year)
    match = re.search(r"\bdia\s+(\d{1,2}|primeiro)(?:\s+de\s+([a-z]+))?(?:\s+de\s+(\d{4}))?\b", text)
    if not match or (match.group(2) and match.group(2) not in MONTHS):
        match = re.search(r"\b(\d{1,2}|primeiro)\s+de\s+([a-z]+)(?:\s+de\s+(\d{4}))?\b", text)
        match = match if match and match.group(2) in MONTHS else None
    if match:
        day = 1 if match.group(1) == "primeiro" else int(match.group(1))
        month = MONTHS.get(match.group(2) or "")
        year = int(match.group(3)) if match.group(3) else None
        return _month_day(today, day, month, year)
    next_week = bool(re.search(r"\b(semana que vem|proxima semana|semana seguinte)\b", text))
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", text):
            if next_week:
                monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(days=7)
                return monday + dt.timedelta(days=weekday)
            later = bool(re.search(r"\b(proxim[ao]|que vem|seguinte)\b", text))
            return _next_weekday(today, weekday, strictly_after=later)
    if next_week:
        return today + dt.timedelta(days=7)
    return None


def parse_when(text: str | None, now: dt.datetime | None = None) -> When | None:
    """Turn "sexta às 15h", "depois de amanhã às 9", "dia 25" or an ISO date into a When.

    Returns None when neither a day nor a time was understood.
    """
    if not text or not text.strip():
        return None
    now = (now or agora()).astimezone(TZ)
    iso = _from_iso(text.strip())
    if iso is not None:
        return iso

    plain = _spoken_numbers(_plain(text))
    match = re.search(r"\bdaqui a (\d{1,3}) (minutos?|horas?)\b", plain)
    if match:
        amount = int(match.group(1))
        delta = dt.timedelta(minutes=amount) if match.group(2).startswith("minuto") else dt.timedelta(hours=amount)
        moment = now + delta
        return When(moment.date(), moment.time().replace(second=0, microsecond=0, tzinfo=None), True)

    time, rest = _parse_time(plain)
    date = _parse_date(rest, now.date())
    if date is None and time is None:
        return None
    return When(date or now.date(), time, date is not None)


def day_label(date: dt.date, today: dt.date | None = None) -> str:
    """"hoje", "amanhã" ou "sexta, 23 de outubro"."""
    today = today or agora().date()
    full = f"{WEEKDAY_NAMES[date.weekday()]}, {date.day} de {MONTH_NAMES[date.month - 1]}"
    if date == today:
        return f"hoje ({full})"
    if date == today + dt.timedelta(days=1):
        return f"amanhã ({full})"
    if date == today - dt.timedelta(days=1):
        return f"ontem ({full})"
    return full


def _hhmm(moment: dt.datetime) -> str:
    return f"{moment:%H:%M}"


def _until(start: dt.datetime, now: dt.datetime) -> str:
    minutes = round((start - now).total_seconds() / 60)
    if minutes <= 0:
        return "agora"
    if minutes < 60:
        return f"em {minutes} {'minuto' if minutes == 1 else 'minutos'}"
    hours, rest = divmod(minutes, 60)
    if hours >= 24:
        days = round(hours / 24)
        return f"em {days} {'dia' if days == 1 else 'dias'}"
    text = f"em {hours} {'hora' if hours == 1 else 'horas'}"
    return f"{text} e {rest} min" if rest else text


# ───────────────────────── eventos ─────────────────────────


@dataclass(frozen=True, slots=True)
class Evento:
    id: str
    title: str
    start: dt.datetime
    end: dt.datetime
    all_day: bool = False
    location: str | None = None
    # Link da videochamada (Meet, Zoom no local...) ou None.
    meeting_link: str | None = None
    html_link: str | None = None

    def describe(self, today: dt.date | None = None, *, with_day: bool = False) -> str:
        prefix = f"{day_label(self.start.date(), today)}, " if with_day else ""
        if self.all_day:
            when = "dia inteiro"
        else:
            when = f"{_hhmm(self.start)}–{_hhmm(self.end)}"
        extra = f" ({self.location})" if self.location else ""
        return f"{prefix}{when} · {self.title}{extra}"

    def to_card(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "all_day": self.all_day,
            "location": self.location,
            "link": self.meeting_link,
        }


def _parse_moment(raw: dict[str, Any]) -> tuple[dt.datetime, bool]:
    if raw.get("dateTime"):
        return dt.datetime.fromisoformat(raw["dateTime"].replace("Z", "+00:00")).astimezone(TZ), False
    date = dt.date.fromisoformat(raw["date"])
    return dt.datetime.combine(date, dt.time(), tzinfo=TZ), True


def _meeting_link(item: dict[str, Any]) -> str | None:
    if item.get("hangoutLink"):
        return item["hangoutLink"]
    for entry in (item.get("conferenceData") or {}).get("entryPoints") or []:
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    location = item.get("location") or ""
    match = re.search(r"https?://\S+", location)
    return match.group(0) if match else None


def event_from_api(item: dict[str, Any]) -> Evento | None:
    """Google Calendar event -> Evento. Cancelled events and invitations declined are dropped."""
    if item.get("status") == "cancelled" or "start" not in item:
        return None
    for attendee in item.get("attendees") or []:
        if attendee.get("self") and attendee.get("responseStatus") == "declined":
            return None
    start, all_day = _parse_moment(item["start"])
    end, _ = _parse_moment(item.get("end") or item["start"])
    return Evento(
        id=item.get("id", ""),
        title=(item.get("summary") or "(sem título)").strip(),
        start=start,
        end=end,
        all_day=all_day,
        location=(item.get("location") or "").strip() or None,
        meeting_link=_meeting_link(item),
        html_link=item.get("htmlLink"),
    )


# ───────────────────────── Google Calendar API ─────────────────────────

_SERVICE: Any | None = None


def is_connected() -> bool:
    """O login já foi feito (existe token salvo)."""
    return TOKEN_FILE.exists()


def _save_token(credentials: Any) -> None:
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(credentials.to_json())


def _load_credentials() -> Any:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_FILE.exists():
        raise CalendarNotConnected(f"O Google Agenda ainda não foi conectado. {LOGIN_HINT}")
    try:
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except (ValueError, OSError) as exc:
        raise CalendarNotConnected(f"O token do Google Agenda está inválido. {LOGIN_HINT}") from exc
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            raise CalendarNotConnected(f"O acesso ao Google Agenda expirou ou foi revogado. {LOGIN_HINT}") from exc
        _save_token(credentials)
        return credentials
    raise CalendarNotConnected(f"O acesso ao Google Agenda expirou. {LOGIN_HINT}")


def get_service() -> Any:
    """Cliente da API (criado uma vez). Os testes trocam esta função por um falso."""
    global _SERVICE
    if _SERVICE is None:
        from googleapiclient.discovery import build

        _SERVICE = build("calendar", "v3", credentials=_load_credentials(), cache_discovery=False)
    return _SERVICE


def _call(request: Any) -> Any:
    """Run one API request, translating Google errors into CalendarError."""
    global _SERVICE
    try:
        return request.execute()
    except CalendarError:
        raise
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status in (401, 403):
            _SERVICE = None
            raise CalendarNotConnected(f"O Google recusou o acesso à agenda ({status}). {LOGIN_HINT}") from exc
        if status == 404:
            raise CalendarError("Esse evento não existe mais na agenda.") from exc
        if exc.__class__.__name__ == "RefreshError":
            _SERVICE = None
            raise CalendarNotConnected(f"O acesso ao Google Agenda expirou ou foi revogado. {LOGIN_HINT}") from exc
        logger.warning("Falha na API do Google Agenda.", exc_info=True)
        raise CalendarError("Não consegui falar com o Google Agenda agora (sem internet?).") from exc


def list_events(start: dt.datetime, end: dt.datetime) -> list[Evento]:
    """Eventos que acontecem entre start e end, em ordem de início."""
    response = _call(
        get_service()
        .events()
        .list(
            calendarId=CALENDAR_ID,
            timeMin=start.astimezone(TZ).isoformat(),
            timeMax=end.astimezone(TZ).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
            timeZone=TZ_NAME,
        )
    )
    events = [event for event in map(event_from_api, response.get("items") or []) if event is not None]
    return sorted(events, key=lambda event: (not event.all_day, event.start))


def _day_bounds(date: dt.date, days: int = 1) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(date, dt.time(), tzinfo=TZ)
    return start, dt.datetime.combine(date + dt.timedelta(days=days), dt.time(), tzinfo=TZ)


def _event_body(title: str, start: dt.datetime | None, end: dt.datetime | None, all_day_date: dt.date | None, location: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"summary": title}
    if location:
        body["location"] = location
    if all_day_date is not None:
        body["start"] = {"date": all_day_date.isoformat()}
        body["end"] = {"date": (all_day_date + dt.timedelta(days=1)).isoformat()}
    else:
        assert start is not None and end is not None
        body["start"] = {"dateTime": start.isoformat(), "timeZone": TZ_NAME}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": TZ_NAME}
    return body


def insert_event(body: dict[str, Any]) -> Evento | None:
    created = _call(get_service().events().insert(calendarId=CALENDAR_ID, body=body))
    return event_from_api(created)


def patch_event(event_id: str, body: dict[str, Any]) -> Evento | None:
    updated = _call(get_service().events().patch(calendarId=CALENDAR_ID, eventId=event_id, body=body))
    return event_from_api(updated)


def delete_event(event_id: str) -> None:
    _call(get_service().events().delete(calendarId=CALENDAR_ID, eventId=event_id))


# ───────────────────────── API pública (rotinas, avisos) ─────────────────────────


def eventos_do_dia(dia: dt.date, *, dias: int = 1) -> list[Evento]:
    """Eventos de um dia (ou de ``dias`` dias a partir dele). Levanta CalendarError."""
    return list_events(*_day_bounds(dia, dias))


def eventos_de_hoje(now: dt.datetime | None = None) -> list[Evento]:
    """Eventos de hoje no fuso de São Paulo. Levanta CalendarError (ex.: login não feito)."""
    return eventos_do_dia((now or agora()).astimezone(TZ).date())


def proximo_evento(now: dt.datetime | None = None, *, dias: int = MAX_LIST_DAYS) -> Evento | None:
    """O próximo evento com horário que ainda não começou (ignora os de dia inteiro)."""
    now = (now or agora()).astimezone(TZ)
    for event in sorted(list_events(now, now + dt.timedelta(days=dias)), key=lambda event: event.start):
        if not event.all_day and event.start >= now:
            return event
    return None


def resumo_do_dia(dia: dt.date | None = None, now: dt.datetime | None = None) -> str:
    """Uma frase com a agenda do dia, pronta para o "bom dia" das rotinas. Nunca levanta erro."""
    now = (now or agora()).astimezone(TZ)
    dia = dia or now.date()
    try:
        events = eventos_do_dia(dia)
    except CalendarError as exc:
        return str(exc)
    return format_day(dia, events, now)


def format_day(date: dt.date, events: list[Evento], now: dt.datetime) -> str:
    label = day_label(date, now.date())
    if not events:
        return f"Agenda de {label}: nada marcado."
    count = len(events)
    lines = [f"Agenda de {label}: {count} {'compromisso' if count == 1 else 'compromissos'}."]
    lines.extend(f"- {event.describe(now.date())}" for event in events)
    return "\n".join(lines)


# ───────────────────────── achar um evento falado ─────────────────────────


def _words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", _plain(text)) if word not in MATCH_STOPWORDS and not word.isdigit()]


def _same_word(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def match_events(query: str, events: list[Evento], now: dt.datetime) -> list[Evento]:
    """Events that "a reunião das 10", "dentista" or "daily de sexta" point to (best first).

    A time in the query must match the start; title words then pick among them. Without a time,
    at least one word of the title has to match.
    """
    plain = _spoken_numbers(_plain(query))
    time, rest = _parse_time(plain)
    if time is None:
        bare = re.search(r"\b(?:das|da|de)\s+(\d{1,2})\b", plain)
        if bare and int(bare.group(1)) <= 23:
            hour = int(bare.group(1))
            time = dt.time(hour + 12 if 1 <= hour <= 6 else hour, 0)
            rest = plain[: bare.start()] + plain[bare.end() :]
    words = _words(rest)

    def time_ok(event: Evento) -> bool:
        if time is None:
            return True
        if event.all_day:
            return False
        return (event.start.hour, event.start.minute) == (time.hour, time.minute)

    def score(event: Evento) -> int:
        title = _words(event.title)
        return sum(1 for word in words if any(_same_word(word, other) for other in title))

    candidates = [event for event in events if time_ok(event)]
    scored = [(score(event), event) for event in candidates]
    if time is None:
        scored = [(points, event) for points, event in scored if points > 0]
    if not scored:
        return []
    best = max(points for points, _ in scored)
    found = [event for points, event in scored if points == best]
    # Sem dia citado, fica o primeiro dia com algo que combina.
    first_day = min(event.start.date() for event in found)
    return sorted((event for event in found if event.start.date() == first_day), key=lambda event: event.start)


def find_events(query: str, day: str | None, now: dt.datetime) -> list[Evento]:
    when = parse_when(day, now) if day else None
    if when is None:
        in_query = parse_when(query, now)
        when = in_query if in_query is not None and in_query.explicit_date else None
    if when is not None:
        events = eventos_do_dia(when.date)
    else:
        start, _ = _day_bounds(now.date())
        events = [event for event in list_events(start, start + dt.timedelta(days=SEARCH_DAYS)) if event.end > now]
    return match_events(query, events, now)


# ───────────────────────── HUD ─────────────────────────


def agenda_card(
    status: str,
    date: dt.date,
    events: list[Evento],
    now: dt.datetime,
    *,
    days: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    label = day_label(date, now.date())
    if days > 1:
        end = date + dt.timedelta(days=days - 1)
        label = f"{label} até {day_label(end, now.date())}"
    return {"status": status, "label": label, "date": date.isoformat(), "events": [e.to_card() for e in events], **extra}


async def _show_day(status: str, date: dt.date, now: dt.datetime, **extra: Any) -> None:
    """Re-read the day and show it on the HUD (after a change). Errors only skip the panel."""
    try:
        events = await asyncio.to_thread(eventos_do_dia, date)
    except CalendarError:
        events = []
    await show_card("calendar", agenda_card(status, date, events, now, **extra))


# ───────────────────────── ferramentas de voz ─────────────────────────


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()[:MAX_TITLE]


def _pending_text(pending: dict[str, Any]) -> str:
    action = {"create": "Criar", "update": "Alterar", "delete": "Apagar"}[pending["action"]]
    return f"{action}: {pending['summary']}"


def _confirmation_lines(code: str) -> list[str]:
    return [
        f"Código de confirmação: {code} (fale dígito por dígito: {spoken_digits(code)}). "
        "O código também aparece no painel Agenda do HUD.",
        f"Para gravar, o usuário precisa dizer: {confirmation_phrase('calendar', code)}. "
        "'Pode marcar', 'sim' ou 'confirma' sem o código não bastam: nesse caso repita o código e a frase.",
    ]


def _describe_slot(start: dt.datetime | None, end: dt.datetime | None, all_day_date: dt.date | None, today: dt.date) -> str:
    if all_day_date is not None:
        return f"{day_label(all_day_date, today)}, dia inteiro"
    assert start is not None and end is not None
    return f"{day_label(start.date(), today)}, {_hhmm(start)}–{_hhmm(end)}"


def _store_pending(context: RunContext, pending: dict[str, Any]) -> str:
    code = new_code()
    session_state(context)[PENDING_CALENDAR_KEY] = {**pending, "code": code}
    return code


def _ask_which(events: list[Evento], today: dt.date) -> str:
    lines = [f"- {event.describe(today, with_day=True)}" for event in events[:6]]
    return (
        "Mais de um evento combina; pergunte ao usuário qual (pelo horário ou título):\n"
        + "\n".join(lines)
        + "\nNada foi alterado."
    )


def _pick_event(query: str, day: str | None, now: dt.datetime) -> tuple[Evento | None, str | None]:
    events = find_events(query, day, now)
    if not events:
        where = f" em {day}" if day else " de hoje até a próxima semana"
        return None, f"Não achei nenhum evento que combine com '{query}'{where}. Nada foi alterado."
    if len(events) > 1:
        return None, _ask_which(events, now.date())
    return events[0], None


@function_tool()
async def get_agenda(context: RunContext, day: str = "hoje", days: int = 1) -> str:
    """Read the user's Google Calendar for a day: "o que eu tenho hoje?", "e amanhã?", "e sexta?".

    Shows the day on the HUD Agenda panel. Reading never needs confirmation.

    Args:
        day: The day as the user said it, in Portuguese: "hoje", "amanhã", "sexta",
            "depois de amanhã", "dia 25", "25/10" or an ISO date.
        days: How many days to list starting at `day` (1 = only that day; "essa semana" = 7).
    """
    now = agora()
    when = parse_when(day, now)
    if when is None:
        return f"Não entendi o dia '{day}'. Peça de novo (ex.: hoje, amanhã, sexta, dia 25)."
    days = max(1, min(int(days or 1), MAX_LIST_DAYS))
    await tool_status("get_agenda", "running", day)
    try:
        events = await asyncio.to_thread(eventos_do_dia, when.date, dias=days)
    except CalendarError as exc:
        await tool_status("get_agenda", "error", str(exc)[:60])
        return str(exc)
    await show_card("calendar", agenda_card("agenda", when.date, events, now, days=days))
    await tool_status("get_agenda", "done", day)
    if days == 1:
        text = format_day(when.date, events, now)
    else:
        label = f"{day_label(when.date, now.date())} e os {days - 1} dias seguintes"
        listed = [f"- {event.describe(now.date(), with_day=True)}" for event in events]
        text = f"Agenda de {label}: " + (f"{len(events)} compromissos.\n" + "\n".join(listed) if events else "nada marcado.")
    return text + "\nResuma em voz (horário e título); a lista completa está no painel Agenda."


@function_tool()
async def next_meeting(context: RunContext) -> str:
    """Tell the user's next event with a time ("qual minha próxima reunião?", "o que vem agora?")."""
    now = agora()
    await tool_status("next_meeting", "running")
    try:
        event = await asyncio.to_thread(proximo_evento, now)
    except CalendarError as exc:
        await tool_status("next_meeting", "error", str(exc)[:60])
        return str(exc)
    await tool_status("next_meeting", "done")
    if event is None:
        return f"Nenhum evento com horário nos próximos {MAX_LIST_DAYS} dias."
    await _show_day("agenda", event.start.date(), now, highlight=event.id)
    lines = [f"Próximo: {event.describe(now.date(), with_day=True)} — começa {_until(event.start, now)}."]
    if event.meeting_link:
        lines.append(f"Tem link de videochamada ({event.meeting_link}); ofereça abrir, sem ler a URL.")
    return "\n".join(lines)


@function_tool()
async def prepare_calendar_event(
    context: RunContext,
    title: str,
    when: str,
    duration_minutes: int = DEFAULT_DURATION_MIN,
    all_day: bool = False,
    location: str | None = None,
) -> str:
    """Prepare a new Google Calendar event ("marca dentista sexta às 15h"). Does NOT save yet.

    It creates a 6-digit code. Tell the user the day, time and code digit by digit, and that to
    save they must say "confirmar agenda" + the code.

    Args:
        title: Event title, e.g. "Dentista".
        when: Day and time as the user said, in Portuguese: "sexta às 15h",
            "depois de amanhã às 9", "dia 25 às 14h30", or an ISO date-time.
        duration_minutes: Length in minutes (default 60).
        all_day: True for an all-day event (birthdays, trips); then `when` only needs the day.
        location: Optional place or meeting link.
    """
    now = agora()
    clean = _clean_title(title)
    if not clean:
        return "Falta o título do evento. Pergunte ao usuário o que marcar."
    parsed = parse_when(when, now)
    if parsed is None:
        return f"Não entendi a data '{when}'. Pergunte o dia e o horário (ex.: sexta às 15h)."
    start = end = None
    all_day_date = None
    if all_day:
        all_day_date = parsed.date
    else:
        start = parsed.start()
        if start is None:
            return (
                f"Entendi o dia ({day_label(parsed.date, now.date())}), mas não o horário. Pergunte que "
                "horas, ou se é o dia inteiro (all_day=true). Nada foi marcado."
            )
        if start < now and not parsed.explicit_date:
            start += dt.timedelta(days=1)  # "às 9" depois das 9 = amanhã
        if start < now - dt.timedelta(minutes=5):
            return f"{day_label(start.date(), now.date())} às {_hhmm(start)} já passou. Confirme a data com o usuário."
        minutes = max(5, min(int(duration_minutes or DEFAULT_DURATION_MIN), MAX_DURATION_MIN))
        end = start + dt.timedelta(minutes=minutes)

    slot = _describe_slot(start, end, all_day_date, now.date())
    place = (location or "").strip()[:200] or None
    try:
        conflicts = [] if all_day else await asyncio.to_thread(list_events, start, end)
    except CalendarError as exc:
        return str(exc)
    target = all_day_date or start.date()
    code = _store_pending(
        context,
        {
            "action": "create",
            "summary": f"{clean} — {slot}",
            "body": _event_body(clean, start, end, all_day_date, place),
            "date": target.isoformat(),
        },
    )
    conflicts = [event for event in conflicts if not event.all_day]
    await _show_day(
        "pending",
        target,
        now,
        action="create",
        code=code,
        pending={"title": clean, "when": slot, "location": place},
    )
    lines = [f"Evento preparado (ainda NÃO gravado): {clean} — {slot}" + (f", em {place}" if place else "") + "."]
    if conflicts:
        lines.append("Atenção, conflita com: " + "; ".join(event.describe(now.date()) for event in conflicts) + ".")
    lines.extend(_confirmation_lines(code))
    return "\n".join(lines)


@function_tool()
async def prepare_calendar_update(
    context: RunContext,
    event: str,
    day: str | None = None,
    new_when: str | None = None,
    new_title: str | None = None,
    new_duration_minutes: int | None = None,
) -> str:
    """Prepare moving/renaming an existing event ("passa o dentista para as 16h"). Does NOT save yet.

    Args:
        event: How the user referred to it: title words and/or its time ("dentista",
            "a reunião das 10").
        day: The event's current day if the user said it ("amanhã", "sexta"); omit otherwise.
        new_when: New day and/or time in Portuguese ("16h", "sexta às 9"); a time alone keeps the day.
        new_title: New title, if renaming.
        new_duration_minutes: New length in minutes; omitted keeps the current length.
    """
    now = agora()
    if not (new_when or new_title or new_duration_minutes):
        return "Diga o que mudar: horário, dia, título ou duração. Nada foi alterado."
    try:
        found, problem = await asyncio.to_thread(_pick_event, event, day, now)
    except CalendarError as exc:
        return str(exc)
    if found is None:
        return problem or "Nada foi alterado."

    title = _clean_title(new_title) if new_title else found.title
    duration = found.end - found.start
    if new_duration_minutes:
        duration = dt.timedelta(minutes=max(5, min(int(new_duration_minutes), MAX_DURATION_MIN)))
    start, all_day_date = found.start, found.start.date() if found.all_day else None
    if new_when:
        parsed = parse_when(new_when, now)
        if parsed is None:
            return f"Não entendi '{new_when}'. Pergunte o novo dia/horário. Nada foi alterado."
        date = parsed.date if parsed.explicit_date else found.start.date()
        if parsed.time is not None:
            start, all_day_date = dt.datetime.combine(date, parsed.time, tzinfo=TZ), None
            if found.all_day and not new_duration_minutes:
                duration = dt.timedelta(minutes=DEFAULT_DURATION_MIN)
        elif found.all_day:
            all_day_date = date
        else:
            start = dt.datetime.combine(date, found.start.timetz())
    end = None if all_day_date else start + duration
    slot = _describe_slot(None if all_day_date else start, end, all_day_date, now.date())
    body = _event_body(title, None if all_day_date else start, end, all_day_date, None)
    if found.all_day != (all_day_date is not None):
        # Trocar entre dia inteiro e horário: o patch precisa apagar o campo antigo.
        for key in ("start", "end"):
            body[key].update({"dateTime": None, "timeZone": None} if all_day_date else {"date": None})
    before = found.describe(now.date(), with_day=True)
    code = _store_pending(
        context,
        {
            "action": "update",
            "event_id": found.id,
            "summary": f"{before} → {title} — {slot}",
            "body": body,
            "date": (all_day_date or start.date()).isoformat(),
        },
    )
    await _show_day(
        "pending",
        all_day_date or start.date(),
        now,
        action="update",
        code=code,
        highlight=found.id,
        pending={"title": title, "when": slot, "before": before},
    )
    return "\n".join(
        [f"Alteração preparada (ainda NÃO gravada): de {before} para {title} — {slot}."] + _confirmation_lines(code)
    )


@function_tool()
async def prepare_calendar_delete(context: RunContext, event: str, day: str | None = None) -> str:
    """Prepare deleting/cancelling an event ("desmarca a reunião das 10"). Does NOT delete yet.

    Args:
        event: How the user referred to it: title words and/or its time ("dentista",
            "a reunião das 10").
        day: The event's day if the user said it ("amanhã", "sexta"); omit otherwise.
    """
    now = agora()
    try:
        found, problem = await asyncio.to_thread(_pick_event, event, day, now)
    except CalendarError as exc:
        return str(exc)
    if found is None:
        return problem or "Nada foi apagado."
    before = found.describe(now.date(), with_day=True)
    code = _store_pending(
        context,
        {"action": "delete", "event_id": found.id, "summary": before, "date": found.start.date().isoformat()},
    )
    await _show_day(
        "pending",
        found.start.date(),
        now,
        action="delete",
        code=code,
        highlight=found.id,
        pending={"title": found.title, "when": before},
    )
    return "\n".join([f"Exclusão preparada (ainda NÃO apagado): {before}."] + _confirmation_lines(code))


@function_tool()
async def confirm_calendar_change(context: RunContext, code: str) -> str:
    """Save the prepared calendar change, only after the user said "confirmar agenda <código>".

    Args:
        code: The 6-digit confirmation code the user said.
    """
    state = session_state(context)
    pending = state.get(PENDING_CALENDAR_KEY)
    if not pending:
        return "Não há nenhuma mudança de agenda pendente."
    expected = pending["code"]
    if normalize_code(code) != expected:
        logger.warning("Confirmação de agenda rejeitada por código inválido.")
        return "Código de confirmação inválido. Nada foi alterado na agenda."
    confirmed, _ = await wait_for_user_confirmation(context, "calendar", expected)
    if not confirmed:
        logger.warning("Confirmação de agenda rejeitada: a última fala não tinha a frase com o código.")
        return (
            "Bloqueado: a última fala do usuário não foi a confirmação com o código. "
            f"Repita o código ({spoken_digits(expected)}) e peça para ele dizer: "
            f"{confirmation_phrase('calendar', expected)}."
        )

    action = pending["action"]
    await tool_status("confirm_calendar_change", "running", pending["summary"][:60])
    try:
        if action == "create":
            saved = await asyncio.to_thread(insert_event, pending["body"])
        elif action == "update":
            saved = await asyncio.to_thread(patch_event, pending["event_id"], pending["body"])
        else:
            saved = None
            await asyncio.to_thread(delete_event, pending["event_id"])
    except CalendarError as exc:
        await tool_status("confirm_calendar_change", "error", str(exc)[:60])
        return f"Falhou, nada mudou na agenda: {exc}"
    state[PENDING_CALENDAR_KEY] = None
    status = {"create": "created", "update": "updated", "delete": "deleted"}[action]
    await _show_day(
        status,
        dt.date.fromisoformat(pending["date"]),
        agora(),
        action=action,
        highlight=saved.id if saved else None,
        message=_pending_text(pending),
    )
    await tool_status("confirm_calendar_change", "done", pending["summary"][:60])
    logger.info("Agenda: %s confirmado.", action)
    done = {"create": "Evento criado", "update": "Evento alterado", "delete": "Evento apagado"}[action]
    return f"{done} no Google Agenda: {pending['summary']}."


@function_tool()
async def cancel_calendar_change(context: RunContext) -> str:
    """Cancel the prepared (not yet confirmed) calendar change."""
    state = session_state(context)
    pending = state.get(PENDING_CALENDAR_KEY)
    if not pending:
        return "Não há nenhuma mudança de agenda pendente para cancelar."
    state[PENDING_CALENDAR_KEY] = None
    await show_card(
        "calendar",
        {
            "status": "cancelled",
            "label": "mudança cancelada",
            "date": pending["date"],
            "events": [],
            "action": pending["action"],
            "message": _pending_text(pending),
        },
    )
    return "Mudança na agenda cancelada; nada foi gravado."


def build_calendar_tools() -> list[Any]:
    return [
        get_agenda,
        next_meeting,
        prepare_calendar_event,
        prepare_calendar_update,
        prepare_calendar_delete,
        confirm_calendar_change,
        cancel_calendar_change,
    ]


# ───────────────────────── aviso antes das reuniões ─────────────────────────


@dataclass
class ReminderWatcher:
    """Decide which events deserve a "sua reunião começa em 10 minutos" (each one only once).

    ``check()`` busca na agenda e devolve os eventos que entraram na janela de aviso; o servidor
    do HUD usa isso para acordar o Jarvis, e outros módulos (avisos proativos) podem usar igual.
    """

    lead_minutes: int = DEFAULT_REMINDER_MIN
    fetch: Callable[[dt.datetime, dt.datetime], list[Evento]] = list_events
    announced: dict[tuple[str, str], dt.datetime] = field(default_factory=dict)

    def due(self, events: list[Evento], now: dt.datetime) -> list[Evento]:
        lead = dt.timedelta(minutes=self.lead_minutes)
        due = []
        for event in events:
            key = (event.id, event.start.isoformat())
            if event.all_day or key in self.announced:
                continue
            if event.start - lead <= now < event.start:
                self.announced[key] = event.start
                due.append(event)
        stale = now - dt.timedelta(days=1)
        self.announced = {key: start for key, start in self.announced.items() if start > stale}
        return due

    def check(self, now: dt.datetime | None = None) -> list[Evento]:
        now = (now or agora()).astimezone(TZ)
        events = self.fetch(now, now + dt.timedelta(minutes=self.lead_minutes + 2))
        return self.due(events, now)


def reminder_payload(event: Evento) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "start": event.start.isoformat(),
        "location": event.location,
        "link": event.meeting_link,
    }


def reminder_instruction(reminders: list[dict[str, Any]], now: dt.datetime | None = None) -> str:
    """What Jarvis is told to say when the HUD server hands over due reminders."""
    now = (now or agora()).astimezone(TZ)
    parts = []
    for item in reminders:
        start = dt.datetime.fromisoformat(item["start"]).astimezone(TZ)
        text = f"'{item['title']}' às {_hhmm(start)} (começa {_until(start, now)})"
        if item.get("link"):
            text += " — tem link de videochamada; ofereça abrir (open_website), sem ler a URL"
        parts.append(text)
    return (
        "Aviso da agenda (não foi o usuário que pediu): avise agora, numa frase curta e elegante, "
        "sobre " + "; ".join(parts) + ". Não chame ferramentas para isso."
    )


async def run_reminder_loop(
    settings_fn: Callable[[], Any],
    on_due: Callable[[list[Evento]], Awaitable[None] | None],
    *,
    interval: float = 60.0,
    clock: Callable[[], dt.datetime] = agora,
    watcher: ReminderWatcher | None = None,
) -> None:
    """Every minute, hand events about to start to ``on_due``. Runs until cancelled.

    Re-reads the settings each round: JARVIS_ENABLE_CALENDAR=false, lead time 0 or no login
    just skip the round.
    """
    watcher = watcher or ReminderWatcher()
    while True:
        try:
            settings = settings_fn()
            enabled = settings.calendar_enabled and settings.calendar_reminder_minutes > 0 and is_connected()
            if enabled:
                watcher.lead_minutes = settings.calendar_reminder_minutes
                due = await asyncio.to_thread(watcher.check, clock())
                if due:
                    result = on_due(due)
                    if asyncio.iscoroutine(result):
                        await result
        except asyncio.CancelledError:
            raise
        except CalendarError as exc:
            logger.info("Aviso de reuniões pausado: %s", exc)
        except Exception:
            logger.warning("Falha ao checar a agenda para avisos.", exc_info=True)
        await asyncio.sleep(interval)


def start_reminder_relay(session: Any, hud_url: str, *, interval: float = 15.0) -> asyncio.Task[None]:
    """Agent side: pick up reminders the HUD server queued and have Jarvis speak them."""
    import requests

    def claim() -> list[dict[str, Any]]:
        response = requests.post(f"{hud_url}/api/calendar/reminders/claim", timeout=5)
        response.raise_for_status()
        return response.json().get("reminders") or []

    async def relay() -> None:
        while True:
            try:
                reminders = await asyncio.to_thread(claim)
                if reminders:
                    session.generate_reply(instructions=reminder_instruction(reminders))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Não consegui buscar avisos da agenda no servidor do HUD.", exc_info=True)
            await asyncio.sleep(interval)

    task = asyncio.create_task(relay())
    try:
        session.on("close", lambda *_: task.cancel())
    except Exception:
        pass
    return task


# ───────────────────────── login pela linha de comando ─────────────────────────

SETUP_STEPS = """\
Falta o arquivo google_credentials.json nesta pasta. Para criá-lo (uma vez só):
  1. https://console.cloud.google.com/ → crie um projeto (ex.: Jarvis).
  2. APIs e serviços → Biblioteca → "Google Calendar API" → Ativar.
  3. Tela de consentimento OAuth → Externo → preencha nome e email → em "Usuários de teste"
     adicione o seu Gmail.
  4. Credenciais → Criar credenciais → ID do cliente OAuth → tipo "App para computador".
  5. Baixe o JSON e salve como google_credentials.json ao lado do jarvis.py.
Depois rode de novo: python calendar_tools.py --login"""


def login() -> int:
    if not CREDENTIALS_FILE.exists():
        print(SETUP_STEPS)
        return 1
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    print("Abrindo o navegador para você autorizar o Jarvis no Google Agenda...")
    credentials = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    _save_token(credentials)
    print(f"Pronto! Token salvo em {TOKEN_FILE.name} (fica só neste computador, fora do git).")
    return print_today()


def logout() -> int:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        print("Token apagado: o Jarvis não acessa mais o Google Agenda deste computador.")
    else:
        print("Nenhum token salvo.")
    print("Para revogar no Google também: https://myaccount.google.com/permissions")
    return 0


def print_today() -> int:
    try:
        print(format_day(agora().date(), eventos_de_hoje(), agora()))
    except CalendarError as exc:
        print(f"Erro: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Google Agenda do Jarvis (AGD-27).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--login", action="store_true", help="autoriza o Jarvis no navegador e salva o token")
    group.add_argument("--logout", action="store_true", help="apaga o token salvo")
    group.add_argument("--hoje", action="store_true", help="mostra a agenda de hoje (teste da conexão)")
    args = parser.parse_args(argv)
    if args.login:
        return login()
    if args.logout:
        return logout()
    return print_today()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
