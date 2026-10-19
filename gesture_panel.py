"""Painel de gestos no canto da tela: a janela Win32, a lista de janelas e as miniaturas.

O desenho e a geometria ficam em gesture_map.py (puro, testável no Linux). Aqui ficam as
partes do Windows, todas fora da thread dos gestos:

- uma thread da janela, que redesenha no máximo PANEL_FPS vezes por segundo e só quando algo
  mudou (o motor dos gestos só entrega o quadro mais novo, nunca espera o desenho);
- uma thread que lê monitores e janelas a cada ~1 s e tira miniaturas com PrintWindow, uma
  por vez, cada janela no máximo a cada THUMB_INTERVAL_S, com prioridade baixa.

A janela reaproveita a base do aviso dos gestos (LayeredWindow): em camadas, sempre no topo,
não rouba o foco, não captura cliques (você mexe com a mão, não com o mouse) e fica fora dos
prints do look_at_screen. Miniaturas e quadros da câmera ficam só na memória: nada é gravado
nem enviado.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import gesture_actions
import win_desktop
from gesture_map import (
    DesktopSnapshot,
    MapWindow,
    PanelConfig,
    PanelFrame,
    choose_monitor,
    panel_origin,
    render_panel,
)

logger = logging.getLogger("jarvis-gestures")

IS_WINDOWS = sys.platform == "win32"

PANEL_FPS = 15.0
SNAPSHOT_INTERVAL_S = 1.0
THUMB_INTERVAL_S = 1.5
THUMB_TICK_S = 0.2  # uma miniatura por vez: no máximo ~5 por segundo no total
THUMB_MAX_SIDE = 320
MAX_WINDOWS = 24
MIN_WINDOW_SIDE = 48
PLACEMENT_CACHE_S = 3.0
PANEL_CLASS = "JarvisGesturePanel"


# ───────────────────────── janelas e miniaturas ─────────────────────────


def read_desktop(own_pids: set[int] | None = None, limit: int = MAX_WINDOWS) -> DesktopSnapshot:
    """Monitors and visible app windows (topmost first), skipping minimized ones and our own."""
    own = own_pids or {os.getpid()}
    screens = tuple(win_desktop.monitors())
    items: list[MapWindow] = []
    for window in win_desktop.windows():
        if window.pid in own or gesture_actions._is_minimized(window.hwnd):
            continue
        rect = win_desktop.window_rect(window.hwnd)
        if rect[2] - rect[0] < MIN_WINDOW_SIDE or rect[3] - rect[1] < MIN_WINDOW_SIDE:
            continue
        if win_desktop.monitor_for_rect(rect, list(screens)) is None:
            continue
        items.append(
            MapWindow(
                hwnd=window.hwnd,
                title=window.title.replace("​", "").strip(),
                process=window.process,
                pid=window.pid,
                rect=rect,
                maximized=gesture_actions._is_maximized(window.hwnd),
            )
        )
        if len(items) >= limit:
            break
    return DesktopSnapshot(monitors=screens, windows=tuple(items), taken=time.monotonic())


def due_thumbnails(
    windows: Sequence[MapWindow], stamps: dict[int, float], now: float, interval: float, limit: int
) -> list[int]:
    """Windows whose thumbnail should be taken now: never taken first, then the oldest ones."""
    stale = [item.hwnd for item in windows if now - stamps.get(item.hwnd, -1e9) >= interval]
    stale.sort(key=lambda hwnd: stamps.get(hwnd, -1e9))
    return stale[:limit]


class DesktopWatcher:
    """Keeps a fresh DesktopSnapshot and thumbnails, rate-limited (one call to tick() at a time)."""

    def __init__(
        self,
        read: Callable[[], DesktopSnapshot] = read_desktop,
        capture: Callable[[MapWindow], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        snapshot_interval: float = SNAPSHOT_INTERVAL_S,
        thumb_interval: float = THUMB_INTERVAL_S,
        thumbs_per_tick: int = 1,
    ) -> None:
        self.read = read
        self.capture = capture
        self.clock = clock
        self.snapshot_interval = snapshot_interval
        self.thumb_interval = thumb_interval
        self.thumbs_per_tick = thumbs_per_tick
        self.snapshot = DesktopSnapshot()
        self.version = 0  # muda a cada snapshot ou miniatura nova (o painel redesenha)
        self._read_at = -1e9
        self._thumbs: dict[int, Any] = {}
        self._stamps: dict[int, float] = {}

    @property
    def thumbs(self) -> dict[int, Any]:
        return dict(self._thumbs)

    def tick(self) -> None:
        now = self.clock()
        if now - self._read_at >= self.snapshot_interval:
            self._read_at = now
            try:
                self.snapshot = self.read()
            except Exception:
                logger.debug("Falha ao ler as janelas para o painel de gestos.", exc_info=True)
            alive = {item.hwnd for item in self.snapshot.windows}
            for hwnd in [hwnd for hwnd in self._thumbs if hwnd not in alive]:
                self._thumbs.pop(hwnd, None)
                self._stamps.pop(hwnd, None)
            self.version += 1
        if self.capture is None:
            return
        by_hwnd = {item.hwnd: item for item in self.snapshot.windows}
        for hwnd in due_thumbnails(self.snapshot.windows, self._stamps, now, self.thumb_interval, self.thumbs_per_tick):
            self._stamps[hwnd] = now
            try:
                thumb = self.capture(by_hwnd[hwnd])
            except Exception:
                logger.debug("Falha na miniatura da janela %s.", hwnd, exc_info=True)
                thumb = None
            if thumb is not None:
                self._thumbs[hwnd] = thumb
                self.version += 1


if IS_WINDOWS:
    from ctypes import wintypes

    from gesture_overlay import _BITMAPINFO, _BITMAPINFOHEADER

PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
THREAD_PRIORITY_BELOW_NORMAL = -1
MAX_CAPTURE_PIXELS = 3840 * 2400


class Win32Thumbnailer:
    """Window thumbnails with PrintWindow (works for windows behind others; GPU apps may come black)."""

    def __init__(self, max_side: int = THUMB_MAX_SIDE) -> None:
        self.max_side = max_side
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        user32.PrintWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.GetDIBits.argtypes = [
            wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
            ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
        ]  # fmt: skip
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.user32, self.gdi32 = user32, gdi32

    def __call__(self, item: MapWindow) -> Any:
        from PIL import Image

        width, height = item.rect[2] - item.rect[0], item.rect[3] - item.rect[1]
        if width <= 0 or height <= 0 or width * height > MAX_CAPTURE_PIXELS:
            return None
        user32, gdi32 = self.user32, self.gdi32
        screen_dc = user32.GetDC(None)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        try:
            if not bitmap:
                return None
            previous = gdi32.SelectObject(memory_dc, bitmap)
            ok = user32.PrintWindow(item.hwnd, memory_dc, PW_RENDERFULLCONTENT)
            gdi32.SelectObject(memory_dc, previous)
            if not ok:
                return None
            info = _BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            buffer = ctypes.create_string_buffer(width * height * 4)
            if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS):
                return None
            image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
        finally:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
        factor = max(1, max(width, height) // self.max_side)
        thumb = image.reduce(factor) if factor > 1 else image.copy()
        if thumb.getextrema() and max(high for _low, high in thumb.getextrema()) < 8:
            return None  # janela que o PrintWindow não consegue desenhar: fica o retângulo colorido
        return thumb


# ───────────────────────── painel ─────────────────────────


class GesturePanel:
    """Thread-safe front of the corner panel: show(frame) from the gesture thread, never blocking."""

    def __init__(
        self,
        config: PanelConfig | None = None,
        watcher: DesktopWatcher | None = None,
        threads: bool = IS_WINDOWS,
    ) -> None:
        self.config = config or PanelConfig.from_env()
        self.watcher = watcher
        self.threads = threads
        self._visible = threading.Event()
        self._closing = threading.Event()
        self._changed = threading.Condition()
        self._frame: PanelFrame | None = None
        self._window_thread: threading.Thread | None = None
        self._watch_thread: threading.Thread | None = None

    @property
    def visible(self) -> bool:
        return self._visible.is_set()

    def set_visible(self, on: bool) -> None:
        if on:
            self._visible.set()
        else:
            self._visible.clear()
        with self._changed:
            self._changed.notify_all()

    def desktop(self) -> DesktopSnapshot:
        return self.watcher.snapshot if self.watcher is not None else DesktopSnapshot()

    def show(self, frame: PanelFrame) -> None:
        """Hand over the newest frame; the panel thread draws it when it gets to it."""
        self._frame = frame
        with self._changed:
            self._changed.notify_all()

    def start(self) -> None:
        if not self.threads or (self._window_thread and self._window_thread.is_alive()):
            return
        self._closing.clear()
        if self.watcher is None:
            capture = None
            if IS_WINDOWS:
                try:
                    capture = Win32Thumbnailer()
                except (OSError, AttributeError):
                    logger.debug("Miniaturas indisponíveis.", exc_info=True)
            self.watcher = DesktopWatcher(capture=capture)
        self._window_thread = threading.Thread(target=self._run, name="gesture-panel", daemon=True)
        self._watch_thread = threading.Thread(target=self._watch, name="gesture-panel-windows", daemon=True)
        self._window_thread.start()
        self._watch_thread.start()

    def close(self) -> None:
        self._closing.set()
        with self._changed:
            self._changed.notify_all()
        for thread in (self._window_thread, self._watch_thread):
            if thread:
                thread.join(timeout=2)
        self._window_thread = self._watch_thread = None

    # ── threads ──

    def _watch(self) -> None:
        try:
            if IS_WINDOWS:
                kernel32 = ctypes.windll.kernel32
                kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)
                ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            while not self._closing.is_set():
                if self.visible and self.watcher is not None:
                    self.watcher.tick()
                    self._closing.wait(THUMB_TICK_S)
                else:
                    self._visible.wait(0.5)
        except Exception:
            logger.exception("A leitura das janelas do painel de gestos falhou.")

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:
            logger.exception("O painel de gestos falhou; os gestos continuam sem ele.")

    def _loop(self) -> None:
        from gesture_overlay import LayeredWindow

        window = LayeredWindow(PANEL_CLASS, "Jarvis · painel de gestos")
        placement: tuple[tuple[int, int, int, int], float, float] | None = None
        painted: tuple[Any, ...] | None = None
        last_paint = 0.0
        try:
            while not self._closing.is_set():
                window.pump()
                with self._changed:
                    self._changed.wait(timeout=0.05)
                if not self.visible:
                    window.hide()
                    painted = None
                    continue
                now = time.monotonic()
                wait = 1.0 / PANEL_FPS - (now - last_paint)
                if wait > 0:
                    time.sleep(wait)
                    now = time.monotonic()
                watcher = self.watcher
                snapshot = watcher.snapshot if watcher else DesktopSnapshot()
                frame = self._frame or PanelFrame(view=None)
                key = (id(frame), watcher.version if watcher else 0)
                if key == painted:
                    continue
                if placement is None or now - placement[2] > PLACEMENT_CACHE_S:
                    monitor = choose_monitor(self.config.monitor, snapshot.monitors or win_desktop.monitors())
                    if monitor is None:
                        continue
                    placement = (tuple(monitor.work), window.scale(tuple(monitor.work)), now)
                area, scale, _ = placement
                image = render_panel(frame, snapshot, watcher.thumbs if watcher else {}, scale, self.config.size)
                x, y = panel_origin(area, image.size, self.config.corner, round(self.config.margin * scale))
                window.paint(image, x, y, round(self.config.opacity * 255))
                painted, last_paint = key, now
        finally:
            window.destroy()
