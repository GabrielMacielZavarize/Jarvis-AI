"""Precisão dos gestos: suavização, histerese, qualidade dos quadros, calibração e replay de traces."""

from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

import gesture_calibration
import gesture_engine
from gesture_actions import Target
from gesture_engine import (
    CALIBRATED_FIELDS,
    Command,
    GestureMachine,
    Hand,
    LandmarkFilter,
    Pose,
    State,
    Tuning,
    classify,
    hand_quality,
    load_trace,
)
from gestures import GestureEngine, confidence_line, hand_from_result
from hand_fixtures import FPS, absent, end_of, hold, make_custom, make_hand, move, shaky, trace_lines, with_score

TRACES = Path(__file__).resolve().parent / "traces"
FOUR = ("index", "middle", "ring", "pinky")
_GUARDS: list[Any] = []


def setUpModule() -> None:
    # A calibração pessoal de quem roda os testes não pode mudar o resultado das mãos sintéticas.
    guard = patch("gesture_engine.CALIBRATION_FILE", Path(tempfile.gettempdir()) / "jarvis-sem-calibracao.json")
    guard.start()
    _GUARDS.append(guard)


def tearDownModule() -> None:
    for guard in reversed(_GUARDS):
        guard.stop()
    _GUARDS.clear()


def play(machine: GestureMachine, *timelines: list[tuple[float, Any]]) -> list[Command]:
    commands: list[Command] = []
    for timeline in timelines:
        for t, hand in timeline:
            commands.extend(machine.step(t, hand))
    return commands


def kinds(commands: list[Command]) -> list[str]:
    return [command.kind for command in commands if command.kind != "mouse_move"]


def replay(lines: list[str], machine: GestureMachine | None = None) -> tuple[GestureMachine, list[Command]]:
    """A trace (JSON lines of --trace) through a fresh GestureMachine, armed by its first frames."""
    machine = machine or GestureMachine()
    return machine, play(machine, load_trace(lines))


def poses_seen(machine: GestureMachine, timeline: list[tuple[float, Any]]) -> list[Pose]:
    seen = []
    for t, hand in timeline:
        machine.step(t, hand)
        if not seen or seen[-1] != machine.pose:
            seen.append(machine.pose)
    return seen


# ───────────────────────── suavização ─────────────────────────


class LandmarkFilterTests(unittest.TestCase):
    def test_takes_the_tremor_out_of_a_still_hand(self) -> None:
        timeline = shaky(hold("open", 0.0, 3.0), sigma=0.004, seed=3)
        smoother = LandmarkFilter()
        raw = np.array([hand.points[8, :2] for _, hand in timeline])
        smooth = np.array([smoother(t, hand).points[8, :2] for t, hand in timeline])
        self.assertLess(smooth[30:].std(axis=0).max(), raw[30:].std(axis=0).max() / 2)

    def test_follows_a_fast_move_without_lagging(self) -> None:
        smoother = LandmarkFilter()
        timeline = hold("open", 0.0, 1.0, (0.3, 0.5)) + move("open", 1.0, 0.15, (0.3, 0.5), (0.7, 0.5))
        timeline += hold("open", end_of(timeline), 0.2, (0.7, 0.5))
        out = [smoother(t, hand) for t, hand in timeline]
        settled = out[len(timeline) - 6 + 3]  # 3 quadros (0,1 s) depois de a mão parar
        self.assertAlmostEqual(float(settled.points[9, 0]), float(timeline[-1][1].points[9, 0]), delta=0.02)

    def test_world_points_are_smoothed_too_and_reset_starts_fresh(self) -> None:
        smoother = LandmarkFilter()
        first = make_hand("open")
        smoother(0.0, first)
        moved = make_hand("open", (0.6, 0.5))
        out = smoother(1 / FPS, moved)
        self.assertIsNotNone(out.world)
        smoother.reset()
        self.assertIs(smoother(2 / FPS, moved), moved)

    def test_tremor_does_not_break_poses_or_arming(self) -> None:
        machine = GestureMachine()
        commands = play(machine, shaky(hold("open", 0.0, 1.6), sigma=0.005, seed=1))
        self.assertEqual(kinds(commands), ["armed"])
        timeline = shaky(hold("point", 1.6, 2.0), sigma=0.005, seed=2)
        self.assertEqual(poses_seen(machine, timeline)[-1], Pose.POINT)
        self.assertEqual(machine.state, State.MOUSE)

    def test_air_mouse_holds_still_under_tremor_and_follows_a_fast_move(self) -> None:
        machine = GestureMachine()
        machine.set_mouse(0.0, True)
        still = shaky(hold("point", 0.0, 2.0), sigma=0.004, seed=5)
        commands = play(machine, still)
        points = np.array([c.point for c in commands if c.kind == "mouse_move"][-30:])
        self.assertLess(points.std(axis=0).max(), 0.004)  # o cursor não treme junto com a mão
        start = end_of(still)
        fast = move("point", start, 0.2, (0.5, 0.5), (0.65, 0.5))
        after = hold("point", end_of(fast), 0.15, (0.65, 0.5))
        moves = [c.point for c in play(machine, fast, after) if c.kind == "mouse_move"]
        target = (0.65 - 0.2) / 0.6  # base do indicador na caixa do mouse, aproximadamente
        self.assertGreater(moves[-1][0], target - 0.12)
        self.assertNotIn("click", kinds(commands))


