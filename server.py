"""Servidor do HUD do Jarvis.

Entrega a interface web (``web/dist``) e emite tokens do LiveKit para o navegador
no formato padrão de endpoint usado pelo ``TokenSource.endpoint`` do livekit-client.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import webbrowser
from pathlib import Path
from typing import Any, Callable

import anyio
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import camera
from camera import CAMERA_DISABLED, OPEN_TIMEOUT_S, CameraError, CameraHub
from generate_playground_token import create_token
from settings import Settings, SettingsError, load_settings
from wake_hub import SECRET_ENV as WAKE_SECRET_ENV
from wake_hub import WakeHub, build_wake_router

APP_VERSION = "2.0.0"
DEFAULT_AGENT_NAME = "jarvis"
TOKEN_TTL_MINUTES = 30
# Safety net for requests still running when Ctrl+C arrives.
GRACEFUL_SHUTDOWN_S = 2
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
    "get_timers",
    "show_on_hud",
    "manage_hud_panels",
    "check_microphone",
    "end_session",
    "change_voice",
]
PC_TOOL_NAMES = [
    "open_website",
    "play_youtube",
    "open_streaming",
    "open_app",
    "close_app",
    "browser_tab",
    "media_control",
    "set_volume",
    "open_folder",
    "lock_computer",
    "take_screenshot",
    "manage_window",
    "manage_screens",
    "manage_layouts",
    "arrange_windows",
    "look_at_screen",
    "save_shortcut",
    "explain_screen",
    "copy_fix",
]
MEMORY_TOOL_NAMES = ["remember", "recall", "forget"]
EMAIL_TOOL_NAMES = ["check_email_address", "draft_email", "confirm_email_send", "cancel_pending_email"]
GESTURE_TOOL_NAMES = ["gesture_control", "gesture_shortcuts"]
INSTALL_TOOL_NAMES = ["search_apps", "prepare_app_install", "confirm_app_install", "cancel_app_install"]
CAMERA_TOOL_NAMES = ["look_at_camera", "camera_view"]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
NO_STORE = {"Cache-Control": "no-store"}
MJPEG_BOUNDARY = "frame"
COMPUTER_USE_TOOL_NAMES = [
    "click_on_screen",
    "move_mouse",
    "type_text",
    "press_keys",
    "scroll",
    "do_on_screen",
    "confirm_screen_action",
    "cancel_screen_action",
    "start_dictation",  # modo ditado (dictation.py), junto com o mouse e teclado
    "write_here",
]


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


_HOME_CACHE: dict[str, dict[str, Any]] = {}


def _geocode_home(city: str) -> dict[str, Any] | None:
    """Locate JARVIS_HOME_CITY once, so the 3D globe can draw connections from it."""
    if city in _HOME_CACHE:
        return _HOME_CACHE[city]
    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "pt"},
            timeout=8,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None
    if not results:
        return None
    place = results[0]
    home = {"name": place.get("name", city), "latitude": place["latitude"], "longitude": place["longitude"]}
    _HOME_CACHE[city] = home
    return home


def _require_local(request: Request) -> None:
    """A webcam só atende este computador: recusa Host estranho (DNS rebinding) e páginas de
    outros sites abertas no navegador (Sec-Fetch-Site), que poderiam ligá-la com um <img>."""
    host = (request.url.hostname or "").strip("[]").lower()
    if host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="A câmera só pode ser acessada pelo próprio computador.")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(status_code=403, detail="Pedido de outro site bloqueado: a câmera só atende o HUD do Jarvis.")


async def _mjpeg(hub: CameraHub, ticket: int, first: bytes, seq: int, quality: int) -> AsyncIterator[bytes]:
    """Feed MJPEG do HUD. Termina quando a câmera é desligada; o ticket volta ao hub quando o
    navegador fecha a conexão (o painel foi fechado)."""
    try:
        data: bytes | None = first
        while data is not None:
            header = f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n\r\n"
            yield header.encode() + data + b"\r\n"
            got = await anyio.to_thread.run_sync(hub.next_jpeg, ticket, seq, quality)
            data, seq = got if got is not None else (None, seq)
    except CameraError:
        pass  # o HUD mostra o motivo lendo /api/camera/state
    finally:
        hub.stop(ticket)


def _requested_agent_name(body: TokenRequest) -> str:
    agents = body.room_config.agents if body.room_config else None
    if agents and agents[0].agent_name:
        return _safe(agents[0].agent_name, DEFAULT_AGENT_NAME)
    return DEFAULT_AGENT_NAME


def _active_voice(settings: Settings) -> str | None:
    """Voice the next Gemini session starts with (VOZ-30), for the Sistema panel."""
    if settings.backend != "gemini-realtime":
        return None
    from voices import effective_voice

    return effective_voice(settings.google_voice)


def create_app(
    *,
    reload_env: bool = True,
    camera_hub: CameraHub | None = None,
    open_browser: Callable[[str], Any] = webbrowser.open,
) -> FastAPI:
    """Build the app. With ``reload_env`` the .env file is re-read on every request,
    so credentials added while the server is running are picked up without a restart.
    ``camera_hub`` replaces the real webcam (tests); ``open_browser`` opens the HUD when
    "Jarvis" is heard and no tab is open."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Ao encerrar o servidor a webcam é solta na hora (a luz apaga).
        if camera_hub is not None:
            camera_hub.off()
        else:
            camera.shutdown()

    app = FastAPI(title="Jarvis HUD", version=APP_VERSION, lifespan=lifespan)

    def current_settings() -> Settings:
        if reload_env:
            load_dotenv(ENV_FILE, override=True)
        return load_settings()

    def hub() -> CameraHub:
        return camera_hub if camera_hub is not None else camera.get_hub()

    def camera_enabled() -> bool:
        try:
            return current_settings().camera_enabled
        except SettingsError:
            return False

    def enabled_hub(request: Request) -> CameraHub:
        _require_local(request)
        if not camera_enabled():
            raise HTTPException(status_code=403, detail=CAMERA_DISABLED)
        return hub()

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
        tools = (
            TOOL_NAMES
            + (MEMORY_TOOL_NAMES if settings.memory_enabled else [])
            + (PC_TOOL_NAMES if settings.pc_control_enabled else [])
            + (GESTURE_TOOL_NAMES if settings.gestures_enabled else [])
            + (EMAIL_TOOL_NAMES if settings.email_tool_enabled else [])
            + (INSTALL_TOOL_NAMES if settings.app_install_enabled else [])
            + (CAMERA_TOOL_NAMES if settings.camera_enabled else [])
            + (COMPUTER_USE_TOOL_NAMES if settings.computer_use_enabled else [])
        )
        return {
            "version": APP_VERSION,
            "ready": not backend_errors and not livekit_errors,
            "backend": settings.backend,
            "model": _active_model(settings),
            "livekit_configured": not livekit_errors,
            "email_enabled": settings.email_tool_enabled,
            "tools": tools,
            "pc_control": settings.pc_control_enabled,
            "app_install": settings.app_install_enabled,
            "camera": settings.camera_enabled,
            "gestures": settings.gestures_enabled,
            "computer_use": settings.computer_use_enabled,
            "memory": settings.memory_enabled,
            "voice": _active_voice(settings),
            "home": _geocode_home(settings.home_city) if settings.home_city else None,
            "wake_word": {"enabled": settings.wake_word_enabled, "silence_s": settings.wake_silence_seconds},
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

    @app.get("/api/camera/state")
    def camera_state(request: Request) -> dict[str, Any]:
        _require_local(request)
        enabled = camera_enabled()
        webcam = hub()
        if not enabled and webcam.state()["active"]:
            webcam.off()  # a câmera foi desativada no .env com ela ligada
        return {"enabled": enabled, **webcam.state()}

    @app.get("/api/camera/snapshot")
    def camera_snapshot(request: Request, quality: int = Query(85, ge=30, le=95)) -> Response:
        webcam = enabled_hub(request)
        try:
            data = webcam.snapshot_jpeg(quality)
        except CameraError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(data, media_type="image/jpeg", headers=NO_STORE)

    @app.get("/api/camera/stream")
    async def camera_stream(request: Request, quality: int = Query(70, ge=30, le=95)) -> StreamingResponse:
        webcam = enabled_hub(request)
        ticket = webcam.start()
        try:
            first = await anyio.to_thread.run_sync(webcam.next_jpeg, ticket, 0, quality, OPEN_TIMEOUT_S)
        except CameraError as exc:
            webcam.stop(ticket)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if first is None:
            raise HTTPException(status_code=409, detail="A câmera foi desligada.")
        return StreamingResponse(
            _mjpeg(webcam, ticket, *first, quality),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers=NO_STORE,
        )

    @app.post("/api/camera/on")
    def camera_on(request: Request) -> dict[str, Any]:
        """Mantém a câmera ligada até /api/camera/off (o indicador CÂMERA ATIVA fica no HUD)."""
        webcam = enabled_hub(request)
        try:
            webcam.pin()
        except CameraError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"enabled": True, **webcam.state()}

    @app.post("/api/camera/off")
    def camera_off(request: Request) -> dict[str, Any]:
        """Desliga na hora para todos (feed do HUD, snapshots, gestos)."""
        _require_local(request)
        webcam = hub()
        webcam.off()
        return {"enabled": camera_enabled(), **webcam.state()}
    app.state.wake_hub = WakeHub()
    app.include_router(
        build_wake_router(
            app.state.wake_hub,
            current_settings,
            secret=os.environ.get(WAKE_SECRET_ENV),
            open_browser=open_browser,
        )
    )

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


def serve(hud_app: FastAPI, *, host: str, port: int, log_level: str) -> None:
    """``uvicorn.run`` that first ends the SSE streams of open HUD tabs, which would otherwise
    keep Ctrl+C waiting until every tab is closed."""
    import uvicorn

    class HudServer(uvicorn.Server):
        async def shutdown(self, sockets: Any = None) -> None:
            hud_app.state.wake_hub.close()
            await super().shutdown(sockets)

    config = uvicorn.Config(
        hud_app, host=host, port=port, log_level=log_level, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S
    )
    try:
        HudServer(config).run()
    except KeyboardInterrupt:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor do HUD do Jarvis.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    serve(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
