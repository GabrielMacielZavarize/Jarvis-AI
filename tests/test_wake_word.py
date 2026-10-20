from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
from collections import deque
from unittest.mock import MagicMock, patch

import requests

import wake_hub
import wake_word
from wake_word import (
    REARM_DELAY_S,
    RETRY_DELAY_S,
    SILENT_AFTER_S,
    Detection,
    DetectorState,
    InputDevice,
    ServerLink,
    WakeDetector,
    browser_label_to_name,
    load_model,
    pick_input_device,
    run,
)

# What sounddevice lists on a notebook with a Bluetooth headset (MME cuts names at 31 characters).
DEVICES = [
    InputDevice(0, "Mapeador de som da Microsoft - Input", "MME"),
    InputDevice(1, "Headset (Redmi Buds 6 Pro)", "MME"),
    InputDevice(2, "Microphone Array (Intel� Smart ", "MME"),
    InputDevice(9, "Headset (Redmi Buds 6 Pro)", "Windows DirectSound"),
    InputDevice(10, "Microphone Array (Intel� Smart Sound Technology for Digital Microphones)", "Windows DirectSound"),
    InputDevice(20, "Headset (Redmi Buds 6 Pro)", "Windows WASAPI"),
    InputDevice(21, "Microphone Array (Intel� Smart Sound Technology for Digital Microphones)", "Windows WASAPI"),
    InputDevice(30, "Fone USB", "Windows WASAPI"),
]


class FakeModel:
    """Scores per frame: a number is "jarvis" alone, a dict carries every word of that frame."""

    def __init__(self, scores: list[float | dict[str, float]], words: tuple[str, ...] = ("jarvis",)) -> None:
        self.scores = deque(scores)
        self.words = words
        self.resets = 0

    def predict(self, _frame: object) -> dict[str, float]:
        frame = self.scores.popleft() if self.scores else 0.0
        scores = dict.fromkeys(self.words, 0.0)
        scores.update(frame if isinstance(frame, dict) else {"jarvis": frame})
        return scores

    def reset(self) -> None:
        self.resets += 1


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeStream:
    description = "Microfone de teste"

    def __init__(self, clock: Clock, label: str | None, amplitude: int) -> None:
        self.clock = clock
        self.label = label
        self.amplitude = amplitude
        self.closed = False

    def read(self, timeout: float) -> np.ndarray:
        self.clock.now += 0.08
        frame = np.zeros(1280, dtype=np.int16)
        frame[::2] = self.amplitude
        return frame

    def close(self) -> None:
        self.closed = True


class FakeLink:
    """Answers polls from a script of (until_time, state) and records triggers."""

    def __init__(self, clock: Clock, script: list[tuple[float, DetectorState | None]]) -> None:
        self.clock = clock
        self.script = script
        self.triggers: list[float] = []
        self.words: list[str] = []
        self.silent_reports: list[bool] = []
        self.reported_words: tuple[str, ...] = ()

    def state(self, mic_silent: bool = False, words: tuple[str, ...] = ()) -> DetectorState | None:
        self.silent_reports.append(mic_silent)
        self.reported_words = tuple(words)
        for until, state in self.script:
            if self.clock.now < until:
                return state
        return self.script[-1][1]

    def trigger(self, score: float, word: str | None = None) -> dict[str, bool]:
        self.triggers.append(score)
        self.words.append(word)
        return {"accepted": True, "opened_browser": False}


class Harness:
    def __init__(
        self,
        script: list[tuple[float, DetectorState | None]],
        scores: list[float | dict[str, float]],
        *,
        until: float = 10.0,
        words: tuple[str, ...] = ("jarvis",),
    ):
        self.clock = Clock()
        self.link = FakeLink(self.clock, script)
        self.model = FakeModel(scores, words)
        self.detector = WakeDetector(self.model, threshold={"jarvis": 0.5, "friday": 0.7}, clock=self.clock)
        self.streams: list[FakeStream] = []
        self.until = until
        self.open_error: Exception | None = None
        self.amplitude = 120

    def open_mic(self, label: str | None) -> FakeStream:
        if self.open_error is not None:
            error, self.open_error = self.open_error, None
            raise error
        stream = FakeStream(self.clock, label, self.amplitude)
        self.streams.append(stream)
        return stream

    def run(self, **kwargs: object) -> None:
        with patch("builtins.print"):
            run(
                self.link,
                self.detector,
                open_mic=self.open_mic,
                clock=self.clock,
                sleep=self.clock.sleep,
                keep_running=lambda: self.clock.now < self.until,
                **kwargs,
            )


LISTEN = DetectorState(listen=True)
PAUSE = DetectorState(listen=False)


