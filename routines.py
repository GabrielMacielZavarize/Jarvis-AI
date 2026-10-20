"""Rotinas do Jarvis (ROT-24): um comando roda várias ferramentas em sequência.

"Bom dia, Jarvis" cumprimenta pelo horário, diz o clima, as manchetes e os lembretes, aplica o
layout "trabalho" e toca uma playlist; "modo foco", "modo jogo" e "boa noite" fazem o mesmo com
outros passos. As rotinas ficam em ``rotinas.json`` (fora do git) e o usuário cria e edita as
suas por voz ("cria uma rotina estudo que abre o Notion e põe lo-fi").

Cada passo é uma linha ``ação: argumento`` ("app: Notion", "youtube: lo-fi", "timer: 25 Pomodoro")
que chama uma ferramenta que já existe. Os passos rodam um de cada vez, aparecem no painel
Rotina do HUD e um passo que falha não derruba os outros: o relatório diz o que falhou.

Segurança:
- Só ações da lista ``ACTIONS`` entram numa rotina; email, instalação de apps e mouse/teclado
  nunca, porque têm a própria confirmação por código.
- Passos perigosos (bloquear o PC, fechar um app) nunca rodam sozinhos: ficam para o fim e só
  acontecem com ``confirm_routine_step`` depois de um "sim" na ÚLTIMA fala do próprio usuário.
- Criar, mudar, apagar ou agendar uma rotina exige que a última fala do usuário fale em rotina
  ou cite o nome dela: texto de páginas, emails ou da tela não planta rotinas.

Agendamento ("todo dia útil às 8h roda o bom dia"): o ``RoutineScheduler`` roda no processo do
servidor do HUD (``server.py``). Na hora, ele guarda a rotina como pendente e abre o link pela
mesma via da palavra de ativação (``wake_hub.py``); o agente, ao começar a sessão ou durante
uma conversa já aberta, pega a pendente em ``POST /api/routines/claim`` e o Jarvis fala o resultado.

Gatilhos por contexto ("quando eu abrir o PhpStorm, roda o modo foco") ficam em ``context_triggers.py``
e entregam a rotina pelo mesmo caminho, com ``RoutineScheduler.fire``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import importlib
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from livekit.agents import RunContext, function_tool

from confirmation import CONFIRMATION_POLL_SECONDS, CONFIRMATION_WAIT_SECONDS, last_user_message, session_state, speech_tokens, strip_accents
from hud import show_card, tool_status
from settings import Settings, load_settings

logger = logging.getLogger("jarvis-routines")

ROUTINES_FILE = Path(__file__).resolve().parent / "rotinas.json"
FILE_VERSION = 1
MAX_ROUTINES = 30
MAX_STEPS = 12
MAX_NAME_CHARS = 40
MAX_ARG_CHARS = 120
MAX_ALIASES = 6
# Um passo travado (rede, app que não abre) não segura a rotina inteira.
STEP_TIMEOUT_S = 60.0
# Quanto do resultado de cada passo vai para o relatório que o Jarvis fala.
REPORT_STEP_CHARS = 600
# Passos perigosos esperando o "sim" do usuário.
PENDING_KEY = "routine_pending"
PENDING_CONFIRM_S = 180.0
# Agendamento: atraso aceito (PC saindo da suspensão às 8h05 ainda roda o "bom dia" das 8h).
CATCH_UP = dt.timedelta(minutes=10)
SCHEDULER_TICK_S = 20.0
# Tempo para o link abrir e o agente pegar a rotina pendente (navegador recém-aberto incluso).
PENDING_ROUTINE_S = 180.0
# Durante uma conversa aberta, o agente confere a cada tanto se uma rotina agendada venceu.
AGENT_POLL_S = 15.0
CLAIM_PATH = "/api/routines/claim"

StepStatus = Literal["pending", "running", "ok", "error", "skipped", "confirm", "cancelled"]


class RoutineError(ValueError):
    """A routine or step that cannot be saved or found (the message is spoken to the user)."""


# ───────────────────────── ações ─────────────────────────


@dataclass(frozen=True, slots=True)
class Action:
    label: str
    # base: ferramentas de sempre; pc: JARVIS_ENABLE_PC_CONTROL; memory: JARVIS_ENABLE_MEMORY.
    needs: Literal["base", "pc", "memory"] = "base"
    needs_arg: bool = False
    dangerous: bool = False
    example: str = ""


ACTIONS: dict[str, Action] = {
    "greet": Action("Cumprimento", example="greet"),
    "weather": Action("Clima", example="weather (cidade padrão) ou weather: Lisboa"),
    "news": Action("Notícias", example="news: tecnologia"),
    "reminders": Action("Lembretes", needs="memory", example="reminders"),
    "time": Action("Horário", example="time"),
    "timer": Action("Timer", needs_arg=True, example="timer: 25 Pomodoro"),
    "note": Action("Nota no HUD", needs_arg=True, example="note: Foco | Sem redes sociais"),
    "layout": Action("Layout", needs="pc", needs_arg=True, example="layout: trabalho"),
    "save_layout": Action("Salvar layout", needs="pc", needs_arg=True, example="save_layout: noite"),
    "youtube": Action("YouTube", needs="pc", needs_arg=True, example="youtube: lo-fi para estudar"),
    "spotify": Action("Spotify", needs="pc", needs_arg=True, example="spotify: Daft Punk"),
    "stream": Action("Streaming", needs="pc", needs_arg=True, example="stream: Netflix"),
    "site": Action("Site", needs="pc", needs_arg=True, example="site: notion.so"),
    "app": Action("Abrir app", needs="pc", needs_arg=True, example="app: Notion"),
    "folder": Action("Pasta", needs="pc", needs_arg=True, example="folder: Downloads"),
    "volume": Action("Volume", needs="pc", needs_arg=True, example="volume: 20 (ou mute/unmute)"),
    "media": Action("Mídia", needs="pc", needs_arg=True, example="media: stop (play_pause/next/previous)"),
    "minimize": Action("Minimizar janelas", needs="pc", example="minimize"),
    "close": Action("Fechar app", needs="pc", needs_arg=True, dangerous=True, example="close: Discord"),
    "lock": Action("Bloquear o PC", needs="pc", dangerous=True, example="lock"),
}
# O que o modelo (ou o usuário editando o arquivo) escreve em português.
ACTION_ALIASES = {
    "cumprimento": "greet",
    "cumprimentar": "greet",
    "saudacao": "greet",
    "clima": "weather",
    "tempo": "weather",
    "previsao": "weather",
    "noticias": "news",
    "manchetes": "news",
    "lembretes": "reminders",
    "memoria": "reminders",
    "hora": "time",
    "horario": "time",
    "pomodoro": "timer",
    "temporizador": "timer",
    "nota": "note",
    "painel": "note",
    "aplicar_layout": "layout",
    "salvar_layout": "save_layout",
    "musica": "youtube",
    "playlist": "youtube",
    "video": "youtube",
    "streaming": "stream",
    "abrir_site": "site",
    "abrir": "app",
    "abrir_app": "app",
    "pasta": "folder",
    "som": "volume",
    "midia": "media",
    "minimizar": "minimize",
    "area_de_trabalho": "minimize",
    "fechar": "close",
    "fechar_app": "close",
    "bloquear": "lock",
    "bloquear_pc": "lock",
}
MEDIA_ACTIONS = {
    "stop": "stop",
    "parar": "stop",
    "pausar": "stop",
    "pause": "stop",
    "pausa": "stop",
    "play_pause": "play_pause",
    "play": "play_pause",
    "tocar": "play_pause",
    "retomar": "play_pause",
    "next": "next",
    "proxima": "next",
    "previous": "previous",
    "anterior": "previous",
}
VOLUME_WORDS = {"mute": "mute", "mudo": "mute", "silenciar": "mute", "unmute": "unmute", "desmutar": "unmute",
                "up": "up", "aumentar": "up", "down": "down", "baixar": "down", "diminuir": "down"}
DEFAULT_NEWS_TOPIC = "principais notícias do Brasil hoje"

# Uma resposta de ferramenta que começa assim é uma falha (as ferramentas devolvem texto, não exceções).
FAILURE_START = re.compile(
    r"^(?:nao (?!ha janelas)|nada |ocorreu |erro|falha|algo deu errado|diga |so abro|isso nao |por seguranca|"
    r"o windows nao|a duracao|cidade .* nao encontrada|o servico de clima|acao .*desconhecida|"
    r"nenhum|o hud nao esta)"
)
FAILURE_ANYWHERE = re.compile(r"so esta disponivel no windows|precisa estar ligado")


@dataclass(frozen=True, slots=True)
class Step:
    action: str
    arg: str = ""

    @property
    def raw(self) -> str:
        return f"{self.action}: {self.arg}" if self.arg else self.action

    @property
    def dangerous(self) -> bool:
        return ACTIONS[self.action].dangerous

    def label(self, settings: Settings | None = None) -> str:
        base = ACTIONS[self.action].label
        if self.action == "weather":
            city = self.arg or (settings.home_city if settings else None)
            return f"{base} em {city}" if city else base
        if self.action == "timer":
            minutes, label = parse_timer(self.arg)
            return f"Timer {minutes:g} min · {label}" if label else f"Timer {minutes:g} min"
        if self.action == "note":
            return f"{base} · {self.arg.split('|', 1)[0].strip()}"
        if self.action == "volume":
            return f"Volume {self.arg}%" if self.arg.isdigit() else f"Volume · {self.arg}"
        if self.action in {"news", "layout", "save_layout", "youtube", "spotify", "stream", "site", "app", "folder", "close"}:
            return f"{base} · {self.arg or DEFAULT_NEWS_TOPIC}"
        if self.action == "media":
            return {"stop": "Pausar a mídia", "play_pause": "Tocar/pausar a mídia"}.get(self.arg, f"Mídia · {self.arg}")
        return base


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


def parse_step(raw: str) -> Step:
    """ "app: Notion" -> Step("app", "Notion"). Aceita os nomes em português ("abrir: Notion")."""
    text = re.sub(r"\s+", " ", str(raw)).strip()
    if not text:
        raise RoutineError("Um dos passos está vazio.")
    head, sep, arg = text.partition(":")
    if not sep:
        head, _, arg = text.partition(" ")
    key = re.sub(r"[\s-]+", "_", _plain(head))
    action = key if key in ACTIONS else ACTION_ALIASES.get(key)
    if action is None:
        options = ", ".join(ACTIONS)
        raise RoutineError(f"Não sei fazer o passo '{text}' numa rotina. Ações possíveis: {options}.")
    arg = arg.strip()[:MAX_ARG_CHARS]
    if action == "media":
        arg = MEDIA_ACTIONS.get(_plain(arg) or "stop", "")
        if not arg:
            raise RoutineError("No passo de mídia use stop (pausar), play_pause, next ou previous.")
    if action == "volume":
        arg = _volume_arg(arg)
    if action == "timer":
        parse_timer(arg)
    if ACTIONS[action].needs_arg and not arg:
        raise RoutineError(f"O passo '{action}' precisa de um argumento, por exemplo '{ACTIONS[action].example}'.")
    return Step(action, arg)


def _volume_arg(arg: str) -> str:
    plain = _plain(arg).rstrip("%").strip()
    if plain in VOLUME_WORDS:
        return VOLUME_WORDS[plain]
    match = re.search(r"\d{1,3}", plain)
    if match is None or int(match.group()) > 100:
        raise RoutineError("No passo de volume use um nível de 0 a 100, mute ou unmute.")
    return match.group()


def parse_timer(arg: str) -> tuple[float, str]:
    """ "25 Pomodoro" -> (25.0, "Pomodoro"); "1.5" -> (1.5, "")."""
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(?:min(?:utos?)?\b)?\s*(.*)$", arg or "")
    if match is None:
        raise RoutineError("No passo de timer diga os minutos, por exemplo 'timer: 25 Pomodoro'.")
    minutes = float(match.group(1).replace(",", "."))
    if not 0 < minutes <= 24 * 60:
        raise RoutineError("O timer de uma rotina precisa ter entre alguns segundos e 24 horas.")
    return minutes, match.group(2).strip()[:40]


# ───────────────────────── agenda ─────────────────────────

WEEKDAY_KEYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
WEEKDAY_NAMES = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
WEEKDAY_WORDS = {
    "segunda": 0, "seg": 0, "terca": 1, "ter": 1, "quarta": 2, "qua": 2, "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4, "sabado": 5, "sab": 5, "domingo": 6, "dom": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
WEEKDAYS = (0, 1, 2, 3, 4)
WEEKEND = (5, 6)
EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


def parse_days(text: str | None) -> tuple[int, ...]:
    """ "dias úteis" -> seg..sex; "todo dia" -> todos; "segunda, quarta e sexta" -> (0, 2, 4)."""
    plain = _plain(text or "todo dia")
    if re.search(r"\b(?:uteis|util|semana de trabalho|weekdays?)\b", plain) or plain in {"semana", "durante a semana"}:
        return WEEKDAYS
    if re.search(r"\b(?:fim de semana|fins de semana|final de semana|finais de semana|weekend)\b", plain):
        return WEEKEND
    if re.search(r"\b(?:todo dia|todos os dias|diariamente|todo santo dia|sempre|daily|every day)\b", plain):
        return EVERY_DAY
    days: set[int] = set()
    for word in re.findall(r"[a-z]+", plain):
        if word in WEEKDAY_WORDS:
            days.add(WEEKDAY_WORDS[word])
        elif word.rstrip("s") in WEEKDAY_WORDS:  # "segundas", "sextas"
            days.add(WEEKDAY_WORDS[word.rstrip("s")])
    range_match = re.search(r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)\b a \b(segunda|terca|quarta|quinta|sexta|sabado|domingo)\b", plain)
    if range_match:
        start, end = WEEKDAY_WORDS[range_match.group(1)], WEEKDAY_WORDS[range_match.group(2)]
        days.update(range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)])
    if not days:
        raise RoutineError(f"Não entendi os dias '{text}'. Diga 'todo dia', 'dias úteis', 'fim de semana' ou os dias da semana.")
    return tuple(sorted(days))


def parse_time(text: str | None) -> str:
    """ "8h" / "08:00" / "8h30" / "20 horas" / "8 e meia" -> "HH:MM"."""
    plain = _plain(text or "")
    match = re.search(r"(\d{1,2})\s*(?:h|:|horas?)?\s*(\d{2})?", plain)
    if match is None:
        raise RoutineError(f"Não entendi o horário '{text}'. Diga, por exemplo, '8h' ou '07:30'.")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if match.group(2) is None and re.search(r"\be meia\b", plain):
        minute = 30
    if re.search(r"\b(?:da tarde|da noite|pm)\b", plain) and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        raise RoutineError(f"O horário '{text}' não existe.")
    return f"{hour:02d}:{minute:02d}"


def describe_days(days: tuple[int, ...] | list[int]) -> str:
    days = tuple(sorted(set(days)))
    if days == EVERY_DAY:
        return "todo dia"
    if days == WEEKDAYS:
        return "dias úteis"
    if days == WEEKEND:
        return "fim de semana"
    names = [WEEKDAY_NAMES[day] for day in days]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]


def describe_schedule(schedule: dict[str, Any] | None) -> str | None:
    if not schedule:
        return None
    hour, minute = schedule["time"].split(":")
    return f"{describe_days(schedule['days'])} às {int(hour)}h{minute if minute != '00' else ''}"


def _valid_schedule(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        days = raw.get("days")
        if isinstance(days, str):
            parsed_days = parse_days(days)
        else:
            parsed_days = tuple(sorted({WEEKDAY_KEYS.index(d) if isinstance(d, str) else int(d) for d in days or ()}))
        if not parsed_days or any(not 0 <= day <= 6 for day in parsed_days):
            return None
        return {"days": list(parsed_days), "time": parse_time(str(raw.get("time", ""))), "enabled": raw.get("enabled", True) is not False}
    except (RoutineError, ValueError, TypeError):
        return None


def occurrence(schedule: dict[str, Any], now: dt.datetime) -> dt.datetime | None:
    """When today's run of this schedule is/was due, or None if it doesn't run today."""
    if not schedule.get("enabled", True) or now.weekday() not in schedule["days"]:
        return None
    hour, minute = (int(part) for part in schedule["time"].split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


# ───────────────────────── arquivo ─────────────────────────


def default_routines() -> dict[str, dict[str, Any]]:
    """As rotinas de fábrica; o usuário pode editar, agendar ou apagar qualquer uma."""
    return {
        "bom dia": {
            "name": "Bom dia",
            "aliases": ["bom dia jarvis", "rotina da manha", "manha"],
            "steps": [
                "greet",
                "weather",
                f"news: {DEFAULT_NEWS_TOPIC}",
                "reminders",
                "layout: trabalho",
                "youtube: playlist lo-fi para trabalhar",
            ],
            "schedule": None,
        },
        "modo foco": {
            "name": "Modo foco",
            "aliases": ["foco", "concentracao", "rotina foco"],
            "steps": [
                "minimize",
                "volume: 15",
                "timer: 25 Pomodoro",
                "note: Modo foco | 25 minutos de foco. Celular longe e uma tarefa por vez.",
            ],
            "schedule": None,
        },
        "modo jogo": {
            "name": "Modo jogo",
            "aliases": ["jogo", "hora do jogo", "gaming"],
            "steps": ["app: Steam", "app: Discord", "volume: 60"],
            "schedule": None,
        },
        "boa noite": {
            "name": "Boa noite",
            "aliases": ["boa noite jarvis", "dormir", "fim do dia"],
            "steps": ["greet", "save_layout: noite", "media: stop", "lock"],
            "schedule": None,
        },
    }


_FILE_LOCK = threading.Lock()


def routine_key(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _plain(name)).strip()[:MAX_NAME_CHARS].strip()


def _valid_routine(key: str, raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not routine_key(key):
        return None
    steps: list[str] = []
    for item in raw.get("steps") or []:
        try:
            steps.append(parse_step(item).raw)
        except RoutineError:
            logger.warning("Passo ignorado na rotina '%s': %r", key, item)
    if not steps:
        return None
    aliases = [routine_key(alias) for alias in raw.get("aliases") or [] if isinstance(alias, str)]
    return {
        "name": str(raw.get("name") or key).strip()[:MAX_NAME_CHARS] or key,
        "aliases": [alias for alias in dict.fromkeys(aliases) if alias][:MAX_ALIASES],
        "steps": steps[:MAX_STEPS],
        "schedule": _valid_schedule(raw.get("schedule")),
        "triggers": _valid_triggers(raw.get("triggers")),
    }


def _valid_triggers(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    from context_triggers import valid_triggers

    return valid_triggers(raw)


def load_routines(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Routines by key. Without a file (first run) the factory routines are used."""
    path = path or ROUTINES_FILE
    with _FILE_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default_routines()
        except (OSError, ValueError):
            logger.warning("rotinas.json ilegível; usando as rotinas padrão (o arquivo não foi apagado).")
            return default_routines()
    raw = data.get("routines") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return default_routines()
    routines: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        valid = _valid_routine(str(key), value)
        if valid is not None:
            routines[routine_key(str(key))] = valid
    return routines


