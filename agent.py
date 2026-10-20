from __future__ import annotations

import asyncio
import sys

from livekit import agents
from livekit.agents import AgentServer, JobProcess

from backends import build_runtime, watch_model_failover
from hud import watch_response_time, watch_user_voice
from model_pool import pool_for
from settings import SettingsError, get_cli_command, load_settings, should_validate_runtime_command


def _prewarm(proc: JobProcess) -> None:
    """Loads the VAD while the process waits for a link, so opening one does not wait for it."""
    from livekit.plugins import silero

    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=_prewarm)


async def _nothing() -> None:
    return None


@server.rtc_session(agent_name="jarvis")
async def jarvis_agent(ctx: agents.JobContext):
    settings = load_settings()
    pool = pool_for(settings)
    model = pool.first() if settings.backend == "gemini-realtime" else None
    runtime = build_runtime(settings, vad=ctx.proc.userdata.get("vad"), model=model)
    watch_user_voice(runtime.session)
    watch_response_time(runtime.session, lambda: runtime.model)
    watch_model_failover(runtime, pool)
    if settings.computer_use_enabled:
        # Modo ditado (DIT-29): escuta as transcrições desde o começo da sessão.
        from dictation import watch_dictation

        watch_dictation(runtime.session)

    # As duas perguntas ao servidor do HUD saem juntas: o link abre sem esperar uma pela outra.
    routine_check = _nothing()
    notices_check = _nothing()
    if settings.routines_enabled:
        from routines import claim_scheduled

        # ROT-24: o link foi aberto por uma rotina agendada? Ela roda no lugar do cumprimento.
        routine_check = asyncio.to_thread(claim_scheduled, settings.hud_url)
    if settings.proactive_enabled:
        from proactive import fetch_notices

        # Link aberto por um aviso (PRO-28): ele vira a primeira fala, no lugar da saudação.
        notices_check = asyncio.to_thread(fetch_notices, settings.hud_url)
    routine, waiting = await asyncio.gather(routine_check, notices_check)
    if routine:
        runtime.agent.startup_routine = routine
    if waiting:
        from proactive import announcement_instruction

        runtime.agent.first_reply_instruction = announcement_instruction(waiting)

    await runtime.session.start(
        room=ctx.room,
        agent=runtime.agent,
        room_options=runtime.room_options,
    )
    if runtime.model:
        from hud import publish_hud_event

        # The pool may have started on a fallback (paused primary or rotation): the HUD shows which.
        await publish_hud_event("model", model=runtime.model)
    # Persona trocada no HUD durante a conversa: persona e voz mudam na hora (personas.py).
    from personas import watch_persona

    persona_task = watch_persona(runtime.session, lambda: runtime.session.current_agent)
    ctx.add_shutdown_callback(lambda: _cancel(persona_task))

    if settings.memory_enabled:
        # Depois do start: o participante local só existe com a sala conectada.
        from memory import index_in_background, serve_memory_panel

        serve_memory_panel(ctx.room)
        # Vetores da busca pelo sentido das memórias que ainda não têm (as antigas, na primeira vez).
        index_in_background()

    if settings.routines_enabled:
        from routines import watch_scheduled_routines

        watch_scheduled_routines(runtime.session, settings.hud_url)

    if settings.proactive_enabled:
        from proactive import announce_loop

        task = asyncio.create_task(announce_loop(runtime.session, settings.hud_url))
        ctx.add_shutdown_callback(lambda: _cancel(task))

    if settings.calendar_enabled and settings.calendar_reminder_minutes > 0:
        # Avisos de reunião que o servidor do HUD guardou (inclusive o que abriu este link).
        from calendar_tools import start_reminder_relay

        start_reminder_relay(runtime.session, settings.hud_url)

    if settings.gestures_enabled:
        from gestures import (
            MIC,
            SERVICE,
            attach_hud,
            autostart_requested,
            serve_gesture_panel,
            start_for_session,
            watch_voice,
        )

        # Tapar a câmera muta/desmuta o que o Jarvis ouve nesta sessão.
        MIC.bind(runtime.session, asyncio.get_running_loop())
        # Apontar enquanto fala marca o "aqui" do assistente de tela, sem ligar o mouse no ar.
        watch_voice(runtime.session)
        # O painel Gestos do HUD: estado ao vivo (eventos) e os botões (RPC), ligados por esta sessão.
        attach_hud(asyncio.get_running_loop())
        serve_gesture_panel(ctx.room)

        async def unbind_mic() -> None:
            MIC.unbind()

        async def stop_gestures() -> None:
            await asyncio.to_thread(SERVICE.stop)

        ctx.add_shutdown_callback(unbind_mic)
        ctx.add_shutdown_callback(stop_gestures)
        if autostart_requested():  # python jarvis.py --gestures
            await start_for_session(ctx)


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()


def _validate_startup() -> None:
    argv = sys.argv[1:]
    if not should_validate_runtime_command(argv):
        return

    command = get_cli_command(argv)
    settings = load_settings()
    settings.validate_for_command(command)


if __name__ == "__main__":
    try:
        _validate_startup()
    except SettingsError as exc:
        raise SystemExit(str(exc)) from exc

    agents.cli.run_app(server)
