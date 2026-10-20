from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import tray
import tray_icon
from server import create_app
from tray import Autostart, MenuEntry, TrayController, TrayState, build_menu
from tray_icon import WM_BALLOON, WM_CLOSE, WM_DESTROY, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_STATE, WM_TRAY, Win32TrayIcon
from wake_hub import WakeHub, _config_event
from settings import load_settings

SECRET = "tray-s3cret"
TRAY = {tray.SECRET_HEADER: SECRET}
TAB = "tab-12345678"
LIVEKIT_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "LIVEKIT_URL": "wss://jarvis.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "a-very-long-test-secret-with-enough-entropy",
}


def queued(hub: WakeHub, client_id: str) -> list[dict]:
    queue = hub.clients[client_id].queue
    return [queue.get_nowait() for _ in range(queue.qsize())]


class FakeResponse:
    def __init__(self, body: dict | None = None, status: int = 200) -> None:
        self.body = body or {}
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(self.status)

    def json(self) -> dict:
        return self.body


class FakeHttp:
    def __init__(self, state: dict | None = None, link: dict | None = None) -> None:
        self.state = state
        self.link = link or {}
        self.calls: list[tuple] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        if self.state is None:
            raise ConnectionError("servidor parado")
        return FakeResponse(self.state)

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        if self.state is None:
            raise ConnectionError("servidor parado")
        return FakeResponse(self.link)


class FakeRegistry:
    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class FakeGestures:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> str:
        self.running = True
        return "Gestos ligados."

    def stop(self) -> str:
        self.running = False
        return "Gestos desligados; a webcam foi liberada."


def controller(**kwargs) -> TrayController:
    defaults = {
        "hud_url": "http://127.0.0.1:8000",
        "secret": SECRET,
        "http": FakeHttp({"link": False, "listening": False}),
        "autostart": Autostart(FakeRegistry(), command=["pythonw.exe", "jarvis.py", "--tray"]),
        "open_browser": MagicMock(),
        "open_folder": MagicMock(),
    }
    return TrayController(**{**defaults, **kwargs})


class TrayStateTests(unittest.TestCase):
    def test_level_follows_server_link_agent_and_detector(self) -> None:
        self.assertEqual(TrayState().level, "off")
        self.assertEqual(TrayState(server=True, agent=True).level, "ready")
        self.assertEqual(TrayState(server=True, agent=True, listening=True).level, "listening")
        self.assertEqual(TrayState(server=True, agent=False).level, "warn")
        self.assertEqual(TrayState(server=True, agent=True, link=True, listening=True).level, "link")
        self.assertEqual(TrayState(server=True, agent=None).level, "ready")

    def test_tooltip_fits_the_windows_limit(self) -> None:
        tip = TrayState(server=True, agent=True, listening=True, gestures=True).tooltip()

        self.assertIn("Jarvis: ouvindo", tip)
        self.assertIn("Agente: ok", tip)
        self.assertIn("Gestos: ligados", tip)
        self.assertLessEqual(len(tip), tray.TIP_MAX)
        self.assertIn("Agente: desligado", TrayState(server=True).tooltip())

    def test_menu_toggles_the_link_and_greys_what_is_unavailable(self) -> None:
        closed = {entry.command: entry for entry in build_menu(TrayState(server=True, agent=True))}
        opened = {entry.command: entry for entry in build_menu(TrayState(server=True, link=True, gestures_available=True))}

        self.assertIn("link_start", closed)
        self.assertNotIn("link_stop", closed)
        self.assertEqual(opened["link_stop"].label, "Encerrar o link")
        self.assertFalse(closed["gestures"].enabled)
        self.assertTrue(opened["gestures"].enabled)
        self.assertTrue(closed["open_hud"].default)
        self.assertFalse({entry.command: entry for entry in build_menu(TrayState())}["open_hud"].enabled)

    def test_header_is_disabled_and_separators_have_no_command(self) -> None:
        menu = build_menu(TrayState(server=True, autostart=True))

        self.assertFalse(menu[0].enabled)
        self.assertTrue(menu[1].separator)
        self.assertTrue(next(entry for entry in menu if entry.command == "autostart").checked)


