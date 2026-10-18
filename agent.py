from __future__ import annotations

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

    await runtime.session.start(
        room=ctx.room,
        agent=runtime.agent,
        room_options=runtime.room_options,
    )

    if settings.gestures_enabled:
        from gestures import autostart_requested, start_for_session

        if autostart_requested():  # python jarvis.py --gestures
            await start_for_session(ctx)


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
