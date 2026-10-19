"""Primitivas do desktop do Windows: monitores, janelas e captura de tela.

Usa a API Win32 via ctypes, com coordenadas físicas (DPI por monitor), para
funcionar com monitores de escalas e orientações diferentes.

As telas são numeradas como o botão "Identificar" das Configurações do Windows, não
como \\\\.\\DISPLAYn. O Windows não documenta essa numeração: ela é estimada pela ordem
dos caminhos do QueryDisplayConfig (adaptador → tela interna, DisplayPort, HDMI... →
conector) e o usuário pode confirmá-la ou corrigi-la por voz; o que ele confirmar fica
em telas.json, junto com os apelidos ("tela de código"), fora do git.
"""

from __future__ import annotations

import ctypes
import difflib
import json
import re
import sys
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator

import psutil

IS_WINDOWS = sys.platform == "win32"
SCREENS_FILE = Path(__file__).resolve().parent / "telas.json"

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

# DISPLAYCONFIG_VIDEO_OUTPUT_TECHNOLOGY (wingdi.h)
OUTPUT_DVI = 4
OUTPUT_HDMI = 5
OUTPUT_LVDS = 6
OUTPUT_DISPLAYPORT_EXTERNAL = 10
OUTPUT_DISPLAYPORT_EMBEDDED = 11
OUTPUT_UDI_EMBEDDED = 13
OUTPUT_INTERNAL = 0x80000000
# Telas embutidas (painel do notebook).
INTERNAL_OUTPUTS = {OUTPUT_INTERNAL, OUTPUT_DISPLAYPORT_EMBEDDED, OUTPUT_LVDS, OUTPUT_UDI_EMBEDDED}
# Ordem em que as Configurações costumam numerar as conexões (a mesma heurística do módulo
# DisplayConfig, de MartinGC94): interna, DisplayPort embutida, DVI, DisplayPort, HDMI, outras.
OUTPUT_PRIORITY = {
    OUTPUT_INTERNAL: 50,
    OUTPUT_DISPLAYPORT_EMBEDDED: 100,
    OUTPUT_DVI: 150,
    OUTPUT_DISPLAYPORT_EXTERNAL: 200,
    OUTPUT_HDMI: 250,
}
OTHER_OUTPUT_PRIORITY = 300

# Nomes automáticos das telas, na ordem em que um vira o nome principal.
SIDE_NAMES = ("de cima", "de baixo", "da esquerda", "da direita")
# Palavras faladas → nome automático ("o monitor de cima", "a tela do notebook").
NAME_WORDS = {
    "notebook": "notebook",
    "note": "notebook",
    "notebuque": "notebook",
    "laptop": "notebook",
    "portatil": "notebook",
    "interna": "notebook",
    "interno": "notebook",
    "embutida": "notebook",
    "vertical": "vertical",
    "retrato": "vertical",
    "pe": "vertical",  # "em pé"
    "horizontal": "horizontal",
    "deitado": "horizontal",
    "deitada": "horizontal",
    "paisagem": "horizontal",
    "cima": "de cima",
    "acima": "de cima",
    "superior": "de cima",
    "baixo": "de baixo",
    "embaixo": "de baixo",
    "debaixo": "de baixo",
    "abaixo": "de baixo",
    "inferior": "de baixo",
    "esquerda": "da esquerda",
    "esquerdo": "da esquerda",
    "direita": "da direita",
    "direito": "da direita",
    "principal": "principal",
    "primario": "principal",
    "primaria": "principal",
}
NUMBER_WORDS = {
    "um": 1, "uma": 1, "primeira": 1, "primeiro": 1,
    "dois": 2, "duas": 2, "segunda": 2, "segundo": 2,
    "tres": 3, "terceira": 3, "terceiro": 3,
    "quatro": 4, "quarta": 4, "quarto": 4,
    "cinco": 5, "quinta": 5, "quinto": 5,
    "seis": 6, "sexta": 6, "sexto": 6,
}  # fmt: skip
# Palavras que só dizem "uma tela" ("pro monitor", "na tela") e não escolhem nenhuma.
SCREEN_FILLER = {
    "tela", "telas", "monitor", "monitores", "display", "o", "a", "os", "as", "do", "da", "de", "no", "na",
    "em", "pro", "pra", "para", "pelo", "pela", "numero", "que", "fica", "esta", "ta",
}  # fmt: skip


