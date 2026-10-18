"""Controle de janelas por gestos das mãos (webcam + MediaPipe Hands).

Uso:
    python gestures.py --preview             # abre a webcam e mostra os pontos da mão e o gesto
    python gestures.py --preview --dry-run   # idem, sem mexer em nenhuma janela
    python gestures.py                       # só o overlay, sem janela de preview

O motor (GestureEngine) consome um iterador de quadros BGR e não abre a câmera sozinho: o
runner deste arquivo abre a webcam direto para desenvolver, e o Jarvis liga/desliga tudo pela
ferramenta de voz gesture_control (JARVIS_ENABLE_GESTURES=true).

Privacidade: os quadros são processados na memória, neste computador, e descartados. Nada é
gravado nem enviado; só os eventos (ex.: "janela → monitor de cima") vão para o HUD local.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import logging
import os
import queue
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import numpy as np
from livekit.agents import RunContext, function_tool, get_job_context

from gesture_actions import DesktopActions, DryRunActions, GestureActionError, Target, describe_direction
from gesture_engine import Command, GestureMachine, Hand, Pose, State, Status, Tuning, classify
from gesture_overlay import Overlay, OverlayView

logger = logging.getLogger("jarvis-gestures")

ROOT = Path(__file__).resolve().parent
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
MODEL_PATH = ROOT / ".cache" / "models" / "hand_landmarker.task"
DETECT_WIDTH = 640  # a detecção roda numa cópia reduzida do quadro
CAMERA_SIZE = (1280, 720)
AUTOSTART_ENV = "JARVIS_GESTURES_AUTOSTART"
FOCUS_CACHE_SECONDS = 1.0
FLASH_SECONDS = 2.2

ACTION_LABELS = {
    "throw": "Movendo a janela",
    "maximize": "Estendendo",
    "minimize": "Minimizando",
    "undo": "Desfazendo",
    "close": "Fechando",
    "tab": "Trocando de aba",
}
HINT_ARMED = "punho: pegar janela · polegar ↓: fechar · 2 dedos: abas · indicador parado: mouse"
HINT_GRAB = "mova e abra a mão: outro monitor · abra parado: estender"
HINT_MOUSE = "pinça ou fechar a mão: clique · segurar: arrastar · palma parada: sair"


class CameraError(RuntimeError):
    """The webcam could not be opened or stopped sending frames (message is user-facing)."""


# ───────────────────────── modelo e detector ─────────────────────────


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(path: Path = MODEL_PATH) -> Path:
    """Download MediaPipe's hand model once (to .cache/, ignored by git) and check its hash."""
    if path.exists() and _sha256(path) == MODEL_SHA256:
        return path
    import requests

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    logger.info("Baixando o modelo de mãos do MediaPipe (≈8 MB)...")
    with requests.get(MODEL_URL, stream=True, timeout=30) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(1 << 16):
                handle.write(chunk)
    if _sha256(partial) != MODEL_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError("O modelo de mãos baixado não confere com o hash esperado; nada foi usado.")
    partial.replace(path)
    return path


class HandTracker:
    """MediaPipe HandLandmarker (Tasks API) in video mode: one hand per frame."""

    def __init__(self, model_path: Path | None = None) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path or ensure_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ms = -1

    def detect(self, frame: np.ndarray, t: float) -> Hand | None:
        """Hand in a mirrored BGR frame, or None."""
        import cv2

        height, width = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        stamp = max(self._last_ms + 1, int(t * 1000))
        self._last_ms = stamp
        result = self._landmarker.detect_for_video(image, stamp)
        if not result.hand_landmarks:
            return None
        points = np.array([[p.x, p.y, p.z] for p in result.hand_landmarks[0]], dtype=float)
        world = None
        if result.hand_world_landmarks:
            world = np.array([[p.x, p.y, p.z] for p in result.hand_world_landmarks[0]], dtype=float)
        category = result.handedness[0][0] if result.handedness and result.handedness[0] else None
        return Hand(
            points=points,
            world=world,
            aspect=width / height,
            handedness=category.category_name if category else "",
            score=float(category.score) if category else 1.0,
        )

    def close(self) -> None:
        self._landmarker.close()


# ───────────────────────── quadros ─────────────────────────