class ControllerTests(unittest.TestCase):
    def test_poll_reads_the_server_agent_gestures_and_autostart(self) -> None:
        gestures = FakeGestures()
        gestures.running = True
        tray_controller = controller(
            http=FakeHttp({"link": True, "listening": False}),
            agent=lambda: True,
            gestures=lambda: gestures,
            autostart=Autostart(FakeRegistry({tray.RUN_VALUE: "x"})),
        )

        state = tray_controller.poll()

        self.assertEqual(
            state,
            TrayState(server=True, agent=True, link=True, gestures=True, gestures_available=True, autostart=True),
        )

    def test_poll_sends_the_secret_and_survives_a_stopped_server(self) -> None:
        http = FakeHttp(None)

        state = controller(http=http).poll()

        self.assertFalse(state.server)
        self.assertEqual(http.calls[0][1], "http://127.0.0.1:8000/api/tray/state")
        self.assertEqual(http.calls[0][2]["headers"], TRAY)

    def test_open_hud_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            tray_controller = controller(log_dir=Path(folder) / "logs")

            tray_controller.run("open_hud")
            tray_controller.run("logs")

            tray_controller._open_browser.assert_called_once_with("http://127.0.0.1:8000/")
            tray_controller._open_folder.assert_called_once_with(Path(folder) / "logs")
            self.assertTrue((Path(folder) / "logs").is_dir())

    def test_link_start_and_stop_go_through_the_server(self) -> None:
        http = FakeHttp({}, {"accepted": True, "opened_browser": True})
        tray_controller = controller(http=http)

        self.assertEqual(tray_controller.run("link_start"), "Abrindo o HUD para conectar o link.")
        self.assertEqual(http.calls[-1][2]["json"], {"action": "start"})
        http.link = {"accepted": False, "opened_browser": False}
        self.assertEqual(tray_controller.run("link_start"), "O link já está aberto ou abrindo.")
        http.link = {"closed": 0}
        self.assertEqual(tray_controller.run("link_stop"), "Nenhum link aberto.")
        http.link = {"closed": 1}
        self.assertIsNone(tray_controller.run("link_stop"))
        self.assertEqual(controller(http=FakeHttp(None)).run("link_start"), "O servidor do HUD não respondeu.")

    def test_gestures_toggle_and_shutdown_only_stops_what_the_tray_started(self) -> None:
        gestures = FakeGestures()
        tray_controller = controller(gestures=lambda: gestures)

        self.assertEqual(tray_controller.run("gestures"), "Gestos ligados.")
        self.assertTrue(gestures.running)
        tray_controller.shutdown()
        self.assertFalse(gestures.running)

        gestures.running = True  # ligados por outro caminho (--gestures sem agente)
        other = controller(gestures=lambda: gestures)
        other.poll()
        other.shutdown()
        self.assertTrue(gestures.running)

    def test_gestures_off_in_env_explains_why(self) -> None:
        self.assertIn("JARVIS_ENABLE_GESTURES", controller().run("gestures"))

    def test_broken_gesture_import_turns_the_item_off(self) -> None:
        def broken() -> FakeGestures:
            raise ImportError("sem mediapipe")

        tray_controller = controller(gestures=broken)

        self.assertFalse(tray_controller.poll().gestures_available)

    def test_autostart_toggle(self) -> None:
        registry = FakeRegistry()
        tray_controller = controller(autostart=Autostart(registry, command=["pythonw.exe", "jarvis.py", "--tray"]))

        self.assertEqual(tray_controller.run("autostart"), "O Jarvis vai abrir junto com o Windows.")
        self.assertEqual(registry.values[tray.RUN_VALUE], "pythonw.exe jarvis.py --tray")
        self.assertEqual(tray_controller.run("autostart"), "O Jarvis não abre mais com o Windows.")
        self.assertEqual(registry.values, {})

    def test_restart_and_quit_stop_the_server(self) -> None:
        stop = MagicMock()
        tray_controller = controller(stop_server=stop)

        tray_controller.run("quit")
        self.assertFalse(tray_controller.restart_requested)
        tray_controller.run("restart")
        self.assertTrue(tray_controller.restart_requested)
        self.assertEqual(stop.call_count, 2)

    def test_watch_reports_only_changes(self) -> None:
        http = FakeHttp({"link": False, "listening": False})
        tray_controller = controller(http=http)
        stop = threading.Event()
        seen: list[TrayState] = []
        polls = iter([None, None, {"link": True}])

        def on_change(state: TrayState) -> None:
            seen.append(state)

        original = tray_controller.poll

        def poll() -> TrayState:
            try:
                http.state = next(polls) or http.state
            except StopIteration:
                stop.set()
            return original()

        tray_controller.poll = poll  # type: ignore[method-assign]
        tray_controller.watch(on_change, stop, interval=0)

        self.assertEqual([state.link for state in seen], [False, True])

    def test_stop_server_sets_uvicorn_exit(self) -> None:
        server = SimpleNamespace(should_exit=False)
        tray.stop_server(SimpleNamespace(state=SimpleNamespace(uvicorn=server)))

        self.assertTrue(server.should_exit)
        tray.stop_server(SimpleNamespace(state=SimpleNamespace()))


