"""Painel de gestos: geometria do mapa das telas e desenho do painel (lógica pura).

O painel fica num canto (padrão: inferior direito do notebook) e mostra a webcam com os pontos
da mão, o estado do gesto e um mapa dos monitores na disposição real do Windows (as mesmas
coordenadas físicas das Configurações: o vertical à esquerda tem x negativo), com as janelas
abertas dentro de cada monitor. Um cursor da mão anda sobre o mapa: fechar a mão em cima de uma
janela pega ela, levar até outro monitor destaca o destino e abrir a mão solta lá, na mesma
posição relativa.

Aqui não há Win32 nem câmera: tudo recebe monitores, retângulos e quadros prontos, então dá
para testar no Linux. A janela flutuante, a lista de janelas e as miniaturas ficam em
gesture_panel.py.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

import win_desktop
from gesture_overlay import DETAIL_FONT, TITLE_FONT, TONES, OverlayView, _fit, _font

Rect = tuple[int, int, int, int]

PANEL_SIZE = (360, 260)  # pixels lógicos (multiplicados pela escala do monitor)
CORNERS = ("inferior-direito", "inferior-esquerdo", "superior-direito", "superior-esquerdo")
CORNER_WORDS = {
    "bottom-right": "inferior-direito",
    "bottom-left": "inferior-esquerdo",
    "top-right": "superior-direito",
    "top-left": "superior-esquerdo",
}
MIN_DROP_SIZE = (200, 120)  # menor janela que o soltar cria, em pixels físicos
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)  # fmt: skip


# ───────────────────────── configuração ─────────────────────────


@dataclass(frozen=True)
class PanelConfig:
    corner: str = "inferior-direito"
    monitor: str = "notebook"  # número ou nome da tela ("notebook", "2", "de cima")
    opacity: float = 0.92
    size: tuple[int, int] = PANEL_SIZE
    margin: int = 16

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PanelConfig:
        """JARVIS_GESTURE_PANEL_CORNER / _MONITOR / _OPACITY / _SIZE; valores ruins caem no padrão."""
        env = os.environ if env is None else env
        default = cls()
        corner = env.get("JARVIS_GESTURE_PANEL_CORNER", "").strip().lower().replace(" ", "-").replace("_", "-")
        corner = CORNER_WORDS.get(corner, corner)
        monitor = env.get("JARVIS_GESTURE_PANEL_MONITOR", "").strip() or default.monitor
        try:
            opacity = float(env.get("JARVIS_GESTURE_PANEL_OPACITY", "").replace(",", ".") or default.opacity)
        except ValueError:
            opacity = default.opacity
        size = default.size
        raw_size = env.get("JARVIS_GESTURE_PANEL_SIZE", "").lower().replace(" ", "")
        if "x" in raw_size:
            try:
                width, height = (int(part) for part in raw_size.split("x", 1))
                size = (min(max(width, 280), 900), min(max(height, 200), 700))
            except ValueError:
                pass
        return cls(
            corner=corner if corner in CORNERS else default.corner,
            monitor=monitor,
            opacity=min(1.0, max(0.3, opacity)),
            size=size,
        )


def choose_monitor(reference: str, screens: Sequence[win_desktop.Monitor]) -> win_desktop.Monitor | None:
    """The configured monitor, else the notebook's built-in screen, else the primary one."""
    items = list(screens)
    if not items:
        return None
    try:
        return win_desktop.find_monitor(reference, items)
    except ValueError:
        pass
    return next((m for m in items if m.internal), None) or next((m for m in items if m.primary), items[0])


def panel_origin(work: Rect, size: tuple[int, int], corner: str, margin: int) -> tuple[int, int]:
    """Top-left of a `size` panel in a corner of a work area (physical pixels)."""
    left, top, right, bottom = work
    width, height = size
    x = left + margin if corner.endswith("esquerdo") else right - margin - width
    y = top + margin if corner.startswith("superior") else bottom - margin - height
    return max(left, x), max(top, y)


# ───────────────────────── geometria ─────────────────────────


def virtual_bounds(screens: Sequence[win_desktop.Monitor]) -> Rect:
    """Rectangle around every monitor (x is negative when a monitor sits left of the main one)."""
    if not screens:
        return (0, 0, 1920, 1080)
    return (
        min(m.left for m in screens),
        min(m.top for m in screens),
        max(m.right for m in screens),
        max(m.bottom for m in screens),
    )


