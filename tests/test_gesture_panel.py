from __future__ import annotations

import threading
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

import win_desktop
from gesture_actions import DesktopActions, DryRunActions, GestureActionError, Target
from gesture_engine import GestureMachine, State
from gesture_map import (
    DesktopSnapshot,
    MapDrag,
    MapLayout,
    MapWindow,
    PanelConfig,
    PanelFrame,
    choose_monitor,
    monitor_at,
    panel_geometry,
    panel_origin,
    relative_rect,
    render_panel,
    uv_to_real,
    virtual_bounds,
    window_at,
)
from gesture_overlay import OverlayView
from gesture_panel import DesktopWatcher, GesturePanel, due_thumbnails
from gestures import PANEL_CAMERA_WIDTH, GestureEngine, GestureService, voice_action
from hand_fixtures import absent, end_of, hold, make_hand, move
from test_gestures import FakeClock, FakeTracker, endless_frames, kinds, play, window
from test_gestures import setUpModule, tearDownModule  # noqa: F401  (nada real no desktop)

# Os 3 monitores do Gabriel (pixels físicos): o de cima, o notebook embaixo e o vertical à
# esquerda, com x negativo.
TOP = win_desktop.Monitor(1, 0, 0, 2560, 1440, (0, 0, 2560, 1392), True, name="de cima")
NOTEBOOK = win_desktop.Monitor(2, 0, 1474, 1920, 2674, (0, 1474, 1920, 2602), False, name="notebook", internal=True)
VERTICAL = win_desktop.Monitor(3, -1440, 124, 0, 2684, (-1440, 124, 0, 2636), False, name="vertical")
SCREENS = (TOP, NOTEBOOK, VERTICAL)

# Mesmo arranjo com um notebook 2880x1800 a 200 % (DPI diferente do monitor de cima, a 100 %).
HIDPI_NOTEBOOK = win_desktop.Monitor(2, 0, 1440, 2880, 3240, (0, 1440, 2880, 3144), False, name="notebook", internal=True)

TERMINAL = MapWindow(41, "Terminal", "windowsterminal.exe", 4100, (200, 1600, 1100, 2400))
CHROME = MapWindow(42, "YouTube - Chrome", "chrome.exe", 4200, (-1440, 124, 0, 1500))
CODE = MapWindow(43, "Visual Studio Code", "code.exe", 4300, (0, 0, 2560, 1392), maximized=True)
DESKTOP = DesktopSnapshot(monitors=SCREENS, windows=(TERMINAL, CHROME, CODE))

MOUSE_BOX = GestureMachine().tuning.mouse_box


def hand_at(pose: str, point: tuple[float, float], bounds: tuple[int, int, int, int] | None = None) -> tuple[float, float]:
    """Palm center that puts the hand cursor (base of the index finger) over a desktop point."""
    left, top, right, bottom = bounds or virtual_bounds(SCREENS)
    u = (point[0] - left) / (right - left - 1)
    v = (point[1] - top) / (bottom - top - 1)
    x0, y0, x1, y1 = MOUSE_BOX
    px, py = x0 + u * (x1 - x0), y0 + v * (y1 - y0)
    offset = make_hand(pose, (0.5, 0.5)).points[5, :2] - 0.5
    return float(px - offset[0]), float(py - offset[1])


class FakePanel:
    def __init__(self, desktop: DesktopSnapshot = DESKTOP, visible: bool = True) -> None:
        self._desktop = desktop
        self.visible = visible
        self.frames: list[PanelFrame] = []
        self.started = self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def set_visible(self, on: bool) -> None:
        self.visible = on

    def desktop(self) -> DesktopSnapshot:
        return self._desktop

    def show(self, frame: PanelFrame) -> None:
        self.frames.append(frame)


def run_with_panel(timelines: list[list[tuple[float, Any]]], actions: Any, panel: Any, **kwargs: Any) -> tuple[GestureEngine, list[dict[str, Any]]]:
    hands = [hand for timeline in timelines for _, hand in timeline]
    clock = FakeClock()
    events: list[dict[str, Any]] = []

    def frames() -> Any:
        for _ in hands:
            yield np.zeros((360, 640, 3), dtype=np.uint8)
            clock.tick()

    engine = GestureEngine(frames(), actions, tracker=FakeTracker(hands), emit=events.append, clock=clock, panel=panel, **kwargs)
    engine.run(threading.Event())
    engine._executor.shutdown(wait=True)
    return engine, events