# ───────────────────────── histerese ─────────────────────────


class HysteresisTests(unittest.TestCase):
    def test_single_frame_flickers_do_not_change_the_pose(self) -> None:
        # Um quadro errado a cada quatro (detector em dúvida) não derruba a mão aberta.
        machine = GestureMachine()
        timeline = hold("open", 0.0, 0.5)
        t = end_of(timeline)
        timeline += [(t + i / FPS, make_hand("fist" if i % 4 == 0 else "open")) for i in range(40)]
        self.assertEqual(poses_seen(machine, timeline), [Pose.NONE, Pose.OPEN])

    def test_entering_takes_more_frames_than_leaving(self) -> None:
        tuning = Tuning()
        self.assertLess(tuning.pose_exit_frames, tuning.pose_enter_frames)
        machine = GestureMachine()
        play(machine, hold("open", 0.0, 0.5))
        t = 0.5
        frames = 0
        while machine.pose == Pose.OPEN:
            machine.step(t, make_hand("fist"))
            t += 1 / FPS
            frames += 1
        self.assertEqual(frames, tuning.pose_exit_frames)
        self.assertEqual(machine.pose, Pose.NONE)
        while machine.pose != Pose.FIST:
            machine.step(t, make_hand("fist"))
            t += 1 / FPS
            frames += 1
        self.assertGreaterEqual(frames, tuning.pose_enter_frames)

    def test_bad_frames_do_not_count_toward_a_new_pose(self) -> None:
        machine = GestureMachine()
        play(machine, hold("open", 0.0, 0.5))
        play(machine, with_score(hold("fist", 0.5, 0.25), 0.2))  # quadros sem confiança: ignorados
        self.assertEqual(machine.pose, Pose.OPEN)


# ───────────────────────── qualidade e distâncias normalizadas ─────────────────────────