def save_routines(routines: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = path or ROUTINES_FILE
    payload = {"version": FILE_VERSION, "routines": routines}
    with _FILE_LOCK:
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)


FILLER = {"rotina", "rotinas", "modo", "a", "o", "de", "do", "da", "jarvis", "ativa", "ativar", "roda", "rodar", "liga"}


def _core(text: str) -> str:
    return " ".join(word for word in routine_key(text).split() if word not in FILLER)


def find_routine(name: str, routines: dict[str, dict[str, Any]], *, fuzzy: bool = True) -> str:
    """Key of the routine the user means ("modo foco", "foco", "o bom dia", "rotina de estudo").

    ``fuzzy`` also accepts a transcription slip ("boa noitê"); saving never uses it, so a new
    routine "jogo 2" does not overwrite "modo jogo".
    """
    wanted = routine_key(name)
    if not wanted:
        raise RoutineError("Diga o nome da rotina.")
    if wanted in routines:
        return wanted
    for key, routine in routines.items():
        if wanted in routine["aliases"] or wanted == routine_key(routine["name"]):
            return key
    core = _core(wanted)
    candidates: dict[str, str] = {}
    for key, routine in routines.items():
        for label in (key, routine["name"], *routine["aliases"]):
            candidates.setdefault(_core(label), key)
    if core and core in candidates:
        return candidates[core]
    close = difflib.get_close_matches(core or wanted, list(candidates), n=1, cutoff=0.75) if fuzzy else []
    if close:
        return candidates[close[0]]
    names = ", ".join(routine["name"] for routine in routines.values()) or "nenhuma"
    raise RoutineError(f"Não tenho uma rotina chamada '{name}'. Rotinas salvas: {names}.")


