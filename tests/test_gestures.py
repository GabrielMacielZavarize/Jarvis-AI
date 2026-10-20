from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

import gesture_actions
import gestures
import pc_control
import win_desktop
from gesture_actions import (
    DesktopActions,
    GestureActionError,
    Target,
    describe_direction,
    monitor_label,
    neighbor_monitor,
    throw_bias,
)
from gesture_engine import Command, GestureMachine, OneEuroFilter, Pose, State, classify
from gesture_overlay import OverlayView, premultiplied_bgra, render, render_reticle
from gestures import GestureEngine, GestureService, voice_action
from hand_fixtures import FPS, POSES, absent, end_of, hold, make_hand, move
from settings import load_settings
from test_tools import FakeRunContext

# Geometria real dos 3 monitores do Gabriel (win_desktop.monitors()); a numeração não importa.
TOP = win_desktop.Monitor(1, 0, 0, 2560, 1440, (0, 0, 2560, 1392), True)
NOTEBOOK = win_desktop.Monitor(2, 0, 1474, 1920, 2674, (0, 1474, 1920, 2602), False)
VERTICAL = win_desktop.Monitor(3, -1440, 124, 0, 2684, (-1440, 124, 0, 2636), False)
SCREENS = [TOP, NOTEBOOK, VERTICAL]

_GUARDS: list[Any] = []


def setUpModule() -> None:
    """Safety net: no test here may move, focus, close, click or type on the real desktop."""
    targets = [
        "win_desktop.bring_to_front",
        "win_desktop.move_to_monitor",
        "win_desktop.restore_placement",
        "win_desktop.show_window",
        "win_desktop.close_window",
        "gesture_actions.Win32Input.move",
        "gesture_actions.Win32Input.button",
        "gesture_actions.Win32Input.keys",
        "gestures.open_webcam",
        "gestures.HandTracker",
        "gestures.Overlay.start",
    ]
    for target in targets:

        def forbid(*_args: Any, _target: str = target, **_kwargs: Any) -> None:
            raise AssertionError(f"o teste chamou {_target} de verdade")

        guard = patch(target, side_effect=forbid)
        guard.start()
        _GUARDS.append(guard)
    # A calibração pessoal (gestos_calibracao.json) não pode mudar o resultado das mãos sintéticas.
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


def armed_machine() -> tuple[GestureMachine, float]:
    machine = GestureMachine()
    machine.arm(0.0)
    timeline = hold("open", 0.0, 0.5)
    play(machine, timeline)
    return machine, end_of(timeline)


class ClassifierTests(unittest.TestCase):
    def test_every_synthetic_pose_is_recognized(self) -> None:
        for pose in POSES:
            expected = {"loose_fist": Pose.FIST, "thumb_down_relaxed": Pose.THUMB_DOWN}.get(pose) or Pose(pose)
            for options in ({}, {"world": False}, {"size": 0.1}):
                with self.subTest(pose=pose, **options):
                    self.assertEqual(classify(make_hand(pose, **options)).pose, expected)

    def test_loose_fist_with_thumb_on_the_index_is_not_a_pinch(self) -> None:
        # Visto na webcam: punho com o polegar por cima do indicador saía como pinça.
        shape = classify(make_hand("loose_fist"))
        self.assertLess(shape.pinch, 0.3)
        self.assertEqual(shape.pose, Pose.FIST)

    def test_tilted_hand_keeps_its_pose(self) -> None:
        for pose in ("open", "fist", "point", "two", "pinch"):
            for roll in (-35, 35):
                with self.subTest(pose=pose, roll=roll):
                    self.assertEqual(classify(make_hand(pose, roll=roll)).pose, Pose(pose))

    def test_fist_with_thumb_sideways_is_not_thumb_down(self) -> None:
        self.assertEqual(classify(make_hand("thumb_down", roll=0)).pose, Pose.FIST)

    def test_thumb_down_as_seen_on_the_webcam(self) -> None:
        # Visto na webcam: dedos semidobrados (~50°) e polegar ~20° abaixo da horizontal.
        shape = classify(make_hand("thumb_down_relaxed"))
        self.assertEqual(shape.pose, Pose.THUMB_DOWN)
        self.assertAlmostEqual(shape.metrics["curl"], 50, delta=5)
        # A mão aberta girada do mesmo jeito (polegar no mesmo ângulo) não fecha nada.
        self.assertEqual(classify(make_hand("open", roll=200 - 143.13)).pose, Pose.OPEN)
        self.assertEqual(classify(make_hand("open", roll=180)).pose, Pose.OPEN)

    def test_center_and_pointer_follow_the_hand(self) -> None:
        shape = classify(make_hand("point", center=(0.3, 0.6)))
        self.assertAlmostEqual(shape.center[0], 0.3 * 16 / 9, places=3)
        self.assertAlmostEqual(shape.center[1], 0.6, places=3)
        self.assertLess(shape.pointer[1], 0.6)  # a base do indicador fica acima do centro da palma


class OneEuroFilterTests(unittest.TestCase):
    def test_smooths_jitter_and_follows_real_moves(self) -> None:
        rng = np.random.default_rng(7)
        filtered = OneEuroFilter(min_cutoff=1.5, beta=0.5)
        noisy = 0.5 + rng.normal(0, 0.01, 120)
        output = [filtered(i / FPS, value) for i, value in enumerate(noisy)]
        self.assertLess(np.std(output[30:]), np.std(noisy[30:]) / 2)
        for i in range(120, 150):
            last = filtered(i / FPS, 0.9)
        self.assertAlmostEqual(last, 0.9, delta=0.02)


