"""Presença (PRS-25): o Jarvis percebe quando o Gabriel chega e quando sai da frente do PC.

Uso:
    python presence.py --enroll   # cadastra o seu rosto (opcional) para o Jarvis saber que é você
    python presence.py --test     # mostra no terminal o que a presença está vendo (2 vezes por segundo)
    python presence.py --forget   # apaga o cadastro do rosto

Com ``JARVIS_PRESENCE=true`` o servidor do HUD (``server.py``) liga o ``PresenceService`` junto
com ele. O serviço pede quadros ao hub da webcam (``camera.py``, o único dono da câmera, que
os divide com o feed do HUD e os gestos), olha ~2 vezes por segundo se há um rosto e alimenta
a ``PresenceMachine``:

- chegou (rosto visto por ``arrive_s`` seguidos) depois de pelo menos ``welcome_s`` fora: o
  link abre pela mesma via da palavra de ativação (``wake_hub.py``) e o agente diz "Bem-vindo
  de volta, senhor", resumindo o que aconteceu enquanto ele estava fora (timers que acabaram,
  mídia pausada, alguém desconhecido na frente do PC...);
- saiu (nem rosto nem teclado/mouse por ``leave_s``): o painel Sistema mostra "Ausente há...";
- fora por mais de N minutos (``JARVIS_PRESENCE_AWAY_MINUTES``): pausa a mídia que estiver
  tocando e, com ``JARVIS_PRESENCE_LOCK=true`` (ou "pode bloquear quando eu sair"), bloqueia o PC.

Privacidade: os quadros ficam só na memória e são descartados logo depois da detecção; nada
de imagem é gravado nem enviado. O cadastro do rosto guarda só embeddings (vetores de 128
números do SFace, calculados neste PC), em ``presenca_rosto.json`` (fora do git).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
from livekit.agents import RunContext, function_tool

from camera import CameraError

logger = logging.getLogger("jarvis-presence")

ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "presenca_rosto.json"
MODELS = ROOT / ".cache" / "models"
DETECTOR_MODEL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/"
    "blaze_face_short_range.tflite",
    "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f",
    MODELS / "blaze_face_short_range.tflite",
)
LANDMARKER_MODEL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    MODELS / "face_landmarker.task",
)
SFACE_MODEL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/"
    "face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    MODELS / "face_recognition_sface_2021dec.onnx",
)
SAMPLE_INTERVAL_S = 0.5  # ~2 detecções por segundo: pouca CPU e chegada percebida em ~2 s
DETECT_WIDTH = 480  # a detecção roda numa cópia reduzida do quadro
RETRY_S = 15.0  # câmera ocupada ou falhando: tenta de novo depois disso
INPUT_GRACE_S = 20.0  # teclado/mouse usados há menos que isso = tem alguém no PC
WELCOME_TTL_S = 120.0  # boas-vindas entregues e não usadas por uma conversa nesse tempo caducam
WELCOME_WAIT_S = 15 * 60.0  # chegou com o PC bloqueado: espera o desbloqueio até isso
STRANGER_NOTE_S = 5 * 60.0  # no máximo uma anotação de "alguém desconhecido" a cada 5 min
JOURNAL_MAX = 60
JOURNAL_KEEP_S = 24 * 3600.0
MAX_NOTE = 200
CAMERA_OFF = "A câmera foi desligada; diga 'liga a presença' para voltar a observar."
NEEDS_CAMERA = "A presença usa a webcam: defina JARVIS_ENABLE_CAMERA=true no .env."


# ───────────────────────── máquina de estados ─────────────────────────


class Presence(str, Enum):
    UNKNOWN = "unknown"
    PRESENT = "present"
    AWAY = "away"


@dataclass(frozen=True, slots=True)
class Tuning:
    arrive_s: float = 1.5  # rosto visto esse tempo seguido = chegou (um vulto passando não conta)
    gap_s: float = 1.2  # falhas curtas do detector não zeram a contagem da chegada
    leave_s: float = 20.0  # sem rosto e sem teclado/mouse esse tempo = saiu (olhar o monitor do lado não conta)
    away_s: float = 300.0  # fora esse tempo = pausa a mídia e (se ligado) bloqueia
    welcome_s: float = 120.0  # só dá boas-vindas depois de pelo menos esse tempo fora


@dataclass(frozen=True, slots=True)
class PresenceEvent:
    kind: Literal["arrived", "left", "away_long"]
    at: float
    # arrived: quanto tempo ficou fora (None na primeira vez que o Jarvis o vê); away_long: idem até agora.
    away_s: float | None = None


class PresenceMachine:
    """Chegou/saiu com histerese. Pura: recebe o que foi visto e o horário, devolve eventos.

    - Chegar exige o rosto por ``arrive_s`` seguidos (com tolerância ``gap_s`` a falhas).
    - Ficar exige rosto OU teclado/mouse: com alguém digitando, um rosto de perfil não "sai".
    - Sair exige ``leave_s`` sem nada; o horário da saída é o da última vez que foi visto.
    - Teclado/mouse sozinhos não fazem chegar (com o reconhecimento ligado, um estranho
      digitando não ganha "bem-vindo de volta"), exceto no início, quando ainda não se sabe nada.
    """

    def __init__(self, tuning: Tuning, now: float) -> None:
        self.tuning = tuning
        self.state = Presence.UNKNOWN
        self.since = now  # PRESENT: horário da chegada; AWAY: horário da saída
        self._streak_start: float | None = None
        self._last_face: float | None = None
        self._last_presence = now
        self._away_fired = False

    def observe(self, face: bool, active: bool, now: float) -> list[PresenceEvent]:
        tuning = self.tuning
        events: list[PresenceEvent] = []
        if face:
            if self._streak_start is None or self._last_face is None or now - self._last_face > tuning.gap_s:
                self._streak_start = now
            self._last_face = now
        elif self._last_face is not None and now - self._last_face > tuning.gap_s:
            self._streak_start = None
        if face or (active and self.state is not Presence.AWAY):
            self._last_presence = now

        arrived = face and self._streak_start is not None and now - self._streak_start >= tuning.arrive_s
        if self.state is Presence.UNKNOWN and (arrived or active):
            self.state, self.since = Presence.PRESENT, self._streak_start if arrived else now
            events.append(PresenceEvent("arrived", self.since))
        elif self.state is Presence.AWAY and arrived:
            start = self._streak_start if self._streak_start is not None else now
            away = max(0.0, start - self.since)
            self.state, self.since = Presence.PRESENT, start
            events.append(PresenceEvent("arrived", start, away))
        elif self.state is not Presence.AWAY and now - self._last_presence >= tuning.leave_s:
            self.state, self.since = Presence.AWAY, self._last_presence
            self._away_fired = False
            events.append(PresenceEvent("left", self.since))

        if self.state is Presence.AWAY and not self._away_fired and now - self.since >= tuning.away_s:
            self._away_fired = True
            events.append(PresenceEvent("away_long", now, now - self.since))
        return events


# ───────────────────────── diário do tempo fora ─────────────────────────


@dataclass(frozen=True, slots=True)
class Note:
    at: float
    text: str


class Journal:
    """O que aconteceu, com horário: o resumo das boas-vindas pega o que caiu no tempo fora.

    Notas podem ter horário no futuro: o fim de um timer é anotado quando ele é criado, assim
    entra no resumo mesmo se a conversa (e o processo do agente) já tiver acabado.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._notes: list[Note] = []

    def add(self, text: str, at: float | None = None) -> Note:
        note = Note(self._clock() if at is None else float(at), " ".join(text.split())[:MAX_NOTE])
        with self._lock:
            now = self._clock()
            self._notes = [item for item in self._notes if item.at > now - JOURNAL_KEEP_S]
            self._notes.append(note)
            self._notes.sort(key=lambda item: item.at)
            del self._notes[:-JOURNAL_MAX]
        return note

    def between(self, start: float, end: float) -> list[Note]:
        with self._lock:
            return [note for note in self._notes if start <= note.at <= end]


