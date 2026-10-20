from __future__ import annotations

import asyncio
import datetime as dt
import difflib
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

from confirmation import (
    confirmation_phrase,
    last_user_message,
    new_code,
    normalize_code,
    session_state,
    spoken_digits,
    strip_accents,
    wait_for_user_confirmation,
)
from hud import hud_request, net_activity, show_card, tool_status
from settings import Settings
from weather import WEATHER_CODES

logger = logging.getLogger("jarvis-tools")

PENDING_EMAIL_KEY = "pending_email"
TIMERS_KEY = "timers"
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
# Palavras que o usuário fala ao ditar um endereço de email.
SPOKEN_EMAIL_SYMBOLS = {
    "@": "@",
    "arroba": "@",
    ".": ".",
    "ponto": ".",
    "dot": ".",
    "underline": "_",
    "underscore": "_",
    "sublinhado": "_",
    "hifen": "-",
    "traco": "-",
    "tracinho": "-",
    "menos": "-",
}
# "arroba gmail" sem "ponto com" -> domínio completo do provedor.
EMAIL_PROVIDER_DOMAINS = {
    "gmail": "gmail.com",
    "hotmail": "hotmail.com",
    "outlook": "outlook.com",
    "live": "live.com",
    "yahoo": "yahoo.com",
    "icloud": "icloud.com",
    "uol": "uol.com.br",
    "bol": "bol.com.br",
    "terra": "terra.com.br",
}
SPELLED_EMAIL_SYMBOLS = {"@": " arroba ", ".": " ponto ", "_": " underline ", "-": " hífen "}
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

# Mantém referência aos timers ativos para que não sejam coletados pelo GC.
_TIMER_TASKS: set[asyncio.Task[None]] = set()
_SESSION_TASKS: set[asyncio.Task[None]] = set()


class CityNotFoundError(LookupError):
    """Raised when the geocoding API finds no match for a city."""


def _truncate(value: str, limit: int = 180) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3].rstrip()}..."


def assemble_email_address(spoken: str) -> str | None:
    """Build an address from dictation: "gabriel m zavarise arroba gmail ponto com".

    Typed addresses pass through. Periods glued to words before the @ ("M.") are the
    transcriber's abbreviation marks, so only the spoken "ponto" becomes a dot there.
    """
    text = re.sub(r"\s+", " ", strip_accents(spoken).lower()).strip()
    compact = text.strip(" .,;:!?")
    if EMAIL_PATTERN.match(compact):
        return compact

    pieces: list[str] = []
    in_domain = False
    for raw in text.split(" "):
        word = raw.strip(",;:!?\"'()<>")
        if word in SPOKEN_EMAIL_SYMBOLS:
            symbol = SPOKEN_EMAIL_SYMBOLS[word]
            in_domain = in_domain or symbol == "@"
            pieces.append(symbol)
            continue
        if "@" in word:
            in_domain = True
        elif not in_domain:
            word = word.strip(".")
        pieces.append(re.sub(r"[^a-z0-9._%+@-]", "", word))

    address = "".join(pieces).strip(".")
    local, _, domain = address.partition("@")
    if domain in EMAIL_PROVIDER_DOMAINS:
        address = f"{local}@{EMAIL_PROVIDER_DOMAINS[domain]}"
    return address if EMAIL_PATTERN.match(address) else None


def spell_email_address(address: str) -> str:
    """"joao.silva@gmail.com" -> "joao ponto silva arroba gmail ponto com" (para ler em voz alta)."""
    spelled = "".join(SPELLED_EMAIL_SYMBOLS.get(ch, ch) for ch in address)
    return re.sub(r"\s+", " ", spelled).strip()


def _validate_email_address(email: str, field_name: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} não pode ser vazio.")
    normalized = assemble_email_address(normalized) or normalized
    if not EMAIL_PATTERN.match(normalized):
        raise ValueError(f"{field_name} precisa ser um email válido.")
    return normalized


def _get_session_state(context: RunContext) -> dict[str, Any]:
    return session_state(context)


def _get_last_user_message(context: RunContext) -> str | None:
    return last_user_message(context)


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


# Horas de previsão no gráfico do painel Meteorologia.
HOURLY_POINTS = 24


