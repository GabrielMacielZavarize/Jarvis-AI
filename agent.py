from __future__ import annotations

import asyncio
import sys

from livekit import agents
from livekit.agents import AgentServer

from backends import build_runtime
from hud import watch_user_voice
from settings import SettingsError, get_cli_command, load_settings, should_validate_runtime_command

server = AgentServer()


@server.rtc_session(agent_name="jarvis")
async def jarvis_agent(ctx: agents.JobContext):
    settings = load_settings()
    runtime = build_runtime(settings)
    watch_user_voice(runtime.session)
    if settings.computer_use_enabled:
        # Modo ditado (DIT-29): escuta as transcrições desde o começo da sessão.
        from dictation import watch_dictation

        watch_dictation(runtime.session)

    if settings.routines_enabled:
        from routines import claim_scheduled

        # ROT-24: o link foi aberto por uma rotina agendada? Ela roda no lugar do cumprimento.
        runtime.agent.startup_routine = await asyncio.to_thread(claim_scheduled, settings.hud_url)

    if settings.proactive_enabled:
        from proactive import announcement_instruction, fetch_notices

        # Link aberto por um aviso (PRO-28): ele vira a primeira fala, no lugar da saudação.
        waiting = await asyncio.to_thread(fetch_notices, settings.hud_url)
        if waiting:
            runtime.agent.first_reply_instruction = announcement_instruction(waiting)

    await runtime.session.start(
        room=ctx.room,
        agent=runtime.agent,
        room_options=runtime.room_options,
    )
    if settings.memory_enabled:
        # Depois do start: o participante local só existe com a sala conectada.
        from memory import serve_memory_panel

        serve_memory_panel(ctx.room)

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
        from gestures import MIC, autostart_requested, start_for_session

        # Tapar a câmera muta/desmuta o que o Jarvis ouve nesta sessão.
        MIC.bind(runtime.session, asyncio.get_running_loop())

        async def unbind_mic() -> None:
            MIC.unbind()

        ctx.add_shutdown_callback(unbind_mic)
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