def _clock_text(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch).strftime("%H:%M")


def human_minutes(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    if minutes < 1:
        return "menos de um minuto"
    if minutes < 60:
        return "1 minuto" if minutes == 1 else f"{minutes} minutos"
    hours, rest = divmod(minutes, 60)
    text = "1 hora" if hours == 1 else f"{hours} horas"
    return f"{text} e {rest} min" if rest else text


def build_welcome_instruction(away_s: float, notes: Iterable[str]) -> str:
    """Instrução da primeira fala da conversa aberta pela presença."""
    items = [item for item in notes if item]
    if items:
        happened = "Enquanto ele estava fora: " + "; ".join(items) + "."
        summary = "Depois resuma isso em no máximo duas frases curtas, sem inventar nada além da lista."
    else:
        happened = "Nada foi registrado enquanto ele estava fora."
        summary = "Não invente novidades: só a saudação e pergunte, em poucas palavras, se precisa de algo."
    return (
        "O usuário acabou de voltar para a frente do computador (a webcam o viu chegar) depois de "
        f"{human_minutes(away_s)} fora. Comece dizendo exatamente 'Bem-vindo de volta, senhor.' "
        f"{happened} {summary} Fale em português do Brasil."
    )


# ───────────────────────── reconhecimento do dono ─────────────────────────

# Embeddings de rosto locais: o MediaPipe acha o rosto e os pontos (olhos, nariz, cantos da
# boca), o rosto é alinhado no molde 112x112 do ArcFace e o SFace (OpenCV, já vem no
# opencv-contrib) gera um vetor de 128 números. Mesma pessoa ≈ 0,6-1,0 de similaridade;
# outra pessoa ≈ 0-0,3.
ARCFACE_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)
# Pontos da malha do Face Landmarker: olho à esquerda da imagem, olho à direita, ponta do
# nariz e cantos da boca (na ordem do molde).
EYE_LEFT, EYE_RIGHT, NOSE_TIP, MOUTH_LEFT, MOUTH_RIGHT = (33, 133), (362, 263), 1, 61, 291
MATCH_THRESHOLD = 0.363  # limite de similaridade do cosseno recomendado para o SFace
ENROLL_SAMPLES = 30
MAX_EMBEDDINGS = 30


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).ravel()
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-9:
        raise ValueError("Embedding vazio.")
    return vector / norm


