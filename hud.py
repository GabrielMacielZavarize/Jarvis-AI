"""Ponte entre as ferramentas do agente e o HUD holográfico do navegador.

Os eventos são enviados como JSON pelo data channel do LiveKit no tópico
``jarvis.hud``. Quando não existe uma sala conectada (testes, modo console),
as funções viram no-op e retornam ``False``.
"""

from __future__ import annotations

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
