"""Ponte entre o detector da palavra de ativação e o HUD (WAK-22).

O detector (``wake_word.py``) pergunta aqui se deve ouvir e avisa quando escutou "Jarvis"; o HUD
recebe o aviso por Server-Sent Events e conecta o link sozinho. Se nenhum HUD estiver aberto, o
servidor abre o navegador e entrega o aviso à primeira aba que se conectar.

O detector só ouve quando nenhum HUD está em conversa: durante o link quem capta a voz é o
navegador, e os dois nunca disputam o microfone.

O aviso de reunião da agenda (AGD-27) usa o mesmo caminho: o servidor guarda o aviso numa fila,
acorda o HUD com ``reason="calendar"`` e o agente busca a fila assim que o link abre.

Um celular pareado (LAN-26) também recebe os eventos, mas a palavra ouvida pelo PC só conecta uma
aba do próprio PC, e só o PC escolhe o microfone que o detector usa.

Com mais de uma palavra no detector ("Jarvis" e "Friday"), o aviso diz qual foi ouvida. Se ela
chama outra persona, o servidor grava o ``persona.json`` antes de avisar o HUD: o agente já
começa a conversa com a persona e a voz certas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lan_access import device_of
from personas import DEFAULT_PERSONA, persona_for_wake, save_persona, saved_persona
from settings import WAKE_WORDS, Settings

logger = logging.getLogger("jarvis-wake")

# jarvis.py shares a random secret with the detector, so only it can say "Jarvis" was heard.
SECRET_ENV = "JARVIS_WAKE_SECRET"
SECRET_HEADER = "X-Jarvis-Wake"
# O mesmo vale para o ícone da bandeja (tray.py), com um segredo próprio.
TRAY_SECRET_ENV = "JARVIS_TRAY_SECRET"
# HUD aberto: tempo para ele conectar o link antes de o detector voltar a ouvir.
PENDING_WAKE_S = 20.0
# Navegador recém-aberto: boot do HUD + permissão de microfone + conexão.
PENDING_BROWSER_S = 45.0
DETECTOR_STALE_S = 5.0
STATUS_INTERVAL_S = 5.0
KEEPALIVE_S = 15.0
CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MAX_LABEL = 160
# Avisos da agenda que ninguém buscou somem depois deste tempo (a reunião já começou).
REMINDER_TTL_S = 15 * 60
# Avisos proativos (PRO-28) que chegaram sem nenhuma aba aberta: entregues à próxima que conectar.
NOTICE_BACKLOG = 10


@dataclass(eq=False)
class HudClient:
    id: str
    connected_at: float
    # None ends the stream (server shutting down).
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    session_active: bool = False
    visible: bool = True
    # Aba aberta no próprio PC (não num celular pareado).
    local: bool = True


class WakeHub:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.clients: dict[str, HudClient] = {}
        self.mic_label: str | None = None
        self.pending_until = 0.0
        # Score of a wake waiting for the browser that was just opened.
        self.undelivered_score: float | None = None
        # Scheduled routine (ROT-24) that asked for that wake.
        self.undelivered_routine: str | None = None
        self.undelivered_reason = "wake"
        # Word heard and persona it called, for that same wake ({"word": "friday", "persona": "friday"}).
        self.undelivered_extra: dict[str, str] = {}
        # Calendar reminders waiting for the agent: (expires_at, payload).
        self.reminders: list[tuple[float, dict[str, Any]]] = []
        self.notice_backlog: list[dict[str, Any]] = []
        self.detector_seen_at: float | None = None
        # The detector's open microphone has delivered only silence (muted in Windows?).
        self.mic_silent = False
        # Wake words the detector hears ("jarvis", "friday"), as it reported in its last poll.
        self.detector_words: tuple[str, ...] = ()

    # --- HUD -------------------------------------------------------------------------------------

    def connect(self, client_id: str, *, local: bool = True) -> HudClient:
        client = HudClient(id=client_id, connected_at=self._clock(), local=local)
        self.clients[client_id] = client
        if self.undelivered_score is not None and self._pending():
            self._deliver(
                client, self.undelivered_score, self.undelivered_reason, self.undelivered_routine, self.undelivered_extra
            )
        for event in self.notice_backlog:
            client.queue.put_nowait(event)
        self.notice_backlog = []
        return client

    def close(self) -> None:
        """End every SSE stream, so open HUD tabs don't hold the server's shutdown."""
        for client in self.clients.values():
            client.queue.put_nowait(None)

    def disconnect(self, client: HudClient) -> None:
        if self.clients.get(client.id) is client:
            del self.clients[client.id]

    def update(self, client_id: str, *, session_active: bool, visible: bool, mic_label: str | None) -> None:
        client = self.clients.get(client_id)
        if client is not None:
            client.session_active = session_active
            client.visible = visible
        # O microfone de um celular não existe no PC: o detector segue o do HUD local.
        if client is None or client.local:
            self.mic_label = mic_label
        if session_active:
            self._clear_pending()

    def wake_handled(self) -> None:
        """The HUD connected, failed or ignored the wake (demo running, link already open)."""
        self._clear_pending()

    # --- Detector --------------------------------------------------------------------------------

    def listening(self) -> bool:
        return not self._pending() and not any(client.session_active for client in self.clients.values())

    def detector_state(self, *, mic_silent: bool = False, words: tuple[str, ...] = ()) -> dict[str, Any]:
        self.detector_seen_at = self._clock()
        self.mic_silent = mic_silent
        self.detector_words = words
        return {"listen": self.listening(), "mic_label": self.mic_label}

    def detector_online(self) -> bool:
        return self.detector_seen_at is not None and self._clock() - self.detector_seen_at < DETECTOR_STALE_S

    def trigger(
        self, score: float, reason: str = "wake", *, word: str | None = None, persona: str | None = None
    ) -> dict[str, Any]:
        """Hand the wake to one HUD tab, or ask for a browser when none is open.

        ``reason`` says why when it was not a heard wake word: "notice" (a proactive notice, PRO-28),
        "calendar" (a meeting reminder, AGD-27) or "presence" (the user sat back down, PRS-25).
        ``word`` is the name heard and ``persona`` the one it called, if the HUD must switch."""
        if not self.listening():
            return {"accepted": False, "opened_browser": False}
        extra = {key: value for key, value in (("word", word), ("persona", persona)) if value}
        target = self._pick_client()
        if target is not None:
            self._deliver(target, score, reason, extra=extra)
            return {"accepted": True, "opened_browser": False}
        self.undelivered_score = score
        self.undelivered_reason = reason
        self.undelivered_extra = extra
        self.pending_until = self._clock() + PENDING_BROWSER_S
        return {"accepted": True, "opened_browser": True}

    def trigger_routine(self, routine: str, reason: str = "wake") -> dict[str, Any]:
        """Open the link for a scheduled routine (ROT-24), the same way a heard "Jarvis" does.

        With a conversation already open (or opening) nothing is needed: the agent picks the
        routine up by itself. ``reason="context"``: a context trigger fired it, not the clock.
        """
        if self._pending() or any(client.session_active for client in self.clients.values()):
            return {"accepted": False, "opened_browser": False}
        target = self._pick_client()
        if target is not None:
            self._deliver(target, 1.0, reason, routine=routine)
            return {"accepted": True, "opened_browser": False}
        self.undelivered_score = 1.0
        self.undelivered_reason = reason
        self.undelivered_routine = routine
        self.pending_until = self._clock() + PENDING_BROWSER_S
        return {"accepted": True, "opened_browser": True}

    # --- Avisos da agenda ------------------------------------------------------------------------

    def push_reminders(self, reminders: list[dict[str, Any]]) -> dict[str, Any]:
        """Queue reminders for the agent and wake a HUD when no link is open.

        With a link open the agent picks them up by itself (claim_reminders); a wake already on
        its way also ends in a link, so the reminder waits for it.
        """
        expires = self._clock() + REMINDER_TTL_S
        self.reminders.extend((expires, reminder) for reminder in reminders)
        if any(client.session_active for client in self.clients.values()):
            return {"accepted": True, "opened_browser": False}
        return self.trigger(1.0, reason="calendar")

    def claim_reminders(self) -> list[dict[str, Any]]:
        now = self._clock()
        fresh = [reminder for expires, reminder in self.reminders if expires > now]
        self.reminders = []
        return fresh

    # --- Avisos proativos (PRO-28) ---------------------------------------------------------------

    def notify(self, event: dict[str, Any]) -> None:
        """A proactive notice for every open HUD tab (kept for the next one if none is open)."""
        if not self.clients:
            self.notice_backlog = [*self.notice_backlog, event][-NOTICE_BACKLOG:]
            return
        for client in self.clients.values():
            client.queue.put_nowait(event)

    def sleep(self, reason: str = "tray") -> int:
        """Ask every tab with a link open to close it (BAN-41: the tray icon). Returns how many."""
        open_tabs = [client for client in self.clients.values() if client.session_active]
        for client in open_tabs:
            client.queue.put_nowait({"type": "sleep", "reason": reason})
        return len(open_tabs)

    def link_open(self) -> bool:
        return any(client.session_active for client in self.clients.values())

    def status(self) -> dict[str, Any]:
        listening = self.detector_online() and self.listening()
        status: dict[str, Any] = {
            "type": "status",
            "detector": self.detector_online(),
            "listening": listening,
            "mic_silent": listening and self.mic_silent,
        }
        if self.detector_online() and self.detector_words:
            status["words"] = list(self.detector_words)
        return status

    # --- Internos --------------------------------------------------------------------------------

    def _pending(self) -> bool:
        return self._clock() < self.pending_until

    def _clear_pending(self) -> None:
        self.pending_until = 0.0
        self.undelivered_score = None
        self.undelivered_reason = "wake"
        self.undelivered_routine = None
        self.undelivered_extra = {}

    def _deliver(
        self,
        client: HudClient,
        score: float,
        reason: str = "wake",
        routine: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.undelivered_score = None
        self.undelivered_reason = "wake"
        self.undelivered_routine = None
        self.undelivered_extra = {}
        self.pending_until = self._clock() + PENDING_WAKE_S
        event: dict[str, Any] = {"type": "wake", "score": score, **(extra or {})}
        if reason != "wake":
            event["reason"] = reason
        if routine:
            event["routine"] = routine
        client.queue.put_nowait(event)

    def _pick_client(self) -> HudClient | None:
        # Uma aba só conecta: a visível mais recente, senão a mais recente. Quem disse "Jarvis" está
        # perto do PC, então o celular nunca é escolhido; sem aba no PC, o navegador do PC abre.
        local = [client for client in self.clients.values() if client.local]
        clients = sorted(local, key=lambda client: (client.visible, client.connected_at))
        return clients[-1] if clients else None


class HudReport(BaseModel):
    client: str = Field(max_length=64)
    session_active: bool = False
    visible: bool = True
    mic_label: str | None = Field(default=None, max_length=MAX_LABEL)


class WakeResult(BaseModel):
    client: str = Field(max_length=64)
    result: Literal["connected", "failed", "ignored"]


class TriggerRequest(BaseModel):
    score: float = Field(ge=0, le=1)
    word: str | None = Field(default=None, max_length=20)


def _known_words(raw: str) -> tuple[str, ...]:
    """The detector's "jarvis,friday", keeping only words this server knows."""
    words = [word.strip().lower() for word in raw.split(",")]
    return tuple(dict.fromkeys(word for word in words if word in WAKE_WORDS))


