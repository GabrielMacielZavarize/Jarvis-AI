from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import platform
import re
import secrets
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil
import requests
from ddgs import DDGS
from livekit.agents import RunContext, function_tool

from hud import hud_request, net_activity, show_card, tool_status
from settings import Settings

logger = logging.getLogger("jarvis-tools")

PENDING_EMAIL_KEY = "pending_email"
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
MAX_TIMER_MINUTES = 24 * 60
WEEKDAYS_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS_PT = (
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
WEATHER_CODES = {
    0: "Céu limpo",
    1: "Predominantemente limpo",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Névoa",
    48: "Névoa com geada",
    51: "Garoa leve",
    53: "Garoa moderada",
    55: "Garoa forte",
    61: "Chuva leve",
    63: "Chuva moderada",
    65: "Chuva forte",
    71: "Neve leve",
    73: "Neve moderada",
    75: "Neve forte",
    80: "Pancadas leves",
    81: "Pancadas moderadas",
    82: "Pancadas fortes",
    95: "Trovoada",
    96: "Trovoada com granizo leve",
    99: "Trovoada com granizo forte",
}

# Mantém referência aos timers ativos para que não sejam coletados pelo GC.
_TIMER_TASKS: set[asyncio.Task[None]] = set()


class CityNotFoundError(LookupError):
    """Raised when the geocoding API finds no match for a city."""


def _truncate(value: str, limit: int = 180) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3].rstrip()}..."


def _validate_email_address(email: str, field_name: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} não pode ser vazio.")
    if not EMAIL_PATTERN.match(normalized):
        raise ValueError(f"{field_name} precisa ser um email válido.")
    return normalized


def _get_session_state(context: RunContext) -> dict[str, Any]:
    userdata = context.userdata
    if userdata is None:
        userdata = {}
        context.session.userdata = userdata
    return userdata


def _get_last_user_message(context: RunContext) -> str | None:
    history = getattr(context.session, "history", None)
    if history is None or not hasattr(history, "messages"):
        return None

    for message in reversed(history.messages()):
        role = str(getattr(message, "role", "")).lower()
        if role == "user" or role.endswith(".user"):
            text_content = getattr(message, "text_content", None)
            if isinstance(text_content, str):
                return text_content.strip()
    return None


def _format_weather(location_name: str, current: dict[str, Any]) -> str:
    required_fields = (
        "temperature_2m",
        "relative_humidity_2m",
        "weather_code",
        "wind_speed_10m",
    )
    missing = [field for field in required_fields if field not in current]
    if missing:
        missing_list = ", ".join(missing)
        raise KeyError(f"Dados do clima incompletos: {missing_list}")

    description = WEATHER_CODES.get(current["weather_code"], "Condição desconhecida")
    return (
        f"{location_name}: {description}, "
        f"{current['temperature_2m']}°C, "
        f"Umidade {current['relative_humidity_2m']}%, "
        f"Vento {current['wind_speed_10m']} km/h"
    )


def _format_datetime_pt(moment: dt.datetime) -> str:
    weekday = WEEKDAYS_PT[moment.weekday()]
    month = MONTHS_PT[moment.month - 1]
    return f"{weekday}, {moment.day} de {month} de {moment.year}, {moment:%H:%M}"


def _format_utc_offset(moment: dt.datetime) -> str:
    offset = moment.utcoffset() or dt.timedelta()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _geocode(city: str) -> dict[str, Any]:
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "pt"},
        timeout=15,
    )
    response.raise_for_status()
    results = response.json().get("results")
    if not results:
        raise CityNotFoundError(city)

    location = results[0]
    if location.get("latitude") is None or location.get("longitude") is None:
        raise KeyError("Latitude/longitude ausentes na resposta da geocodificação.")
    return location