class QualityTests(unittest.TestCase):
    def test_reasons(self) -> None:
        self.assertTrue(hand_quality(make_hand("open")).ok)
        self.assertEqual(hand_quality(replace(make_hand("open"), score=0.3)).reason, "confiança")
        self.assertEqual(hand_quality(make_hand("open", (1.0, 0.5))).reason, "borda")
        self.assertEqual(hand_quality(make_hand("open", size=0.3), previous_palm=0.18).reason, "salto")
        self.assertTrue(hand_quality(make_hand("open", size=0.19), previous_palm=0.18).ok)

    def test_a_palm_size_glitch_is_dropped_but_a_real_approach_is_followed(self) -> None:
        machine = GestureMachine()
        play(machine, hold("open", 0.0, 0.5))
        machine.step(0.5, make_hand("fist", size=0.32))
        self.assertEqual(machine.quality.reason, "salto")
        approach = [(0.53 + i / FPS, make_hand("open", size=0.18 * 1.04 ** i)) for i in range(15)]
        play(machine, approach)
        self.assertTrue(machine.quality.ok)
        self.assertEqual(machine.pose, Pose.OPEN)

    def test_poses_hold_near_and_far_from_the_camera(self) -> None:
        for pose in ("open", "fist", "point", "two", "pinch", "loose_fist", "thumb_down_relaxed"):
            expected = {"loose_fist": Pose.FIST, "thumb_down_relaxed": Pose.THUMB_DOWN}.get(pose) or Pose(pose)
            for size in (0.07, 0.35):
                for world in (True, False):
                    with self.subTest(pose=pose, size=size, world=world):
                        self.assertEqual(classify(make_hand(pose, size=size, world=world)).pose, expected)

    def test_tab_swipe_scales_with_the_hand_size(self) -> None:
        def swipe(size: float, distance: float) -> list[str]:
            machine = GestureMachine()
            machine.arm(0.0)
            ready = hold("two", 0.0, 0.5, (0.4, 0.5), size=size)
            stroke = move("two", end_of(ready), 0.3, (0.4, 0.5), (0.4 + distance, 0.5), size=size)
            return kinds(play(machine, ready, stroke))

        self.assertIn("tab", swipe(0.18, 0.2))
        # Com a mão bem perto da câmera o mesmo deslocamento no quadro é um movimento pequeno de verdade.
        self.assertNotIn("tab", swipe(0.3, 0.2))
        self.assertIn("tab", swipe(0.3, 0.35))

    def test_still_hand_near_the_camera_arms_despite_bigger_jitter(self) -> None:
        machine = GestureMachine()
        commands = play(machine, shaky(hold("open", 0.0, 1.8, size=0.3), sigma=0.008, seed=4))
        self.assertEqual(kinds(commands), ["armed"])


# ───────────────────────── traces de casos difíceis ─────────────────────────


def armed_trace(start_pose: str = "open") -> tuple[list, float]:
    timeline = hold(start_pose, 0.0, 1.6)
    return timeline, end_of(timeline)