class MachineTests(unittest.TestCase):
    def test_still_open_palm_arms_once(self) -> None:
        machine = GestureMachine()
        commands = play(machine, hold("open", 0.0, 1.6))
        self.assertEqual(kinds(commands), ["armed"])
        self.assertEqual(machine.state, State.ARMED)

    def test_moving_palm_does_not_arm(self) -> None:
        machine = GestureMachine()
        wave = [
            (i / FPS, make_hand("open", (0.5 + 0.15 * np.sin(i / 3), 0.5))) for i in range(int(2.5 * FPS))
        ]
        self.assertEqual(kinds(play(machine, wave)), [])
        self.assertEqual(machine.state, State.IDLE)

    def test_nothing_happens_while_disarmed(self) -> None:
        machine = GestureMachine()
        commands = play(machine, hold("fist", 0.0, 1.0), hold("thumb_down", 1.0, 2.0))
        self.assertEqual(kinds(commands), [])

    def test_grab_move_up_and_release_throws_up(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.4)
        lift = move("fist", end_of(grab), 0.3, (0.5, 0.5), (0.52, 0.25))
        release = hold("open", end_of(lift), 0.3, center=(0.52, 0.25))
        commands = play(machine, grab, lift, release)
        self.assertEqual(kinds(commands), ["grab", "aim", "throw"])
        throw = commands[-1]
        self.assertEqual(throw.direction, "up")
        self.assertLess(throw.vector[1], -0.15)

    def test_direction_follows_where_the_hand_goes(self) -> None:
        for end, expected in (((0.2, 0.5), "left"), ((0.8, 0.5), "right"), ((0.5, 0.8), "down")):
            with self.subTest(expected=expected):
                machine, t = armed_machine()
                grab = hold("fist", t, 0.4)
                travel = move("fist", end_of(grab), 0.3, (0.5, 0.5), end)
                commands = play(machine, grab, travel, hold("open", end_of(travel), 0.3, center=end))
                self.assertEqual(commands[-1].kind, "throw")
                self.assertEqual(commands[-1].direction, expected)

    def test_opening_hand_releases_during_the_pinch_phase(self) -> None:
        # Visto na webcam: ao abrir, o polegar desencosta do indicador por último; a mão às vezes
        # sai do quadro antes de ficar aberta. A fase de pinça já conta como soltar.
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        lift = move("fist", end_of(grab), 0.3, (0.5, 0.5), (0.5, 0.25))
        opening = hold("pinch", end_of(lift), 0.3, center=(0.5, 0.25))
        commands = play(machine, grab, lift, opening, absent(end_of(opening), 0.5))
        self.assertEqual(kinds(commands), ["grab", "aim", "throw"])
        self.assertEqual(commands[-1].direction, "up")

    def test_hand_closing_right_after_a_throw_does_not_grab_again(self) -> None:
        # Visto na webcam: depois de soltar, a mão relaxa e fecha sozinha em ~0,6 s.
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        lift = move("fist", end_of(grab), 0.3, (0.5, 0.5), (0.5, 0.25))
        release = hold("open", end_of(lift), 0.3, center=(0.5, 0.25))
        relaxed = hold("fist", end_of(release), 2.0, center=(0.5, 0.25))
        commands = play(machine, grab, lift, release, relaxed)
        self.assertEqual(kinds(commands), ["grab", "aim", "throw"])
        reopen = hold("open", end_of(relaxed), 0.3, center=(0.5, 0.25))
        again = hold("fist", end_of(reopen), 0.5, center=(0.5, 0.25))
        self.assertEqual(kinds(play(machine, reopen, again)), ["grab"])

    def test_throw_distance_grows_with_a_hand_close_to_the_camera(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5, size=0.3)
        nudge = move("fist", end_of(grab), 0.3, (0.5, 0.5), (0.5, 0.36), size=0.3)
        commands = play(machine, grab, nudge)
        self.assertEqual(kinds(commands), ["grab"])  # 0,14 de quadro é pouco para uma mão desse tamanho

    def test_release_in_place_maximizes(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.5)
        commands = play(machine, grab, hold("open", end_of(grab), 0.3))
        self.assertEqual(kinds(commands), ["grab", "maximize"])

    def test_small_move_then_release_cancels(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.4)
        nudge = move("fist", end_of(grab), 0.4, (0.5, 0.5), (0.5, 0.405))
        commands = play(machine, grab, nudge, hold("open", end_of(nudge), 0.3, center=(0.5, 0.405)))
        self.assertEqual(kinds(commands), ["grab", "cancel"])

    def test_moving_back_to_the_start_clears_the_aim(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.4)
        out = move("fist", end_of(grab), 0.3, (0.5, 0.5), (0.5, 0.25))
        back = move("fist", end_of(out), 0.3, (0.5, 0.25), (0.5, 0.5))
        commands = play(machine, grab, out, back, hold("fist", end_of(back), 0.3))
        aims = [command.direction for command in commands if command.kind == "aim"]
        self.assertEqual(aims, ["up", None])
        self.assertEqual(machine.state, State.GRAB)

    def test_losing_the_hand_while_holding_cancels(self) -> None:
        machine, t = armed_machine()
        grab = hold("fist", t, 0.4)
        commands = play(machine, grab, absent(end_of(grab), 0.5))
        self.assertEqual(kinds(commands), ["grab", "cancel"])
        self.assertEqual(machine.state, State.ARMED)

    def test_thumb_down_held_closes_once(self) -> None:
        machine, t = armed_machine()
        commands = play(machine, hold("thumb_down", t, 3.5))
        self.assertEqual(kinds(commands), ["grab", "close"])
        self.assertEqual(machine.state, State.ARMED)

    def test_relaxed_thumb_down_closes_too(self) -> None:
        machine, t = armed_machine()
        commands = play(machine, hold("thumb_down_relaxed", t, 1.6))
        self.assertEqual(kinds(commands), ["grab", "close"])

    def test_close_needs_the_full_countdown(self) -> None:
        machine, t = armed_machine()
        down = hold("thumb_down", t, 0.7)
        commands = play(machine, down, hold("open", end_of(down), 0.5))
        self.assertEqual(kinds(commands), ["grab", "cancel"])
        status = machine.status(end_of(down))
        self.assertEqual(status.state, State.ARMED)

    def test_close_countdown_progress(self) -> None:
        machine, t = armed_machine()
        down = hold("thumb_down", t, 0.8)
        play(machine, down)
        status = machine.status(down[-1][0])
        self.assertEqual(status.state, State.CLOSE)
        self.assertEqual(status.charging, "close")
        self.assertGreater(status.progress, 0.3)
        self.assertLess(status.progress, 1.0)

    def test_fist_turning_into_thumb_down_switches_to_close(self) -> None:
        machine, t = armed_machine()
        fist = hold("fist", t, 0.4)
        commands = play(machine, fist, hold("thumb_down", end_of(fist), 1.6))
        self.assertEqual(kinds(commands), ["grab", "close"])

    def test_palm_swipe_down_minimizes_when_the_hand_stops_in_view(self) -> None:
        machine, t = armed_machine()
        swipe = move("open", t, 0.25, (0.5, 0.35), (0.5, 0.7))
        commands = play(machine, swipe, hold("open", end_of(swipe), 0.5, center=(0.5, 0.7)))
        self.assertEqual(kinds(commands), ["minimize"])

    def test_dropping_the_hand_out_of_view_does_not_minimize(self) -> None:
        machine, t = armed_machine()
        swipe = move("open", t, 0.25, (0.5, 0.35), (0.5, 0.75))
        commands = play(machine, swipe, absent(end_of(swipe), 1.0))
        self.assertEqual(kinds(commands), [])

    def test_two_finger_swipes_switch_tabs_and_ignore_the_return_stroke(self) -> None:
        machine, t = armed_machine()
        settle = hold("two", t, 0.3, center=(0.35, 0.5))
        right = move("two", end_of(settle), 0.25, (0.35, 0.5), (0.65, 0.5))
        back = move("two", end_of(right), 0.3, (0.65, 0.5), (0.35, 0.5))
        commands = play(machine, settle, right, back)
        tabs = [command for command in commands if command.kind == "tab"]
        self.assertEqual([command.step for command in tabs], [1])

        later = hold("two", end_of(back) + 0.5, 0.3, center=(0.65, 0.5))
        left = move("two", end_of(later), 0.25, (0.65, 0.5), (0.35, 0.5))
        commands = play(machine, later, left)
        self.assertEqual([command.step for command in commands if command.kind == "tab"], [-1])

    def test_tab_swipe_at_the_speed_seen_on_the_webcam(self) -> None:
        # Visto na webcam: 0,3 de quadro em ~0,4 s com dois dedos (0,79/s) não passava.
        machine, t = armed_machine()
        settle = hold("two", t, 0.3, center=(0.34, 0.5))
        right = move("two", end_of(settle), 0.4, (0.34, 0.5), (0.52, 0.5))
        commands = play(machine, settle, right, hold("two", end_of(right), 0.3, center=(0.52, 0.5)))
        self.assertEqual([command.step for command in commands if command.kind == "tab"], [1])

    def test_slow_wipe_still_undoes(self) -> None:
        machine, t = armed_machine()
        wipe = move("open", t, 1.8, (0.4, 0.5), (0.6, 0.5), path=lambda k: 0.5 - 0.5 * np.cos(k * 3 * np.pi))
        self.assertEqual(kinds(play(machine, wipe)), ["undo"])

    def test_side_to_side_wipe_undoes(self) -> None:
        machine, t = armed_machine()
        wipe = move("open", t, 1.0, (0.4, 0.5), (0.6, 0.5), path=lambda k: 0.5 - 0.5 * np.cos(k * 3 * np.pi))
        commands = play(machine, wipe)
        self.assertEqual(kinds(commands), ["undo"])

    def test_disarms_after_idle_time_and_when_the_hand_leaves(self) -> None:
        machine, t = armed_machine()
        idle = hold("open", t, 13.0)
        commands = play(machine, idle, hold("open", end_of(idle), 3.0))
        self.assertEqual(kinds(commands), ["disarmed"])  # a mão parada não rearma sozinha
        fist = hold("fist", end_of(idle) + 3.0, 0.5)
        commands = play(machine, fist, hold("open", end_of(fist), 1.5))
        self.assertEqual(kinds(commands), ["armed"])

        machine, t = armed_machine()
        commands = play(machine, absent(t, 6.0))
        self.assertEqual(kinds(commands), ["disarmed"])
        self.assertEqual(machine.state, State.IDLE)

    def test_air_mouse_move_click_drag_and_exit(self) -> None:
        machine, t = armed_machine()
        point = hold("point", t, 1.2)
        commands = play(machine, point)
        self.assertEqual(kinds(commands), ["mouse_on"])

        travel = move("point", end_of(point), 0.5, (0.5, 0.5), (0.3, 0.3))
        moves = [command for command in play(machine, travel) if command.kind == "mouse_move"]
        self.assertGreater(len(moves), 5)
        self.assertLess(moves[-1].point[0], moves[0].point[0])
        self.assertTrue(all(0.0 <= value <= 1.0 for command in moves for value in command.point))

        tap = hold("pinch", end_of(travel), 0.2, center=(0.3, 0.3))
        after_tap = hold("point", end_of(tap), 0.3, center=(0.3, 0.3))
        self.assertEqual(kinds(play(machine, tap, after_tap)), ["click"])

        drag = hold("pinch", end_of(after_tap), 0.8, center=(0.3, 0.3))
        drop = hold("point", end_of(drag), 0.3, center=(0.3, 0.3))
        self.assertEqual(kinds(play(machine, drag, drop)), ["mouse_down", "mouse_up"])

        leave = hold("open", end_of(drop), 1.5, center=(0.3, 0.3))
        self.assertEqual(kinds(play(machine, leave)), ["mouse_off"])
        self.assertEqual(machine.state, State.ARMED)

    def test_air_mouse_clicks_by_closing_the_hand(self) -> None:
        # Visto na webcam: no mouse no ar o Gabriel clicou fechando a mão, não com pinça.
        machine, t = armed_machine()
        point = hold("point", t, 1.2)
        play(machine, point)
        tap = hold("fist", end_of(point), 0.25)
        after = hold("point", end_of(tap), 0.4)
        commands = play(machine, tap, after)
        self.assertEqual(kinds(commands), ["click"])

        drag = hold("fist", end_of(after), 0.9)
        drop = hold("point", end_of(drag), 0.4)
        self.assertEqual(kinds(play(machine, drag, drop)), ["mouse_down", "mouse_up"])
        self.assertEqual(machine.state, State.MOUSE)

    def test_voice_mouse_from_idle_and_disarm_releases_the_button(self) -> None:
        machine = GestureMachine()
        self.assertEqual(kinds(machine.set_mouse(0.0, True)), ["armed", "mouse_on"])
        drag = hold("pinch", 0.0, 0.8)
        self.assertIn("mouse_down", kinds(play(machine, drag)))
        self.assertEqual(kinds(machine.disarm(end_of(drag))), ["mouse_up", "disarmed"])


