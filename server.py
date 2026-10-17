"""Servidor do HUD do Jarvis.

Entrega a interface web (``web/dist``) e emite tokens do LiveKit para o navegador
no formato padrão de endpoint usado pelo ``TokenSource.endpoint`` do livekit-client.
"""

from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from generate_playground_token import create_token
from settings import Settings, SettingsError, load_settings

APP_VERSION = "2.0.0"
DEFAULT_AGENT_NAME = "jarvis"
TOKEN_TTL_MINUTES = 30
ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
WEB_DIST = ROOT / "web" / "dist"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\- ]{1,64}$")
TOOL_NAMES = [
    "get_weather",
    "search_web",
    "search_news",
    "get_current_time",
    "run_diagnostics",
    "set_timer",
    "show_on_hud",
]
EMAIL_TOOL_NAMES = ["draft_email", "confirm_email_send", "cancel_pending_email"]


class AgentDispatchRequest(BaseModel):
    agent_name: str | None = None
    metadata: str | None = None


class RoomConfigRequest(BaseModel):
    agents: list[AgentDispatchRequest] | None = None


class TokenRequest(BaseModel):
    room_name: str | None = None
    participant_identity: str | None = None
    participant_name: str | None = None
    room_config: RoomConfigRequest | None = None


def _safe(value: str | None, fallback: str) -> str:
    if value and SAFE_NAME.match(value):
        return value
    return fallback


def _active_model(settings: Settings) -> str:
    if settings.backend == "gemini-realtime":
        return settings.google_model
    if settings.backend == "openai-realtime":
        return settings.openai_realtime_model
    return settings.openai_llm_model


def _requested_agent_name(body: TokenRequest) -> str:
    agents = body.room_config.agents if body.room_config else None
    if agents and agents[0].agent_name:
        return _safe(agents[0].agent_name, DEFAULT_AGENT_NAME)
    return DEFAULT_AGENT_NAME


def create_app(*, reload_env: bool = True) -> FastAPI:
    """Build the app. With ``reload_env`` the .env file is re-read on every request,
    so credentials added while the server is running are picked up without a restart."""
    app = FastAPI(title="Jarvis HUD", version=APP_VERSION)

    def current_settings() -> Settings:
        if reload_env:
            load_dotenv(ENV_FILE, override=True)
        return load_settings()

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        try:
            settings = current_settings()
        except SettingsError as exc:
            return {
                "version": APP_VERSION,
                "ready": False,
                "livekit_configured": False,
                "errors": [str(exc)],
            }

        backend_errors = [*settings.backend_validation_errors(), *settings.email_validation_errors()]
        livekit_errors = settings.livekit_validation_errors()
        tools = TOOL_NAMES + (EMAIL_TOOL_NAMES if settings.email_tool_enabled else [])
        return {
            "version": APP_VERSION,
            "ready": not backend_errors and not livekit_errors,
            "backend": settings.backend,
            "model": _active_model(settings),
            "livekit_configured": not livekit_errors,
            "email_enabled": settings.email_tool_enabled,
            "tools": tools,
            "errors": backend_errors + livekit_errors,
        }

    @app.post("/api/token")
    def issue_token(body: TokenRequest | None = None) -> dict[str, str]:
        body = body or TokenRequest()
        settings = current_settings()
        errors = settings.livekit_validation_errors()
        if errors:
            raise HTTPException(status_code=503, detail=" ".join(errors))

        token = create_token(
            room=_safe(body.room_name, f"jarvis-{secrets.token_hex(4)}"),
            identity=_safe(body.participant_identity, f"operador-{secrets.token_hex(3)}"),
            name=_safe(body.participant_name, "Operador"),
            agent_name=_requested_agent_name(body),
            ttl_minutes=TOKEN_TTL_MINUTES,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        return {"server_url": settings.livekit_url or "", "participant_token": token}

    if (WEB_DIST / "index.html").exists():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="hud")
    else:

        @app.get("/", response_class=HTMLResponse)
        def missing_build() -> str:
            return (
                "<body style='background:#02060b;color:#5ff4ff;font-family:monospace;padding:40px'>"
                "<h1>J.A.R.V.I.S.</h1><p>A interface ainda não foi compilada.</p>"
                "<pre>cd web\nnpm install\nnpm run build</pre></body>"
            )

    return app


app = create_app()


def main() -> int:
    import uvicorn

    parser = argparse.ArgumentParser(description="Servidor do HUD do Jarvis.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