@dataclass(frozen=True, slots=True)
class OwnerProfile:
    """Embeddings do rosto do dono (sem imagem). Serve para não dar boas-vindas a outra pessoa
    e anotar quem apareceu; não é uma trava de segurança (o bloqueio do Windows é)."""

    embeddings: np.ndarray  # (N, 128), cada linha com norma 1
    threshold: float = MATCH_THRESHOLD

    def similarity(self, embedding: np.ndarray) -> float:
        return float(np.max(self.embeddings @ _unit(embedding)))

    def matches(self, embedding: np.ndarray) -> bool:
        return self.similarity(embedding) >= self.threshold

    @classmethod
    def from_samples(cls, samples: list[np.ndarray], threshold: float = MATCH_THRESHOLD) -> OwnerProfile:
        if len(samples) < 5:
            raise ValueError("Poucas amostras do rosto.")
        vectors = np.stack([_unit(sample) for sample in samples])
        mean = _unit(vectors.mean(axis=0))
        if float(np.median(vectors @ mean)) < 0.5:
            raise ValueError("As amostras não parecem ser da mesma pessoa (havia mais alguém na frente da câmera?).")
        step = max(1, len(vectors) // MAX_EMBEDDINGS)
        return cls(embeddings=vectors[::step][:MAX_EMBEDDINGS], threshold=threshold)

    def save(self, path: Path = PROFILE_PATH) -> None:
        data = {
            "version": 2,
            "model": "sface-2021dec",
            "created": dt.datetime.now().isoformat(timespec="seconds"),
            "threshold": self.threshold,
            "embeddings": np.round(self.embeddings, 5).tolist(),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> OwnerProfile | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            embeddings = np.asarray(data["embeddings"], dtype=np.float32)
            threshold = float(data.get("threshold", MATCH_THRESHOLD))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Cadastro do rosto ilegível em %s; refaça com python presence.py --enroll.", path.name)
            return None
        if data.get("model") != "sface-2021dec" or embeddings.ndim != 2 or embeddings.shape[1] != 128:
            logger.warning("Cadastro do rosto de outra versão; refaça com python presence.py --enroll.")
            return None
        return cls(embeddings=embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True), threshold=threshold)


# ───────────────────────── sensor (MediaPipe + SFace) ─────────────────────────


@dataclass(frozen=True, slots=True)
class Sighting:
    faces: int = 0
    # Com o rosto cadastrado: algum rosto é o do dono? None sem cadastro (qualquer rosto vale).
    owner: bool | None = None
    similarity: float | None = None

    @property
    def present(self) -> bool:
        return self.owner if self.owner is not None else self.faces > 0


class Sensor(Protocol):
    recognizes: bool

    def look(self, frame: np.ndarray) -> Sighting: ...

    def close(self) -> None: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model(model: tuple[str, str, Path]) -> Path:
    """Baixa um modelo uma vez (.cache/, fora do git) e confere o hash."""
    url, sha256, path = model
    if path.exists() and _sha256(path) == sha256:
        return path
    import requests

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    logger.info("Baixando o modelo %s...", path.name)
    with requests.get(url, stream=True, timeout=30) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(1 << 16):
                handle.write(chunk)
    if _sha256(partial) != sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"O modelo {path.name} baixado não confere com o hash esperado; nada foi usado.")
    partial.replace(path)
    return path


