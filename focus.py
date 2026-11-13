"""Sessão de foco (FOC-47) no servidor do HUD: blocos de trabalho e pausas, estilo Pomodoro.

A fonte da verdade é esta, não a aba do navegador: a contagem anda com o HUD fechado, avisa a troca
de bloco pelo motor de avisos (PRO-28) e pelo ícone da bandeja (BAN-41) e conversa com a presença
(PRS-25). O HUD só mostra o estado e manda comandos (``/api/focus``); o agente de voz também
(``focus_session`` em ``briefing.py``).

- Estado em memória e em ``foco.json`` (fora do git): um arquivo pequeno, sem segredo nenhum,
  para a sessão sobreviver a um "Reiniciar o Jarvis" da bandeja ou a uma queda. Ao subir, os blocos
  que venceram com o servidor fora são passados de uma vez (só a última troca vira aviso).
- Com a presença ligada, ficar ausente por mais de ``AWAY_GRACE_S`` durante um bloco de foco pausa a
  contagem (o tempo do bloco não anda) e a volta retoma dizendo quanto falta. Durante a pausa
  (descanso) a ausência é esperada e não pausa nada. Sem presença, nada muda.
- Enquanto um bloco de foco corre, o motor de avisos segura os avisos não críticos (``holding``).

O relógio é injetável (``now``), em segundos de relógio de parede: o arquivo precisa valer entre
reinícios, então não dá para usar um relógio monotônico.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("jarvis-focus")

FOCUS_FILE = Path(__file__).resolve().parent / "foco.json"
API_PATH = "/api/focus"

DEFAULT_CONFIG = {"work": 25, "rest": 5, "cycles": 4}
FOCUS_LIMITS = {"work": (1, 180), "rest": (1, 60), "cycles": (1, 12)}
# Ausência mais curta que isso (pegar um café, atender a porta) não pausa nada.
AWAY_GRACE_S = 60.0
TICK_S = 1.0
MAX_CATCHUP = 64

Kind = Literal["rest", "work", "done", "paused", "resumed"]
# As trocas que viram aviso (som, voz, bandeja). A pausa só aparece no estado.
ANNOUNCED: frozenset[str] = frozenset({"rest", "work", "done", "resumed"})


@dataclass(frozen=True, slots=True)
class FocusEvent:
    kind: Kind
    title: str
    message: str


def clean_config(raw: dict[str, Any] | None, fallback: dict[str, int] | None = None) -> dict[str, int]:
    """Tempos dentro dos limites; o que faltar (ou vier torto) cai no ``fallback``."""
    base = fallback or DEFAULT_CONFIG
    clean: dict[str, int] = {}
    for key, (low, high) in FOCUS_LIMITS.items():
        value = (raw or {}).get(key)
        number = round(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else base[key]
        clean[key] = max(low, min(high, int(number)))
    return clean


def spoken_left(seconds: float) -> str:
    """"14 min", "3 min e 20 s", "45 s": o que falta, para falar."""
    total = max(0, math.ceil(seconds))
    minutes, rest = divmod(total, 60)
    if minutes == 0:
        return f"{rest} s"
    return f"{minutes} min" + (f" e {rest} s" if rest and minutes < 5 else "")


class FocusSession:
    """A sessão e a regra de cada troca. Só é chamada do laço do servidor (sem threads)."""

    def __init__(self, path: Path | None = None, *, now: Callable[[], float] = time.time) -> None:
        self.path = path
        self._now = now
        self.config = dict(DEFAULT_CONFIG)
        self.running = False
        self.phase: Literal["work", "rest"] = "work"
        self.cycle = 1
        self.ends_at = 0.0
        self.paused = False
        # Quanto faltava quando a contagem parou (só vale com ``paused``).
        self.remaining_s = 0.0
        self._away_since: float | None = None
        self.seq = 0
        self.last_event: dict[str, Any] | None = None
        self._load()

    # --- arquivo -----------------------------------------------------------------------------------

    def _file(self) -> Path:
        return self.path or FOCUS_FILE

    def _load(self) -> None:
        target = self._file()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self._set_aside(target)
            return
        if not isinstance(raw, dict):
            self._set_aside(target)
            return
        self.config = clean_config(raw.get("config") if isinstance(raw.get("config"), dict) else None)
        session = raw.get("session")
        if not isinstance(session, dict) or not session.get("running"):
            return
        ends_at, remaining = session.get("ends_at"), session.get("remaining_s")
        paused = bool(session.get("paused"))
        if paused and not (isinstance(remaining, (int, float)) and math.isfinite(remaining) and remaining > 0):
            return
        if not paused and not (isinstance(ends_at, (int, float)) and math.isfinite(ends_at)):
            return
        self.running = True
        self.phase = "rest" if session.get("phase") == "rest" and not paused else "work"
        cycle = session.get("cycle")
        self.cycle = max(1, min(self.config["cycles"], int(cycle))) if isinstance(cycle, int) and not isinstance(cycle, bool) else 1
        self.paused = paused
        self.ends_at = 0.0 if paused else float(ends_at)
        self.remaining_s = float(remaining) if paused else 0.0

    @staticmethod
    def _set_aside(target: Path) -> None:
        backup = target.with_name(f"{target.stem}.corrompido-{int(time.time())}{target.suffix}")
        with contextlib.suppress(OSError):
            os.replace(target, backup)
            logger.warning("%s estava ilegível e foi guardado em %s.", target.name, backup.name)

    def _save(self) -> None:
        target = self._file()
        data = {
            "version": 1,
            "config": self.config,
            "session": {
                "running": self.running,
                "phase": self.phase,
                "cycle": self.cycle,
                "ends_at": self.ends_at,
                "paused": self.paused,
                "remaining_s": self.remaining_s,
            },
        }
        try:
            temp = target.with_name(f"{target.name}.tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, target)
        except OSError:
            logger.exception("Não consegui gravar %s: a sessão de foco vale só até o Jarvis fechar.", target.name)

    # --- estado ------------------------------------------------------------------------------------

    def holding(self) -> bool:
        """Um bloco de foco está em andamento (mesmo pausado pela ausência): avisos não críticos esperam."""
        return self.running and self.phase == "work"

    def remaining(self, now: float | None = None) -> float:
        if not self.running:
            return 0.0
        if self.paused:
            return self.remaining_s
        return max(0.0, self.ends_at - (self._now() if now is None else now))

    def snapshot(self) -> dict[str, Any]:
        now = self._now()
        return {
            "running": self.running,
            "phase": self.phase,
            "cycle": self.cycle,
            "cycles": self.config["cycles"],
            "work": self.config["work"],
            "rest": self.config["rest"],
            "paused": self.paused,
            "paused_reason": "away" if self.paused else None,
            "remaining_s": math.ceil(self.remaining(now)),
            "ends_at_ms": round(self.ends_at * 1000) if self.running and not self.paused else None,
            "now_ms": round(now * 1000),
            "last_event": self.last_event,
        }

    def report(self) -> dict[str, Any]:
        """O que a ferramenta de voz recebe de volta."""
        snap = self.snapshot()
        return {key: snap[key] for key in ("running", "phase", "cycle", "cycles", "paused", "remaining_s")}

    # --- eventos -----------------------------------------------------------------------------------

    def _event(self, kind: Kind, now: float) -> FocusEvent:
        cycles, work, rest = self.config["cycles"], self.config["work"], self.config["rest"]
        if kind == "rest":
            event = FocusEvent(kind, "Hora da pausa", f"Bloco {self.cycle} de {cycles} concluído. {rest} min de descanso.")
        elif kind == "work":
            event = FocusEvent(kind, "De volta ao foco", f"Bloco {self.cycle} de {cycles}: {work} min.")
        elif kind == "done":
            event = FocusEvent(kind, "Sessão de foco concluída", f"{cycles} {'bloco' if cycles == 1 else 'blocos'} de {work} min. Bom trabalho.")
        elif kind == "resumed":
            event = FocusEvent(
                kind, "Foco retomado", f"Bem-vindo de volta. Faltam {spoken_left(self.remaining(now))} do bloco {self.cycle} de {cycles}."
            )
        else:
            event = FocusEvent(kind, "Foco pausado", f"Você saiu: a contagem parou com {spoken_left(self.remaining(now))} para o fim do bloco.")
        self.seq += 1
        self.last_event = {"seq": self.seq, "kind": event.kind, "title": event.title, "message": event.message, "at_ms": round(now * 1000)}
        return event

    def _next_block(self, from_: float) -> Kind:
        """Passa para o bloco seguinte, contado a partir de ``from_`` (o fim do anterior, ou agora ao pular)."""
        if self.phase == "work":
            # Depois do último bloco de foco não há pausa: a sessão acabou.
            if self.cycle >= self.config["cycles"]:
                self.running = False
                self.ends_at = 0.0
                return "done"
            self.phase = "rest"
            self.ends_at = from_ + self.config["rest"] * 60
            return "rest"
        self.phase = "work"
        self.cycle += 1
        self.ends_at = from_ + self.config["work"] * 60
        return "work"

    # --- comandos ----------------------------------------------------------------------------------

    def start(self, config: dict[str, Any] | None = None) -> None:
        """Começa do primeiro bloco; o que não vier nos ``config`` repete os tempos da última sessão."""
        self.config = clean_config(config, self.config)
        now = self._now()
        self.running, self.phase, self.cycle = True, "work", 1
        self.ends_at = now + self.config["work"] * 60
        self.paused, self.remaining_s, self._away_since = False, 0.0, None
        self._save()

    def stop(self) -> None:
        self.running, self.phase, self.cycle = False, "work", 1
        self.ends_at, self.paused, self.remaining_s, self._away_since = 0.0, False, 0.0, None
        self._save()

    def skip(self) -> list[FocusEvent]:
        if not self.running:
            return []
        now = self._now()
        self.paused, self.remaining_s, self._away_since = False, 0.0, None
        event = self._event(self._next_block(now), now)
        self._save()
        return [event]

    def tick(self, present: bool | None = None, now: float | None = None) -> list[FocusEvent]:
        """Anda a sessão até agora. ``present``: True/False com a presença ligada, None sem ela."""
        if not self.running:
            self._away_since = None
            return []
        moment = self._now() if now is None else now
        events: list[FocusEvent] = []
        changed = False
        # Primeiro o relógio: um bloco que acabou durante a ausência acabou, e a pausa não o alcança.
        while self.running and not self.paused and moment >= self.ends_at and len(events) < MAX_CATCHUP:
            events.append(self._event(self._next_block(self.ends_at), moment))
            self._away_since = None
            changed = True
        if self.running and self.phase == "work":
            events.extend(self._presence(present, moment))
            changed = changed or bool(events)
        elif self._away_since is not None:
            self._away_since = None
        if changed:
            self._save()
        return events

    def _presence(self, present: bool | None, now: float) -> list[FocusEvent]:
        if present is False:
            if self._away_since is None:
                self._away_since = now
            if not self.paused and now - self._away_since >= AWAY_GRACE_S:
                # Retroativo: o tempo de toda a ausência fica de fora, não só o que veio depois da tolerância.
                self.remaining_s = max(0.0, self.ends_at - self._away_since)
                self.paused, self.ends_at = True, 0.0
                return [self._event("paused", now)]
            return []
        self._away_since = None
        if not self.paused:
            return []
        self.paused = False
        self.ends_at = now + self.remaining_s
        # Sem presença (desligada no meio da pausa) a contagem volta em silêncio: ninguém "voltou".
        if present is True:
            return [self._event("resumed", now)]
        self.remaining_s = 0.0
        return []

    # --- laço do servidor --------------------------------------------------------------------------

    async def run(
        self,
        present: Callable[[], bool | None],
        announce: Callable[[list[FocusEvent]], Awaitable[None] | None],
        enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        """Um tique por segundo: a contagem anda com o HUD aberto ou não."""
        while True:
            try:
                if enabled():
                    try:
                        here = present()
                    except Exception:
                        logger.exception("Não consegui saber se há alguém no PC.")
                        here = None
                    events = self.tick(here)
                    if events:
                        result = announce(events)
                        if asyncio.iscoroutine(result):
                            await result
            except Exception:
                logger.exception("Falha no tique da sessão de foco.")
            await asyncio.sleep(TICK_S)


# ───────────────────────── rotas ─────────────────────────


class FocusCommand(BaseModel):
    command: Literal["start", "stop", "skip", "status"]
    work: int | None = None
    rest: int | None = None
    cycles: int | None = None


def build_focus_router(
    session: Callable[[], FocusSession],
    enabled: Callable[[], bool],
    require_local: Callable[..., None],
) -> APIRouter:
    """``GET`` lê o estado; ``POST`` começa, para, pula ou consulta. Só o próprio PC (e celulares pareados).

    Pular o bloco por aqui (o botão do HUD ou a voz) não vira aviso do motor: quem pediu já sabe, e o
    HUD toca o som e mostra a notificação a partir de ``last_event``."""
    router = APIRouter(prefix=API_PATH)

    def snapshot() -> dict[str, Any]:
        return {"enabled": True, **session().snapshot()}

    @router.get("")
    async def read(request: Request) -> dict[str, Any]:
        require_local(request, "A sessão de foco")
        if not enabled():
            return {"enabled": False}
        return snapshot()

    @router.post("")
    async def command(body: FocusCommand, request: Request) -> dict[str, Any]:
        require_local(request, "A sessão de foco")
        if not enabled():
            raise HTTPException(status_code=403, detail="O foco está desligado (JARVIS_ENABLE_DAY=false no .env).")
        current = session()
        if body.command == "start":
            current.start({"work": body.work, "rest": body.rest, "cycles": body.cycles})
        elif body.command == "stop":
            current.stop()
        elif body.command == "skip":
            current.skip()
        return snapshot()

    return router
