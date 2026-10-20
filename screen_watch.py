"""Fica de olho no terminal (protocolo OLH-35).

"Jarvis, fica de olho no terminal" (ou "no PhpStorm", "nessa janela") liga um vigia que lê o
texto daquela janela a cada poucos segundos, pela mesma UI Automation do assistente de tela
(TEL-31) e sem prints. Quando aparece um erro novo (Traceback, exceção, Fatal error, teste
falhando, erro de build), sai um aviso pelo caminho dos avisos proativos (PRO-28): com o link
aberto o Jarvis fala e pergunta se quer a explicação; com o link fechado valem as regras de
prioridade, silêncio e assuntos silenciados que já existem. "Sim" chama o ``explain_screen``
com ``target="watched"`` sobre a janela vigiada.

O vigia roda no servidor do HUD, como os outros monitores, porque precisa continuar com o link
fechado. O agente liga, desliga e consulta pelo ``/api/proactive/watch``. Ele para sozinho
quando a janela fecha, quando ela vira uma janela que nunca é lida ou depois de
``IDLE_STOP_S`` sem o texto mudar.

Cuidados: o texto passa pelo ``redact_secrets`` antes de qualquer coisa; só as linhas novas
são procuradas; cada erro avisa uma vez por vigia; e o texto da tela é dado, nunca ordem
(o aviso vai pelo ``announcement_instruction``, que trata o texto como dado).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import requests
from fastapi import APIRouter, Request
from livekit.agents import RunContext, function_tool
from pydantic import BaseModel

import screen_assist
from computer_use import WindowInfo, is_hud, norm
from hud import show_card, tool_status
from proactive import API_PREFIX, TICK_S, Notice, _require_local

logger = logging.getLogger("jarvis-vigia")

IS_WINDOWS = sys.platform == "win32"
PROTOCOL = "OLH-35"
TOPIC = "watch"
WATCH_PATH = f"{API_PREFIX}/watch"

POLL_S = TICK_S
IDLE_STOP_S = 30 * 60.0
# Dois avisos seguidos do vigia ficam pelo menos este tempo separados.
NOTICE_GAP_S = 20.0
MAX_SEEN = 200
MAX_SUMMARY_CHARS = 160
TRACEBACK_LOOKAHEAD = 80

TERMINAL_PROCESSES = {
    "windowsterminal.exe", "openconsole.exe", "conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "wt.exe", "wsl.exe", "wslhost.exe", "bash.exe", "mintty.exe", "alacritty.exe", "wezterm-gui.exe",
    "hyper.exe", "tabby.exe", "conemu64.exe", "conemu.exe",
}
TERMINAL_WORDS = {"terminal", "console", "powershell", "prompt", "cmd", "wsl", "bash", "shell"}
THIS_WINDOW_WORDS = {"", "essa", "esta", "nessa", "nesta", "aqui", "atual", "isso", "essa janela", "esta janela"}
APP_ALIASES = {"vs code": "code", "vscode": "code", "visual studio code": "code", "navegador": "chrome"}
FILLER_WORDS = {"o", "a", "no", "na", "do", "da", "de", "janela", "aba", "app", "programa"}

# Linhas que abrem um erro. A pilha do Python vira um aviso só, pela linha da exceção.
TRACEBACK = re.compile(r"^\s*Traceback \(most recent call last\):")
EXCEPTION_LINE = re.compile(r"^\s*(Uncaught )?[A-Za-z_][\w.$\\]*(Exception|Error)(: |$)")
ERROR_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("php", re.compile(r"^\s*(PHP )?(Fatal error|Parse error)\b")),
    ("exception", EXCEPTION_LINE),
    ("exception", re.compile(r"^\s*Exception in thread \"")),
    ("exception", re.compile(r"\bUnhandledPromiseRejection")),
    ("test", re.compile(
        r"^\s*FAILED \S|^=+ .*\b\d+ failed\b|^\s*FAILURES!|^\s*Tests?:\s+\d+ failed|^\s*FAIL\s+\S"
        r"|^\s*Tests run: .*Failures: [1-9]|^\s*\d+ failing\b"
    )),
    ("build", re.compile(
        r"\berror (TS|CS)\d+:|^\s*error(\[E\d+\])?: |^\s*npm (ERR!|error) |^\s*ERROR in |^\s*BUILD FAILED"
        r"|^\s*make(\[\d+\])?: \*\*\*|\bCompilation failed\b|\bBuild failed\b|^\s*error: (linker|could not compile)"
    )),
]
KIND_LABELS = {"php": "Erro do PHP", "exception": "Exceção", "test": "Teste falhando", "build": "Erro de build"}
_VOLATILE = re.compile(r"0x[0-9a-f]+|\d+")


@dataclass(frozen=True)
class FoundError:
    kind: str
    summary: str

    @property
    def signature(self) -> str:
        return f"{self.kind}:" + " ".join(_VOLATILE.sub("#", self.summary.lower()).split())


def _summary(line: str) -> str:
    text = " ".join(line.split())
    return text if len(text) <= MAX_SUMMARY_CHARS else text[: MAX_SUMMARY_CHARS - 1] + "…"


def find_errors(lines: list[str], new: set[int] | None = None) -> list[FoundError]:
    """Errors that start on the lines in ``new`` (all of them when None), oldest first."""
    found: list[FoundError] = []
    used: set[int] = set()
    for index, line in enumerate(lines):
        if index in used or (new is not None and index not in new):
            continue
        if TRACEBACK.match(line):
            # A linha da exceção fecha a pilha; sem ela ainda, ela mesma vira o aviso depois.
            for ahead in range(index + 1, min(len(lines), index + TRACEBACK_LOOKAHEAD)):
                candidate = lines[ahead]
                if candidate[:1].strip() and EXCEPTION_LINE.match(candidate):
                    found.append(FoundError("exception", _summary(candidate)))
                    used.add(ahead)
                    break
            continue
        for kind, pattern in ERROR_RULES:
            if pattern.search(line):
                found.append(FoundError(kind, _summary(line)))
                break
    return found


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


# ───────────────────────── Windows (trocado nos testes) ─────────────────────────


def _win_windows() -> list[WindowInfo]:
    """Visible top-level windows, most recently used first."""
    import win_desktop

    return [WindowInfo(hwnd=w.hwnd, title=w.title, class_name="", process=w.process) for w in win_desktop.windows()]


def _win_window(hwnd: int) -> WindowInfo | None:
    """The window as it is now (title may change), or None when it was closed."""
    if not IS_WINDOWS:
        return None
    import ctypes

    from computer_use import window_info

    if not ctypes.windll.user32.IsWindow(hwnd):
        return None
    return window_info(hwnd)


def _win_read(hwnd: int) -> str | None:
    return screen_assist._win_visible_text(hwnd) or screen_assist._win_window_text(hwnd)


# ───────────────────────── qual janela ─────────────────────────


class WatchError(Exception):
    """Mensagem em PT-BR, pronta para o modelo repetir ao usuário."""


def _query_words(query: str) -> str:
    return " ".join(word for word in norm(query).split() if word not in FILLER_WORDS)


def describe_window(window: WindowInfo) -> str:
    if window.process in TERMINAL_PROCESSES:
        return f"o terminal '{screen_assist._short(window.title, 40)}'" if window.title else "o terminal"
    return screen_assist.window_label(window)


def find_window(query: str | None) -> WindowInfo:
    """'terminal', 'phpstorm', 'essa janela'... -> the window to watch; raises WatchError."""
    if not IS_WINDOWS:
        raise WatchError("vigiar uma janela só funciona no Windows.")
    wanted = _query_words(query or "")
    if wanted in THIS_WINDOW_WORDS:
        window = screen_assist._target_window()
        if window is None:
            raise WatchError("o HUD está em foco; clique na janela que quer que eu vigie e peça de novo.")
    else:
        wanted = APP_ALIASES.get(wanted, wanted)
        candidates = [w for w in _win_windows() if not is_hud(w)]
        if set(wanted.split()) & TERMINAL_WORDS:
            matches = [w for w in candidates if w.process in TERMINAL_PROCESSES]
        else:
            matches = [
                w for w in candidates
                if wanted in norm(w.title) or wanted.replace(" ", "") in w.process.removesuffix(".exe")
            ]
        if not matches:
            raise WatchError(f"não achei nenhuma janela aberta de '{query}'.")
        window = matches[0]
    if reason := screen_assist.never_read_reason(window):
        raise WatchError(f"essa janela é {reason}; por segurança eu não leio.")
    return window


# ───────────────────────── vigia (servidor do HUD) ─────────────────────────


@dataclass
class Watch:
    window: WindowInfo
    label: str
    started: float
    changed: float
    text: str = ""
    lines: set[str] = field(default_factory=set)
    seen: list[str] = field(default_factory=list)
    last_notice: float | None = None
    last_error: str = ""
    errors: int = 0

    def status(self, clock: float) -> dict[str, Any]:
        return {
            "hwnd": self.window.hwnd,
            "title": self.window.title,
            "process": self.window.process,
            "label": self.label,
            "minutes": round((clock - self.started) / 60),
            "errors": self.errors,
            "last_error": self.last_error,
            "readable": bool(self.text.strip()),
        }


class WindowWatcher:
    """PRO-28 monitor that watches one window's text for new errors."""

    topic = TOPIC
    interval = POLL_S

    def __init__(
        self,
        *,
        read: Callable[[int], str | None] = _win_read,
        lookup: Callable[[int], WindowInfo | None] = _win_window,
        finder: Callable[[str | None], WindowInfo] = find_window,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.read = read
        self.lookup = lookup
        self.finder = finder
        self._clock = clock
        self._lock = threading.Lock()
        self.watch: Watch | None = None

    def _snapshot(self, hwnd: int) -> str:
        text = self.read(hwnd) or ""
        return screen_assist.redact_secrets(text)[0]

    def start(self, query: str | None) -> Watch:
        window = self.finder(query)
        clock = self._clock()
        text = self._snapshot(window.hwnd)
        lines = _lines(text)
        # O que já estava na tela ao ligar não é erro novo.
        seen = [error.signature for error in find_errors(lines)]
        watch = Watch(window=window, label=describe_window(window), started=clock, changed=clock,
                      text=text, lines=set(lines), seen=seen[-MAX_SEEN:])
        with self._lock:
            self.watch = watch
        logger.info("OLH-35: vigiando %s (%s).", watch.label, window.process)
        return watch

    def stop(self) -> Watch | None:
        with self._lock:
            watch, self.watch = self.watch, None
        if watch is not None:
            logger.info("OLH-35: parei de vigiar %s.", watch.label)
        return watch

    def status(self) -> dict[str, Any] | None:
        watch = self.watch
        return watch.status(self._clock()) if watch else None

    def _ended(self, watch: Watch, why: str) -> list[Notice]:
        with self._lock:
            if self.watch is watch:
                self.watch = None
        logger.info("OLH-35: parei de vigiar %s: %s", watch.label, why)
        return [Notice(TOPIC, "low", "Vigia encerrado", f"Parei de vigiar {watch.label}: {why}.")]

    def check(self, now: dt.datetime, clock: float) -> list[Notice]:
        watch = self.watch
        if watch is None:
            return []
        current = self.lookup(watch.window.hwnd)
        if current is None:
            return self._ended(watch, "a janela fechou")
        if reason := screen_assist.never_read_reason(current):
            return self._ended(watch, f"ela virou {reason}, que eu não leio")
        if clock - watch.changed >= IDLE_STOP_S:
            return self._ended(watch, f"{round(IDLE_STOP_S / 60)} minutos sem nada mudar")
        text = self._snapshot(watch.window.hwnd)
        if not text or text == watch.text:
            return []
        lines = _lines(text)
        new = {index for index, line in enumerate(lines) if line.strip() and line not in watch.lines}
        watch.text, watch.lines, watch.changed = text, set(lines), clock
        fresh = [error for error in find_errors(lines, new) if error.signature not in watch.seen]
        if not fresh:
            return []
        for error in fresh:
            watch.seen.append(error.signature)
        del watch.seen[:-MAX_SEEN]
        if watch.last_notice is not None and clock - watch.last_notice < NOTICE_GAP_S:
            return []
        latest = fresh[0]  # o primeiro costuma ser a causa; os outros vêm dele
        watch.last_notice = clock
        watch.last_error = latest.summary
        watch.errors += 1
        extra = f" (e mais {len(fresh) - 1})" if len(fresh) > 1 else ""
        message = f"Apareceu um erro novo em {watch.label}: {latest.summary}{extra}. Quer que eu explique esse erro?"
        return [Notice(TOPIC, "normal", KIND_LABELS[latest.kind], message)]


def attach_screen_watch(engine: Any, settings: Any) -> WindowWatcher | None:
    """Add the watcher to the PRO-28 engine when the PC control (and so TEL-31) is on."""
    if engine is None or settings is None or not settings.pc_control_enabled:
        return None
    watcher = WindowWatcher()
    engine.monitors.append(watcher)
    return watcher


class WatchRequest(BaseModel):
    action: Literal["start", "stop"]
    window: str | None = None


def build_watch_router(watcher: Callable[[], WindowWatcher | None]) -> APIRouter:
    router = APIRouter(prefix=WATCH_PATH)

    @router.get("")
    async def watch_status(request: Request) -> dict[str, Any]:
        _require_local(request)
        current = watcher()
        return {"enabled": current is not None, "watch": current.status() if current else None}

    @router.post("")
    async def watch_change(request: Request, body: WatchRequest) -> dict[str, Any]:
        _require_local(request)
        current = watcher()
        if current is None:
            return {"ok": False, "error": "o vigia precisa dos avisos (JARVIS_PROACTIVE) e do controle do PC ligados."}
        if body.action == "stop":
            stopped = await asyncio.to_thread(current.stop)
            return {"ok": True, "stopped": stopped.label if stopped else None}
        try:
            await asyncio.to_thread(current.start, (body.window or "")[:80])
        except (WatchError, screen_assist.ScreenAssistError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "watch": current.status()}

    return router


# ───────────────────────── agente (worker do link) ─────────────────────────

HUD_URL = "http://127.0.0.1:8000"


def configure(hud_url: str) -> None:
    global HUD_URL
    HUD_URL = hud_url.rstrip("/")


def _call(method: str, payload: dict[str, Any] | None = None, *, http: Any = requests) -> dict[str, Any] | None:
    try:
        if method == "GET":
            response = http.get(f"{HUD_URL}{WATCH_PATH}", timeout=3.0)
        else:
            response = http.post(f"{HUD_URL}{WATCH_PATH}", json=payload, timeout=10.0)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError):
        return None
    return body if isinstance(body, dict) else None