def _small(frame: np.ndarray, square: bool = False) -> np.ndarray:
    """Cópia reduzida em RGB (o quadro do hub é compartilhado e somente leitura).

    ``square`` recorta o centro: o detector de curta distância enxerga um quadrado de 128 px, e
    num quadro 16:9 inteiro o rosto de quem está sentado ao notebook fica pequeno demais.
    """
    import cv2

    height, width = frame.shape[:2]
    if square and width > height:
        left = (width - height) // 2
        frame = frame[:, left : left + height]
        height, width = frame.shape[:2]
    if width > DETECT_WIDTH:
        frame = cv2.resize(frame, (DETECT_WIDTH, int(height * DETECT_WIDTH / width)), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


class FaceSensor:
    """MediaPipe Face Detector (BlazeFace, curta distância) em todo quadro e, com rosto
    cadastrado, Face Landmarker + SFace para conferir se é o dono (só quando há rosto)."""

    def __init__(self, profile: OwnerProfile | None = None, *, embeddings: bool | None = None) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        self.profile = profile
        self.recognizes = profile is not None
        self._detector = vision.FaceDetector.create_from_options(
            vision.FaceDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(ensure_model(DETECTOR_MODEL))),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=0.5,
            )
        )
        self._landmarker = None
        self._recognizer = None
        if embeddings if embeddings is not None else profile is not None:
            import cv2

            self._landmarker = vision.FaceLandmarker.create_from_options(
                vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(ensure_model(LANDMARKER_MODEL))),
                    running_mode=vision.RunningMode.IMAGE,
                    num_faces=2,
                    min_face_detection_confidence=0.5,
                )
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(ensure_model(SFACE_MODEL)), "")

    def _count(self, rgb: np.ndarray) -> int:
        result = self._detector.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        return len(result.detections or [])

    def embeddings(self, rgb: np.ndarray) -> list[np.ndarray]:
        """Um embedding (norma 1) por rosto da imagem RGB."""
        if self._landmarker is None or self._recognizer is None:
            return []
        import cv2

        height, width = rgb.shape[:2]
        result = self._landmarker.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb))
        bgr = None
        found = []
        for face in result.face_landmarks or []:
            def point(index: int) -> np.ndarray:
                return np.array([face[index].x * width, face[index].y * height])

            points = np.array(
                [
                    (point(EYE_LEFT[0]) + point(EYE_LEFT[1])) / 2,
                    (point(EYE_RIGHT[0]) + point(EYE_RIGHT[1])) / 2,
                    point(NOSE_TIP),
                    point(MOUTH_LEFT),
                    point(MOUTH_RIGHT),
                ],
                dtype=np.float32,
            )
            matrix, _ = cv2.estimateAffinePartial2D(points, ARCFACE_TEMPLATE)
            if matrix is None:
                continue
            if bgr is None:
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            aligned = cv2.warpAffine(bgr, matrix, (112, 112))
            try:
                found.append(_unit(self._recognizer.feature(aligned)))
            except ValueError:
                continue
        return found

    def look(self, frame: np.ndarray) -> Sighting:
        # Primeiro o centro (quem está sentado ao PC); sem rosto ali, o quadro inteiro.
        rgb = _small(frame, square=True)
        faces = self._count(rgb)
        if not faces:
            rgb = _small(frame)
            faces = self._count(rgb)
        if not faces or self.profile is None:
            return Sighting(faces=faces, owner=None if self.profile is None else False)
        scores = [self.profile.similarity(embedding) for embedding in self.embeddings(rgb)]
        if not scores:
            return Sighting(faces=faces, owner=False)
        best = max(scores)
        return Sighting(faces=faces, owner=best >= self.profile.threshold, similarity=best)

    def close(self) -> None:
        for task in (self._detector, self._landmarker):
            if task is not None:
                try:
                    task.close()
                except Exception:
                    logger.debug("Falha ao fechar o MediaPipe.", exc_info=True)


def default_sensor() -> FaceSensor:
    return FaceSensor(OwnerProfile.load())


# ───────────────────────── sistema (Windows) ─────────────────────────


class System(Protocol):
    def idle_seconds(self) -> float | None: ...

    def locked(self) -> bool: ...

    def pause_media(self) -> bool: ...

    def lock(self) -> None: ...


class NullSystem:
    """Fora do Windows (desenvolvimento): sem teclado/mouse, mídia ou bloqueio."""

    def idle_seconds(self) -> float | None:
        return None

    def locked(self) -> bool:
        return False

    def pause_media(self) -> bool:
        return False

    def lock(self) -> None:
        raise RuntimeError("Bloquear a tela só funciona no Windows.")


