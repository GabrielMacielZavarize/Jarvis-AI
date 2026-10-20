from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from google.genai import types as genai_types
from livekit.agents import Agent, AgentSession, room_io
from livekit.agents.llm import RealtimeModelError
from livekit.agents.utils import images
from livekit.plugins import google, noise_cancellation, openai, silero

from model_pool import REASON_LABELS, ModelPool, classify_failure
from personas import load_persona, set_active
from prompts import build_agent_instructions, build_initial_reply_instruction
from settings import Settings
from tools import PENDING_EMAIL_KEY, build_tools
from voices import effective_voice

logger = logging.getLogger("jarvis-backends")


def _compact_kwargs(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


@dataclass(slots=True)
class BackendComponents:
    backend: str
    llm: Any | None = None
    stt: Any | None = None
    tts: Any | None = None

    @property
    def is_realtime(self) -> bool:
        return self.backend in {"gemini-realtime", "openai-realtime"}


@dataclass(slots=True)
class JarvisRuntime:
    settings: Settings
    agent: Agent
    session: AgentSession
    room_options: room_io.RoomOptions
    # Modelo do Gemini Live em uso agora; muda quando a conversa passa para um modelo de reserva.
    model: str = ""


# Prints de tela precisam de resolução para o texto ficar legível.
SCREEN_IMAGE_OPTIONS = images.EncodeOptions(
    format="JPEG",
    quality=85,
    resize_options=images.ResizeOptions(width=2048, height=2048, strategy="scale_aspect_fit"),
)
TRANSCRIPTION_VOCABULARY = ["Jarvis", "Claude", "Criciúma", "SATC", "PhpStorm", "Edge", "WhatsApp", "YouTube"]
# Sem compressão o Gemini Live encerra a sessão de áudio em ~15 min (128k tokens de contexto a 25
# tokens por segundo de áudio). A janela deslizante descarta as falas mais antigas e deixa o link
# aberto pelo tempo que for; com menos contexto cada resposta também começa mais cedo.
CONTEXT_TRIGGER_TOKENS = 48_000
CONTEXT_TARGET_TOKENS = 24_000
# Trocas de modelo numa mesma conversa antes de desistir (a sessão fecha no erro seguinte).
MAX_MODEL_SWITCHES = 4


def _monitor_layout() -> str | None:
    try:
        import win_desktop

        return win_desktop.describe_monitors() or None
    except Exception:
        return None


def _memory_summary() -> str | None:
    """What the user asked Jarvis to remember in earlier conversations (memoria.json)."""
    try:
        from memory import summary_for_prompt

        return summary_for_prompt()
    except Exception:
        return None


def _integrations_summary() -> str | None:
    """MCP services configured in mcp.json (MCP-32), read after build_tools filled the states."""
    try:
        from mcp_client import integrations_summary

        return integrations_summary()
    except Exception:
        return None


def _routines_summary() -> str | None:
    """Saved routines (rotinas.json) with their schedules, so "bom dia, Jarvis" runs one."""
    try:
        from routines import summary_for_prompt

        return summary_for_prompt()
    except Exception:
        return None


class JarvisAgent(Agent):
    def __init__(self, instructions: Any = None, **agent_options: Any) -> None:
        super().__init__(instructions=instructions or build_agent_instructions(), **agent_options)
        # Scheduled routine (ROT-24) that opened this link: it replaces the opening greeting.
        self.startup_routine: str | None = None
        # Link aberto por um aviso proativo (PRO-28): a primeira fala é o aviso, não a saudação.
        self.first_reply_instruction: str | None = None
        # The conversation moved to a fallback model: no greeting, only the reply that was due.
        self.resumed = False

    async def on_enter(self) -> None:
        if self.resumed:
            last = next((item for item in reversed(self.chat_ctx.items) if item.type == "message"), None)
            if last is not None and last.role == "user":
                self.session.generate_reply()
            return
        if self.startup_routine:
            import asyncio

            from routines import run_scheduled

            self._startup_task = asyncio.create_task(run_scheduled(self.session, self.startup_routine))
            return
        from presence import welcome_instruction

        # Link aberto porque o usuário voltou para a frente do PC (PRS-25): "Bem-vindo de volta".
        welcome = await welcome_instruction()
        self.session.generate_reply(
            instructions=self.first_reply_instruction
            or welcome
            or build_initial_reply_instruction(persona=load_persona())
        )


def build_gemini_model(settings: Settings, model: str | None = None) -> Any:
    """Gemini Live model for this session; ``model`` overrides GOOGLE_MODEL (fallbacks)."""
    return google.realtime.RealtimeModel(
        **_compact_kwargs(
            api_key=settings.google_api_key,
            model=model or settings.google_model,
            voice=effective_voice(settings.google_voice, persona=load_persona().id),
            temperature=0.8,
            # Espera o resultado da ferramenta antes de falar: uma resposta por ação,
            # sem "vou fazer..." seguido de um "feito" atrasado.
            tool_behavior=genai_types.Behavior.BLOCKING,
            image_encode_options=SCREEN_IMAGE_OPTIONS,
            media_resolution=genai_types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            input_audio_transcription=(
                genai_types.AudioTranscriptionConfig(
                    language_codes=["pt-BR"],
                    custom_vocabulary=TRANSCRIPTION_VOCABULARY,
                )
                if settings.transcription_hints
                else None
            ),
            context_window_compression=genai_types.ContextWindowCompressionConfig(
                trigger_tokens=CONTEXT_TRIGGER_TOKENS,
                sliding_window=genai_types.SlidingWindow(target_tokens=CONTEXT_TARGET_TOKENS),
            ),
            # JARVIS_END_OF_SPEECH_MS: silence that ends the user's turn (0 = Google's default).
            realtime_input_config=(
                genai_types.RealtimeInputConfig(
                    automatic_activity_detection=genai_types.AutomaticActivityDetection(
                        silence_duration_ms=settings.end_of_speech_ms,
                    )
                )
                if settings.end_of_speech_ms
                else None
            ),
        )
    )


def build_backend_components(settings: Settings, model: str | None = None) -> BackendComponents:
    settings.validate_for_command("console")

    if settings.backend == "gemini-realtime":
        return BackendComponents(backend=settings.backend, llm=build_gemini_model(settings, model))

    if settings.backend == "openai-realtime":
        llm = openai.realtime.RealtimeModel(
            **_compact_kwargs(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_realtime_model,
                voice=settings.openai_voice,
                temperature=0.8,
            )
        )
        return BackendComponents(backend=settings.backend, llm=llm)

    if settings.backend == "openai-compatible-pipeline":
        stt = openai.STT(
            **_compact_kwargs(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_stt_model,
                language="pt",
            )
        )
        llm = openai.LLM(
            **_compact_kwargs(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_llm_model,
                temperature=0.8,
            )
        )
        tts = openai.TTS(
            **_compact_kwargs(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_tts_model,
                voice=settings.openai_tts_voice,
            )
        )
        return BackendComponents(
            backend=settings.backend,
            llm=llm,
            stt=stt,
            tts=tts,
        )

    raise ValueError(f"Backend desconhecido: {settings.backend}")


def build_runtime(
    settings: Settings,
    *,
    load_vad: bool = True,
    vad: Any | None = None,
    model: str | None = None,
) -> JarvisRuntime:
    """``vad`` comes preloaded by the worker process (agent.py); ``model`` is the pool's choice."""
    backend = build_backend_components(settings, model)
    tools = build_tools(settings)

    session_kwargs: dict[str, Any] = {
        "tools": tools,
        "userdata": {PENDING_EMAIL_KEY: None},
    }
    if vad is not None:
        session_kwargs["vad"] = vad
    elif load_vad:
        session_kwargs["vad"] = silero.VAD.load()
    if backend.llm is not None:
        session_kwargs["llm"] = backend.llm
    if backend.stt is not None:
        session_kwargs["stt"] = backend.stt
    if backend.tts is not None:
        session_kwargs["tts"] = backend.tts

    session = AgentSession(**session_kwargs)
    # The HUD persona (persona.json): J.A.R.V.I.S., Mark III, F.R.I.D.A.Y. or Stealth.
    persona = load_persona()
    set_active(persona.id)
    agent = JarvisAgent(
        build_agent_instructions(
            home_city=settings.home_city,
            monitors=_monitor_layout() if settings.pc_control_enabled or settings.computer_use_enabled else None,
            memories=_memory_summary() if settings.memory_enabled else None,
            routines=_routines_summary() if settings.routines_enabled else None,
            persona=persona,
            integrations=_integrations_summary() if settings.mcp_enabled else None,
        )
    )
    room_options = room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    return JarvisRuntime(
        settings=settings,
        agent=agent,
        session=session,
        room_options=room_options,
        model=(model or settings.google_model) if settings.backend == "gemini-realtime" else "",
    )


def watch_model_failover(runtime: JarvisRuntime, pool: ModelPool) -> None:
    """When Gemini fails for good (quota, overload), the conversation goes on with the next model.

    Without this the link stays open on a dead model session and Jarvis stops answering. The failed
    model is paused in modelos.json, so the next links skip it too. A full session (1007) restarts
    once on the same model, carrying only the text of the conversation.
    """
    if runtime.settings.backend != "gemini-realtime":
        return
    session = runtime.session
    state: dict[str, Any] = {"switching": False, "switches": 0, "context_retry": None}
    tasks: set[asyncio.Task[None]] = set()

    @session.on("error")
    def _on_error(event: Any) -> None:
        error = event.error
        if not isinstance(error, RealtimeModelError) or error.recoverable or state["switching"]:
            return
        failed = runtime.model
        reason = classify_failure(error.error)
        if reason == "context" and state["context_retry"] != failed:
            state["context_retry"] = failed
            target: str | None = failed
        else:
            pool.mark_failed(failed, error.error if reason != "context" else "falha repetida")
            target = pool.next_after(failed)
        if target is None or state["switches"] >= MAX_MODEL_SWITCHES:
            logger.error("Gemini Live caiu (%s) e não há outro modelo livre para continuar.", REASON_LABELS[reason])
            return
        state["switching"] = True
        state["switches"] += 1
        task = asyncio.create_task(_switch(target, reason))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async def _switch(target: str, reason: str) -> None:
        from hud import publish_hud_event

        previous = runtime.model
        try:
            current = session.current_agent
            agent = JarvisAgent(
                current.instructions,
                chat_ctx=current.chat_ctx.copy(),
                llm=build_gemini_model(runtime.settings, target),
            )
            agent.resumed = True
            runtime.agent = agent
            runtime.model = target
            session.update_agent(agent)
            logger.warning("Gemini Live: %s em %s; a conversa segue em %s.", REASON_LABELS[reason], previous, target)
            await publish_hud_event("model", model=target, previous=previous, reason=REASON_LABELS[reason])
        except Exception:
            logger.exception("Não consegui passar a conversa para %s.", target)
        finally:
            state["switching"] = False