class HardTraceTests(unittest.TestCase):
    """Synthetic traces in the --trace format replayed through the GestureMachine."""

    def test_loose_fist_carrying_a_window_never_reads_as_a_pinch(self) -> None:
        # O polegar por cima do indicador deixa a "pinça" < 0,3; se virasse PINCH, soltaria a janela.
        timeline, t = armed_trace()
        grab = hold("fist", t, 0.5)
        t = end_of(grab)
        loosen = shaky(move("loose_fist", t, 0.8, (0.5, 0.5), (0.5, 0.2)), sigma=0.003, seed=8)
        t = end_of(loosen)
        settle = shaky(hold("loose_fist", t, 0.4, (0.5, 0.2)), sigma=0.003, seed=9)
        release = hold("open", end_of(settle), 0.4, (0.5, 0.2))
        frames = timeline + grab + loosen + settle + release
        self.assertLess(classify(make_hand("loose_fist")).pinch, 0.3)
        machine, commands = replay(trace_lines(frames))
        self.assertEqual(kinds(commands), ["armed", "grab", "aim", "throw"])
        self.assertEqual(commands[-1].direction, "up")

    def test_loose_fist_alone_grabs_instead_of_pinching(self) -> None:
        timeline, t = armed_trace()
        frames = timeline + shaky(hold("loose_fist", t, 0.8), sigma=0.003, seed=10)
        machine, commands = replay(trace_lines(frames))
        self.assertEqual(kinds(commands), ["armed", "grab"])
        self.assertNotIn(Pose.PINCH, [machine.pose])

    def hand_leaving_the_frame(self) -> list[str]:
        timeline, t = armed_trace()
        grab = hold("fist", t, 0.5, (0.6, 0.5))
        t = end_of(grab)
        out = move("fist", t, 0.25, (0.6, 0.5), (1.0, 0.5))  # metade da mão já fora do quadro
        t = end_of(out)
        # Na borda o MediaPipe ainda chuta uma mão "aberta", com pouca confiança, antes de perdê-la.
        garbled = with_score(hold("open", t, 0.3, (1.02, 0.5)), 0.4)
        gone = absent(end_of(garbled), 1.0)
        return trace_lines(timeline + grab + out + garbled + gone)

    def test_hand_leaving_the_frame_cancels_instead_of_throwing(self) -> None:
        _, commands = replay(self.hand_leaving_the_frame())
        names = kinds(commands)
        self.assertNotIn("throw", names)
        self.assertIn("cancel", names)

    def test_without_the_quality_gate_the_same_trace_would_throw(self) -> None:
        loose = GestureMachine(Tuning(min_score=0.0, min_inside=0.0))
        _, commands = replay(self.hand_leaving_the_frame(), loose)
        self.assertIn("throw", kinds(commands))

    def test_tremor_while_holding_a_fist_does_not_aim_or_release(self) -> None:
        timeline, t = armed_trace()
        frames = timeline + shaky(hold("fist", t, 2.0), sigma=0.006, seed=11)
        _, commands = replay(trace_lines(frames))
        self.assertEqual(kinds(commands), ["armed", "grab"])

    def test_fast_throw_is_not_delayed_by_the_smoothing(self) -> None:
        timeline, t = armed_trace()
        grab = hold("fist", t, 0.4)
        fast = move("fist", end_of(grab), 0.15, (0.5, 0.5), (0.5, 0.2))
        opened_at = end_of(fast)
        release = hold("open", opened_at, 0.5, (0.5, 0.2))
        machine = GestureMachine()
        thrown_at = None
        for at, hand in load_trace(trace_lines(timeline + grab + fast + release)):
            if any(c.kind == "throw" for c in machine.step(at, hand)) and thrown_at is None:
                thrown_at = at
        self.assertIsNotNone(thrown_at)
        self.assertLess(thrown_at - opened_at, 0.25)

    def test_recorded_traces_in_the_traces_folder(self) -> None:
        """Real traces (python gestures.py --trace) with a {"expect": [...]} first line."""
        files = sorted(TRACES.glob("*.jsonl")) if TRACES.exists() else []
        if not files:
            self.skipTest("nenhum trace gravado em tests/traces/")
        for path in files:
            lines = path.read_text(encoding="utf-8").splitlines()
            header = json.loads(lines[0]) if lines else {}
            if "expect" not in header:
                continue
            with self.subTest(trace=path.name):
                _, commands = replay(lines, GestureMachine(Tuning(**header.get("tuning", {}))))
                self.assertEqual(kinds(commands), header["expect"])


class TraceFormatTests(unittest.TestCase):
    def test_engine_trace_round_trips_into_the_machine(self) -> None:
        timeline = hold("open", 0.0, 1.6) + hold("fist", 1.6, 0.6)
        hands = [hand for _, hand in timeline]
        tracker = MagicMock()
        tracker.detect.side_effect = hands
        tracker.other_hands.return_value = []
        clock = {"t": 0.0}

        def frames() -> Any:
            for _ in hands:
                yield np.zeros((360, 640, 3), dtype=np.uint8)
                clock["t"] += 1 / FPS

        actions = MagicMock()
        actions.grab.return_value = Target(window=MagicMock(title="x"), monitor=None, browser=False)
        trace = io.StringIO()
        engine = GestureEngine(frames(), actions, tracker=tracker, clock=lambda: clock["t"], trace=trace)
        engine.run(threading.Event())
        rows = [json.loads(line) for line in trace.getvalue().splitlines()]
        self.assertIn("quality", rows[-1])
        self.assertEqual(rows[-1]["pose"], "fist")
        recorded = [kind for row in rows for kind in row.get("commands", [])]
        _, commands = replay(trace.getvalue().splitlines())
        self.assertEqual(kinds(commands), recorded)
        self.assertEqual(recorded, ["armed", "grab"])

    def test_old_traces_without_aspect_or_score_still_load(self) -> None:
        hand = make_hand("open")
        row = {"t": 1.0, "points": hand.points.round(3).tolist()}
        frames = load_trace([json.dumps({"expect": []}), json.dumps(row), json.dumps({"t": 1.03}), ""])
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0][1].score, 1.0)
        self.assertIsNone(frames[1][1])
        self.assertEqual(classify(frames[0][1]).pose, Pose.OPEN)