def _parse_hourly_forecast(hourly: Any) -> list[dict[str, Any]]:
    """Next hours for the temperature chart of the weather panel; [] when the API sent none."""
    if not isinstance(hourly, dict):
        return []
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    rain = hourly.get("precipitation_probability") or []
    points = []
    for index, moment in enumerate(times[:HOURLY_POINTS]):
        if index >= len(temps) or temps[index] is None:
            break
        points.append({"time": moment, "temp": temps[index], "rain": rain[index] if index < len(rain) else None})
    return points


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
            "hourly": "temperature_2m,precipitation_probability",
            "forecast_hours": HOURLY_POINTS,
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
        "hourly": _parse_hourly_forecast(weather_data.get("hourly")),
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


def _session_timers(context: RunContext) -> dict[str, dict[str, Any]]:
    state = _get_session_state(context)
    timers = state.get(TIMERS_KEY)
    if not isinstance(timers, dict):
        timers = {}
        state[TIMERS_KEY] = timers
    return timers


def _human_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs and not hours:
        parts.append(f"{secs} s")
    return " e ".join(parts) or "0 s"


async def _finish_timer(context: RunContext, timer_id: str, label: str, seconds: float) -> None:
    await asyncio.sleep(seconds)
    timer = _session_timers(context).get(timer_id)
    if timer is not None:
        timer["status"] = "done"
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
    ends_at = time.time() + seconds
    ends_at_ms = int(ends_at * 1000)
    _session_timers(context)[timer_id] = {
        "label": clean_label,
        "ends_at": ends_at,
        "duration_s": seconds,
        "status": "running",
    }

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
    from presence import note_soon

    # O fim vai para o resumo de "bem-vindo de volta" (PRS-25), mesmo se esta conversa acabar antes.
    ends = dt.datetime.fromtimestamp(ends_at).strftime("%H:%M")
    await note_soon(f"o timer '{clean_label}' terminou às {ends}", ends_at)

    if seconds < 60:
        human = f"{int(seconds)} segundos"
    else:
        human = f"{round(minutes, 1):g} minutos"
    return f"Timer '{clean_label}' iniciado para {human}."


@function_tool()
async def get_timers(context: RunContext) -> str:
    """Tell how much time is left on each timer of this conversation (label and remaining time).

    Use it whenever the user asks about a timer ("quanto tempo falta?", "o timer já acabou?")
    instead of guessing.
    """
    timers = _session_timers(context)
    if not timers:
        return "Nenhum timer foi criado nesta conversa."

    now = time.time()
    running = []
    finished = []
    for timer in sorted(timers.values(), key=lambda item: item["ends_at"]):
        remaining = timer["ends_at"] - now
        if timer["status"] == "running" and remaining > 0:
            ends = dt.datetime.fromtimestamp(timer["ends_at"]).strftime("%H:%M")
            running.append(f"'{timer['label']}': faltam {_human_duration(remaining)} (termina às {ends})")
        else:
            finished.append(f"'{timer['label']}' terminou há {_human_duration(-remaining)}")

    parts = ["Timers ativos: " + "; ".join(running) + "." if running else "Nenhum timer ativo agora."]
    if finished:
        parts.append("Já terminaram: " + "; ".join(finished[-3:]) + ".")
    return " ".join(parts)


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


# Título exibido em cada tipo de painel do HUD (web/src/lib/panels.ts → PANEL_META).
HUD_PANEL_KINDS = {
    "weather": "Meteorologia",
    "search": "Pesquisa",
    "news": "Notícias",
    "time": "Cronometria",
    "diagnostics": "Diagnóstico",
    "timer": "Timer",
    "note": "Nota",
    "email": "Email",
    "media": "Reprodução",
    "screen": "Leitura de tela",
    "install": "Instalação de app",
    "camera": "Câmera",
    "pointer": "Mouse e teclado",
    "memory": "Memória",
    "explain": "Assistente de tela",
    "routine": "Rotina",
    "calendar": "Agenda",
}
LAST_PANEL = "last"
MAX_PANEL_TARGETS = 6
_PANEL_VERBS = {"close": "fechado", "close_all": "fechado", "expand": "ampliado", "collapse": "reduzido"}