class WindowsSystem:
    """Teclado/mouse ociosos, tela bloqueada, mídia tocando e bloqueio, pelas APIs do Windows."""

    PEAK_FLOOR = 0.01  # nível de áudio que conta como "tocando"
    PEAK_SAMPLES = 6

    def idle_seconds(self) -> float | None:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def locked(self) -> bool:
        """Com a tela bloqueada a área de trabalho de entrada é a do Winlogon: não dá para trocar para ela."""
        import ctypes

        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = ctypes.c_void_p
        desktop = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desktop:
            return True
        try:
            return not user32.SwitchDesktop(ctypes.c_void_p(desktop))
        finally:
            user32.CloseDesktop(ctypes.c_void_p(desktop))

    @staticmethod
    def _peak_once() -> float:
        """Maior nível de áudio entre os apps agora (os objetos COM são soltos ao sair daqui)."""
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

        peak = 0.0
        for session in AudioUtilities.GetAllSessions():
            if session.Process is not None and session.Process.pid == os.getpid():
                continue
            meter = session._ctl.QueryInterface(IAudioMeterInformation)
            peak = max(peak, float(meter.GetPeakValue()))
        return peak

    def _audio_peak(self) -> float:
        """Uma música tem pausas: olha algumas vezes em ~1 s."""
        import comtypes

        comtypes.CoInitialize()
        try:
            peak = 0.0
            for _ in range(self.PEAK_SAMPLES):
                peak = max(peak, self._peak_once())
                if peak >= self.PEAK_FLOOR:
                    break
                time.sleep(0.2)
            return peak
        finally:
            comtypes.CoUninitialize()

    def pause_media(self) -> bool:
        """Pausa só se algo estiver tocando: a tecla de mídia alterna, e sem som ela daria play."""
        if self._audio_peak() < self.PEAK_FLOOR:
            return False
        from pc_control import press_media_key

        press_media_key("play_pause")
        return True

    def lock(self) -> None:
        from pc_control import lock_workstation

        lock_workstation()


def default_system() -> System:
    return WindowsSystem() if sys.platform == "win32" else NullSystem()


def hub_frames() -> Iterator[np.ndarray]:
    from camera import get_hub

    return get_hub().frames()


# ───────────────────────── serviço ─────────────────────────


@dataclass(slots=True)
class Welcome:
    away_s: float
    notes: list[str]
    at: float
    delivered_at: float | None = None


@dataclass(slots=True)
class _Status:
    running: bool = False
    error: str | None = None
    camera_off: bool = False
    faces: int = 0
    owner: bool | None = None
    stranger_noted_at: float = float("-inf")
    rates: deque[float] = field(default_factory=lambda: deque(maxlen=8))


