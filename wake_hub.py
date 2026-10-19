"""Ponte entre o detector da palavra de ativação e o HUD (WAK-22).

O detector (``wake_word.py``) pergunta aqui se deve ouvir e avisa quando escutou "Jarvis"; o HUD
recebe o aviso por Server-Sent Events e conecta o link sozinho. Se nenhum HUD estiver aberto, o
servidor abre o navegador e entrega o aviso à primeira aba que se conectar.

O detector só ouve quando nenhum HUD está em conversa: durante o link quem capta a voz é o
navegador, e os dois nunca disputam o microfone.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from settings import Settings

# jarvis.py shares a random secret with the detector, so only it can say "Jarvis" was heard.
SECRET_ENV = "JARVIS_WAKE_SECRET"
SECRET_HEADER = "X-Jarvis-Wake"
# HUD aberto: tempo para ele conectar o link antes de o detector voltar a ouvir.
PENDING_WAKE_S = 20.0
# Navegador recém-aberto: boot do HUD + permissão de microfone + conexão.
PENDING_BROWSER_S = 45.0
DETECTOR_STALE_S = 5.0
STATUS_INTERVAL_S = 5.0
KEEPALIVE_S = 15.0
CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
MAX_LABEL = 160


@dataclass(eq=False)
class HudClient:
    id: str
    connected_at: float
    # None ends the stream (server shutting down).
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    session_active: bool = False
    visible: bool = True


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
        self.detector_seen_at: float | None = None
        # The detector's open microphone has delivered only silence (muted in Windows?).
        self.mic_silent = False

    # --- HUD -------------------------------------------------------------------------------------

    def connect(self, client_id: str) -> HudClient:
        client = HudClient(id=client_id, connected_at=self._clock())
        self.clients[client_id] = client
        if self.undelivered_score is not None and self._pending():
            self._deliver(client, self.undelivered_score, self.undelivered_routine)
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
        self.mic_label = mic_label
        if session_active:
            self._clear_pending()

    def wake_handled(self) -> None:
        """The HUD connected, failed or ignored the wake (demo running, link already open)."""
        self._clear_pending()

    # --- Detector --------------------------------------------------------------------------------

    def listening(self) -> bool:
        return not self._pending() and not any(client.session_active for client in self.clients.values())

    def detector_state(self, *, mic_silent: bool = False) -> dict[str, Any]:
        self.detector_seen_at = self._clock()
        self.mic_silent = mic_silent
        return {"listen": self.listening(), "mic_label": self.mic_label}

    def detector_online(self) -> bool:
        return self.detector_seen_at is not None and self._clock() - self.detector_seen_at < DETECTOR_STALE_S

    def trigger(self, score: float) -> dict[str, Any]:
        """Hand the wake to one HUD tab, or ask for a browser when none is open."""
        if not self.listening():
            return {"accepted": False, "opened_browser": False}
        target = self._pick_client()
        if target is not None:
            self._deliver(target, score)
            return {"accepted": True, "opened_browser": False}
        self.undelivered_score = score
        self.pending_until = self._clock() + PENDING_BROWSER_S
        return {"accepted": True, "opened_browser": True}

    def trigger_routine(self, routine: str) -> dict[str, Any]:
        """Open the link for a scheduled routine (ROT-24), the same way a heard "Jarvis" does.

        With a conversation already open (or opening) nothing is needed: the agent picks the
        routine up by itself.
        """
        if self._pending() or any(client.session_active for client in self.clients.values()):
            return {"accepted": False, "opened_browser": False}
        target = self._pick_client()
        if target is not None:
            self._deliver(target, 1.0, routine)
            return {"accepted": True, "opened_browser": False}
        self.undelivered_score = 1.0
        self.undelivered_routine = routine
        self.pending_until = self._clock() + PENDING_BROWSER_S
        return {"accepted": True, "opened_browser": True}

    def status(self) -> dict[str, Any]:
        listening = self.detector_online() and self.listening()
        return {
            "type": "status",
            "detector": self.detector_online(),
            "listening": listening,
            "mic_silent": listening and self.mic_silent,
        }

    # --- Internos --------------------------------------------------------------------------------

    def _pending(self) -> bool:
        return self._clock() < self.pending_until

    def _clear_pending(self) -> None:
        self.pending_until = 0.0
        self.undelivered_score = None
        self.undelivered_routine = None

    def _deliver(self, client: HudClient, score: float, routine: str | None = None) -> None:
        self.undelivered_score = None
        self.undelivered_routine = None
        self.pending_until = self._clock() + PENDING_WAKE_S
        event: dict[str, Any] = {"type": "wake", "score": score}
        if routine:
            event["routine"] = routine
        client.queue.put_nowait(event)

    def _pick_client(self) -> HudClient | None:
        # Uma aba só conecta: a visível mais recente, senão a mais recente.
        clients = sorted(self.clients.values(), key=lambda client: (client.visible, client.connected_at))
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


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def hud_events(hub: WakeHub, client_id: str, settings: Settings) -> AsyncIterator[str]:
    """SSE stream of one HUD tab: config, detector status changes and wakes."""
    client = hub.connect(client_id)
    try:
        yield _sse({"type": "config", "enabled": settings.wake_word_enabled, "silence_s": settings.wake_silence_seconds})
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
) -> APIRouter:
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
            hud_events(hub, client_id(client), current_settings()),
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
    async def detector(request: Request, silent: int = 0) -> dict[str, Any]:
        require_detector(request)
        if not current_settings().wake_word_enabled:
            return {"listen": False, "mic_label": None}
        return hub.detector_state(mic_silent=bool(silent))

    @router.post("/trigger")
    async def trigger(body: TriggerRequest, request: Request) -> dict[str, Any]:
        require_detector(request)
        if not current_settings().wake_word_enabled:
            return {"accepted": False, "opened_browser": False}
        result = hub.trigger(body.score)
        if result["opened_browser"]:
            await asyncio.to_thread(open_browser, str(request.base_url))
        return result

    return router