def _panel_label(panel: Any) -> str:
    """'Leitura de tela (tela 2) [screen]' from the HUD reply; older HUD builds sent bare kinds."""
    if isinstance(panel, str):
        return f"{HUD_PANEL_KINDS.get(panel, panel)} [{panel}]"
    if not isinstance(panel, dict):
        return str(panel)
    kind = str(panel.get("kind") or "")
    title = str(panel.get("title") or HUD_PANEL_KINDS.get(kind, kind))
    extras = [str(panel["detail"])] if panel.get("detail") else []
    if panel.get("expanded"):
        extras.append("ampliado")
    label = f"{title} ({', '.join(extras)})" if extras else title
    return f"{label} [{kind}]" if kind else label


def _panel_list(panels: Any) -> str:
    if not isinstance(panels, list) or not panels:
        return "nenhum"
    return "; ".join(_panel_label(panel) for panel in panels)


@function_tool()
async def manage_hud_panels(
    context: RunContext,
    action: Literal["list", "close", "close_all", "expand", "collapse"],
    panels: list[str] | None = None,
) -> str:
    """List, close, expand (enlarge) or collapse the panels of the user's holographic HUD.

    The user calls these panels "abas", "abinhas", "painéis", "janelas" or "telas"; they sit
    in the left column of the HUD. They are NOT browser tabs, and closing one never means
    pausing media.

    Args:
        action: list (what is open, newest first, with the title shown on each panel), close,
            close_all, expand (enlarge one panel in the center of the HUD) or collapse.
        panels: Which panels. Each item is a kind (weather, search, news, time, diagnostics,
            timer, note, email, media, screen, install, camera, pointer, memory, explain), words of the title/subject shown on the panel
            ("Leitura de tela", "Reprodução", "lista de compras estrogonofe") or "last" for the
            most recent panel. Without panels, close and expand act on the most recent panel.
    """
    targets = [str(item).strip()[:80] for item in (panels or []) if str(item).strip()][:MAX_PANEL_TARGETS]
    if action in {"close", "expand"} and not targets:
        targets = [LAST_PANEL]

    # "kinds" mantém compatível um HUD compilado antes dos títulos (python jarvis.py --rebuild).
    response = await hud_request(
        action, {"targets": targets, "kinds": [target for target in targets if target in HUD_PANEL_KINDS]}
    )
    if response is None:
        if action == "list":
            return "Não sei quais painéis estão abertos: o HUD não está conectado."
        return f"NADA foi {_PANEL_VERBS[action]}: o HUD não está conectado. Não diga que conseguiu."

    open_panels = response.get("open") or []
    open_now = _panel_list(open_panels)
    changed = response.get("changed") or []
    if action == "list":
        if not open_panels:
            return "Nenhum painel aberto no HUD."
        return f"Painéis abertos no HUD, do mais recente ao mais antigo: {open_now}."

    if not changed:
        verb = _PANEL_VERBS[action]
        if action == "collapse":
            reason = "nenhum painel estava ampliado"
        elif not open_panels:
            reason = "não há nenhum painel aberto no HUD"
        else:
            wanted = ", ".join(f"'{target}'" for target in targets)
            reason = f"nenhum painel aberto corresponde a {wanted}"
        return f"NADA foi {verb}: {reason}. Painéis abertos agora: {open_now}. Não diga ao usuário que foi {verb}."

    if action == "close_all":
        return f"Fechados {len(changed)} painel(is): {_panel_list(changed)}. O HUD está limpo."
    if action == "collapse":
        return f"Voltou ao tamanho normal: {_panel_list(changed)}."
    if action == "expand":
        return f"Ampliado no centro do HUD: {_panel_list(changed)}."

    result = f"Fechado no HUD: {_panel_list(changed)}. Continuam abertos: {open_now}."
    unmatched = [str(item) for item in response.get("unmatched") or []]
    if unmatched:
        result += f" Não encontrei painel para: {', '.join(unmatched)}."
    return result