class PresenceService:
    """Uma thread por processo (a do servidor do HUD) que observa a webcam e age na chegada/saída."""

    def __init__(
        self,
        *,
        away_minutes: float = 5,
        lock: bool = False,
        frames_factory: Callable[[], Iterator[np.ndarray]] = hub_frames,
        sensor_factory: Callable[[], Sensor] = default_sensor,
        system: System | None = None,
        clock: Callable[[], float] = time.time,
        interval: float = SAMPLE_INTERVAL_S,
        retry_s: float = RETRY_S,
        tuning: Tuning | None = None,
    ) -> None:
        self.tuning = tuning or Tuning(away_s=away_minutes * 60)
        self.lock_on_leave = lock
        self.frames_factory = frames_factory
        self.sensor_factory = sensor_factory
        self.system = system or default_system()
        self.clock = clock
        self.interval = interval
        self.retry_s = retry_s
        self.journal = Journal(clock)
        # Chamado (na thread da presença) quando as boas-vindas devem abrir o link.
        self.on_welcome: Callable[[], None] | None = None
        self.machine = PresenceMachine(self.tuning, clock())
        self._welcome: Welcome | None = None
        self._status = _Status()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recognizes = False

    # ── controle ──

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        with self._lock:
            if self.running:
                return "A presença já estava ligada."
            self._stop = threading.Event()
            self._status = _Status(running=True)
            self.machine = PresenceMachine(self.tuning, self.clock())
            self._thread = threading.Thread(target=self._run, args=(self._stop,), name="jarvis-presence", daemon=True)
            self._thread.start()
        return (
            "Presença ligada: observo a webcam duas vezes por segundo, só na memória. "
            f"Depois de {human_minutes(self.tuning.away_s)} fora eu pauso a mídia"
            + (" e bloqueio o computador." if self.lock_on_leave else "; o bloqueio está desligado.")
        )

    def stop(self, wait: float = 5.0) -> str:
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._status.running = False
        if thread is None or not thread.is_alive():
            return "A presença já estava desligada."
        if thread is not threading.current_thread():
            thread.join(wait)
        return "Presença desligada; a webcam foi liberada por ela."

    def set_lock(self, on: bool) -> str:
        self.lock_on_leave = on
        minutes = human_minutes(self.tuning.away_s)
        if on:
            return f"Certo: quando você sair por mais de {minutes}, eu bloqueio o computador."
        return f"Certo: não vou bloquear o computador quando você sair (a mídia ainda pausa depois de {minutes})."

    def describe(self) -> str:
        state = self.state()
        if not state["running"]:
            return "A presença está desligada." + (f" {state['error']}" if state["error"] else "")
        if state["error"]:
            return f"A presença está ligada, mas a câmera não está disponível: {state['error']}"
        lock = "bloqueio ligado" if state["lock"] else "bloqueio desligado"
        who = ", reconhecendo o seu rosto" if state["recognition"] else ""
        if state["state"] == Presence.PRESENT.value:
            where = "você está presente"
        elif state["state"] == Presence.AWAY.value:
            where = f"você está ausente há {human_minutes(self.clock() - state['since'])}"
        else:
            where = "ainda estou verificando se tem alguém"
        return f"Presença ligada{who}: {where}; {lock}."

    def state(self) -> dict[str, Any]:
        with self._lock:
            status = self._status
            running = self.running and status.running
            return {
                "running": running,
                "state": self.machine.state.value if running and not status.error else "off",
                "since": self.machine.since,
                "lock": self.lock_on_leave,
                "away_minutes": round(self.tuning.away_s / 60, 1),
                "recognition": self._recognizes,
                "faces": status.faces,
                "owner": status.owner,
                "camera_off": status.camera_off,
                "error": status.error,
            }

    def consume_welcome(self) -> Welcome | None:
        """As boas-vindas pendentes, para a conversa que acabou de abrir (só uma vez)."""
        with self._lock:
            welcome = self._welcome
            now = self.clock()
            if welcome is None or welcome.delivered_at is None or now - welcome.delivered_at > WELCOME_TTL_S:
                return None
            self._welcome = None
            return welcome

    # ── observação ──

    def tick(self, sighting: Sighting, now: float | None = None) -> list[PresenceEvent]:
        """Processa uma detecção (a thread chama ~2x/s; os testes chamam direto)."""
        now = self.clock() if now is None else now
        idle = self._safe(self.system.idle_seconds, None)
        active = idle is not None and idle < INPUT_GRACE_S
        with self._lock:
            self._status.faces, self._status.owner = sighting.faces, sighting.owner
            events = self.machine.observe(sighting.present, active, now)
            away = self.machine.state is Presence.AWAY
            if away and sighting.faces and sighting.owner is False and now - self._status.stranger_noted_at >= STRANGER_NOTE_S:
                self._status.stranger_noted_at = now
                self.journal.add(f"às {_clock_text(now)} alguém que eu não reconheci apareceu na frente do computador", now)
        for event in events:
            self._handle(event)
        self._deliver_welcome(now)
        return events

    def _handle(self, event: PresenceEvent) -> None:
        logger.info("Presença: %s (%s).", event.kind, f"{event.away_s:.0f} s fora" if event.away_s else "-")
        if event.kind == "arrived":
            if event.away_s is not None and event.away_s >= self.tuning.welcome_s:
                notes = [note.text for note in self.journal.between(event.at - event.away_s, event.at)]
                with self._lock:
                    self._welcome = Welcome(away_s=event.away_s, notes=notes, at=event.at)
        elif event.kind == "away_long":
            if self._safe(self.system.pause_media, False):
                self.journal.add(f"pausei a mídia que estava tocando às {_clock_text(event.at)}", event.at)
            if self.lock_on_leave:
                try:
                    self.system.lock()
                    self.journal.add(f"bloqueei o computador às {_clock_text(event.at)}", event.at)
                except Exception as exc:
                    logger.warning("Presença: não consegui bloquear o computador: %s", exc)

    def _deliver_welcome(self, now: float) -> None:
        with self._lock:
            welcome = self._welcome
            if welcome is None or welcome.delivered_at is not None:
                if welcome is not None and now - (welcome.delivered_at or now) > WELCOME_TTL_S:
                    self._welcome = None
                return
            if now - welcome.at > WELCOME_WAIT_S:
                self._welcome = None
                return
            if self._safe(self.system.locked, False):
                return  # fala só depois que ele desbloquear a tela
            welcome.delivered_at = now
        callback = self.on_welcome
        if callback is not None:
            try:
                callback()
            except Exception:
                logger.exception("Presença: falha ao abrir o link de boas-vindas.")

    def _safe(self, func: Callable[[], Any], default: Any) -> Any:
        try:
            return func()
        except Exception:
            logger.debug("Presença: falha em %s.", getattr(func, "__name__", func), exc_info=True)
            return default

    def _run(self, stop: threading.Event) -> None:
        sensor: Sensor | None = None
        try:
            while not stop.is_set():
                try:
                    if sensor is None:
                        sensor = self.sensor_factory()
                        self._recognizes = bool(getattr(sensor, "recognizes", False))
                    if self._watch(sensor, stop):
                        return
                    with self._lock:  # o usuário desligou a câmera: não religa sozinha
                        self._status.camera_off = True
                        self._status.error = CAMERA_OFF
                        self._status.running = False
                    return
                except CameraError as exc:
                    logger.warning("Presença: %s", exc)
                    with self._lock:
                        self._status.error = str(exc)
                except Exception as exc:
                    logger.exception("Presença: falha observando a webcam.")
                    with self._lock:
                        self._status.error = f"{type(exc).__name__}: {exc}"
                stop.wait(self.retry_s)
        finally:
            if sensor is not None:
                sensor.close()

    def _watch(self, sensor: Sensor, stop: threading.Event) -> bool:
        """Observa até o fim dos quadros; True quando parou por stop()."""
        frames = self.frames_factory()
        try:
            for frame in frames:
                if stop.is_set():
                    return True
                sighting = sensor.look(frame)
                with self._lock:
                    self._status.error = None
                self.tick(sighting)
                if stop.wait(self.interval):  # ~2 fps: o hub entrega o quadro mais novo no próximo next()
                    return True
            return stop.is_set()
        finally:
            close = getattr(frames, "close", None)
            if callable(close):
                close()