class GeometryTests(unittest.TestCase):
    def test_map_keeps_the_physical_layout_and_goes_back_to_real_coordinates(self) -> None:
        layout = MapLayout.fit(SCREENS, (8, 100, 352, 246))
        top = layout.rect_to_map((TOP.left, TOP.top, TOP.right, TOP.bottom))
        notebook = layout.rect_to_map((NOTEBOOK.left, NOTEBOOK.top, NOTEBOOK.right, NOTEBOOK.bottom))
        vertical = layout.rect_to_map((VERTICAL.left, VERTICAL.top, VERTICAL.right, VERTICAL.bottom))
        self.assertLess(vertical[2], top[0] + 1e-6)  # vertical à esquerda
        self.assertLess(top[3], notebook[1])  # notebook embaixo do de cima
        self.assertGreater(vertical[3] - vertical[1], vertical[2] - vertical[0])  # em pé
        # Proporções preservadas e tudo dentro da área do mapa.
        for real, drawn in ((TOP, top), (VERTICAL, vertical)):
            self.assertAlmostEqual(real.width / real.height, (drawn[2] - drawn[0]) / (drawn[3] - drawn[1]), places=6)
        for x0, y0, x1, y1 in (top, notebook, vertical):
            self.assertGreaterEqual(x0, 8 - 1e-6)
            self.assertLessEqual(x1, 352 + 1e-6)
            self.assertGreaterEqual(y0, 100 - 1e-6)
            self.assertLessEqual(y1, 246 + 1e-6)
        for point in ((-1440, 124), (-700, 2000), (0, 0), (2559, 1439), (1919, 2673)):
            back = layout.to_real(*layout.to_map(*point))
            self.assertAlmostEqual(back[0], point[0], places=6)
            self.assertAlmostEqual(back[1], point[1], places=6)

    def test_hand_spans_every_monitor_including_negative_x(self) -> None:
        bounds = virtual_bounds(SCREENS)
        self.assertEqual(bounds, (-1440, 0, 2560, 2684))
        self.assertEqual(uv_to_real(0.0, 0.0, bounds), (-1440, 0))
        self.assertEqual(uv_to_real(1.0, 1.0, bounds), (2559, 2683))
        self.assertEqual(uv_to_real(-3.0, 9.0, bounds), (-1440, 2683))
        self.assertIs(monitor_at(uv_to_real(0.1, 0.5, bounds), SCREENS), VERTICAL)

    def test_monitor_under_the_hand_and_in_the_gaps(self) -> None:
        self.assertIs(monitor_at((-10, 2000), SCREENS), VERTICAL)
        self.assertIs(monitor_at((100, 2000), SCREENS), NOTEBOOK)
        self.assertIs(monitor_at((1000, 1465), SCREENS), NOTEBOOK)  # faixa entre o de cima e o notebook, mais perto dele
        self.assertIs(monitor_at((-700, 40), SCREENS), VERTICAL)  # acima do vertical
        self.assertIs(monitor_at((2400, 2400), SCREENS), NOTEBOOK)  # à direita do notebook
        self.assertIsNone(monitor_at((0, 0), ()))

    def test_topmost_window_under_the_hand(self) -> None:
        overlapping = MapWindow(44, "Bloco de notas", "notepad.exe", 4400, (300, 1700, 900, 2000))
        windows = (overlapping, TERMINAL, CHROME, CODE)
        self.assertIs(window_at((500, 1800), windows), overlapping)
        self.assertIs(window_at((1000, 1800), windows), TERMINAL)
        self.assertIs(window_at((-1, 200), windows), CHROME)
        self.assertIsNone(window_at((1500, 2500), windows))

    def test_drop_keeps_the_relative_position(self) -> None:
        left_half = (0, 1474, 960, 2602)  # metade esquerda da área útil do notebook
        self.assertEqual(relative_rect(left_half, NOTEBOOK.work, TOP.work), (0, 0, 1280, 1392))
        # Do vertical (em pé) para o de cima: a mesma fração de largura e de altura.
        rect = relative_rect((-1440, 124, -720, 1380), VERTICAL.work, TOP.work)
        self.assertEqual(rect, (0, 0, 1280, 696))
        # Para o vertical, x negativo.
        self.assertEqual(relative_rect((1280, 696, 2560, 1392), TOP.work, VERTICAL.work), (-720, 1380, 0, 2636))

    def test_drop_between_monitors_with_different_dpi(self) -> None:
        # Janela de 960x540 físicos no de cima (100 %) → no notebook a 200 % fica com 2x os pixels,
        # o mesmo tamanho aparente.
        rect = relative_rect((640, 348, 1600, 888), TOP.work, HIDPI_NOTEBOOK.work)
        self.assertEqual(rect, (720, 1866, 1800, 2527))  # altura útil: 1392 → 1704
        width_share = (rect[2] - rect[0]) / (HIDPI_NOTEBOOK.work[2] - HIDPI_NOTEBOOK.work[0])
        self.assertAlmostEqual(width_share, 960 / 2560, places=2)
        back = relative_rect(rect, HIDPI_NOTEBOOK.work, TOP.work)
        for got, want in zip(back, (640, 348, 1600, 888)):
            self.assertLessEqual(abs(got - want), 2)
        layout = MapLayout.fit((TOP, HIDPI_NOTEBOOK, VERTICAL), (0, 0, 344, 150))
        self.assertAlmostEqual(layout.to_real(*layout.to_map(1440, 3000))[1], 3000, places=6)

    def test_drop_stays_inside_the_destination_and_keeps_a_usable_size(self) -> None:
        huge = relative_rect((-50, -20, 2700, 1500), TOP.work, NOTEBOOK.work)
        self.assertEqual(huge, NOTEBOOK.work)
        tiny = relative_rect((2500, 1300, 2510, 1310), TOP.work, NOTEBOOK.work)
        self.assertEqual((tiny[2] - tiny[0], tiny[3] - tiny[1]), (200, 120))
        self.assertLessEqual(tiny[2], NOTEBOOK.work[2])
        self.assertLessEqual(tiny[3], NOTEBOOK.work[3])

    def test_drag_follows_the_hand_and_knows_the_destination(self) -> None:
        drag = MapDrag(item=TERMINAL, source=NOTEBOOK, grab_point=(600, 2000))
        drag.update((700, 2100), SCREENS)
        self.assertIs(drag.dest, NOTEBOOK)
        self.assertFalse(drag.moves)
        drag.update((1200, 600), SCREENS)
        self.assertIs(drag.dest, TOP)
        self.assertTrue(drag.moves)
        self.assertEqual(drag.ghost(), (800, 200, 1700, 1000))
        drag.update((-300, 900), SCREENS)
        self.assertIs(drag.dest, VERTICAL)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_environment(self) -> None:
        self.assertEqual(PanelConfig.from_env({}), PanelConfig())
        config = PanelConfig.from_env(
            {
                "JARVIS_GESTURE_PANEL_CORNER": "superior esquerdo",
                "JARVIS_GESTURE_PANEL_MONITOR": "2",
                "JARVIS_GESTURE_PANEL_OPACITY": "0,7",
                "JARVIS_GESTURE_PANEL_SIZE": "420x300",
            }
        )
        self.assertEqual((config.corner, config.monitor, config.opacity, config.size), ("superior-esquerdo", "2", 0.7, (420, 300)))
        self.assertEqual(PanelConfig.from_env({"JARVIS_GESTURE_PANEL_CORNER": "top-right"}).corner, "superior-direito")
        bad = PanelConfig.from_env(
            {"JARVIS_GESTURE_PANEL_CORNER": "meio", "JARVIS_GESTURE_PANEL_OPACITY": "x", "JARVIS_GESTURE_PANEL_SIZE": "grande"}
        )
        self.assertEqual(bad, PanelConfig())
        self.assertEqual(PanelConfig.from_env({"JARVIS_GESTURE_PANEL_OPACITY": "0.05"}).opacity, 0.3)

    def test_panel_goes_to_the_notebook_corner_by_default(self) -> None:
        self.assertIs(choose_monitor("notebook", SCREENS), NOTEBOOK)
        self.assertIs(choose_monitor("3", SCREENS), VERTICAL)
        self.assertIs(choose_monitor("tela que não existe", SCREENS), NOTEBOOK)  # a tela embutida
        no_internal = [TOP, VERTICAL]
        self.assertIs(choose_monitor("notebook", no_internal), TOP)  # a principal
        self.assertIsNone(choose_monitor("notebook", []))

    def test_corner_positions_with_dpi_scale(self) -> None:
        work = NOTEBOOK.work
        self.assertEqual(panel_origin(work, (360, 260), "inferior-direito", 16), (1544, 2326))
        self.assertEqual(panel_origin(work, (360, 260), "superior-esquerdo", 16), (16, 1490))
        # A 200 %, o painel tem o dobro de pixels físicos e a margem também.
        geo = panel_geometry((360, 260), 2.0)
        self.assertEqual((geo.width, geo.height), (720, 520))
        x, y = panel_origin(HIDPI_NOTEBOOK.work, (geo.width, geo.height), "inferior-direito", 32)
        self.assertEqual((x + geo.width, y + geo.height), (2880 - 32, 3144 - 32))
        # No vertical (x negativo).
        self.assertEqual(panel_origin(VERTICAL.work, (360, 260), "inferior-esquerdo", 16), (-1424, 2360))


