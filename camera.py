"""Webcam do Jarvis: um único dono (``CameraHub``) para todos que querem ver pela câmera.

O hub roda no processo do ``server.py`` (que o ``jarvis.py`` sobe) e é o ÚNICO a abrir a
webcam. Quem precisa de imagens pede a ele: o feed MJPEG do HUD, o snapshot que o agente
analisa (por HTTP, já que o worker do agente é outro processo) e o reconhecimento de gestos.

Privacidade: a câmera só liga quando alguém pede, desliga sozinha poucos segundos depois que
ninguém mais usa (a luz da webcam apaga), nunca abre com ``JARVIS_ENABLE_CAMERA`` desligado e
nada é gravado em disco. Os quadros só saem do computador quando o usuário pede ao Jarvis
para olhar (``look_at_camera``).

Na máquina do Gabriel a 'ASUS FHD webcam' abre pelo Media Foundation (MSMF) em ~1 s, a 30 fps
em 1280x720; o DirectShow leva ~2,5 s. A câmera infravermelha (Windows Hello) é sempre
recusada: ela não serve para ver o ambiente.
"""

from __future__ import annotations

import ctypes
import itertools
import logging
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import numpy as np

logger = logging.getLogger("jarvis-camera")

CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
CAPTURE_FPS = 30
FRAME_TIMEOUT_S = 5.0
OPEN_TIMEOUT_S = 8.0  # o primeiro quadro inclui abrir o dispositivo
LINGER_S = 3.0  # segura a câmera um instante após o último uso (snapshot → painel sem piscar)
MAX_READ_FAILURES = 30  # ~1 s sem imagem e a webcam é dada como perdida
IR_CAMERA = re.compile(r"\bIR\b|infra", re.IGNORECASE)
CAMERA_DISABLED = "A câmera está desativada. Defina JARVIS_ENABLE_CAMERA=true no .env."
CAMERA_TURNED_OFF = "A câmera foi desligada."


class CameraError(RuntimeError):
    """Câmera desativada, ausente, ocupada ou sem enviar imagens (mensagem em PT-BR)."""


class FrameSource(Protocol):
    """Dispositivo aberto. ``read`` bloqueia até o próximo quadro e devolve None se falhar."""

    name: str
    backend: str

    def read(self) -> np.ndarray | None: ...

    def close(self) -> None: ...


# ───────────────────────── dispositivos ─────────────────────────


def pick_camera(names: list[str], wanted: str | None = None) -> int:
    """Índice da webcam a usar: `wanted` é um índice ou parte do nome (JARVIS_CAMERA);
    sem ele, a primeira câmera que não seja infravermelha."""
    usable = [index for index, name in enumerate(names) if not IR_CAMERA.search(name)]
    found = ", ".join(f"'{name}'" for name in names) or "nenhuma"
    wanted = (wanted or "").strip()
    if wanted.isdigit():
        index = int(wanted)
        if not names or index in usable:
            return index
        if index < len(names):
            raise CameraError(f"A câmera {index} ('{names[index]}') é infravermelha e não serve para ver o ambiente.")
        raise CameraError(f"Não existe câmera {index}. Câmeras encontradas: {found}.")
    if wanted:
        matches = [index for index in usable if wanted.lower() in names[index].lower()]
        if not matches:
            raise CameraError(f"Não achei a câmera '{wanted}' (JARVIS_CAMERA). Câmeras encontradas: {found}.")
        return matches[0]
    if not usable:
        raise CameraError("Nenhuma webcam encontrada." if not names else f"Só achei câmeras infravermelhas: {found}.")
    return usable[0]


@contextmanager
def _com() -> Iterator[None]:
    ole32 = ctypes.WinDLL("ole32")
    result = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    try:
        yield
    finally:
        if result in (0, 1):  # S_OK / S_FALSE: este thread inicializou o COM
            ole32.CoUninitialize()


