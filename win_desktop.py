"""Primitivas do desktop do Windows: monitores, janelas e captura de tela.

Usa a API Win32 via ctypes, com coordenadas físicas (DPI por monitor), para
funcionar com monitores de escalas e orientações diferentes.
"""

from __future__ import annotations

import ctypes
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import psutil

IS_WINDOWS = sys.platform == "win32"

SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WPF_RESTORETOMAXIMIZED = 0x0002
WM_CLOSE = 0x0010
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
DWMWA_CLOAKED = 14
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
# Janelas do próprio shell do Windows que nunca devem ser movidas ou fechadas.
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}


@dataclass(frozen=True)
class Monitor:
    number: int
    left: int
    top: int
    right: int
    bottom: int
    work: tuple[int, int, int, int]
    primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def orientation(self) -> str:
        return "vertical" if self.height > self.width else "horizontal"


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    process: str
    pid: int


@dataclass(frozen=True)
class Placement:
    """Where a window sits (Win32 WINDOWPLACEMENT), enough to put it back exactly."""

    flags: int
    show_cmd: int
    min_pos: tuple[int, int]
    max_pos: tuple[int, int]
    normal: tuple[int, int, int, int]

    @property
    def maximized(self) -> bool:
        if self.show_cmd == SW_SHOWMINIMIZED:
            return bool(self.flags & WPF_RESTORETOMAXIMIZED)
        return self.show_cmd == SW_MAXIMIZE


@contextmanager
def physical_pixels() -> Iterator[None]:
    """Run Win32 calls with per-monitor DPI awareness (real pixel coordinates)."""
    if not IS_WINDOWS:
        yield
        return
    user32 = ctypes.windll.user32
    previous = user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    try:
        yield
    finally:
        if previous:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))


if IS_WINDOWS:
    from ctypes import wintypes

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", ctypes.c_wchar * 32),
        ]

    class _WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.UINT),
            ("flags", wintypes.UINT),
            ("showCmd", wintypes.UINT),
            ("ptMinPosition", wintypes.POINT),
            ("ptMaxPosition", wintypes.POINT),
            ("rcNormalPosition", _RECT),
        ]

    _MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_double
    )
    _WINDOW_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def monitors() -> list[Monitor]:
    """Monitors numbered like Windows does (\\\\.\\DISPLAY1 → tela 1)."""
    if not IS_WINDOWS:
        return []
    found: list[Monitor] = []

    def collect(handle: Any, _hdc: Any, _rect: Any, _data: Any) -> int:
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info))
        digits = "".join(ch for ch in info.szDevice if ch.isdigit())
        found.append(
            Monitor(
                number=int(digits) if digits else len(found) + 1,
                left=info.rcMonitor.left,
                top=info.rcMonitor.top,
                right=info.rcMonitor.right,
                bottom=info.rcMonitor.bottom,
                work=(info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom),
                primary=bool(info.dwFlags & 1),
            )
        )
        return 1

    with physical_pixels():
        ctypes.windll.user32.EnumDisplayMonitors(None, None, _MONITOR_ENUM_PROC(collect), 0)
    return sorted(found, key=lambda monitor: monitor.number)


def describe_monitors(items: list[Monitor] | None = None) -> str:
    """Human description such as 'tela 3: 1440x2560 vertical, à esquerda da principal'."""
    items = items if items is not None else monitors()
    primary = next((m for m in items if m.primary), items[0] if items else None)
    parts = []
    for m in items:
        if m.primary:
            where = "principal"
        elif primary is not None:
            dx = (m.left + m.right) / 2 - (primary.left + primary.right) / 2
            dy = (m.top + m.bottom) / 2 - (primary.top + primary.bottom) / 2
            if abs(dx) >= abs(dy):
                where = "à esquerda da principal" if dx < 0 else "à direita da principal"
            else:
                where = "acima da principal" if dy < 0 else "abaixo da principal"
        else:
            where = ""
        parts.append(f"tela {m.number}: {m.width}x{m.height} {m.orientation}, {where}")
    return "; ".join(parts)


def monitor_for_rect(rect: tuple[int, int, int, int], items: list[Monitor]) -> Monitor | None:
    """Monitor holding the rectangle's center, else the one it overlaps the most."""
    left, top, right, bottom = rect
    cx, cy = (left + right) // 2, (top + bottom) // 2
    for m in items:
        if m.left <= cx < m.right and m.top <= cy < m.bottom:
            return m

    def overlap(m: Monitor) -> int:
        return max(0, min(right, m.right) - max(left, m.left)) * max(0, min(bottom, m.bottom) - max(top, m.top))

    best = max(items, key=overlap, default=None)
    return best if best is not None and overlap(best) > 0 else None


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name().lower()
    except psutil.Error:
        return ""


def _is_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return cloaked.value != 0