def summary_for_prompt(routines: dict[str, dict[str, Any]] | None = None) -> str | None:
    """One line per routine for the agent's instructions: name, aliases and schedule."""
    try:
        routines = routines if routines is not None else load_routines()
    except Exception:
        return None
    lines = []
    for routine in routines.values():
        extra = [f"também: {', '.join(routine['aliases'][:3])}"] if routine["aliases"] else []
        when = describe_schedule(routine["schedule"])
        if when:
            extra.append(f"agendada {when}")
        if routine.get("triggers"):
            from context_triggers import describe_triggers

            extra.append(f"roda sozinha {describe_triggers(routine)}")
        lines.append(f"- {routine['name']}" + (f" ({'; '.join(extra)})" if extra else ""))
    return "\n".join(lines) or None


# ───────────────────────── execução ─────────────────────────


class SessionContext:
    """What the tools need from a RunContext, for runs that no tool call started (agendadas)."""

    def __init__(self, session: Any) -> None:
        self.session = session

    @property
    def userdata(self) -> Any:
        return self.session.userdata


@dataclass(slots=True)
class StepResult:
    step: Step
    label: str
    status: StepStatus = "pending"
    detail: str = ""

    def card(self) -> dict[str, Any]:
        return {"label": self.label, "status": self.status, "detail": self.detail[:240]}


