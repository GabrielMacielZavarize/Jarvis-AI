"""Visão do Jarvis: imagens enviadas ao modelo e a webcam.

A webcam pertence ao servidor do HUD (``server.py``, ``camera.CameraHub``). O worker do agente
é outro processo, então pede os quadros por HTTP em ``JARVIS_HUD_URL`` (127.0.0.1). Os quadros
só vão para o modelo (Google) quando o usuário pede ao Jarvis para olhar; não há vídeo
contínuo: sessões de áudio+vídeo do Gemini Live duram ~2 min sem compressão de contexto e
cada quadro custa ~258 tokens.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any, Literal

import requests
from livekit.agents import RunContext, function_tool

from hud import CAMERA_TOPIC, hud_request, send_screenshot, show_card, tool_status
from settings import load_settings

logger = logging.getLogger("jarvis-vision")

CAMERA_REQUEST_TIMEOUT = 12.0
SHOW_WAIT_SECONDS = 6.0
POLL_SECONDS = 0.4


class CameraUnavailable(Exception):
    """Mensagem em PT-BR, pronta para o modelo repetir ao usuário."""


def push_image_to_model(context: RunContext, image: Any) -> bool:
    """Send a PIL image to the realtime model as a video frame; False when it takes no images."""
    try:
        from livekit import rtc

        rgba = image.convert("RGBA")
        frame = rtc.VideoFrame(rgba.width, rgba.height, rtc.VideoBufferType.RGBA, rgba.tobytes())
        context.session.current_agent.realtime_llm_session.push_video(frame)
        return True
    except Exception:
        logger.warning("Não foi possível enviar a imagem ao modelo.", exc_info=True)
        return False


# ───────────────────────── webcam (via servidor do HUD) ─────────────────────────


def camera_request(method: str, path: str) -> requests.Response:
    base = load_settings().hud_url
    try:
        response = requests.request(method, f"{base}/api/camera/{path}", timeout=CAMERA_REQUEST_TIMEOUT)
    except requests.ConnectionError as exc:
        raise CameraUnavailable(
            f"o servidor do HUD não está rodando em {base}, e é ele que cuida da câmera. "
            "Inicie o Jarvis com python jarvis.py."
        ) from exc
    except requests.Timeout as exc:
        raise CameraUnavailable("o servidor do HUD não respondeu a tempo.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        raise CameraUnavailable(str(detail or f"o servidor respondeu {response.status_code}."))
    return response


def camera_state() -> dict[str, Any]:
    return camera_request("GET", "state").json()


def fetch_snapshot() -> Any:
    from PIL import Image

    data = camera_request("GET", "snapshot").content
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


async def _wait_for_feed() -> dict[str, Any]:
    """Estado da câmera depois que o HUD abriu o feed (ou o último lido, se não abriu a tempo)."""
    deadline = time.monotonic() + SHOW_WAIT_SECONDS
    state = await asyncio.to_thread(camera_state)
    while not state.get("streaming") and not state.get("error") and time.monotonic() < deadline:
        await asyncio.sleep(POLL_SECONDS)
        state = await asyncio.to_thread(camera_state)
    return state


async def _close_camera_panel() -> dict[str, Any] | None:
    return await hud_request("close", {"targets": ["camera"], "kinds": ["camera"]})


@function_tool()
async def look_at_camera(context: RunContext, question: str | None = None) -> str:
    """Look through the user's webcam. Only when the user explicitly asks you to look or see.

    "O que você está vendo?", "olha isso aqui", "o que eu tenho na mão?", "que livro é esse?",
    "como eu estou?". Takes one photo, shows it on the HUD (Câmera panel, with the live feed)
    and sends it to you as an image so you can answer.

    Args:
        question: What the user wants to know about the image, in their words
            ("que livro é esse?"). Omit for a general description.
    """
    question = (question or "").strip()[:200] or None
    await tool_status("look_at_camera", "running", question)
    try:
        image = await asyncio.to_thread(fetch_snapshot)
    except CameraUnavailable as exc:
        await tool_status("look_at_camera", "error", question)
        return f"Não consegui olhar pela câmera: {exc}"
    except Exception:
        logger.exception("Falha ao pegar o quadro da câmera.")
        await tool_status("look_at_camera", "error", question)
        return "Não consegui olhar pela câmera: a imagem veio corrompida."

    taken = time.strftime("%H:%M:%S")
    sent_to_model = push_image_to_model(context, image)
    await send_screenshot(image, f"câmera {taken}", topic=CAMERA_TOPIC, attributes={"question": question or ""})
    await tool_status("look_at_camera", "done", question)
    logger.info("Quadro da câmera (%s) enviado para análise.", taken)
    if not sent_to_model:
        return "Tirei a foto e mostrei no HUD, mas este modelo não recebe imagens; não consigo analisá-la."
    ask = f' Pergunta do usuário: "{question}".' if question else ""
    return (
        f"Foto da webcam tirada às {taken}, exibida no painel Câmera do HUD e enviada a você como imagem.{ask} "
        "Responda pelo que realmente aparece nela; se algo não estiver visível ou nítido, diga isso em vez "
        "de supor. Nunca leia senhas, documentos ou dados pessoais em voz alta."
    )


@function_tool()
async def camera_view(context: RunContext, action: Literal["show", "hide", "off"]) -> str:
    """Show or hide the live webcam feed on the HUD, or turn the webcam off.

    Args:
        action: show ("mostra a câmera", "abre a webcam": opens the Câmera panel with the live
            feed), hide ("esconde/fecha a câmera": closes the panel; the webcam turns itself off
            when nothing else uses it) or off ("desliga a câmera": turns the webcam off right
            away for everything, the light goes out).
    """
    await tool_status("camera_view", "running", action)
    try:
        if action == "show":
            result = await _show_camera()
        elif action == "hide":
            result = await _hide_camera()
        else:
            result = await _camera_off()
    except CameraUnavailable as exc:
        await tool_status("camera_view", "error", action)
        return f"NADA mudou na câmera: {exc}"
    await tool_status("camera_view", "done", action)
    logger.info("Câmera (%s): %s", action, result)
    return result


async def _show_camera() -> str:
    state = await asyncio.to_thread(camera_state)
    if not state.get("enabled"):
        return "NADA foi aberto: a câmera está desativada (JARVIS_ENABLE_CAMERA=false no .env)."
    if not await show_card("camera", {}):
        return "NADA foi aberto: o HUD não está conectado. Não diga que a câmera está na tela."
    state = await _wait_for_feed()
    if state.get("streaming"):
        return "Câmera ligada: o feed ao vivo está no painel Câmera do HUD, com o aviso CÂMERA ATIVA."
    if state.get("error"):
        return f"Abri o painel Câmera no HUD, mas a webcam não ligou: {state['error']}"
    return "Abri o painel Câmera no HUD, mas a imagem ainda não chegou. Não diga que está vendo nada."


async def _hide_camera() -> str:
    response = await _close_camera_panel()
    if response is None:
        return "NADA foi fechado: o HUD não está conectado."
    if not response.get("changed"):
        return "O painel Câmera não estava aberto no HUD."
    await asyncio.sleep(POLL_SECONDS)  # o navegador solta o feed ao fechar o painel
    state = await asyncio.to_thread(camera_state)
    if state.get("active") and state.get("users"):
        return (
            "Painel Câmera fechado, mas a webcam continua ligada porque outro recurso do Jarvis a "
            "está usando. Para cortar tudo, diga 'desliga a câmera'."
        )
    return "Painel Câmera fechado; a webcam desliga sozinha em instantes."


async def _camera_off() -> str:
    state = (await asyncio.to_thread(camera_request, "POST", "off")).json()
    await _close_camera_panel()
    if state.get("active"):
        return f"Pedi para desligar, mas a webcam ainda aparece ligada. {state.get('error') or ''}".strip()
    return "Câmera desligada: a luz da webcam apagou e nada mais está usando ela."


def build_camera_tools() -> list[Any]:
    return [look_at_camera, camera_view]