class TrayEndpointTests(unittest.TestCase):
    def client(self, env: dict[str, str]) -> tuple[TestClient, MagicMock]:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        browser = MagicMock()
        return TestClient(create_app(reload_env=False, open_browser=browser)), browser

    def test_needs_the_secret(self) -> None:
        client, _ = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})

        self.assertEqual(client.get("/api/tray/state").status_code, 403)
        self.assertEqual(client.get("/api/tray/state", headers={tray.SECRET_HEADER: "chute"}).status_code, 403)
        self.assertEqual(client.post("/api/tray/link", json={"action": "start"}).status_code, 403)
        cross = {**TRAY, "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(client.get("/api/tray/state", headers=cross).status_code, 403)
        self.assertEqual(client.get("/api/tray/state", headers=TRAY).status_code, 200)

    def test_without_tray_nothing_answers(self) -> None:
        client, _ = self.client(LIVEKIT_ENV)

        self.assertEqual(client.get("/api/tray/state", headers=TRAY).status_code, 403)
        self.assertFalse(client.get("/api/status").json()["tray"])

    def test_status_and_stream_config_tell_the_hud(self) -> None:
        client, _ = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})

        self.assertTrue(client.get("/api/status").json()["tray"])
        self.assertTrue(_config_event(load_settings())["tray"])

    def test_state_follows_the_open_link(self) -> None:
        client, _ = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})
        hub: WakeHub = client.app.state.wake_hub

        self.assertEqual(client.get("/api/tray/state", headers=TRAY).json(), {"link": False, "listening": False, "detector": False, "tabs": 0})
        hub.connect(TAB)
        hub.update(TAB, session_active=True, visible=True, mic_label=None)
        self.assertEqual(client.get("/api/tray/state", headers=TRAY).json()["link"], True)

    def test_start_without_a_tab_opens_the_browser(self) -> None:
        client, browser = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})

        body = client.post("/api/tray/link", json={"action": "start"}, headers=TRAY).json()

        self.assertEqual(body, {"accepted": True, "opened_browser": True})
        browser.assert_called_once_with("http://testserver/")
        client.app.state.wake_hub.connect(TAB)
        self.assertEqual(queued(client.app.state.wake_hub, TAB), [{"type": "wake", "score": 1.0, "reason": "tray"}])

    def test_start_with_a_tab_wakes_it(self) -> None:
        client, browser = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})
        client.app.state.wake_hub.connect(TAB)

        body = client.post("/api/tray/link", json={"action": "start"}, headers=TRAY).json()

        self.assertEqual(body, {"accepted": True, "opened_browser": False})
        browser.assert_not_called()
        self.assertEqual(queued(client.app.state.wake_hub, TAB), [{"type": "wake", "score": 1.0, "reason": "tray"}])

    def test_stop_asks_only_tabs_in_a_conversation(self) -> None:
        client, _ = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})
        hub: WakeHub = client.app.state.wake_hub
        hub.connect(TAB)
        hub.connect("tab-87654321")
        hub.update(TAB, session_active=True, visible=True, mic_label=None)

        self.assertEqual(client.post("/api/tray/link", json={"action": "stop"}, headers=TRAY).json(), {"closed": 1})
        self.assertEqual(queued(hub, TAB), [{"type": "sleep", "reason": "tray"}])
        self.assertEqual(queued(hub, "tab-87654321"), [])

    def test_rejects_unknown_actions(self) -> None:
        client, _ = self.client({**LIVEKIT_ENV, tray.SECRET_ENV: SECRET})

        self.assertEqual(client.post("/api/tray/link", json={"action": "reboot"}, headers=TRAY).status_code, 422)