# Personas do HUD (web/src/lib/themes.ts, personas.py) e como o usuário costuma chamá-las
# (inclusive como o reconhecimento de voz escreve "Friday" e "Mark").
HUD_THEMES = {
    "jarvis": ("jarvis", "padrao", "normal", "original", "azul", "ciano", "classico"),
    "mark3": (
        "mark3", "mark 3", "mark iii", "marc 3", "marca 3", "homem de ferro", "iron man", "armadura",
        "tatico", "vermelho", "dourado", "ouro",
    ),
    "friday": ("friday", "fraide", "fraidei", "fraidey", "sexta-feira", "sexta feira", "roxo", "violeta", "lilas", "rosa"),
    "stealth": ("stealth", "stelf", "furtivo", "discreto", "silencioso", "prata", "branco", "cinza", "neutro"),
}
HUD_THEME_NAMES = {"jarvis": "J.A.R.V.I.S.", "mark3": "Mark III", "friday": "F.R.I.D.A.Y.", "stealth": "Stealth"}


def match_hud_theme(text: str) -> str | None:
    # "F.R.I.D.A.Y." / "J.A.R.V.I.S." como o HUD escreve.
    folded = re.sub(r"[^a-z0-9 -]", "", strip_accents(text).lower()).strip()
    for theme, names in HUD_THEMES.items():
        if folded == theme or any(name in folded for name in names):
            return theme
    return None


@function_tool()
async def set_hud_appearance(
    context: RunContext,
    theme: str | None = None,
    cinema: bool | None = None,
) -> str:
    """Change the HUD persona (theme) and/or the cinema mode.

    Each theme is a whole persona: the HUD look (core, rings, panels, sounds) AND the assistant's
    persona and voice, which switch right after your confirmation. "Chama a Friday" = friday,
    "modo Mark III"/"modo armadura" = mark3, "modo discreto" = stealth, "volta o Jarvis" = jarvis.

    Args:
        theme: Persona by name or colour: "jarvis" (cyan, the British butler, the default),
            "mark3" (gold and red, Jarvis inside the Iron Man armour, terse mission reports),
            "friday" (violet, F.R.I.D.A.Y.: female voice, direct and warm, calls the user "chefe")
            or "stealth" (silver, whispered minimal answers). Omit to keep it.
        cinema: true hides every panel and leaves only the core and the live caption ("modo
            cinema", "modo foco", "esconde os painéis"); false brings the full HUD back.
    """
    wanted = None
    if theme:
        wanted = match_hud_theme(theme)
        if wanted is None:
            options = ", ".join(HUD_THEME_NAMES.values())
            return f"NADA mudou: não conheço o tema '{theme}'. Temas do HUD: {options}."
    if wanted is None and cinema is None:
        return "Diga o tema (J.A.R.V.I.S., Mark III, F.R.I.D.A.Y. ou Stealth) ou se é para ligar o modo cinema."

    response = await hud_request("appearance", {"theme": wanted, "cinema": cinema})
    if response is None:
        return "NADA mudou: o HUD não está conectado. Não diga que conseguiu."
    if response.get("error"):
        return "NADA mudou: este HUD é de uma versão anterior. Peça para rodar python jarvis.py --rebuild."
    parts = []
    if wanted:
        name = HUD_THEME_NAMES.get(str(response.get("theme")), response.get("theme"))
        parts.append(
            f"Persona do HUD agora: {name}. O jeito e a voz de {name} assumem logo depois desta "
            "resposta (ela se apresenta sozinha): confirme em UMA frase curta, ainda com o seu jeito atual"
        )
    if cinema is not None:
        parts.append("modo cinema ligado (só o núcleo e a legenda)" if response.get("cinema") else "modo cinema desligado")
    return ". ".join(parts) + "."


# ───────────────────────── microphone ─────────────────────────


def _windows_default_audio() -> dict[str, str]:
    """Names of the Windows default input/output devices (pycaw); {} when unavailable."""
    if os.name != "nt":
        return {}
    try:
        import warnings

        import comtypes
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        return {}

    devices: dict[str, str] = {}
    comtypes.CoInitialize()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for role, getter in (("entrada", AudioUtilities.GetMicrophone), ("saída", AudioUtilities.GetSpeakers)):
                try:
                    device = getter()
                    if not hasattr(device, "FriendlyName"):
                        device = AudioUtilities.CreateDevice(device)
                    if device is not None and device.FriendlyName:
                        devices[role] = str(device.FriendlyName)
                except Exception:
                    logger.debug("Não foi possível ler o dispositivo de %s padrão.", role, exc_info=True)
    finally:
        comtypes.CoUninitialize()
    return devices


