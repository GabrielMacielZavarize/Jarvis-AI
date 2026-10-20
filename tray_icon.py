"""O ícone da bandeja em Win32 puro (ctypes), no estilo do gesture_overlay.py.

Uma janela oculta recebe os cliques do ícone (Shell_NotifyIconW) numa thread própria, com o seu
laço de mensagens. O estado chega de outra thread (TrayController.watch) por PostMessageW, e os
comandos do menu rodam fora da thread da janela, para o menu nunca travar.

O desenho do ícone usa o Pillow (já vem com as dependências); sem ele, fica o ícone padrão do
Windows. Tudo o que fala com o Windows passa por ``Win32Api``, trocado por um falso nos testes.
"""

from __future__ import annotations

import functools
import logging
import queue
import threading
from pathlib import Path
from typing import Any, Callable

from tray import ROOT, MenuEntry, TrayController, TrayState

logger = logging.getLogger("jarvis-tray")

ICON_DIR = ROOT / ".cache" / "tray"
ICON_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64)]
COLORS = {
    "off": (120, 132, 145),
    "warn": (255, 190, 40),
    "ready": (0, 210, 255),
    "listening": (0, 210, 255),
    "link": (90, 235, 130),
}

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_STATE = WM_APP + 2
WM_BALLOON = WM_APP + 3


# ───────────────────────── desenho ─────────────────────────


def render_icon(level: str, size: int = 256) -> Any:
    """The reactor ring in the color of the state, as an RGBA PIL image."""
    from PIL import Image, ImageDraw

    color = COLORS.get(level, COLORS["off"])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    edge = size // 32
    draw.ellipse((edge, edge, size - edge, size - edge), fill=(6, 14, 24, 235))
    ring = size // 8
    inset = edge + size // 12
    draw.ellipse((inset, inset, size - inset, size - inset), outline=(*color, 255), width=ring)
    if level in ("listening", "link"):
        core = size * (5 if level == "link" else 3) // 16
        center = size // 2
        draw.ellipse((center - core, center - core, center + core, center + core), fill=(*color, 255))
    return image


@functools.lru_cache(maxsize=8)
def icon_file(level: str, folder: Path = ICON_DIR) -> Path | None:
    """The .ico of a state, drawn once into .cache/tray. None without Pillow."""
    try:
        image = render_icon(level)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"jarvis-{level}.ico"
        image.save(path, format="ICO", sizes=ICON_SIZES)
        return path
    except Exception as exc:
        logger.warning("Ícone da bandeja sem desenho próprio (%s); uso o padrão do Windows.", exc)
        return None


# ───────────────────────── Win32 ─────────────────────────


