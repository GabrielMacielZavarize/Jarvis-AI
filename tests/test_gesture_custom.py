"""Gestos novos e personalizáveis: OK, pinça, rock, joinha, tela pelos dedos, duas mãos, câmera tapada."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

import gesture_actions
import gesture_mapping
import gestures
import pc_control
import test_gestures
from gesture_actions import DesktopActions, GestureActionError, Target
from gesture_engine import Command, GestureMachine, Pose, State, classify, is_ok_sign, refine
from gesture_mapping import GESTURES, Binding, MappingError
from gestures import GestureEngine, MicSwitch, camera_covered
from hand_fixtures import FPS, POSES, end_of, hold, make_hand, move, pair
from test_gestures import NOTEBOOK, SCREENS, TOP, FakeClock, FakeInput, FakeTracker, armed_machine, kinds, play, window
from test_tools import FakeRunContext

# As mesmas travas do test_gestures: nada aqui mexe, foca, fecha, clica ou digita de verdade.
setUpModule = test_gestures.setUpModule
tearDownModule = test_gestures.tearDownModule


def gestures_of(commands: list[Command]) -> list[str]:
    return [command.name for command in commands if command.kind == "gesture" and command.name]


def play_pairs(machine: GestureMachine, timeline: list[tuple[float, Any, Any]]) -> list[Command]:
    commands: list[Command] = []
    for t, first, second in timeline:
        commands.extend(machine.step_pair(t, first, second))
    return commands


class NewPoseTests(unittest.TestCase):
    def test_three_fingers_and_rock_are_recognized(self) -> None:
        for pose, expected in (("three", Pose.THREE), ("rock", Pose.ROCK), ("rock_thumb", Pose.ROCK)):
            for options in ({}, {"world": False}, {"size": 0.1}, {"roll": 30}, {"roll": -30}):
                with self.subTest(pose=pose, **options):
                    shape = classify(make_hand(pose, **options))
                    self.assertEqual(shape.pose, Pose.NONE)  # o classify não muda: refine é que reconhece
                    self.assertEqual(refine(shape).pose, expected)

    def test_refine_keeps_every_existing_pose(self) -> None:
        for pose in POSES:
            with self.subTest(pose=pose):
                shape = classify(make_hand(pose))
                self.assertEqual(refine(shape).pose, shape.pose)

    def test_ok_sign_is_a_pinch_with_three_fingers_up(self) -> None:
        self.assertTrue(is_ok_sign(classify(make_hand("ok"))))
        self.assertTrue(is_ok_sign(classify(make_hand("ok", roll=30))))
        curled = classify(make_hand("pinch_curled"))
        self.assertEqual(curled.pose, Pose.PINCH)
        self.assertFalse(is_ok_sign(curled))
        self.assertFalse(is_ok_sign(classify(make_hand("open"))))


class OkAndPinchTests(unittest.TestCase):
    def test_ok_held_still_fires_once_and_again_after_letting_go(self) -> None:
        machine, t = armed_machine()
        first = hold("ok", t, 1.6)
        self.assertEqual(gestures_of(play(machine, first)), ["ok"])
        again = [hold("open", end_of(first), 1.0), hold("ok", end_of(first) + 1.0, 1.2)]
        self.assertEqual(gestures_of(play(machine, *again)), ["ok"])

    def test_ok_shows_a_countdown_before_firing(self) -> None:
        machine, t = armed_machine()
        play(machine, hold("ok", t, 0.6))
        status = machine.status(t + 0.6)
        self.assertEqual((status.charging, status.gesture), ("gesture", "ok"))
        self.assertGreater(status.progress, 0.3)

    def test_pinch_moving_up_and_down_changes_the_volume_step_by_step(self) -> None:
        machine, t = armed_machine()
        start = hold("pinch_curled", t, 0.4)
        up = move("pinch_curled", end_of(start), 0.6, (0.5, 0.5), (0.5, 0.25))
        rest = hold("pinch_curled", end_of(up), 0.4, center=(0.5, 0.25))
        commands = gestures_of(play(machine, start, up, rest))
        self.assertGreaterEqual(commands.count("pinca_sobe"), 3)
        self.assertNotIn("pinca_desce", commands)
        down = move("pinch_curled", end_of(rest), 0.4, (0.5, 0.25), (0.5, 0.4))
        commands = gestures_of(play(machine, down, hold("pinch_curled", end_of(down), 0.4, center=(0.5, 0.4))))
        self.assertEqual(set(commands), {"pinca_desce"})
        self.assertGreaterEqual(len(commands), 2)

    def test_ok_that_moves_changes_volume_instead_of_pausing(self) -> None:
        machine, t = armed_machine()
        start = hold("ok", t, 0.35)
        up = move("ok", end_of(start), 0.4, (0.5, 0.5), (0.5, 0.35))
        commands = gestures_of(play(machine, start, up, hold("ok", end_of(up), 1.2, center=(0.5, 0.35))))
        self.assertIn("pinca_sobe", commands)
        self.assertNotIn("ok", commands)

    def test_still_pinch_with_curled_fingers_does_nothing(self) -> None:
        machine, t = armed_machine()
        self.assertEqual(gestures_of(play(machine, hold("pinch_curled", t, 2.0))), [])

    def test_nothing_while_disarmed(self) -> None:
        machine = GestureMachine()
        commands = play(machine, hold("ok", 0.0, 1.5), hold("rock", 1.5, 1.5), hold("thumb_up", 3.0, 1.5))
        self.assertEqual(gestures_of(commands), [])

    def test_air_mouse_pinch_still_clicks(self) -> None:
        machine, t = armed_machine()
        machine.set_mouse(t, True)
        commands = play(machine, hold("open", t, 0.3), hold("pinch", t + 0.3, 0.2), hold("open", t + 0.5, 0.3))
        self.assertIn("click", kinds(commands))
        self.assertEqual(gestures_of(commands), [])


class HoldGestureTests(unittest.TestCase):
    def test_rock_and_thumbs_up_fire_after_holding(self) -> None:
        for pose, name in (("rock", "rock"), ("rock_thumb", "rock"), ("thumb_up", "joinha")):
            with self.subTest(pose=pose):
                machine, t = armed_machine()
                short = hold(pose, t, 0.5)
                self.assertEqual(gestures_of(play(machine, short)), [])
                self.assertEqual(gestures_of(play(machine, hold(pose, end_of(short), 1.5))), [name])

    def test_moving_rock_does_not_fire(self) -> None:
        machine, t = armed_machine()
        wave = move("rock", t, 1.5, (0.2, 0.5), (0.8, 0.5))
        self.assertEqual(gestures_of(play(machine, wave)), [])


class ScreenByFingersTests(unittest.TestCase):
    def test_grabbed_window_plus_fingers_picks_the_screen(self) -> None:
        for pose, number in (("point", 1), ("two", 2), ("three", 3)):
            with self.subTest(pose=pose):
                machine, t = armed_machine()
                grab = hold("fist", t, 0.5)
                fingers = hold(pose, end_of(grab), 0.9)
                commands = play(machine, grab, fingers)
                self.assertEqual(kinds(commands), ["grab", "screen"])
                self.assertEqual(commands[-1].step, number)
                self.assertEqual(machine.state, State.ARMED)

    def test_screen_countdown_is_visible(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        play(machine, grab, hold("two", end_of(grab), 0.4))
        status = machine.status(end_of(grab) + 0.4)
        self.assertEqual((status.state, status.charging, status.screen), (State.GRAB, "screen", 2))

    def test_opening_the_hand_still_maximizes_and_aimed_fingers_still_throw(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        self.assertEqual(kinds(play(machine, grab, hold("open", end_of(grab), 0.3))), ["grab", "maximize"])
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        drop = move("fist", end_of(grab), 0.3, (0.5, 0.4), (0.5, 0.75))
        out = kinds(play(machine, grab, drop, hold("two", end_of(drop), 0.3, center=(0.5, 0.75))))
        self.assertEqual(out[-1], "throw")


class TwoHandTests(unittest.TestCase):
    def test_hands_moving_apart_and_together(self) -> None:
        machine, t = armed_machine()
        commands = play_pairs(machine, pair(t, 0.5, 0.2, 0.6))
        self.assertEqual(gestures_of(commands), ["maos_afastam"])
        later = t + 2.0
        commands = play_pairs(machine, pair(later, 0.5, 0.6, 0.2))
        self.assertEqual(gestures_of(commands), ["maos_aproximam"])

    def test_slow_drift_fists_and_disarmed_do_nothing(self) -> None:
        machine, t = armed_machine()
        self.assertEqual(gestures_of(play_pairs(machine, pair(t, 3.0, 0.3, 0.45))), [])
        machine, t = armed_machine()
        self.assertEqual(gestures_of(play_pairs(machine, pair(t, 0.5, 0.2, 0.6, pose="fist"))), [])
        machine = GestureMachine()
        self.assertEqual(gestures_of(play_pairs(machine, pair(0.0, 0.5, 0.2, 0.6))), [])

    def test_back_to_one_hand_does_not_fake_a_swipe(self) -> None:
        machine, t = armed_machine()
        timeline = pair(t, 0.5, 0.25, 0.3)
        play_pairs(machine, timeline)
        # A mão que fica está noutro lugar do quadro: sem o recomeço viraria um "swipe".
        out = play(machine, hold("open", timeline[-1][0] + 1 / FPS, 1.0, center=(0.85, 0.85)))
        self.assertEqual(kinds(out), [])


class CoverCameraTests(unittest.TestCase):
    def feed(self, machine: GestureMachine, start: float, seconds: float, hand: bool, covered: bool) -> list[Command]:
        out: list[Command] = []
        for i in range(round(seconds * FPS)):
            t = start + i / FPS
            out.extend(machine.step(t, make_hand("open") if hand else None))
            out.extend(machine.cover(t, covered))
        return out

    def test_palm_over_the_lens_fires_once_even_disarmed(self) -> None:
        machine = GestureMachine()
        self.feed(machine, 0.0, 0.5, hand=True, covered=False)
        out = self.feed(machine, 0.5, 2.5, hand=False, covered=True)
        self.assertEqual(gestures_of(out), ["tapar_camera"])
        self.feed(machine, 3.0, 0.5, hand=True, covered=False)
        self.assertEqual(gestures_of(self.feed(machine, 3.5, 1.5, hand=False, covered=True)), ["tapar_camera"])

    def test_countdown_before_muting(self) -> None:
        machine = GestureMachine()
        self.feed(machine, 0.0, 0.5, hand=True, covered=False)
        self.feed(machine, 0.5, 0.6, hand=False, covered=True)
        status = machine.status(1.1)
        self.assertEqual((status.charging, status.gesture), ("gesture", "tapar_camera"))

    def test_lights_off_or_a_closed_lens_do_nothing(self) -> None:
        machine = GestureMachine()
        self.assertEqual(gestures_of(self.feed(machine, 0.0, 3.0, hand=False, covered=True)), [])
        machine = GestureMachine()
        self.feed(machine, 0.0, 0.5, hand=True, covered=False)
        self.feed(machine, 0.5, 3.0, hand=False, covered=False)  # a mão saiu; a sala continua clara
        self.assertEqual(gestures_of(self.feed(machine, 3.5, 3.0, hand=False, covered=True)), [])

    def test_short_cover_does_nothing(self) -> None:
        machine = GestureMachine()
        self.feed(machine, 0.0, 0.5, hand=True, covered=False)
        self.feed(machine, 0.5, 0.6, hand=False, covered=True)
        self.assertEqual(gestures_of(self.feed(machine, 1.1, 1.0, hand=True, covered=False)), [])

    def test_covered_frames(self) -> None:
        rng = np.random.default_rng(3)
        scene = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
        self.assertFalse(camera_covered(scene))
        gradient = np.tile(np.linspace(0, 255, 640, dtype=np.uint8)[None, :, None], (360, 1, 3))
        self.assertFalse(camera_covered(gradient))
        self.assertTrue(camera_covered(np.zeros((360, 640, 3), dtype=np.uint8)))
        dark = rng.integers(0, 40, (360, 640, 3), dtype=np.uint8)  # palma encostada, com um pouco de luz
        self.assertTrue(camera_covered(dark))
        skin = np.full((360, 640, 3), (120, 150, 200), dtype=np.uint8)  # palma clara e desfocada
        self.assertTrue(camera_covered(skin))


class MappingTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "gestos.json"

    def test_sensible_defaults(self) -> None:
        bindings = gesture_mapping.load_bindings(self.path)
        self.assertEqual(set(bindings), set(GESTURES))
        self.assertEqual(bindings["ok"], Binding("acao", "play_pause"))
        self.assertEqual(bindings["pinca_sobe"], Binding("acao", "volume_up"))
        self.assertEqual(bindings["pinca_desce"], Binding("acao", "volume_down"))
        self.assertEqual(bindings["rock"], Binding("layout", "trabalho"))
        self.assertEqual(bindings["tapar_camera"], Binding("acao", "mic_toggle"))
        self.assertEqual(bindings["maos_afastam"], Binding("acao", "maximize"))
        self.assertEqual(bindings["maos_aproximam"], Binding("acao", "restore"))
        self.assertIsNone(bindings["joinha"])

    def test_set_explain_list_and_reset(self) -> None:
        result = gesture_mapping.set_binding("joinha", "action", "pausa a música", self.path)
        self.assertIn("tocar/pausar", result)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"joinha": {"tipo": "acao", "acao": "play_pause"}})
        self.assertEqual(gesture_mapping.binding_for("joinha", self.path), Binding("acao", "play_pause"))
        gesture_mapping.set_binding("🤘", "app", "Spotify", self.path)
        self.assertIn("abrir o app Spotify", gesture_mapping.explain("o rock", self.path))
        gesture_mapping.set_binding("ok", "keys", "ctrl shift m", self.path)
        self.assertEqual(gesture_mapping.binding_for("ok", self.path), Binding("atalho", "Ctrl+Shift+M", (0x11, 0x10, 0x4D)))
        gesture_mapping.set_binding("afastar as mãos", "site", "youtube.com", self.path)
        gesture_mapping.set_binding("tapar a câmera", "none", None, self.path)
        listing = gesture_mapping.list_gestures(self.path)
        self.assertIn("joinha (👍): tocar/pausar a mídia", listing)
        self.assertIn("tapar a câmera: nada", listing)
        self.assertIn("punho", listing)  # os fixos também aparecem
        self.assertIn("voltou ao padrão", gesture_mapping.reset_binding("rock", self.path))
        self.assertEqual(gesture_mapping.binding_for("rock", self.path), Binding("layout", "trabalho"))
        gesture_mapping.reset_binding(None, self.path)
        self.assertIsNone(gesture_mapping.binding_for("joinha", self.path))

    def test_dangerous_actions_never_go_on_a_gesture(self) -> None:
        refused = [
            ("action", "fechar a janela"),
            ("action", "digitar meu email"),
            ("keys", "alt+f4"),
            ("keys", "ctrl+w"),
            ("keys", "ctrl+shift+w"),
            ("keys", "shift+delete"),
            ("keys", "a"),  # tecla solta digitaria
            ("keys", "enter"),
            ("app", "desinstalar programas"),
        ]
        for kind, value in refused:
            with self.subTest(value=value):
                with self.assertRaises(MappingError):
                    gesture_mapping.set_binding("joinha", kind, value, self.path)
        self.assertFalse(self.path.exists())

    def test_fixed_and_unknown_gestures(self) -> None:
        with self.assertRaises(MappingError) as error:
            gesture_mapping.set_binding("punho", "action", "play_pause", self.path)
        self.assertIn("fixo", str(error.exception))
        with self.assertRaises(MappingError):
            gesture_mapping.explain("estrela", self.path)
        with self.assertRaises(MappingError) as error:
            gesture_mapping.explain("pinça", self.path)
        self.assertIn("Qual deles", str(error.exception))

    def test_hand_edited_file_is_validated(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "joinha": {"tipo": "atalho", "teclas": "alt+f4"},
                    "rock": {"tipo": "acao", "acao": "next"},
                    "estrela": {"tipo": "acao", "acao": "next"},
                    "ok": "qualquer coisa",
                }
            ),
            encoding="utf-8",
        )
        bindings = gesture_mapping.load_bindings(self.path)
        self.assertIsNone(bindings["joinha"])  # o atalho perigoso foi ignorado
        self.assertEqual(bindings["rock"], Binding("acao", "next"))
        self.assertEqual(bindings["ok"], Binding("acao", "play_pause"))  # inválido: fica o padrão
        self.path.write_text("{ quebrado", encoding="utf-8")
        self.assertEqual(gesture_mapping.load_bindings(self.path)["rock"], Binding("layout", "trabalho"))

    def test_shortcut_parsing(self) -> None:
        self.assertEqual(gesture_mapping.parse_keys("Ctrl Alt T"), ((0x11, 0x12, 0x54), "Ctrl+Alt+T"))
        self.assertEqual(gesture_mapping.parse_keys("win + d"), ((0x5B, 0x44), "Win+D"))
        self.assertEqual(gesture_mapping.parse_keys("F5"), ((0x74,), "F5"))
        self.assertEqual(gesture_mapping.parse_keys("shift ctrl m"), ((0x11, 0x10, 0x4D), "Ctrl+Shift+M"))
        with self.assertRaises(MappingError):
            gesture_mapping.parse_keys("ctrl+tecla mágica")


class FakeBindings:
    def __init__(self, **bindings: Binding) -> None:
        self.bindings = bindings

    def __call__(self, gesture: str) -> Binding | None:
        return self.bindings.get(gesture)


class PairTracker(FakeTracker):
    def __init__(self, frames: list[tuple[Any, Any]]) -> None:
        super().__init__([first for first, _ in frames])
        self.seconds = [second for _, second in frames]
        self._other: Any = None

    def detect(self, frame: np.ndarray, t: float) -> Any:
        self._other = self.seconds.pop(0) if self.seconds else None
        return super().detect(frame, t)

    def other_hands(self) -> list[Any]:
        return [self._other] if self._other is not None else []


def run_frames(
    hands: list[tuple[Any, Any]], actions: Any, images: list[np.ndarray] | None = None, **kwargs: Any
) -> tuple[GestureEngine, list[dict[str, Any]]]:
    clock = FakeClock()
    events: list[dict[str, Any]] = []
    textured = np.random.default_rng(1).integers(0, 255, (360, 640, 3), dtype=np.uint8)

    def frames() -> Any:
        for index in range(len(hands)):
            yield images[index] if images else textured
            clock.tick()

    engine = GestureEngine(frames(), actions, tracker=PairTracker(hands), emit=events.append, clock=clock, **kwargs)
    engine.run(threading.Event())
    return engine, events


def single(*timelines: list[tuple[float, Any]]) -> list[tuple[Any, Any]]:
    return [(hand, None) for timeline in timelines for _, hand in timeline]


class EngineDispatchTests(unittest.TestCase):
    def actions(self) -> MagicMock:
        actions = MagicMock()
        actions.grab.return_value = Target(window=window(), monitor=TOP, browser=False)
        for name in ("media", "volume", "layout", "launch", "site", "shortcut", "focus_window", "to_screen"):
            getattr(actions, name).return_value = "ok"
        return actions

    def test_each_binding_kind_reaches_its_action(self) -> None:
        cases = [
            (Binding("acao", "play_pause"), "media", ("play_pause",)),
            (Binding("acao", "volume_down"), "volume", ("down",)),
            (Binding("acao", "maximize"), "focus_window", ("maximize",)),
            (Binding("acao", "next_tab"), "tab", (1,)),
            (Binding("acao", "undo"), "undo", ()),
            (Binding("layout", "trabalho"), "layout", ("trabalho",)),
            (Binding("app", "spotify"), "launch", ("spotify",)),
            (Binding("site", "youtube.com"), "site", ("youtube.com",)),
            (Binding("atalho", "Ctrl+Shift+M", (0x11, 0x10, 0x4D)), "shortcut", ((0x11, 0x10, 0x4D), "Ctrl+Shift+M")),
        ]
        for binding, method, args in cases:
            with self.subTest(binding=binding):
                actions = self.actions()
                engine = GestureEngine([], actions, tracker=FakeTracker([]), bindings=FakeBindings(rock=binding))
                engine._dispatch(Command("gesture", name="rock"), 0.0)
                engine._executor.shutdown(wait=True)
                getattr(actions, method).assert_called_once_with(*args)
                self.assertTrue(engine._flash[0])

    def test_unbound_gesture_does_nothing_and_mic_uses_the_switch(self) -> None:
        actions = self.actions()
        mic = MagicMock(return_value="Microfone do Jarvis mudo.")
        engine = GestureEngine(
            [], actions, tracker=FakeTracker([]), bindings=FakeBindings(tapar_camera=Binding("acao", "mic_toggle")), mic=mic
        )
        engine._dispatch(Command("gesture", name="joinha"), 0.0)
        engine._dispatch(Command("gesture", name="tapar_camera"), 0.0)
        engine._executor.shutdown(wait=True)
        mic.assert_called_once_with()
        self.assertEqual([call[0] for call in actions.method_calls], [])

    def test_rock_from_the_camera_applies_the_layout(self) -> None:
        actions = self.actions()
        _, events = run_frames(
            single(hold("open", 0.0, 0.3), hold("rock", 0.3, 1.5)), actions, armed=True, bindings=FakeBindings(rock=Binding("layout", "trabalho"))
        )
        actions.layout.assert_called_once_with("trabalho")
        action = next(event for event in events if event["event"] == "action")
        self.assertEqual((action["action"], action["ok"]), ("rock", True))

    def test_fingers_send_the_grabbed_window_to_that_screen(self) -> None:
        actions = self.actions()
        grab = hold("fist", 0.0, 0.5)
        run_frames(single(grab, hold("three", end_of(grab), 0.9)), actions, armed=True)
        actions.to_screen.assert_called_once()
        target, number = actions.to_screen.call_args.args
        self.assertEqual((target.window.hwnd, number), (10, 3))
        actions.maximize.assert_not_called()

    def test_two_hands_from_the_camera(self) -> None:
        actions = self.actions()
        hands = single(hold("open", 0.0, 0.3)) + [(a, b) for _, a, b in pair(0.3, 0.5, 0.2, 0.6)]
        run_frames(hands, actions, armed=True, bindings=FakeBindings(maos_afastam=Binding("acao", "maximize")))
        actions.focus_window.assert_called_once_with("maximize")

    def test_covering_the_camera_toggles_the_mic(self) -> None:
        actions = self.actions()
        mic = MagicMock(return_value="Microfone do Jarvis mudo.")
        rng = np.random.default_rng(2)
        lit = [rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)] * 15
        dark = [np.zeros((360, 640, 3), dtype=np.uint8)] * 45
        hands = single(hold("open", 0.0, 0.5)) + [(None, None)] * 45
        run_frames(hands, actions, images=lit + dark, mic=mic, bindings=FakeBindings(tapar_camera=Binding("acao", "mic_toggle")))
        mic.assert_called_once_with()

    def test_overlay_names_the_action_before_running_it(self) -> None:
        actions = self.actions()
        engine = GestureEngine([], actions, tracker=FakeTracker([]), clock=lambda: 0.0, bindings=FakeBindings(rock=Binding("layout", "trabalho")))
        engine.machine.arm(0.0)
        timeline = hold("rock", 0.0, 0.6)
        self.assertEqual(gestures_of(play(engine.machine, timeline)), [])
        view = engine.view(timeline[-1][0])
        self.assertEqual(view.title, "APLICAR O LAYOUT 'TRABALHO'")
        self.assertIn("rock", view.detail)
        self.assertGreater(view.progress, 0.15)

        engine = GestureEngine([], actions, tracker=FakeTracker([]), clock=lambda: 0.0)
        engine.machine.arm(0.0)
        grab = hold("fist", 0.0, 0.5)
        for command in play(engine.machine, grab):
            engine._dispatch(command, 0.5)
        play(engine.machine, hold("two", end_of(grab), 0.3))
        view = engine.view(end_of(grab) + 0.3)
        self.assertEqual(view.title, "→ TELA 2")

    def test_overlay_flashes_the_label_while_running(self) -> None:
        actions = self.actions()
        started = threading.Event()
        release = threading.Event()

        def slow(_name: str) -> str:
            started.set()
            release.wait(2)
            return "Volume em 45%."

        actions.volume.side_effect = slow
        engine = GestureEngine([], actions, tracker=FakeTracker([]), clock=lambda: 0.0, bindings=FakeBindings(pinca_sobe=Binding("acao", "volume_up")))
        engine._dispatch(Command("gesture", name="pinca_sobe"), 0.0)
        started.wait(2)
        self.assertEqual(engine.view(0.0).title, "Aumentar o volume…")
        release.set()
        engine._executor.shutdown(wait=True)
        self.assertEqual(engine.view(0.0).title, "Volume em 45%.")


class ActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input = FakeInput()
        self.actions = DesktopActions(self.input)
        guard = patch("win_desktop.monitors", return_value=SCREENS)
        guard.start()
        self.addCleanup(guard.stop)

    def test_media_keys_and_shortcuts_go_through_send_input(self) -> None:
        self.assertEqual(self.actions.media("play_pause"), "Tocar/pausar.")
        self.actions.media("next")
        self.assertIn("Ctrl+Shift+M", self.actions.shortcut((0x11, 0x10, 0x4D), "Ctrl+Shift+M"))
        self.assertEqual(self.input.calls, [("keys", 0xB3), ("keys", 0xB0), ("keys", 0x11, 0x10, 0x4D)])

    def test_volume_layout_app_and_site_use_pc_control(self) -> None:
        with patch("pc_control.change_volume", return_value=45) as volume:
            self.assertEqual(self.actions.volume("up"), "Volume em 45%.")
        volume.assert_called_once_with("up", gesture_actions.VOLUME_STEP)
        with patch("pc_control.apply_layout", side_effect=pc_control.PCControlError("Não há layout 'trabalho'.")):
            with self.assertRaises(GestureActionError) as error:
                self.actions.layout("trabalho")
        self.assertIn("trabalho", str(error.exception))
        with patch("pc_control.launch_app", return_value="Abri o Spotify.") as launch:
            self.assertEqual(self.actions.launch("spotify"), "Abri o Spotify.")
        launch.assert_called_once_with("spotify")
        with patch("pc_control.open_url", return_value="Abri YouTube no navegador.") as open_url:
            self.actions.site("youtube")
        self.assertIn("youtube.com", open_url.call_args.args[1])

    def test_to_screen_uses_the_identify_number_and_checks_where_it_landed(self) -> None:
        target = Target(window=window(), monitor=TOP, browser=False)
        with (
            patch("gesture_actions._window_exists", return_value=True),
            patch("pc_control._move_window", return_value="'Bloco de notas' agora está na tela 2.") as move_window,
        ):
            self.assertIn("tela 2", self.actions.to_screen(target, 2))
            move_window.assert_called_once_with(target.window, NOTEBOOK)
            with self.assertRaises(GestureActionError):
                self.actions.to_screen(target, 7)
        with (
            patch("gesture_actions._window_exists", return_value=True),
            patch("pc_control._move_window", return_value="Tentei levar 'Bloco de notas' para a tela 2, mas ela ficou na tela 1."),
        ):
            with self.assertRaises(GestureActionError):
                self.actions.to_screen(target, 2)

    def test_two_hands_maximize_and_restore_the_focused_window(self) -> None:
        target = Target(window=window(), monitor=TOP, browser=False)
        with (
            patch.object(self.actions, "grab", return_value=target),
            patch("gesture_actions._window_exists", return_value=True),
            patch("gesture_actions._is_maximized", return_value=False),
            patch("pc_control._remember_position"),
            patch("win_desktop.show_window") as show,
            patch("win_desktop.bring_to_front", return_value=True),
        ):
            self.assertIn("estendida", self.actions.focus_window("maximize"))
            self.assertIn("já está restaurada", self.actions.focus_window("restore"))
        show.assert_called_once()
        with (
            patch.object(self.actions, "grab", return_value=target),
            patch("gesture_actions._is_maximized", return_value=True),
            patch("win_desktop.show_window") as show,
        ):
            self.assertIn("restaurada", self.actions.focus_window("restore"))
        show.assert_called_once_with(10, gesture_actions.win_desktop.SW_RESTORE)


class FakeInputStream:
    def __init__(self) -> None:
        self.audio_enabled = True

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = enabled


class MicAndVoiceTests(unittest.TestCase):
    def test_mic_switch_needs_a_session_and_toggles_on_its_loop(self) -> None:
        switch = MicSwitch()
        with self.assertRaises(GestureActionError):
            switch.toggle()
        session = MagicMock()
        session.input = FakeInputStream()
        loop = asyncio.new_event_loop()
        try:
            switch.bind(session, loop)
            self.assertIn("mudo", switch.toggle())
            loop.run_until_complete(asyncio.sleep(0))
            self.assertFalse(session.input.audio_enabled)
            self.assertIn("ouvindo", switch.toggle())
            loop.run_until_complete(asyncio.sleep(0))
            self.assertTrue(session.input.audio_enabled)
        finally:
            loop.close()
        switch.unbind()
        with self.assertRaises(GestureActionError):
            switch.toggle()

    def test_voice_tool_lists_explains_and_changes_gestures(self) -> None:
        _control, shortcuts = gestures.build_gesture_tools()
        with tempfile.TemporaryDirectory() as folder, patch.object(gesture_mapping, "GESTURES_FILE", Path(folder) / "gestos.json"):
            context = FakeRunContext()
            result = asyncio.run(shortcuts(context, action="set", gesture="joinha", kind="action", value="play_pause"))
            self.assertIn("joinha", result)
            self.assertIn("tocar/pausar", asyncio.run(shortcuts(context, action="explain", gesture="joinha")))
            self.assertIn("aplicar o layout 'trabalho'", asyncio.run(shortcuts(context, action="explain", gesture="rock")))
            self.assertIn("Gestos personalizáveis", asyncio.run(shortcuts(context, action="list")))
            refusal = asyncio.run(shortcuts(context, action="set", gesture="rock", kind="keys", value="alt+f4"))
            self.assertIn("polegar para baixo", refusal)
            self.assertIn("Diga o que o gesto", asyncio.run(shortcuts(context, action="set", gesture="rock")))
            self.assertIn("voltou ao padrão", asyncio.run(shortcuts(context, action="reset", gesture="joinha")))


if __name__ == "__main__":
    unittest.main()
