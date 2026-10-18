"""Ponte entre as ferramentas do agente e o HUD holográfico do navegador.

Os eventos são enviados como JSON pelo data channel do LiveKit no tópico
``jarvis.hud``. Quando não existe uma sala conectada (testes, modo console),
as funções viram no-op e retornam ``False``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from livekit.agents import get_job_context

logger = logging.getLogger("jarvis-hud")

HUD_TOPIC = "jarvis.hud"


def _local_participant() -> Any | None:
    try:
        job_ctx = get_job_context(required=False)
        if job_ctx is None:
            return None
        return job_ctx.room.local_participant
    except Exception:
        return None


def encode_event(event_type: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {"type": event_type, "ts": time.time(), **payload},
        ensure_ascii=False,
        default=str,
    )


async def publish_hud_event(event_type: str, **payload: Any) -> bool:
    participant = _local_participant()
    if participant is None:
        return False

    try:
        await participant.publish_data(
            encode_event(event_type, payload),
            reliable=True,
            topic=HUD_TOPIC,
        )
        return True
    except Exception:
        logger.debug("Falha ao publicar evento '%s' no HUD.", event_type, exc_info=True)
        return False


async def show_card(kind: str, data: dict[str, Any]) -> bool:
    return await publish_hud_event("card", kind=kind, data=data)


async def tool_status(name: str, status: str, detail: str | None = None) -> bool:
    return await publish_hud_event("tool", name=name, status=status, detail=detail)


async def net_activity(hosts: list[str], kind: str = "request") -> bool:
    """Tell the HUD which hosts are being contacted, for the 3D globe connections.

    kind: "request" (Jarvis is calling this host) or "source" (a site found in the results).
    """
    unique = [host for host in dict.fromkeys(h.strip().lower() for h in hosts) if host]
    if not unique:
        return False
    return await publish_hud_event("net", hosts=unique[:8], kind=kind)


HUD_RPC_METHOD = "jarvis.hud"
SCREEN_TOPIC = "jarvis.screen"
CAMERA_TOPIC = "jarvis.camera"
POINTER_TOPIC = "jarvis.pointer"


def _hud_participant() -> tuple[Any, str] | None:
    """(local participant, identity of the person viewing the HUD)."""
    try:
        job_ctx = get_job_context(required=False)
        if job_ctx is None:
            return None
        room = job_ctx.room
        viewers = [p.identity for p in room.remote_participants.values() if not p.identity.startswith("agent-")]
        if not viewers:
            return None
        return room.local_participant, viewers[0]
    except Exception:
        return None


async def hud_request(action: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask the HUD something over RPC and return what it actually did.

    Actions: list/close/close_all/expand/collapse panels (``payload`` carries ``targets``),
    ``mic`` (microphone selected in the Sistema panel) and ``end_session`` (same as the
    "Encerrar link" button). Returns None when no HUD is connected (console mode, tests,
    closed tab) or it did not answer.
    """
    target = _hud_participant()
    if target is None:
        return None
    participant, identity = target
    try:
        response = await participant.perform_rpc(
            destination_identity=identity,
            method=HUD_RPC_METHOD,
            payload=json.dumps({"action": action, **(payload or {})}, ensure_ascii=False),
            response_timeout=4.0,
        )
        reply = json.loads(response)
    except Exception:
        logger.debug("HUD não respondeu ao comando '%s'.", action, exc_info=True)
        return None
    return reply if isinstance(reply, dict) else None


async def send_screenshot(
    image: Any,
    label: str,
    topic: str = SCREEN_TOPIC,
    attributes: dict[str, str] | None = None,
) -> bool:
    """Stream a downscaled JPEG of what Jarvis looked at to the HUD so the user sees what it saw.

    ``topic`` jarvis.screen opens a "Leitura de tela" panel; jarvis.camera opens the webcam panel; jarvis.pointer attaches the
    print (with the click target drawn) to the MOU-20 panel whose ``action_id`` matches.
    """
    target = _hud_participant()
    if target is None:
        return False
    participant, identity = target
    try:
        import io

        preview = image.convert("RGB")
        preview.thumbnail((1600, 1600))
        buffer = io.BytesIO()
        preview.save(buffer, format="JPEG", quality=78)
        data = buffer.getvalue()
        writer = await participant.stream_bytes(
            f"print-{int(time.time())}.jpg",
            total_size=len(data),
            mime_type="image/jpeg",
            topic=topic,
            attributes={"label": label, **(attributes or {})},
            destination_identities=[identity],
        )
        for start in range(0, len(data), 64 * 1024):
            await writer.write(data[start : start + 64 * 1024])
        await writer.aclose()
        return True
    except Exception:
        logger.debug("Falha ao enviar o print para o HUD.", exc_info=True)
        return False


_PENDING: set[asyncio.Task[bool]] = set()


def _publish_soon(event_type: str, **payload: Any) -> None:
    task = asyncio.create_task(publish_hud_event(event_type, **payload))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


def watch_user_voice(session: Any) -> None:
    """Log (and show on the HUD) when the agent actually hears the user.

    Makes microphone problems visible: if you speak and nothing shows up here,
    the audio never reached the agent (wrong input device, muted mic, etc.).
    """

    @session.on("user_state_changed")
    def _on_user_state(event: Any) -> None:
        if event.new_state == "speaking":
            logger.info("Voz do usuário detectada.")
            _publish_soon("voice", state="speaking")

    @session.on("user_input_transcribed")
    def _on_transcribed(event: Any) -> None:
        if event.is_final and event.transcript.strip():
            logger.info("Transcrição do usuário: %s", event.transcript.strip())