class RenderTests(unittest.TestCase):
    def frame(self, **kwargs: Any) -> PanelFrame:
        values: dict[str, Any] = {
            "view": OverlayView("GESTOS ATIVOS", "punho: pegar 'Terminal'", None, "armed"),
            "state": "armed",
            "camera": np.full((120, 213, 3), 40, dtype=np.uint8),
            "hand": make_hand("open").points[:, :2],
            "cursor": (600, 2000),
            "hover": TERMINAL.hwnd,
            "fps": 30.0,
        }
        values.update(kwargs)
        return PanelFrame(**values)

    def test_render_at_two_scales(self) -> None:
        for scale, size in ((1.0, (360, 260)), (2.0, (720, 520))):
            image = render_panel(self.frame(), DESKTOP, {}, scale)
            self.assertEqual(image.size, size)
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)  # canto arredondado transparente

    def test_destination_monitor_is_highlighted_while_dragging(self) -> None:
        drag = MapDrag(item=TERMINAL, source=NOTEBOOK, grab_point=(600, 2000))
        drag.update((2300, 1300), SCREENS)
        geo = panel_geometry()
        layout = MapLayout.fit(SCREENS, geo.map_area)
        # Um ponto vazio do notebook (origem) e um do de cima (destino): só o destino fica verde.
        empty = DesktopSnapshot(monitors=SCREENS, windows=(TERMINAL,))
        image = render_panel(self.frame(state="grab", cursor=None, closed=True, drag=drag, hover=None), empty, {})
        top_point = layout.to_map(2400, 100)
        notebook_point = layout.to_map(1800, 2600)
        top_color = image.getpixel((round(top_point[0]), round(top_point[1])))[:3]
        notebook_color = image.getpixel((round(notebook_point[0]), round(notebook_point[1])))[:3]
        self.assertGreater(top_color[1], notebook_color[1] + 15)

    def test_thumbnail_is_drawn_inside_the_window(self) -> None:
        from PIL import Image

        geo = panel_geometry()
        layout = MapLayout.fit(SCREENS, geo.map_area)
        thumb = Image.new("RGB", (320, 284), (255, 0, 0))
        image = render_panel(self.frame(cursor=None, hover=None), DesktopSnapshot(SCREENS, (TERMINAL,)), {TERMINAL.hwnd: thumb})
        x, y = layout.to_map(650, 2000)
        self.assertEqual(image.getpixel((round(x), round(y)))[:3], (255, 0, 0))

    def test_mouse_mode_and_empty_desktop_render(self) -> None:
        render_panel(self.frame(state="mouse", cursor=None, mouse=(-500, 500)), DESKTOP, {})
        render_panel(PanelFrame(view=None), DesktopSnapshot(), {})

    def test_render_is_cheap_enough_for_the_panel_thread(self) -> None:
        frame = self.frame()
        render_panel(frame, DESKTOP, {})
        start = time.perf_counter()
        for _ in range(10):
            render_panel(frame, DESKTOP, {}, 1.5)
        self.assertLess((time.perf_counter() - start) / 10, 0.05)