def _parse_daily_forecast(daily: Any) -> list[dict[str, Any]]:
    if not isinstance(daily, dict):
        return []

    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    maxes = daily.get("temperature_2m_max") or []
    mins = daily.get("temperature_2m_min") or []
    rain = daily.get("precipitation_probability_max") or []

    forecast = []
    for index, date in enumerate(dates):
        if index >= min(len(codes), len(maxes), len(mins)):
            break
        forecast.append(
            {
                "date": date,
                "code": codes[index],
                "label": WEATHER_CODES.get(codes[index], "Condição desconhecida"),
                "max": maxes[index],
                "min": mins[index],
                "rain": rain[index] if index < len(rain) else None,
            }
        )
    return forecast


def _fetch_weather(city: str) -> tuple[str, dict[str, Any]]:
    location = _geocode(city)
    city_name = location.get("name", city)
    country = location.get("country")
    location_name = f"{city_name}, {country}" if country else city_name

    weather_response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,"
                "apparent_temperature,is_day"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "forecast_days": 7,
            "timezone": "auto",
        },
        timeout=15,
    )
    weather_response.raise_for_status()
    weather_data = weather_response.json()

    current = weather_data.get("current")
    if not isinstance(current, dict):
        raise KeyError("Resposta do clima sem bloco 'current'.")

    summary = _format_weather(location_name, current)
    forecast = _parse_daily_forecast(weather_data.get("daily"))
    if forecast:
        today = forecast[0]
        summary += f", Máx {today['max']}°C / Mín {today['min']}°C"

    card = {
        "location": city_name,
        "country": country,
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": weather_data.get("timezone") or location.get("timezone"),
        "current": {
            "temperature": current["temperature_2m"],
            "feels_like": current.get("apparent_temperature"),
            "humidity": current["relative_humidity_2m"],
            "wind": current["wind_speed_10m"],
            "code": current["weather_code"],
            "label": WEATHER_CODES.get(current["weather_code"], "Condição desconhecida"),
            "is_day": current.get("is_day", 1),
        },
        "daily": forecast,
    }
    return summary, card


@function_tool()
async def get_weather(
    context: RunContext,
    city: str,
) -> str:
    """Get the current weather and the 7-day forecast for a given city.

    Args:
        city: The name of the city to get weather for.
    """
    await tool_status("get_weather", "running", city)
    await net_activity(["geocoding-api.open-meteo.com", "api.open-meteo.com"])
    try:
        result, card = await asyncio.to_thread(_fetch_weather, city)
        await show_card("weather", card)
        await tool_status("get_weather", "done", city)
        logger.info("Consulta de clima concluída para '%s'.", city)
        return result
    except CityNotFoundError:
        await tool_status("get_weather", "error", city)
        return f"Cidade '{city}' não encontrada."
    except requests.HTTPError:
        logger.warning("Falha HTTP ao consultar clima para '%s'.", city)
        await tool_status("get_weather", "error", city)
        return "O serviço de clima retornou um erro ao processar a consulta."
    except (KeyError, TypeError, ValueError):
        logger.warning("Resposta inválida ao consultar clima para '%s'.", city)
        await tool_status("get_weather", "error", city)
        return "O serviço de clima retornou dados incompletos ou inválidos."
    except requests.RequestException:
        logger.warning("Falha de rede ao consultar clima para '%s'.", city)
        await tool_status("get_weather", "error", city)
        return "Não foi possível consultar o clima por causa de uma falha de rede."
    except Exception:
        logger.exception("Erro inesperado ao consultar clima para '%s'.", city)
        await tool_status("get_weather", "error", city)
        return f"Ocorreu um erro ao buscar o clima para {city}."