def _config_event(settings: Settings) -> dict[str, Any]:
    config: dict[str, Any] = {
        "type": "config",
        "enabled": settings.wake_word_enabled,
        "silence_s": settings.wake_silence_seconds,
        "proactive": settings.proactive_enabled,
        "presence": settings.presence_enabled,
    }
    if settings.calendar_enabled and settings.calendar_reminder_minutes > 0:
        # Os avisos da agenda também acordam o HUD; sem a palavra de ativação o link não fecha
        # sozinho por silêncio.
        config.update(
            enabled=True,
            reminders=True,
            wake_word=settings.wake_word_enabled,
            silence_s=settings.wake_silence_seconds if settings.wake_word_enabled else 0,
        )
    if os.environ.get(TRAY_SECRET_ENV):
        # BAN-41: o ícone da bandeja abre e fecha o link por este canal.
        config["tray"] = True
    return config


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def hud_events(hub: WakeHub, client_id: str, settings: Settings, *, local: bool = True) -> AsyncIterator[str]:
    """SSE stream of one HUD tab: config, detector status changes and wakes."""
    client = hub.connect(client_id, local=local)
    try:
        yield _sse(_config_event(settings))
        last_status = hub.status()
        yield _sse(last_status)
        idle = 0.0
        while True:
            try:
                event = await asyncio.wait_for(client.queue.get(), STATUS_INTERVAL_S)
            except asyncio.TimeoutError:
                event = {}
            if event is None:
                return
            if event:
                yield _sse(event)
            status = hub.status()
            if status != last_status:
                last_status = status
                yield _sse(status)
            elif not event:
                idle += STATUS_INTERVAL_S
                if idle >= KEEPALIVE_S:
                    idle = 0.0
                    yield ": keepalive\n\n"
    finally:
        hub.disconnect(client)


