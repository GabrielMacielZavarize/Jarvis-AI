"""Reconhecimento de gestos das mãos: poses, suavização e máquina de estados.

Lógica pura, sem câmera, Win32 nem MediaPipe: recebe os 21 pontos de uma mão por quadro
(no formato do MediaPipe Hands, já espelhados como num espelho) e devolve comandos como
"pegar a janela", "jogar para cima" ou "fechar". Por isso tudo aqui é testável com mãos
sintéticas, sem webcam.

Coordenadas: x e y vão de 0 a 1 no quadro espelhado (x cresce para a direita da pessoa,
y para baixo). Distâncias e velocidades são medidas em "alturas de quadro", com x
multiplicado pela proporção do quadro, para que um movimento valha o mesmo nos dois eixos.

Proteções contra acidentes: nada acontece antes de "armar" (mão aberta parada ~1 s); cada
pose só vale depois de estável por um instante (debounce); direções têm histerese; depois de
uma ação há um intervalo (cooldown); e repetir exige soltar a pose antes. Armado sem uso por
alguns segundos, ou sem a mão no quadro, ele desarma sozinho.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

WRIST = 0
THUMB = (1, 2, 3, 4)
FINGERS = {
    "index": (5, 6, 7, 8),
    "middle": (9, 10, 11, 12),
    "ring": (13, 14, 15, 16),
    "pinky": (17, 18, 19, 20),
}
INDEX_MCP = 5
MIDDLE_MCP = 9
PALM_POINTS = (0, 5, 9, 13, 17)
DIRECTIONS = ("up", "down", "left", "right")


class Pose(str, Enum):
    NONE = "none"  # transição ou pose ambígua
    OPEN = "open"
    FIST = "fist"
    POINT = "point"
    TWO = "two"
    PINCH = "pinch"
    THUMB_DOWN = "thumb_down"
    THUMB_UP = "thumb_up"


class State(str, Enum):
    IDLE = "idle"  # desarmado: só a mão aberta parada faz algo (arma)
    ARMED = "armed"
    GRAB = "grab"  # punho fechado segurando a janela em foco
    CLOSE = "close"  # polegar para baixo: contagem para fechar
    MOUSE = "mouse"  # mouse no ar


@dataclass(frozen=True)
class Hand:
    """One detected hand: MediaPipe landmarks of a mirrored frame."""

    points: np.ndarray  # (21, 3) x, y normalizados no quadro; z na escala de x
    world: np.ndarray | None = None  # (21, 3) em metros, quando o detector fornece
    aspect: float = 16 / 9  # largura / altura do quadro
    handedness: str = ""
    score: float = 1.0


@dataclass(frozen=True)
class Shape:
    pose: Pose
    extended: dict[str, bool]
    folded: dict[str, bool]
    pinch: float  # distância polegar–indicador / tamanho da palma
    palm: float  # tamanho da palma (pulso → base do dedo médio) em alturas de quadro
    center: tuple[float, float]  # centro da palma em alturas de quadro (x * proporção)
    pointer: tuple[float, float]  # base do indicador, normalizada de 0 a 1 (mouse no ar)
    metrics: dict[str, float] = field(default_factory=dict)  # ângulos e razões usados (calibração)


@dataclass(frozen=True)
class Tuning:
    """Limiares do reconhecimento. Tempos em segundos, distâncias em alturas de quadro."""

    stable_pose_s: float = 0.12  # uma pose só vale depois de durar isso
    still_speed: float = 0.35  # abaixo disso (alturas/s) a mão está "parada"
    arm_hold_s: float = 1.0
    idle_disarm_s: float = 12.0
    lost_disarm_s: float = 5.0
    lost_grace_s: float = 0.3  # quadros sem mão tolerados antes de cancelar um gesto
    cooldown_s: float = 0.8
    grab_confirm_s: float = 0.2  # punho segurado antes de pegar a janela
    grab_cancel_s: float = 4.0  # punho parado por tanto tempo sem direção cancela
    release_none_s: float = 1.0  # pose ambígua por tanto tempo enquanto segura cancela
    throw_distance: float = 0.12
    maximize_max_move: float = 0.07
    close_hold_s: float = 1.2
    swipe_distance: float = 0.2
    swipe_max_s: float = 0.5
    swipe_min_speed: float = 0.8
    swipe_settle_s: float = 0.45  # o swipe para baixo só vale se a mão parar ainda no quadro
    tab_cooldown_s: float = 0.35
    return_block_s: float = 0.8  # ignora o movimento de volta depois de um swipe de aba
    wipe_window_s: float = 1.4
    wipe_amplitude: float = 0.07
    wipe_segments: int = 3
    mouse_enter_s: float = 0.9
    mouse_exit_s: float = 1.0
    mouse_lost_s: float = 8.0
    pinch_on: float = 0.3
    pinch_off: float = 0.45
    drag_after_s: float = 0.35
    click_freeze_s: float = 0.12
    mouse_box: tuple[float, float, float, float] = (0.2, 0.15, 0.8, 0.7)  # região do quadro → todas as telas
    mouse_epsilon: float = 0.0004


@dataclass(frozen=True)
class Command:
    kind: str
    direction: str | None = None
    vector: tuple[float, float] = (0.0, 0.0)
    point: tuple[float, float] | None = None
    step: int = 0


@dataclass(frozen=True)
class Status:
    state: State
    pose: Pose
    hand: bool
    charging: str | None = None  # "arm" | "mouse_on" | "mouse_off" | "close"
    progress: float | None = None
    direction: str | None = None
    dragging: bool = False


# ───────────────────────── poses ─────────────────────────


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    cos = float(np.dot(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _shape_points(hand: Hand) -> np.ndarray:
    if hand.world is not None:
        return np.asarray(hand.world, dtype=float)
    points = np.asarray(hand.points, dtype=float).copy()
    points[:, 0] *= hand.aspect
    points[:, 2] *= hand.aspect
    return points


def classify(hand: Hand) -> Shape:
    """Pose of one hand, using joint angles (works with the hand tilted or far away)."""
    s = _shape_points(hand)
    flat = np.asarray(hand.points, dtype=float)[:, :2] * (hand.aspect, 1.0)
    palm3d = max(float(np.linalg.norm(s[MIDDLE_MCP] - s[WRIST])), 1e-6)
    palm = max(float(np.linalg.norm(flat[MIDDLE_MCP] - flat[WRIST])), 1e-6)

    extended: dict[str, bool] = {}
    folded: dict[str, bool] = {}
    metrics: dict[str, float] = {}
    for name, (mcp, pip, dip, tip) in FINGERS.items():
        bend = _angle(s[pip] - s[mcp], s[tip] - s[dip])
        reach = float(np.linalg.norm(s[tip] - s[WRIST])) / max(float(np.linalg.norm(s[pip] - s[WRIST])), 1e-6)
        extended[name] = bend < 55 and reach > 1.15
        folded[name] = bend > 95 or reach < 0.95
        metrics[f"{name}_bend"], metrics[f"{name}_reach"] = bend, reach

    cmc, mcp, ip, tip = THUMB
    thumb_bend = _angle(s[ip] - s[mcp], s[tip] - s[ip])
    thumb_out = float(np.linalg.norm(s[tip] - s[INDEX_MCP])) / palm3d
    extended["thumb"] = thumb_bend < 40 and thumb_out > 0.6
    folded["thumb"] = thumb_out < 0.45
    pinch = float(np.linalg.norm(s[tip] - s[FINGERS["index"][3]])) / palm3d
    thumb_dir = flat[tip] - flat[mcp]
    metrics.update(
        thumb_bend=thumb_bend,
        thumb_out=thumb_out,
        thumb_dir_y=float(thumb_dir[1] / max(float(np.linalg.norm(thumb_dir)), 1e-6)),
        pinch=pinch,
        palm=palm,
    )

    four = ("index", "middle", "ring", "pinky")
    pose = Pose.NONE
    if all(folded[f] for f in four):
        pose = Pose.FIST
        if extended["thumb"]:
            direction = flat[tip] - flat[mcp]
            direction = direction / max(float(np.linalg.norm(direction)), 1e-6)
            others = [i for i in range(21) if i not in (ip, tip)]
            margin = 0.1 * palm
            if direction[1] > 0.7 and flat[tip][1] > flat[others, 1].max() + margin:
                pose = Pose.THUMB_DOWN
            elif direction[1] < -0.7 and flat[tip][1] < flat[others, 1].min() - margin:
                pose = Pose.THUMB_UP
    elif pinch < 0.3:
        pose = Pose.PINCH
    elif all(extended[f] for f in four):
        pose = Pose.OPEN
    elif extended["index"] and all(folded[f] for f in ("middle", "ring", "pinky")):
        pose = Pose.POINT
    elif extended["index"] and extended["middle"] and folded["ring"] and folded["pinky"]:
        pose = Pose.TWO

    center = flat[list(PALM_POINTS)].mean(axis=0)
    pointer = np.asarray(hand.points, dtype=float)[INDEX_MCP, :2]
    return Shape(
        pose=pose,
        extended=extended,
        folded=folded,
        pinch=pinch,
        palm=palm,
        center=(float(center[0]), float(center[1])),
        pointer=(float(pointer[0]), float(pointer[1])),
        metrics=metrics,
    )


# ───────────────────────── suavização ─────────────────────────


class OneEuroFilter:
    """One Euro filter (Casiez et al.): smooths jitter at rest, follows fast moves with little lag."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self) -> None:
        self._t: float | None = None
        self._x = 0.0
        self._dx = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t: float, x: float) -> float:
        if self._t is None or t <= self._t:
            self._t, self._x, self._dx = t, x, 0.0
            return x
        dt = t - self._t
        dx = (x - self._x) / dt
        self._dx += self._alpha(self.d_cutoff, dt) * (dx - self._dx)
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        self._x += self._alpha(cutoff, dt) * (x - self._x)
        self._t = t
        return self._x