def uv_to_real(u: float, v: float, bounds: Rect) -> tuple[int, int]:
    """Hand position (0..1 in each axis) → point on the desktop, spanning every monitor."""
    left, top, right, bottom = bounds
    x = round(left + min(max(u, 0.0), 1.0) * (right - left - 1))
    y = round(top + min(max(v, 0.0), 1.0) * (bottom - top - 1))
    return x, y


def _bounds(monitor: win_desktop.Monitor) -> Rect:
    return monitor.left, monitor.top, monitor.right, monitor.bottom


def _distance(point: tuple[float, float], rect: Rect) -> float:
    x, y = point
    left, top, right, bottom = rect
    return math.hypot(max(left - x, 0.0, x - (right - 1)), max(top - y, 0.0, y - (bottom - 1)))


def monitor_at(point: tuple[float, float], screens: Sequence[win_desktop.Monitor]) -> win_desktop.Monitor | None:
    """Monitor under a desktop point; in the gaps between screens, the closest one."""
    if not screens:
        return None
    return min(screens, key=lambda m: _distance(point, _bounds(m)))


def clip(rect: Rect, to: Rect) -> Rect | None:
    left, top = max(rect[0], to[0]), max(rect[1], to[1])
    right, bottom = min(rect[2], to[2]), min(rect[3], to[3])
    return (left, top, right, bottom) if right > left and bottom > top else None


def relative_rect(rect: Rect, source: Rect, dest: Rect, min_size: tuple[int, int] = MIN_DROP_SIZE) -> Rect:
    """Where `rect` lands on `dest` keeping its place and size relative to `source` (work areas).

    Proportional on purpose: a window covering the left half of a 1920 px notebook at 100 %
    covers the left half of a 3840 px screen at 200 % too, so DPI differences sort themselves out.
    """
    sl, st, sr, sb = source
    dl, dt, dr, db = dest
    sw, sh = max(sr - sl, 1), max(sb - st, 1)
    dw, dh = dr - dl, db - dt
    width = min(dw, max(min(min_size[0], dw), round((rect[2] - rect[0]) * dw / sw)))
    height = min(dh, max(min(min_size[1], dh), round((rect[3] - rect[1]) * dh / sh)))
    x = dl + round((rect[0] - sl) * dw / sw)
    y = dt + round((rect[1] - st) * dh / sh)
    x = min(max(x, dl), dr - width)
    y = min(max(y, dt), db - height)
    return x, y, x + width, y + height


@dataclass(frozen=True)
class MapWindow:
    hwnd: int
    title: str
    process: str
    pid: int
    rect: Rect  # pixels físicos, coordenadas da área de trabalho virtual
    maximized: bool = False

    @property
    def window(self) -> win_desktop.Window:
        return win_desktop.Window(hwnd=self.hwnd, title=self.title, process=self.process, pid=self.pid)


@dataclass(frozen=True)
class DesktopSnapshot:
    """Monitors and app windows (Z order, topmost first) at one moment."""

    monitors: tuple[win_desktop.Monitor, ...] = ()
    windows: tuple[MapWindow, ...] = ()
    taken: float = 0.0


def window_at(point: tuple[float, float], windows: Sequence[MapWindow]) -> MapWindow | None:
    """Topmost window under a desktop point."""
    x, y = point
    for item in windows:
        left, top, right, bottom = item.rect
        if left <= x < right and top <= y < bottom:
            return item
    return None


@dataclass(frozen=True)
class MapLayout:
    """Linear map between the desktop (physical pixels) and the map area of the panel."""

    bounds: Rect
    scale: float
    offset: tuple[float, float]

    @classmethod
    def fit(cls, screens: Sequence[win_desktop.Monitor], area: tuple[float, float, float, float]) -> MapLayout:
        bounds = virtual_bounds(screens)
        left, top, right, bottom = bounds
        x0, y0, x1, y1 = area
        scale = min((x1 - x0) / max(right - left, 1), (y1 - y0) / max(bottom - top, 1))
        ox = x0 + ((x1 - x0) - (right - left) * scale) / 2
        oy = y0 + ((y1 - y0) - (bottom - top) * scale) / 2
        return cls(bounds=bounds, scale=scale, offset=(ox, oy))

    def to_map(self, x: float, y: float) -> tuple[float, float]:
        return self.offset[0] + (x - self.bounds[0]) * self.scale, self.offset[1] + (y - self.bounds[1]) * self.scale

    def to_real(self, mx: float, my: float) -> tuple[float, float]:
        return self.bounds[0] + (mx - self.offset[0]) / self.scale, self.bounds[1] + (my - self.offset[1]) / self.scale

    def rect_to_map(self, rect: Rect) -> tuple[float, float, float, float]:
        x0, y0 = self.to_map(rect[0], rect[1])
        x1, y1 = self.to_map(rect[2], rect[3])
        return x0, y0, x1, y1