def _require_hud(request: Request) -> None:
    # Navegadores marcam pedidos vindos de outros sites; só o próprio HUD fala com estes endpoints.
    site = request.headers.get("sec-fetch-site")
    if site and site not in {"same-origin", "none"}:
        raise HTTPException(status_code=403, detail="Somente o HUD local pode usar este endpoint.")


def build_wake_router(
    hub: WakeHub,
    current_settings: Callable[[], Settings],
    *,
    secret: str | None,
    open_browser: Callable[[str], Any],
    on_wake: Callable[[str | None, float], None] | None = None,
) -> APIRouter:
    """``on_wake`` records each wake the HUD accepted (word, score) for the health panel (SAU-40)."""
    router = APIRouter(prefix="/api/wake")

    def require_detector(request: Request) -> None:
        _require_hud(request)
        # O cabeçalho próprio também barra outros sites: o navegador exige um preflight que este
        # servidor nunca aprova.
        sent = request.headers.get(SECRET_HEADER)
        if sent is None or (secret and not secrets.compare_digest(sent, secret)):
            raise HTTPException(status_code=403, detail="Detector não autorizado.")

    def client_id(raw: str) -> str:
        if not CLIENT_ID.match(raw):
            raise HTTPException(status_code=422, detail="Identificador de aba inválido.")
        return raw

    @router.get("/events")
    async def events(request: Request, client: str = "") -> StreamingResponse:
        _require_hud(request)
        return StreamingResponse(
            hud_events(hub, client_id(client), current_settings(), local=device_of(request) is None),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/hud")
    async def hud_report(body: HudReport, request: Request) -> dict[str, bool]:
        _require_hud(request)
        label = (body.mic_label or "").strip() or None
        hub.update(client_id(body.client), session_active=body.session_active, visible=body.visible, mic_label=label)
        return {"listening": hub.listening()}

    @router.post("/result")
    async def wake_result(body: WakeResult, request: Request) -> dict[str, bool]:
        _require_hud(request)
        client_id(body.client)
        hub.wake_handled()
        return {"listening": hub.listening()}

    @router.get("/detector")
    async def detector(request: Request, silent: int = 0, words: str = "") -> dict[str, Any]:
        require_detector(request)
        if not current_settings().wake_word_enabled:
            return {"listen": False, "mic_label": None}
        return hub.detector_state(mic_silent=bool(silent), words=_known_words(words[:100]))

    @router.post("/trigger")
    async def trigger(body: TriggerRequest, request: Request) -> dict[str, Any]:
        require_detector(request)
        if not current_settings().wake_word_enabled:
            return {"accepted": False, "opened_browser": False}
        word = (body.word or "").lower()
        word = word if word in WAKE_WORDS else None
        persona = persona_for_wake(word, saved_persona() or DEFAULT_PERSONA, hub.detector_words)
        result = hub.trigger(body.score, word=word, persona=persona)
        if result["accepted"] and on_wake is not None:
            on_wake(word, body.score)
        if result["accepted"] and persona:
            # Antes de qualquer await: o persona.json muda antes de o HUD receber o aviso e abrir o link.
            save_persona(persona)
            logger.info("“%s” ouvido: persona do HUD agora é %s.", word, persona)
        if result["opened_browser"]:
            await asyncio.to_thread(open_browser, str(request.base_url))
        return result

    return router