class MicrophoneMatchTests(unittest.TestCase):
    def test_strips_browser_aliases_and_usb_ids(self) -> None:
        self.assertEqual(browser_label_to_name("Padrão - Headset (Redmi Buds 6 Pro)"), "Headset (Redmi Buds 6 Pro)")
        self.assertEqual(browser_label_to_name("Default - Fone USB (0b0e:0300)"), "Fone USB")
        self.assertEqual(browser_label_to_name("Comunicações - Microfone (Realtek)"), "Microfone (Realtek)")

    def test_prefers_mme_even_with_the_name_cut(self) -> None:
        # O MME converte para 16 kHz sozinho, então vence o nome completo do DirectSound/WASAPI.
        device = pick_input_device("Microphone Array (Intel® Smart Sound Technology for Digital Microphones)", DEVICES)

        self.assertEqual(device, DEVICES[2])

    def test_matches_the_browser_label_of_the_default_alias(self) -> None:
        self.assertEqual(pick_input_device("Padrão - Headset (Redmi Buds 6 Pro)", DEVICES), DEVICES[1])

    def test_falls_back_to_wasapi_when_only_it_lists_the_device(self) -> None:
        self.assertEqual(pick_input_device("Fone USB (0b0e:0300)", DEVICES).index, 30)

    def test_part_of_the_name_works_for_jarvis_wake_mic(self) -> None:
        self.assertEqual(pick_input_device("array", DEVICES), DEVICES[2])

    def test_unknown_or_empty_labels_mean_the_windows_default(self) -> None:
        self.assertIsNone(pick_input_device("Microfone que não existe", DEVICES))
        self.assertIsNone(pick_input_device(None, DEVICES))
        self.assertIsNone(pick_input_device("ab", DEVICES))

    def test_lists_inputs_without_wdm_ks(self) -> None:
        sd = MagicMock()
        sd.query_hostapis.return_value = [{"name": "MME"}, {"name": "Windows WDM-KS"}]
        sd.query_devices.return_value = [
            {"index": 1, "name": "Headset", "hostapi": 0, "max_input_channels": 1},
            {"index": 2, "name": "Alto-falante", "hostapi": 0, "max_input_channels": 0},
            {"index": 3, "name": "Microfone 1", "hostapi": 1, "max_input_channels": 2},
        ]

        self.assertEqual(wake_word.list_input_devices(sd), [InputDevice(1, "Headset", "MME")])