# ───────────────────────── arrastar e soltar ─────────────────────────


@dataclass
class MapDrag:
    """A window being carried on the map: where it came from and where it would land."""

    item: MapWindow
    source: win_desktop.Monitor | None
    grab_point: tuple[float, float]  # ponto da área de trabalho onde a mão fechou
    point: tuple[float, float] = (0.0, 0.0)
    dest: win_desktop.Monitor | None = None

    def update(self, point: tuple[float, float], screens: Sequence[win_desktop.Monitor]) -> None:
        self.point = point
        self.dest = monitor_at(point, screens)

    @property
    def moves(self) -> bool:
        """Whether releasing now sends the window to another monitor."""
        return self.dest is not None and (self.source is None or _bounds(self.dest) != _bounds(self.source))

    def ghost(self) -> Rect:
        """The window's rectangle following the hand (for drawing)."""
        dx, dy = self.point[0] - self.grab_point[0], self.point[1] - self.grab_point[1]
        left, top, right, bottom = self.item.rect
        return round(left + dx), round(top + dy), round(right + dx), round(bottom + dy)


# ───────────────────────── desenho ─────────────────────────


@dataclass(frozen=True)
class PanelFrame:
    """Everything the panel shows at one frame (built by the gesture thread, drawn by the panel's)."""

    view: OverlayView | None
    state: str = "idle"
    camera: np.ndarray | None = None  # RGB pequeno, já espelhado
    hand: np.ndarray | None = None  # (21, 2) normalizado no quadro espelhado
    cursor: tuple[float, float] | None = None  # cursor da mão no mapa (ponto da área de trabalho)
    closed: bool = False  # mão fechada (pegando)
    mouse: tuple[float, float] | None = None  # posição do mouse no ar, quando ligado
    hover: int | None = None
    drag: MapDrag | None = None
    fps: float = 0.0
    hint: str = ""


@dataclass
class PanelGeometry:
    width: int
    height: int
    pad: int
    camera: tuple[int, int, int, int]
    text_x: int
    map_area: tuple[int, int, int, int]


def panel_geometry(size: tuple[int, int] = PANEL_SIZE, scale: float = 1.0) -> PanelGeometry:
    width, height = round(size[0] * scale), round(size[1] * scale)
    pad = round(8 * scale)
    cam_w = round(width * 0.42)
    cam_h = round(cam_w * 9 / 16)
    camera = (pad, pad, pad + cam_w, pad + cam_h)
    map_top = camera[3] + pad
    return PanelGeometry(
        width=width,
        height=height,
        pad=pad,
        camera=camera,
        text_x=camera[2] + pad + round(2 * scale),
        map_area=(pad, map_top, width - pad, height - pad - round(6 * scale)),
    )


def _to_image(array: np.ndarray, size: tuple[int, int]) -> Any:
    from PIL import Image

    return Image.fromarray(np.ascontiguousarray(array[..., :3])).resize(size)


def _shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(min(255, max(0, round(channel * factor))) for channel in color)  # type: ignore[return-value]


def _window_color(item: MapWindow) -> tuple[int, int, int]:
    """Stable color per process, so the same app looks the same everywhere on the map."""
    seed = sum(ord(ch) * (i + 1) for i, ch in enumerate(item.process or item.title)) % 360
    hue = seed / 360
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.55)
    return round(r * 255), round(g * 255), round(b * 255)