def _is_color(frame: np.ndarray) -> bool:
    """False for the IR camera (gray frames where B, G and R are the same)."""
    sample = frame[::8, ::8].astype(np.int16)
    return float(np.abs(sample[..., 0] - sample[..., 1]).mean() + np.abs(sample[..., 1] - sample[..., 2]).mean()) > 2.0


def open_webcam(index: int | None = None) -> Any:
    """Open the color webcam (the ASUS FHD one, never the IR camera) with DirectShow."""
    import cv2

    configured = os.environ.get("JARVIS_CAMERA_INDEX", "").strip()
    if index is None and configured.isdigit():
        index = int(configured)
    for candidate in [index] if index is not None else range(4):
        capture = cv2.VideoCapture(candidate, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            continue
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
        capture.set(cv2.CAP_PROP_FPS, 30)
        for _ in range(15):
            ok, frame = capture.read()
            if ok and frame is not None:
                if _is_color(frame):
                    logger.info("Webcam %s aberta (%sx%s).", candidate, frame.shape[1], frame.shape[0])
                    return capture
                break
        capture.release()
    raise CameraError("Não consegui abrir a webcam: ela pode estar em uso por outro app (Teams, Zoom, câmera do Windows).")


def webcam_frames(index: int | None = None) -> Iterator[np.ndarray]:
    """Newest frame straight from the webcam (development runner; the Jarvis will use the camera hub).

    A reader thread keeps only the latest frame, so detecting a hand never makes the next read
    wait for another exposure (reading and detecting in series halves the frame rate).
    """
    capture = open_webcam(index)
    latest: dict[str, Any] = {"frame": None, "seq": 0, "error": None}
    changed = threading.Condition()
    stop = threading.Event()

    def reader() -> None:
        failures = 0
        while not stop.is_set():
            ok, frame = capture.read()
            if not ok or frame is None:
                failures += 1
                if failures > 60:
                    latest["error"] = CameraError("A webcam parou de enviar imagens.")
                    break
                time.sleep(0.02)
                continue
            failures = 0
            with changed:
                latest["frame"] = frame
                latest["seq"] += 1
                changed.notify_all()
        with changed:
            changed.notify_all()

    thread = threading.Thread(target=reader, name="gesture-webcam", daemon=True)
    thread.start()
    seen = 0
    try:
        while True:
            with changed:
                changed.wait_for(lambda: latest["seq"] != seen or not thread.is_alive(), timeout=2.0)
                if latest["error"] is not None:
                    raise latest["error"]
                if latest["seq"] == seen:
                    if not thread.is_alive():
                        raise CameraError("A webcam parou de enviar imagens.")
                    continue
                seen, frame = latest["seq"], latest["frame"]
            yield frame
    finally:
        stop.set()
        thread.join(timeout=2)
        capture.release()


def default_frames() -> tuple[Iterator[np.ndarray], str]:
    """Where the gesture engine gets its frames.

    TODO(camera-hub): ponto de integração com o camera.py da sessão de câmera. Quando o hub
    existir neste processo, os gestos consomem get_hub().frames() (o quadro mais novo, com vários
    consumidores) e dividem a webcam com a visão do Jarvis em vez de abri-la de novo. Confirme na
    junção que frames() entrega quadros BGR sem espelhar; o motor espelha sozinho.
    """
    try:
        from camera import get_hub  # type: ignore[import-not-found]
    except ImportError:
        return webcam_frames(), "webcam"
    return iter(get_hub().frames()), "hub da câmera"


# ───────────────────────── motor ─────────────────────────


def _prepare(frame: np.ndarray) -> np.ndarray:
    """Reduced, mirrored copy of a frame (selfie view: your right is the image's right)."""
    height, width = frame.shape[:2]
    if width > DETECT_WIDTH:
        import cv2

        frame = cv2.resize(frame, (DETECT_WIDTH, round(height * DETECT_WIDTH / width)), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(frame[:, ::-1])


class GestureEngine:
    """Frames → hand → commands → desktop actions, with overlay and events.

    Host-agnostic: give it any iterator of BGR frames (webcam, camera hub, a test list) and an
    actions object. run(stop_event) blocks until the frames end or stop_event is set.
    """

    def __init__(
        self,
        frames: Iterable[np.ndarray],
        actions: Any,
        *,
        tracker: Any | None = None,
        overlay: Overlay | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
        tuning: Tuning | None = None,
        clock: Callable[[], float] = time.monotonic,
        preview: bool = False,
        armed: bool = False,
        mouse: bool = False,
        on_ready: Callable[[], None] | None = None,
        trace: Any | None = None,
    ) -> None:
        self.frames = frames
        self.actions = actions
        self.tracker = tracker
        self.overlay = overlay
        self.emit = emit or (lambda _event: None)
        self.machine = GestureMachine(tuning)
        self.clock = clock
        self.preview = preview
        self.on_ready = on_ready
        self.trace = trace  # arquivo para números de calibração (nunca imagens)
        self.fps = 0.0
        self.hand: Hand | None = None
        self._requests: queue.Queue[str] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gesture-action")
        self._target: Target | None = None
        self._aim: tuple[str | None, str | None] = (None, None)  # (direção, monitor de destino)
        self._flash: tuple[str, str, float] | None = None
        self._focus: tuple[Any, float] | None = None
        self._last_t: float | None = None
        self._stopping = False
        if armed:
            self.request("arm")
        if mouse:
            self.request("mouse_on")

    def request(self, action: Literal["arm", "disarm", "mouse_on", "mouse_off", "quit"]) -> None:
        """Thread-safe control (voice tool, preview keys); applied on the next frame."""
        self._requests.put(action)

    @property
    def status(self) -> Status:
        return self.machine.status(self.clock())

    def run(self, stop_event: threading.Event) -> None:
        owns_tracker = self.tracker is None
        self.tracker = self.tracker or HandTracker()
        if self.overlay:
            self.overlay.start()
        first = True
        try:
            for frame in self.frames:
                if stop_event.is_set() or self._stopping:
                    break
                if frame is None:
                    continue
                image = self.process(frame)
                if first:
                    first = False
                    if self.on_ready:
                        self.on_ready()
                if self.preview and not self._show_preview(image):
                    break
        finally:
            for command in self.machine.disarm(self.clock()):  # nunca deixa o botão do mouse preso
                if command.kind == "mouse_up":
                    self._dispatch(command, self.clock())
            self._emit("state", state="off")
            close = getattr(self.frames, "close", None)
            if callable(close):
                close()
            if owns_tracker and self.tracker is not None:
                self.tracker.close()
            if self.overlay:
                self.overlay.close()
            self._executor.shutdown(wait=True)
            if self.preview:
                import cv2

                cv2.destroyAllWindows()

    def process(self, frame: np.ndarray) -> np.ndarray:
        t = self.clock()
        if self._last_t is not None and t > self._last_t:
            self.fps = 0.9 * self.fps + 0.1 * (1.0 / (t - self._last_t)) if self.fps else 1.0 / (t - self._last_t)
        self._last_t = t
        self._apply_requests(t)
        image = _prepare(frame)
        self.hand = self.tracker.detect(image, t)
        commands = self.machine.step(t, self.hand)
        for command in commands:
            self._dispatch(command, t)
        self._refresh_overlay(t)
        if self.trace is not None:
            self._write_trace(t, commands)
        return image

    def _write_trace(self, t: float, commands: list[Command]) -> None:
        import json

        status = self.machine.status(t)
        row: dict[str, Any] = {"t": round(t, 3), "state": status.state.value, "pose": status.pose.value}
        if self.hand is not None:
            shape = classify(self.hand)
            row["raw"] = shape.pose.value
            row["center"] = [round(value, 3) for value in shape.center]
            row.update({key: round(value, 3) for key, value in shape.metrics.items()})
            row["points"] = np.round(self.hand.points, 3).tolist()
            if self.hand.world is not None:
                row["world"] = np.round(self.hand.world, 4).tolist()
        if commands:
            row["commands"] = [command.kind for command in commands if command.kind != "mouse_move"]
        print(json.dumps(row), file=self.trace, flush=True)

    # ── comandos ──

    def _apply_requests(self, t: float) -> None:
        while True:
            try:
                action = self._requests.get_nowait()
            except queue.Empty:
                return
            if action == "quit":
                self._stopping = True
                continue
            commands = {
                "arm": lambda: self.machine.arm(t),
                "disarm": lambda: self.machine.disarm(t),
                "mouse_on": lambda: self.machine.set_mouse(t, True),
                "mouse_off": lambda: self.machine.set_mouse(t, False),
            }[action]()
            for command in commands:
                self._dispatch(command, t)

    def _dispatch(self, command: Command, t: float) -> None:
        kind = command.kind
        try:
            if kind == "mouse_move" and command.point:
                self.actions.mouse_move(*command.point)
            elif kind in ("mouse_down", "mouse_up", "click"):
                getattr(self.actions, kind)()
            elif kind == "grab":
                self._grab(t)
            elif kind == "aim":
                label = None
                if command.direction and self._target is not None:
                    label = self.actions.aim(self._target, command.direction, command.vector)
                self._aim = (command.direction, label)
                self._emit("aim", direction=command.direction, target=label)
            elif kind == "cancel":
                self._target = None
                self._aim = (None, None)
                self._flash = ("Cancelado", "info", t + 1.2)
                self._emit("cancel")
            elif kind in ("throw", "maximize", "close"):
                target, self._target = self._target, None
                self._aim = (None, None)
                if target is None:
                    return
                args = (target, command.direction, command.vector) if kind == "throw" else (target,)
                self._submit(kind, getattr(self.actions, kind), *args, title=target.title)
            elif kind in ("minimize", "undo"):
                self._submit(kind, getattr(self.actions, kind))
            elif kind == "tab":
                self._submit(kind, self.actions.tab, command.step)
            elif kind in ("armed", "disarmed", "mouse_on", "mouse_off"):
                state = {"armed": "armed", "disarmed": "idle", "mouse_on": "mouse", "mouse_off": "armed"}[kind]
                if kind == "disarmed":
                    self._target = None
                logger.info("Gestos: %s", kind)
                self._emit("state", state=state)
        except Exception:
            logger.exception("Falha ao tratar o gesto '%s'.", kind)

    def _grab(self, t: float) -> None:
        target = self.actions.grab()
        if target is None:
            self.machine.abort(t)
            self._flash = ("Nenhuma janela em foco", "warn", t + FLASH_SECONDS)
            return
        self._target = target
        self._aim = (None, None)
        self._emit("grab", title=target.title, browser=target.browser)

    def _submit(self, name: str, func: Callable[..., str], *args: Any, title: str | None = None) -> None:
        self._flash = (f"{ACTION_LABELS[name]}…", "info", self.clock() + 5.0)

        def job() -> None:
            try:
                message, ok = func(*args), True
            except GestureActionError as exc:
                message, ok = str(exc), False
            except Exception:
                logger.exception("Falha na ação de gesto '%s'.", name)
                message, ok = "Algo deu errado nessa ação.", False
            self._flash = (message, "ok" if ok else "error", self.clock() + FLASH_SECONDS)
            logger.info("Gesto %s: %s", name, message)
            self._emit("action", action=name, ok=ok, message=message, title=title)

        self._executor.submit(job)

    def _emit(self, event: str, **data: Any) -> None:
        try:
            self.emit({"event": event, **data})
        except Exception:
            logger.debug("Falha ao emitir o evento de gesto '%s'.", event, exc_info=True)

    # ── overlay ──

    def view(self, t: float) -> OverlayView | None:
        """What the overlay should say right now (None hides it)."""
        status = self.machine.status(t)
        target = self._target
        if status.state == State.CLOSE and target is not None:
            what = "ABA" if target.browser else "JANELA"
            return OverlayView(f"FECHAR {what}? {target.title}", "segure o polegar para baixo · solte para cancelar", status.progress, "danger")
        if status.state == State.GRAB and target is not None:
            direction, label = self._aim
            if direction and label:
                return OverlayView(f"→ {label.upper()}", f"abra a mão para soltar · {target.title}", None, "armed")
            if direction:
                return OverlayView(f"Não há {describe_direction(direction)}", target.title, None, "warn")
            return OverlayView(f"SEGURANDO · {target.title}", HINT_GRAB, None, "info")
        flash = self._flash
        if flash and t < flash[2]:
            return OverlayView(flash[0], "", None, flash[1])
        if status.state == State.MOUSE:
            if status.charging == "mouse_off":
                return OverlayView("SAINDO DO MOUSE…", "mantenha a palma parada", status.progress, "info")
            return OverlayView("MOUSE NO AR" + (" · ARRASTANDO" if status.dragging else ""), HINT_MOUSE, None, "info")
        if status.state == State.ARMED:
            if status.charging == "mouse_on":
                return OverlayView("MOUSE NO AR…", "continue apontando", status.progress, "info")
            return OverlayView("GESTOS ATIVOS", HINT_ARMED, None, "armed")
        if status.charging == "arm" and (status.progress or 0) > 0.15:
            return OverlayView("ARMANDO GESTOS…", "mantenha a mão aberta parada", status.progress, "info")
        return None

    def _area(self, t: float) -> tuple[int, int, int, int] | None:
        monitor = None
        status = self.machine.status(t)
        if status.state in (State.GRAB, State.CLOSE) and self._target is not None:
            monitor = self._target.monitor
        else:
            if self._focus is None or t - self._focus[1] > FOCUS_CACHE_SECONDS:
                try:
                    probe = self.actions.cursor_monitor if status.state == State.MOUSE else self.actions.focus_monitor
                    self._focus = (probe(), t)
                except Exception:
                    self._focus = (None, t)
            monitor = self._focus[0]
        return tuple(monitor.work) if monitor is not None else None

    def _refresh_overlay(self, t: float) -> None:
        if self.overlay is None:
            return
        view = self.view(t)
        if view is not None and view.progress is not None:
            view = OverlayView(view.title, view.detail, round(view.progress * 50) / 50, view.tone)
        self.overlay.show(view, self._area(t) if view is not None else None)

    # ── preview ──

    def _show_preview(self, image: np.ndarray) -> bool:
        import cv2

        canvas = image.copy()
        draw_hand(canvas, self.hand)
        status = self.machine.status(self.clock())
        view = self.view(self.clock())
        lines = [
            f"estado: {status.state.value}   pose: {status.pose.value}   {self.fps:4.1f} fps",
            view.title if view else "mostre a mão aberta parada para armar",
        ]
        if self.hand is not None:
            shape = classify(self.hand)
            fingers = " ".join(f"{name[:3]}:{'E' if shape.extended[name] else ('d' if shape.folded[name] else '-')}" for name in shape.extended)
            lines.append(f"{fingers}  pinça:{shape.pinch:.2f}")
        for row, text in enumerate(lines):
            y = 24 + row * 22
            cv2.putText(canvas, _ascii(text), (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(canvas, _ascii(text), (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 230, 120), 1, cv2.LINE_AA)
        if status.progress is not None:
            width = canvas.shape[1] - 20
            cv2.rectangle(canvas, (10, canvas.shape[0] - 18), (10 + int(width * status.progress), canvas.shape[0] - 10), (0, 210, 255), -1)
        cv2.imshow(PREVIEW_TITLE, cv2.resize(canvas, None, fx=1.5, fy=1.5))
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27) or cv2.getWindowProperty(PREVIEW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
            return False
        if key == ord("a"):
            self.request("arm")
        elif key == ord("d"):
            self.request("disarm")
        elif key == ord("m"):
            self.request("mouse_off" if status.state == State.MOUSE else "mouse_on")
        return True


PREVIEW_TITLE = "Jarvis - gestos (q sai, a arma, d desarma, m mouse)"
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)  # fmt: skip


def _ascii(text: str) -> str:
    """OpenCV's Hershey fonts only draw ASCII."""
    import unicodedata

    text = text.replace("→", "->").replace("↓", "v").replace("·", "|").replace("…", "...")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def draw_hand(canvas: np.ndarray, hand: Hand | None) -> None:
    import cv2

    if hand is None:
        return
    height, width = canvas.shape[:2]
    points = [(int(x * width), int(y * height)) for x, y, _ in hand.points]
    for start, end in HAND_CONNECTIONS:
        cv2.line(canvas, points[start], points[end], (255, 200, 0), 2, cv2.LINE_AA)
    for index, point in enumerate(points):
        cv2.circle(canvas, point, 5 if index in (4, 8) else 3, (0, 255, 200), -1, cv2.LINE_AA)


# ───────────────────────── serviço (voz e Jarvis) ─────────────────────────


class GestureService:
    """One gesture engine per process, on a background thread, turned on/off by voice."""

    def __init__(
        self,
        frames_factory: Callable[[], tuple[Iterator[np.ndarray], str]] = default_frames,
        actions_factory: Callable[[], Any] = DesktopActions,
        overlay_factory: Callable[[], Overlay | None] = Overlay,
        tracker_factory: Callable[[], Any] = HandTracker,
    ) -> None:
        self.frames_factory = frames_factory
        self.actions_factory = actions_factory
        self.overlay_factory = overlay_factory
        self.tracker_factory = tracker_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._engine: GestureEngine | None = None
        self._error: str | None = None
        self._source = ""
        self._listeners: dict[str, Callable[[dict[str, Any]], None]] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_listener(self, name: str, listener: Callable[[dict[str, Any]], None] | None) -> None:
        if listener is None:
            self._listeners.pop(name, None)
        else:
            self._listeners[name] = listener

    def _emit(self, event: dict[str, Any]) -> None:
        for listener in list(self._listeners.values()):
            try:
                listener(event)
            except Exception:
                logger.debug("Falha num ouvinte de gestos.", exc_info=True)

    def start(self, mouse: bool = False, wait: float = 15.0) -> str:
        with self._lock:
            if self.running and self._engine is not None:
                if mouse:
                    self._engine.request("mouse_on")
                    return "Os gestos já estavam ligados; liguei o mouse no ar."
                self._engine.request("arm")
                return "Os gestos já estavam ligados (armados agora)."
            self._error = None
            self._stop = threading.Event()
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(mouse,), name="gestures", daemon=True)
            self._thread.start()
        self._ready.wait(wait)
        if self._error:
            return f"Não consegui ligar os gestos: {self._error}"
        if not self.running:
            return "Os gestos não ficaram ligados (a câmera fechou logo depois de abrir)."
        if self._engine is None or not self._ready.is_set():
            return "Estou ligando a câmera dos gestos; pode levar alguns segundos."
        mode = " com o mouse no ar" if mouse else ""
        return (
            f"Gestos ligados{mode} (câmera: {self._source}) e já armados. Punho pega a janela em foco; "
            "mova e abra a mão para jogá-la no monitor daquele lado. Sem uso, desarmam sozinhos; "
            "para rearmar, mão aberta parada por um segundo."
        )

    def _run(self, mouse: bool) -> None:
        try:
            tracker = self.tracker_factory()
            frames, self._source = self.frames_factory()
            engine = GestureEngine(
                frames,
                self.actions_factory(),
                tracker=tracker,
                overlay=self.overlay_factory(),
                emit=self._emit,
                armed=True,
                mouse=mouse,
                on_ready=self._ready.set,
            )
            self._engine = engine
            try:
                engine.run(self._stop)
            finally:
                close = getattr(tracker, "close", None)
                if callable(close):
                    close()
        except CameraError as exc:
            self._error = str(exc)
        except Exception as exc:
            logger.exception("O controle por gestos parou com erro.")
            self._error = f"{type(exc).__name__}: {exc}"
        finally:
            self._engine = None
            self._ready.set()

    def stop(self, wait: float = 5.0) -> str:
        with self._lock:
            if not self.running:
                return "Os gestos já estavam desligados."
            self._stop.set()
            thread = self._thread
        if thread:
            thread.join(wait)
        return "Gestos desligados; a webcam foi liberada." if not self.running else "Pedi para desligar os gestos."

    def set_mouse(self, on: bool) -> str:
        if not self.running or self._engine is None:
            return self.start(mouse=True) if on else "Os gestos estão desligados, então o mouse no ar também."
        self._engine.request("mouse_on" if on else "mouse_off")
        return "Mouse no ar ligado: o indicador move o cursor e a pinça clica." if on else "Mouse no ar desligado."

    def describe(self) -> str:
        engine = self._engine
        if not self.running or engine is None:
            reason = f" Último erro: {self._error}" if self._error else ""
            return f"Os gestos estão desligados.{reason}"
        status = engine.status
        states = {
            State.IDLE: "ligados, mas desarmados (mão aberta parada por um segundo arma)",
            State.ARMED: "ligados e armados",
            State.GRAB: "segurando uma janela",
            State.CLOSE: "contando para fechar uma janela",
            State.MOUSE: "no modo mouse no ar",
        }
        hand = "vendo sua mão" if status.hand else "sem mão no quadro"
        return f"Gestos {states[status.state]}; câmera: {self._source}, {hand}, {engine.fps:.0f} quadros/s."


SERVICE = GestureService()


def voice_action(action: str, service: GestureService | None = None) -> str:
    service = service or SERVICE
    if action == "on":
        return service.start()
    if action == "off":
        return service.stop()
    if action == "mouse_on":
        return service.set_mouse(True)
    if action == "mouse_off":
        return service.set_mouse(False)
    return service.describe()


_HUD_TASKS: set[Any] = set()


def attach_hud(loop: asyncio.AbstractEventLoop, service: GestureService | None = None) -> None:
    """Forward gesture events to the HUD (data channel) from the engine thread."""
    from hud import publish_hud_event

    service = service or SERVICE
    context = contextvars.copy_context()  # get_job_context() precisa do contexto do job

    def publish(event: dict[str, Any]) -> None:
        def schedule() -> None:
            task = asyncio.ensure_future(publish_hud_event("gesture", **event))
            _HUD_TASKS.add(task)
            task.add_done_callback(_HUD_TASKS.discard)
            if event.get("event") == "action":
                status = "done" if event.get("ok") else "error"
                log = asyncio.ensure_future(publish_hud_event("tool", name="gesture", status=status, detail=event.get("message")))
                _HUD_TASKS.add(log)
                log.add_done_callback(_HUD_TASKS.discard)

        if not loop.is_closed():
            loop.call_soon_threadsafe(schedule, context=context)

    service.set_listener("hud", publish)


def autostart_requested() -> bool:
    return os.environ.get(AUTOSTART_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


async def start_for_session(job_context: Any) -> str:
    """Start gestures with a voice session (python jarvis.py --gestures) and stop them with it."""
    attach_hud(asyncio.get_running_loop())
    result = await asyncio.to_thread(SERVICE.start)
    logger.info("Gestos com a sessão: %s", result)

    async def stop() -> None:
        await asyncio.to_thread(SERVICE.stop)

    job_context.add_shutdown_callback(stop)
    return result


def build_gesture_tools() -> list[Any]:
    from hud import tool_status

    registered: list[bool] = []

    @function_tool()
    async def gesture_control(
        context: RunContext,
        action: Literal["on", "off", "status", "mouse_on", "mouse_off"],
    ) -> str:
        """Turn on/off the hand-gesture control of windows through the webcam, or the air mouse.

        Only when the user asks ("liga os gestos", "desliga o controle por gestos", "liga o mouse
        no ar", "os gestos estão ligados?"). The gestures themselves are made by the user's hand
        in front of the camera, never by you. Report exactly what the result says (e.g. that the
        webcam is busy).

        Args:
            action: on (start the camera and arm the gestures), off (stop and free the webcam),
                status, mouse_on (index finger moves the cursor, pinch clicks) or mouse_off.
        """
        attach_hud(asyncio.get_running_loop())
        job = get_job_context(required=False)
        if job is not None and not registered:
            registered.append(True)

            async def stop() -> None:
                await asyncio.to_thread(SERVICE.stop)

            job.add_shutdown_callback(stop)
        await tool_status("gesture_control", "running", action)
        result = await asyncio.to_thread(voice_action, action)
        await tool_status("gesture_control", "done", action)
        logger.info("Gestos por voz: %s → %s", action, result)
        return result

    return [gesture_control]


# ───────────────────────── runner de desenvolvimento ─────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Controle de janelas por gestos (webcam + MediaPipe).")
    parser.add_argument("--preview", action="store_true", help="Mostra a webcam com os pontos da mão e o gesto.")
    parser.add_argument("--dry-run", action="store_true", help="Reconhece os gestos sem mexer em nenhuma janela.")
    parser.add_argument("--camera", type=int, default=None, help="Índice da webcam (padrão: a primeira colorida).")
    parser.add_argument("--mouse", action="store_true", help="Já começa no modo mouse no ar.")
    parser.add_argument("--no-overlay", action="store_true", help="Sem o aviso flutuante na tela.")
    parser.add_argument("--trace", type=Path, help="Grava os números de cada quadro (sem imagens) para calibrar.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    trace = args.trace.open("a", encoding="utf-8") if args.trace else None
    try:
        tracker = HandTracker()
        frames = webcam_frames(args.camera)
        engine = GestureEngine(
            frames,
            DryRunActions() if args.dry_run else DesktopActions(),
            tracker=tracker,
            overlay=None if args.no_overlay else Overlay(),
            emit=lambda event: logger.info("evento: %s", event),
            preview=args.preview,
            mouse=args.mouse,
            trace=trace,
        )
        print("Gestos rodando. Mão aberta parada por ~1 s arma; Ctrl+C (ou q no preview) encerra.")
        engine.run(threading.Event())
    except CameraError as exc:
        print(exc)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if trace is not None:
            trace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