class PointingTests(unittest.TestCase):
    def test_pointing_marks_the_spot_without_touching_the_cursor(self) -> None:
        machine, t = armed_machine()
        point = hold("point", t, 0.6, center=(0.3, 0.3))
        commands = play(machine, point)

        self.assertEqual(kinds(commands), [])
        self.assertFalse(any(command.kind == "mouse_move" for command in commands))
        spot = machine.pointed_at(end_of(point), 2.5)
        self.assertIsNotNone(spot)
        self.assertLess(spot[0], 0.5)  # mão à esquerda do quadro: lado esquerdo das telas
        self.assertEqual(machine.aim(end_of(point), 1.0), spot)

    def test_lowering_the_hand_keeps_the_spot_and_it_expires(self) -> None:
        machine, t = armed_machine()
        point = hold("point", t, 0.6, center=(0.3, 0.3))
        play(machine, point)
        spot = machine.pointed_at(end_of(point), 2.5)

        lower = move("point", end_of(point), 0.2, (0.3, 0.3), (0.3, 0.75))
        gone = absent(end_of(lower), 1.5)
        play(machine, lower, gone)

        self.assertEqual(machine.pointed_at(end_of(lower), 2.5), spot)
        self.assertIsNone(machine.aim(end_of(gone), 1.0))  # a mira some 1 s depois de baixar a mão
        self.assertIsNone(machine.pointed_at(end_of(point) + 3.0, 2.5))

    def test_pointing_while_talking_never_turns_into_the_air_mouse(self) -> None:
        machine, t = armed_machine()
        machine.set_talking(t, True)
        point = hold("point", t, 1.6)
        commands = play(machine, point)

        self.assertNotIn("mouse_on", kinds(commands))
        self.assertTrue(machine.pointing)
        self.assertEqual(machine.state, State.ARMED)

        # A fala acabou, mas o mesmo indicador continua sendo só o ponteiro.
        machine.set_talking(end_of(point), False)
        still = hold("point", end_of(point), 3.0)
        self.assertNotIn("mouse_on", kinds(play(machine, still)))

        # Baixar a mão e apontar de novo, longe de uma fala, volta a ligar o mouse no ar.
        rest = hold("open", end_of(still), 0.4)
        again = hold("point", end_of(rest), 1.2)
        self.assertEqual(kinds(play(machine, rest, again)), ["mouse_on"])

    def test_speech_that_starts_while_the_mouse_charges_cancels_it(self) -> None:
        machine, t = armed_machine()
        start = hold("point", t, 0.5)
        play(machine, start)
        machine.set_talking(end_of(start), True)

        rest = hold("point", end_of(start), 1.0)

        self.assertNotIn("mouse_on", kinds(play(machine, rest)))
        self.assertIsNotNone(machine.pointed_at(end_of(rest), 2.5))

    def test_engine_gives_the_pointed_pixel_and_draws_the_crosshair(self) -> None:
        overlay = MagicMock()
        actions = MagicMock()
        actions.virtual_bounds.return_value = (-1440, 0, 2560, 2684)
        machine, t = armed_machine()
        point = hold("point", t, 0.6, center=(0.3, 0.3))
        engine = GestureEngine([], actions, tracker=FakeTracker([]), overlay=overlay, clock=lambda: end_of(point))
        engine.machine = machine
        play(machine, point)

        pixel = engine.pointed_screen_point(2.5)
        engine._refresh_overlay(end_of(point))

        self.assertIsNotNone(pixel)
        self.assertTrue(-1440 <= pixel[0] < 2560 and 0 <= pixel[1] < 2684)
        overlay.aim.assert_called_with(pixel)
        actions.mouse_move.assert_not_called()

        machine.set_talking(end_of(point), True)
        play(machine, hold("point", end_of(point), 0.2, center=(0.3, 0.3)))
        self.assertEqual(engine.view(end_of(point) + 0.2).title, "APONTANDO")

    def test_service_reports_the_point_and_the_voice(self) -> None:
        service = GestureService()
        self.assertIsNone(service.pointed_screen_point(2.5))  # gestos desligados

        engine = MagicMock()
        engine.pointed_screen_point.return_value = (-800, 900)
        service._engine = engine
        with patch.object(GestureService, "running", new=True):
            self.assertEqual(service.pointed_screen_point(2.5), (-800, 900))
            service.set_talking(True)
            service.set_talking(False)
        engine.request.assert_has_calls([unittest.mock.call("talk_on"), unittest.mock.call("talk_off")])

    def test_voice_session_tells_the_gestures_when_the_user_talks(self) -> None:
        handlers: dict[str, Any] = {}
        session = MagicMock()
        session.on.side_effect = lambda name: lambda handler: handlers.setdefault(name, handler)
        service = MagicMock()

        gestures.watch_voice(session, service)
        handlers["user_state_changed"](MagicMock(new_state="speaking"))
        handlers["user_state_changed"](MagicMock(new_state="listening"))

        service.set_talking.assert_has_calls([unittest.mock.call(True), unittest.mock.call(False)])


