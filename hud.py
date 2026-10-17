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


async def hud_command(action: str, kinds: list[str] | None = None) -> bool:
    """Ask the HUD to close panels (`kinds`) or clear them all."""
    return await publish_hud_event("hud", action=action, kinds=kinds or [])


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