@dataclass(frozen=True)
class Monitor:
    number: int  # o número que o "Identificar" das Configurações do Windows mostra
    left: int
    top: int
    right: int
    bottom: int
    work: tuple[int, int, int, int]
    primary: bool
    device: str = ""  # \\.\DISPLAYn: numeração interna do Windows, diferente da das Configurações
    name: str = ""  # nome falado automático: "notebook", "vertical", "de cima"...
    aliases: tuple[str, ...] = ()  # outros nomes automáticos que também valem ("de baixo", "horizontal")
    nicknames: tuple[str, ...] = ()  # apelidos dados pelo usuário ("tela de código")
    internal: bool = False  # tela embutida do notebook
    model: str = ""  # nome do monitor no EDID ("GF270A"); vazio na maioria dos notebooks
    hardware_id: str = ""  # identificação estável do monitor ("QHX2700#UID20550"), chave do telas.json
    confirmed: bool = False  # número confirmado pelo usuário, não só estimado

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def orientation(self) -> str:
        return "vertical" if self.height > self.width else "horizontal"

    @property
    def label(self) -> str:
        """How to say it: 'notebook (tela 1)', 'monitor de cima (tela 3)' or just 'tela 2'."""
        if not self.name:
            return f"tela {self.number}"
        noun = self.name if self.name == "notebook" else f"monitor {self.name}"
        return f"{noun} (tela {self.number})"


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

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _PATH_SOURCE_INFO(ctypes.Structure):
        _fields_ = [("adapterId", _LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32), ("statusFlags", ctypes.c_uint32)]

    class _PATH_TARGET_INFO(ctypes.Structure):
        _fields_ = [
            ("adapterId", _LUID),
            ("id", ctypes.c_uint32),
            ("modeInfoIdx", ctypes.c_uint32),
            ("outputTechnology", ctypes.c_uint32),
            ("rotation", ctypes.c_uint32),
            ("scaling", ctypes.c_uint32),
            ("refreshRate", ctypes.c_uint32 * 2),
            ("scanLineOrdering", ctypes.c_uint32),
            ("targetAvailable", wintypes.BOOL),
            ("statusFlags", ctypes.c_uint32),
        ]

    class _PATH_INFO(ctypes.Structure):
        _fields_ = [("sourceInfo", _PATH_SOURCE_INFO), ("targetInfo", _PATH_TARGET_INFO), ("flags", ctypes.c_uint32)]

    class _MODE_INFO(ctypes.Structure):
        _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", _LUID), ("data", ctypes.c_byte * 48)]

    class _DEVICE_INFO_HEADER(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", _LUID), ("id", ctypes.c_uint32)]

    class _SOURCE_DEVICE_NAME(ctypes.Structure):
        _fields_ = [("header", _DEVICE_INFO_HEADER), ("viewGdiDeviceName", ctypes.c_wchar * 32)]

    class _TARGET_DEVICE_NAME(ctypes.Structure):
        _fields_ = [
            ("header", _DEVICE_INFO_HEADER),
            ("flags", ctypes.c_uint32),
            ("outputTechnology", ctypes.c_uint32),
            ("edidManufactureId", ctypes.c_uint16),
            ("edidProductCodeId", ctypes.c_uint16),
            ("connectorInstance", ctypes.c_uint32),
            ("monitorFriendlyDeviceName", ctypes.c_wchar * 64),
            ("monitorDevicePath", ctypes.c_wchar * 128),
        ]

    class _ADAPTER_DEVICE_NAME(ctypes.Structure):
        _fields_ = [("header", _DEVICE_INFO_HEADER), ("adapterDevicePath", ctypes.c_wchar * 128)]

QDC_ONLY_ACTIVE_PATHS = 0x2
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
DISPLAYCONFIG_DEVICE_INFO_GET_ADAPTER_NAME = 4


@dataclass(frozen=True)
class DisplayTarget:
    """One active display path (QueryDisplayConfig): what is needed to number it like the Settings app."""

    device: str  # \\.\DISPLAYn da origem (o mesmo nome do GetMonitorInfo)
    adapter: str
    target_id: int
    output: int  # DISPLAYCONFIG_VIDEO_OUTPUT_TECHNOLOGY
    connector: int  # connectorInstance: conta as conexões do mesmo tipo
    model: str = ""
    hardware_id: str = ""

    @property
    def internal(self) -> bool:
        return self.output in INTERNAL_OUTPUTS


def hardware_id_from_path(device_path: str, fallback: str = "") -> str:
    """'\\\\?\\DISPLAY#QHX2700#4&b182007&0&UID20550#{...}' → 'QHX2700#UID20550' (stable per monitor and port)."""
    parts = device_path.split("#")
    if len(parts) >= 3 and parts[1]:
        return f"{parts[1]}#{parts[2].split('&')[-1]}".upper()
    return fallback


def _device_info(packet: Any, kind: int, adapter: Any, target: int) -> bool:
    packet.header.type = kind
    packet.header.size = ctypes.sizeof(packet)
    packet.header.adapterId = adapter
    packet.header.id = target
    return ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(packet)) == 0