@function_tool()
async def search_web(
    context: RunContext,
    query: str,
) -> str:
    """Search the web using DuckDuckGo.

    Args:
        query: The search query to look up on the web.
    """
    await tool_status("search_web", "running", query)
    await net_activity(["duckduckgo.com"])
    try:
        results = await asyncio.to_thread(DDGS().text, query, max_results=5)
        if not results:
            await tool_status("search_web", "done", query)
            return f"Nenhum resultado encontrado para '{query}'."

        lines = []
        card_results = []
        for index, item in enumerate(results[:5], start=1):
            title = _truncate(str(item.get("title", "Sem título")))
            href = str(item.get("href", "Sem URL"))
            body = _truncate(str(item.get("body", "Sem resumo")), limit=220)
            lines.append(
                f"{index}. {title}\nURL: {href}\nResumo: {body}"
            )
            card_results.append({"title": title, "url": href, "snippet": body})

        await show_card("search", {"query": query, "results": card_results})
        await net_activity([_hostname(item["url"]) for item in card_results], "source")
        await tool_status("search_web", "done", query)
        logger.info("Pesquisa web concluída para '%s'.", query)
        return "\n\n".join(lines)
    except Exception:
        logger.warning("Erro ao pesquisar na web por '%s'.", query)
        await tool_status("search_web", "error", query)
        return f"Ocorreu um erro ao pesquisar na web por '{query}'."


@function_tool()
async def search_news(
    context: RunContext,
    topic: str,
) -> str:
    """Get the latest news headlines about a topic (in Brazilian Portuguese when possible).

    Args:
        topic: The subject to look for news about, e.g. "tecnologia" or "Fórmula 1".
    """
    await tool_status("search_news", "running", topic)
    await net_activity(["duckduckgo.com"])
    try:
        results = await asyncio.to_thread(
            DDGS().news,
            topic,
            region="br-pt",
            max_results=6,
        )
        if not results:
            await tool_status("search_news", "done", topic)
            return f"Nenhuma notícia encontrada sobre '{topic}'."

        lines = []
        items = []
        for index, item in enumerate(results[:6], start=1):
            title = _truncate(str(item.get("title", "Sem título")))
            source = str(item.get("source") or "Fonte desconhecida")
            snippet = _truncate(str(item.get("body", "")), limit=200)
            lines.append(f"{index}. {title} ({source})")
            items.append(
                {
                    "title": title,
                    "url": str(item.get("url", "")),
                    "source": source,
                    "date": item.get("date"),
                    "snippet": snippet,
                    "image": item.get("image"),
                }
            )

        await show_card("news", {"topic": topic, "items": items})
        await net_activity([_hostname(item["url"]) for item in items], "source")
        await tool_status("search_news", "done", topic)
        logger.info("Busca de notícias concluída para '%s'.", topic)
        return "\n".join(lines)
    except Exception:
        logger.warning("Erro ao buscar notícias sobre '%s'.", topic)
        await tool_status("search_news", "error", topic)
        return f"Ocorreu um erro ao buscar notícias sobre '{topic}'."


def _resolve_time(city: str | None) -> tuple[str, dict[str, Any]]:
    if city:
        location = _geocode(city)
        timezone_name = location.get("timezone")
        if not timezone_name:
            raise KeyError("Fuso horário ausente na resposta da geocodificação.")
        moment = dt.datetime.now(ZoneInfo(timezone_name))
        country = location.get("country")
        name = location.get("name", city)
        label = f"{name}, {country}" if country else name
        latitude = location.get("latitude")
        longitude = location.get("longitude")
    else:
        moment = dt.datetime.now().astimezone()
        timezone_name = moment.tzname() or "local"
        label = "Horário local"
        latitude = longitude = None

    summary = f"{label}: {_format_datetime_pt(moment)} ({_format_utc_offset(moment)})"
    card = {
        "location": label,
        "timezone": timezone_name,
        "iso": moment.isoformat(),
        "utc_offset": _format_utc_offset(moment),
        "latitude": latitude,
        "longitude": longitude,
    }
    return summary, card