@dataclass(slots=True)
class RoutineRun:
    key: str
    name: str
    trigger: Literal["voz", "agenda", "contexto"]
    results: list[StepResult]
    run_id: str = field(default_factory=lambda: secrets.token_hex(4))
    started_at: float = field(default_factory=time.time)

    @property
    def status(self) -> str:
        statuses = {result.status for result in self.results}
        if statuses & {"pending", "running"}:
            return "running"
        if "confirm" in statuses:
            return "confirm"
        failed = sum(result.status == "error" for result in self.results)
        if failed == 0:
            return "done"
        return "failed" if failed == len(self.results) else "partial"

    def card(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "name": self.name,
            "trigger": self.trigger,
            "status": self.status,
            "started_at": int(self.started_at * 1000),
            "steps": [result.card() for result in self.results],
        }


def _now() -> dt.datetime:
    return dt.datetime.now()


def _settings() -> Settings:
    return load_settings()


def _tool(module: str, name: str) -> Callable[..., Awaitable[str]]:
    # Resolved on every call, so tests can patch the tool in its own module.
    return getattr(importlib.import_module(module), name)


def greeting(moment: dt.datetime) -> str:
    from tools import MONTHS_PT, WEEKDAYS_PT

    if 5 <= moment.hour < 12:
        salutation = "Bom dia"
    elif 12 <= moment.hour < 18:
        salutation = "Boa tarde"
    else:
        salutation = "Boa noite"
    when = f"{moment:%H:%M} de {WEEKDAYS_PT[moment.weekday()]}, {moment.day} de {MONTHS_PT[moment.month - 1]}"
    return f"{salutation}, senhor. Agora são {when}."


def reminders_text(limit: int = 5) -> str:
    from memory import load_memories

    memories = load_memories()
    agenda = [item for item in memories if item.get("category") == "agenda"]
    if not agenda:
        return "Sem lembretes de agenda na memória."
    return "Lembretes: " + "; ".join(item["fact"] for item in agenda[-limit:]) + "."


def is_failure(result: str) -> bool:
    plain = _plain(result)
    return bool(FAILURE_START.match(plain) or FAILURE_ANYWHERE.search(plain))


