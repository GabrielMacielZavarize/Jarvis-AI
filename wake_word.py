"""Detector local da palavra de ativação (WAK-22): diga "Jarvis" e o HUD abre o link sozinho.

Roda em um processo leve iniciado pelo ``jarvis.py`` quando ``JARVIS_WAKE_WORD=true``. O áudio
do microfone é analisado aqui mesmo pelo openWakeWord (modelo ``hey_jarvis``); só a pontuação de
uma detecção vai para o servidor do HUD em 127.0.0.1. Nada é gravado nem sai do computador.

O microfone fica aberto só enquanto o detector precisa ouvir: durante o link o navegador é quem
capta a sua voz, e o detector libera o dispositivo até a conversa acabar.

Uso:
    python wake_word.py --test        # pontuação ao vivo, para calibrar JARVIS_WAKE_THRESHOLD
    python wake_word.py --list-mics   # microfones que o detector enxerga
    python wake_word.py --server http://127.0.0.1:8000   # o que o jarvis.py executa
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import time
import types
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol

import requests

SAMPLE_RATE = 16_000
# openWakeWord avalia o áudio em passos de 80 ms.
FRAME_SAMPLES = 1280
MODEL_NAME = "hey_jarvis"
POLL_INTERVAL_S = 0.5
# Depois do link, espera a despedida do Jarvis sair da caixa de som antes de voltar a ouvir.
REARM_DELAY_S = 1.5
RETRY_DELAY_S = 5.0
REFRACTORY_S = 2.0
# Microfone mudo no Windows entrega zeros e ±1; voz e até o ruído de uma sala passam disso.
SILENT_PEAK = 2
SILENT_AFTER_S = 5.0
# Calibração: fala perto do microfone passa de ~-36 dBFS; o ruído de fundo fica abaixo.
SPEECH_PEAK = 500
SILENT_FRAMES = round(SILENT_AFTER_S * SAMPLE_RATE / FRAME_SAMPLES)
UTTERANCE_TAIL_FRAMES = 12
MAX_UTTERANCE_FRAMES = 50
SECRET_ENV = "JARVIS_WAKE_SECRET"
SECRET_HEADER = "X-Jarvis-Wake"
LOG_PREFIX = "[ATIVAÇÃO]"

# Prefixos que o Chrome/Edge põem nos aliases do microfone padrão e de comunicação.
BROWSER_ALIAS_PREFIX = re.compile(
    r"^(padr[aã]o|default|comunica[cç][oõ]es|communications)\s+-\s+", re.IGNORECASE
)
# Dispositivos USB vêm com "(vendor:product)" no fim do nome no navegador.
USB_ID_SUFFIX = re.compile(r"\s*\([0-9a-f]{4}:[0-9a-f]{4}\)\s*$", re.IGNORECASE)
# Ordem de preferência: o MME converte para 16 kHz sozinho; WDM-KS fica de fora (acesso direto ao driver).
HOST_API_PREFERENCE = {"MME": 0, "Windows DirectSound": 1, "Windows WASAPI": 2}
WASAPI = "Windows WASAPI"


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", flush=True)


# --- Microfone -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputDevice:
    index: int
    name: str
    host_api: str


def browser_label_to_name(label: str) -> str:
    """"Padrão - Headset (Fone X) (0b0e:0300)" → "Headset (Fone X)"."""
    return USB_ID_SUFFIX.sub("", BROWSER_ALIAS_PREFIX.sub("", label.strip())).strip()


def _compact(name: str) -> str:
    # O MME corta nomes em 31 caracteres e troca "®" por "�"; comparar só letras e números resolve os dois.
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def list_input_devices(sd: Any) -> list[InputDevice]:
    host_apis = sd.query_hostapis()
    devices = []
    for device in sd.query_devices():
        host_api = host_apis[device["hostapi"]]["name"]
        if device["max_input_channels"] > 0 and host_api in HOST_API_PREFERENCE:
            devices.append(InputDevice(device["index"], device["name"], host_api))
    return devices


def pick_input_device(label: str | None, devices: Iterable[InputDevice]) -> InputDevice | None:
    """Device whose name matches the label the browser shows (or part of it, for JARVIS_WAKE_MIC)."""
    if not label:
        return None
    target = _compact(browser_label_to_name(label))
    if len(target) < 3:
        return None

    ranked: list[tuple[int, int, int, InputDevice]] = []
    for device in devices:
        name = _compact(device.name)
        if not name:
            continue
        # O mesmo nome, ou cortado pelo MME, vale tanto quanto o nome completo do WASAPI.
        if name == target or (len(name) >= 12 and target.startswith(name)):
            score = 2
        elif target in name or name in target:
            score = 1
        else:
            continue
        ranked.append((-score, HOST_API_PREFERENCE[device.host_api], device.index, device))
    return min(ranked)[3] if ranked else None


class AudioSource(Protocol):
    description: str

    def read(self, timeout: float) -> Any | None: ...

    def close(self) -> None: ...


def _default_input_name(sd: Any) -> str:
    try:
        return sd.query_devices(kind="input")["name"]
    except Exception:
        return "sem nome"


class MicStream:
    """16 kHz mono capture; frames go to a queue so polling the server never drops audio."""

    def __init__(self, sd: Any, device: InputDevice | None) -> None:
        self.description = device.name if device else f"padrão do Windows ({_default_input_name(sd)})"
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=64)
        extra = sd.WasapiSettings(auto_convert=True) if device and device.host_api == WASAPI else None
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=device.index if device else None,
            callback=self._on_audio,
            extra_settings=extra,
        )
        self._stream.start()

    def _on_audio(self, indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        try:
            self._queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def read(self, timeout: float) -> Any | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()


def open_microphone(label: str | None) -> MicStream:
    import sounddevice as sd

    device = pick_input_device(label, list_input_devices(sd)) if label else None
    if label and device is None:
        log(f"Microfone “{label}” não encontrado; usando o padrão do Windows.")
    return MicStream(sd, device)


# --- Detecção ------------------------------------------------------------------------------------


class WakeModel(Protocol):
    def predict(self, frame: Any) -> dict[str, float]: ...

    def reset(self) -> None: ...


class WakeDetector:
    """Turns 80 ms frames into activations, ignoring the echo of the same utterance."""

    def __init__(
        self,
        model: WakeModel,
        threshold: float,
        *,
        refractory_s: float = REFRACTORY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.model = model
        self.threshold = threshold
        self.refractory_s = refractory_s
        self._clock = clock
        self._last_at: float | None = None

    def score(self, frame: Any) -> float:
        scores = self.model.predict(frame)
        return float(max(scores.values(), default=0.0))

    def process(self, frame: Any) -> float | None:
        score = self.score(frame)
        if score < self.threshold:
            return None
        now = self._clock()
        if self._last_at is not None and now - self._last_at < self.refractory_s:
            return None
        self._last_at = now
        self.model.reset()
        return score

    def reset(self) -> None:
        self.model.reset()


def _skip_verifier_training_imports() -> None:
    """``openwakeword/__init__`` imports the custom-verifier trainer (scipy + scikit-learn, ~90 MB
    of RAM) that the detector never uses; an empty stand-in keeps this process light."""
    name = "openwakeword.custom_verifier_model"
    if name in sys.modules:
        return
    stub = types.ModuleType(name)

    def train_custom_verifier(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Treino de verificador indisponível no detector do Jarvis.")

    stub.train_custom_verifier = train_custom_verifier  # type: ignore[attr-defined]
    sys.modules[name] = stub


def load_model() -> WakeModel:
    _skip_verifier_training_imports()
    import openwakeword
    from openwakeword.model import Model
    from openwakeword.utils import download_models

    needed = [
        openwakeword.MODELS[MODEL_NAME]["model_path"],
        *(model["model_path"] for model in openwakeword.FEATURE_MODELS.values()),
    ]
    if not all(os.path.exists(path.replace(".tflite", ".onnx")) for path in needed):
        log(f"Baixando o modelo {MODEL_NAME} do openWakeWord (~5 MB, só na primeira vez)...")
        download_models(model_names=[MODEL_NAME])
    return Model(wakeword_models=[MODEL_NAME], inference_framework="onnx")


# --- Conversa com o servidor do HUD --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectorState:
    listen: bool
    mic_label: str | None = None


class ServerLink:
    def __init__(self, base_url: str, secret: str | None, *, http: Any = requests, timeout: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {SECRET_HEADER: secret or "1"}
        self.http = http
        self.timeout = timeout
        self.reachable: bool | None = None

    def _note_reachable(self, reachable: bool) -> None:
        if reachable != self.reachable:
            if reachable:
                log("Conectado ao servidor do HUD.")
            elif self.reachable is not None:
                log("Servidor do HUD fora do ar; microfone liberado até ele voltar.")
        self.reachable = reachable

    def state(self, mic_silent: bool = False) -> DetectorState | None:
        """What the server wants; ``mic_silent`` tells the HUD the open mic only delivers silence."""
        try:
            response = self.http.get(
                f"{self.base_url}/api/wake/detector",
                params={"silent": int(mic_silent)},
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError):
            self._note_reachable(False)
            return None
        self._note_reachable(True)
        label = body.get("mic_label")
        return DetectorState(listen=bool(body.get("listen")), mic_label=label if isinstance(label, str) else None)

    def trigger(self, score: float) -> dict[str, Any] | None:
        try:
            response = self.http.post(
                f"{self.base_url}/api/wake/trigger",
                json={"score": round(score, 3)},
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            return None


def _peak(frame: Any) -> int:
    return max(int(frame.max()), -int(frame.min()))


def run(
    link: ServerLink,
    detector: WakeDetector,
    *,
    open_mic: Callable[[str | None], AudioSource] = open_microphone,
    mic_override: str | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    keep_running: Callable[[], bool] = lambda: True,
) -> None:
    """Listen only while the server says so; on "Jarvis", free the mic and tell the server."""
    stream: AudioSource | None = None
    stream_label: str | None = None
    listening = False
    open_at = 0.0
    next_poll = 0.0
    signal_at = 0.0
    mic_silent = False

    def close_stream(reason: str) -> None:
        nonlocal stream, mic_silent
        mic_silent = False
        if stream is not None:
            stream.close()
            stream = None
            log(reason)

    try:
        while keep_running():
            now = clock()
            if now >= next_poll:
                next_poll = now + POLL_INTERVAL_S
                state = link.state(mic_silent=mic_silent)
                label = mic_override or (state.mic_label if state else None)
                if state is None or not state.listen:
                    close_stream("Microfone liberado para o link." if state else "Microfone liberado.")
                    listening = False
                else:
                    if not listening:
                        listening = True
                        open_at = now + REARM_DELAY_S
                    if stream is not None and label != stream_label:
                        close_stream("Trocando de microfone...")
                        open_at = now
                    if stream is None and now >= open_at:
                        try:
                            stream = open_mic(label)
                            stream_label = label
                            signal_at = now
                            detector.reset()
                            log(f"Ouvindo “Jarvis” em: {stream.description}.")
                        except Exception as exc:  # dispositivo ocupado, desconectado ou sem permissão
                            log(f"Não foi possível abrir o microfone ({exc}); tento de novo em {RETRY_DELAY_S:g} s.")
                            open_at = now + RETRY_DELAY_S

            if stream is None:
                sleep(0.1)
                continue
            frame = stream.read(timeout=0.1)
            if frame is None:
                continue
            if _peak(frame) > SILENT_PEAK:
                signal_at = clock()
            silent = clock() - signal_at >= SILENT_AFTER_S
            if silent != mic_silent:
                mic_silent = silent
                log(
                    f"Sem sinal em {stream.description}: o microfone está mudo no Windows?"
                    if silent
                    else "O microfone voltou a captar som."
                )
            score = detector.process(frame)
            if score is None:
                continue

            close_stream(f"“Jarvis” detectado (pontuação {score:.2f}); abrindo o link.")
            listening = False
            result = link.trigger(score)
            if result is None:
                log("O servidor do HUD não respondeu ao aviso.")
            elif result.get("opened_browser"):
                log("HUD não estava aberto; abrindo o navegador.")
            next_poll = 0.0
    finally:
        if stream is not None:
            stream.close()


# --- Linha de comando ----------------------------------------------------------------------------


def _list_mics() -> int:
    import sounddevice as sd

    default_index = sd.default.device[0]
    for device in list_input_devices(sd):
        marker = "  (padrão)" if device.index == default_index else ""
        print(f"{device.index:>3}  {device.host_api:<20} {device.name}{marker}")
    return 0


def _calibrate(threshold: float, label: str | None) -> int:
    """Live scores, so the threshold can be tuned to your voice and room."""
    model = load_model()
    mic = open_microphone(label)
    print(f"Microfone: {mic.description}. Limiar atual: {threshold:.2f}. Ctrl+C para sair.")
    print("Diga “Jarvis” e “hey Jarvis” algumas vezes, e fale frases comuns para ver os falsos positivos.\n")
    best = 0.0
    loudest = voiced = quiet = silent = 0
    try:
        while True:
            frame = mic.read(timeout=1.0)
            if frame is None:
                continue
            level = _peak(frame)
            score = float(max(model.predict(frame).values(), default=0.0))

            if level > SILENT_PEAK:
                if silent >= SILENT_FRAMES:
                    print("Sinal chegando. Pode falar.", flush=True)
                silent = 0
            else:
                silent += 1
                if silent == SILENT_FRAMES:
                    print("Sem sinal nenhum: o microfone está mudo no Windows? (tecla de mudo ou Som > Entrada)", flush=True)

            if level >= SPEECH_PEAK or score >= 0.05:
                voiced += 1
                quiet = 0
                best, loudest = max(best, score), max(loudest, level)
                if voiced < MAX_UTTERANCE_FRAMES:
                    continue
            elif voiced:
                # A pontuação chega meio segundo depois do som: espera antes de fechar a fala.
                quiet += 1
                best = max(best, score)
                if quiet < UTTERANCE_TAIL_FRAMES:
                    continue
            else:
                continue

            verdict = "ATIVARIA" if best >= threshold else "abaixo do limiar"
            print(
                f"fala de {voiced * FRAME_SAMPLES / SAMPLE_RATE:.1f} s · volume {loudest * 100 // 32767:>3}% · "
                f"pontuação {best:.2f}  {'█' * round(best * 30):<30}  {verdict}",
                flush=True,
            )
            best = 0.0
            loudest = voiced = quiet = 0
    except KeyboardInterrupt:
        return 0
    finally:
        mic.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detector local da palavra de ativação do Jarvis.")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="Endereço do servidor do HUD.")
    parser.add_argument("--test", action="store_true", help="Mostra a pontuação ao vivo para calibrar o limiar.")
    parser.add_argument("--list-mics", action="store_true", help="Lista os microfones disponíveis.")
    parser.add_argument("--mic", help="Parte do nome do microfone (sobrepõe JARVIS_WAKE_MIC).")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    from settings import SettingsError, load_settings

    try:
        settings = load_settings()
    except SettingsError as exc:
        log(str(exc))
        return 1
    mic_override = args.mic or settings.wake_mic

    try:
        if args.list_mics:
            return _list_mics()
        if args.test:
            return _calibrate(settings.wake_threshold, mic_override)
        model = load_model()
    except ImportError as exc:
        log(f"Dependência ausente ({exc.name}). Instale com: pip install openwakeword sounddevice")
        return 1

    detector = WakeDetector(model, settings.wake_threshold)
    link = ServerLink(args.server, os.environ.get(SECRET_ENV))
    log(f"Detector pronto (limiar {settings.wake_threshold:.2f}). Diga “Jarvis” para abrir o link.")
    try:
        run(link, detector, mic_override=mic_override)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
