"""O que os gestos fazem no Windows: janelas entre monitores, abas do navegador e mouse no ar.

Reaproveita o pc_control (memória de posições para desfazer, processos protegidos, HUD) e o
win_desktop (monitores e janelas em pixels físicos). O monitor de destino de um arremesso sai
da geometria real dos monitores, nunca de números fixos: "para cima" é o monitor que está
fisicamente acima daquele onde a janela está agora.

Continua sendo um conjunto fechado de ações visíveis: mover, estender, minimizar, desfazer,
fechar (com as mesmas proteções da voz), trocar de aba e mover/clicar o mouse.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import win_desktop

logger = logging.getLogger("jarvis-gestures")

IS_WINDOWS = sys.platform == "win32"

DIRECTION_VECTORS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
DIRECTION_LABELS = {"up": "de cima", "down": "de baixo", "left": "da esquerda", "right": "da direita"}
# Um monitor sem sobreposição com o atual só conta se estiver até este ângulo da direção pedida.
MAX_DIAGONAL_DEGREES = 50.0

VK_TAB = 0x09
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_W = 0x57
BOUNDS_CACHE_SECONDS = 5.0


class GestureActionError(Exception):
    """A gesture that could not be carried out (message is shown on the overlay)."""


@dataclass(frozen=True)
class Target:
    window: win_desktop.Window
    monitor: win_desktop.Monitor | None
    browser: bool

    @property
    def title(self) -> str:
        return self.window.title.replace("​", "").strip()


# ───────────────────────── geometria ─────────────────────────


def _center(rect: tuple[int, int, int, int]) -> tuple[float, float]:
    left, top, right, bottom = rect
    return (left + right) / 2, (top + bottom) / 2


def _bounds(monitor: win_desktop.Monitor) -> tuple[int, int, int, int]:
    return monitor.left, monitor.top, monitor.right, monitor.bottom


def same_monitor(a: win_desktop.Monitor | None, b: win_desktop.Monitor | None) -> bool:
    return a is not None and b is not None and _bounds(a) == _bounds(b)


def _distance_to_rect(x: float, y: float, rect: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = rect
    dx = max(left - x, 0.0, x - (right - 1))
    dy = max(top - y, 0.0, y - (bottom - 1))
    return math.hypot(dx, dy)


def neighbor_monitor(
    source: win_desktop.Monitor,
    direction: str,
    screens: list[win_desktop.Monitor],
    anchor: tuple[float, float] | None = None,
    bias: float = 0.0,
) -> win_desktop.Monitor | None:
    """Monitor physically next to `source` in `direction`, or None when there is none.

    `anchor` is where the window is (its center): throwing right from a tall monitor lands on
    the screen beside that height. `bias` (-1..1) is the sideways part of the hand movement, so a
    diagonal throw picks the screen on that side when two share the edge.
    """
    dx, dy = DIRECTION_VECTORS[direction]
    sx, sy = _center(_bounds(source))
    ax, ay = anchor if anchor is not None else (sx, sy)
    ax = min(max(ax, source.left), source.right - 1)
    ay = min(max(ay, source.top), source.bottom - 1)
    bias = max(-1.0, min(1.0, bias))

    # Ponto logo depois da borda na direção pedida, deslocado para o lado do viés.
    if dx:
        px = source.right if dx > 0 else source.left - 1
        py = ay + bias * source.height / 2
    else:
        py = source.bottom if dy > 0 else source.top - 1
        px = ax + bias * source.width / 2

    candidates: list[tuple[float, float, win_desktop.Monitor]] = []
    for screen in screens:
        if same_monitor(screen, source):
            continue
        # Precisa estar além do centro do monitor atual, na direção pedida.
        if (dx > 0 and screen.left < sx) or (dx < 0 and screen.right > sx):
            continue
        if (dy > 0 and screen.top < sy) or (dy < 0 and screen.bottom > sy):
            continue
        if dx:
            overlap = min(screen.bottom, source.bottom) - max(screen.top, source.top)
        else:
            overlap = min(screen.right, source.right) - max(screen.left, source.left)
        if overlap <= 0:
            cx, cy = _center(_bounds(screen))
            angle = math.degrees(math.atan2(abs((cy - sy) * dx - (cx - sx) * dy), (cx - sx) * dx + (cy - sy) * dy))
            if angle > MAX_DIAGONAL_DEGREES:
                continue
        candidates.append((_distance_to_rect(px, py, _bounds(screen)), -max(overlap, 0), screen))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def describe_direction(direction: str) -> str:
    return f"monitor {DIRECTION_LABELS[direction]}"


def throw_bias(direction: str, vector: tuple[float, float]) -> float:
    """Sideways share of the hand movement (positive = down for left/right, right for up/down)."""
    vx, vy = vector
    main, side = (vx, vy) if direction in ("left", "right") else (vy, vx)
    if abs(main) < 1e-6:
        return 0.0
    return max(-1.0, min(1.0, side / abs(main)))


# ───────────────────────── entrada (mouse e teclado) ─────────────────────────


if IS_WINDOWS:
    from ctypes import wintypes

    _ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", _ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002


class Win32Input:
    """Cursor and keys through SetCursorPos/SendInput, in physical pixels.

    SetCursorPos with per-monitor DPI awareness takes real pixel coordinates, including the
    negative x of a monitor to the left of the main one (pyautogui gets those wrong).
    """

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True) if IS_WINDOWS else None
        if self._user32 is not None:
            self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
            self._user32.SendInput.restype = wintypes.UINT

    def move(self, x: int, y: int) -> None:
        if self._user32 is None:
            return
        with win_desktop.physical_pixels():
            self._user32.SetCursorPos(int(x), int(y))

    def _send(self, *inputs: Any) -> None:
        if self._user32 is None or not inputs:
            return
        array = (_INPUT * len(inputs))(*inputs)
        self._user32.SendInput(len(inputs), ctypes.byref(array), ctypes.sizeof(_INPUT))

    def button(self, down: bool) -> None:
        if self._user32 is None:
            return
        flags = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
        self._send(_INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=_MOUSEINPUT(0, 0, 0, flags, 0, 0))))

    def keys(self, *codes: int) -> None:
        """Press a shortcut (e.g. Ctrl+W): keys down in order, then up in reverse."""
        if self._user32 is None:
            return
        down = [_INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=_KEYBDINPUT(code, 0, 0, 0, 0))) for code in codes]
        up = [
            _INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=_KEYBDINPUT(code, 0, KEYEVENTF_KEYUP, 0, 0)))
            for code in reversed(codes)
        ]
        self._send(*down, *up)


# ───────────────────────── janelas ─────────────────────────


def _foreground_hwnd() -> int:
    if not IS_WINDOWS:
        return 0
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def _window_exists(hwnd: int) -> bool:
    return bool(IS_WINDOWS and ctypes.windll.user32.IsWindow(hwnd))


def _is_maximized(hwnd: int) -> bool:
    return bool(IS_WINDOWS and ctypes.windll.user32.IsZoomed(hwnd))


def _is_minimized(hwnd: int) -> bool:
    return bool(IS_WINDOWS and ctypes.windll.user32.IsIconic(hwnd))


def _pc() -> Any:
    """pc_control, imported lazily: it pulls the LiveKit agent framework."""
    import pc_control

    return pc_control


class DesktopActions:
    """Window, tab and mouse actions for the gesture engine (one instance per engine)."""

    def __init__(self, input_device: Win32Input | None = None) -> None:
        self.input = input_device or Win32Input()
        self.own_pids = {os.getpid()}
        self._bounds: tuple[int, int, int, int] | None = None
        self._bounds_at = 0.0

    # ── alvo ──

    def grab(self) -> Target | None:
        """The window in focus (or the topmost app window when focus is on the desktop or on us)."""
        pc = _pc()
        windows = [w for w in win_desktop.windows() if w.pid not in self.own_pids]
        if not windows:
            return None
        foreground = _foreground_hwnd()
        window = next((w for w in windows if w.hwnd == foreground), None)
        window = window or next((w for w in windows if not _is_minimized(w.hwnd)), None)
        if window is None:
            return None
        rect = win_desktop.window_rect(window.hwnd)
        monitor = win_desktop.monitor_for_rect(rect, win_desktop.monitors())
        return Target(window=window, monitor=monitor, browser=window.process in pc.BROWSER_PROCESSES)

    def focus_monitor(self) -> win_desktop.Monitor | None:
        """Monitor the user is most likely looking at (where the window in focus is)."""
        target = self.grab()
        return target.monitor if target else None

    def cursor_monitor(self) -> win_desktop.Monitor | None:
        if not IS_WINDOWS:
            return None
        point = wintypes.POINT()
        with win_desktop.physical_pixels():
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return win_desktop.monitor_for_rect((point.x, point.y, point.x + 1, point.y + 1), win_desktop.monitors())

    def destination(self, target: Target, direction: str, vector: tuple[float, float]) -> win_desktop.Monitor | None:
        screens = win_desktop.monitors()
        rect = win_desktop.window_rect(target.window.hwnd)
        source = win_desktop.monitor_for_rect(rect, screens) or target.monitor
        if source is None:
            return None
        return neighbor_monitor(source, direction, screens, anchor=_center(rect), bias=throw_bias(direction, vector))

    def aim(self, target: Target, direction: str, vector: tuple[float, float]) -> str | None:
        """Label of the monitor a release would send the window to (None when there is none)."""
        return describe_direction(direction) if self.destination(target, direction, vector) else None

    # ── ações ──

    def throw(self, target: Target, direction: str, vector: tuple[float, float]) -> str:
        if not _window_exists(target.window.hwnd):
            raise GestureActionError("A janela fechou antes de eu movê-la.")
        screen = self.destination(target, direction, vector)
        if screen is None:
            raise GestureActionError(f"Não há {describe_direction(direction)}.")
        _pc()._remember_position(target.window.hwnd)
        win_desktop.move_to_monitor(target.window.hwnd, screen)
        landed = win_desktop.window_monitor(target.window.hwnd)
        if not same_monitor(landed, screen):
            raise GestureActionError(f"Tentei levar '{target.title}', mas ela não saiu do lugar.")
        return f"'{target.title}' → {describe_direction(direction)}."

    def maximize(self, target: Target) -> str:
        """'Estender': maximize the window, or restore it when it already is maximized."""
        hwnd = target.window.hwnd
        if not _window_exists(hwnd):
            raise GestureActionError("A janela fechou.")
        if _is_maximized(hwnd):
            win_desktop.show_window(hwnd, win_desktop.SW_RESTORE)
            return f"'{target.title}' restaurada."
        _pc()._remember_position(hwnd)
        win_desktop.show_window(hwnd, win_desktop.SW_MAXIMIZE)
        win_desktop.bring_to_front(hwnd)
        return f"'{target.title}' estendida."

    def minimize(self) -> str:
        target = self.grab()
        if target is None:
            raise GestureActionError("Nenhuma janela em foco para minimizar.")
        _pc()._remember_position(target.window.hwnd)
        win_desktop.show_window(target.window.hwnd, win_desktop.SW_MINIMIZE)
        return f"'{target.title}' minimizada."

    def undo(self) -> str:
        """Put back the window moved last (by gesture or by voice), where it was before."""
        pc = _pc()
        for hwnd in reversed(list(pc.MEMORY.positions)):
            if not _window_exists(hwnd):
                pc.MEMORY.positions.pop(hwnd, None)
                continue
            stack = pc.MEMORY.positions[hwnd]
            saved = stack.pop()
            if not stack:
                del pc.MEMORY.positions[hwnd]
            win_desktop.restore_placement(hwnd, saved.placement)
            title = win_desktop.window_title(hwnd) or "janela"
            return f"'{title}' voltou para onde estava."
        raise GestureActionError("Nada para desfazer.")

    def close(self, target: Target) -> str:
        """Close the window in focus; in a browser only the active tab (never the HUD tab)."""
        pc = _pc()
        window = target.window
        if not _window_exists(window.hwnd):
            raise GestureActionError("A janela já fechou.")
        if target.browser:
            if not win_desktop.bring_to_front(window.hwnd):
                raise GestureActionError("O Windows não deixou focar o navegador.")
            title = pc._active_title()
            if pc.HUD_TITLE in title:
                raise GestureActionError("A aba ativa é o HUD do Jarvis: essa eu não fecho por gesto.")
            self.input.keys(VK_CONTROL, VK_W)
            pc._forget_media_tab(title)
            return f"Fechei a aba '{title}'."
        protected = pc.PROTECTED_PROCESSES | pc._jarvis_ancestor_names()
        if window.process in protected or window.pid in self.own_pids or pc.HUD_TITLE in window.title:
            raise GestureActionError("Essa janela é do sistema ou do próprio Jarvis: não fecho.")
        win_desktop.close_window(window.hwnd)
        return f"Pedi para fechar '{target.title}'."

    def tab(self, step: int) -> str:
        target = self.grab()
        if target is None or not target.browser:
            raise GestureActionError("A janela em foco não é um navegador.")
        if _foreground_hwnd() != target.window.hwnd and not win_desktop.bring_to_front(target.window.hwnd):
            raise GestureActionError("O Windows não deixou focar o navegador.")
        if step > 0:
            self.input.keys(VK_CONTROL, VK_TAB)
            return "Próxima aba."
        self.input.keys(VK_CONTROL, VK_SHIFT, VK_TAB)
        return "Aba anterior."

    # ── mouse no ar ──

    def virtual_bounds(self) -> tuple[int, int, int, int]:
        """Rectangle around every monitor (x is negative when a monitor sits left of the main one)."""
        now = time.monotonic()
        if self._bounds is None or now - self._bounds_at > BOUNDS_CACHE_SECONDS:
            screens = win_desktop.monitors()
            if screens:
                self._bounds = (
                    min(m.left for m in screens),
                    min(m.top for m in screens),
                    max(m.right for m in screens),
                    max(m.bottom for m in screens),
                )
                self._bounds_at = now
        return self._bounds or (0, 0, 1920, 1080)

    def mouse_move(self, u: float, v: float) -> None:
        left, top, right, bottom = self.virtual_bounds()
        x = round(left + min(max(u, 0.0), 1.0) * (right - left - 1))
        y = round(top + min(max(v, 0.0), 1.0) * (bottom - top - 1))
        self.input.move(x, y)

    def mouse_down(self) -> None:
        self.input.button(True)

    def mouse_up(self) -> None:
        self.input.button(False)

    def click(self) -> None:
        self.input.button(True)
        self.input.button(False)


class DryRunActions(DesktopActions):
    """Reads the real windows and monitors but changes nothing (for `gestures.py --dry-run`)."""

    def throw(self, target: Target, direction: str, vector: tuple[float, float]) -> str:
        screen = self.destination(target, direction, vector)
        if screen is None:
            raise GestureActionError(f"Não há {describe_direction(direction)}.")
        return f"(simulação) '{target.title}' → {describe_direction(direction)}."

    def maximize(self, target: Target) -> str:
        return f"(simulação) estender '{target.title}'."

    def minimize(self) -> str:
        target = self.grab()
        return f"(simulação) minimizar '{target.title if target else '?'}'."

    def undo(self) -> str:
        return "(simulação) desfazer o último movimento."

    def close(self, target: Target) -> str:
        what = "a aba ativa de" if target.browser else "a janela"
        return f"(simulação) fechar {what} '{target.title}'."

    def tab(self, step: int) -> str:
        return "(simulação) próxima aba." if step > 0 else "(simulação) aba anterior."

    def mouse_move(self, u: float, v: float) -> None:
        return None

    def mouse_down(self) -> None:
        return None

    def mouse_up(self) -> None:
        return None

    def click(self) -> None:
        return None