def _seconds_ago(seconds: Any) -> str | None:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return None
    return "agora há pouco" if seconds < 2 else f"há {_human_duration(seconds)}"


def _describe_microphone(mic: dict[str, Any]) -> str:
    label = str(mic.get("label") or "").strip()
    text = "Microfone selecionado no HUD: " + (f"'{label}'" if label else "sem nome (o navegador não informou)")
    if mic.get("is_default"):
        text += ", o padrão do sistema"
    text += "."
    if not mic.get("enabled"):
        text += " Ele está MUDO no HUD (botão de microfone desligado)."
    else:
        signal = _seconds_ago(mic.get("signal_s"))
        heard = _seconds_ago(mic.get("heard_s"))
        text += f" O navegador recebeu som dele {signal}." if signal else " O navegador ainda não recebeu som dele."
        if heard:
            text += f" Eu ouvi sua voz pela última vez {heard}."
    others = [str(name) for name in mic.get("available") or [] if name and str(name) != label]
    if others:
        text += f" Outros microfones disponíveis: {', '.join(others[:5])}."
    return text


@function_tool()
async def check_microphone(context: RunContext) -> str:
    """Tell which microphone the user is talking through and whether it is picking up sound.

    Reads the microphone selected in the HUD's "Sistema" panel (the one this conversation
    uses), whether it is muted and when sound last came from it, plus the Windows default
    input and output devices (names only).
    """
    await tool_status("check_microphone", "running")
    reply = await hud_request("mic")
    try:
        windows = await asyncio.to_thread(_windows_default_audio)
    except Exception:
        logger.debug("Falha ao consultar os dispositivos de áudio do Windows.", exc_info=True)
        windows = {}

    mic = reply.get("mic") if reply else None
    if reply is None:
        parts = ["Não consegui consultar o HUD, então não sei qual microfone está selecionado nele."]
    elif not isinstance(mic, dict):
        parts = ["O HUD não informou o microfone (talvez esteja desatualizado: python jarvis.py --rebuild)."]
    else:
        parts = [_describe_microphone(mic)]
    if windows:
        defaults = ", ".join(f"{role} '{name}'" for role, name in windows.items())
        parts.append(f"Padrões do Windows: {defaults}.")

    await tool_status("check_microphone", "done" if mic or windows else "error")
    return " ".join(parts)


# ───────────────────────── end of session ─────────────────────────

FAREWELL_START_TIMEOUT_S = 6.0
FAREWELL_PLAYOUT_TIMEOUT_S = 30.0
# O fim da despedida ainda está chegando ao navegador quando o agente termina de falar.
FAREWELL_AUDIO_TAIL_S = 0.8


def _spawn(coro: Any) -> asyncio.Task[None]:
    task = asyncio.create_task(coro)
    _SESSION_TASKS.add(task)
    task.add_done_callback(_SESSION_TASKS.discard)
    return task


def _tool_reply_is_new_speech(session: Any) -> bool:
    """Realtime models (Gemini Live) answer a tool result in a new speech; pipelines reuse the tool's."""
    try:
        return bool(session.current_agent.realtime_llm_session.capabilities.auto_tool_reply_generation)
    except Exception:
        return False