class WatcherTests(unittest.TestCase):
    def test_thumbnails_are_rate_limited(self) -> None:
        windows = (TERMINAL, CHROME, CODE)
        stamps = {TERMINAL.hwnd: 9.0, CHROME.hwnd: 5.0}
        self.assertEqual(due_thumbnails(windows, stamps, 10.0, 1.5, 2), [CODE.hwnd, CHROME.hwnd])
        self.assertEqual(due_thumbnails(windows, {w.hwnd: 9.5 for w in windows}, 10.0, 1.5, 3), [])

    def test_watcher_reads_once_a_second_and_takes_one_thumbnail_per_tick(self) -> None:
        clock = [0.0]
        reads: list[float] = []
        captured: list[tuple[float, int]] = []

        def read() -> DesktopSnapshot:
            reads.append(clock[0])
            windows = (TERMINAL, CHROME, CODE) if clock[0] < 3 else (TERMINAL,)
            return DesktopSnapshot(SCREENS, windows, clock[0])

        def capture(item: MapWindow) -> Any:
            captured.append((clock[0], item.hwnd))
            return f"thumb-{item.hwnd}"

        watcher = DesktopWatcher(read=read, capture=capture, clock=lambda: clock[0])
        while clock[0] < 4.0:
            watcher.tick()
            clock[0] = round(clock[0] + 0.2, 3)
        self.assertEqual(reads, [0.0, 1.0, 2.0, 3.0])
        per_tick: dict[float, int] = {}
        for t, _ in captured:
            per_tick[t] = per_tick.get(t, 0) + 1
        self.assertEqual(max(per_tick.values()), 1)
        last: dict[int, float] = {}
        for t, hwnd in captured:
            if hwnd in last:
                self.assertGreaterEqual(t - last[hwnd], 1.5 - 1e-9)
            last[hwnd] = t
        self.assertEqual(set(watcher.thumbs), {TERMINAL.hwnd})  # janelas fechadas saem do cache

    def test_failures_do_not_break_the_watcher(self) -> None:
        def read() -> DesktopSnapshot:
            raise OSError("sem telas")

        watcher = DesktopWatcher(read=read, capture=MagicMock(side_effect=OSError("preto")))
        watcher.tick()
        self.assertEqual(watcher.snapshot, DesktopSnapshot())

    def test_panel_front_without_threads(self) -> None:
        panel = GesturePanel(PanelConfig(), watcher=DesktopWatcher(read=lambda: DESKTOP), threads=False)
        panel.start()
        self.assertFalse(panel.visible)
        panel.set_visible(True)
        panel.watcher.tick()
        self.assertEqual(panel.desktop(), DESKTOP)
        panel.show(PanelFrame(view=None))
        panel.close()