_SERVICE: PresenceService | None = None
_SERVICE_LOCK = threading.Lock()


def get_service() -> PresenceService:
    """O serviço de presença deste processo (o do server.py), com as opções do .env."""
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            from settings import load_settings

            settings = load_settings()
            _SERVICE = PresenceService(away_minutes=settings.presence_away_minutes, lock=settings.presence_lock)
        return _SERVICE


def voice_action(service: PresenceService, action: str) -> str:
    if action == "on":
        return service.start()
    if action == "off":
        return service.stop()
    if action == "lock_on":
        return service.set_lock(True)
    if action == "lock_off":
        return service.set_lock(False)
    return service.describe()


# ───────────────────────── agente (outro processo, via HTTP) ─────────────────────────

REQUEST_TIMEOUT = 4.0


class PresenceUnavailable(Exception):
    """Mensagem em PT-BR, pronta para o modelo repetir."""


def presence_request(method: str, path: str = "", body: dict[str, Any] | None = None, timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
    import requests

    from settings import load_settings

    base = load_settings().hud_url
    try:
        response = requests.request(method, f"{base}/api/presence{path}", json=body, timeout=timeout)
    except requests.ConnectionError as exc:
        raise PresenceUnavailable(
            f"o servidor do HUD não está rodando em {base}, e é ele que cuida da presença. Inicie com python jarvis.py."
        ) from exc
    except requests.Timeout as exc:
        raise PresenceUnavailable("o servidor do HUD não respondeu a tempo.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        raise PresenceUnavailable(str(detail or f"o servidor respondeu {response.status_code}."))
    return response.json()


def _presence_on() -> bool:
    try:
        from settings import load_settings

        return load_settings().presence_enabled
    except Exception:
        return False


async def welcome_instruction() -> str | None:
    """Instrução de boas-vindas quando esta conversa foi aberta pela chegada do usuário."""
    if not _presence_on():
        return None
    try:
        reply = await asyncio.to_thread(presence_request, "GET", "/welcome", None, 2.0)
    except PresenceUnavailable:
        return None
    welcome = reply.get("welcome")
    if not isinstance(welcome, dict):
        return None
    return build_welcome_instruction(float(welcome.get("away_s") or 0), [str(n) for n in welcome.get("notes") or []])


async def note_soon(text: str, at: float | None = None) -> None:
    """Anota no diário da presença (ex.: quando um timer vai acabar). Silencioso se não der."""
    if not _presence_on():
        return
    try:
        await asyncio.to_thread(presence_request, "POST", "/note", {"text": text, "at": at}, 1.5)
    except PresenceUnavailable:
        logger.debug("Presença: não consegui anotar '%s'.", text)


def build_presence_tools() -> list[Any]:
    from hud import tool_status

    @function_tool()
    async def presence_control(
        context: RunContext,
        action: Literal["on", "off", "status", "lock_on", "lock_off"],
    ) -> str:
        """Turn on/off the presence detection (the webcam notices when the user arrives and leaves),
        or choose whether the computer gets locked when the user is away.

        Only when the user asks: "liga a presença", "desliga a presença", "pode bloquear quando eu
        sair", "não bloqueia quando eu sair", "a presença está ligada?". Report exactly what the
        result says.

        Args:
            action: on, off, status, lock_on (lock the PC after the user is away for a while) or
                lock_off (never lock; media still pauses).
        """
        await tool_status("presence_control", "running", action)
        try:
            reply = await asyncio.to_thread(presence_request, "POST", "", {"action": action})
        except PresenceUnavailable as exc:
            await tool_status("presence_control", "error", action)
            return f"NADA mudou na presença: {exc}"
        await tool_status("presence_control", "done", action)
        logger.info("Presença por voz: %s → %s", action, reply.get("message"))
        return str(reply.get("message") or "Feito.")

    return [presence_control]


# ───────────────────────── linha de comando ─────────────────────────


def _cli_frames(device: str | None) -> Iterator[np.ndarray]:
    """Um hub só deste comando, com a webcam aberta direto (o Jarvis precisa estar fechado)."""
    from camera import CameraHub, open_camera

    return CameraHub(lambda: open_camera(device), linger=0).frames()


def enroll(
    frames: Iterator[np.ndarray],
    sensor: FaceSensor,
    *,
    samples: int = ENROLL_SAMPLES,
    path: Path = PROFILE_PATH,
    pause: float = 0.25,
) -> OwnerProfile:
    """Coleta embeddings do rosto (só um rosto no quadro) e grava o cadastro. Nenhuma imagem é salva."""
    collected: list[np.ndarray] = []
    for frame in frames:
        found = sensor.embeddings(_small(frame, square=True)) or sensor.embeddings(_small(frame))
        if len(found) == 1:
            collected.append(found[0])
            print(f"\r  amostras: {len(collected)}/{samples}   ", end="", flush=True)
            if len(collected) >= samples:
                break
        elif len(found) > 1:
            print("\r  há mais de um rosto no quadro; fique sozinho na frente da câmera", end="", flush=True)
        time.sleep(pause)  # amostras espaçadas pegam ângulos diferentes
    print()
    profile = OwnerProfile.from_samples(collected)
    profile.save(path)
    return profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Presença do Jarvis (PRS-25): cadastro e teste do rosto.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enroll", action="store_true", help="Cadastra o seu rosto (só embeddings, sem imagem).")
    group.add_argument("--test", action="store_true", help="Mostra no terminal o que a presença vê.")
    group.add_argument("--forget", action="store_true", help="Apaga o cadastro do rosto.")
    parser.add_argument("--camera", default=None, help="Índice ou parte do nome da webcam (padrão: JARVIS_CAMERA).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if args.forget:
        if PROFILE_PATH.exists():
            PROFILE_PATH.unlink()
            print(f"Cadastro apagado ({PROFILE_PATH.name}). A presença volta a aceitar qualquer rosto.")
        else:
            print("Não havia rosto cadastrado.")
        return 0

    from settings import load_settings

    device = args.camera or load_settings().camera_device
    try:
        frames = _cli_frames(device)
        if args.enroll:
            print("Cadastro do rosto: feche o Jarvis (ele é o dono da câmera), fique sozinho na frente da")
            print("webcam, a uns 50-80 cm, e vire a cabeça devagar um pouco para os lados e para cima/baixo.")
            profile = enroll(frames, FaceSensor(None, embeddings=True))
            print(
                f"Pronto: rosto cadastrado em {PROFILE_PATH.name} ({len(profile.embeddings)} embeddings, "
                "nenhuma imagem). Confira com: python presence.py --test"
            )
            return 0
        sensor = default_sensor()
        print("Ctrl+C para sair. " + ("Comparando com o rosto cadastrado." if sensor.recognizes else "Sem cadastro: qualquer rosto vale."))
        machine = PresenceMachine(Tuning(), time.time())
        for frame in frames:
            sighting = sensor.look(frame)
            for event in machine.observe(sighting.present, False, time.time()):
                print(f"\n>>> {event.kind}" + (f" ({human_minutes(event.away_s)} fora)" if event.away_s else ""))
            score = ""
            if sighting.similarity is not None and sensor.profile is not None:
                score = f" · semelhança {sighting.similarity:.2f} (mínimo {sensor.profile.threshold:.2f})"
            owner = "" if sighting.owner is None else (" · é você" if sighting.owner else " · não reconheci")
            print(f"\r  rostos: {sighting.faces}{owner}{score} · estado: {machine.state.value}      ", end="", flush=True)
            time.sleep(SAMPLE_INTERVAL_S)
    except CameraError as exc:
        print(f"Câmera: {exc}")
        return 1
    except ValueError as exc:
        print(f"Não deu para cadastrar: {exc} Tente de novo com mais luz no rosto.")
        return 1
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
