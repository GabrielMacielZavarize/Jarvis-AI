from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from livekit.agents import Agent, AgentSession, room_io
from livekit.plugins import google, noise_cancellation, openai, silero

from prompts import AGENT_INSTRUCTION, INITIAL_REPLY_INSTRUCTION
from settings import Settings
from tools import PENDING_EMAIL_KEY, build_tools


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


class JarvisAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=AGENT_INSTRUCTION)

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions=INITIAL_REPLY_INSTRUCTION)


def build_backend_components(settings: Settings) -> BackendComponents:
    settings.validate_for_command("console")

    if settings.backend == "gemini-realtime":
        llm = google.realtime.RealtimeModel(
            **_compact_kwargs(
                api_key=settings.google_api_key,
                model=settings.google_model,
                voice=settings.google_voice,
                temperature=0.8,
            )
        )
        return BackendComponents(backend=settings.backend, llm=llm)

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


def build_runtime(settings: Settings, *, load_vad: bool = True) -> JarvisRuntime:
    backend = build_backend_components(settings)
    tools = build_tools(settings)

    session_kwargs: dict[str, Any] = {
        "tools": tools,
        "userdata": {PENDING_EMAIL_KEY: None},
    }
    if load_vad:
        session_kwargs["vad"] = silero.VAD.load()
    if backend.llm is not None:
        session_kwargs["llm"] = backend.llm
    if backend.stt is not None:
        session_kwargs["stt"] = backend.stt
    if backend.tts is not None:
        session_kwargs["tts"] = backend.tts

    session = AgentSession(**session_kwargs)
    agent = JarvisAgent()
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
    )