class PanelGestureTests(unittest.TestCase):
    def test_two_fingers_held_still_toggle_the_panel_once(self) -> None:
        machine = GestureMachine()
        machine.arm(0.0)
        two = hold("two", 0.0, 1.6)
        commands = play(machine, two)
        self.assertEqual(kinds(commands).count("panel"), 1)
        self.assertEqual(machine.state, State.ARMED)
        again = hold("two", end_of(two), 1.6)
        self.assertNotIn("panel", kinds(play(machine, again)))  # precisa soltar os dois dedos
        rest = hold("open", end_of(again), 0.3)
        self.assertIn("panel", kinds(play(machine, rest, hold("two", end_of(rest), 1.6))))

    def test_tab_swipe_does_not_toggle_the_panel(self) -> None:
        machine = GestureMachine()
        machine.arm(0.0)
        swipe = move("two", 0.0, 0.3, (0.35, 0.5), (0.65, 0.5))
        commands = play(machine, hold("two", 0.0, 0.2), swipe, hold("two", end_of(swipe), 1.5, center=(0.65, 0.5)))
        self.assertIn("tab", kinds(commands))
        self.assertNotIn("panel", kinds(commands))

    def test_gesture_shows_and_hides_the_panel(self) -> None:
        panel = FakePanel(visible=False)
        two = hold("two", 0.0, 1.4)
        rest = hold("open", end_of(two), 0.3)
        engine, events = run_with_panel([two, rest, hold("two", end_of(rest), 1.4)], MagicMock(), panel, armed=True)
        panel_events = [event for event in events if event["event"] == "panel"]
        self.assertEqual(panel_events, [{"event": "panel", "visible": True}, {"event": "panel", "visible": False}])
        self.assertTrue(panel.started and panel.closed)
        self.assertTrue(panel.frames)  # recebeu quadros enquanto estava aberto


