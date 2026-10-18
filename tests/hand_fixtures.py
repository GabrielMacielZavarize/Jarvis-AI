"""Mãos sintéticas no formato do MediaPipe Hands, para testar os gestos sem webcam.

Uma mão "de mentira" é montada num espaço próprio (pulso na origem, base do dedo médio a 1
unidade para cima, palma virada para a câmera), girada, e projetada no quadro espelhado como o
MediaPipe entregaria: pontos normalizados de 0 a 1 e pontos "do mundo" em metros.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from gesture_engine import PALM_POINTS, Hand

FINGER_BASES = {"index": (-0.33, 0.93), "middle": (0.0, 1.0), "ring": (0.30, 0.95), "pinky": (0.55, 0.85)}
FINGER_DIRECTIONS = {"index": (-0.12, 1.0), "middle": (0.0, 1.0), "ring": (0.1, 1.0), "pinky": (0.22, 1.0)}
FINGER_LENGTHS = {
    "index": (0.42, 0.25, 0.2),
    "middle": (0.47, 0.29, 0.21),
    "ring": (0.43, 0.27, 0.2),
    "pinky": (0.33, 0.2, 0.18),
}
STRAIGHT = (5, 5, 5)
CURLED = (80, 100, 60)
TOWARD_CAMERA = np.array([0.0, 0.0, -1.0])  # dobrar os dedos aproxima as pontas da câmera
THUMB_CMC = np.array([-0.28, 0.22, -0.02])
THUMB_OUT = (-0.8, 0.6)
ASPECT = 16 / 9
FPS = 30

POSES = {
    # pose: (dedos esticados, polegar)
    "open": ({"index", "middle", "ring", "pinky"}, "out"),
    "fist": (set(), "tucked"),
    "point": ({"index"}, "tucked"),
    "two": ({"index", "middle"}, "tucked"),
    "thumb_down": (set(), "out"),
    "thumb_up": (set(), "out"),
    "pinch": ({"middle", "ring", "pinky"}, "pinch"),
    "loose_fist": (set(), "pinch"),  # punho frouxo, polegar encostado na ponta do indicador
}
# Giro que deixa o polegar esticado apontando para baixo / para cima no quadro.
THUMB_ANGLE = math.degrees(math.atan2(THUMB_OUT[1], THUMB_OUT[0]))
ROLLS = {"thumb_down": 270 - THUMB_ANGLE, "thumb_up": 90 - THUMB_ANGLE}


def _unit(vector: tuple[float, ...] | np.ndarray) -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    return array / np.linalg.norm(array)


def _finger(name: str, curls: tuple[float, float, float]) -> list[np.ndarray]:
    base = np.array([*FINGER_BASES[name], 0.0])
    direction = _unit((*FINGER_DIRECTIONS[name], 0.0))
    points = [base]
    angle = 0.0
    for length, curl in zip(FINGER_LENGTHS[name], curls):
        angle += math.radians(curl)
        points.append(points[-1] + length * (direction * math.cos(angle) + TOWARD_CAMERA * math.sin(angle)))
    return points


def _thumb(mode: str, index_tip: np.ndarray) -> list[np.ndarray]:
    if mode == "out":
        direction = _unit((*THUMB_OUT, 0.0))
        mcp = THUMB_CMC + 0.35 * direction
        ip = mcp + 0.3 * direction
        return [THUMB_CMC, mcp, ip, ip + 0.25 * direction]
    if mode == "pinch":
        tip = index_tip + np.array([-0.03, 0.0, 0.0])
        return [THUMB_CMC, THUMB_CMC + 0.4 * (tip - THUMB_CMC), THUMB_CMC + 0.72 * (tip - THUMB_CMC), tip]
    mcp = THUMB_CMC + 0.35 * _unit((-0.1, 0.85, -0.5))  # dobrado sobre os dedos (punho)
    ip = mcp + 0.3 * _unit((0.55, 0.5, -0.65))
    return [THUMB_CMC, mcp, ip, ip + 0.25 * _unit((0.9, -0.2, 0.1))]


def hand_space(pose: str) -> np.ndarray:
    """(21, 3) points of a pose in hand space (y up)."""
    straight, thumb = POSES[pose]
    points = [np.zeros(3)] * 21
    points[0] = np.zeros(3)
    starts = {"index": 5, "middle": 9, "ring": 13, "pinky": 17}
    for name, start in starts.items():
        if pose == "pinch" and name == "index":
            curls = (30, 40, 20)
        elif pose == "loose_fist":
            curls = (50, 45, 30) if name == "pinky" else (70, 80, 45)
        else:
            curls = STRAIGHT if name in straight else CURLED
        for offset, point in enumerate(_finger(name, curls)):
            points[start + offset] = point
    for offset, point in enumerate(_thumb(thumb, points[8])):
        points[1 + offset] = point
    return np.array(points)


def make_hand(
    pose: str = "open",
    center: tuple[float, float] = (0.5, 0.5),
    size: float = 0.18,
    roll: float | None = None,
    world: bool = True,
) -> Hand:
    """A hand in a mirrored frame: palm center at `center` (0..1), palm `size` frame heights long."""
    space = hand_space(pose)
    angle = math.radians(ROLLS.get(pose, 0.0) if roll is None else roll)
    rotation = np.array([[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]])
    space = space @ rotation.T
    space = space - space[list(PALM_POINTS)].mean(axis=0) * np.array([1, 1, 0])
    image = np.column_stack(
        [
            center[0] + space[:, 0] * size / ASPECT,
            center[1] - space[:, 1] * size,
            space[:, 2] * size / ASPECT,
        ]
    )
    metric = np.column_stack([space[:, 0], -space[:, 1], space[:, 2]]) * 0.09 if world else None
    return Hand(points=image, world=metric, aspect=ASPECT)


Timeline = list[tuple[float, Hand | None]]


def hold(pose: str, start: float, seconds: float, center: tuple[float, float] = (0.5, 0.5), **kwargs: object) -> Timeline:
    frames = round(seconds * FPS)
    return [(start + i / FPS, make_hand(pose, center, **kwargs)) for i in range(frames)]


def move(
    pose: str,
    start: float,
    seconds: float,
    origin: tuple[float, float],
    end: tuple[float, float],
    path: Callable[[float], float] = lambda k: k,
    **kwargs: object,
) -> Timeline:
    """Hand moving in a straight line from `origin` to `end` (frame coordinates 0..1)."""
    frames = max(2, round(seconds * FPS))
    timeline = []
    for i in range(frames):
        k = path(i / (frames - 1))
        point = (origin[0] + (end[0] - origin[0]) * k, origin[1] + (end[1] - origin[1]) * k)
        timeline.append((start + i / FPS, make_hand(pose, point, **kwargs)))
    return timeline


def absent(start: float, seconds: float) -> Timeline:
    return [(start + i / FPS, None) for i in range(round(seconds * FPS))]


def end_of(timeline: Timeline) -> float:
    return timeline[-1][0] + 1 / FPS