class Filter2D:
    def __init__(self, min_cutoff: float, beta: float) -> None:
        self._x = OneEuroFilter(min_cutoff, beta)
        self._y = OneEuroFilter(min_cutoff, beta)

    def reset(self) -> None:
        self._x.reset()
        self._y.reset()

    def __call__(self, t: float, point: tuple[float, float]) -> tuple[float, float]:
        return self._x(t, point[0]), self._y(t, point[1])


# ───────────────────────── máquina de estados ─────────────────────────


def dominant_direction(dx: float, dy: float, current: str | None = None) -> str:
    """'left'/'right'/'up'/'down' of a movement, keeping the current axis unless the other clearly wins."""
    horizontal = "right" if dx > 0 else "left"
    vertical = "down" if dy > 0 else "up"
    ax, ay = abs(dx), abs(dy)
    if current in ("left", "right") and ax >= ay * 0.75:
        return horizontal
    if current in ("up", "down") and ay >= ax * 0.75:
        return vertical
    return horizontal if ax > ay else vertical


class GestureMachine:
    """Turns one hand per frame into commands. Call step() for every frame (hand=None when absent)."""

    def __init__(self, tuning: Tuning | None = None) -> None:
        self.tuning = tuning or Tuning()
        self.state = State.IDLE
        self.pose = Pose.NONE
        self._pose_since = 0.0
        self._candidate = Pose.NONE
        self._candidate_since = 0.0
        self._center_filter = Filter2D(min_cutoff=1.5, beta=0.5)
        self._pointer_filter = Filter2D(min_cutoff=0.8, beta=4.0)
        self._history: deque[tuple[float, float, float]] = deque()
        self._still_since = 0.0
        self._last_seen: float | None = None
        self._last_activity = 0.0
        self._cooldown_until = 0.0
        self._need_release = False
        self._rearm_blocked = False  # depois de desarmar, só rearma se a mão mudar de pose ou sair
        self._origin = (0.0, 0.0)
        self._grab_t = 0.0
        self._direction: str | None = None
        self._vector = (0.0, 0.0)
        self._none_since: float | None = None
        self._close_t = 0.0
        self._pending_swipe: float | None = None
        self._tab_until = 0.0
        self._blocked: tuple[str, float] | None = None
        self._pinching = False
        self._pinch_t = 0.0
        self._dragging = False
        self._freeze_until = 0.0
        self._last_point: tuple[float, float] | None = None
        self._charging: tuple[str, float] | None = None
        self._shape: Shape | None = None

    # ── controle externo (voz, teclado do preview) ──

    def arm(self, t: float) -> list[Command]:
        if self.state != State.IDLE:
            return []
        self._rearm_blocked = False
        self._enter(State.ARMED, t)
        return [Command("armed")]

    def disarm(self, t: float) -> list[Command]:
        if self.state == State.IDLE:
            return []
        out = self._release_mouse()
        if self.state in (State.GRAB, State.CLOSE):
            out.append(Command("cancel"))
        self._enter(State.IDLE, t)
        self._rearm_blocked = True
        out.append(Command("disarmed"))
        return out

    def set_mouse(self, t: float, on: bool) -> list[Command]:
        if on and self.state != State.MOUSE:
            out = self.arm(t) if self.state == State.IDLE else []
            if self.state in (State.GRAB, State.CLOSE):
                out.append(Command("cancel"))
            self._enter(State.MOUSE, t)
            return [*out, Command("mouse_on")]
        if not on and self.state == State.MOUSE:
            out = self._release_mouse()
            self._enter(State.ARMED, t)
            return [*out, Command("mouse_off")]
        return []

    def abort(self, t: float) -> None:
        """Give up the current grab/close (e.g. there was no window to act on)."""
        if self.state in (State.GRAB, State.CLOSE):
            self._need_release = True
            self._enter(State.ARMED, t)
            self._cooldown_until = t + self.tuning.cooldown_s

    def status(self, t: float) -> Status:
        charging = self._charging
        progress = None
        if self.state == State.CLOSE:
            charging = ("close", min(1.0, (t - self._close_t) / self.tuning.close_hold_s))
        if charging:
            progress = charging[1]
        return Status(
            state=self.state,
            pose=self.pose,
            hand=self._last_seen is not None and t - self._last_seen <= self.tuning.lost_grace_s,
            charging=charging[0] if charging else None,
            progress=progress,
            direction=self._direction if self.state == State.GRAB else None,
            dragging=self._dragging,
        )

    # ── quadro a quadro ──

    def step(self, t: float, hand: Hand | None) -> list[Command]:
        out: list[Command] = []
        self._charging = None
        if hand is None:
            self._lost(t, out)
            return out

        tuning = self.tuning
        if self._last_seen is None or t - self._last_seen > tuning.lost_grace_s:
            self._center_filter.reset()
            self._pointer_filter.reset()
            self._history.clear()
            self._candidate = self.pose = Pose.NONE
            self._candidate_since = self._pose_since = self._still_since = t
        self._last_seen = t

        shape = classify(hand)
        self._shape = shape
        if self._debounce(t, shape.pose):
            self._history.clear()
            self._still_since = t
            self._pending_swipe = None
            self._touch(t)
        cx, cy = self._center_filter(t, shape.center)
        self._history.append((t, cx, cy))
        while self._history and t - self._history[0][0] > max(tuning.wipe_window_s, tuning.swipe_max_s) + 0.2:
            self._history.popleft()
        if self._speed(t) > tuning.still_speed:
            self._still_since = t

        handler = {
            State.IDLE: self._idle,
            State.ARMED: self._armed,
            State.GRAB: self._grab,
            State.CLOSE: self._close,
            State.MOUSE: self._mouse,
        }[self.state]
        handler(t, shape, (cx, cy), out)
        if out:
            self._touch(t)
        return out

    # ── estados ──

    def _idle(self, t: float, shape: Shape, center: tuple[float, float], out: list[Command]) -> None:
        if self._rearm_blocked:
            if self.pose not in (Pose.OPEN, Pose.NONE):
                self._rearm_blocked = False
            return
        held = self._still_for(t)
        if self.pose == Pose.OPEN and held > 0.2:
            self._charging = ("arm", min(1.0, held / self.tuning.arm_hold_s))
            if held >= self.tuning.arm_hold_s:
                out.extend(self.arm(t))

    def _armed(self, t: float, shape: Shape, center: tuple[float, float], out: list[Command]) -> None:
        tuning = self.tuning
        if t - self._last_activity > tuning.idle_disarm_s:
            out.extend(self.disarm(t))
            return
        if self._need_release and self.pose not in (Pose.FIST, Pose.THUMB_DOWN, Pose.NONE):
            self._need_release = False
        if self._pending_swipe is not None:
            if t - self._pending_swipe > tuning.swipe_settle_s:
                self._pending_swipe = None
            elif self._speed(t) < tuning.still_speed:
                self._pending_swipe = None
                self._after_action(t)
                out.append(Command("minimize", direction="down"))
            return
        if t < self._cooldown_until:
            return

        if self.pose == Pose.FIST and not self._need_release and t - self._pose_since >= tuning.grab_confirm_s:
            self._enter(State.GRAB, t)
            self._origin = center
            self._grab_t = t
            out.append(Command("grab"))
        elif self.pose == Pose.THUMB_DOWN and not self._need_release:
            self._enter(State.CLOSE, t)
            self._close_t = t
            out.append(Command("grab"))
        elif self.pose == Pose.OPEN:
            if self._wipe(t):
                self._history.clear()
                self._after_action(t)
                out.append(Command("undo"))
                return
            swipe = self._swipe(t)
            if swipe and swipe[0] == "down":
                self._pending_swipe = t
                self._history.clear()
        elif self.pose == Pose.TWO and t >= self._tab_until:
            swipe = self._swipe(t)
            if swipe and swipe[0] in ("left", "right"):
                direction = swipe[0]
                if self._blocked and self._blocked[0] == direction and t < self._blocked[1]:
                    return
                self._history.clear()
                self._tab_until = t + tuning.tab_cooldown_s
                opposite = "left" if direction == "right" else "right"
                self._blocked = (opposite, t + tuning.return_block_s)
                out.append(Command("tab", direction=direction, step=1 if direction == "right" else -1))
        elif self.pose == Pose.POINT:
            held = self._still_for(t)
            if held > 0.25:
                self._charging = ("mouse_on", min(1.0, held / tuning.mouse_enter_s))
                if held >= tuning.mouse_enter_s:
                    self._enter(State.MOUSE, t)
                    out.append(Command("mouse_on"))

    def _grab(self, t: float, shape: Shape, center: tuple[float, float], out: list[Command]) -> None:
        tuning = self.tuning
        dx, dy = center[0] - self._origin[0], center[1] - self._origin[1]
        distance = math.hypot(dx, dy)
        self._vector = (dx, dy)

        if self.pose == Pose.THUMB_DOWN and self._direction is None:
            self._enter(State.CLOSE, t)
            self._close_t = t
            return

        if distance >= tuning.throw_distance:
            direction: str | None = dominant_direction(dx, dy, self._direction)
        elif distance < tuning.throw_distance * 0.7:
            direction = None
        else:
            direction = self._direction
        if direction != self._direction:
            self._direction = direction
            out.append(Command("aim", direction=direction, vector=(dx, dy)))

        if self.pose in (Pose.OPEN, Pose.TWO, Pose.POINT, Pose.THUMB_UP):
            if self._direction:
                out.append(Command("throw", direction=self._direction, vector=(dx, dy)))
            elif distance <= tuning.maximize_max_move:
                out.append(Command("maximize"))
            else:
                out.append(Command("cancel"))
            self._after_action(t)
            return

        if self.pose == Pose.NONE:
            self._none_since = self._none_since if self._none_since is not None else t
            if t - self._none_since >= tuning.release_none_s:
                out.append(Command("cancel"))
                self._need_release = True
                self._after_action(t)
            return
        self._none_since = None

        if self._direction is None and t - self._grab_t >= tuning.grab_cancel_s and self._still_for(t) >= 1.0:
            out.append(Command("cancel"))
            self._need_release = True
            self._after_action(t)

    def _close(self, t: float, shape: Shape, center: tuple[float, float], out: list[Command]) -> None:
        if self.pose != Pose.THUMB_DOWN:
            out.append(Command("cancel"))
            self._need_release = True
            self._enter(State.ARMED, t)
            return
        if t - self._close_t >= self.tuning.close_hold_s:
            out.append(Command("close"))
            self._need_release = True
            self._after_action(t, cooldown=self.tuning.cooldown_s * 1.5)

    def _mouse(self, t: float, shape: Shape, center: tuple[float, float], out: list[Command]) -> None:
        tuning = self.tuning
        px, py = self._pointer_filter(t, shape.pointer)
        x0, y0, x1, y1 = tuning.mouse_box
        point = (min(1.0, max(0.0, (px - x0) / (x1 - x0))), min(1.0, max(0.0, (py - y0) / (y1 - y0))))

        if not self._pinching and shape.pinch < tuning.pinch_on:
            self._pinching = True
            self._pinch_t = t
            self._freeze_until = t + tuning.click_freeze_s
        if t >= self._freeze_until and (
            self._last_point is None
            or abs(point[0] - self._last_point[0]) + abs(point[1] - self._last_point[1]) > tuning.mouse_epsilon
        ):
            self._last_point = point
            out.append(Command("mouse_move", point=point))
        if self._pinching and shape.pinch > tuning.pinch_off:
            self._pinching = False
            out.append(Command("mouse_up" if self._dragging else "click"))
            self._dragging = False
        elif self._pinching and not self._dragging and t - self._pinch_t >= tuning.drag_after_s:
            self._dragging = True
            out.append(Command("mouse_down"))

        if self.pose == Pose.OPEN and not self._pinching:
            held = self._still_for(t)
            if held > 0.25:
                self._charging = ("mouse_off", min(1.0, held / tuning.mouse_exit_s))
                if held >= tuning.mouse_exit_s:
                    out.extend(self._release_mouse())
                    self._enter(State.ARMED, t)
                    self._need_release = False
                    self._cooldown_until = t + tuning.cooldown_s
                    out.append(Command("mouse_off"))

    def _lost(self, t: float, out: list[Command]) -> None:
        tuning = self.tuning
        self._pending_swipe = None
        if self._last_seen is None:
            return
        lost_for = t - self._last_seen
        if lost_for <= tuning.lost_grace_s:
            return
        self._rearm_blocked = False
        if self.state in (State.GRAB, State.CLOSE):
            out.append(Command("cancel"))
            self._need_release = False
            self._enter(State.ARMED, t)
            self._touch(t)
        elif self.state == State.MOUSE:
            out.extend(self._release_mouse())
            if lost_for > tuning.mouse_lost_s:
                self._enter(State.IDLE, t)
                out.extend([Command("mouse_off"), Command("disarmed")])
        elif self.state == State.ARMED and lost_for > tuning.lost_disarm_s:
            out.extend(self.disarm(t))

    # ── auxiliares ──

    def _enter(self, state: State, t: float) -> None:
        self.state = state
        self._direction = None
        self._vector = (0.0, 0.0)
        self._none_since = None
        self._pending_swipe = None
        self._touch(t)
        if state != State.MOUSE:
            self._pinching = False
            self._dragging = False
            self._last_point = None

    def _after_action(self, t: float, cooldown: float | None = None) -> None:
        if self.state != State.ARMED:
            self._enter(State.ARMED, t)
        self._cooldown_until = t + (self.tuning.cooldown_s if cooldown is None else cooldown)
        self._touch(t)

    def _release_mouse(self) -> list[Command]:
        out = [Command("mouse_up")] if self._dragging else []
        self._dragging = False
        self._pinching = False
        return out

    def _touch(self, t: float) -> None:
        self._last_activity = t

    def _debounce(self, t: float, pose: Pose) -> bool:
        """Update the stable pose; True when it changed."""
        if pose != self._candidate:
            self._candidate = pose
            self._candidate_since = t
        if self._candidate != self.pose and t - self._candidate_since >= self.tuning.stable_pose_s:
            self.pose = self._candidate
            self._pose_since = self._candidate_since
            return True
        return False

    def _still_for(self, t: float) -> float:
        return t - max(self._still_since, self._pose_since)

    def _speed(self, t: float, window: float = 0.15) -> float:
        if len(self._history) < 2:
            return 0.0
        newest = self._history[-1]
        oldest = newest
        for sample in reversed(self._history):
            oldest = sample
            if newest[0] - sample[0] >= window:
                break
        dt = newest[0] - oldest[0]
        if dt <= 0:
            return 0.0
        return math.hypot(newest[1] - oldest[1], newest[2] - oldest[2]) / dt

    def _swipe(self, t: float) -> tuple[str, tuple[float, float]] | None:
        tuning = self.tuning
        recent = [sample for sample in self._history if t - sample[0] <= tuning.swipe_max_s]
        if len(recent) < 3:
            return None
        _, x1, y1 = recent[-1]
        start = max(recent[:-1], key=lambda sample: math.hypot(x1 - sample[1], y1 - sample[2]))
        dx, dy = x1 - start[1], y1 - start[2]
        distance = math.hypot(dx, dy)
        elapsed = max(t - start[0], 1e-3)
        if distance < tuning.swipe_distance or distance / elapsed < tuning.swipe_min_speed:
            return None
        if abs(dx) >= 2 * abs(dy):
            return ("right" if dx > 0 else "left"), (dx, dy)
        if abs(dy) >= 2 * abs(dx):
            return ("down" if dy > 0 else "up"), (dx, dy)
        return None

    def _wipe(self, t: float) -> bool:
        """Side-to-side 'erase' motion (open palm): at least N strokes of a minimum size."""
        tuning = self.tuning
        xs = [sample[1] for sample in self._history if t - sample[0] <= tuning.wipe_window_s]
        if len(xs) < 4:
            return False
        pivot = extreme = xs[0]
        heading = 0
        strokes = 0
        for x in xs[1:]:
            if heading == 0:
                if abs(x - pivot) >= tuning.wipe_amplitude:
                    heading = 1 if x > pivot else -1
                    extreme = x
                    strokes = 1
            elif heading > 0:
                if x > extreme:
                    extreme = x
                elif extreme - x >= tuning.wipe_amplitude:
                    heading, pivot, extreme = -1, extreme, x
                    strokes += 1
            else:
                if x < extreme:
                    extreme = x
                elif x - extreme >= tuning.wipe_amplitude:
                    heading, pivot, extreme = 1, extreme, x
                    strokes += 1
        return strokes >= tuning.wipe_segments