def display_targets() -> list[DisplayTarget]:
    """Active display paths in QueryDisplayConfig order ([] when the API is unavailable)."""
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    for _ in range(3):  # a topologia pode mudar entre as duas chamadas
        path_count, mode_count = ctypes.c_uint32(), ctypes.c_uint32()
        if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)):
            return []
        paths = (_PATH_INFO * path_count.value)()
        modes = (_MODE_INFO * mode_count.value)()
        result = user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), paths, ctypes.byref(mode_count), modes, None
        )
        if result == 0:
            break
        if result != 122:  # ERROR_INSUFFICIENT_BUFFER: tenta de novo
            return []
    else:
        return []

    adapters: dict[tuple[int, int], str] = {}
    found = []
    for path in paths[: path_count.value]:
        source, target = path.sourceInfo, path.targetInfo
        source_name = _SOURCE_DEVICE_NAME()
        if not _device_info(source_name, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME, source.adapterId, source.id):
            continue
        target_name = _TARGET_DEVICE_NAME()
        _device_info(target_name, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME, target.adapterId, target.id)
        luid = (target.adapterId.HighPart, target.adapterId.LowPart)
        if luid not in adapters:
            adapter_name = _ADAPTER_DEVICE_NAME()
            _device_info(adapter_name, DISPLAYCONFIG_DEVICE_INFO_GET_ADAPTER_NAME, target.adapterId, 0)
            adapters[luid] = adapter_name.adapterDevicePath or f"{luid}"
        found.append(
            DisplayTarget(
                device=source_name.viewGdiDeviceName,
                adapter=adapters[luid],
                target_id=target.id,
                output=target.outputTechnology,
                connector=target_name.connectorInstance,
                model=target_name.monitorFriendlyDeviceName.strip(),
                hardware_id=hardware_id_from_path(target_name.monitorDevicePath, f"{adapters[luid]}#{target.id}"),
            )
        )
    return found


def settings_order(targets: list[DisplayTarget]) -> list[DisplayTarget]:
    """Targets in the order the Settings app numbers them (1, 2, 3...), as far as it can be known.

    The Settings numbering is undocumented. This is the heuristic of the DisplayConfig module:
    adapter, then connection type (internal first, then DisplayPort, then HDMI), then connector.
    On Gabriel's setup it gives notebook = 1, vertical (DisplayPort) = 2, top (HDMI) = 3, like
    "Identificar"; when it misses, the user corrects it and the fix is kept in telas.json.
    """
    return sorted(targets, key=lambda t: (t.adapter, OUTPUT_PRIORITY.get(t.output, OTHER_OUTPUT_PRIORITY) + t.connector))


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", stripped)).strip().lower()


def _core_words(text: str) -> list[str]:
    return [word for word in _plain(text).split() if word not in SCREEN_FILLER]