class AutostartTests(unittest.TestCase):
    def test_command_prefers_pythonw_next_to_python(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            python = Path(folder) / "python.exe"
            python.touch()
            self.assertEqual(tray.pythonw_executable(str(python)), str(python))
            (Path(folder) / "pythonw.exe").touch()
            self.assertEqual(tray.pythonw_executable(str(python)), str(Path(folder) / "pythonw.exe"))

    def test_default_command_starts_the_tray_without_a_browser_tab(self) -> None:
        command = tray.jarvis_command(["--no-browser"], executable="C:/venv/Scripts/python.exe")

        self.assertEqual(command[1:], [str(tray.ROOT / "jarvis.py"), "--tray", "--no-browser"])

    def test_enable_disable_and_refresh(self) -> None:
        registry = FakeRegistry()
        autostart = Autostart(registry, command=["pythonw.exe", "C:/Jarvis AI/jarvis.py", "--tray"])

        self.assertFalse(autostart.enabled())
        self.assertFalse(autostart.refresh())
        autostart.set(True)
        self.assertEqual(registry.values[tray.RUN_VALUE], 'pythonw.exe "C:/Jarvis AI/jarvis.py" --tray')
        self.assertFalse(autostart.refresh())
        registry.values[tray.RUN_VALUE] = "pythonw.exe D:/antigo/jarvis.py --tray"
        self.assertTrue(autostart.refresh())
        self.assertEqual(registry.values[tray.RUN_VALUE], autostart.command)
        autostart.set(False)
        self.assertFalse(autostart.enabled())

    def test_off_windows_there_is_no_registry(self) -> None:
        with patch.object(tray, "IS_WINDOWS", False):
            autostart = Autostart()

            self.assertFalse(autostart.enabled())
            self.assertRaises(OSError, autostart.set, True)
            self.assertIn("só existe no Windows", controller(autostart=autostart).run("autostart"))

    def test_relaunch_keeps_the_options_and_skips_the_browser(self) -> None:
        popen = MagicMock()

        tray.relaunch(["--tray", "--port", "8080", "--gestures"], popen=popen)

        command = popen.call_args.args[0]
        self.assertEqual(command[1:], [str(tray.ROOT / "jarvis.py"), "--tray", "--port", "8080", "--gestures", "--no-browser"])
        self.assertEqual(popen.call_args.kwargs["cwd"], tray.ROOT)


class WantedTests(unittest.TestCase):
    def test_flag_or_env_only_on_windows(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(tray, "IS_WINDOWS", True):
            self.assertFalse(tray.wanted(False))
            self.assertTrue(tray.wanted(True))
        with patch.dict(os.environ, {"JARVIS_TRAY": "true"}, clear=True), patch.object(tray, "IS_WINDOWS", True):
            self.assertTrue(tray.wanted(False))
        with patch.dict(os.environ, {"JARVIS_TRAY": "true"}, clear=True), patch.object(tray, "IS_WINDOWS", False):
            with patch("builtins.print") as printed:
                self.assertFalse(tray.wanted(False))
            self.assertIn("só existe no Windows", printed.call_args.args[0])

    def test_invalid_env_value_keeps_the_tray_off(self) -> None:
        with patch.dict(os.environ, {"JARVIS_TRAY": "talvez"}, clear=True), patch("builtins.print"):
            self.assertFalse(tray.wanted(False))

    def test_new_secret_goes_to_the_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            secret = tray.new_secret()

            self.assertEqual(os.environ[tray.SECRET_ENV], secret)
            self.assertGreater(len(secret), 20)


class FileLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = logging.getLogger()
        handlers = list(root.handlers)
        streams = (sys.stdout, sys.stderr)
        env = patch.dict(os.environ, {})
        env.start()

        def restore() -> None:
            for handler in root.handlers[:]:
                if handler not in handlers:
                    handler.close()
                    root.removeHandler(handler)
            sys.stdout, sys.stderr = streams
            env.stop()

        self.addCleanup(restore)

    def test_print_and_stderr_land_in_the_file(self) -> None:
        with patch.object(sys, "__stdout__", None):
            path = tray.setup_file_logging(Path(self.folder.name) / "logs")
        print("[HUD] Interface disponível em http://127.0.0.1:8000")
        sys.stderr.write("Traceback falso\nsegunda ")
        sys.stderr.write("linha\n")

        text = path.read_text(encoding="utf-8")
        self.assertIn("[jarvis] [HUD] Interface disponível", text)
        self.assertIn("[jarvis.erro] segunda linha", text)
        self.assertEqual(os.environ["PYTHONUNBUFFERED"], "1")

    def test_the_file_rotates(self) -> None:
        with patch.object(sys, "__stdout__", None), patch.object(tray, "LOG_MAX_BYTES", 200):
            path = tray.setup_file_logging(Path(self.folder.name))
        for index in range(20):
            print(f"linha {index} " + "x" * 40)

        self.assertTrue(path.with_name("jarvis.log.1").exists())
        self.assertFalse(path.with_name(f"jarvis.log.{tray.LOG_BACKUPS + 1}").exists())

    def test_child_output_is_pumped_into_the_log(self) -> None:
        with patch.object(sys, "__stdout__", None):
            path = tray.setup_file_logging(Path(self.folder.name))
        process = SimpleNamespace(stdout=io.BytesIO("[AGENTE] conectado\n\nçã ok\n".encode()))

        tray.pump_output(process, "agente").join(timeout=2)

        text = path.read_text(encoding="utf-8")
        self.assertIn("[jarvis.agente] [AGENTE] conectado", text)
        self.assertIn("çã ok", text)
        self.assertIsNone(tray.pump_output(SimpleNamespace(stdout=None), "x"))

    def test_child_output_pipes_and_hides_windows(self) -> None:
        kwargs = tray.child_output()

        self.assertEqual(kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        with patch.object(tray, "IS_WINDOWS", True), patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True):
            self.assertEqual(tray.child_output()["creationflags"], 0x08000000)


class FakeApi:
    def __init__(self, choice: str | None = None) -> None:
        self.calls: list[tuple] = []
        self.choice = choice
        self.menus: list[list[MenuEntry]] = []

    def create_window(self, handler) -> int:
        self.handler = handler
        return 42

    def register_message(self, name: str) -> int:
        return 0xC123

    def add_icon(self, hwnd, icon, tip) -> bool:
        self.calls.append(("add", icon, tip))
        return True

    def modify_icon(self, hwnd, icon, tip) -> bool:
        self.calls.append(("modify", icon, tip))
        return True

    def balloon(self, hwnd, title, text) -> bool:
        self.calls.append(("balloon", title, text))
        return True

    def delete_icon(self, hwnd) -> None:
        self.calls.append(("delete",))

    def load_icon(self, path) -> int:
        return 1000 + len(self.calls)

    def destroy_icon(self, icon) -> None:
        self.calls.append(("destroy_icon", icon))

    def show_menu(self, hwnd, entries) -> str | None:
        self.menus.append(entries)
        return self.choice

    def post(self, hwnd, msg) -> None:
        self.calls.append(("post", msg))

    def destroy_window(self, hwnd) -> None:
        self.calls.append(("destroy_window",))

    def quit(self) -> None:
        self.calls.append(("quit",))

    def loop(self) -> None:
        self.calls.append(("loop",))


class Win32IconTests(unittest.TestCase):
    def icon(self, choice: str | None = None) -> tuple[Win32TrayIcon, FakeApi, MagicMock, list]:
        api = FakeApi(choice)
        tray_controller = MagicMock()
        tray_controller.menu.return_value = build_menu(TrayState(server=True))
        tray_controller.run.return_value = None
        tray_controller.poll.return_value = TrayState(server=True, link=True)
        spawned: list = []
        icon = Win32TrayIcon(tray_controller, api, icon_path=lambda level: None, spawn=spawned.append)
        icon.run()
        return icon, api, tray_controller, spawned

    def test_run_adds_the_icon_starts_watching_and_pumps_messages(self) -> None:
        icon, api, _, spawned = self.icon()

        self.assertEqual(api.calls[0][0], "add")
        self.assertIn("servidor parado", api.calls[0][2])
        self.assertEqual(api.calls[-1], ("loop",))
        self.assertEqual(len(spawned), 1)

    def test_right_click_runs_the_chosen_command_off_the_window_thread(self) -> None:
        icon, api, tray_controller, spawned = self.icon("link_start")

        self.assertEqual(icon.handle(42, WM_TRAY, 0, WM_RBUTTONUP), 0)

        tray_controller.run.assert_not_called()
        spawned[-1]()
        tray_controller.run.assert_called_once_with("link_start")
        self.assertIn(("post", WM_STATE), api.calls)

    def test_closing_the_menu_runs_nothing(self) -> None:
        icon, _, _, spawned = self.icon(None)

        icon.handle(42, WM_TRAY, 0, WM_RBUTTONUP)

        self.assertEqual(len(spawned), 1)

    def test_double_click_opens_the_hud(self) -> None:
        icon, _, tray_controller, spawned = self.icon()

        icon.handle(42, WM_TRAY, 0, WM_LBUTTONDBLCLK)
        spawned[-1]()

        tray_controller.run.assert_called_once_with("open_hud")

    def test_messages_become_notifications(self) -> None:
        icon, api, tray_controller, spawned = self.icon("gestures")
        tray_controller.run.return_value = "Gestos ligados."

        icon.handle(42, WM_TRAY, 0, WM_RBUTTONUP)
        with patch("builtins.print"):
            spawned[-1]()
        icon.handle(42, WM_BALLOON, 0, 0)

        self.assertIn(("balloon", "Jarvis", "Gestos ligados."), api.calls)

    def test_failing_command_is_reported_not_raised(self) -> None:
        icon, api, tray_controller, spawned = self.icon("autostart")
        tray_controller.run.side_effect = RuntimeError("registro travado")

        icon.handle(42, WM_TRAY, 0, WM_RBUTTONUP)
        with patch("builtins.print"), self.assertLogs("jarvis-tray", "ERROR"):
            spawned[-1]()
        icon.handle(42, WM_BALLOON, 0, 0)

        self.assertIn("registro travado", api.calls[-1][2])

    def test_state_change_updates_icon_and_tip_on_the_window_thread(self) -> None:
        icon, api, _, _ = self.icon()

        icon.update(TrayState(server=True, agent=True, link=True))
        self.assertIn(("post", WM_STATE), api.calls)
        icon.handle(42, WM_STATE, 0, 0)

        self.assertEqual(api.calls[-1][0], "modify")
        self.assertIn("link aberto", api.calls[-1][2])
        self.assertEqual(icon.state.level, "link")

    def test_explorer_restart_adds_the_icon_again(self) -> None:
        icon, api, _, _ = self.icon()

        icon.handle(42, 0xC123, 0, 0)

        self.assertEqual([call[0] for call in api.calls].count("add"), 2)

    def test_stop_removes_the_icon_and_ends_the_loop(self) -> None:
        icon, api, _, _ = self.icon()

        icon.stop()
        self.assertIn(("post", WM_CLOSE), api.calls)
        icon.handle(42, WM_CLOSE, 0, 0)
        icon.handle(42, WM_DESTROY, 0, 0)

        names = [call[0] for call in api.calls]
        self.assertIn("delete", names)
        self.assertIn("destroy_icon", names)
        self.assertIn("destroy_window", names)
        self.assertEqual(names[-1], "quit")
        self.assertIsNone(icon.hwnd)

    def test_other_messages_go_to_the_default_handler(self) -> None:
        icon, _, _, _ = self.icon()

        self.assertIsNone(icon.handle(42, 0x0001, 0, 0))


class IconDrawingTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow não instalado")

    def test_each_state_has_its_color(self) -> None:
        link = tray_icon.render_icon("link", 64)
        off = tray_icon.render_icon("off", 64)

        self.assertEqual(link.size, (64, 64))
        self.assertEqual(link.getpixel((32, 32))[:3], tray_icon.COLORS["link"])
        self.assertNotEqual(off.getpixel((32, 32))[:3], tray_icon.COLORS["off"])

    def test_icon_file_is_a_multi_size_ico(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = tray_icon.icon_file("ready", Path(folder))

            self.assertIsNotNone(path)
            self.assertEqual(path.read_bytes()[:4], b"\x00\x00\x01\x00")


class JarvisIntegrationTests(unittest.TestCase):
    def test_tray_controller_reports_the_agent(self) -> None:
        import jarvis

        app = SimpleNamespace(state=SimpleNamespace(uvicorn=SimpleNamespace(should_exit=False)))
        alive = MagicMock()
        alive.poll.return_value = None
        args = SimpleNamespace(no_agent=False, gestures=False)
        with patch.dict(os.environ, {tray.SECRET_ENV: SECRET}), patch.object(tray.Autostart, "refresh", return_value=False):
            built = jarvis._tray_controller(app, "http://127.0.0.1:8000", args, alive)
            self.assertTrue(built._agent())
            alive.poll.return_value = 1
            self.assertFalse(built._agent())
            self.assertFalse(jarvis._tray_controller(app, "http://x", args, None)._agent())
            self.assertIsNone(jarvis._tray_controller(app, "http://x", SimpleNamespace(no_agent=True, gestures=False), None)._agent())
            built.run("quit")

        self.assertTrue(app.state.uvicorn.should_exit)

    def test_gestures_item_follows_the_flag(self) -> None:
        import jarvis

        app = SimpleNamespace(state=SimpleNamespace())
        with patch.dict(os.environ, {tray.SECRET_ENV: SECRET, "JARVIS_ENABLE_GESTURES": "false"}), patch.object(
            tray.Autostart, "refresh", return_value=False
        ):
            off = jarvis._tray_controller(app, "http://x", SimpleNamespace(no_agent=True, gestures=False), None)
            on = jarvis._tray_controller(app, "http://x", SimpleNamespace(no_agent=True, gestures=True), None)

        self.assertIsNone(off._gesture_factory)
        self.assertIsNotNone(on._gesture_factory)


if __name__ == "__main__":
    unittest.main()