async def _wait_for_farewell(session: Any) -> None:
    """Wait for the agent's next speech (the goodbye) to finish playing."""
    created: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

    def _on_speech_created(event: Any) -> None:
        if not created.done():
            created.set_result(event.speech_handle)

    session.on("speech_created", _on_speech_created)
    try:
        handle = await asyncio.wait_for(created, FAREWELL_START_TIMEOUT_S)
        await asyncio.wait_for(handle.wait_for_playout(), FAREWELL_PLAYOUT_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("A despedida não terminou a tempo; encerrando a sessão assim mesmo.")
    finally:
        session.off("speech_created", _on_speech_created)


async def _hang_up(session: Any, wait_for_farewell: bool) -> None:
    """Close the link like the HUD's "Encerrar link" button, once Jarvis said goodbye."""
    if wait_for_farewell:
        await _wait_for_farewell(session)
    await asyncio.sleep(FAREWELL_AUDIO_TAIL_S)
    await tool_status("end_session", "done")
    reply = await hud_request("end_session")
    if reply and reply.get("ended"):
        logger.info("O HUD encerrou o link a pedido do usuário.")
        return
    logger.info("O HUD não encerrou o link; encerrando a sessão pelo agente.")
    session.shutdown()


@function_tool()
async def end_session(context: RunContext) -> str:
    """End this conversation: say goodbye and close the link with the HUD ("Encerrar link").

    Call it when the user says goodbye or tells Jarvis to switch itself off: "tchau, Jarvis",
    "até mais", "desligar", "pode desligar", "desliga, Jarvis", "encerrar", "encerra a sessão".
    It does NOT shut down, restart or lock the computer.
    """
    await tool_status("end_session", "running")
    session = context.session
    handle = getattr(context, "speech_handle", None)
    if handle is None:
        _spawn(_hang_up(session, wait_for_farewell=True))
    else:
        wait_for_farewell = _tool_reply_is_new_speech(session)
        handle.add_done_callback(lambda _: _spawn(_hang_up(session, wait_for_farewell)))
    logger.info("Encerramento da sessão pedido pelo usuário.")
    return (
        "O link com o HUD será encerrado assim que você terminar de falar. Despeça-se agora em UMA "
        "frase curta (ex.: 'Até logo, senhor.'), sem perguntas. O computador continua ligado."
    )


def build_email_tools(settings: Settings) -> list[Any]:
    def _closest_allowed(address: str) -> str | None:
        """The authorized address the transcriber probably meant ("zavarise" -> "zavarize")."""
        matches = difflib.get_close_matches(address, settings.effective_allowed_emails, n=1, cutoff=0.8)
        return matches[0] if matches else None

    def _validate_recipient_policy(to_email: str, cc_email: str | None) -> None:
        allowed = set(settings.effective_allowed_emails)
        recipients = [to_email]
        if cc_email:
            recipients.append(cc_email)

        blocked = [email for email in recipients if email not in allowed]
        if blocked:
            blocked_list = ", ".join(blocked)
            hints = [
                f" Você quis dizer {suggestion}? Confirme com o usuário antes de rascunhar de novo."
                for suggestion in (_closest_allowed(email) for email in blocked)
                if suggestion
            ]
            raise PermissionError(
                "Envio bloqueado: destinatário fora da política permitida "
                f"({blocked_list})." + "".join(hints)
            )

    @function_tool()
    async def check_email_address(
        context: RunContext,
        spoken_address: str,
    ) -> str:
        """Assemble an email address the user dictated and check it before drafting.

        Call it whenever the address was spoken ("gabriel m silva arroba gmail ponto com").
        Read the assembled address back to the user and only call draft_email after they
        confirm it.

        Args:
            spoken_address: Exactly what the user said for the address.
        """
        address = assemble_email_address(spoken_address)
        if not address:
            return (
                f"Não consegui montar um email válido a partir de '{_truncate(spoken_address, 80)}'. "
                "Peça para o usuário soletrar o endereço dizendo 'arroba' e 'ponto'."
            )

        allowed = address in settings.effective_allowed_emails
        suggestion = None if allowed else _closest_allowed(address)
        await show_card(
            "email",
            {"status": "address", "to": address, "allowed": allowed, "suggestion": suggestion},
        )
        lines = [f"Endereço montado: {address}", f"Para ler em voz alta: {spell_email_address(address)}"]
        if allowed:
            lines.append(
                "Está na lista de destinatários autorizados. Confirme o endereço com o usuário "
                "e só então chame draft_email."
            )
        elif suggestion:
            lines.append(
                f"Não está na lista autorizada. O autorizado mais parecido é {suggestion} "
                f"({spell_email_address(suggestion)}): pergunte se é esse e use o que o usuário confirmar."
            )
        else:
            lines.append(
                "Não está na lista de destinatários autorizados (JARVIS_ALLOWED_EMAILS): "
                "um email para ele seria bloqueado."
            )
        return "\n".join(lines)

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
        """Prepare an email draft and require explicit user confirmation before sending.

        After it, tell the user the confirmation code digit by digit, say it is also on
        the HUD email panel, and explain that to send they must say "confirmar" + the code.

        Args:
            to_email: Recipient address (a dictated one is assembled; confirm it first with
                check_email_address).
            subject: Email subject.
            message: Email body.
            cc_email: Optional CC address.
        """
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

            code = new_code()
            state = _get_session_state(context)
            state[PENDING_EMAIL_KEY] = {
                "code": code,
                "to_email": normalized_to,
                "cc_email": normalized_cc,
                "subject": trimmed_subject,
                "message": trimmed_message,
            }

            preview_lines = [
                "Rascunho pronto (ainda NÃO enviado).",
                f"Para: {normalized_to}",
            ]
            if normalized_cc:
                preview_lines.append(f"CC: {normalized_cc}")
            preview_lines.extend(
                [
                    f"Assunto: {trimmed_subject}",
                    f"Mensagem: {_truncate(trimmed_message, limit=240)}",
                    f"Código de confirmação: {code} (fale dígito por dígito: {spoken_digits(code)}).",
                    "O código também aparece no painel de email do HUD.",
                    f"Para enviar, o usuário precisa dizer: {confirmation_phrase('email', code)}. "
                    "'Pode ir', 'manda' ou 'sim' não enviam: nesse caso repita o código e a frase.",
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
        """Send the last drafted email only after explicit user confirmation.

        Call it only when the user's latest words were "confirmar" followed by the code.

        Args:
            code: The 6-digit confirmation code the user said.
        """
        state = _get_session_state(context)
        pending = state.get(PENDING_EMAIL_KEY)
        if not pending:
            return "Não há nenhum email pendente para envio."

        expected_code = pending.get("code")
        if normalize_code(code) != expected_code:
            logger.warning("Confirmação de email rejeitada por código inválido.")
            return "Código de confirmação inválido. O email não foi enviado."

        confirmed, _ = await wait_for_user_confirmation(context, "email", expected_code)
        if not confirmed:
            logger.warning("Confirmação de email rejeitada: a última fala não tinha a frase com o código.")
            return (
                "Envio bloqueado: a última fala do usuário não foi a confirmação com o código. "
                f"Repita o código ({spoken_digits(expected_code)}) e peça para ele dizer: "
                f"{confirmation_phrase('email', expected_code)}."
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

    return [check_email_address, draft_email, confirm_email_send, cancel_pending_email]


def build_tools(settings: Settings) -> list[Any]:
    tools = [
        get_weather,
        search_web,
        search_news,
        get_current_time,
        run_diagnostics,
        set_timer,
        get_timers,
        show_on_hud,
        manage_hud_panels,
        set_hud_appearance,
        check_microphone,
        end_session,
    ]
    from voices import build_voice_tools

    tools.extend(build_voice_tools(settings))
    if settings.memory_enabled:
        from memory import build_memory_tools

        tools.extend(build_memory_tools())
    if settings.routines_enabled:
        from routines import build_routine_tools

        tools.extend(build_routine_tools())
    if settings.pc_control_enabled:
        from pc_control import build_pc_tools

        tools.extend(build_pc_tools())
        import screen_assist

        screen_assist.configure(settings.google_api_key, settings.computer_use_model)
        tools.extend(screen_assist.build_screen_assist_tools())
    if settings.gestures_enabled:
        from gestures import build_gesture_tools

        tools.extend(build_gesture_tools())
    if settings.email_tool_enabled:
        tools.extend(build_email_tools(settings))
    if settings.calendar_enabled:
        from calendar_tools import build_calendar_tools

        tools.extend(build_calendar_tools())
    if settings.app_install_enabled:
        from installer import build_install_tools

        tools.extend(build_install_tools())
    if settings.camera_enabled:
        from vision import build_camera_tools

        tools.extend(build_camera_tools())
    if settings.presence_enabled:
        from presence import build_presence_tools

        tools.extend(build_presence_tools())
    if settings.computer_use_enabled:
        from computer_use import build_computer_use_tools

        tools.extend(build_computer_use_tools(settings.google_api_key, settings.computer_use_model))
        from dictation import build_dictation_tools

        tools.extend(build_dictation_tools())

    if settings.proactive_enabled:
        from proactive import build_proactive_tools

        tools.extend(build_proactive_tools())
    return tools
