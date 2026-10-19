"""Voz do Jarvis (VOZ-30): qual voz do Gemini Live ele usa e a ferramenta "troca sua voz para X".

A voz vem, em ordem: da escolha feita por voz (``voz.json``, fora do git), de ``JARVIS_VOICE``,
de ``GOOGLE_VOICE`` e, por fim, de Charon, o timbre grave e calmo recomendado para o Jarvis.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from livekit.agents import RunContext, function_tool

from hud import show_card, tool_status
from settings import Settings

logger = logging.getLogger("jarvis-voice")

VOICE_FILE = Path(__file__).resolve().parent / "voz.json"
DEFAULT_VOICE = "Charon"

# Vozes do Gemini Live (livekit.plugins.google.realtime.api_proto.Voice) com o estilo que o Google
# descreve para cada uma. As primeiras são as recomendadas para o Jarvis: graves, calmas e firmes.
GEMINI_VOICES: dict[str, str] = {
    "Charon": "grave, calma e informativa (recomendada)",
    "Orus": "grave e firme",
    "Iapetus": "clara e serena",
    "Rasalgethi": "informativa, de narrador",
    "Algieba": "suave",
    "Sadaltager": "culta, de professor",
    "Alnilam": "firme",
    "Algenib": "rouca",
    "Schedar": "equilibrada",
    "Gacrux": "madura",
    "Umbriel": "tranquila",
    "Enceladus": "sussurrada",
    "Fenrir": "animada",
    "Puck": "alegre",
    "Achird": "amigável",
    "Zubenelgenubi": "descontraída",
    "Sadachbia": "vivaz",
    "Kore": "firme (feminina)",
    "Zephyr": "brilhante (feminina)",
    "Leda": "jovem (feminina)",
    "Aoede": "leve (feminina)",
    "Callirrhoe": "tranquila (feminina)",
    "Autonoe": "brilhante (feminina)",
    "Despina": "suave (feminina)",
    "Erinome": "clara (feminina)",
    "Laomedeia": "alegre (feminina)",
    "Achernar": "macia (feminina)",
    "Pulcherrima": "direta (feminina)",
    "Vindemiatrix": "gentil (feminina)",
    "Sulafat": "calorosa (feminina)",
}
RECOMMENDED_VOICES = ("Charon", "Orus", "Iapetus", "Rasalgethi", "Algieba", "Sadaltager")


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(char for char in folded.lower() if char.isalnum())


_BY_KEY = {_normalize(name): name for name in GEMINI_VOICES}


def canonical_voice(name: str | None) -> str | None:
    """Exact voice name ("charon" → "Charon"), or None when it is not a Gemini Live voice."""
    if not name:
        return None
    return _BY_KEY.get(_normalize(name))


def match_voice(spoken: str) -> str | None:
    """The voice the user meant, tolerating what speech recognition does to the names ("Óros", "caron")."""
    exact = canonical_voice(spoken)
    if exact:
        return exact
    key = _normalize(re.sub(r"^\s*(a\s+)?voz\s+(d[oa]\s+)?", "", spoken.lower()))
    if not key:
        return None
    close = difflib.get_close_matches(key, _BY_KEY, n=1, cutoff=0.7)
    return _BY_KEY[close[0]] if close else None


def saved_voice(path: Path | None = None) -> str | None:
    """The voice chosen with "troca sua voz para X" in an earlier conversation."""
    try:
        data = json.loads((path or VOICE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return canonical_voice(data.get("voice")) if isinstance(data, dict) else None


def save_voice(voice: str | None, path: Path | None = None) -> None:
    """Remember the voice for the next sessions; None goes back to the .env one."""
    target = path or VOICE_FILE
    if voice is None:
        target.unlink(missing_ok=True)
        return
    target.write_text(json.dumps({"voice": voice}, ensure_ascii=False) + "\n", encoding="utf-8")


def effective_voice(configured: str | None, path: Path | None = None) -> str:
    """Voice the Gemini session starts with: the spoken choice wins over JARVIS_VOICE/GOOGLE_VOICE."""
    return saved_voice(path) or canonical_voice(configured) or DEFAULT_VOICE


def describe_voices(current: str) -> str:
    recommended = ", ".join(RECOMMENDED_VOICES)
    others = ", ".join(name for name in GEMINI_VOICES if name not in RECOMMENDED_VOICES)
    return (
        f"Voz atual: {current} ({GEMINI_VOICES.get(current, 'sem descrição')}). "
        f"Recomendadas para o Jarvis, graves e calmas: {recommended}. Outras: {others}."
    )


def _voice_card_content(current: str) -> str:
    lines = []
    for name, style in GEMINI_VOICES.items():
        marker = "▶ " if name == current else "· "
        lines.append(f"{marker}{name} — {style}")
    return "\n".join(lines)


async def _apply_after_reply(session: Any, llm: Any, voice: str, wait_for_reply: bool) -> None:
    """Switch the live voice once the confirmation was spoken (the Gemini session reconnects)."""
    from tools import _wait_for_farewell

    if wait_for_reply:
        await _wait_for_farewell(session)
    try:
        llm.update_options(voice=voice)
        logger.info("Voz trocada na hora para %s.", voice)
    except Exception:
        logger.warning("Não deu para trocar a voz na hora; %s vale a partir da próxima sessão.", voice, exc_info=True)


def _live_model(session: Any) -> Any | None:
    """The Gemini Live model of this session, when it can change voice without a new session."""
    llm = getattr(session, "llm", None)
    if llm is None or not type(llm).__module__.startswith("livekit.plugins.google"):
        return None
    return llm if callable(getattr(llm, "update_options", None)) else None


def build_voice_tools(settings: Settings) -> list[Any]:
    configured_voice = settings.google_voice
    gemini = settings.backend == "gemini-realtime"
    state = {"current": effective_voice(configured_voice)}

    @function_tool()
    async def change_voice(
        context: RunContext,
        action: Literal["set", "list", "reset"],
        voice: str = "",
    ) -> str:
        """Change Jarvis's own speaking voice (Gemini Live voices) or list the available ones.

        "Troca sua voz para Orus", "usa a voz Charon" = set. "Quais vozes você tem?", "qual é a
        sua voz?" = list. "Volta para a sua voz padrão" = reset (the one in the .env). The choice
        is saved for the next conversations too.

        Args:
            action: "set" to switch to `voice`, "list" to tell the voices, "reset" for the .env voice.
            voice: Voice name as the user said it (e.g. "Orus", "Charon"). Only for "set".
        """
        await tool_status("change_voice", "running")
        if not gemini:
            await tool_status("change_voice", "error", "só no Gemini Live")
            return (
                "Trocar de voz por comando só funciona com o Gemini Live (JARVIS_BACKEND=gemini-realtime). "
                "Com a OpenAI, a voz é a de OPENAI_VOICE no .env. Diga isso numa frase."
            )
        if action == "list":
            await show_card("note", {"title": "Vozes do Jarvis", "content": _voice_card_content(state["current"])})
            await tool_status("change_voice", "done")
            return describe_voices(state["current"]) + " A lista completa está no painel."

        if action == "reset":
            await asyncio.to_thread(save_voice, None)
            target = canonical_voice(configured_voice) or DEFAULT_VOICE
        else:
            target = match_voice(voice)
            if target is None:
                await tool_status("change_voice", "error", voice)
                return (
                    f"Não existe a voz '{voice}'. Pergunte qual delas o usuário quer: "
                    + describe_voices(state["current"])
                )
            await asyncio.to_thread(save_voice, target)

        if target == state["current"]:
            await tool_status("change_voice", "done", target)
            return f"Você já está falando com a voz {target}; nada mudou."

        state["current"] = target
        session = context.session
        llm = _live_model(session)
        await tool_status("change_voice", "done", target)
        if llm is None:
            return f"Voz {target} salva; ela vale a partir da próxima conversa. Diga isso numa frase curta."
        from tools import _spawn, _tool_reply_is_new_speech

        handle = getattr(context, "speech_handle", None)
        if handle is None:
            _spawn(_apply_after_reply(session, llm, target, wait_for_reply=True))
        else:
            wait = _tool_reply_is_new_speech(session)
            handle.add_done_callback(lambda _: _spawn(_apply_after_reply(session, llm, target, wait)))
        return (
            f"Voz {target} salva. A troca acontece assim que você terminar esta resposta (a conexão "
            "com o Gemini reabre em um instante). Confirme em UMA frase curta, sem perguntas."
        )

    return [change_voice]