class Win32Api:
    """Thin ctypes layer over user32 and shell32 (only built on Windows)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        lresult = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON),
            ]

        self.WNDCLASSW = WNDCLASSW
        self.NOTIFYICONDATAW = NOTIFYICONDATAW
        self.MSG = wintypes.MSG
        self.POINT = wintypes.POINT

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = lresult
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]  # fmt: skip
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = lresult
        user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterWindowMessageW.restype = wintypes.UINT
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID
        ]
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
        user32.LoadIconW.restype = wintypes.HICON
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.user32 = user32
        self.shell32 = shell32
        self.instance = kernel32.GetModuleHandleW(None)

    def create_window(self, handler: Callable[[int, int, int, int], int | None]) -> int:
        def proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            try:
                result = handler(hwnd, msg, wparam, lparam)
            except Exception:
                logger.exception("Falha no ícone da bandeja.")
                result = None
            return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam) if result is None else result

        # A referência precisa viver enquanto a janela existir.
        self._proc = self.WNDPROC(proc)
        wndclass = self.WNDCLASSW()
        wndclass.lpfnWndProc = self._proc
        wndclass.hInstance = self.instance
        wndclass.lpszClassName = "JarvisTrayWindow"
        self.user32.RegisterClassW(self._ctypes.byref(wndclass))
        return self.user32.CreateWindowExW(0, "JarvisTrayWindow", "Jarvis", 0, 0, 0, 0, 0, None, None, self.instance, None)

    def register_message(self, name: str) -> int:
        return self.user32.RegisterWindowMessageW(name)

    def _notify(self, action: int, hwnd: int, flags: int, **fields: Any) -> bool:
        data = self.NOTIFYICONDATAW()
        data.cbSize = self._ctypes.sizeof(self.NOTIFYICONDATAW)
        data.hWnd = hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAY
        for name, value in fields.items():
            setattr(data, name, value)
        return bool(self.shell32.Shell_NotifyIconW(action, self._ctypes.byref(data)))

    def add_icon(self, hwnd: int, icon: int, tip: str) -> bool:
        # NIM_ADD com NIF_MESSAGE | NIF_ICON | NIF_TIP
        return self._notify(0, hwnd, 0x1 | 0x2 | 0x4, hIcon=icon, szTip=tip)

    def modify_icon(self, hwnd: int, icon: int, tip: str) -> bool:
        return self._notify(1, hwnd, 0x1 | 0x2 | 0x4, hIcon=icon, szTip=tip)

    def balloon(self, hwnd: int, title: str, text: str) -> bool:
        # NIF_INFO com NIIF_INFO: a notificação do Windows, sem trocar o ícone.
        return self._notify(1, hwnd, 0x10, szInfo=text[:255], szInfoTitle=title[:63], dwInfoFlags=0x1)

    def delete_icon(self, hwnd: int) -> None:
        self._notify(2, hwnd, 0)

    def load_icon(self, path: Path | None) -> int:
        if path is not None:
            # IMAGE_ICON, LR_LOADFROMFILE; tamanho dos ícones pequenos (SM_CXSMICON/SM_CYSMICON)
            size = self.user32.GetSystemMetrics(49), self.user32.GetSystemMetrics(50)
            handle = self.user32.LoadImageW(None, str(path), 1, size[0], size[1], 0x10)
            if handle:
                return handle
        return self.user32.LoadIconW(None, 32512)  # IDI_APPLICATION

    def destroy_icon(self, icon: int) -> None:
        self.user32.DestroyIcon(icon)

    def show_menu(self, hwnd: int, entries: list[MenuEntry]) -> str | None:
        menu = self.user32.CreatePopupMenu()
        try:
            for index, entry in enumerate(entries, start=1):
                if entry.separator:
                    self.user32.AppendMenuW(menu, 0x800, 0, None)  # MF_SEPARATOR
                    continue
                flags = (0 if entry.enabled else 0x1) | (0x8 if entry.checked else 0)  # MF_GRAYED, MF_CHECKED
                self.user32.AppendMenuW(menu, flags, index, entry.label)
                if entry.default:
                    self.user32.SetMenuDefaultItem(menu, index, 0)
            point = self.POINT()
            self.user32.GetCursorPos(self._ctypes.byref(point))
            # Sem isso o menu não fecha ao clicar fora dele.
            self.user32.SetForegroundWindow(hwnd)
            # TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON
            chosen = self.user32.TrackPopupMenu(menu, 0x100 | 0x80 | 0x2, point.x, point.y, 0, hwnd, None)
            self.user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            self.user32.DestroyMenu(menu)
        if 0 < chosen <= len(entries) and entries[chosen - 1].enabled:
            return entries[chosen - 1].command or None
        return None

    def post(self, hwnd: int, msg: int) -> None:
        self.user32.PostMessageW(hwnd, msg, 0, 0)

    def destroy_window(self, hwnd: int) -> None:
        self.user32.DestroyWindow(hwnd)

    def quit(self) -> None:
        self.user32.PostQuitMessage(0)

    def loop(self) -> None:
        msg = self.MSG()
        while self.user32.GetMessageW(self._ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(self._ctypes.byref(msg))
            self.user32.DispatchMessageW(self._ctypes.byref(msg))


# ───────────────────────── ícone ─────────────────────────


class Win32TrayIcon:
    def __init__(
        self,
        controller: TrayController,
        api: Any = None,
        *,
        icon_path: Callable[[str], Path | None] = icon_file,
        spawn: Callable[[Callable[[], None]], Any] | None = None,
    ) -> None:
        self.controller = controller
        self._api = api
        self._icon_path = icon_path
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True).start())
        self.hwnd: int | None = None
        self.state = TrayState()
        self._pending: TrayState | None = None
        self._icons: dict[str, int] = {}
        self._messages: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._taskbar_created: int | None = None

    def run(self) -> None:
        """Create the icon and pump its messages until ``stop()`` (blocks: call it on its own thread)."""
        api = self._api = self._api or Win32Api()
        self.hwnd = api.create_window(self.handle)
        # O Explorer avisa por esta mensagem quando reinicia: o ícone precisa ser recriado.
        self._taskbar_created = api.register_message("TaskbarCreated")
        api.add_icon(self.hwnd, self._icon(self.state.level), self.state.tooltip())
        self._spawn(lambda: self.controller.watch(self.update, self._stop))
        api.loop()

    def stop(self) -> None:
        self._stop.set()
        if self.hwnd is not None and self._api is not None:
            self._api.post(self.hwnd, WM_CLOSE)

    def update(self, state: TrayState) -> None:
        """New state from the watcher thread; applied on the window thread."""
        self._pending = state
        if self.hwnd is not None:
            self._api.post(self.hwnd, WM_STATE)

    def notify(self, text: str) -> None:
        self._messages.put(text)
        if self.hwnd is not None:
            self._api.post(self.hwnd, WM_BALLOON)

    def handle(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int | None:
        api = self._api
        if msg == WM_TRAY:
            event = lparam & 0xFFFF
            if event == WM_LBUTTONDBLCLK:
                self._run("open_hud")
            elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                command = api.show_menu(hwnd, self.controller.menu(self.state))
                if command:
                    self._run(command)
            return 0
        if msg == WM_STATE:
            if self._pending is not None:
                self.state, self._pending = self._pending, None
                api.modify_icon(hwnd, self._icon(self.state.level), self.state.tooltip())
            return 0
        if msg == WM_BALLOON:
            while not self._messages.empty():
                api.balloon(hwnd, "Jarvis", self._messages.get_nowait())
            return 0
        if msg == self._taskbar_created and msg:
            api.add_icon(hwnd, self._icon(self.state.level), self.state.tooltip())
            return 0
        if msg == WM_CLOSE:
            api.delete_icon(hwnd)
            for icon in self._icons.values():
                api.destroy_icon(icon)
            self._icons.clear()
            api.destroy_window(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.hwnd = None
            api.quit()
            return 0
        return None

    def _icon(self, level: str) -> int:
        if level not in self._icons:
            self._icons[level] = self._api.load_icon(self._icon_path(level))
        return self._icons[level]

    def _run(self, command: str) -> None:
        def work() -> None:
            try:
                message = self.controller.run(command)
            except Exception as exc:
                logger.exception("Falha no comando %s da bandeja.", command)
                message = f"Não deu certo: {exc}"
            if message:
                print(f"[BANDEJA] {message}")
                self.notify(message)
            if command not in ("restart", "quit"):
                self.update(self.controller.poll())

        self._spawn(work)
