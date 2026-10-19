"""Aviso flutuante dos gestos: pequeno, sempre no topo, transparente e sem capturar cliques.

É uma janela Win32 em camadas (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE) com
alpha por pixel, desenhada com o Pillow numa thread própria. Aparece no topo do monitor onde
o Gabriel está olhando e mostra o estado: armado, segurando, "→ monitor de cima", contagem
para fechar. Não rouba o foco nem aparece na barra de tarefas, e fica fora dos prints de tela
do próprio Jarvis (look_at_screen).
"""

from __future__ import annotations

import ctypes
import functools
import logging
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("jarvis-gestures")

IS_WINDOWS = sys.platform == "win32"

TONES = {
    "info": (0, 210, 255),
    "armed": (0, 230, 170),
    "warn": (255, 190, 40),
    "danger": (255, 72, 72),
    "ok": (90, 235, 130),
    "error": (255, 96, 96),
}
FONTS_DIR = Path("C:/Windows/Fonts")
TITLE_FONT = ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf")
DETAIL_FONT = ("segoeui.ttf", "arial.ttf")


@dataclass(frozen=True)
class OverlayView:
    title: str
    detail: str = ""
    progress: float | None = None
    tone: str = "info"


# ───────────────────────── desenho ─────────────────────────


@functools.lru_cache(maxsize=64)
def _font(names: tuple[str, ...], size: int) -> Any:
    from PIL import ImageFont

    for name in names:
        try:
            return ImageFont.truetype(str(FONTS_DIR / name), size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _fit(draw: Any, text: str, font: Any, width: float) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def render(view: OverlayView, scale: float = 1.0) -> Any:
    """The overlay as an RGBA PIL image (pure: testable without a screen)."""
    from PIL import Image, ImageDraw

    color = TONES.get(view.tone, TONES["info"])
    title_font = _font(TITLE_FONT, round(19 * scale))
    detail_font = _font(DETAIL_FONT, round(14 * scale))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    pad = round(18 * scale)
    dot = round(10 * scale)
    max_text = round(620 * scale)
    title = _fit(probe, view.title, title_font, max_text)
    detail = _fit(probe, view.detail, detail_font, max_text) if view.detail else ""
    text_width = max(probe.textlength(title, font=title_font), probe.textlength(detail, font=detail_font) if detail else 0)
    width = int(max(round(300 * scale), text_width + pad * 3 + dot))
    height = round((76 if detail else 52) * scale) + (round(8 * scale) if view.progress is not None else 0)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = round(16 * scale)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(6, 14, 24, 218))
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1), radius=radius, outline=(*color, 235), width=max(1, round(2 * scale))
    )
    text_x = pad + dot + round(12 * scale)
    title_y = round(12 * scale)
    dot_y = title_y + round(6 * scale)
    draw.ellipse((pad, dot_y, pad + dot, dot_y + dot), fill=(*color, 255))
    draw.text((text_x, title_y), title, font=title_font, fill=(232, 248, 255, 255))
    if detail:
        draw.text((text_x, title_y + round(30 * scale)), detail, font=detail_font, fill=(150, 205, 225, 255))
    if view.progress is not None:
        bar_h = max(2, round(5 * scale))
        top = height - round(12 * scale)
        left, right = pad, width - pad
        draw.rounded_rectangle((left, top, right, top + bar_h), radius=bar_h // 2, fill=(255, 255, 255, 40))
        filled = left + (right - left) * min(1.0, max(0.0, view.progress))
        if filled > left + 1:
            draw.rounded_rectangle((left, top, filled, top + bar_h), radius=bar_h // 2, fill=(*color, 255))
    return image


def premultiplied_bgra(image: Any) -> bytes:
    """RGBA image → premultiplied BGRA bytes, the format UpdateLayeredWindow expects."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint16)
    alpha = rgba[..., 3:4]
    rgb = rgba[..., :3] * alpha // 255
    bgra = np.concatenate([rgb[..., ::-1], alpha], axis=2).astype(np.uint8)
    return bgra.tobytes()


# ───────────────────────── janela Win32 ─────────────────────────


if IS_WINDOWS:
    from ctypes import wintypes

    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", _WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    class _BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_ubyte),
            ("BlendFlags", ctypes.c_ubyte),
            ("SourceConstantAlpha", ctypes.c_ubyte),
            ("AlphaFormat", ctypes.c_ubyte),
        ]

    def _dlls() -> tuple[Any, Any, Any, Any]:
        """Private DLL handles with full prototypes (64-bit handles), not shared with win_desktop."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        H, UINT, DWORD, INT = wintypes.HANDLE, wintypes.UINT, wintypes.DWORD, ctypes.c_int
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.CreateWindowExW.argtypes = [
            DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, DWORD, INT, INT, INT, INT,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]  # fmt: skip
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [wintypes.HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = _LRESULT
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, UINT, UINT, UINT]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.ShowWindow.argtypes = [wintypes.HWND, INT]
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, INT, INT, INT, INT, UINT]
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, DWORD]
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
            wintypes.HDC, ctypes.POINTER(wintypes.POINT), DWORD, ctypes.POINTER(_BLENDFUNCTION), DWORD,
        ]  # fmt: skip
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, DWORD]
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC, ctypes.POINTER(_BITMAPINFO), UINT, ctypes.POINTER(ctypes.c_void_p), H, DWORD
        ]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, INT, ctypes.POINTER(UINT), ctypes.POINTER(UINT)]
        return user32, gdi32, kernel32, shcore


WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
PM_REMOVE = 0x0001
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
WDA_EXCLUDEFROMCAPTURE = 0x00000011
MONITOR_DEFAULTTONEAREST = 2
CLASS_NAME = "JarvisGestureOverlay"
_CLOSE = object()


class LayeredWindow:
    """One layered window (click-through, always on top, never focused, out of screenshots).

    Create, paint and destroy it from a single thread: Win32 windows belong to their thread.
    """

    def __init__(self, class_name: str, title: str) -> None:
        self.user32, self.gdi32, kernel32, self.shcore = _dlls()
        self.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        self.class_name = class_name
        self.instance = kernel32.GetModuleHandleW(None)
        user32 = self.user32

        def window_proc(hwnd: Any, message: int, wparam: Any, lparam: Any) -> int:
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._proc = _WNDPROC(window_proc)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._proc
        wc.hInstance = self.instance
        wc.lpszClassName = class_name
        self._registered = bool(user32.RegisterClassExW(ctypes.byref(wc)))
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class_name,
            title,
            WS_POPUP,
            0, 0, 1, 1,
            None, None, self.instance, None,
        )  # fmt: skip
        if not self.hwnd:
            raise OSError(f"CreateWindowExW falhou ({ctypes.get_last_error()})")
        user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)
        self.visible = False
        self._msg = wintypes.MSG()

    def pump(self) -> None:
        while self.user32.PeekMessageW(ctypes.byref(self._msg), None, 0, 0, PM_REMOVE):
            self.user32.TranslateMessage(ctypes.byref(self._msg))
            self.user32.DispatchMessageW(ctypes.byref(self._msg))

    def scale(self, area: tuple[int, int, int, int]) -> float:
        """DPI scale (1.0 = 96 dpi) of the monitor holding the center of `area`."""
        left, top, right, bottom = area
        point = wintypes.POINT((left + right) // 2, (top + bottom) // 2)
        monitor = self.user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        dpi_x, dpi_y = wintypes.UINT(96), wintypes.UINT(96)
        if monitor and self.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            return max(1.0, dpi_x.value / 96)
        return 1.0

    def hide(self) -> None:
        if self.visible:
            self.user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def paint(self, image: Any, x: int, y: int, alpha: int = 255) -> None:
        """Show an RGBA image at (x, y) in physical pixels, with an extra constant opacity."""
        user32, gdi32 = self.user32, self.gdi32
        width, height = image.size
        data = premultiplied_bgra(image)
        screen_dc = user32.GetDC(None)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # de cima para baixo
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        try:
            if not bitmap or not bits.value:
                return
            ctypes.memmove(bits, data, len(data))
            previous = gdi32.SelectObject(memory_dc, bitmap)
            blend = _BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(alpha))), AC_SRC_ALPHA)
            user32.UpdateLayeredWindow(
                self.hwnd,
                screen_dc,
                ctypes.byref(wintypes.POINT(x, y)),
                ctypes.byref(wintypes.SIZE(width, height)),
                memory_dc,
                ctypes.byref(wintypes.POINT(0, 0)),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
            gdi32.SelectObject(memory_dc, previous)
        finally:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
        if not self.visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.visible = True
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def destroy(self) -> None:
        self.user32.DestroyWindow(self.hwnd)
        if self._registered:
            self.user32.UnregisterClassW(self.class_name, self.instance)


class Overlay:
    """Thread-safe front: show(view, area) / hide() from any thread; the window lives in its own thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._last: tuple[OverlayView | None, tuple[int, int, int, int] | None] | None = None

    def start(self) -> None:
        if not IS_WINDOWS or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(target=self._run, name="gesture-overlay", daemon=True)
        self._thread.start()

    def show(self, view: OverlayView | None, area: tuple[int, int, int, int] | None) -> None:
        """Display `view` at the top of `area` (a monitor's work area, physical pixels); None hides."""
        item = (view, area if view is not None else None)
        if item == self._last:
            return
        self._last = item
        self._queue.put(item)

    def hide(self) -> None:
        self.show(None, None)

    def close(self) -> None:
        self._queue.put(_CLOSE)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._last = None

    # ── thread da janela ──

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:
            logger.exception("O overlay dos gestos falhou; os gestos continuam sem ele.")

    def _loop(self) -> None:
        window = LayeredWindow(CLASS_NAME, "Jarvis · gestos")
        try:
            while True:
                window.pump()
                try:
                    item = self._queue.get(timeout=0.03)
                except queue.Empty:
                    continue
                while item is not _CLOSE:  # só o estado mais novo interessa
                    try:
                        item = self._queue.get_nowait()
                    except queue.Empty:
                        break
                if item is _CLOSE:
                    break
                view, area = item
                if view is None or area is None:
                    window.hide()
                    continue
                scale = window.scale(area)
                image = render(view, scale)
                left, top, right, _ = area
                window.paint(image, left + (right - left - image.size[0]) // 2, top + round(22 * scale))
        finally:
            window.destroy()