class DetectorTests(unittest.TestCase):
    def test_fires_once_per_utterance(self) -> None:
        clock = Clock()
        model = FakeModel([0.1, 0.7, 0.9, 0.8])
        detector = WakeDetector(model, threshold=0.5, clock=clock)

        results = [detector.process(object()) for _ in range(4)]

        self.assertEqual(results, [None, Detection("jarvis", 0.7), None, None])
        self.assertEqual(model.resets, 1)

    def test_fires_again_after_the_refractory_period(self) -> None:
        clock = Clock()
        detector = WakeDetector(FakeModel([0.9, 0.9]), threshold=0.5, clock=clock)

        detector.process(object())
        clock.now += 2.5

        self.assertEqual(detector.process(object()), Detection("jarvis", 0.9))

    def test_each_word_has_its_own_threshold_and_the_highest_score_wins(self) -> None:
        clock = Clock()
        model = FakeModel(
            [{"friday": 0.65}, {"friday": 0.82}, {"jarvis": 0.6, "friday": 0.9}, {"jarvis": 0.95, "friday": 0.75}],
            words=("jarvis", "friday"),
        )
        detector = WakeDetector(model, threshold={"jarvis": 0.5, "friday": 0.7}, clock=clock)

        heard = []
        for _ in range(4):
            heard.append(detector.process(object()))
            clock.now += 3

        self.assertEqual(
            heard,
            [None, Detection("friday", 0.82), Detection("friday", 0.9), Detection("jarvis", 0.95)],
        )
        self.assertEqual(detector.words, ("jarvis", "friday"))

    def test_loads_every_word_that_has_a_model(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        friday = Path(folder.name) / "friday.onnx"
        friday.write_bytes(b"onnx")
        loaded: list[list[str]] = []

        class OwwModel:
            def __init__(self, wakeword_models: list[str], inference_framework: str) -> None:
                loaded.append(list(wakeword_models))

            def predict(self, _frame: object) -> dict[str, float]:
                return {"hey_jarvis": 0.1, "friday": 0.8}

            def reset(self) -> None:
                pass

        fake = types.ModuleType("openwakeword")
        fake.MODELS = {"hey_jarvis": {"model_path": __file__}}
        fake.FEATURE_MODELS = {}
        modules = {
            "openwakeword": fake,
            "openwakeword.model": types.SimpleNamespace(Model=OwwModel),
            "openwakeword.utils": types.SimpleNamespace(download_models=MagicMock()),
        }
        with (
            patch.dict(sys.modules, modules),
            patch.dict(wake_word.WORD_MODELS, {"friday": friday}),
            patch("os.path.exists", return_value=True),
            patch("builtins.print") as printed,
        ):
            model = load_model(("jarvis", "friday"))
            self.assertEqual(model.predict(object()), {"jarvis": 0.1, "friday": 0.8})
            self.assertEqual(model.words, ("jarvis", "friday"))

            friday.unlink()
            only_jarvis = load_model(("jarvis", "friday"))

        self.assertEqual(loaded, [["hey_jarvis", str(friday)], ["hey_jarvis"]])
        self.assertEqual(only_jarvis.words, ("jarvis",))
        self.assertIn("não encontrado", str(printed.call_args))

    def test_verifier_trainer_is_not_imported(self) -> None:
        with patch.dict(sys.modules):
            sys.modules.pop("openwakeword.custom_verifier_model", None)
            wake_word._skip_verifier_training_imports()
            stub = sys.modules["openwakeword.custom_verifier_model"]

            with self.assertRaises(RuntimeError):
                stub.train_custom_verifier()


class ServerLinkTests(unittest.TestCase):
    def test_polls_with_the_shared_secret(self) -> None:
        http = MagicMock()
        http.get.return_value.json.return_value = {"listen": True, "mic_label": "Headset"}
        link = ServerLink("http://127.0.0.1:8000/", "s3cret", http=http)

        with patch("builtins.print"):
            state = link.state()

        self.assertEqual(state, DetectorState(listen=True, mic_label="Headset"))
        url = http.get.call_args.args[0]
        self.assertEqual(url, "http://127.0.0.1:8000/api/wake/detector")
        self.assertEqual(http.get.call_args.kwargs["params"], {"silent": 0})
        self.assertEqual(http.get.call_args.kwargs["headers"], {"X-Jarvis-Wake": "s3cret"})

    def test_server_down_means_do_not_listen(self) -> None:
        http = MagicMock()
        http.get.side_effect = requests.ConnectionError("down")

        self.assertIsNone(ServerLink("http://127.0.0.1:8000", None, http=http).state())

    def test_trigger_sends_the_score_and_the_word_heard(self) -> None:
        http = MagicMock()
        http.post.return_value.json.return_value = {"accepted": True, "opened_browser": True}
        link = ServerLink("http://127.0.0.1:8000", None, http=http)

        result = link.trigger(0.91234)

        self.assertTrue(result["opened_browser"])
        self.assertEqual(http.post.call_args.kwargs["json"], {"score": 0.912})
        self.assertEqual(http.post.call_args.kwargs["headers"], {"X-Jarvis-Wake": "1"})
        link.trigger(0.8, "friday")
        self.assertEqual(http.post.call_args.kwargs["json"], {"score": 0.8, "word": "friday"})

    def test_polls_tell_the_server_which_words_it_hears(self) -> None:
        http = MagicMock()
        http.get.return_value.json.return_value = {"listen": True}

        with patch("builtins.print"):
            ServerLink("http://127.0.0.1:8000", None, http=http).state(words=("jarvis", "friday"))

        self.assertEqual(http.get.call_args.kwargs["params"], {"silent": 0, "words": "jarvis,friday"})

    def test_same_secret_names_as_the_server(self) -> None:
        self.assertEqual(wake_word.SECRET_ENV, wake_hub.SECRET_ENV)
        self.assertEqual(wake_word.SECRET_HEADER, wake_hub.SECRET_HEADER)


class RunLoopTests(unittest.TestCase):
    def test_opens_the_mic_only_after_the_rearm_delay(self) -> None:
        harness = Harness([(10.0, LISTEN)], scores=[], until=REARM_DELAY_S - 0.2)

        harness.run()

        self.assertEqual(harness.streams, [])

    def test_detection_frees_the_mic_and_tells_the_server(self) -> None:
        harness = Harness([(3.0, LISTEN), (6.0, PAUSE)], scores=[0.0, 0.0, 0.93], until=6.0)

        harness.run()

        self.assertEqual(harness.link.triggers, [0.93])
        self.assertEqual(harness.link.words, ["jarvis"])
        self.assertEqual(len(harness.streams), 1)
        self.assertTrue(harness.streams[0].closed)

    def test_friday_is_reported_with_its_name(self) -> None:
        harness = Harness(
            [(3.0, LISTEN), (6.0, PAUSE)], scores=[0.0, {"friday": 0.88}], until=6.0, words=("jarvis", "friday")
        )

        harness.run()

        self.assertEqual(harness.link.triggers, [0.88])
        self.assertEqual(harness.link.words, ["friday"])
        self.assertEqual(harness.link.reported_words, ("jarvis", "friday"))

    def test_never_listens_while_the_link_is_open(self) -> None:
        harness = Harness([(10.0, PAUSE)], scores=[0.99], until=5.0)

        harness.run()

        self.assertEqual(harness.streams, [])
        self.assertEqual(harness.link.triggers, [])

    def test_releases_the_mic_when_a_session_starts_and_listens_again_after(self) -> None:
        harness = Harness([(3.0, LISTEN), (5.0, PAUSE), (10.0, LISTEN)], scores=[], until=9.0)

        harness.run()

        self.assertEqual(len(harness.streams), 2)
        self.assertTrue(harness.streams[0].closed)
        self.assertTrue(harness.streams[1].closed)  # o loop fecha ao sair

    def test_reopens_on_the_microphone_chosen_in_the_hud(self) -> None:
        harness = Harness(
            [(3.0, LISTEN), (10.0, DetectorState(listen=True, mic_label="Headset (Redmi Buds 6 Pro)"))],
            scores=[],
            until=5.0,
        )

        harness.run()

        self.assertEqual([stream.label for stream in harness.streams], [None, "Headset (Redmi Buds 6 Pro)"])

    def test_jarvis_wake_mic_overrides_the_hud_choice(self) -> None:
        harness = Harness([(10.0, DetectorState(listen=True, mic_label="Headset"))], scores=[], until=3.0)

        harness.run(mic_override="Microphone Array")

        self.assertEqual([stream.label for stream in harness.streams], ["Microphone Array"])

    def test_retries_when_the_mic_is_busy(self) -> None:
        harness = Harness([(20.0, LISTEN)], scores=[], until=REARM_DELAY_S + RETRY_DELAY_S + 1)
        harness.open_error = OSError("Device unavailable")

        harness.run()

        self.assertEqual(len(harness.streams), 1)

    def test_reports_a_muted_microphone(self) -> None:
        harness = Harness([(30.0, LISTEN)], scores=[], until=REARM_DELAY_S + SILENT_AFTER_S + 1.5)
        harness.amplitude = 1  # mudo no Windows: zeros e ±1

        harness.run()

        self.assertFalse(harness.link.silent_reports[0])
        self.assertTrue(harness.link.silent_reports[-1])

    def test_room_noise_is_not_silence(self) -> None:
        harness = Harness([(30.0, LISTEN)], scores=[], until=REARM_DELAY_S + SILENT_AFTER_S + 1.5)

        harness.run()

        self.assertFalse(any(harness.link.silent_reports))

    def test_server_down_releases_the_mic(self) -> None:
        harness = Harness([(3.0, LISTEN), (10.0, None)], scores=[], until=5.0)

        harness.run()

        self.assertEqual(len(harness.streams), 1)
        self.assertTrue(harness.streams[0].closed)


class CommandLineTests(unittest.TestCase):
    def test_missing_dependency_is_explained(self) -> None:
        error = ImportError("No module named 'openwakeword'", name="openwakeword")
        with (
            patch.dict("os.environ", {"GOOGLE_API_KEY": "x"}, clear=True),
            patch("wake_word.load_model", side_effect=error),
            patch("builtins.print") as printed,
        ):
            code = wake_word.main([])

        self.assertEqual(code, 1)
        self.assertIn("pip install openwakeword", str(printed.call_args))

    def test_loads_the_words_and_thresholds_of_the_env(self) -> None:
        env = {"GOOGLE_API_KEY": "x", "JARVIS_WAKE_WORDS": "jarvis,friday", "JARVIS_WAKE_THRESHOLD_FRIDAY": "0.8"}
        model = FakeModel([], words=("jarvis", "friday"))
        with (
            patch.dict("os.environ", env, clear=True),
            patch("wake_word.load_model", return_value=model) as load,
            patch("wake_word.run") as loop,
            patch("builtins.print") as printed,
        ):
            self.assertEqual(wake_word.main([]), 0)

        self.assertEqual(load.call_args.args[0], ("jarvis", "friday"))
        detector = loop.call_args.args[1]
        self.assertEqual((detector.threshold_for("jarvis"), detector.threshold_for("friday")), (0.5, 0.8))
        self.assertIn("“Jarvis” ou “Friday”", str(printed.call_args))


if __name__ == "__main__":
    unittest.main()
