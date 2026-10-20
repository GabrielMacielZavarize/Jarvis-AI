"""Servidor do HUD do Jarvis.

Entrega a interface web (``web/dist``) e emite tokens do LiveKit para o navegador
no formato padrão de endpoint usado pelo ``TokenSource.endpoint`` do livekit-client.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import mimetypes
import os
import re
import secrets
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import webbrowser
from pathlib import Path
from typing import Any, Callable, Literal

import anyio
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import camera
import gesture_mapping
from gesture_engine import CALIBRATION_FILE as GESTURE_CALIBRATION_FILE
from camera import CAMERA_DISABLED, OPEN_TIMEOUT_S, CameraError, CameraHub
from generate_playground_token import create_token
from routines import RoutineScheduler
from context_triggers import ContextWatcher
from proactive import ProactiveEngine, build_proactive_router
from screen_watch import attach_screen_watch, build_watch_router
from presence import NEEDS_CAMERA, PresenceService, get_service, voice_action
from personas import is_persona, save_persona, saved_persona
from lan_access import DeviceRegistry, LanGuard, TlsFiles, build_lan_router, device_of, ensure_certificates, lan_addresses, lan_url
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
# O manifest do PWA precisa do tipo certo (o Windows nem sempre o conhece).
mimetypes.add_type("application/manifest+json", ".webmanifest")
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
    "set_hud_appearance",
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
DIARY_TOOL_NAMES = ["diary_lookup", "forget_diary"]
ROUTINE_TOOL_NAMES = [
    "list_routines",
    "run_routine",
    "confirm_routine_step",
    "save_routine",
    "delete_routine",
    "schedule_routine",
    "set_routine_trigger",
]

PRESENCE_TOOL_NAMES = ["presence_control"]
EMAIL_TOOL_NAMES = ["check_email_address", "draft_email", "confirm_email_send", "cancel_pending_email"]
GESTURE_TOOL_NAMES = ["gesture_control", "gesture_shortcuts"]
INSTALL_TOOL_NAMES = ["search_apps", "prepare_app_install", "confirm_app_install", "cancel_app_install"]
CAMERA_TOOL_NAMES = ["look_at_camera", "camera_view"]
CALENDAR_TOOL_NAMES = [
    "get_agenda",
    "next_meeting",
    "prepare_calendar_event",
    "prepare_calendar_update",
    "prepare_calendar_delete",
    "confirm_calendar_change",
    "cancel_calendar_change",
]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
NO_STORE = {"Cache-Control": "no-store"}
MJPEG_BOUNDARY = "frame"
PROACTIVE_TOOL_NAMES = ["set_reminder", "list_reminders", "cancel_reminder", "configure_alerts"]
WATCH_TOOL_NAMES = ["watch_screen"]
MCP_TOOL_NAMES = ["mcp_status", "confirm_mcp_action", "cancel_mcp_action"]
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


logger = logging.getLogger("jarvis-server")


class PresenceAction(BaseModel):
    action: Literal["on", "off", "status", "lock_on", "lock_off"]


class PresenceNote(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    at: float | None = None


class AgentDispatchRequest(BaseModel):
    agent_name: str | None = None
    metadata: str | None = None


class RoomConfigRequest(BaseModel):
    agents: list[AgentDispatchRequest] | None = None


class GestureBindingRequest(BaseModel):
    kind: Literal["action", "layout", "app", "site", "keys", "none"]
    value: str | None = Field(default=None, max_length=120)


class PersonaRequest(BaseModel):
    persona: str = Field(min_length=1, max_length=20)


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


# Modo ambiente do HUD: o clima muda devagar e a agenda é consultada no Google, então os dois
# ficam guardados um tempo em vez de ir à rede a cada minuto de tela ociosa.
AMBIENT_WEATHER_TTL = 10 * 60
AMBIENT_AGENDA_TTL = 5 * 60
_AMBIENT_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fetch: Callable[[], Any]) -> Any:
    hit = _AMBIENT_CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < ttl:
        return hit[1]
    try:
        value = fetch()
    except Exception:
        logger.debug("Modo ambiente: falha ao buscar %s.", key, exc_info=True)
        value = None
    _AMBIENT_CACHE[key] = (now, value)
    return value


def _next_event() -> dict[str, Any] | None:
    """The next meeting with a time in the coming 24 h (all-day events are not meetings)."""
    from calendar_tools import TZ, is_connected, list_events

    if not is_connected():
        return None
    now = dt.datetime.now(TZ)
    for event in list_events(now, now + dt.timedelta(hours=24)):
        if not event.all_day and event.end > now:
            return {
                "title": event.title,
                "start": event.start.isoformat(),
                "end": event.end.isoformat(),
                "location": event.location,
                "call": bool(event.meeting_link),
            }
    return None


def _require_local(request: Request, name: str = "A câmera", *, devices: bool = True) -> None:
    """A webcam (e o resto do que é do PC) só atende este computador ou um celular pareado
    (LAN-26): recusa Host estranho (DNS rebinding) e páginas de outros sites abertas no navegador
    (Sec-Fetch-Site), que poderiam ligá-la com um <img>. ``devices=False`` fecha a rota também
    para os celulares pareados (ex.: a fila de avisos da agenda, que é só do agente)."""
    host = (request.url.hostname or "").strip("[]").lower()
    if host not in LOCAL_HOSTS and not (devices and device_of(request) is not None):
        raise HTTPException(status_code=403, detail=f"{name} só pode ser acessada pelo próprio computador.")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise HTTPException(status_code=403, detail=f"Pedido de outro site bloqueado: {name.lower()} só atende o HUD do Jarvis.")


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


def _calendar_status(settings: Settings) -> dict[str, Any] | None:
    if not settings.calendar_enabled:
        return None
    from calendar_tools import is_connected

    return {
        "connected": is_connected(),
        "reminder_minutes": settings.calendar_reminder_minutes,
        "reminders": settings.calendar_reminder_minutes > 0,
    }


def _mcp_status(settings: Settings) -> dict[str, Any] | None:
    """MCP-32 as configured in mcp.json (the agent is who connects; here nothing connects)."""
    if not settings.mcp_enabled:
        return None
    from mcp_client import MCPConfigError, load_servers, server_problems

    try:
        servers = load_servers()
    except MCPConfigError as exc:
        return {"servers": [], "error": str(exc)}
    return {
        "servers": [
            {
                "name": server.name,
                "label": server.label,
                "tools": list(server.allowed),
                "problems": server_problems(server, os.environ),
            }
            for server in servers
        ],
        "error": None,
    }


def _requested_agent_name(body: TokenRequest) -> str:
    agents = body.room_config.agents if body.room_config else None
    if agents and agents[0].agent_name:
        return _safe(agents[0].agent_name, DEFAULT_AGENT_NAME)
    return DEFAULT_AGENT_NAME


def _active_voice(settings: Settings) -> str | None:
    """Voice the next Gemini session starts with (VOZ-30), for the Sistema panel."""
    if settings.backend != "gemini-realtime":
        return None
    from personas import load_persona
    from voices import effective_voice

    return effective_voice(settings.google_voice, persona=load_persona().id)


def _layout_names() -> list[str]:
    """Saved window layouts (layouts.json), for the gesture that applies one."""
    try:
        from pc_control import load_layouts

        return sorted(load_layouts())
    except Exception:
        return []


def create_app(
    *,
    reload_env: bool = True,
    camera_hub: CameraHub | None = None,
    open_browser: Callable[[str], Any] = webbrowser.open,
    routine_scheduler: RoutineScheduler | None = None,
    calendar_reminders: bool = True,
    proactive: Callable[[WakeHub], ProactiveEngine | None] | None = None,
    presence_service: PresenceService | None = None,
    devices: DeviceRegistry | None = None,
    context_watcher: ContextWatcher | None = None,
) -> FastAPI:
    """Build the app. With ``reload_env`` the .env file is re-read on every request,
    so credentials added while the server is running are picked up without a restart.
    ``camera_hub`` replaces the real webcam (tests); ``open_browser`` opens the HUD when
    "Jarvis" is heard (or a meeting is about to start) and no tab is open. ``routine_scheduler``
    replaces the clock-driven scheduler of the routines (tests); ``calendar_reminders=False``
    turns off the meeting reminders loop (tests); ``proactive`` builds the PRO-28 notice engine
    (tests); by default it runs when JARVIS_PROACTIVE=true; ``presence_service`` replaces the
    webcam presence detector (PRS-25, tests); ``devices`` replaces ``aparelhos.json`` (tests);
    ``context_watcher`` replaces the watcher of the routines fired by context (tests)."""

    def default_engine(wake_hub: WakeHub) -> ProactiveEngine | None:
        try:
            settings = current_settings()
        except SettingsError:
            return None
        if not settings.proactive_enabled:
            return None
        # webbrowser.open pode demorar: fora do loop do servidor.
        opener = lambda url: threading.Thread(target=open_browser, args=(url,), daemon=True).start()  # noqa: E731
        return ProactiveEngine.for_settings(settings, wake_hub, open_browser=opener)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()

        async def welcome_back() -> None:
            # Mesma via da palavra de ativação: o HUD conecta o link e o agente dá as boas-vindas.
            result = app.state.wake_hub.trigger(1.0, reason="presence")
            logger.info("Presença: boas-vindas %s.", "entregues" if result["accepted"] else "recusadas (link já aberto)")
            if result["opened_browser"]:
                await asyncio.to_thread(open_browser, f"{current_settings().hud_url}/")

        service = presence()
        service.on_welcome = lambda: loop.call_soon_threadsafe(lambda: asyncio.ensure_future(welcome_back()))
        try:
            settings = current_settings()
        except SettingsError:
            settings = None
        if settings is not None and settings.presence_enabled:
            if settings.camera_enabled:
                logger.info("Presença: %s", service.start())
            else:
                logger.warning("Presença: %s", NEEDS_CAMERA)
        # ROT-24: as rotinas agendadas vencem aqui, no processo do servidor.
        scheduler_task = asyncio.create_task(app.state.routines.run_forever(routines_enabled))
        # Rotinas por contexto: app aberto, fone conectado, chegada ou saída, rede Wi-Fi.
        context_task = asyncio.create_task(app.state.context.run_forever(context_enabled))
        reminders = asyncio.create_task(_calendar_reminders()) if calendar_reminders else None
        engine = (proactive or default_engine)(app.state.wake_hub)
        app.state.proactive = engine
        if engine is not None:
            engine.start()
        # OLH-35: o vigia de janela é mais um monitor do motor de avisos.
        app.state.screen_watch = attach_screen_watch(engine, settings)
        yield
        scheduler_task.cancel()
        context_task.cancel()
        if reminders is not None:
            reminders.cancel()
        if engine is not None:
            await engine.stop()
        service.on_welcome = None
        service.stop()
        # Ao encerrar o servidor a webcam é solta na hora (a luz apaga).
        if camera_hub is not None:
            camera_hub.off()
        else:
            camera.shutdown()

    app = FastAPI(title="Jarvis HUD", version=APP_VERSION, lifespan=lifespan)
    # LAN-26: fora do próprio PC nada responde sem um aparelho pareado. serve() preenche os
    # endereços da rede local e o certificado quando o modo --lan está ligado.
    app.state.lan_urls = []
    app.state.tls = None
    registry_box: list[DeviceRegistry] = [devices] if devices is not None else []

    def registry() -> DeviceRegistry:
        if not registry_box:
            registry_box.append(DeviceRegistry())
        return registry_box[0]

    app.add_middleware(LanGuard, registry=registry, web_dist=WEB_DIST)
    app.include_router(
        build_lan_router(
            registry,
            lambda: app.state.lan_urls,
            lambda: app.state.tls.ca_cert if app.state.tls else None,
        )
    )

    def current_settings() -> Settings:
        if reload_env:
            load_dotenv(ENV_FILE, override=True)
        return load_settings()

    def hub() -> CameraHub:
        return camera_hub if camera_hub is not None else camera.get_hub()

    def routines_enabled() -> bool:
        try:
            return current_settings().routines_enabled
        except SettingsError:
            return False

    def context_enabled() -> bool:
        try:
            settings = current_settings()
        except SettingsError:
            return False
        return settings.routines_enabled and settings.context_triggers_enabled

    def context_cooldown() -> float:
        try:
            return current_settings().context_cooldown_minutes
        except SettingsError:
            return 30.0

    def presence() -> PresenceService:
        return presence_service if presence_service is not None else get_service()

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

    async def _calendar_reminders() -> None:
        """AGD-27: N minutos antes de uma reunião, acorda o HUD (como o "Jarvis") e deixa o aviso
        na fila para o agente falar."""
        from calendar_tools import reminder_payload, run_reminder_loop

        async def on_due(events: list[Any]) -> None:
            result = app.state.wake_hub.push_reminders([reminder_payload(event) for event in events])
            if result.get("opened_browser"):
                await asyncio.to_thread(open_browser, app.state.base_url or current_settings().hud_url + "/")

        await run_reminder_loop(current_settings, on_due)

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
            + (DIARY_TOOL_NAMES if settings.diary_enabled else [])
            + (ROUTINE_TOOL_NAMES if settings.routines_enabled else [])
            + (PC_TOOL_NAMES if settings.pc_control_enabled else [])
            + (GESTURE_TOOL_NAMES if settings.gestures_enabled else [])
            + (EMAIL_TOOL_NAMES if settings.email_tool_enabled else [])
            + (INSTALL_TOOL_NAMES if settings.app_install_enabled else [])
            + (CAMERA_TOOL_NAMES if settings.camera_enabled else [])
            + (CALENDAR_TOOL_NAMES if settings.calendar_enabled else [])
            + (PRESENCE_TOOL_NAMES if settings.presence_enabled else [])
            + (COMPUTER_USE_TOOL_NAMES if settings.computer_use_enabled else [])
            + (PROACTIVE_TOOL_NAMES if settings.proactive_enabled else [])
            + (WATCH_TOOL_NAMES if settings.proactive_enabled and settings.pc_control_enabled else [])
            + (MCP_TOOL_NAMES if settings.mcp_enabled else [])
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
            "presence": settings.presence_enabled,
            "computer_use": settings.computer_use_enabled,
            "memory": settings.memory_enabled,
            "diary": settings.diary_enabled,
            "voice": _active_voice(settings),
            "routines": {
                "enabled": settings.routines_enabled,
                "scheduled": app.state.routines.scheduled_count() if settings.routines_enabled else 0,
                "context_triggers": app.state.context.trigger_count()
                if settings.routines_enabled and settings.context_triggers_enabled
                else 0,
            },
            "calendar": _calendar_status(settings),
            "proactive": settings.proactive_enabled,
            "home": _geocode_home(settings.home_city) if settings.home_city else None,
            "wake_word": {"enabled": settings.wake_word_enabled, "silence_s": settings.wake_silence_seconds},
            "lan": bool(app.state.lan_urls),
            "mcp": _mcp_status(settings),
            # HUD persona chosen on any device (None: nobody chose yet, the browser keeps its own).
            "persona": saved_persona(),
            "errors": backend_errors + livekit_errors,
        }

    @app.get("/api/persona")
    def get_persona() -> dict[str, Any]:
        return {"persona": saved_persona()}

    @app.post("/api/persona")
    def set_persona(body: PersonaRequest, request: Request) -> dict[str, Any]:
        """The HUD persona (theme) changed: the agent picks up the persona and voice (personas.py)."""
        _require_local(request, "A troca de persona")
        if not is_persona(body.persona):
            raise HTTPException(status_code=400, detail=f"Persona desconhecida: {body.persona}")
        if saved_persona() != body.persona:
            save_persona(body.persona)
            logger.info("Persona do HUD: %s.", body.persona)
        return {"persona": body.persona}

    # ── Gestos (GST-18): o painel do HUD vê e muda o que cada gesto livre faz (gestos.json) ──

    def gesture_catalog() -> dict[str, Any]:
        settings = current_settings()
        return {
            **gesture_mapping.catalog(),
            "enabled": settings.gestures_enabled,
            "layouts": _layout_names(),
            "calibrated": GESTURE_CALIBRATION_FILE.exists(),
        }

    @app.get("/api/gestures")
    def gestures(request: Request) -> dict[str, Any]:
        _require_local(request, "A configuração dos gestos")
        return gesture_catalog()

    @app.put("/api/gestures/{gesture}")
    def set_gesture(gesture: str, body: GestureBindingRequest, request: Request) -> dict[str, Any]:
        """Same rules as the voice ("o rock abre o Spotify"): closing, deleting and typing are refused.
        The engine re-reads gestos.json by its date, so the change works on the next gesture."""
        _require_local(request, "A configuração dos gestos")
        try:
            message = gesture_mapping.set_binding(gesture, body.kind, body.value)
        except gesture_mapping.MappingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.info("Gesto pelo HUD: %s", message)
        return {"message": message, **gesture_catalog()}

    @app.delete("/api/gestures/{gesture}")
    def reset_gesture(gesture: str, request: Request) -> dict[str, Any]:
        _require_local(request, "A configuração dos gestos")
        try:
            message = gesture_mapping.reset_binding(gesture)
        except gesture_mapping.MappingError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": message, **gesture_catalog()}

    @app.delete("/api/gestures")
    def reset_gestures(request: Request) -> dict[str, Any]:
        _require_local(request, "A configuração dos gestos")
        return {"message": gesture_mapping.reset_binding(None), **gesture_catalog()}

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
    @app.post("/api/calendar/reminders/claim")
    def claim_calendar_reminders(request: Request) -> dict[str, Any]:
        """O agente busca os avisos de reunião que o servidor guardou (cada um sai uma vez só)."""
        _require_local(request, "A agenda", devices=False)
        return {"reminders": app.state.wake_hub.claim_reminders()}

    def presence_state() -> dict[str, Any]:
        try:
            settings = current_settings()
            enabled, camera_on = settings.presence_enabled, settings.camera_enabled
        except SettingsError:
            enabled = camera_on = False
        state = presence().state()
        if enabled and not camera_on:
            state["error"] = NEEDS_CAMERA
        return {"enabled": enabled, **state}

    @app.get("/api/presence")
    def presence_get(request: Request) -> dict[str, Any]:
        """Estado da presença (PRS-25) para o painel Sistema: presente, ausente desde quando..."""
        _require_local(request)
        return presence_state()

    @app.post("/api/presence")
    def presence_post(body: PresenceAction, request: Request) -> dict[str, Any]:
        """Ferramenta de voz presence_control: liga/desliga e escolhe se bloqueia o PC."""
        _require_local(request)
        state = presence_state()
        if not state["enabled"]:
            raise HTTPException(status_code=403, detail="A presença está desativada. Defina JARVIS_PRESENCE=true no .env.")
        if body.action == "on" and not camera_enabled():
            raise HTTPException(status_code=403, detail=NEEDS_CAMERA)
        message = voice_action(presence(), body.action)
        return {"message": message, **presence_state()}

    @app.post("/api/presence/note")
    def presence_note(body: PresenceNote, request: Request) -> dict[str, bool]:
        """Anota algo para o resumo das boas-vindas (ex.: o fim de um timer, enviado ao criá-lo)."""
        _require_local(request)
        presence().journal.add(body.text, body.at)
        return {"ok": True}

    @app.get("/api/presence/welcome")
    def presence_welcome(request: Request) -> dict[str, Any]:
        """Boas-vindas pendentes para a conversa que acabou de abrir (entregues uma vez só)."""
        _require_local(request)
        welcome = presence().consume_welcome()
        if welcome is None:
            return {"welcome": None}
        return {"welcome": {"away_s": round(welcome.away_s), "notes": welcome.notes}}

    app.state.wake_hub = WakeHub()
    app.state.base_url = None
    app.state.proactive = None
    app.include_router(build_proactive_router(lambda: app.state.proactive))
    app.state.screen_watch = None
    app.include_router(build_watch_router(lambda: app.state.screen_watch))
    app.include_router(
        build_wake_router(
            app.state.wake_hub,
            current_settings,
            secret=os.environ.get(WAKE_SECRET_ENV),
            open_browser=open_browser,
        )
    )

    app.state.hud_url = "http://127.0.0.1:8000"
    app.state.routines = routine_scheduler or RoutineScheduler()

    def routine_due(key: str) -> None:
        """Open the link (the HUD tab, or the browser when none is open) for a scheduled routine."""
        reason = "context" if key in app.state.routines.reasons else "wake"
        if app.state.wake_hub.trigger_routine(key, reason)["opened_browser"]:
            threading.Thread(target=open_browser, args=(app.state.hud_url,), daemon=True).start()

    app.state.routines.on_due = routine_due
    app.state.context = context_watcher or ContextWatcher(
        presence=lambda: presence().state()["state"], cooldown_minutes=context_cooldown
    )
    app.state.context.fire = app.state.routines.fire

    @app.get("/api/ambient")
    def ambient(request: Request) -> dict[str, Any]:
        """Modo ambiente do HUD: clima da JARVIS_HOME_CITY e a próxima reunião, com cache."""
        _require_local(request, "A tela ambiente")
        try:
            settings = current_settings()
        except SettingsError:
            return {"weather": None, "next_event": None}
        home = _geocode_home(settings.home_city) if settings.home_city else None
        weather = None
        if home is not None:
            from weather import current_conditions

            weather = _cached(
                f"weather:{home['name']}",
                AMBIENT_WEATHER_TTL,
                lambda: {"city": home["name"], **current_conditions(home["latitude"], home["longitude"])},
            )
        event = _cached("agenda", AMBIENT_AGENDA_TTL, _next_event) if settings.calendar_enabled else None
        return {"weather": weather, "next_event": event}

    @app.get("/api/system/live")
    def system_live(request: Request) -> dict[str, Any]:
        """CPU e memória agora, para o painel Diagnóstico ao vivo (desde a consulta anterior)."""
        _require_local(request, "A leitura do sistema")
        import psutil

        return {
            "cpu": psutil.cpu_percent(interval=None),
            "per_core": psutil.cpu_percent(interval=None, percpu=True),
            "memory": psutil.virtual_memory().percent,
        }

    @app.post("/api/routines/claim")
    def claim_routine(request: Request) -> dict[str, Any]:
        """The agent picks up the scheduled routine that came due (each one is handed out once)."""
        _require_local(request)
        key = app.state.routines.claim()
        context = app.state.routines.claim_reason(key)
        return {"routine": key, **({"context": context} if context else {})}

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


def enable_lan(hud_app: FastAPI, port: int) -> list[str]:
    """LAN-26: descobre os IPs da rede de casa e prepara o certificado HTTPS para eles."""
    ips = lan_addresses()
    if not ips:
        raise RuntimeError("Nenhum IP de rede local encontrado. O PC está no Wi-Fi ou no cabo de casa?")
    hud_app.state.tls = ensure_certificates(ips)
    hud_app.state.lan_urls = [lan_url(ip, port) for ip in ips]
    return ips


def serve(hud_app: FastAPI, *, host: str, port: int, log_level: str, lan_ips: list[str] | None = None) -> None:
    """``uvicorn.run`` that first ends the SSE streams of open HUD tabs, which would otherwise
    keep Ctrl+C waiting until every tab is closed.

    With ``lan_ips`` (``--lan``) the same app also listens with HTTPS on each LAN address and the
    same port: the PC keeps http://127.0.0.1, the phone gets https://<ip> (the mic needs HTTPS)."""
    import asyncio
    import contextlib

    import uvicorn

    shown = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    hud_app.state.hud_url = f"http://{f'[{shown}]' if ':' in shown else shown}:{port}"
    extras: list[uvicorn.Server] = []

    class HudServer(uvicorn.Server):
        async def shutdown(self, sockets: Any = None) -> None:
            hud_app.state.wake_hub.close()
            for extra in extras:
                extra.should_exit = True
            await super().shutdown(sockets)

    hud_app.state.base_url = f"http://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{port}/"
    class LanServer(uvicorn.Server):
        # Ctrl+C chega ao servidor principal, que encerra este junto.
        def capture_signals(self) -> Any:
            return contextlib.nullcontext()

    config = uvicorn.Config(
        hud_app, host=host, port=port, log_level=log_level, timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S
    )
    main_server = HudServer(config)
    tls: TlsFiles | None = hud_app.state.tls
    for ip in lan_ips or []:
        if tls is None:
            break
        lan_config = uvicorn.Config(
            hud_app,
            host=ip,
            port=port,
            log_level=log_level,
            lifespan="off",
            ssl_certfile=str(tls.cert),
            ssl_keyfile=str(tls.key),
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_S,
        )
        extras.append(LanServer(lan_config))

    async def run_all() -> None:
        await asyncio.gather(main_server.serve(), *(extra.serve() for extra in extras))

    try:
        if extras:
            asyncio.run(run_all())
        else:
            main_server.run()
    except KeyboardInterrupt:
        pass


def _lan_from_env() -> bool:
    try:
        return load_settings().lan_enabled
    except SettingsError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor do HUD do Jarvis.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--lan", action="store_true", help="Atende também o celular na rede de casa (HTTPS).")
    args = parser.parse_args()

    lan_ips = enable_lan(app, args.port) if args.lan or _lan_from_env() else None
    for url in app.state.lan_urls:
        print(f"[LAN] Celular: {url}")
    serve(app, host=args.host, port=args.port, log_level="info", lan_ips=lan_ips)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