def watched_window() -> WindowInfo | None:
    """The window the HUD server is watching (for explain_screen target="watched")."""
    body = _call("GET")
    watch = (body or {}).get("watch")
    if not isinstance(watch, dict) or not watch.get("hwnd"):
        return None
    return WindowInfo(hwnd=int(watch["hwnd"]), title=str(watch.get("title") or ""), class_name="",
                      process=str(watch.get("process") or ""))


def _status_card(watch: dict[str, Any] | None, message: str = "") -> dict[str, str]:
    if not watch:
        return {"title": f"Vigia · {PROTOCOL}", "content": message or "Não estou vigiando nenhuma janela."}
    lines = [f"Vigiando {watch['label']} há {watch['minutes']} min.", f"Erros avisados: {watch['errors']}."]
    if watch.get("last_error"):
        lines.append(f"Último: {watch['last_error']}")
    return {"title": f"Vigia · {PROTOCOL}", "content": "\n".join(lines)}


@function_tool()
async def watch_screen(
    context: RunContext,
    action: Literal["start", "stop", "status"],
    window: str | None = None,
) -> str:
    """Keep an eye on a window and warn when a new error shows up (Traceback, exception, Fatal
    error, failed test, build error), then offer to explain it.

    - "fica de olho no terminal" → start, window "terminal"; "no PhpStorm" → window "phpstorm";
      "nessa janela" → window omitted (the focused window).
    - "para de vigiar" / "pode parar de olhar o terminal" → stop.
    - "o que você está vigiando?" → status.
    It reads the window text only (no screenshots) every few seconds and stops by itself when the
    window closes or after 30 minutes without changes. When the notice comes and the user says
    yes, call explain_screen with task explain_error and target watched.

    Args:
        action: start, stop or status.
        window: For start: "terminal", an app name ("phpstorm", "vs code") or words of the window
            title. Omit for the focused window.
    """
    await tool_status("watch_screen", "running", action)
    if action == "status":
        body = await asyncio.to_thread(_call, "GET")
        if body is None:
            await tool_status("watch_screen", "error", "servidor do HUD")
            return "Não consegui falar com o servidor do HUD agora."
        watch = body.get("watch")
        await show_card("note", _status_card(watch))
        await tool_status("watch_screen", "done", action)
        if not watch:
            return "Não estou vigiando nenhuma janela."
        last = f" O último foi: {watch['last_error']}." if watch.get("last_error") else ""
        return f"Estou vigiando {watch['label']} há {watch['minutes']} minutos; avisei {watch['errors']} erro(s).{last}"

    payload: dict[str, Any] = {"action": action}
    if action == "start":
        payload["window"] = (window or "").strip()[:80]
    body = await asyncio.to_thread(_call, "POST", payload)
    if body is None:
        await tool_status("watch_screen", "error", "servidor do HUD")
        return "NÃO mudei nada: não consegui falar com o servidor do HUD."
    if not body.get("ok"):
        await tool_status("watch_screen", "error", action)
        return f"NÃO estou vigiando: {body.get('error') or 'o servidor recusou'}"
    await tool_status("watch_screen", "done", action)
    if action == "stop":
        stopped = body.get("stopped")
        await show_card("note", _status_card(None, f"Parei de vigiar {stopped}." if stopped else ""))
        return f"Parei de vigiar {stopped}." if stopped else "Eu não estava vigiando nenhuma janela."
    watch = body.get("watch") or {}
    await show_card("note", _status_card(watch))
    unreadable = (
        " Por enquanto essa janela não mostra texto que eu consiga ler; se continuar assim, não vou ver "
        "os erros dela. Avise o usuário."
        if not watch.get("readable", True) else ""
    )
    return (
        f"Estou de olho em {watch.get('label', 'na janela')}. Leio só o texto, a cada poucos segundos, e "
        "aviso quando aparecer um erro novo. Paro sozinho se a janela fechar ou depois de 30 minutos "
        f"sem mudança.{unreadable} Confirme em uma frase curta."
    )


def build_watch_tools(settings: Any) -> list[Any]:
    configure(settings.hud_url)
    screen_assist.set_watched(watched_window)
    return [watch_screen]