def windows() -> list[Window]:
    """Visible top-level app windows in Z order (most recently used first)."""
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    found: list[Window] = []

    def collect(hwnd: Any, _param: Any) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # 4 = GW_OWNER
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value in SHELL_CLASSES or _is_cloaked(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(Window(hwnd=int(hwnd), title=title.value, process=_process_name(pid.value), pid=pid.value))
        return True

    user32.EnumWindows(_WINDOW_ENUM_PROC(collect), 0)
    return found


def window_title(hwnd: int) -> str:
    if not IS_WINDOWS:
        return ""
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.replace("​", "").strip()


def foreground_title() -> str:
    if not IS_WINDOWS:
        return ""
    return window_title(ctypes.windll.user32.GetForegroundWindow())


def bring_to_front(hwnd: int) -> bool:
    """Focus a window even when Windows' focus-stealing protection is active."""
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    for attempt in range(3):
        if attempt == 1:
            # Um "Alt" sintético libera o SetForegroundWindow para este processo.
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        elif attempt == 2:
            current = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            target = user32.GetWindowThreadProcessId(hwnd, None)
            user32.AttachThreadInput(current, target, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(current, target, False)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        if user32.GetForegroundWindow() == hwnd:
            return True
    return False


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = _RECT()
    with physical_pixels():
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def window_monitor(hwnd: int) -> Monitor | None:
    """Monitor the window is on right now (None when minimized or gone)."""
    if not ctypes.windll.user32.IsWindow(hwnd):
        return None
    return monitor_for_rect(window_rect(hwnd), monitors())


def get_placement(hwnd: int) -> Placement | None:
    placement = _WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(placement)
    with physical_pixels():
        if not ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            return None
    normal = placement.rcNormalPosition
    return Placement(
        flags=placement.flags,
        show_cmd=placement.showCmd,
        min_pos=(placement.ptMinPosition.x, placement.ptMinPosition.y),
        max_pos=(placement.ptMaxPosition.x, placement.ptMaxPosition.y),
        normal=(normal.left, normal.top, normal.right, normal.bottom),
    )


def restore_placement(hwnd: int, saved: Placement) -> None:
    """Put a window back where `saved` says (monitor, size, maximized), visible and focused."""
    placement = _WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(placement)
    placement.flags = 0
    placement.showCmd = SW_MAXIMIZE if saved.maximized else SW_SHOWNORMAL
    placement.ptMinPosition = wintypes.POINT(*saved.min_pos)
    placement.ptMaxPosition = wintypes.POINT(*saved.max_pos)
    placement.rcNormalPosition = _RECT(*saved.normal)
    user32 = ctypes.windll.user32
    with physical_pixels():
        # Sai do maximizado no monitor atual antes, senão o Windows pode não trocar de tela.
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPlacement(hwnd, ctypes.byref(placement))
    bring_to_front(hwnd)


def move_to_monitor(hwnd: int, monitor: Monitor, maximize: bool | None = None) -> None:
    """Move a window to a monitor, keeping its size when it fits, and keep/maximize state."""
    user32 = ctypes.windll.user32
    was_maximized = bool(user32.IsZoomed(hwnd))
    with physical_pixels():
        user32.ShowWindow(hwnd, SW_RESTORE)
        left, top, right, bottom = window_rect(hwnd)
        work_left, work_top, work_right, work_bottom = monitor.work
        work_w, work_h = work_right - work_left, work_bottom - work_top
        width = min(right - left, int(work_w * 0.92))
        height = min(bottom - top, int(work_h * 0.92))
        x = work_left + (work_w - width) // 2
        y = work_top + (work_h - height) // 2
        user32.SetWindowPos(hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
        if maximize or (maximize is None and was_maximized):
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
    bring_to_front(hwnd)


def show_window(hwnd: int, command: int) -> None:
    ctypes.windll.user32.ShowWindow(hwnd, command)


def close_window(hwnd: int) -> None:
    """Polite close request (same as clicking the X)."""
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def grab_region(rect: tuple[int, int, int, int]) -> Any:
    """Screenshot of a rectangle in virtual-screen coordinates (e.g. a window)."""
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=rect, all_screens=True)


def grab_monitor(monitor: Monitor | None) -> Any:
    """Screenshot of one monitor (or every monitor) as a PIL image."""
    from PIL import ImageGrab

    if monitor is None:
        return ImageGrab.grab(all_screens=True)
    return ImageGrab.grab(bbox=(monitor.left, monitor.top, monitor.right, monitor.bottom), all_screens=True)


WM_APPCOMMAND = 0x0319
APPCOMMAND_MEDIA_PLAY_PAUSE = 14


def process_windows(process: str) -> list[Window]:
    """Top-level windows of one executable, hidden ones included (apps minimized to the tray)."""
    if not IS_WINDOWS:
        return []
    wanted = process.lower()
    pids = {proc.pid for proc in psutil.process_iter(["name"]) if (proc.info.get("name") or "").lower() == wanted}
    if not pids:
        return []
    user32 = ctypes.windll.user32
    found: list[Window] = []

    def collect(hwnd: Any, _param: Any) -> bool:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        if pid.value not in pids or length == 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        found.append(Window(hwnd=int(hwnd), title=title.value, process=wanted, pid=pid.value))
        return True

    user32.EnumWindows(_WINDOW_ENUM_PROC(collect), 0)
    return found


def send_app_command(hwnd: int, command: int) -> None:
    """Send a media command (WM_APPCOMMAND) to one window only, without focusing it."""
    ctypes.windll.user32.PostMessageW(hwnd, WM_APPCOMMAND, hwnd, command << 16)
