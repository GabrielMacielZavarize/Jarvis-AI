"""Ícone do Jarvis na bandeja do Windows (BAN-41).

Com ``python jarvis.py --tray`` (ou ``JARVIS_TRAY=true``) o Jarvis ganha um ícone ao lado do
relógio que mostra o estado (servidor, agente, link aberto, palavra de ativação ouvindo) e um
menu: abrir o HUD, iniciar e encerrar o link, ligar e desligar os gestos, iniciar com o Windows,
reiniciar e sair. Com ``pythonw`` não há janela de console: tudo o que o terminal mostraria vai
para ``logs/jarvis.log``, com rotação.

O ícone em si é Win32 puro (``tray_icon.py``). Aqui fica o que não depende do Windows: o estado,
o menu, as rotas do servidor, a entrada em ``HKCU\\...\\Run`` e os logs em arquivo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Literal, Protocol

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from settings import SettingsError, _parse_bool
from wake_hub import TRAY_SECRET_ENV, WakeHub, _require_hud

logger = logging.getLogger("jarvis-tray")

ROOT = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform == "win32"
SECRET_ENV = TRAY_SECRET_ENV
SECRET_HEADER = "X-Jarvis-Tray"
POLL_S = 2.0
HTTP_TIMEOUT_S = 1.5
LOG_DIR = ROOT / "logs"
LOG_FILE = "jarvis.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 5
LOG_FORMAT = "%(asctime)s [%(name)s] %(message)s"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Jarvis"
# O menu do Windows corta a dica do ícone em 127 caracteres.
TIP_MAX = 127

LEVEL_LABELS = {
    "off": "servidor parado",
    "warn": "agente parado",
    "ready": "pronto",
    "listening": "ouvindo",
    "link": "link aberto",
}


def wanted(flag: bool) -> bool:
    """--tray or JARVIS_TRAY=true, and only on Windows (elsewhere Jarvis runs as before)."""
    try:
        on = flag or _parse_bool(os.environ.get("JARVIS_TRAY"), "JARVIS_TRAY", default=False)
    except SettingsError as exc:
        print(f"[BANDEJA] {exc}")
        return False
    if on and not IS_WINDOWS:
        print("[BANDEJA] O ícone na bandeja só existe no Windows; o Jarvis segue sem ele.")
        return False
    return on


# ───────────────────────── estado e menu ─────────────────────────


@dataclass(frozen=True)
class TrayState:
    server: bool = False
    # None: o Jarvis subiu com --no-agent.
    agent: bool | None = None
    link: bool = False
    listening: bool = False
    gestures: bool = False
    gestures_available: bool = False
    autostart: bool = False

    @property
    def level(self) -> str:
        if not self.server:
            return "off"
        if self.link:
            return "link"
        if self.agent is False:
            return "warn"
        return "listening" if self.listening else "ready"

    def tooltip(self) -> str:
        agent = {None: "desligado", True: "ok", False: "parado"}[self.agent]
        lines = [
            f"Jarvis: {LEVEL_LABELS[self.level]}",
            f"Servidor: {'ok' if self.server else 'parado'} | Agente: {agent}",
            f"Link: {'aberto' if self.link else 'fechado'}",
        ]
        if self.listening:
            lines.append("Palavra de ativação: ouvindo")
        if self.gestures:
            lines.append("Gestos: ligados")
        return "\n".join(lines)[:TIP_MAX]


@dataclass(frozen=True)
class MenuEntry:
    command: str
    label: str = ""
    enabled: bool = True
    checked: bool = False
    default: bool = False

    @property
    def separator(self) -> bool:
        return not self.command and not self.label


SEPARATOR = MenuEntry("")


def build_menu(state: TrayState) -> list[MenuEntry]:
    link = MenuEntry("link_stop", "Encerrar o link") if state.link else MenuEntry("link_start", "Iniciar o link")
    return [
        MenuEntry("", f"Jarvis: {LEVEL_LABELS[state.level]}", enabled=False),
        SEPARATOR,
        MenuEntry("open_hud", "Abrir o HUD", enabled=state.server, default=True),
        MenuEntry(link.command, link.label, enabled=state.server),
        MenuEntry("gestures", "Gestos", enabled=state.gestures_available, checked=state.gestures),
        SEPARATOR,
        MenuEntry("autostart", "Iniciar com o Windows", checked=state.autostart),
        MenuEntry("logs", "Abrir a pasta de logs"),
        SEPARATOR,
        MenuEntry("restart", "Reiniciar o Jarvis"),
        MenuEntry("quit", "Sair"),
    ]


class GestureSwitch(Protocol):
    @property
    def running(self) -> bool: ...

    def start(self) -> str: ...

    def stop(self) -> str: ...


class TrayController:
    """Everything the icon shows and does, without any Win32 (testable anywhere)."""

    def __init__(
        self,
        *,
        hud_url: str,
        secret: str,
        agent: Callable[[], bool | None] = lambda: None,
        gestures: Callable[[], GestureSwitch] | None = None,
        autostart: Autostart | None = None,
        stop_server: Callable[[], None] = lambda: None,
        open_browser: Callable[[str], Any] = webbrowser.open,
        open_folder: Callable[[Path], Any] | None = None,
        http: Any = requests,
        log_dir: Path = LOG_DIR,
    ) -> None:
        self.hud_url = hud_url.rstrip("/")
        self._secret = secret
        self._agent = agent
        self._gesture_factory = gestures
        self._gestures: GestureSwitch | None = None
        self._gestures_started = False
        self.autostart = autostart or Autostart()
        self._stop_server = stop_server
        self._open_browser = open_browser
        self._open_folder = open_folder or _open_folder
        self._http = http
        self.log_dir = log_dir
        self.restart_requested = False
        self.last_state = TrayState()

    def poll(self) -> TrayState:
        hub = self._hub_state()
        gestures = self._gesture_service()
        try:
            autostart = self.autostart.enabled()
        except OSError:
            autostart = False
        self.last_state = TrayState(
            server=hub is not None,
            agent=self._agent(),
            link=bool(hub and hub.get("link")),
            listening=bool(hub and hub.get("listening")),
            gestures=bool(gestures and gestures.running),
            gestures_available=gestures is not None,
            autostart=autostart,
        )
        return self.last_state

    def menu(self, state: TrayState | None = None) -> list[MenuEntry]:
        return build_menu(state or self.last_state)

    def run(self, command: str) -> str | None:
        """Carry out one menu command; the text, if any, becomes a notification."""
        if command == "open_hud":
            self._open_browser(f"{self.hud_url}/")
        elif command in ("link_start", "link_stop"):
            return self._link("start" if command == "link_start" else "stop")
        elif command == "gestures":
            return self._toggle_gestures()
        elif command == "autostart":
            return self._toggle_autostart()
        elif command == "logs":
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._open_folder(self.log_dir)
        elif command == "restart":
            self.restart_requested = True
            self._stop_server()
        elif command == "quit":
            self._stop_server()
        return None

    def watch(self, on_change: Callable[[TrayState], None], stop: threading.Event, interval: float = POLL_S) -> None:
        """Poll until ``stop`` is set, calling ``on_change`` whenever the state changes."""
        last: TrayState | None = None
        while not stop.is_set():
            try:
                state = self.poll()
            except Exception:
                logger.exception("Falha ao ler o estado do Jarvis para a bandeja.")
                state = TrayState()
            if state != last:
                last = state
                on_change(state)
            stop.wait(interval)

    def shutdown(self) -> None:
        """Turn off the gestures this menu turned on (the webcam goes free)."""
        if self._gestures_started and self._gestures is not None and self._gestures.running:
            print(f"[GESTOS] {self._gestures.stop()}")

    # --- internos --------------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {SECRET_HEADER: self._secret}

    def _hub_state(self) -> dict[str, Any] | None:
        try:
            response = self._http.get(f"{self.hud_url}/api/tray/state", headers=self._headers(), timeout=HTTP_TIMEOUT_S)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _link(self, action: str) -> str | None:
        try:
            response = self._http.post(
                f"{self.hud_url}/api/tray/link", json={"action": action}, headers=self._headers(), timeout=HTTP_TIMEOUT_S
            )
            response.raise_for_status()
            result = response.json()
        except Exception:
            return "O servidor do HUD não respondeu."
        if action == "stop":
            return None if result.get("closed") else "Nenhum link aberto."
        if not result.get("accepted"):
            return "O link já está aberto ou abrindo."
        return "Abrindo o HUD para conectar o link." if result.get("opened_browser") else None

    def _gesture_service(self) -> GestureSwitch | None:
        if self._gestures is None and self._gesture_factory is not None:
            try:
                self._gestures = self._gesture_factory()
            except Exception as exc:
                logger.warning("Gestos indisponíveis na bandeja: %s", exc)
                self._gesture_factory = None
        return self._gestures

    def _toggle_gestures(self) -> str:
        service = self._gesture_service()
        if service is None:
            return "Os gestos estão desligados no .env (JARVIS_ENABLE_GESTURES)."
        if service.running:
            self._gestures_started = False
            return service.stop()
        self._gestures_started = True
        return service.start()

    def _toggle_autostart(self) -> str:
        try:
            on = not self.autostart.enabled()
            self.autostart.set(on)
        except OSError as exc:
            return f"Não consegui mudar o início com o Windows: {exc}"
        return "O Jarvis vai abrir junto com o Windows." if on else "O Jarvis não abre mais com o Windows."


def _open_folder(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606


def stop_server(app: Any) -> None:
    """Ask the uvicorn server started by ``server.serve`` to shut down (like Ctrl+C)."""
    server = getattr(app.state, "uvicorn", None)
    if server is not None:
        server.should_exit = True


def start_icon(controller: TrayController) -> Any:
    """Show the icon on its own thread. Returns it (``stop()`` removes it) or None off Windows."""
    if not IS_WINDOWS:
        return None
    from tray_icon import Win32TrayIcon

    icon = Win32TrayIcon(controller)
    threading.Thread(target=icon.run, name="jarvis-tray", daemon=True).start()
    return icon


def new_secret() -> str:
    """Shared with the server before it is imported, so only this process drives /api/tray."""
    secret = secrets.token_urlsafe(24)
    os.environ[SECRET_ENV] = secret
    return secret


# ───────────────────────── rotas do servidor ─────────────────────────


class LinkRequest(BaseModel):
    action: Literal["start", "stop"]


def build_tray_router(hub: WakeHub, *, secret: str | None, open_browser: Callable[[str], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/tray")

    def require_tray(request: Request) -> None:
        _require_hud(request)
        sent = request.headers.get(SECRET_HEADER)
        if not secret or sent is None or not secrets.compare_digest(sent, secret):
            raise HTTPException(status_code=403, detail="Somente o ícone da bandeja usa este endpoint.")

    @router.get("/state")
    async def state(request: Request) -> dict[str, Any]:
        require_tray(request)
        status = hub.status()
        return {"link": hub.link_open(), "listening": status["listening"], "detector": status["detector"], "tabs": len(hub.clients)}

    @router.post("/link")
    async def link(body: LinkRequest, request: Request) -> dict[str, Any]:
        require_tray(request)
        if body.action == "stop":
            return {"closed": hub.sleep()}
        result = hub.trigger(1.0, reason="tray")
        if result["opened_browser"]:
            await asyncio.to_thread(open_browser, str(request.base_url))
        return result

    return router


# ───────────────────────── iniciar com o Windows ─────────────────────────


class Registry(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class RunKey:
    """HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (no admin rights needed)."""

    def get(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return str(value)

    def set(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def pythonw_executable(executable: str | None = None) -> str:
    """pythonw.exe next to the running python.exe (no console window), if it exists."""
    path = Path(executable or sys.executable)
    windowless = path.with_name("pythonw.exe")
    return str(windowless) if path.name.lower() == "python.exe" and windowless.exists() else str(path)


def jarvis_command(extra: list[str] | None = None, executable: str | None = None) -> list[str]:
    return [pythonw_executable(executable), str(ROOT / "jarvis.py"), "--tray", *(extra or [])]


class Autostart:
    """Start Jarvis (tray, no console, no browser tab) when the user logs in to Windows."""

    def __init__(self, registry: Registry | None = None, command: list[str] | None = None) -> None:
        self._registry = registry
        self.command = subprocess.list2cmdline(command or jarvis_command(["--no-browser"]))

    @property
    def registry(self) -> Registry | None:
        if self._registry is None and IS_WINDOWS:
            self._registry = RunKey()
        return self._registry

    def enabled(self) -> bool:
        return self.registry is not None and bool(self.registry.get(RUN_VALUE))

    def set(self, on: bool) -> None:
        if self.registry is None:
            raise OSError("só existe no Windows")
        if on:
            self.registry.set(RUN_VALUE, self.command)
        else:
            self.registry.delete(RUN_VALUE)

    def refresh(self) -> bool:
        """Point an existing entry at this folder and venv (the project moved). True if rewritten."""
        if self.registry is None:
            return False
        current = self.registry.get(RUN_VALUE)
        if not current or current == self.command:
            return False
        self.registry.set(RUN_VALUE, self.command)
        return True


def relaunch(argv: list[str] | None = None, *, popen: Callable[..., Any] = subprocess.Popen) -> Any:
    """Start a fresh Jarvis after this one has freed the port (menu Reiniciar)."""
    args = [arg for arg in (sys.argv[1:] if argv is None else argv) if arg not in ("--tray", "--no-browser")]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return popen(jarvis_command([*args, "--no-browser"]), cwd=ROOT, creationflags=flags, close_fds=True)


# ───────────────────────── logs em arquivo ─────────────────────────


class _LogStream:
    """File-like object that sends print() lines to a logger."""

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, log: logging.Logger) -> None:
        self._log = log
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            if line.strip():
                self._log.info(line.rstrip())
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


def setup_file_logging(log_dir: Path = LOG_DIR) -> Path:
    """Send logging, print() and the children's output to ``logs/jarvis.log`` (1 MB x 5 files).

    With pythonw there is no console: without this everything printed would be lost."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE
    handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    # Com console (python jarvis.py --tray) as linhas continuam aparecendo nele também.
    console = sys.__stdout__
    if console is not None:
        if hasattr(console, "reconfigure"):
            console.reconfigure(errors="replace")
        root.addHandler(logging.StreamHandler(console))
    for name in ("jarvis", "jarvis.erro"):
        logging.getLogger(name).setLevel(logging.INFO)
    sys.stdout = _LogStream(logging.getLogger("jarvis"))
    sys.stderr = _LogStream(logging.getLogger("jarvis.erro"))
    # O agente e o detector escrevem num pipe que este processo lê: sem buffer e sempre em UTF-8.
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    return path


def child_output() -> dict[str, Any]:
    """Popen arguments that pipe a child's output to this process (see ``pump_output``)."""
    kwargs: dict[str, Any] = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def pump_output(process: Any, name: str) -> threading.Thread | None:
    """Copy a child's output into the log, line by line, until it exits."""
    stream = getattr(process, "stdout", None)
    if stream is None:
        return None
    log = logging.getLogger(f"jarvis.{name}")
    log.setLevel(logging.INFO)

    def copy() -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                log.info(line)

    thread = threading.Thread(target=copy, name=f"log-{name}", daemon=True)
    thread.start()
    return thread