class NeighborMonitorTests(unittest.TestCase):
    def test_real_layout_directions(self) -> None:
        cases = [
            (TOP, "down", NOTEBOOK),
            (TOP, "left", VERTICAL),
            (TOP, "up", None),
            (TOP, "right", None),
            (NOTEBOOK, "up", TOP),
            (NOTEBOOK, "left", VERTICAL),
            (NOTEBOOK, "right", None),
            (NOTEBOOK, "down", None),
            (VERTICAL, "up", None),
            (VERTICAL, "down", NOTEBOOK),  # mais à direita, mas é o que fica embaixo (pedido no teste real)
            (VERTICAL, "left", None),
        ]
        for source, direction, expected in cases:
            with self.subTest(source=source.number, direction=direction):
                self.assertEqual(neighbor_monitor(source, direction, SCREENS), expected)

    def test_right_of_the_vertical_monitor_depends_on_the_window_height(self) -> None:
        self.assertEqual(neighbor_monitor(VERTICAL, "right", SCREENS, anchor=(-720, 500)), TOP)
        self.assertEqual(neighbor_monitor(VERTICAL, "right", SCREENS, anchor=(-720, 2200)), NOTEBOOK)

    def test_diagonal_throw_picks_the_screen_on_that_side(self) -> None:
        middle = (-720, 1450)
        self.assertEqual(neighbor_monitor(VERTICAL, "right", SCREENS, anchor=middle, bias=0.6), NOTEBOOK)
        self.assertEqual(neighbor_monitor(VERTICAL, "right", SCREENS, anchor=middle, bias=-0.6), TOP)

    def test_wide_window_on_the_top_monitor_still_finds_the_notebook(self) -> None:
        self.assertEqual(neighbor_monitor(TOP, "down", SCREENS, anchor=(2400, 700)), NOTEBOOK)

    def test_other_layouts(self) -> None:
        left = win_desktop.Monitor(1, 0, 0, 1920, 1080, (0, 0, 1920, 1040), True)
        right = win_desktop.Monitor(2, 1920, 200, 3840, 1280, (1920, 200, 3840, 1240), False)
        diagonal = win_desktop.Monitor(3, 3840, 1280, 5760, 2360, (3840, 1280, 5760, 2320), False)
        self.assertEqual(neighbor_monitor(left, "right", [left, right]), right)
        self.assertEqual(neighbor_monitor(right, "left", [left, right]), left)
        self.assertIsNone(neighbor_monitor(left, "down", [left, right]))
        self.assertEqual(neighbor_monitor(right, "right", [left, right, diagonal]), diagonal)
        self.assertEqual(neighbor_monitor(right, "down", [left, right, diagonal]), diagonal)
        self.assertEqual(neighbor_monitor(diagonal, "up", [left, right, diagonal]), right)
        self.assertIsNone(neighbor_monitor(left, "up", [left, right, diagonal]))

    def test_monitor_names_come_from_the_physical_layout(self) -> None:
        self.assertEqual(monitor_label(TOP, SCREENS), "monitor de cima")
        self.assertEqual(monitor_label(NOTEBOOK, SCREENS), "monitor de baixo")
        self.assertEqual(monitor_label(VERTICAL, SCREENS), "monitor vertical")

    def test_throw_bias(self) -> None:
        self.assertAlmostEqual(throw_bias("right", (0.2, 0.1)), 0.5)
        self.assertAlmostEqual(throw_bias("up", (-0.05, -0.2)), -0.25)
        self.assertEqual(throw_bias("left", (0.0, 0.3)), 0.0)
        self.assertEqual(throw_bias("down", (0.5, 0.1)), 1.0)