def load_screen_config(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """telas.json: {hardware_id: {"numero": 2, "apelidos": ["tela de código"], "monitor": "GF270A"}}."""
    try:
        data = json.loads((path or SCREENS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def save_screen_config(config: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    (path or SCREENS_FILE).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _confirmed_number(entry: dict[str, Any]) -> int | None:
    number = entry.get("numero")
    return number if isinstance(number, int) and not isinstance(number, bool) and number > 0 else None


def _nicknames(entry: dict[str, Any]) -> tuple[str, ...]:
    names = entry.get("apelidos")
    if not isinstance(names, list):
        return ()
    return tuple(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _side_names(monitor: Monitor, items: list[Monitor]) -> list[str]:
    """'de cima' when the monitor sits above a neighbor and below none; same for the other sides."""
    above = below = left = right = False  # está acima/abaixo/à esquerda/à direita de algum vizinho
    cx, cy = (monitor.left + monitor.right) / 2, (monitor.top + monitor.bottom) / 2
    for other in items:
        if other is monitor:
            continue
        side_by_side = _overlap(monitor.top, monitor.bottom, other.top, other.bottom) >= 0.3 * min(
            monitor.height, other.height
        )
        stacked = _overlap(monitor.left, monitor.right, other.left, other.right) >= 0.3 * min(
            monitor.width, other.width
        )
        ox, oy = (other.left + other.right) / 2, (other.top + other.bottom) / 2
        if stacked and not side_by_side:
            above, below = above or cy < oy, below or cy > oy
        elif side_by_side and not stacked:
            left, right = left or cx < ox, right or cx > ox
    sides = {"de cima": above and not below, "de baixo": below and not above}
    sides.update({"da esquerda": left and not right, "da direita": right and not left})
    return [name for name in SIDE_NAMES if sides[name]]


def name_monitors(items: list[Monitor]) -> list[Monitor]:
    """Give each monitor its spoken names from hardware and geometry, keeping only unambiguous ones.

    notebook = the built-in panel; vertical = portrait; de cima / de baixo / da esquerda /
    da direita = where it sits; horizontal = the only landscape external monitor.
    """
    tags: dict[int, list[str]] = {}
    for m in items:
        found = ["notebook"] if m.internal else []
        if m.orientation == "vertical":
            found.append("vertical")
        elif not m.internal:
            found.append("horizontal")
        tags[id(m)] = found + _side_names(m, items)
    counts: dict[str, int] = {}
    for found in tags.values():
        for tag in found:
            counts[tag] = counts.get(tag, 0) + 1
    named = []
    for m in items:
        unique = [tag for tag in tags[id(m)] if counts[tag] == 1]
        order = ["notebook", "vertical", *SIDE_NAMES, "horizontal"]
        main = next((tag for tag in order if tag in unique), "")
        named.append(replace(m, name=main, aliases=tuple(tag for tag in unique if tag != main)))
    return named


def number_monitors(
    raw: list[Monitor], targets: list[DisplayTarget], config: dict[str, dict[str, Any]] | None = None
) -> list[Monitor]:
    """Renumber monitors like the Settings app, apply what the user confirmed, and name them.

    `raw` holds the GetMonitorInfo data with `device` set; numbers confirmed in telas.json
    win over the estimate, then the monitors are renumbered 1..N in that order (an unplugged
    monitor doesn't leave a hole, as in the Settings app).
    """
    config = config or {}
    ordered = settings_order(targets)
    by_device: dict[str, tuple[int, DisplayTarget]] = {}
    for index, target in enumerate(ordered):
        by_device.setdefault(target.device.upper(), (index, target))  # clone: vale a primeira

    ranked = []
    for m in raw:
        estimate, target = by_device.get(m.device.upper(), (len(ordered) + m.number, None))
        hardware_id = target.hardware_id if target else m.hardware_id
        entry = config.get(hardware_id, {}) if hardware_id else {}
        confirmed = _confirmed_number(entry)
        if target is not None:
            m = replace(m, internal=target.internal, model=target.model, hardware_id=hardware_id)
        m = replace(m, nicknames=_nicknames(entry), confirmed=confirmed is not None)
        ranked.append(((confirmed if confirmed is not None else estimate + 1, confirmed is None, estimate), m))
    ranked.sort(key=lambda item: item[0])
    numbered = [replace(m, number=position) for position, (_, m) in enumerate(ranked, start=1)]
    return name_monitors(numbered)


def _raw_monitors() -> list[Monitor]:
    """GetMonitorInfo for every monitor, numbered by \\\\.\\DISPLAYn (before renumbering)."""
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
                device=info.szDevice,
            )
        )
        return 1

    with physical_pixels():
        ctypes.windll.user32.EnumDisplayMonitors(None, None, _MONITOR_ENUM_PROC(collect), 0)
    return sorted(found, key=lambda monitor: monitor.number)


def monitors() -> list[Monitor]:
    """Monitors numbered like the Settings app's "Identificar" (tela 1, 2, 3), with spoken names."""
    if not IS_WINDOWS:
        return []
    raw = _raw_monitors()
    try:
        targets = display_targets()
    except (OSError, ValueError, AttributeError):
        targets = []
    return number_monitors(raw, targets, load_screen_config())


def find_monitor(reference: int | str, items: list[Monitor]) -> Monitor:
    """The monitor the user means: a number ("1", "tela 2", "terceira"), a name or a nickname.

    Names are the automatic ones ("notebook", "vertical", "de cima", "principal"...) and the
    user's nicknames ("tela de código"). Raises ValueError with a message safe to speak.
    """
    if isinstance(reference, bool) or not str(reference).strip():
        raise ValueError("Diga qual tela: o número ou o nome dela.")
    if isinstance(reference, int):
        number: int | None = reference
    else:
        text = _plain(reference)
        words = _core_words(reference)
        for m in items:  # apelidos primeiro: um apelido pode conter qualquer palavra
            for nickname in m.nicknames:
                if _plain(nickname) == text or (words and _core_words(nickname) == words):
                    return m
        number = None
        if len(words) == 1 and words[0].isdigit():
            number = int(words[0])
        elif len(words) == 1 and words[0] in NUMBER_WORDS:
            number = NUMBER_WORDS[words[0]]
        if number is None:
            wanted = {NAME_WORDS[word] for word in words if word in NAME_WORDS}
            if wanted:
                matches = [m for m in items if wanted <= {m.name, *m.aliases, *(["principal"] if m.primary else [])}]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    raise ValueError(f"Mais de uma tela combina com '{reference}': {screen_list(matches)}. Qual delas?")
                raise ValueError(f"Nenhuma tela é a única '{reference}' aqui. Telas: {screen_list(items)}.")
            nicknames = {_plain(nickname): m for m in items for nickname in m.nicknames}
            close = difflib.get_close_matches(text, list(nicknames), n=1, cutoff=0.75)
            if close:
                return nicknames[close[0]]
            raise ValueError(f"Não sei qual é a tela '{reference}'. Telas: {screen_list(items)}.")
    for m in items:
        if m.number == number:
            return m
    raise ValueError(f"Não existe tela {number}. Telas disponíveis: {screen_list(items)}.")


def screen_list(items: list[Monitor]) -> str:
    """'1 (notebook), 2 (vertical), 3 (de cima)' or '1, 2, 3' when they have no names."""
    return ", ".join(f"{m.number} ({m.name})" if m.name else str(m.number) for m in items)


def describe_monitors(items: list[Monitor] | None = None) -> str:
    """Human description such as 'tela 2: monitor vertical (GF270A), 1440x2560, à esquerda da principal'."""
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
        title = m.label.removesuffix(f" (tela {m.number})") if m.name else ""
        model = f" ({m.model})" if m.model else ""
        head = f"tela {m.number}: {title}{model}, " if title else f"tela {m.number}: "
        extras = [f"também '{alias}'" for alias in m.aliases] + [f"apelido '{nick}'" for nick in m.nicknames]
        tail = "".join(f", {extra}" for extra in extras)
        parts.append(f"{head}{m.width}x{m.height} {m.orientation}, {where}{tail}")
    return "; ".join(parts)


def workspace_offset(items: list[Monitor]) -> tuple[int, int]:
    """Screen = workspace + offset. WINDOWPLACEMENT uses workspace coordinates, whose (0, 0) is
    the top-left of the primary monitor's work area (it differs when the taskbar is on top/left)."""
    primary = next((m for m in items if m.primary), None)
    if primary is None:
        return 0, 0
    return primary.work[0] - primary.left, primary.work[1] - primary.top


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


def restore_placement(hwnd: int, saved: Placement, focus: bool = True) -> None:
    """Put a window back where `saved` says (monitor, size, maximized), visible (and focused)."""
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
    if focus:
        bring_to_front(hwnd)


def move_to_monitor(hwnd: int, monitor: Monitor, maximize: bool | None = None, focus: bool = True) -> None:
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
    if focus:
        bring_to_front(hwnd)


def place_window(hwnd: int, rect: tuple[int, int, int, int], maximize: bool = False, focus: bool = True) -> None:
    """Put a window at an exact rectangle (physical pixels), e.g. on another monitor.

    Crossing to a monitor with another DPI, apps that follow the DPI resize themselves right
    after the move; a second SetWindowPos puts the size back to what was asked.
    """
    user32 = ctypes.windll.user32
    left, top, right, bottom = rect
    with physical_pixels():
        user32.ShowWindow(hwnd, SW_RESTORE)
        for _ in range(2):
            user32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top, SWP_NOZORDER | SWP_NOACTIVATE)
            if window_rect(hwnd) == rect:
                break
        if maximize:
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
    if focus:
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
