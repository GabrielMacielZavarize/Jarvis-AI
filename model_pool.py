"""Fila de modelos do Gemini Live: o principal, as reservas e uma pausa para quem falhou.

Cada link do LiveKit roda num processo novo, então o estado (quem está em pausa até quando e,
no modo ``rotate``, de quem é a vez) fica em ``modelos.json`` na pasta do projeto, fora do git.
O plano gratuito do Google limita cada modelo separadamente: quando um estoura a cota ou fica
sobrecarregado, os próximos links (e a conversa em andamento) seguem com o seguinte da lista.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis-models")

STATE_FILE = Path(__file__).with_name("modelos.json")

# Pausa de cada tipo de falha, em segundos. "context" (sessão cheia, erro 1007) não é culpa do
# modelo: a conversa recomeça nele mesmo, só com o texto do histórico.
COOLDOWNS = {
    "quota": 30 * 60,
    "overloaded": 5 * 60,
    "unavailable": 6 * 60 * 60,
    "context": 0,
    "error": 2 * 60,
}
REASON_LABELS = {
    "quota": "cota esgotada",
    "overloaded": "modelo sobrecarregado",
    "unavailable": "modelo indisponível para esta chave",
    "context": "sessão cheia",
    "error": "falha de conexão",
}
# A cota diária do Gemini volta à meia-noite do Pacífico.
QUOTA_RESET_ZONE = ZoneInfo("America/Los_Angeles")

_QUOTA = ("resource_exhausted", "quota", "429", "rate limit", "rate_limit", "too many requests")
_DAILY = ("perday", "per day", "per_day", "daily")
_OVERLOADED = ("overloaded", "unavailable", "503", "1011", "internal error", "try again", "deadline", "timed out", "timeout")
_UNAVAILABLE = ("not found", "404", "1008", "not supported", "permission", "403", "not available", "is not enabled")
_CONTEXT = ("1007", "context exhausted", "invalid argument")


def classify_failure(error: BaseException | str) -> str:
    """Kind of failure of a Gemini Live session, from the exception text the SDK raises."""
    text = str(error).lower()
    cause = getattr(error, "__cause__", None)
    if cause is not None:
        text += " " + str(cause).lower()
    if any(word in text for word in _QUOTA):
        return "quota"
    if any(word in text for word in _CONTEXT):
        return "context"
    if any(word in text for word in _UNAVAILABLE):
        return "unavailable"
    if any(word in text for word in _OVERLOADED):
        return "overloaded"
    return "error"


def cooldown_until(reason: str, error_text: str, now: float) -> float:
    """When a model that failed for ``reason`` may be tried again."""
    if reason == "quota" and any(word in error_text.lower() for word in _DAILY):
        local = dt.datetime.fromtimestamp(now, QUOTA_RESET_ZONE)
        reset = (local + dt.timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return reset.timestamp()
    return now + COOLDOWNS.get(reason, COOLDOWNS["error"])


@dataclass
class ModelPool:
    models: tuple[str, ...]
    rotate: bool = False
    path: Path = STATE_FILE
    clock: Callable[[], float] = time.time
    _state: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def _load(self) -> dict[str, Any]:
        if self._state is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            cooldowns = data.get("cooldowns") if isinstance(data, dict) else None
            turn = data.get("next") if isinstance(data, dict) else None
            self._state = {
                "cooldowns": {
                    str(model): float(until)
                    for model, until in (cooldowns or {}).items()
                    if isinstance(until, int | float)
                },
                "next": turn if isinstance(turn, int) and turn >= 0 else 0,
            }
        return self._state

    def _save(self) -> None:
        state = self._load()
        now = self.clock()
        state["cooldowns"] = {model: until for model, until in state["cooldowns"].items() if until > now}
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            logger.debug("Não consegui gravar %s.", self.path, exc_info=True)

    def paused_until(self, model: str) -> float | None:
        until = self._load()["cooldowns"].get(model)
        return until if until is not None and until > self.clock() else None

    def available(self, model: str) -> bool:
        return self.paused_until(model) is None

    def _first_free(self, ordered: list[str]) -> str:
        for model in ordered:
            if self.available(model):
                return model
        # Todos em pausa: tenta o que volta primeiro, melhor do que não conectar.
        return min(ordered, key=lambda model: self.paused_until(model) or 0.0)

    def first(self) -> str:
        """Model for a new link: the first one free (fallback) or the next in turn (rotate)."""
        if not self.rotate or len(self.models) < 2:
            return self._first_free(list(self.models))
        state = self._load()
        start = state["next"] % len(self.models)
        ordered = [*self.models[start:], *self.models[:start]]
        chosen = self._first_free(ordered)
        state["next"] = (self.models.index(chosen) + 1) % len(self.models)
        self._save()
        return chosen

    def next_after(self, current: str) -> str | None:
        """The next free model after ``current`` (wrapping around), or None when all are paused."""
        if current in self.models:
            index = self.models.index(current)
            ordered = [*self.models[index + 1 :], *self.models[:index]]
        else:
            ordered = list(self.models)
        return next((model for model in ordered if self.available(model)), None)

    def mark_failed(self, model: str, error: BaseException | str) -> str:
        """Pause ``model`` for its kind of failure and return that kind."""
        reason = classify_failure(error)
        until = cooldown_until(reason, str(error), self.clock())
        if until > self.clock():
            self._load()["cooldowns"][model] = until
            self._save()
        return reason

    def describe(self) -> list[str]:
        """One line per model for doctor.py: "gemini-x · livre" / "gemini-y · em pausa até 14:32"."""
        lines = []
        for model in self.models:
            until = self.paused_until(model)
            state = "livre" if until is None else f"em pausa até {time.strftime('%H:%M', time.localtime(until))}"
            lines.append(f"{model} · {state}")
        return lines


def pool_for(settings: Any) -> ModelPool:
    return ModelPool(settings.google_models, rotate=settings.model_rotation == "rotate")