def window(hwnd: int = 10, title: str = "Bloco de notas", process: str = "notepad.exe", pid: int = 4321) -> win_desktop.Window:
    return win_desktop.Window(hwnd=hwnd, title=title, process=process, pid=pid)


class FakeInput:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def move(self, x: int, y: int) -> None:
        self.calls.append(("move", x, y))

    def button(self, down: bool) -> None:
        self.calls.append(("button", down))

    def keys(self, *codes: int) -> None:
        self.calls.append(("keys", *codes))


class ActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input = FakeInput()
        self.actions = DesktopActions(self.input)
        patches = {
            "win_desktop.monitors": patch("win_desktop.monitors", return_value=SCREENS),
            "exists": patch("gesture_actions._window_exists", return_value=True),
            "remember": patch("pc_control._remember_position"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def target(self, item: win_desktop.Window | None = None, monitor: win_desktop.Monitor = TOP, browser: bool = False) -> Target:
        return Target(window=item or window(), monitor=monitor, browser=browser)

    def test_grab_takes_the_foreground_window_but_never_our_own(self) -> None:
        own = window(1, "Jarvis - gestos", "python.exe", pid=self.actions.own_pids.pop())
        self.actions.own_pids.add(own.pid)
        edge = window(2, "YouTube - Edge", "msedge.exe")
        notes = window(3)
        with (
            patch("win_desktop.windows", return_value=[own, edge, notes]),
            patch("gesture_actions._foreground_hwnd", return_value=3),
            patch("gesture_actions._is_minimized", return_value=False),
            patch("win_desktop.window_rect", return_value=(100, 1500, 900, 2000)),
        ):
            target = self.actions.grab()
            self.assertEqual(target.window, notes)
            self.assertEqual(target.monitor, NOTEBOOK)
            self.assertFalse(target.browser)
        with (
            patch("win_desktop.windows", return_value=[own, edge, notes]),
            patch("gesture_actions._foreground_hwnd", return_value=1),
            patch("gesture_actions._is_minimized", return_value=False),
            patch("win_desktop.window_rect", return_value=(100, 100, 900, 600)),
        ):
            target = self.actions.grab()
            self.assertEqual(target.window, edge)
            self.assertTrue(target.browser)

    def test_throw_moves_to_the_physical_neighbor_and_remembers_the_old_place(self) -> None:
        with (
            patch("win_desktop.window_rect", return_value=(200, 200, 1200, 900)),
            patch("win_desktop.move_to_monitor") as move_to,
            patch("win_desktop.window_monitor", return_value=NOTEBOOK),
        ):
            result = self.actions.throw(self.target(), "down", (0.0, 0.3))
        move_to.assert_called_once_with(10, NOTEBOOK)
        self.mocks["remember"].assert_called_once_with(10)
        self.assertIn("monitor de baixo", result)

    def test_down_from_the_vertical_monitor_goes_to_the_notebook(self) -> None:
        with (
            patch("win_desktop.window_rect", return_value=(-1300, 1800, -200, 2500)),
            patch("win_desktop.move_to_monitor") as move_to,
            patch("win_desktop.window_monitor", return_value=NOTEBOOK),
        ):
            self.actions.throw(self.target(monitor=VERTICAL), "down", (0.05, 0.3))
        move_to.assert_called_once_with(10, NOTEBOOK)

    def test_throw_without_a_monitor_there_changes_nothing(self) -> None:
        with (
            patch("win_desktop.window_rect", return_value=(200, 200, 1200, 900)),
            patch("win_desktop.move_to_monitor") as move_to,
        ):
            with self.assertRaises(GestureActionError) as error:
                self.actions.throw(self.target(), "up", (0.0, -0.3))
        move_to.assert_not_called()
        self.assertIn("Não há monitor de cima", str(error.exception))

    def test_throw_reports_when_the_window_did_not_move(self) -> None:
        with (
            patch("win_desktop.window_rect", return_value=(200, 200, 1200, 900)),
            patch("win_desktop.move_to_monitor"),
            patch("win_desktop.window_monitor", return_value=TOP),
        ):
            with self.assertRaises(GestureActionError) as error:
                self.actions.throw(self.target(), "left", (-0.3, 0.0))
        self.assertIn("não saiu do lugar", str(error.exception))

    def test_aim_names_the_destination(self) -> None:
        with patch("win_desktop.window_rect", return_value=(200, 200, 1200, 900)):
            self.assertEqual(self.actions.aim(self.target(), "left", (-0.2, 0)), "monitor vertical")
            self.assertEqual(self.actions.aim(self.target(), "down", (0, 0.2)), "monitor de baixo")
            self.assertIsNone(self.actions.aim(self.target(), "right", (0.2, 0)))

    def test_maximize_toggles(self) -> None:
        with (
            patch("gesture_actions._is_maximized", return_value=False),
            patch("win_desktop.show_window") as show,
            patch("win_desktop.bring_to_front", return_value=True),
        ):
            self.assertIn("estendida", self.actions.maximize(self.target()))
        show.assert_called_once_with(10, win_desktop.SW_MAXIMIZE)
        self.mocks["remember"].assert_called_once_with(10)
        with patch("gesture_actions._is_maximized", return_value=True), patch("win_desktop.show_window") as show:
            self.assertIn("restaurada", self.actions.maximize(self.target()))
        show.assert_called_once_with(10, win_desktop.SW_RESTORE)

    def test_undo_restores_the_last_moved_window_from_pc_control_memory(self) -> None:
        placement = win_desktop.Placement(0, 1, (0, 0), (0, 0), (10, 10, 500, 500))
        memory = pc_control.WindowMemory()
        memory.positions = {
            7: [pc_control.SavedPosition(placement, 1)],
            9: [pc_control.SavedPosition(placement, 3), pc_control.SavedPosition(placement, 2)],
        }
        with (
            patch.object(pc_control, "MEMORY", memory),
            patch("win_desktop.restore_placement") as restore,
            patch("win_desktop.window_title", return_value="Spotify"),
        ):
            self.assertIn("Spotify", self.actions.undo())
            restore.assert_called_once_with(9, placement)
            self.assertEqual(len(memory.positions[9]), 1)
            self.actions.undo()
            self.actions.undo()
            self.assertEqual(memory.positions, {})
            with self.assertRaises(GestureActionError):
                self.actions.undo()

    def test_close_respects_protected_processes_and_the_hud(self) -> None:
        with patch("win_desktop.close_window") as close:
            with self.assertRaises(GestureActionError):
                self.actions.close(self.target(window(process="explorer.exe")))
            with self.assertRaises(GestureActionError):
                self.actions.close(self.target(window(process="python.exe")))
            close.assert_not_called()
            self.assertIn("fechar", self.actions.close(self.target()))
            close.assert_called_once_with(10)

    def test_close_in_a_browser_closes_only_the_active_tab(self) -> None:
        browser = self.target(window(5, "YouTube - Edge", "msedge.exe"), browser=True)
        with (
            patch("win_desktop.bring_to_front", return_value=True),
            patch("pc_control._active_title", return_value="Lo-fi - YouTube"),
            patch("win_desktop.close_window") as close,
        ):
            self.assertIn("Lo-fi", self.actions.close(browser))
        close.assert_not_called()
        self.assertEqual(self.input.calls, [("keys", gesture_actions.VK_CONTROL, gesture_actions.VK_W)])

        self.input.calls.clear()
        with (
            patch("win_desktop.bring_to_front", return_value=True),
            patch("pc_control._active_title", return_value=f"{pc_control.HUD_TITLE} - Edge"),
        ):
            with self.assertRaises(GestureActionError):
                self.actions.close(browser)
        self.assertEqual(self.input.calls, [])

    def test_tabs_only_in_a_browser(self) -> None:
        browser = self.target(window(5, "YouTube - Edge", "msedge.exe"), browser=True)
        with patch.object(self.actions, "grab", return_value=self.target()):
            with self.assertRaises(GestureActionError):
                self.actions.tab(1)
        with patch.object(self.actions, "grab", return_value=browser), patch("gesture_actions._foreground_hwnd", return_value=5):
            self.actions.tab(1)
            self.actions.tab(-1)
        self.assertEqual(
            self.input.calls,
            [
                ("keys", gesture_actions.VK_CONTROL, gesture_actions.VK_TAB),
                ("keys", gesture_actions.VK_CONTROL, gesture_actions.VK_SHIFT, gesture_actions.VK_TAB),
            ],
        )

    def test_air_mouse_spans_every_monitor_including_negative_x(self) -> None:
        self.actions.mouse_move(0.0, 0.0)
        self.actions.mouse_move(1.0, 1.0)
        self.actions.mouse_move(0.1, 0.5)
        self.actions.click()
        self.assertEqual(self.input.calls[0], ("move", -1440, 0))
        self.assertEqual(self.input.calls[1], ("move", 2559, 2683))
        self.assertLess(self.input.calls[2][1], 0)  # monitor vertical, à esquerda
        self.assertEqual(self.input.calls[3:], [("button", True), ("button", False)])


class FakeTracker:
    def __init__(self, hands: list[Any]) -> None:
        self.hands = list(hands)

    def detect(self, _frame: np.ndarray, _t: float) -> Any:
        return self.hands.pop(0) if self.hands else None

    def close(self) -> None:
        pass


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def tick(self) -> None:
        self.t += 1 / FPS


def run_engine(timelines: list[list[tuple[float, Any]]], actions: Any, **kwargs: Any) -> tuple[GestureEngine, list[dict[str, Any]]]:
    hands = [hand for timeline in timelines for _, hand in timeline]
    clock = FakeClock()
    events: list[dict[str, Any]] = []

    def frames() -> Any:
        for _ in hands:
            yield np.zeros((360, 640, 3), dtype=np.uint8)
            clock.tick()

    engine = GestureEngine(frames(), actions, tracker=FakeTracker(hands), emit=events.append, clock=clock, **kwargs)
    engine.run(threading.Event())
    return engine, events


class EngineTests(unittest.TestCase):
    def fake_actions(self) -> MagicMock:
        actions = MagicMock()
        actions.grab.return_value = Target(window=window(), monitor=TOP, browser=False)
        actions.aim.return_value = "monitor de baixo"
        actions.throw.return_value = "'Bloco de notas' → monitor de baixo."
        return actions

    def test_grab_and_throw_reach_the_actions(self) -> None:
        actions = self.fake_actions()
        grab = hold("fist", 0.0, 0.4)
        drop = move("fist", end_of(grab), 0.3, (0.5, 0.4), (0.5, 0.7))
        release = hold("open", end_of(drop), 0.3, center=(0.5, 0.7))
        _, events = run_engine([grab, drop, release], actions, armed=True)
        actions.throw.assert_called_once()
        target, direction, _vector = actions.throw.call_args.args
        self.assertEqual((target.window.hwnd, direction), (10, "down"))
        self.assertIn({"event": "aim", "direction": "down", "target": "monitor de baixo"}, events)
        action = next(event for event in events if event["event"] == "action")
        self.assertEqual((action["action"], action["ok"]), ("throw", True))
        self.assertEqual(events[-1], {"event": "state", "state": "off"})

    def test_no_window_in_focus_aborts_the_grab(self) -> None:
        actions = self.fake_actions()
        actions.grab.return_value = None
        grab = hold("fist", 0.0, 0.4)
        _, events = run_engine([grab, hold("open", end_of(grab), 0.3)], actions, armed=True)
        actions.grab.assert_called_once()
        actions.maximize.assert_not_called()
        self.assertNotIn("grab", [event["event"] for event in events])

    def test_failed_action_is_reported_not_raised(self) -> None:
        actions = self.fake_actions()
        actions.close.side_effect = GestureActionError("Essa janela é do sistema ou do próprio Jarvis: não fecho.")
        _, events = run_engine([hold("thumb_down", 0.0, 1.6)], actions, armed=True)
        action = next(event for event in events if event["event"] == "action")
        self.assertFalse(action["ok"])
        self.assertIn("não fecho", action["message"])

    def test_overlay_shows_the_aim_and_the_countdown(self) -> None:
        actions = self.fake_actions()
        engine = GestureEngine([], actions, tracker=FakeTracker([]), clock=lambda: 0.0)
        engine.machine.arm(0.0)
        commands = play(engine.machine, hold("fist", 0.0, 0.4))
        for command in commands:
            engine._dispatch(command, 0.4)
        self.assertIn("SEGURANDO", engine.view(0.4).title)
        engine._dispatch(Command("aim", direction="down", vector=(0, 0.2)), 0.5)
        self.assertEqual(engine.view(0.5).title, "→ MONITOR DE BAIXO")

        engine = GestureEngine([], actions, tracker=FakeTracker([]), clock=lambda: 0.0)
        engine.machine.arm(0.0)
        down = hold("thumb_down", 0.0, 0.8)
        for command in play(engine.machine, down):
            engine._dispatch(command, down[-1][0])
        view = engine.view(down[-1][0])
        self.assertTrue(view.title.startswith("FECHAR JANELA?"))
        self.assertEqual(view.tone, "danger")
        self.assertGreater(view.progress, 0.3)

    def test_stopping_mid_drag_releases_the_mouse_button(self) -> None:
        actions = self.fake_actions()
        _, _ = run_engine([hold("pinch", 0.0, 0.8)], actions, mouse=True)
        actions.mouse_down.assert_called_once()
        actions.mouse_up.assert_called_once()


class OverlayRenderTests(unittest.TestCase):
    def test_render_and_premultiply(self) -> None:
        image = render(OverlayView("→ MONITOR DE CIMA", "abra a mão para soltar", 0.5, "armed"), 1.5)
        width, height = image.size
        self.assertGreater(width, 300)
        data = premultiplied_bgra(image)
        self.assertEqual(len(data), width * height * 4)
        pixels = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)
        self.assertEqual(pixels[0, 0, 3], 0)  # canto arredondado transparente
        self.assertTrue((pixels[..., :3] <= pixels[..., 3:4]).all())  # alpha pré-multiplicado

    def test_crosshair_is_centered_and_transparent_around(self) -> None:
        image = render_reticle(1.5)
        width, height = image.size
        self.assertEqual(width, height)
        self.assertEqual(width % 2, 1)
        pixels = np.asarray(image)
        self.assertEqual(pixels[0, 0, 3], 0)
        self.assertEqual(pixels[height // 2, width // 2, 3], 255)


def endless_frames(stop: threading.Event) -> Any:
    def frames() -> Any:
        while not stop.is_set():
            time.sleep(0.005)
            yield np.zeros((360, 640, 3), dtype=np.uint8)

    return frames()


class ServiceTests(unittest.TestCase):
    def service(self, frames_factory: Any) -> GestureService:
        return GestureService(
            frames_factory=frames_factory,
            actions_factory=MagicMock,
            overlay_factory=lambda: None,
            tracker_factory=lambda: FakeTracker([]),
        )

    def test_on_status_mouse_and_off(self) -> None:
        stop = threading.Event()
        service = self.service(lambda: (endless_frames(stop), "teste"))
        events: list[dict[str, Any]] = []
        service.set_listener("test", events.append)
        try:
            self.assertIn("Gestos ligados", voice_action("on", service))
            self.assertIn("ligados e armados", voice_action("status", service))
            self.assertIn("Mouse no ar ligado", voice_action("mouse_on", service))
            time.sleep(0.1)
            self.assertIn("mouse no ar", voice_action("status", service))
            self.assertIn("já estavam ligados", voice_action("on", service))
        finally:
            result = voice_action("off", service)
            stop.set()
        self.assertIn("webcam foi liberada", result)
        self.assertFalse(service.running)
        self.assertIn({"event": "state", "state": "mouse"}, events)
        self.assertIn("desligados", voice_action("status", service))
        self.assertIn("já estavam desligados", voice_action("off", service))

    def test_busy_webcam_is_reported(self) -> None:
        def busy() -> Any:
            raise gestures.CameraError("Não consegui abrir a webcam: ela pode estar em uso por outro app.")

        service = self.service(busy)
        result = voice_action("on", service)
        self.assertIn("Não consegui ligar os gestos", result)
        self.assertIn("em uso", result)
        self.assertIn("Último erro", voice_action("status", service))


class ToolAndSettingsTests(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        self.assertFalse(load_settings({"GOOGLE_API_KEY": "k"}).gestures_enabled)
        self.assertTrue(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_GESTURES": "true"}).gestures_enabled)

    def test_tool_is_registered_only_with_the_flag(self) -> None:
        from server import DIARY_TOOL_NAMES, GESTURE_TOOL_NAMES, MEMORY_TOOL_NAMES, ROUTINE_TOOL_NAMES, TOOL_NAMES
        from tools import build_tools

        names = [tool.__name__ for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k"}))]
        self.assertNotIn("gesture_control", names)
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_GESTURES": "true"})
        self.assertEqual([tool.__name__ for tool in build_tools(settings)], TOOL_NAMES + MEMORY_TOOL_NAMES + DIARY_TOOL_NAMES + ROUTINE_TOOL_NAMES + GESTURE_TOOL_NAMES)

    def test_voice_tool_calls_the_service(self) -> None:
        gesture_control, _shortcuts = gestures.build_gesture_tools()
        with patch("gestures.voice_action", return_value="Gestos ligados (teste).") as action:
            result = asyncio.run(gesture_control(FakeRunContext(), action="on"))
        action.assert_called_once_with("on")
        self.assertEqual(result, "Gestos ligados (teste).")

    def test_autostart_flag(self) -> None:
        with patch.dict("os.environ", {"JARVIS_GESTURES_AUTOSTART": "true"}):
            self.assertTrue(gestures.autostart_requested())
        with patch.dict("os.environ", {"JARVIS_GESTURES_AUTOSTART": ""}):
            self.assertFalse(gestures.autostart_requested())

    def test_direction_labels(self) -> None:
        self.assertEqual(describe_direction("up"), "monitor de cima")
        self.assertEqual(describe_direction("left"), "monitor da esquerda")


if __name__ == "__main__":
    unittest.main()