async def _execute(step: Step, context: Any, settings: Settings) -> str:
    """Run one step through the tool that already does it; raises RoutineError for a clear failure."""
    action, arg = step.action, step.arg
    needs = ACTIONS[action].needs
    if needs == "pc" and not settings.pc_control_enabled:
        raise RoutineError("o controle do PC está desligado (JARVIS_ENABLE_PC_CONTROL=true liga).")
    if needs == "memory" and not settings.memory_enabled:
        return "A memória está desligada (JARVIS_ENABLE_MEMORY=false): nenhum lembrete."

    if action == "greet":
        return greeting(_now())
    if action == "reminders":
        return await asyncio.to_thread(reminders_text)
    if action == "weather":
        city = arg or settings.home_city
        if not city:
            raise RoutineError("nenhuma cidade: defina JARVIS_HOME_CITY no .env ou use 'weather: cidade'.")
        return await _tool("tools", "get_weather")(context, city=city)
    if action == "news":
        return await _tool("tools", "search_news")(context, topic=arg or DEFAULT_NEWS_TOPIC)
    if action == "time":
        return await _tool("tools", "get_current_time")(context)
    if action == "timer":
        minutes, label = parse_timer(arg)
        return await _tool("tools", "set_timer")(context, minutes=minutes, label=label or "Rotina")
    if action == "note":
        title, _, content = arg.partition("|")
        return await _tool("tools", "show_on_hud")(context, title=title.strip(), content=(content or title).strip())
    if action == "layout":
        return await _tool("pc_control", "manage_layouts")(context, action="apply", name=arg)
    if action == "save_layout":
        return await _tool("pc_control", "manage_layouts")(context, action="save", name=arg)
    if action == "youtube":
        return await _tool("pc_control", "play_youtube")(context, query=arg)
    if action == "spotify":
        return await _tool("pc_control", "open_streaming")(context, service="Spotify", query=arg)
    if action == "stream":
        service, _, query = arg.partition("|")
        return await _tool("pc_control", "open_streaming")(context, service=service.strip(), query=query.strip() or None)
    if action == "site":
        return await _tool("pc_control", "open_website")(context, url=arg)
    if action == "app":
        return await _tool("pc_control", "open_app")(context, name=arg)
    if action == "folder":
        return await _tool("pc_control", "open_folder")(context, folder=arg)
    if action == "volume":
        if arg.isdigit():
            return await _tool("pc_control", "set_volume")(context, action="set", level=int(arg))
        return await _tool("pc_control", "set_volume")(context, action=arg)
    if action == "media":
        return await _tool("pc_control", "media_control")(context, action=arg)
    if action == "minimize":
        return await _tool("pc_control", "arrange_windows")(context, action="show_desktop")
    if action == "close":
        return await _tool("pc_control", "close_app")(context, name=arg)
    if action == "lock":
        return await _tool("pc_control", "lock_computer")(context)
    raise RoutineError(f"ação desconhecida: {action}.")


async def _publish(run: RoutineRun) -> None:
    await show_card("routine", run.card())


async def run_step(result: StepResult, context: Any, settings: Settings) -> None:
    result.status = "running"
    try:
        detail = await asyncio.wait_for(_execute(result.step, context, settings), STEP_TIMEOUT_S)
    except RoutineError as exc:
        result.status, result.detail = "error", str(exc)
    except asyncio.TimeoutError:
        result.status, result.detail = "error", f"não terminou em {STEP_TIMEOUT_S:g} segundos."
    except Exception as exc:  # um passo nunca derruba a rotina
        logger.exception("Passo '%s' da rotina falhou.", result.step.raw)
        result.status, result.detail = "error", f"erro inesperado ({type(exc).__name__})."
    else:
        detail = str(detail or "").strip()
        result.status = "error" if is_failure(detail) else "ok"
        result.detail = detail or "Feito."


_RUNNING: set[str] = set()


async def execute_routine(
    context: Any,
    key: str,
    routine: dict[str, Any],
    *,
    trigger: Literal["voz", "agenda", "contexto"],
    settings: Settings | None = None,
) -> RoutineRun:
    """Run the safe steps in order, then park the dangerous ones waiting for the user's "sim"."""
    settings = settings or _settings()
    steps = [parse_step(raw) for raw in routine["steps"]]
    run = RoutineRun(key=key, name=routine["name"], trigger=trigger, results=[StepResult(step, step.label(settings)) for step in steps])
    if key in _RUNNING:
        raise RoutineError(f"A rotina '{routine['name']}' já está rodando.")
    _RUNNING.add(key)
    try:
        await tool_status("run_routine", "running", routine["name"])
        await _publish(run)
        for result in run.results:
            if result.step.dangerous:
                continue
            result.status = "running"
            await _publish(run)
            await run_step(result, context, settings)
        await _publish(run)
        dangerous = [result for result in run.results if result.step.dangerous]
        for result in dangerous:
            result.status = "confirm"
            result.detail = "Esperando o seu sim."
        state = session_state(context)
        if dangerous:
            # Só uma fala NOVA do usuário vale como "sim" (não o pedido que rodou a rotina).
            state[PENDING_KEY] = {"run": run, "expires": time.time() + PENDING_CONFIRM_S, "heard": user_message_count(context)}
        else:
            state.pop(PENDING_KEY, None)
        await _publish(run)
        await tool_status("run_routine", "error" if run.status == "failed" else "done", routine["name"])
    finally:
        _RUNNING.discard(key)
    logger.info("Rotina '%s' (%s): %s", routine["name"], trigger, run.status)
    return run