@function_tool()
async def get_current_time(
    context: RunContext,
    city: str | None = None,
) -> str:
    """Get the current date and time, locally or in a specific city.

    Args:
        city: Optional city name. When omitted, the local time of this computer is used.
    """
    await tool_status("get_current_time", "running", city)
    if city:
        await net_activity(["geocoding-api.open-meteo.com"])
    try:
        summary, card = await asyncio.to_thread(_resolve_time, city)
        await show_card("time", card)
        await tool_status("get_current_time", "done", city)
        return summary
    except CityNotFoundError:
        await tool_status("get_current_time", "error", city)
        return f"Cidade '{city}' não encontrada."
    except (requests.RequestException, KeyError, ZoneInfoNotFoundError):
        logger.warning("Falha ao consultar o horário de '%s'.", city)
        await tool_status("get_current_time", "error", city)
        return "Não foi possível descobrir o horário dessa localidade agora."


def _bytes_to_gb(value: float) -> float:
    return round(value / (1024**3), 1)


def _top_processes(processes: list[psutil.Process], cores: int, limit: int = 5) -> list[dict[str, Any]]:
    usage = []
    for proc in processes:
        try:
            name = proc.info.get("name") or "?"
            if name.lower() in {"system idle process", "idle"}:
                continue
            cpu = proc.cpu_percent(None) / max(cores, 1)
            memory = proc.info["memory_info"].rss / (1024**2) if proc.info.get("memory_info") else 0.0
        except (psutil.Error, KeyError):
            continue
        usage.append({"name": name, "cpu": round(cpu, 1), "mem_mb": round(memory)})
    usage.sort(key=lambda item: (item["cpu"], item["mem_mb"]), reverse=True)
    return usage[:limit]


def _collect_diagnostics() -> dict[str, Any]:
    processes = list(psutil.process_iter(["name", "memory_info"]))
    for proc in processes:
        try:
            proc.cpu_percent(None)  # primeira leitura; a segunda vem depois do intervalo abaixo
        except psutil.Error:
            continue
    per_core = psutil.cpu_percent(interval=0.5, percpu=True)
    cpu_percent = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
    frequency = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    disk_root = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"
    disk = psutil.disk_usage(disk_root)
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    net = psutil.net_io_counters()

    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(logical=True),
            "per_core": [round(value, 1) for value in per_core],
            "freq_mhz": round(frequency.current) if frequency else None,
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": _bytes_to_gb(memory.used),
            "total_gb": _bytes_to_gb(memory.total),
        },
        "disk": {
            "mount": disk_root,
            "percent": disk.percent,
            "used_gb": _bytes_to_gb(disk.used),
            "total_gb": _bytes_to_gb(disk.total),
        },
        "battery": (
            {"percent": round(battery.percent), "plugged": bool(battery.power_plugged)}
            if battery
            else None
        ),
        "uptime_s": int(time.time() - psutil.boot_time()),
        "processes": len(psutil.pids()),
        "top": _top_processes(processes, psutil.cpu_count(logical=True) or 1),
        "net": {
            "sent_mb": round(net.bytes_sent / (1024**2), 1),
            "recv_mb": round(net.bytes_recv / (1024**2), 1),
        }
        if net
        else None,
    }


def _format_diagnostics(data: dict[str, Any]) -> str:
    uptime_hours = data["uptime_s"] // 3600
    parts = [
        f"CPU {data['cpu']['percent']}% em {data['cpu']['cores']} núcleos",
        (
            f"Memória {data['memory']['percent']}% "
            f"({data['memory']['used_gb']} de {data['memory']['total_gb']} GB)"
        ),
        (
            f"Disco {data['disk']['percent']}% "
            f"({data['disk']['used_gb']} de {data['disk']['total_gb']} GB)"
        ),
        f"Ligado há {uptime_hours} h",
        f"{data['processes']} processos",
    ]
    if data.get("battery"):
        plugged = "na tomada" if data["battery"]["plugged"] else "na bateria"
        parts.append(f"Bateria {data['battery']['percent']}% ({plugged})")
    return f"Diagnóstico de {data['os']}: " + ", ".join(parts) + "."