class MapDragTests(unittest.TestCase):
    def setUp(self) -> None:
        patches = [
            patch("win_desktop.monitors", return_value=list(SCREENS)),
            patch("gesture_actions._window_exists", return_value=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def drag_timelines(self, start: tuple[float, float], end: tuple[float, float]) -> list[list[tuple[float, Any]]]:
        hover = hold("open", 0.0, 0.5, center=hand_at("open", start))
        grab = hold("fist", end_of(hover), 0.5, center=hand_at("fist", start))
        carry = move("fist", end_of(grab), 0.6, hand_at("fist", start), hand_at("fist", end))
        settle = hold("fist", end_of(carry), 0.3, center=hand_at("fist", end))
        release = hold("open", end_of(settle), 0.4, center=hand_at("open", end))
        return [hover, grab, carry, settle, release]

    def test_fist_over_a_window_on_the_map_carries_it_to_another_monitor(self) -> None:
        panel = FakePanel()
        actions = DryRunActions()
        actions.grab = MagicMock()  # o punho no mapa não usa a janela em foco
        engine, events = run_with_panel(self.drag_timelines((650, 2000), (1300, 700)), actions, panel, armed=True)
        actions.grab.assert_not_called()
        grab = next(event for event in events if event["event"] == "grab")
        self.assertEqual((grab["title"], grab["map"]), ("Terminal", True))
        action = next(event for event in events if event["event"] == "action")
        self.assertEqual((action["action"], action["ok"]), ("drop", True))
        self.assertIn("(simulação) 'Terminal' → monitor de cima", action["message"])
        self.assertIn("posição relativa", action["message"])
        dragging = [frame for frame in panel.frames if frame.drag is not None]
        self.assertTrue(dragging)
        self.assertIs(dragging[-1].drag.dest, TOP)
        self.assertTrue(any(frame.view and frame.view.title == "→ MONITOR DE CIMA" for frame in dragging))
        self.assertIsNone(engine._drag)

    def test_drag_to_the_vertical_monitor_with_negative_x(self) -> None:
        actions = DryRunActions()
        _, events = run_with_panel(self.drag_timelines((1200, 700), (-700, 1500)), actions, FakePanel(), armed=True)
        grab = next(event for event in events if event["event"] == "grab")
        self.assertEqual(grab["title"], "Visual Studio Code")
        action = next(event for event in events if event["event"] == "action")
        self.assertIn("monitor vertical", action["message"])

    def test_dropping_on_the_same_monitor_changes_nothing(self) -> None:
        actions = MagicMock()
        _, events = run_with_panel(self.drag_timelines((650, 2000), (1500, 2300)), actions, FakePanel(), armed=True)
        actions.drop.assert_not_called()
        actions.throw.assert_not_called()
        actions.maximize.assert_not_called()
        self.assertIn({"event": "cancel"}, events)

    def test_losing_the_hand_while_carrying_cancels(self) -> None:
        actions = MagicMock()
        timelines = self.drag_timelines((650, 2000), (1300, 700))[:3]
        timelines.append(absent(end_of(timelines[-1]), 0.6))
        _, events = run_with_panel(timelines, actions, FakePanel(), armed=True)
        actions.drop.assert_not_called()
        self.assertIn({"event": "cancel"}, events)

    def test_fist_away_from_windows_grabs_the_focused_window_as_before(self) -> None:
        actions = MagicMock()
        actions.grab.return_value = Target(window=window(), monitor=TOP, browser=False)
        # Ponto vazio do notebook: sem janela embaixo da mão no mapa.
        timelines = self.drag_timelines((1700, 2600), (1700, 2600))
        _, events = run_with_panel(timelines, actions, FakePanel(), armed=True)
        actions.grab.assert_called_once()
        actions.maximize.assert_called_once()  # soltar parado estende, como sem o painel
        actions.drop.assert_not_called()

    def test_map_mode_is_off_with_the_panel_closed_and_in_the_air_mouse(self) -> None:
        actions = MagicMock()
        actions.grab.return_value = Target(window=window(), monitor=TOP, browser=False)
        _, _ = run_with_panel(self.drag_timelines((650, 2000), (1300, 700)), actions, FakePanel(visible=False), armed=True)
        actions.grab.assert_called_once()
        actions.drop.assert_not_called()

        panel = FakePanel()
        engine, _ = run_with_panel([hold("pinch", 0.0, 0.2), hold("point", 0.2, 0.5, center=hand_at("point", (-700, 900)))], MagicMock(), panel, mouse=True)
        mouse_frames = [frame for frame in panel.frames if frame.state == "mouse"]
        self.assertTrue(mouse_frames)
        self.assertTrue(all(frame.cursor is None and frame.drag is None for frame in mouse_frames))
        self.assertTrue(any(frame.mouse is not None for frame in mouse_frames))

    def test_panel_frames_are_small_and_never_block_the_gesture_loop(self) -> None:
        panel = FakePanel()
        hands = hold("open", 0.0, 1.0)
        engine, _ = run_with_panel([hands], MagicMock(), panel, armed=True)
        frame = panel.frames[-1]
        self.assertLessEqual(frame.camera.shape[1], PANEL_CAMERA_WIDTH * 2)
        self.assertEqual(frame.camera.shape[2], 3)
        self.assertEqual(frame.hand.shape, (21, 2))
        self.assertEqual(len(panel.frames), len(hands))  # um quadro por quadro da câmera, sem desenhar aqui

        # O custo do painel na thread dos gestos (copiar a câmera e achar a janela) é desprezível.
        clock = FakeClock()
        engine = GestureEngine([], MagicMock(), tracker=FakeTracker([]), clock=clock, panel=FakePanel())
        engine.machine.arm(0.0)
        image = np.zeros((360, 640, 3), dtype=np.uint8)
        engine.tracker = FakeTracker([make_hand("open", hand_at("open", (650, 2000)))] * 60)
        start = time.perf_counter()
        for _ in range(60):
            engine.process(image)
            clock.tick()
        per_frame = (time.perf_counter() - start) / 60
        self.assertLess(per_frame, 1 / 25)


class DropActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mocks = {
            "monitors": patch("win_desktop.monitors", return_value=list(SCREENS)),
            "exists": patch("gesture_actions._window_exists", return_value=True),
            "zoomed": patch("gesture_actions._is_maximized", return_value=False),
            "rect": patch("win_desktop.window_rect", return_value=(0, 1474, 960, 2602)),
            "place": patch("win_desktop.place_window"),
            "move": patch("win_desktop.move_to_monitor"),
            "landed": patch("win_desktop.window_monitor", return_value=TOP),
            "remember": patch("pc_control._remember_position"),
        }
        self.m = {name: p.start() for name, p in self.mocks.items()}
        for p in self.mocks.values():
            self.addCleanup(p.stop)
        self.actions = DesktopActions(MagicMock())
        self.target = Target(window=window(), monitor=NOTEBOOK, browser=False)

    def test_drop_places_the_window_at_the_same_relative_spot_and_can_be_undone(self) -> None:
        message = self.actions.drop(self.target, TOP)
        self.m["place"].assert_called_once_with(10, (0, 0, 1280, 1392))
        self.m["remember"].assert_called_once_with(10)
        self.assertIn("monitor de cima", message)

    def test_maximized_window_stays_maximized(self) -> None:
        self.m["zoomed"].return_value = True
        self.actions.drop(self.target, TOP)
        self.m["move"].assert_called_once_with(10, TOP, maximize=True)
        self.m["place"].assert_not_called()

    def test_same_monitor_and_failures(self) -> None:
        with self.assertRaises(GestureActionError):
            self.actions.drop(self.target, NOTEBOOK)
        self.m["landed"].return_value = NOTEBOOK
        with self.assertRaisesRegex(GestureActionError, "não saiu do lugar"):
            self.actions.drop(self.target, TOP)
        self.m["exists"].return_value = False
        with self.assertRaisesRegex(GestureActionError, "fechou"):
            self.actions.drop(self.target, TOP)


class PanelServiceTests(unittest.TestCase):
    def test_voice_opens_and_closes_the_panel(self) -> None:
        stop = threading.Event()
        panel = FakePanel(visible=False)
        service = GestureService(
            frames_factory=lambda: (endless_frames(stop), "teste"),
            actions_factory=MagicMock,
            overlay_factory=lambda: None,
            tracker_factory=lambda: FakeTracker([]),
            panel_factory=lambda: panel,
        )
        events: list[dict[str, Any]] = []
        service.set_listener("test", events.append)
        try:
            self.assertIn("painel de gestos", voice_action("panel_on", service))  # liga os gestos junto
            deadline = time.monotonic() + 2
            while not panel.visible and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(panel.visible)
            self.assertIn("painel aberto", voice_action("status", service))
            self.assertIn("Painel de gestos fechado", voice_action("panel_off", service))
            deadline = time.monotonic() + 2
            while panel.visible and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(panel.visible)
        finally:
            voice_action("off", service)
            stop.set()
        self.assertIn({"event": "panel", "visible": True}, events)
        self.assertIn("desligados", voice_action("panel_off", service))


if __name__ == "__main__":
    unittest.main()
