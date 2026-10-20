"""Painel de saúde (SAU-40): histórico local para calibrar o Jarvis com números, não no olho.

O agente, o detector da palavra de ativação e o próprio HUD mandam pequenos eventos ao servidor
(tempo de resposta, ferramenta que falhou, modelo que pausou, "Jarvis" quase ouvido...). O servidor
guarda tudo em ``saude.db`` (SQLite, fora do git), apaga o que passa de ``RETENTION_DAYS`` e
resume a janela pedida para o painel do HUD, com sugestões de ajuste do ``.env``.

Nenhum evento leva texto da conversa: só nomes (ferramenta, modelo, palavra), números e a
mensagem curta de erro da ferramenta.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import statistics
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("jarvis-health")

DB_FILE = Path(__file__).with_name("saude.db")
API_PREFIX = "/api/health"
RETENTION_DAYS = 30
MAX_EVENTS = 50_000
# A limpeza roda a cada tantas gravações, não a cada uma.
PRUNE_EVERY = 200
DAY_S = 24 * 60 * 60

# Regras das sugestões.
SILENT_WAKES = 3
NEAR_WAKES = 5
LATENCY_MIN_SAMPLES = 5
LATENCY_WORSE_RATIO = 1.25
LATENCY_WORSE_S = 0.3
TOOL_ERRORS = 3
QUOTA_PAUSES = 3
MEMORY_MIN_SEARCHES = 5
MEMORY_EMPTY_RATIO = 0.4
THRESHOLD_STEP = 0.05


@dataclass(frozen=True, slots=True)
class Event:
    ts: float
    kind: str
    key: str
    value: float | None = None
    detail: str | None = None


class HealthStore:
    """Events in SQLite; one connection per call, so the server threads never share one."""

    def __init__(self, path: Path | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self.path = path or DB_FILE
        self.clock = clock
        self._lock = threading.Lock()
        self._writes = 0
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        if not self._ready:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, "
                "value REAL, detail TEXT)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS events_ts ON events (ts)")
            self._ready = True
        return connection

    def add(self, kind: str, key: str, value: float | None = None, detail: str | None = None, ts: float | None = None) -> None:
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO events (ts, kind, key, value, detail) VALUES (?, ?, ?, ?, ?)",
                        (self.clock() if ts is None else ts, kind, key[:64], value, (detail or None) and detail[:200]),
                    )
                    self._writes += 1
                    if (self._writes - 1) % PRUNE_EVERY == 0:
                        self._prune(connection)
            except sqlite3.Error:
                logger.debug("Não consegui gravar o evento de saúde %s.", kind, exc_info=True)

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM events WHERE ts < ?", (self.clock() - RETENTION_DAYS * DAY_S,))
        connection.execute(
            "DELETE FROM events WHERE id <= (SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?)", (MAX_EVENTS,)
        )

    def events(self, since: float) -> list[Event]:
        with self._lock:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT ts, kind, key, value, detail FROM events WHERE ts >= ? ORDER BY ts", (since,)
                    ).fetchall()
            except sqlite3.Error:
                logger.debug("Não consegui ler %s.", self.path, exc_info=True)
                return []
        return [Event(*row) for row in rows]

    def clear(self) -> None:
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute("DELETE FROM events")
            except sqlite3.Error:
                logger.debug("Não consegui limpar %s.", self.path, exc_info=True)


# --- Resumo e sugestões ---------------------------------------------------------------------------


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " s"


def _word_label(word: str) -> str:
    return word.capitalize()


def summarize(
    events: Iterable[Event],
    *,
    now: float,
    days: int,
    wake_thresholds: Mapping[str, float],
    min_similarity: float,
) -> dict[str, Any]:
    """What the SAU-40 panel draws, plus the calibration hints, for the last ``days`` days."""
    since = now - days * DAY_S
    events = [event for event in events if event.ts >= since]

    latency = [event for event in events if event.kind == "latency" and event.value is not None]
    by_day: dict[str, list[float]] = defaultdict(list)
    for event in latency:
        by_day[_day(event.ts)].append(float(event.value))  # type: ignore[arg-type]
    last24 = [float(e.value) for e in latency if e.ts >= now - DAY_S]  # type: ignore[arg-type]
    prev24 = [float(e.value) for e in latency if now - 2 * DAY_S <= e.ts < now - DAY_S]  # type: ignore[arg-type]

    tool_errors: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.kind == "tool_error":
            tool_errors[event.key].append(event)

    pauses = Counter((event.key, event.detail or "error") for event in events if event.kind == "model_pause")
    switches = sum(1 for event in events if event.kind == "model_switch")

    words = sorted({*wake_thresholds, *(e.key for e in events if e.kind.startswith("wake"))})
    wake = []
    for word in words:
        mine = [event for event in events if event.key == word]
        near = [float(e.value) for e in mine if e.kind == "wake_near" and e.value is not None]
        wake.append(
            {
                "word": word,
                "threshold": wake_thresholds.get(word),
                "activations": sum(1 for e in mine if e.kind == "wake"),
                "silent": sum(1 for e in mine if e.kind == "wake_silent"),
                "near": len(near),
                "near_best": round(max(near), 2) if near else None,
            }
        )

    searches = [event for event in events if event.kind == "memory_search"]
    found = [float(e.value) for e in searches if e.value is not None]
    memory = {
        "searches": len(searches),
        "empty": sum(1 for e in searches if e.key == "nada"),
        "average": round(statistics.fmean(found), 2) if found else None,
        "min_similarity": min_similarity,
    }

    summary = {
        "days": days,
        "events": len(events),
        "latency": {
            "daily": [{"day": day, "median": _median(values), "count": len(values)} for day, values in sorted(by_day.items())],
            "last24": _median(last24),
            "prev24": _median(prev24),
            "count": len(latency),
        },
        "tools": sorted(
            ({"name": name, "errors": len(items), "last": items[-1].detail} for name, items in tool_errors.items()),
            key=lambda item: -item["errors"],
        ),
        "models": {
            "pauses": [
                {"model": model, "reason": reason, "count": count} for (model, reason), count in pauses.most_common()
            ],
            "switches": switches,
        },
        "wake": wake,
        "memory": memory,
    }
    summary["suggestions"] = suggestions(summary, latency_samples=(len(last24), len(prev24)))
    return summary


def suggestions(summary: Mapping[str, Any], *, latency_samples: tuple[int, int]) -> list[dict[str, str]]:
    """Plain hints like "o Friday ativou 4 vezes sem você falar: suba JARVIS_WAKE_THRESHOLD_FRIDAY"."""
    hints: list[dict[str, str]] = []
    period = "hoje" if summary["days"] == 1 else f"em {summary['days']} dias"

    for item in summary["wake"]:
        word, threshold = item["word"], item["threshold"]
        env = f"JARVIS_WAKE_THRESHOLD_{word.upper()}"
        if item["silent"] >= SILENT_WAKES:
            target = f" para {min(0.95, threshold + 2 * THRESHOLD_STEP):.2f}" if threshold is not None else ""
            hints.append(
                {
                    "level": "warn",
                    "area": "wake",
                    "text": f"O “{_word_label(word)}” ativou {item['silent']} vezes sem você falar {period}: suba {env}{target}.",
                }
            )
        elif item["near"] >= NEAR_WAKES and item["near"] >= 2 * max(1, item["activations"]):
            target = f" para {max(0.1, threshold - THRESHOLD_STEP):.2f}" if threshold is not None else ""
            hints.append(
                {
                    "level": "info",
                    "area": "wake",
                    "text": f"O “{_word_label(word)}” quase ativou {item['near']} vezes {period}: se era você chamando, desça {env}{target}.",
                }
            )

    latency = summary["latency"]
    last, prev = latency["last24"], latency["prev24"]
    if (
        min(latency_samples) >= LATENCY_MIN_SAMPLES
        and last is not None
        and prev is not None
        and last >= prev * LATENCY_WORSE_RATIO
        and last - prev >= LATENCY_WORSE_S
    ):
        hints.append(
            {
                "level": "warn",
                "area": "latency",
                "text": f"O tempo de resposta piorou desde ontem: mediana de {_seconds(prev)} para {_seconds(last)}.",
            }
        )

    for tool in summary["tools"]:
        if tool["errors"] >= TOOL_ERRORS:
            last_error = f": último erro “{tool['last']}”" if tool["last"] else ""
            hints.append(
                {"level": "warn", "area": "tools", "text": f"A ferramenta {tool['name']} falhou {tool['errors']} vezes {period}{last_error}."}
            )

    quota = Counter()
    for pause in summary["models"]["pauses"]:
        if pause["reason"] == "quota":
            quota[pause["model"]] += pause["count"]
    for model, count in quota.items():
        if count >= QUOTA_PAUSES:
            hints.append(
                {
                    "level": "info",
                    "area": "models",
                    "text": f"O {model} pausou por cota {count} vezes {period}: ponha um reserva em GOOGLE_FALLBACK_MODELS "
                    "ou ligue o rodízio com JARVIS_MODEL_ROTATION=rotate.",
                }
            )

    memory = summary["memory"]
    if memory["searches"] >= MEMORY_MIN_SEARCHES and memory["empty"] / memory["searches"] >= MEMORY_EMPTY_RATIO:
        hints.append(
            {
                "level": "info",
                "area": "memory",
                "text": f"{memory['empty']} de {memory['searches']} buscas na memória não acharam nada: se o fato existia, "
                f"desça JARVIS_MEMORY_MIN_SIMILARITY (hoje {memory['min_similarity']:.2f}).",
            }
        )
    return hints


# --- Envio dos eventos (agente e detector) --------------------------------------------------------


def _hud_url() -> str:
    from settings import DEFAULT_HUD_URL

    return (os.environ.get("JARVIS_HUD_URL") or DEFAULT_HUD_URL).rstrip("/")


def _post(url: str, body: dict[str, Any]) -> None:
    try:
        requests.post(url, json=body, timeout=2)
    except requests.RequestException:
        pass  # servidor fora do ar: o evento se perde, o Jarvis segue


def report(
    kind: str,
    key: str,
    value: float | None = None,
    detail: str | None = None,
    *,
    base_url: str | None = None,
    post: Callable[[str, dict[str, Any]], None] | None = None,
) -> None:
    """Send one event to the server without waiting (a thread per event; they are rare)."""
    body: dict[str, Any] = {"kind": kind, "key": key or "?"}
    if value is not None:
        body["value"] = round(float(value), 3)
    if detail:
        body["detail"] = str(detail)[:200]
    url = f"{(base_url or _hud_url()).rstrip('/')}{API_PREFIX}/event"
    threading.Thread(target=post or _post, args=(url, body), daemon=True).start()


# --- Rotas ----------------------------------------------------------------------------------------


class HealthEvent(BaseModel):
    # "wake" não entra: quem grava a ativação é o próprio servidor, ao receber o aviso do detector.
    kind: Literal["latency", "tool_error", "model_pause", "model_switch", "wake_near", "wake_silent", "memory_search"]
    key: str = Field(min_length=1, max_length=64)
    value: float | None = Field(default=None, ge=0, le=3600)
    detail: str | None = Field(default=None, max_length=200)


def build_health_router(
    store: Callable[[], HealthStore],
    current_settings: Callable[[], Any],
    require_local: Callable[..., None],
    *,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """``require_local`` is server._require_local: Host do próprio PC e nada de outros sites."""
    router = APIRouter(prefix=API_PREFIX)

    def enabled() -> bool:
        try:
            return bool(current_settings().health_enabled)
        except Exception:
            return False

    @router.get("")
    def health(request: Request, days: int = Query(7, ge=1, le=RETENTION_DAYS)) -> dict[str, Any]:
        """Resumo do painel SAU-40. O celular pareado também lê (só números, nada da conversa)."""
        require_local(request, "O painel de saúde")
        if not enabled():
            return {"enabled": False}
        settings = current_settings()
        now = clock()
        summary = summarize(
            store().events(now - days * DAY_S),
            now=now,
            days=days,
            wake_thresholds=dict(settings.wake_thresholds) if settings.wake_word_enabled else {},
            min_similarity=settings.memory_min_similarity,
        )
        return {"enabled": True, **summary}

    @router.post("/event")
    def add_event(body: HealthEvent, request: Request) -> dict[str, bool]:
        """Agente, detector e HUD do PC gravam aqui; o celular não."""
        require_local(request, "O painel de saúde", devices=False)
        if not enabled():
            return {"ok": False}
        store().add(body.kind, body.key, body.value, body.detail)
        return {"ok": True}

    @router.delete("")
    def clear(request: Request) -> dict[str, bool]:
        require_local(request, "O painel de saúde", devices=False)
        store().clear()
        return {"ok": True}

    return router