def _vcall(obj: Any, index: int, restype: Any, argtypes: tuple[Any, ...], *args: Any) -> Any:
    """Chama o método `index` da vtable de um objeto COM."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])(obj, *args)


def list_cameras() -> list[str]:
    """Nomes das câmeras de vídeo no Windows, na ordem dos índices do OpenCV com CAP_MSMF
    (os dois usam MFEnumDeviceSources)."""
    from ctypes import HRESULT, POINTER, byref, c_uint32, c_ulong, c_void_p, c_wchar_p

    from comtypes import GUID

    source_type = GUID("{c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3}")  # MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE
    video_capture = GUID("{8ac3587a-4ae7-42d8-99e0-0a6013eef90f}")  # ..._SOURCE_TYPE_VIDCAP_GUID
    friendly_name = GUID("{60d0e559-52f8-4fa2-bbce-acdb34a8ec01}")  # MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME
    mfplat, mf, ole32 = ctypes.WinDLL("mfplat"), ctypes.WinDLL("mf"), ctypes.WinDLL("ole32")
    for func in (mfplat.MFStartup, mfplat.MFCreateAttributes, mf.MFEnumDeviceSources):
        func.restype = HRESULT

    names: list[str] = []
    with _com():
        mfplat.MFStartup(0x00020070, 0)  # MF_VERSION
        attributes = c_void_p()
        devices = POINTER(c_void_p)()
        count = c_uint32()
        try:
            mfplat.MFCreateAttributes(byref(attributes), 1)
            _vcall(attributes, 24, HRESULT, (POINTER(GUID), POINTER(GUID)), byref(source_type), byref(video_capture))
            mf.MFEnumDeviceSources(attributes, byref(devices), byref(count))
            for index in range(count.value):
                activate = c_void_p(devices[index])
                text, length = c_wchar_p(), c_uint32()
                try:
                    _vcall(
                        activate, 13, HRESULT, (POINTER(GUID), POINTER(c_wchar_p), POINTER(c_uint32)),
                        byref(friendly_name), byref(text), byref(length),
                    )  # IMFAttributes::GetAllocatedString
                    names.append(text.value or f"Câmera {index}")
                    ole32.CoTaskMemFree(text)
                finally:
                    _vcall(activate, 2, c_ulong, ())  # Release
        finally:
            if devices:
                ole32.CoTaskMemFree(devices)
            if attributes:
                _vcall(attributes, 2, c_ulong, ())
            mfplat.MFShutdown()
    return names


class OpenCVSource:
    def __init__(self, capture: Any, name: str, backend: str) -> None:
        self._capture = capture
        self.name = name
        self.backend = backend

    def read(self) -> np.ndarray | None:
        ok, frame = self._capture.read()
        return frame if ok and frame is not None and frame.size else None

    def close(self) -> None:
        self._capture.release()


def open_camera(wanted: str | None = None) -> OpenCVSource:
    """Abre a webcam escolhida (nunca a infravermelha) em 1280x720@30 e confere um quadro."""
    import cv2

    if sys.platform == "win32":
        try:
            names = list_cameras()
        except OSError as exc:
            raise CameraError("Não consegui listar as câmeras do Windows.") from exc
        index = pick_camera(names, wanted)
        name = names[index] if index < len(names) else f"Câmera {index}"
        api = cv2.CAP_MSMF
    else:
        index = int(wanted) if wanted and wanted.strip().isdigit() else 0
        name, api = f"Câmera {index}", cv2.CAP_ANY

    capture = cv2.VideoCapture(index, api)
    if capture.isOpened():
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        capture.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)
        source = OpenCVSource(capture, name, capture.getBackendName())
        if source.read() is not None:
            logger.info("Webcam aberta: %s (%s).", name, source.backend)
            return source
    capture.release()
    raise CameraError(
        f"Não consegui abrir a webcam '{name}'. Ela pode estar em uso por outro programa "
        "(Teams, Zoom, app Câmera do Windows)."
    )


def _default_source() -> FrameSource:
    from settings import load_settings

    settings = load_settings()
    if not settings.camera_enabled:
        raise CameraError(CAMERA_DISABLED)
    return open_camera(settings.camera_device)


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise CameraError("Não consegui codificar a imagem da câmera.")
    return buffer.tobytes()


# ───────────────────────── hub ─────────────────────────


class CameraHub:
    """Dono único da webcam, com uma thread de captura e vários consumidores.

    Cada uso tem um ticket: ``start()`` liga a câmera (se ainda não estiver ligada) e devolve
    o ticket; ``stop(ticket)`` o devolve. Sem tickets, a câmera desliga sozinha depois de
    ``linger`` segundos. ``off()`` desliga na hora para todo mundo (pedido do usuário).

    Contrato de ``frames()`` (consumido pelo reconhecimento de gestos; mantenha estável)::

        for frame in get_hub().frames():   # frame: np.ndarray BGR uint8 (720, 1280, 3)
            ...

    - Liga a câmera no primeiro ``next()`` e solta o ticket quando o iterador é fechado
      (``.close()``, ``break`` num ``for`` ou coleta de lixo).
    - Cada ``next()`` bloqueia até sair um quadro mais novo que o último que ESTE iterador
      entregou e devolve o mais recente: consumidor lento pula quadros, nunca acumula fila.
      Vários iteradores ao mesmo tempo recebem todos os quadros, sem um roubar do outro.
    - O quadro é compartilhado e somente leitura; copie (``frame.copy()``) para desenhar.
    - Termina normalmente (StopIteration) quando o usuário desliga a câmera (``off()``);
      não religue sozinho.
    - Levanta ``CameraError`` se a câmera estiver desativada no .env, não abrir (em uso,
      ausente) ou passar ``timeout`` segundos sem quadro novo (o primeiro tem até
      ``OPEN_TIMEOUT_S``).
    """

    def __init__(
        self,
        source_factory: Callable[[], FrameSource] = _default_source,
        *,
        linger: float = LINGER_S,
    ) -> None:
        self._factory = source_factory
        self._linger = linger
        self._cond = threading.Condition()
        self._tickets = itertools.count(1)
        self._holders: set[int] = set()
        self._pinned: int | None = None
        self._idle_since = 0.0
        # A geração muda a cada partida e a cada parada: uma thread de captura antiga nunca
        # mexe no estado de uma nova.
        self._generation = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame: np.ndarray | None = None
        self._frame_ts = 0.0
        self._seq = 0
        self._recent: deque[float] = deque(maxlen=CAPTURE_FPS)  # horários dos últimos quadros, para o FPS
        self._error: str | None = None
        self._device: str | None = None
        self._backend: str | None = None
        self._started_at: float | None = None
        self._jpeg_cache: tuple[int, int, bytes] | None = None

    # ── uso ──

    def start(self) -> int:
        """Pega um ticket, ligando a câmera se preciso. Devolva com ``stop(ticket)``."""
        with self._cond:
            ticket = next(self._tickets)
            self._holders.add(ticket)
            if not self._running:
                self._launch()
            return ticket

    def stop(self, ticket: int) -> None:
        with self._cond:
            if ticket not in self._holders:
                return
            self._holders.discard(ticket)
            if ticket == self._pinned:
                self._pinned = None
            if not self._holders:
                self._idle_since = time.monotonic()
            self._cond.notify_all()

    @contextmanager
    def session(self) -> Iterator[int]:
        ticket = self.start()
        try:
            yield ticket
        finally:
            self.stop(ticket)

    def off(self, wait: float = 3.0) -> None:
        """Desliga na hora para todos: encerra os ``frames()`` e o feed do HUD."""
        with self._cond:
            self._holders.clear()
            self._pinned = None
            thread = self._thread
            if self._running:
                self._retire(None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(wait)

    def pin(self) -> None:
        """Mantém a câmera ligada até ``off()`` (POST /api/camera/on)."""
        with self._cond:
            if self._pinned is not None and self._running:
                return
            ticket = self.start()
        try:
            if self.wait_frame(ticket, 0, OPEN_TIMEOUT_S) is None:
                raise CameraError(CAMERA_TURNED_OFF)
        except CameraError:
            self.stop(ticket)
            raise
        with self._cond:
            if self._pinned is not None:
                self.stop(self._pinned)
            self._pinned = ticket

    # ── quadros ──

    def wait_frame(self, ticket: int, after_seq: int, timeout: float = FRAME_TIMEOUT_S) -> tuple[np.ndarray, float, int] | None:
        """Espera um quadro com número maior que `after_seq` e devolve (quadro, epoch, número).

        None quando o ticket foi encerrado por ``off()``. Levanta CameraError em falha ou timeout.
        """
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if ticket not in self._holders:
                    return None
                if self._frame is not None and self._seq > after_seq:
                    return self._frame, self._frame_ts, self._seq
                if not self._running:
                    if self._error:
                        raise CameraError(self._error)
                    self._launch()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CameraError(f"A webcam não enviou imagens em {timeout:.0f} s.")
                self._cond.wait(remaining)

    def frames(self, timeout: float = FRAME_TIMEOUT_S) -> Iterator[np.ndarray]:
        """Quadros BGR mais recentes, um por ``next()``. Veja o contrato no docstring da classe."""
        ticket = self.start()
        try:
            seq = 0
            while True:
                got = self.wait_frame(ticket, seq, max(timeout, OPEN_TIMEOUT_S) if seq == 0 else timeout)
                if got is None:
                    return
                frame, _, seq = got
                yield frame
        finally:
            self.stop(ticket)

    def latest(self) -> tuple[np.ndarray, float] | None:
        """Último quadro e seu horário (epoch), sem ligar a câmera. None com ela desligada."""
        with self._cond:
            if not self._running or self._frame is None:
                return None
            return self._frame, self._frame_ts

    def snapshot_jpeg(self, quality: int = 85, timeout: float = OPEN_TIMEOUT_S) -> bytes:
        """Liga a câmera se preciso e devolve um JPEG de um quadro capturado depois do pedido."""
        with self.session() as ticket:
            with self._cond:
                after = self._seq
            got = self.wait_frame(ticket, after, timeout)
            if got is None:
                raise CameraError(CAMERA_TURNED_OFF)
            return encode_jpeg(got[0], quality)

    def jpeg_of(self, frame: np.ndarray, seq: int, quality: int = 70) -> bytes:
        """JPEG de um quadro do feed, codificado uma vez só para todos os espectadores."""
        cached = self._jpeg_cache
        if cached is not None and cached[0] == seq and cached[1] == quality:
            return cached[2]
        data = encode_jpeg(frame, quality)
        self._jpeg_cache = (seq, quality, data)
        return data

    def next_jpeg(self, ticket: int, after_seq: int, quality: int = 70, timeout: float = FRAME_TIMEOUT_S) -> tuple[bytes, int] | None:
        """Próximo quadro já em JPEG (para o feed MJPEG). None quando a câmera foi desligada."""
        got = self.wait_frame(ticket, after_seq, timeout)
        if got is None:
            return None
        frame, _, seq = got
        return self.jpeg_of(frame, seq, quality), seq

    def state(self) -> dict[str, Any]:
        with self._cond:
            frame = self._frame if self._running else None
            return {
                "active": self._running,
                "streaming": frame is not None,
                "users": len(self._holders),
                "pinned": self._pinned is not None,
                "device": self._device,
                "backend": self._backend,
                "width": int(frame.shape[1]) if frame is not None else None,
                "height": int(frame.shape[0]) if frame is not None else None,
                "fps": self._measured_fps() if self._running else 0.0,
                "since": self._started_at if self._running else None,
                "error": self._error,
            }

    # ── captura ──

    def _measured_fps(self) -> float:
        if len(self._recent) < 2 or self._recent[-1] <= self._recent[0]:
            return 0.0
        return round((len(self._recent) - 1) / (self._recent[-1] - self._recent[0]), 1)

    def _launch(self) -> None:
        """Sobe uma nova thread de captura (com o lock adquirido)."""
        previous = self._thread
        self._generation += 1
        self._running = True
        self._error = None
        self._frame = None
        self._recent.clear()
        self._device = self._backend = None
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._capture, args=(self._generation, previous), name="jarvis-camera", daemon=True
        )
        self._thread.start()

    def _retire(self, error: str | None) -> None:
        """Marca a câmera como desligada (com o lock adquirido)."""
        self._generation += 1
        self._running = False
        self._error = error
        self._frame = None
        self._jpeg_cache = None
        if error and self._pinned is not None:
            self._holders.discard(self._pinned)
            self._pinned = None
        self._cond.notify_all()

    def _retire_if_current(self, generation: int, error: str | None) -> None:
        with self._cond:
            if generation == self._generation:
                self._retire(error)

    def _capture(self, generation: int, previous: threading.Thread | None) -> None:
        if previous is not None:
            previous.join(5.0)  # o dispositivo precisa ser solto antes de reabrir
        source: FrameSource | None = None
        try:
            with self._cond:
                if generation != self._generation:
                    return
            source = self._factory()
            with self._cond:
                if generation != self._generation:
                    return
                self._device, self._backend = source.name, source.backend
            self._pump(source, generation)
        except CameraError as exc:
            logger.warning("Câmera: %s", exc)
            self._retire_if_current(generation, str(exc))
        except Exception:
            logger.exception("Falha na captura da webcam.")
            self._retire_if_current(generation, "A webcam falhou durante a captura.")
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception:
                    logger.debug("Falha ao fechar a webcam.", exc_info=True)

    def _pump(self, source: FrameSource, generation: int) -> None:
        failures = 0
        while True:
            with self._cond:
                if generation != self._generation:
                    return
                if not self._holders and time.monotonic() - self._idle_since >= self._linger:
                    self._retire(None)
                    return
            frame = source.read()
            if frame is None:
                failures += 1
                if failures >= MAX_READ_FAILURES:
                    raise CameraError("A webcam parou de enviar imagens.")
                time.sleep(1 / CAPTURE_FPS)
                continue
            failures = 0
            frame.setflags(write=False)
            now = time.time()
            with self._cond:
                if generation != self._generation:
                    return
                self._recent.append(now)
                self._frame, self._frame_ts = frame, now
                self._seq += 1
                self._cond.notify_all()


_HUB: CameraHub | None = None
_HUB_LOCK = threading.Lock()


def get_hub() -> CameraHub:
    """O hub da webcam deste processo (o do server.py)."""
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = CameraHub()
        return _HUB


def shutdown() -> None:
    """Desliga a webcam ao encerrar o servidor."""
    if _HUB is not None:
        _HUB.off()