@function_tool()
async def run_diagnostics(
    context: RunContext,
) -> str:
    """Run a diagnostic scan of this computer: CPU, memory, disk, battery and uptime."""
    await tool_status("run_diagnostics", "running")
    try:
        data = await asyncio.to_thread(_collect_diagnostics)
        await show_card("diagnostics", data)
        await tool_status("run_diagnostics", "done")
        return _format_diagnostics(data)
    except Exception:
        logger.exception("Erro ao executar diagnóstico do sistema.")
        await tool_status("run_diagnostics", "error")
        return "Não foi possível concluir o diagnóstico do sistema."


async def _finish_timer(context: RunContext, timer_id: str, label: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    await show_card("timer", {"id": timer_id, "label": label, "status": "done"})
    try:
        context.session.generate_reply(
            instructions=(
                f"Avise o usuário, em uma frase curta, que o timer '{label}' terminou."
            )
        )
    except Exception:
        logger.warning("Não foi possível anunciar o fim do timer '%s'.", label)


@function_tool()
async def set_timer(
    context: RunContext,
    minutes: float,
    label: str = "Timer",
) -> str:
    """Start a countdown timer. Jarvis announces out loud when it finishes.

    Args:
        minutes: Duration in minutes. Fractions are allowed (0.5 = 30 seconds).
        label: Short name for the timer, e.g. "macarrão".
    """
    if minutes <= 0 or minutes > MAX_TIMER_MINUTES:
        return "A duração do timer precisa estar entre alguns segundos e 24 horas."

    clean_label = _truncate(label.strip() or "Timer", limit=40)
    seconds = round(minutes * 60, 1)
    timer_id = secrets.token_hex(4)
    ends_at_ms = int((time.time() + seconds) * 1000)

    task = asyncio.create_task(_finish_timer(context, timer_id, clean_label, seconds))
    _TIMER_TASKS.add(task)
    task.add_done_callback(_TIMER_TASKS.discard)

    await show_card(
        "timer",
        {
            "id": timer_id,
            "label": clean_label,
            "duration_s": seconds,
            "ends_at": ends_at_ms,
            "status": "running",
        },
    )
    logger.info("Timer '%s' iniciado (%ss).", clean_label, seconds)

    if seconds < 60:
        human = f"{int(seconds)} segundos"
    else:
        human = f"{round(minutes, 1):g} minutos"
    return f"Timer '{clean_label}' iniciado para {human}."


@function_tool()
async def show_on_hud(
    context: RunContext,
    title: str,
    content: str,
) -> str:
    """Display a text panel on the user's holographic HUD.

    Use it for lists, step-by-step instructions, summaries, code or anything that
    reads better than it sounds.

    Args:
        title: Short title for the panel.
        content: The text to display. Use one item per line for lists.
    """
    shown = await show_card(
        "note",
        {"title": _truncate(title.strip() or "Nota", limit=60), "content": content[:4000]},
    )
    if not shown:
        return "O HUD não está conectado; descreva o conteúdo em voz."
    return "Painel exibido no HUD."


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


HUD_PANEL_KINDS = {
    "weather": "clima",
    "search": "pesquisa",
    "news": "notícias",
    "time": "horário",
    "diagnostics": "diagnóstico",
    "timer": "timers",
    "note": "notas",
    "email": "email",
    "media": "mídia",
}


def _panel_names(kinds: list[str]) -> str:
    return ", ".join(HUD_PANEL_KINDS.get(kind, kind) for kind in kinds) or "nenhum"


@function_tool()
async def manage_hud_panels(
    context: RunContext,
    action: Literal["list", "close", "close_all", "expand", "collapse"],
    panels: list[str] | None = None,
) -> str:
    """List, close, expand (enlarge) or collapse the panels on the user's holographic HUD.

    When the user talks about an "aba"/"painel"/"janela" of weather, search, news, time,
    diagnostics, timer, notes, email or media, they mean these HUD panels (not browser tabs).

    Args:
        action: list (what is open), close, close_all, expand (enlarge one panel in the
            center of the HUD) or collapse (return it to normal size).
        panels: Panel kinds: weather, search, news, time, diagnostics, timer, note, email, media.
            For expand, pass the single panel to enlarge.
    """
    kinds = [kind for kind in (panels or []) if kind in HUD_PANEL_KINDS]
    if action in {"close", "expand"} and not kinds:
        return f"Diga qual painel. Opções: {', '.join(HUD_PANEL_KINDS)}."

    response = await hud_request(action, kinds)
    if response is None:
        return "O HUD não está conectado, então não consegui mexer nos painéis."

    open_now = _panel_names(response.get("open", []))
    changed = response.get("changed", [])
    if action == "list":
        return f"Painéis abertos no HUD: {open_now}."
    if action == "close_all":
        return f"Fechei {len(changed)} painel(is). O HUD está limpo."
    if action == "collapse":
        return "Painel de volta ao tamanho normal."
    if not changed:
        return f"Não havia painel de {_panel_names(kinds)} aberto. Abertos agora: {open_now}."
    if action == "expand":
        return f"Painel de {_panel_names(changed)} ampliado no centro do HUD."
    return f"Fechei: {_panel_names(changed)}. Continuam abertos: {open_now}."


def build_email_tools(settings: Settings) -> list[Any]:
    def _validate_recipient_policy(to_email: str, cc_email: str | None) -> None:
        allowed = set(settings.effective_allowed_emails)
        recipients = [to_email]
        if cc_email:
            recipients.append(cc_email)

        blocked = [email for email in recipients if email not in allowed]
        if blocked:
            blocked_list = ", ".join(blocked)
            raise PermissionError(
                "Envio bloqueado: destinatário fora da política permitida "
                f"({blocked_list})."
            )

    def _send_pending_email(payload: dict[str, Any]) -> None:
        msg = MIMEMultipart()
        msg["From"] = settings.gmail_user or ""
        msg["To"] = payload["to_email"]
        msg["Subject"] = payload["subject"]

        recipients = [payload["to_email"]]
        if payload.get("cc_email"):
            msg["Cc"] = payload["cc_email"]
            recipients.append(payload["cc_email"])

        msg.attach(MIMEText(payload["message"], "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(settings.gmail_user, settings.gmail_app_password)
            server.sendmail(settings.gmail_user, recipients, msg.as_string())

    @function_tool()
    async def draft_email(
        context: RunContext,
        to_email: str,
        subject: str,
        message: str,
        cc_email: str | None = None,
    ) -> str:
        """Prepare an email draft and require explicit user confirmation before sending."""
        try:
            normalized_to = _validate_email_address(to_email, "to_email")
            normalized_cc = (
                _validate_email_address(cc_email, "cc_email")
                if cc_email
                else None
            )
            trimmed_subject = subject.strip()
            trimmed_message = message.strip()

            if not trimmed_subject:
                return "Não foi possível criar o rascunho: o assunto está vazio."
            if not trimmed_message:
                return "Não foi possível criar o rascunho: a mensagem está vazia."

            _validate_recipient_policy(normalized_to, normalized_cc)

            code = f"{secrets.randbelow(1_000_000):06d}"
            state = _get_session_state(context)
            state[PENDING_EMAIL_KEY] = {
                "code": code,
                "to_email": normalized_to,
                "cc_email": normalized_cc,
                "subject": trimmed_subject,
                "message": trimmed_message,
            }

            preview_lines = [
                "Rascunho pronto.",
                f"Para: {normalized_to}",
            ]
            if normalized_cc:
                preview_lines.append(f"CC: {normalized_cc}")
            preview_lines.extend(
                [
                    f"Assunto: {trimmed_subject}",
                    f"Mensagem: {_truncate(trimmed_message, limit=240)}",
                    f"Código de confirmação: {code}",
                    f"Para enviar, o usuário precisa dizer exatamente: confirmar {code}",
                ]
            )
            await show_card(
                "email",
                {
                    "status": "draft",
                    "to": normalized_to,
                    "cc": normalized_cc,
                    "subject": trimmed_subject,
                    "preview": _truncate(trimmed_message, limit=400),
                    "code": code,
                },
            )
            logger.info("Rascunho de email criado para '%s'.", normalized_to)
            return "\n".join(preview_lines)
        except PermissionError as exc:
            logger.warning("Tentativa bloqueada de criar rascunho de email.")
            return str(exc)
        except ValueError as exc:
            logger.warning("Email rejeitado por validação: %s", exc)
            return f"Não foi possível criar o rascunho: {exc}"
        except Exception:
            logger.exception("Erro inesperado ao criar rascunho de email.")
            return "Ocorreu um erro ao criar o rascunho de email."

    @function_tool()
    async def confirm_email_send(
        context: RunContext,
        code: str,
    ) -> str:
        """Send the last drafted email only after explicit user confirmation."""
        state = _get_session_state(context)
        pending = state.get(PENDING_EMAIL_KEY)
        if not pending:
            return "Não há nenhum email pendente para envio."

        expected_code = pending.get("code")
        normalized_code = code.strip()
        if normalized_code != expected_code:
            logger.warning("Confirmação de email rejeitada por código inválido.")
            return "Código de confirmação inválido. O email não foi enviado."

        last_user_message = _get_last_user_message(context)
        expected_phrase = f"confirmar {expected_code}"
        if last_user_message != expected_phrase:
            logger.warning("Confirmação de email rejeitada por frase inválida.")
            return (
                "Envio bloqueado: o último comando do usuário precisa ser exatamente "
                f"'{expected_phrase}'."
            )

        try:
            await tool_status("confirm_email_send", "running", pending["to_email"])
            await asyncio.to_thread(_send_pending_email, pending)
            state[PENDING_EMAIL_KEY] = None
            await show_card(
                "email",
                {
                    "status": "sent",
                    "to": pending["to_email"],
                    "cc": pending.get("cc_email"),
                    "subject": pending["subject"],
                },
            )
            await tool_status("confirm_email_send", "done", pending["to_email"])
            logger.info("Email enviado para '%s'.", pending["to_email"])
            return f"Email enviado com sucesso para {pending['to_email']}."
        except smtplib.SMTPAuthenticationError:
            logger.exception("Falha de autenticação ao enviar email.")
            await tool_status("confirm_email_send", "error", "autenticação")
            return (
                "Falha ao enviar email: erro de autenticação. "
                "Verifique as credenciais configuradas."
            )
        except smtplib.SMTPException as exc:
            logger.exception("Falha SMTP ao enviar email.")
            await tool_status("confirm_email_send", "error", "SMTP")
            return f"Falha ao enviar email: erro SMTP - {exc}"
        except Exception:
            logger.exception("Erro inesperado ao enviar email.")
            await tool_status("confirm_email_send", "error")
            return "Ocorreu um erro ao enviar o email."

    @function_tool()
    async def cancel_pending_email(
        context: RunContext,
    ) -> str:
        """Cancel the current pending email draft."""
        state = _get_session_state(context)
        pending = state.get(PENDING_EMAIL_KEY)
        if not pending:
            return "Não há nenhum email pendente para cancelar."

        state[PENDING_EMAIL_KEY] = None
        await show_card(
            "email",
            {"status": "cancelled", "to": pending["to_email"], "subject": pending["subject"]},
        )
        logger.info("Rascunho de email cancelado.")
        return "Rascunho de email cancelado com sucesso."

    return [draft_email, confirm_email_send, cancel_pending_email]


def build_tools(settings: Settings) -> list[Any]:
    tools = [
        get_weather,
        search_web,
        search_news,
        get_current_time,
        run_diagnostics,
        set_timer,
        show_on_hud,
        manage_hud_panels,
    ]
    if settings.pc_control_enabled:
        from pc_control import build_pc_tools

        tools.extend(build_pc_tools())
    if settings.email_tool_enabled:
        tools.extend(build_email_tools(settings))
    return tools