def render_panel(
    frame: PanelFrame,
    desktop: DesktopSnapshot,
    thumbs: Mapping[int, Any] | None = None,
    scale: float = 1.0,
    size: tuple[int, int] = PANEL_SIZE,
) -> Any:
    """The panel as an RGBA PIL image (pure: testable without a screen)."""
    from PIL import Image, ImageDraw

    thumbs = thumbs or {}
    geo = panel_geometry(size, scale)
    view = frame.view
    color = TONES.get(view.tone if view else "info", TONES["info"])
    image = Image.new("RGBA", (geo.width, geo.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = round(14 * scale)
    line = max(1, round(1.5 * scale))
    draw.rounded_rectangle((0, 0, geo.width - 1, geo.height - 1), radius=radius, fill=(6, 14, 24, 230))
    draw.rounded_rectangle((0, 0, geo.width - 1, geo.height - 1), radius=radius, outline=(*color, 235), width=line)

    # Câmera com os pontos da mão.
    cx0, cy0, cx1, cy1 = geo.camera
    cam_w, cam_h = cx1 - cx0, cy1 - cy0
    if frame.camera is not None:
        image.paste(_to_image(frame.camera, (cam_w, cam_h)), (cx0, cy0))
    else:
        draw.rectangle(geo.camera, fill=(16, 28, 40, 255))
    if frame.hand is not None:
        points = [(cx0 + x * cam_w, cy0 + y * cam_h) for x, y in np.asarray(frame.hand)[:, :2]]
        for start, end in HAND_CONNECTIONS:
            draw.line((points[start], points[end]), fill=(255, 200, 0, 255), width=max(1, round(1.4 * scale)))
        dot = max(1.5, 2 * scale)
        for x, y in points:
            draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(0, 255, 200, 255))
    draw.rectangle(geo.camera, outline=(*_shade(color, 0.8), 200), width=max(1, round(scale)))

    # Estado do gesto ao lado da câmera.
    title_font = _font(TITLE_FONT, round(14 * scale))
    detail_font = _font(DETAIL_FONT, round(11 * scale))
    text_w = geo.width - geo.text_x - geo.pad
    title = view.title if view else "Gestos desarmados"
    detail = view.detail if view and view.detail else frame.hint or "mão aberta parada ~1 s arma"
    draw.ellipse(
        (geo.text_x, cy0 + round(4 * scale), geo.text_x + round(8 * scale), cy0 + round(12 * scale)), fill=(*color, 255)
    )
    title_x = geo.text_x + round(13 * scale)
    draw.text((title_x, cy0), _fit(draw, title, title_font, text_w - (title_x - geo.text_x)), font=title_font, fill=(232, 248, 255, 255))
    y = cy0 + round(21 * scale)
    for row in _wrap(draw, detail, detail_font, text_w, 3):
        draw.text((geo.text_x, y), row, font=detail_font, fill=(150, 205, 225, 255))
        y += round(14 * scale)
    if view is not None and view.progress is not None:
        bar_h = max(2, round(4 * scale))
        top = cy1 - bar_h
        right = geo.text_x + text_w
        draw.rounded_rectangle((geo.text_x, top, right, top + bar_h), radius=bar_h // 2, fill=(255, 255, 255, 40))
        filled = geo.text_x + (right - geo.text_x) * min(1.0, max(0.0, view.progress))
        if filled > geo.text_x + 1:
            draw.rounded_rectangle((geo.text_x, top, filled, top + bar_h), radius=bar_h // 2, fill=(*color, 255))
    small = _font(DETAIL_FONT, round(9 * scale))
    draw.text((cx1 - round(34 * scale), cy1 - round(12 * scale)), f"{frame.fps:2.0f} fps", font=small, fill=(255, 255, 255, 170))

    _render_map(image, draw, frame, desktop, thumbs, geo, scale)
    return image


def _wrap(draw: Any, text: str, font: Any, width: float, rows: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == rows:
            break
    if current and len(lines) < rows:
        lines.append(current)
    elif len(lines) == rows and current:
        lines[-1] = _fit(draw, lines[-1] + " " + current, font, width)
    return [_fit(draw, row, font, width) for row in lines]


def _render_map(
    image: Any,
    draw: Any,
    frame: PanelFrame,
    desktop: DesktopSnapshot,
    thumbs: Mapping[int, Any],
    geo: PanelGeometry,
    scale: float,
) -> None:
    from PIL import Image, ImageDraw

    screens = list(desktop.monitors)
    if not screens:
        font = _font(DETAIL_FONT, round(11 * scale))
        draw.text((geo.map_area[0], geo.map_area[1] + round(6 * scale)), "lendo as telas…", font=font, fill=(150, 205, 225, 255))
        return
    layout = MapLayout.fit(screens, geo.map_area)
    gap = max(1, round(2 * scale))
    label_font = _font(DETAIL_FONT, round(9 * scale))
    drag = frame.drag
    dest = drag.dest if drag is not None else None

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas = ImageDraw.Draw(layer)
    for monitor in screens:
        mx0, my0, mx1, my1 = layout.rect_to_map(_bounds(monitor))
        box = (mx0 + gap, my0 + gap, mx1 - gap, my1 - gap)
        target = drag is not None and dest is not None and _bounds(dest) == _bounds(monitor)
        source = drag is not None and drag.source is not None and _bounds(drag.source) == _bounds(monitor)
        fill = (20, 60, 52, 255) if target and drag.moves else (14, 30, 46, 255)
        canvas.rectangle(box, fill=fill)
        # Janelas, de baixo para cima na ordem Z, recortadas no monitor.
        for item in reversed(desktop.windows):
            if drag is not None and item.hwnd == drag.item.hwnd:
                continue
            visible = clip(item.rect, _bounds(monitor))
            if visible is None:
                continue
            _draw_window(layer, canvas, item, visible, layout, thumbs, frame.hover == item.hwnd, scale, box)
        outline = TONES["armed"] if target and drag.moves else ((90, 130, 150) if not source else (150, 170, 185))
        canvas.rectangle(box, outline=(*outline, 255), width=max(1, round((2.5 if target else 1) * scale)))
        name = f"{monitor.number}" + (f" · {monitor.name}" if monitor.name else "")
        canvas.text((box[0] + round(3 * scale), box[1] + round(1 * scale)), name, font=label_font, fill=(200, 230, 245, 220))

    if drag is not None:
        ghost = layout.rect_to_map(drag.ghost())
        canvas.rectangle(ghost, fill=(0, 210, 255, 70), outline=(0, 230, 255, 255), width=max(1, round(1.5 * scale)))

    marker = frame.mouse or frame.cursor
    if marker is not None:
        x, y = layout.to_map(*marker)
        r = 5 * scale
        if frame.mouse is not None:
            canvas.polygon([(x, y), (x + 2.2 * r, y + 1.4 * r), (x + 1.1 * r, y + 1.6 * r), (x + 0.8 * r, y + 2.6 * r)], fill=(255, 190, 40, 255))
        elif frame.closed:
            canvas.ellipse((x - r, y - r, x + r, y + r), fill=(0, 230, 170, 255), outline=(255, 255, 255, 255))
        else:
            canvas.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 255), width=max(1, round(2 * scale)))
            canvas.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=(255, 255, 255, 255))
    image.alpha_composite(layer)


def _draw_window(
    layer: Any,
    canvas: Any,
    item: MapWindow,
    rect: Rect,
    layout: MapLayout,
    thumbs: Mapping[int, Any],
    hovered: bool,
    scale: float,
    box: tuple[float, float, float, float],
) -> None:
    x0, y0, x1, y1 = layout.rect_to_map(rect)
    x0, y0 = max(x0, box[0]), max(y0, box[1])
    x1, y1 = min(x1, box[2]), min(y1, box[3])
    width, height = int(round(x1 - x0)), int(round(y1 - y0))
    if width < 2 or height < 2:
        return
    thumb = thumbs.get(item.hwnd)
    if thumb is not None:
        # A miniatura é da janela inteira: recorta a parte que cai neste monitor.
        full = item.rect
        tw, th = thumb.size
        crop = (
            round((rect[0] - full[0]) * tw / max(full[2] - full[0], 1)),
            round((rect[1] - full[1]) * th / max(full[3] - full[1], 1)),
            round((rect[2] - full[0]) * tw / max(full[2] - full[0], 1)),
            round((rect[3] - full[1]) * th / max(full[3] - full[1], 1)),
        )
        if crop[2] > crop[0] and crop[3] > crop[1]:
            layer.paste(thumb.crop(crop).convert("RGBA").resize((width, height)), (round(x0), round(y0)))
    else:
        base = _window_color(item)
        canvas.rectangle((x0, y0, x1, y1), fill=(*base, 235))
        canvas.rectangle((x0, y0, x1, min(y1, y0 + max(2, 3 * scale))), fill=(*_shade(base, 1.5), 255))
        if width > 14 * scale and height > 10 * scale:
            letter = (item.title.strip()[:1] or "?").upper()
            font = _font(TITLE_FONT, round(min(height * 0.5, 12 * scale)))
            canvas.text(((x0 + x1) / 2, (y0 + y1) / 2), letter, font=font, fill=(240, 248, 255, 230), anchor="mm")
    outline = (0, 230, 255, 255) if hovered else (220, 235, 245, 150)
    canvas.rectangle((x0, y0, x1, y1), outline=outline, width=max(1, round((2.5 if hovered else 1) * scale)))