def _clip(text: str, limit: int = REPORT_STEP_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def build_report(run: RoutineRun) -> str:
    """What the routine did, step by step, plus how Jarvis should say it."""
    done = [result for result in run.results if result.status == "ok"]
    failed = [result for result in run.results if result.status == "error"]
    waiting = [result for result in run.results if result.status == "confirm"]
    lines = [f"Rotina '{run.name}': {len(done)} de {len(run.results)} passos concluídos."]
    for result in run.results:
        if result.status == "ok":
            lines.append(f"- {result.label}: {_clip(result.detail)}")
        elif result.status == "error":
            lines.append(f"- {result.label}: FALHOU — {_clip(result.detail, 240)}")
    if waiting:
        what = " e ".join(result.label.lower() for result in waiting)
        lines.append(
            f"PRECISA CONFIRMAÇÃO: falta {what}, que NÃO foi feito. Pergunte ao usuário se pode; só chame "
            "confirm_routine_step depois que ele disser sim. Se ele disser não, chame confirm_routine_step(cancel=True)."
        )
    guide = (
        "Responda em poucas frases naturais, sem ler a lista: comece pelo cumprimento se houver, resuma o clima "
        "em uma frase, diga só as 2 ou 3 manchetes mais importantes e os lembretes, e confirme o que foi aberto ou ajustado."
    )
    if failed:
        guide += " Diga claramente o que falhou e por quê, sem fingir que deu certo."
    return "\n".join(lines) + "\n" + guide


def pending_run(context: Any) -> RoutineRun | None:
    pending = session_state(context).get(PENDING_KEY)
    if not isinstance(pending, dict) or pending.get("expires", 0) < time.time():
        session_state(context).pop(PENDING_KEY, None)
        return None
    return pending["run"]


YES_WORDS = {
    "sim", "pode", "podes", "confirmo", "confirma", "confirmar", "claro", "manda", "isso", "ok", "beleza",
    "positivo", "bloqueia", "bloquear", "fecha", "fechar", "faz", "faca", "vai", "certo", "afirmativo", "yes",
}
NO_WORDS = {"nao", "espera", "pera", "cancela", "cancelar", "negativo", "nunca", "deixa", "pare"}
LEADING = {"jarvis", "e", "ah", "ta", "entao"}


def user_said_yes(text: str | None) -> bool:
    """A plain "sim"/"pode bloquear" from the user; any "não"/"espera"/"cancela" means no."""
    tokens = speech_tokens(text or "")
    if any(token in NO_WORDS for token in tokens):
        return False
    while tokens and tokens[0] in LEADING:
        tokens.pop(0)
    return bool(tokens) and tokens[0] in YES_WORDS and len(tokens) <= 8


def user_message_count(context: Any) -> int | None:
    history = getattr(context.session, "history", None)
    if history is None or not hasattr(history, "messages"):
        return None
    return sum(1 for message in history.messages() if str(getattr(message, "role", "")).lower().endswith("user"))


async def _wait_for_user(context: Any, accept: Callable[[str | None], bool]) -> bool:
    """The transcript of the user's speech can land in the history a moment after the tool call."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CONFIRMATION_WAIT_SECONDS
    while True:
        if accept(last_user_message(context)):
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(CONFIRMATION_POLL_SECONDS)


ASK_WORDS = {"rotina", "rotinas", "modo", "agenda", "agendar", "agendado", "agendada", "agende", "programa", "programar"}


def _asks_about(text: str | None, names: tuple[str, ...]) -> bool:
    plain = " " + " ".join(speech_tokens(text or "")) + " "
    if any(f" {word} " in plain for word in ASK_WORDS):
        return True
    return any(core and f" {core} " in plain for core in (_core(name) for name in names))


NOT_ASKED = (
    "NADA foi alterado: só crio, mudo, apago ou agendo rotinas quando o próprio usuário pede, falando em "
    "rotina ou no nome dela. Pergunte se ele quer isso."
)


# ───────────────────────── ferramentas ─────────────────────────


def _routine_lines(routines: dict[str, dict[str, Any]]) -> list[str]:
    lines = []
    for routine in routines.values():
        when = describe_schedule(routine["schedule"])
        steps = ", ".join(parse_step(raw).label() for raw in routine["steps"])
        lines.append(f"{routine['name']}{f' (agendada: {when})' if when else ''}: {steps}")
        if routine.get("triggers"):
            from context_triggers import describe_triggers

            lines[-1] += f" (roda sozinha {describe_triggers(routine)})"
    return lines


@function_tool()
async def list_routines(context: RunContext) -> str:
    """List the saved routines (rotinas): name, steps and schedule. Also shows them on the HUD.

    Use it when the user asks which routines exist or what one does, and before editing one.
    """
    routines = await asyncio.to_thread(load_routines)
    if not routines:
        return "Nenhuma rotina salva. Ofereça criar uma."
    lines = _routine_lines(routines)
    await show_card("note", {"title": "Rotinas", "content": "\n".join(f"- {line}" for line in lines)})
    return "Rotinas salvas:\n" + "\n".join(lines)


@function_tool()
async def run_routine(context: RunContext, name: str) -> str:
    """Run a saved routine: several actions in sequence, shown step by step on the HUD.

    Use it when the user says a routine's name as a command: "bom dia, Jarvis" (greeting, weather,
    headlines, reminders, work layout and a playlist), "modo foco", "modo jogo", "boa noite",
    "roda a rotina estudo", "ativa o modo foco". The result says what each step did and what
    failed; tell the user both. Dangerous steps (lock the PC, close an app) are NOT done here:
    if the result says PRECISA CONFIRMAÇÃO, ask and call confirm_routine_step only after a yes.

    Args:
        name: The routine as the user says it, e.g. "bom dia", "modo foco", "estudo".
    """
    try:
        routines = await asyncio.to_thread(load_routines)
        key = find_routine(name, routines)
        run = await execute_routine(context, key, routines[key], trigger="voz")
    except RoutineError as exc:
        return str(exc)
    return build_report(run)


@function_tool()
async def confirm_routine_step(context: RunContext, cancel: bool = False) -> str:
    """Do (or cancel) the dangerous steps a routine left waiting, e.g. locking the PC in "boa noite".

    Call it only right after the user answered your question: yes ("sim", "pode") -> cancel=False;
    no ("não", "deixa") -> cancel=True. The user's own last words are checked; nothing runs without them.

    Args:
        cancel: True when the user said no.
    """
    pending = session_state(context).get(PENDING_KEY)
    run = pending_run(context)
    if run is None:
        return "Não há nenhum passo de rotina esperando confirmação."
    waiting = [result for result in run.results if result.status == "confirm"]
    if cancel:
        for result in waiting:
            result.status, result.detail = "cancelled", "Cancelado pelo usuário."
        session_state(context).pop(PENDING_KEY, None)
        await _publish(run)
        return "Combinado: " + " e ".join(result.label.lower() for result in waiting) + " ficou de fora."
    heard = pending.get("heard")

    def answered_yes(text: str | None) -> bool:
        count = user_message_count(context)
        return user_said_yes(text) and (heard is None or count is None or count > heard)

    if not await _wait_for_user(context, answered_yes):
        return (
            "NADA foi feito: a última fala do usuário não foi um sim claro. Pergunte de novo e espere "
            "ele responder 'sim' ou 'pode'."
        )
    session_state(context).pop(PENDING_KEY, None)
    settings = _settings()
    for result in waiting:
        await run_step(result, context, settings)
        await _publish(run)
    parts = [f"{result.label}: {'feito' if result.status == 'ok' else 'FALHOU — ' + _clip(result.detail, 200)}" for result in waiting]
    return "; ".join(parts) + "."


@function_tool()
async def save_routine(
    context: RunContext,
    name: str,
    steps: list[str],
    mode: Literal["replace", "append"] = "replace",
    aliases: list[str] | None = None,
) -> str:
    """Create a routine or change one ("cria uma rotina estudo que abre o Notion e põe lo-fi").

    Each step is one line "action: argument". Actions: greet; weather (or "weather: city");
    news: topic; reminders; time; timer: minutes label; note: title | text; layout: name (apply a
    saved window layout); save_layout: name; youtube: search (plays the best video/playlist);
    spotify: search; stream: service | search; site: url or name; app: name; folder: name;
    volume: 0-100 | mute | unmute; media: stop | play_pause | next | previous; minimize (show the
    desktop); close: app (asks first); lock (asks first).
    Example: name="estudo", steps=["app: Notion", "youtube: lo-fi para estudar"].

    Args:
        name: Routine name, e.g. "estudo".
        steps: The steps in order. With mode="replace" they become the whole routine.
        mode: replace (create, or rewrite every step) or append (add steps at the end).
        aliases: Other ways the user calls it, e.g. ["hora de estudar"].
    """
    if not await _wait_for_user(context, lambda text: _asks_about(text, (name,))):
        return NOT_ASKED
    try:
        parsed = [parse_step(raw) for raw in steps]
        routines = await asyncio.to_thread(load_routines)
        try:
            key = find_routine(name, routines, fuzzy=False)
        except RoutineError:
            key = routine_key(name)
            if not key:
                raise RoutineError("Diga um nome curto para a rotina, por exemplo 'estudo'.") from None
            if len(routines) >= MAX_ROUTINES:
                raise RoutineError(f"Já existem {MAX_ROUTINES} rotinas; apague uma antes.") from None
        existing = routines.get(key)
        new_steps = [step.raw for step in parsed]
        if existing and mode == "append":
            new_steps = existing["steps"] + new_steps
        if not new_steps:
            raise RoutineError("Uma rotina precisa de pelo menos um passo.")
        if len(new_steps) > MAX_STEPS:
            raise RoutineError(f"Uma rotina tem no máximo {MAX_STEPS} passos.")
        routine = {
            "name": existing["name"] if existing else name.strip()[:MAX_NAME_CHARS],
            "aliases": list(dict.fromkeys([*(existing["aliases"] if existing else []), *(routine_key(a) for a in aliases or [])]))[:MAX_ALIASES],
            "steps": new_steps,
            "schedule": existing["schedule"] if existing else None,
            "triggers": existing.get("triggers", []) if existing else [],
        }
        routines[key] = _valid_routine(key, routine) or routine
        await asyncio.to_thread(save_routines, routines)
    except RoutineError as exc:
        return f"NADA foi salvo: {exc}"
    labels = ", ".join(parse_step(raw).label() for raw in routines[key]["steps"])
    verb = "atualizada" if existing else "criada"
    await show_card("note", {"title": f"Rotina {routines[key]['name']}", "content": "\n".join(f"{i}. {parse_step(raw).label()}" for i, raw in enumerate(routines[key]["steps"], 1))})
    warning = ""
    if any(parse_step(raw).dangerous for raw in routines[key]["steps"]):
        warning = " Os passos de fechar app ou bloquear o PC sempre vão pedir confirmação na hora."
    return f"Rotina '{routines[key]['name']}' {verb}: {labels}.{warning}"


@function_tool()
async def delete_routine(context: RunContext, name: str) -> str:
    """Delete a saved routine ("apaga a rotina estudo"). The factory ones can be deleted too.

    Args:
        name: The routine to delete.
    """
    if not await _wait_for_user(context, lambda text: _asks_about(text, (name,))):
        return NOT_ASKED
    try:
        routines = await asyncio.to_thread(load_routines)
        key = find_routine(name, routines)
        removed = routines.pop(key)
        await asyncio.to_thread(save_routines, routines)
    except RoutineError as exc:
        return f"NADA foi apagado: {exc}"
    return f"Rotina '{removed['name']}' apagada."


@function_tool()
async def schedule_routine(
    context: RunContext,
    name: str,
    time_of_day: str | None = None,
    days: str | None = None,
    cancel: bool = False,
) -> str:
    """Schedule a routine to run by itself ("todo dia útil às 8h roda o bom dia"), or cancel it.

    At that time the HUD opens the link by itself (like the wake word) and Jarvis speaks the result.
    It only runs while `python jarvis.py` is running on the computer.

    Args:
        name: The routine, e.g. "bom dia".
        time_of_day: Time as said, e.g. "8h", "07:30", "8 e meia".
        days: "todo dia", "dias úteis", "fim de semana" or weekdays ("segunda, quarta e sexta").
        cancel: True to remove the schedule ("para de rodar o bom dia sozinho").
    """
    if not await _wait_for_user(context, lambda text: _asks_about(text, (name,))):
        return NOT_ASKED
    try:
        routines = await asyncio.to_thread(load_routines)
        key = find_routine(name, routines)
        routine = routines[key]
        if cancel:
            routine["schedule"] = None
        else:
            if not time_of_day:
                raise RoutineError("Diga o horário, por exemplo '8h'.")
            routine["schedule"] = {"days": list(parse_days(days)), "time": parse_time(time_of_day), "enabled": True}
        await asyncio.to_thread(save_routines, routines)
    except RoutineError as exc:
        return f"NADA foi agendado: {exc}"
    if cancel:
        return f"A rotina '{routine['name']}' não roda mais sozinha."
    return (
        f"Rotina '{routine['name']}' agendada: {describe_schedule(routine['schedule'])}. Ela roda enquanto o Jarvis "
        "estiver aberto no computador (python jarvis.py)."
    )


def build_routine_tools() -> list[Any]:
    from context_triggers import set_routine_trigger

    return [list_routines, run_routine, confirm_routine_step, save_routine, delete_routine, schedule_routine, set_routine_trigger]


# ───────────────────────── agente: rotinas agendadas ─────────────────────────


class ClaimedRoutine(str):
    """A routine key handed out by the server; ``context`` says what fired it, when not the clock."""

    context: str | None = None


def claim_scheduled(hud_url: str, *, post: Callable[..., Any] | None = None) -> str | None:
    """Ask the HUD server for a scheduled routine that is due (it hands each one out once)."""
    if post is None:
        import requests

        post = requests.post
    try:
        response = post(hud_url.rstrip("/") + CLAIM_PATH, timeout=3)
        response.raise_for_status()
        body = response.json()
        routine = body.get("routine")
    except Exception:
        logger.debug("Servidor do HUD não respondeu sobre rotinas agendadas.", exc_info=True)
        return None
    if not isinstance(routine, str) or not routine:
        return None
    claimed = ClaimedRoutine(routine)
    context = body.get("context")
    claimed.context = context if isinstance(context, str) and context else None
    return claimed


async def run_scheduled(session: Any, key: str) -> RoutineRun | None:
    """Run a routine the schedule fired and make Jarvis say how it went."""
    context = SessionContext(session)
    # Rotina por contexto: o servidor diz o que a disparou ("o PhpStorm abriu").
    why = getattr(key, "context", None)
    try:
        routines = await asyncio.to_thread(load_routines)
        found = find_routine(key, routines)
        run = await execute_routine(context, found, routines[found], trigger="contexto" if why else "agenda")
    except RoutineError as exc:
        logger.warning("Rotina agendada '%s' não rodou: %s", key, exc)
        return None
    try:
        opening = (
            f"A rotina '{run.name}' acabou de rodar sozinha porque {why}. "
            if why
            else f"A rotina agendada '{run.name}' acabou de rodar sozinha, no horário marcado. "
        )
        session.generate_reply(instructions=f"{opening}Fale com o usuário sobre o resultado:\n{build_report(run)}")
    except Exception:
        logger.warning("Não foi possível anunciar a rotina agendada '%s'.", run.name)
    return run


_WATCH_TASKS: set[asyncio.Task[None]] = set()


def watch_scheduled_routines(session: Any, hud_url: str, *, interval: float = AGENT_POLL_S) -> asyncio.Task[None]:
    """While this conversation is open, run the scheduled routines that come due."""

    async def loop() -> None:
        while True:
            await asyncio.sleep(interval)
            key = await asyncio.to_thread(claim_scheduled, hud_url)
            if key:
                await run_scheduled(session, key)

    task = asyncio.create_task(loop())
    _WATCH_TASKS.add(task)
    task.add_done_callback(_WATCH_TASKS.discard)
    try:
        session.on("close", lambda *_: task.cancel())
    except Exception:
        pass
    return task


# ───────────────────────── servidor: agendamento ─────────────────────────


class RoutineScheduler:
    """Runs in the HUD server: fires due schedules once a day and hands them to the agent.

    ``now`` gives the local wall clock (dates and times of the schedule); ``monotonic`` measures
    how long a fired routine waits to be claimed. ``on_due(key)`` opens the link (wake_hub).
    """

    def __init__(
        self,
        *,
        load: Callable[[], dict[str, dict[str, Any]]] = load_routines,
        now: Callable[[], dt.datetime] = _now,
        monotonic: Callable[[], float] = time.monotonic,
        on_due: Callable[[str], Any] | None = None,
    ) -> None:
        self._load = load
        self._now = now
        self._monotonic = monotonic
        self.on_due = on_due
        self.fired: dict[str, dt.date] = {}
        self.pending: list[tuple[str, float]] = []
        # Rotinas disparadas por contexto: o que aconteceu, para o agente dizer.
        self.reasons: dict[str, str] = {}

    def scheduled_count(self) -> int:
        try:
            return sum(1 for routine in self._load().values() if routine["schedule"] and routine["schedule"].get("enabled", True))
        except Exception:
            return 0

    def tick(self) -> list[str]:
        """Routines that came due since the last tick (each at most once a day)."""
        now = self._now()
        try:
            routines = self._load()
        except Exception:
            logger.exception("Não foi possível ler as rotinas agendadas.")
            return []
        due = []
        for key, routine in routines.items():
            schedule = routine.get("schedule")
            when = occurrence(schedule, now) if schedule else None
            if when is None or not when <= now < when + CATCH_UP or self.fired.get(key) == now.date():
                continue
            self.fired[key] = now.date()
            self.reasons.pop(key, None)
            self.pending = [item for item in self.pending if item[0] != key]
            self.pending.append((key, self._monotonic() + PENDING_ROUTINE_S))
            due.append(key)
            logger.info("Rotina agendada '%s' venceu (%s).", routine["name"], schedule["time"])
            if self.on_due is not None:
                try:
                    self.on_due(key)
                except Exception:
                    logger.exception("Falha ao abrir o link para a rotina '%s'.", key)
        return due

    def fire(self, key: str, reason: str) -> None:
        """Hand a routine fired by context (context_triggers.py) to the agent, like a due schedule."""
        self.pending = [item for item in self.pending if item[0] != key]
        self.pending.append((key, self._monotonic() + PENDING_ROUTINE_S))
        self.reasons[key] = reason
        if self.on_due is not None:
            try:
                self.on_due(key)
            except Exception:
                logger.exception("Falha ao abrir o link para a rotina '%s'.", key)

    def claim_reason(self, key: str | None) -> str | None:
        return self.reasons.pop(key, None) if key else None

    def claim(self) -> str | None:
        now = self._monotonic()
        self.pending = [item for item in self.pending if item[1] > now]
        if not self.pending:
            return None
        key, _ = self.pending.pop(0)
        return key

    async def run_forever(self, enabled: Callable[[], bool], interval: float = SCHEDULER_TICK_S) -> None:
        while True:
            try:
                # No laço de eventos: on_due entrega o aviso nas filas asyncio das abas do HUD.
                if enabled():
                    self.tick()
            except Exception:
                logger.exception("Falha no agendador de rotinas.")
            await asyncio.sleep(interval)