# ───────────────────────── calibração ─────────────────────────


STIFF = (10, 40, 35)  # dedos que não esticam de todo: curva de ~75°, acima do padrão de 70°


def stiff_samples(rng: np.random.Generator) -> dict[str, list[Hand]]:
    def jitter() -> dict[str, Any]:
        return {"center": (0.5 + rng.normal(0, 0.01), 0.5 + rng.normal(0, 0.01)), "size": 0.15 + rng.normal(0, 0.004)}

    def fingers(extended: set[str]) -> dict[str, tuple[float, float, float]]:
        return {f: STIFF if f in extended else (80, 100, 60) for f in FOUR}

    samples = {
        "open": [make_custom(fingers(set(FOUR)), "out", **jitter()) for _ in range(30)],
        "fist": [make_hand("loose_fist", **jitter()) for _ in range(30)],
        "pinch": [make_hand("pinch", **jitter()) for _ in range(30)],
        "point": [make_custom(fingers({"index"}), "tucked", **jitter()) for _ in range(30)],
        "two": [make_custom(fingers({"index", "middle"}), "tucked", **jitter()) for _ in range(30)],
        "thumb_down": [make_hand("thumb_down_relaxed", **jitter()) for _ in range(30)],
    }
    return samples


class CalibrationTests(unittest.TestCase):
    def test_learns_a_hand_that_the_defaults_do_not_read(self) -> None:
        samples = stiff_samples(np.random.default_rng(0))
        tuning, report = gesture_calibration.calibrate(samples)
        self.assertLess(report["accuracy_before"]["open"], 0.5)
        for key, value in report["accuracy_after"].items():
            with self.subTest(pose=key):
                self.assertGreaterEqual(value, 0.95)
        self.assertGreater(tuning.extend_bend, 75)
        self.assertLess(tuning.extend_bend, tuning.fold_bend)
        self.assertLess(tuning.pinch_on, tuning.closing_pinch)
        self.assertLess(tuning.closing_pinch, tuning.pinch_off)
        self.assertAlmostEqual(tuning.reference_palm, 0.15, delta=0.01)
        # A mesma mão, depois da calibração, também arma os gestos na máquina.
        machine = GestureMachine(tuning)
        stiff_open = samples["open"][0]
        commands = play(machine, [(i / FPS, stiff_open) for i in range(int(1.6 * FPS))])
        self.assertEqual(kinds(commands), ["armed"])

    def test_defaults_that_already_work_are_only_nudged(self) -> None:
        rng = np.random.default_rng(1)
        pose_of = {"open": "open", "fist": "fist", "pinch": "pinch", "point": "point", "two": "two", "thumb_down": "thumb_down_relaxed"}
        samples = {key: [make_hand(pose, center=(0.5 + rng.normal(0, 0.01), 0.5)) for _ in range(20)] for key, pose in pose_of.items()}
        tuning, report = gesture_calibration.calibrate(samples)
        self.assertEqual(set(report["accuracy_after"].values()), {1.0})
        base = Tuning()
        self.assertGreater(tuning.extend_bend, base.extend_bend * 0.6)  # o meio do caminho, não a borda das amostras

    def test_overlapping_poses_keep_the_default_and_warn(self) -> None:
        open_hands = [make_hand("open") for _ in range(20)]
        tuning, report = gesture_calibration.calibrate({"open": open_hands, "fist": open_hands})
        self.assertEqual(tuning.extend_bend, Tuning().extend_bend)
        self.assertTrue(report["warnings"])

    def test_save_and_load_round_trip(self) -> None:
        tuning, report = gesture_calibration.calibrate(stiff_samples(np.random.default_rng(2)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gestos_calibracao.json"
            gesture_calibration.save(tuning, report, path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(data["tuning"]), set(CALIBRATED_FIELDS))
            loaded = Tuning.load(path)
            for name in CALIBRATED_FIELDS:
                self.assertAlmostEqual(getattr(loaded, name), getattr(tuning, name), places=3)
            self.assertEqual(loaded.cooldown_s, Tuning().cooldown_s)  # comportamento não vem do arquivo

    def test_load_ignores_missing_broken_and_foreign_values(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gestos_calibracao.json"
            self.assertEqual(Tuning.load(path), Tuning())
            path.write_text("{ não é json", encoding="utf-8")
            with self.assertLogs("jarvis-gestures", level="WARNING"):
                self.assertEqual(Tuning.load(path), Tuning())
            path.write_text(
                json.dumps({"tuning": {"extend_bend": 90, "cooldown_s": 0, "pinch_on": "x", "fold_bend": -1, "pose_exit_frames": True}}),
                encoding="utf-8",
            )
            loaded = Tuning.load(path)
            self.assertEqual(loaded.extend_bend, 90.0)
            self.assertEqual(replace(loaded, extend_bend=Tuning().extend_bend), Tuning())

    def test_engine_loads_the_calibration_file_when_it_exists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gestos_calibracao.json"
            path.write_text(json.dumps({"version": 1, "tuning": {"extend_bend": 88}}), encoding="utf-8")
            with patch.object(gesture_engine, "CALIBRATION_FILE", path):
                engine = GestureEngine(iter(()), MagicMock(), tracker=MagicMock())
            self.assertEqual(engine.machine.tuning.extend_bend, 88.0)
            self.assertTrue(engine.calibrated)
        self.assertFalse(GestureEngine(iter(()), MagicMock(), tracker=MagicMock()).calibrated)


class CalibrationSessionTests(unittest.TestCase):
    def test_walks_through_every_pose_and_collects_samples(self) -> None:
        session = gesture_calibration.CalibrationSession(prepare_s=0.5, record_s=1.0)
        poses = {"open": "open", "fist": "fist", "pinch": "pinch", "point": "point", "two": "two", "thumb_down": "thumb_down_relaxed"}
        t = 0.0
        phases = []
        while not session.done and t < 60:
            key = session.steps[min(len(session.steps) - 1, len(session.samples) + len(session.skipped))].key
            prompt = session.feed(t, make_hand(poses[key]))
            phases.append((prompt.step, prompt.phase))
            t += 1 / FPS
        self.assertTrue(session.done)
        self.assertEqual(set(session.samples), set(poses))
        self.assertTrue(all(len(hands) >= 15 for hands in session.samples.values()))
        self.assertIn((0, "prepare"), phases)
        self.assertIn((5, "record"), phases)
        self.assertTrue(session.feed(t, None).done)

    def test_a_pose_without_the_hand_is_repeated_then_skipped(self) -> None:
        steps = gesture_calibration.STEPS[:2]
        session = gesture_calibration.CalibrationSession(steps, prepare_s=0.2, record_s=1.0, retries=1)
        t = 0.0
        details = []
        while not session.done and t < 30:
            hand = None if session.steps[len(session.samples) + len(session.skipped)].key == "open" else make_hand("fist")
            details.append(session.feed(t, hand).detail)
            t += 1 / FPS
        self.assertEqual(session.skipped, ["open"])
        self.assertIn("fist", session.samples)
        self.assertTrue(any("de novo" in detail for detail in details))

    def test_bad_frames_are_not_measured(self) -> None:
        session = gesture_calibration.CalibrationSession(gesture_calibration.STEPS[:1], prepare_s=0.1, record_s=1.0, retries=0)
        t = 0.0
        while not session.done:
            session.feed(t, replace(make_hand("open"), score=0.2))
            t += 1 / FPS
        self.assertEqual(session.skipped, ["open"])


class CalibrationRunnerTests(unittest.TestCase):
    def test_calibrate_flag_measures_every_pose_and_saves_the_file(self) -> None:
        import gestures

        poses = ["open", "fist", "pinch", "point", "two", "thumb_down_relaxed"]
        session_s = 4.5 + 0.2  # preparar 2,5 s + medir 2 s, por pose
        clock = {"t": 0.0}

        class Tracker:
            def detect(self, _image: Any, t: float) -> Hand:
                return make_hand(poses[min(len(poses) - 1, int(t // session_s))])

            def close(self) -> None:
                pass

        def frames(_camera: Any = None) -> Any:
            while True:
                clock["t"] += 1 / FPS
                yield np.zeros((360, 640, 3), dtype=np.uint8)

        cv2 = MagicMock(getWindowProperty=MagicMock(return_value=1.0), waitKey=MagicMock(return_value=-1))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gestos_calibracao.json"
            with (
                patch.object(gestures, "HandTracker", Tracker),
                patch.object(gestures, "webcam_frames", frames),
                patch.object(gestures.time, "monotonic", lambda: clock["t"]),
                patch.dict("sys.modules", {"cv2": cv2}),
                patch("builtins.print"),
            ):
                self.assertEqual(gestures.run_calibration(path=path), 0)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(data["report"]["samples"]), {"open", "fist", "pinch", "point", "two", "thumb_down"})
        self.assertTrue(cv2.imshow.called)


# ───────────────────────── detector e preview ─────────────────────────


class Landmark:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x, self.y, self.z = x, y, z


class HandTrackerResultTests(unittest.TestCase):
    def result(self, hand: Hand, score: float = 0.93, world: bool = True) -> Any:
        result = MagicMock()
        result.hand_landmarks = [[Landmark(*p) for p in hand.points]]
        result.hand_world_landmarks = [[Landmark(*p) for p in hand.world]] if world else []
        category = MagicMock(category_name="Right", score=score)
        result.handedness = [[category]]
        return result

    def test_converts_the_first_hand_with_its_confidence(self) -> None:
        source = make_hand("point")
        hand = hand_from_result(self.result(source), 16 / 9)
        self.assertIsNotNone(hand)
        self.assertEqual(hand.score, 0.93)
        self.assertEqual(hand.handedness, "Right")
        np.testing.assert_allclose(hand.points, source.points)
        self.assertEqual(classify(hand).pose, Pose.POINT)

    def test_no_hand_and_broken_landmarks(self) -> None:
        empty = MagicMock(hand_landmarks=[], hand_world_landmarks=[], handedness=[])
        self.assertIsNone(hand_from_result(empty, 16 / 9))
        broken = self.result(make_hand("open"))
        broken.hand_landmarks[0][3] = Landmark(float("nan"), 0.5, 0.0)
        self.assertIsNone(hand_from_result(broken, 16 / 9))

    def test_low_confidence_from_the_detector_is_dropped_by_the_machine(self) -> None:
        machine = GestureMachine()
        hand = hand_from_result(self.result(make_hand("open"), score=0.3), 16 / 9)
        machine.step(0.0, hand)
        self.assertEqual(machine.quality.reason, "confiança")
        self.assertFalse(machine.status(0.0).hand)

    def test_preview_line_shows_confidence_and_stable_pose(self) -> None:
        quality = hand_quality(replace(make_hand("open"), score=0.42))
        line = confidence_line(quality, Pose.FIST, Pose.OPEN)
        self.assertIn("confiança 0.42", line)
        self.assertIn("quadro: fist", line)
        self.assertIn("estável: open", line)
        self.assertIn("DESCARTADO (confiança)", line)
        self.assertIn("estável: none", confidence_line(None, Pose.NONE, Pose.NONE))


if __name__ == "__main__":
    unittest.main()
