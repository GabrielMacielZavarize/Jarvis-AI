from __future__ import annotations

import sys

from livekit import agents
from livekit.agents import AgentServer

from backends import build_runtime
from settings import SettingsError, get_cli_command, load_settings, should_validate_runtime_command

server = AgentServer()


@server.rtc_session(agent_name="jarvis")
async def jarvis_agent(ctx: agents.JobContext):
    settings = load_settings()
    runtime = build_runtime(settings)

    await runtime.session.start(
        room=ctx.room,
        agent=runtime.agent,
        room_options=runtime.room_options,
    )


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
