from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pc_control
import tempfile
from pathlib import Path

import win_desktop
from pc_control import (
    PCControlError,
    close_app,
    command_executable,
    find_window,
    new_window_command,
    open_url,
    play_video,
    resolve_site,
    save_shortcut_entry,
    window_action,
    best_match,
    browser_tab_action,
    close_app_processes,
    describe_spotify,
    describe_youtube,
    find_youtube_video,
    is_blocked_app,
    launch_app,
    live_subject,
    media_control,
    normalize_url,
    open_streaming,
    parse_spotify_result,
    parse_twitch_channel,
    parse_youtube_results,
    pick_spotify_item,
    play_spotify,
    play_youtube,
    spotify_now_playing,
    streaming_url,
    twitch_login,
    twitch_summary,
    wants_live,
)
from prompts import AGENT_INSTRUCTION

from test_tools import FakeResponse, FakeRunContext

_GUARDS: list[Any] = []


def setUpModule() -> None:
    """Safety net: no test here may focus, move, open or close anything on the real desktop."""
    import pyautogui  # noqa: F401  — garante que o patch abaixo encontre o módulo

    targets = [
        "win_desktop.bring_to_front",
        "win_desktop.move_to_monitor",
        "win_desktop.restore_placement",
        "win_desktop.show_window",
        "win_desktop.close_window",
        "pc_control.os.startfile",
        "pc_control.subprocess.Popen",
        "pc_control.subprocess.run",
        "pc_control.webbrowser.open",
        "pyautogui.hotkey",
        "pyautogui.press",
    ]
    for target in targets:

        def forbid(*_args: Any, _target: str = target, **_kwargs: Any) -> None:
            raise AssertionError(f"o teste chamou {_target} de verdade")

        guard = patch(target, side_effect=forbid, create=True)
        guard.start()
        _GUARDS.append(guard)


def tearDownModule() -> None:
    while _GUARDS:
        _GUARDS.pop().stop()


# Layout do usuário: tela 1 = notebook abaixo, tela 2 = principal, tela 3 = vertical à esquerda.
SCREEN1 = win_desktop.Monitor(1, 0, 1440, 1920, 2640, (0, 1440, 1920, 2592), False)
SCREEN2 = win_desktop.Monitor(2, 0, 0, 2560, 1440, (0, 0, 2560, 1392), True)
SCREEN3 = win_desktop.Monitor(3, -1440, -560, 0, 2000, (-1440, -560, 0, 1952), False)
SCREENS = [SCREEN1, SCREEN2, SCREEN3]
EDGE = Path("C:/Edge/msedge.exe")


def win(hwnd: int, title: str, process: str) -> win_desktop.Window:
    return win_desktop.Window(hwnd=hwnd, title=title, process=process, pid=hwnd)


class Sequence:
    """Returns the next value on each call, then keeps repeating the last one."""

    def __init__(self, *values: Any) -> None:
        self.values = list(values)

    def __call__(self, *_args: Any) -> Any:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]


class DesktopCase(unittest.TestCase):
    """Fake desktop: windows, monitors and processes are scripted; polling doesn't sleep."""

    def setUp(self) -> None:
        self.desktop = Sequence([])  # o que win_desktop.windows() devolve a cada chamada
        self.titles: dict[int, Sequence] = {}
        self.screen_of: dict[int, win_desktop.Monitor] = {}
        self.maximized: set[int] = set()
        self.running = Sequence(set())
        self.mock: dict[str, Any] = {}
        patches = {
            "windows_os": patch.object(pc_control, "IS_WINDOWS", True),
            "memory": patch.object(pc_control, "MEMORY", pc_control.WindowMemory()),
            "sleep": patch("pc_control.time.sleep"),
            "windows": patch("pc_control.win_desktop.windows", side_effect=lambda: list(self.desktop())),
            "monitors": patch("pc_control.win_desktop.monitors", return_value=SCREENS),
            "title": patch("pc_control.win_desktop.window_title", side_effect=lambda hwnd: self.titles[hwnd]()),
            "where": patch("pc_control.win_desktop.window_monitor", side_effect=self.screen_of.get),
            "placement": patch("pc_control.win_desktop.get_placement", side_effect=self.fake_placement),
            "move": patch("pc_control.win_desktop.move_to_monitor", side_effect=self.fake_move),
            "restore": patch("pc_control.win_desktop.restore_placement", side_effect=self.fake_restore),
            "front": patch("pc_control.win_desktop.bring_to_front", return_value=True),
            "show": patch("pc_control.win_desktop.show_window"),
            "startfile": patch("pc_control.os.startfile", create=True),
            "popen": patch("pc_control.subprocess.Popen"),
            "browser": patch("pc_control.webbrowser.open"),
            "default_browser": patch("pc_control.default_browser", return_value=EDGE),
            "running": patch("pc_control._running_processes", side_effect=lambda: set(self.running())),
            "ancestors": patch("pc_control._jarvis_ancestor_names", return_value=set()),
        }
        for key, patcher in patches.items():
            self.mock[key] = patcher.start()
            self.addCleanup(patcher.stop)

    def fake_placement(self, hwnd: int) -> win_desktop.Placement | None:
        screen = self.screen_of.get(hwnd)
        if screen is None:
            return None
        left, top, right, bottom = screen.work
        normal = (left + 100, top + 100, right - 100, bottom - 100)
        show_cmd = win_desktop.SW_MAXIMIZE if hwnd in self.maximized else win_desktop.SW_SHOWNORMAL
        return win_desktop.Placement(0, show_cmd, (-1, -1), (-1, -1), normal)

    def fake_move(self, hwnd: int, screen: win_desktop.Monitor, maximize: bool | None = None) -> None:
        self.screen_of[hwnd] = screen

    def fake_restore(self, hwnd: int, placement: win_desktop.Placement) -> None:
        self.screen_of[hwnd] = win_desktop.monitor_for_rect(placement.normal, SCREENS)
        self.maximized.discard(hwnd)
        if placement.maximized:
            self.maximized.add(hwnd)

    def moved_hwnds(self) -> list[int]:
        return [call.args[0] for call in self.mock["move"].call_args_list]


class UrlTests(unittest.TestCase):
    def test_adds_https_to_bare_domains(self) -> None:
        self.assertEqual(normalize_url("tudogostoso.com.br/receita/1"), "https://tudogostoso.com.br/receita/1")

    def test_rejects_non_web_schemes(self) -> None:
        for target in ("file:///C:/Windows/System32", "javascript:alert(1)", "ms-settings:", "cmd.exe /c del"):
            with self.subTest(target=target), self.assertRaises(PCControlError):
                normalize_url(target)


class AppMatchingTests(unittest.TestCase):
    def test_uninstallers_and_installers_are_blocked(self) -> None:
        for name in ("Uninstall Steam", "Desinstalar o Zoom", "Setup Wizard", "Reparar Office"):
            with self.subTest(name=name):
                self.assertTrue(is_blocked_app(name))
        self.assertFalse(is_blocked_app("Spotify"))

    def test_best_match_prefers_exact_then_prefix_then_fuzzy(self) -> None:
        names = ["Visual Studio Code", "Spotify", "Steam", "Calculadora"]
        self.assertEqual(best_match("spotify", names), "Spotify")
        self.assertEqual(best_match("visual", names), "Visual Studio Code")
        self.assertEqual(best_match("spotfy", names), "Spotify")
        self.assertIsNone(best_match("photoshop", names))

    @patch.object(pc_control, "IS_WINDOWS", True)
    def test_launch_refuses_uninstallers(self) -> None:
        with self.assertRaises(PCControlError):
            launch_app("uninstall chrome")


class CloseAppTests(unittest.TestCase):
    @patch("pc_control.hud_browser_processes", return_value=set())
    @patch("pc_control.find_processes", return_value=["explorer.exe"])
    def test_system_processes_are_protected(self, _find, _hud) -> None:
        with self.assertRaises(PCControlError) as ctx:
            close_app_processes("explorer")
        self.assertIn("sistema", str(ctx.exception))

    @patch("pc_control._jarvis_ancestor_names", return_value={"windowsterminal.exe", "python.exe"})
    @patch("pc_control.hud_browser_processes", return_value=set())
    @patch("pc_control.find_processes", return_value=["windowsterminal.exe"])
    def test_processes_hosting_jarvis_are_protected(self, _find, _hud, _ancestors) -> None:
        with self.assertRaises(PCControlError):
            close_app_processes("terminal")

    @patch("pc_control._jarvis_ancestor_names", return_value=set())
    @patch("pc_control.hud_browser_processes", return_value={"chrome.exe"})
    @patch("pc_control.find_processes", return_value=["chrome.exe"])
    def test_browser_with_hud_is_not_closed(self, _find, _hud, _ancestors) -> None:
        with self.assertRaises(PCControlError) as ctx:
            close_app_processes("chrome")
        self.assertIn("HUD", str(ctx.exception))


class BrowserTabTests(unittest.TestCase):
    @patch.object(pc_control, "IS_WINDOWS", True)
    @patch("pc_control._active_title", return_value="J.A.R.V.I.S. - Google Chrome")
    @patch("pc_control.win_desktop.bring_to_front", return_value=True)
    @patch("pc_control._browser_windows", return_value=[win_desktop.Window(hwnd=1, title="x", process="msedge.exe", pid=1)])
    def test_never_closes_the_hud_tab(self, _windows, _focus, _title) -> None:
        with patch("pyautogui.hotkey") as hotkey, self.assertRaises(PCControlError):
            browser_tab_action("close")
        hotkey.assert_not_called()


class MediaLookupTests(unittest.TestCase):
    @patch("pc_control.requests.get")
    def test_youtube_returns_first_video_with_metadata(self, mock_get) -> None:
        page = FakeResponse({})
        page.text = 'xx "videoId":"dQw4w9WgXcQ" yy "videoId":"aaaaaaaaaaa"'
        meta = FakeResponse({"title": "Vídeo", "author_name": "Canal"})
        meta.ok = True
        mock_get.side_effect = [page, meta]

        video = find_youtube_video("teste")

        self.assertEqual(video["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(video["title"], "Vídeo")
        self.assertIn("dQw4w9WgXcQ", video["thumbnail"])

    def test_streaming_search_and_aliases(self) -> None:
        self.assertEqual(
            streaming_url("netflix", "Homem de Ferro"),
            ("Netflix", "https://www.netflix.com/search?q=Homem+de+Ferro", True),
        )
        self.assertEqual(streaming_url("amazon prime", None)[0], "Prime Video")
        self.assertEqual(streaming_url("disney", "Loki"), ("Disney+", "https://www.disneyplus.com", False))
        with self.assertRaises(PCControlError):
            streaming_url("pirataflix", "x")


class SiteResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(pc_control, "SHORTCUTS_FILE", Path(folder.name) / "atalhos.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_known_services_and_misheard_claude(self) -> None:
        self.assertEqual(resolve_site("Google Maps"), ("Google Maps", "https://www.google.com/maps"))
        self.assertEqual(resolve_site("Cláudio")[1], "https://claude.ai")
        self.assertEqual(resolve_site("cloud")[1], "https://claude.ai")

    def test_urls_and_domains_pass_through(self) -> None:
        self.assertEqual(resolve_site("tudogostoso.com.br"), ("tudogostoso.com.br", "https://tudogostoso.com.br"))

    def test_unknown_names_ask_for_a_search_instead_of_guessing(self) -> None:
        with self.assertRaises(PCControlError) as ctx:
            resolve_site("portal satc")
        self.assertIn("search_web", str(ctx.exception))

    def test_saved_shortcuts_are_used_by_name(self) -> None:
        save_shortcut_entry("Portal SATC", "https://portal.exemplo.edu.br/login")
        self.assertEqual(resolve_site("portal satc"), ("Portal SATC", "https://portal.exemplo.edu.br/login"))

    def test_shortcuts_reject_non_web_urls(self) -> None:
        with self.assertRaises(PCControlError):
            save_shortcut_entry("perigo", "file:///C:/Windows")


WINDOWS = [
    win_desktop.Window(hwnd=1, title="J.A.R.V.I.S. e mais 2 páginas - Pessoal - Microsoft\u200b Edge", process="msedge.exe", pid=10),
    win_desktop.Window(hwnd=2, title="Configurações", process="applicationframehost.exe", pid=11),
    win_desktop.Window(hwnd=3, title="Jarvis-AI – tools.py", process="phpstorm64.exe", pid=12),
    win_desktop.Window(hwnd=4, title="Prompt de Comando", process="windowsterminal.exe", pid=13),
]


@patch("pc_control.win_desktop.windows", return_value=WINDOWS)
class WindowTests(unittest.TestCase):
    def test_finds_windows_by_title_and_never_the_hud(self, _windows) -> None:
        self.assertEqual(find_window("configurações").hwnd, 2)
        self.assertEqual(find_window("tools.py").hwnd, 3)
        with self.assertRaises(PCControlError):
            find_window("J.A.R.V.I.S.")

    @patch.object(pc_control, "IS_WINDOWS", True)
    @patch("pc_control._jarvis_ancestor_names", return_value={"windowsterminal.exe"})
    @patch("pc_control.win_desktop.close_window")
    def test_close_window_protects_jarvis_host(self, mock_close, _ancestors, _windows) -> None:
        with self.assertRaises(PCControlError):
            window_action("prompt de comando", "close", None)
        mock_close.assert_not_called()

        window_action("configurações", "close", None)
        mock_close.assert_called_once_with(2)


class EdgeTabTests(unittest.TestCase):
    async def _close_without_name(self) -> str:
        return await pc_control.browser_tab(SimpleNamespace(), action="close")

    def test_close_without_site_never_touches_the_browser(self) -> None:
        # "Feche a aba" sem site costuma ser um painel do HUD, não a aba ativa do Edge.
        import asyncio

        with patch("pc_control.browser_tab_action") as action:
            result = asyncio.run(self._close_without_name())

        action.assert_not_called()
        self.assertTrue(result.startswith("NADA foi fechado"))
        self.assertIn("manage_hud_panels", result)

    @patch.object(pc_control, "IS_WINDOWS", True)
    @patch("pc_control.win_desktop.bring_to_front", return_value=True)
    @patch("pc_control.win_desktop.windows")
    def test_edge_windows_are_found_by_process(self, mock_windows, _front) -> None:
        mock_windows.return_value = [
            win_desktop.Window(hwnd=9, title="Google Maps e mais 3 páginas - Pessoal — Microsoft\u200b Edge", process="msedge.exe", pid=1),
        ]
        titles = iter(["Google Maps e mais 3 páginas - Pessoal — Microsoft Edge"])
        with patch("pc_control._active_title", side_effect=lambda: next(titles)), patch("pyautogui.hotkey") as hotkey:
            result = browser_tab_action("close", "google maps")

        hotkey.assert_called_once_with("ctrl", "w")
        self.assertIn("Fechei", result)


HUD_WINDOW = win(1, "J.A.R.V.I.S. e mais 2 páginas - Pessoal - Microsoft\u200b Edge", "msedge.exe")
CLAUDE = win(30, "Claude", "claude.exe")
DISCORD = win(7, "\U0001f509–Bate papo | amongols - Discord", "discord.exe")
START_APPS = [
    {"name": "Discord", "app_id": "com.squirrel.Discord.Discord"},
    {"name": "Visual Studio Code", "app_id": "Microsoft.VisualStudioCode"},
    {"name": "WhatsApp", "app_id": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
    {"name": "Claude", "app_id": "Claude_pzs8sxrjxfjjc!Claude"},
]


class DesktopHelperTests(unittest.TestCase):
    def test_monitor_for_rect_uses_the_center_then_the_overlap(self) -> None:
        self.assertEqual(win_desktop.monitor_for_rect((-1300, 0, -100, 900), SCREENS).number, 3)
        self.assertEqual(win_desktop.monitor_for_rect((-8, -8, 2568, 1400), SCREENS).number, 2)  # maximizada
        self.assertEqual(win_desktop.monitor_for_rect((1500, 1500, 2700, 1700), SCREENS).number, 1)
        self.assertIsNone(win_desktop.monitor_for_rect((-32000, -32000, -31840, -31972), SCREENS))  # minimizada

    def test_placement_knows_when_to_come_back_maximized(self) -> None:
        rect = (0, 0, 10, 10)
        self.assertTrue(win_desktop.Placement(0, win_desktop.SW_MAXIMIZE, (0, 0), (0, 0), rect).maximized)
        minimized = win_desktop.Placement(
            win_desktop.WPF_RESTORETOMAXIMIZED, win_desktop.SW_SHOWMINIMIZED, (0, 0), (0, 0), rect
        )
        self.assertTrue(minimized.maximized)
        self.assertFalse(win_desktop.Placement(0, win_desktop.SW_SHOWNORMAL, (0, 0), (0, 0), rect).maximized)

    def test_browser_command_line_is_fixed_and_only_takes_web_urls(self) -> None:
        edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
        self.assertEqual(command_executable(f'"{edge}" --single-argument %1'), edge)
        self.assertEqual(command_executable("C:\\Firefox\\firefox.exe -osint -url %1"), "C:\\Firefox\\firefox.exe")
        self.assertEqual(new_window_command(EDGE, "youtube.com"), [str(EDGE), "--new-window", "https://youtube.com"])
        self.assertEqual(new_window_command(Path("C:/ff/firefox.exe"), "https://x.com")[1], "-new-window")
        for bad in ("--remote-debugging-port=9222", "file:///C:/Windows", "javascript:alert(1)"):
            with self.subTest(bad=bad), self.assertRaises(PCControlError):
                new_window_command(EDGE, bad)


class OpenOnMonitorTests(DesktopCase):
    def test_site_opens_in_its_own_window_and_moves_without_the_hud(self) -> None:
        self.desktop = Sequence([HUD_WINDOW], [HUD_WINDOW], [win(50, "Nova guia", "msedge.exe"), HUD_WINDOW])
        self.titles[50] = Sequence(
            "Nova guia - Pessoal - Microsoft\u200b Edge", "(378) YouTube - Pessoal - Microsoft\u200b Edge"
        )
        self.screen_of.update({1: SCREEN2, 50: SCREEN2})

        result = open_url("YouTube", "https://www.youtube.com", 1)

        self.assertEqual(self.mock["popen"].call_args.args[0], [str(EDGE), "--new-window", "https://www.youtube.com"])
        self.mock["browser"].assert_not_called()
        self.assertEqual(self.moved_hwnds(), [50])
        self.assertIs(self.mock["move"].call_args.args[1], SCREEN1)
        self.assertIn("janela nova", result)
        self.assertIn("'(378) YouTube - Pessoal - Microsoft Edge' agora está na tela 1", result)
        self.assertNotIn("HUD", result)

        # Logo depois o título pode ainda ser "Nova guia": a janela é achada pelo nome pedido.
        self.desktop = Sequence([win(50, "Nova guia - Pessoal - Microsoft Edge", "msedge.exe"), HUD_WINDOW])
        self.assertEqual(find_window("YouTube").hwnd, 50)

    def test_window_that_never_shows_up_is_not_moved(self) -> None:
        self.desktop = Sequence([HUD_WINDOW])
        result = open_url("YouTube", "https://www.youtube.com", 1)
        self.assertIn("não apareceu", result)
        self.mock["move"].assert_not_called()

    def test_without_a_known_browser_it_opens_a_tab_and_leaves_the_hud_alone(self) -> None:
        self.mock["default_browser"].return_value = None
        result = open_url("YouTube", "https://www.youtube.com", 1)
        self.mock["browser"].assert_called_once_with("https://www.youtube.com", 2)
        self.mock["move"].assert_not_called()
        self.assertIn("não movi", result)

    def test_unknown_monitor_fails_before_opening_anything(self) -> None:
        with self.assertRaises(PCControlError):
            open_url("YouTube", "https://www.youtube.com", 7)
        self.mock["popen"].assert_not_called()
        self.mock["browser"].assert_not_called()

    def test_without_monitor_it_is_still_a_plain_new_tab(self) -> None:
        self.assertEqual(open_url("YouTube", "https://www.youtube.com", None), "Abri YouTube no navegador.")
        self.mock["browser"].assert_called_once_with("https://www.youtube.com", 2)
        self.mock["popen"].assert_not_called()

    @patch("pc_control.find_youtube_video")
    def test_youtube_video_plays_on_the_requested_monitor(self, mock_find) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        mock_find.return_value = {"url": url, "title": "Lo-fi", "channel": "Canal", "thumbnail": ""}
        self.desktop = Sequence([], [win(60, "Lo-fi - YouTube", "msedge.exe")])
        self.titles[60] = Sequence("Lo-fi - YouTube - Pessoal - Microsoft Edge")
        self.screen_of[60] = SCREEN2

        video, result = play_video("lo-fi", 3)

        self.assertEqual(self.mock["popen"].call_args.args[0][-1], url)
        self.assertEqual(video["title"], "Lo-fi")
        self.assertIn("tela 3", result)
        self.mock["browser"].assert_not_called()


class FindWindowTests(DesktopCase):
    def test_waits_for_a_window_that_is_still_opening(self) -> None:
        self.desktop = Sequence([], [], [DISCORD])
        self.assertEqual(find_window("discord", wait=2).hwnd, 7)

    def test_without_wait_a_missing_window_is_an_error(self) -> None:
        with self.assertRaises(PCControlError):
            find_window("discord")

    def test_titles_with_notification_counters_still_match(self) -> None:
        self.desktop = Sequence([HUD_WINDOW, win(8, "(378) YouTube - Pessoal - Microsoft\u200b Edge", "msedge.exe")])
        self.assertEqual(find_window("YouTube").hwnd, 8)


class BackTests(DesktopCase):
    def setUp(self) -> None:
        super().setUp()
        self.desktop = Sequence([HUD_WINDOW, CLAUDE])
        self.screen_of[30] = SCREEN1

    def test_back_returns_to_where_the_window_was_not_to_the_primary(self) -> None:
        self.assertIn("agora está na tela 3", window_action("claude", "move", 3))

        result = window_action("claude", "back", None)

        self.assertIn("voltou para onde estava: tela 1", result)
        self.assertNotIn("tela 2", result)
        self.assertIs(self.screen_of[30], SCREEN1)
        with self.assertRaises(PCControlError) as ctx:
            window_action("claude", "back", None)
        self.assertIn("Não tenho registro", str(ctx.exception))
        self.mock["restore"].assert_called_once()

    def test_back_undoes_moves_in_order_and_restores_maximized(self) -> None:
        self.maximized.add(30)
        window_action("claude", "move", 3)
        self.maximized.discard(30)
        self.assertIn("tela 2 e maximizada", window_action("claude", "maximize", 2))

        self.assertIn("tela 3.", window_action("claude", "back", None))
        self.assertIn("tela 1, maximizada", window_action("claude", "back", None))

    def test_move_needs_a_monitor_instead_of_guessing_the_primary(self) -> None:
        with self.assertRaises(PCControlError) as ctx:
            window_action("claude", "move", None)
        self.assertIn("back", str(ctx.exception))
        self.mock["move"].assert_not_called()

    def test_reports_the_monitor_the_window_really_landed_on(self) -> None:
        self.mock["move"].side_effect = None  # o Windows ignorou o pedido
        result = window_action("claude", "move", 3)
        self.assertIn("ficou na tela 1", result)
        self.assertNotIn("agora está", result)

    def test_back_says_so_when_the_window_did_not_return(self) -> None:
        window_action("claude", "move", 3)
        self.mock["restore"].side_effect = None
        result = window_action("claude", "back", None)
        self.assertIn("Tentei devolver 'Claude' para a tela 1, mas ela ficou na tela 3", result)

    def test_back_without_history_does_not_pretend(self) -> None:
        with self.assertRaises(PCControlError) as ctx:
            window_action("claude", "back", None)
        self.assertIn("Não tenho registro", str(ctx.exception))
        self.mock["restore"].assert_not_called()

    def test_moving_the_browser_window_that_holds_the_hud_says_so(self) -> None:
        youtube_tab = win(1, "YouTube e mais 2 páginas - Pessoal - Microsoft\u200b Edge", "msedge.exe")
        self.desktop = Sequence([HUD_WINDOW], [youtube_tab])
        self.screen_of[1] = SCREEN2
        self.assertIn("HUD", window_action("youtube", "move", 1))


class LaunchAppTests(DesktopCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("pc_control.list_start_apps", return_value=START_APPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_waits_for_the_window_and_brings_it_to_front(self) -> None:
        self.desktop = Sequence([], [], [DISCORD])
        self.screen_of[7] = SCREEN2

        result = launch_app("discord")

        self.mock["startfile"].assert_called_once_with("shell:AppsFolder\\com.squirrel.Discord.Discord")
        self.mock["front"].assert_called_once_with(7)
        self.assertTrue(result.startswith("Abri Discord"))
        self.assertIn("primeiro plano na tela 2", result)

    def test_start_menu_names_and_aliases(self) -> None:
        self.desktop = Sequence([], [win(3, "Bem-vindo - Visual Studio Code", "code.exe")])
        self.assertTrue(launch_app("vs code").startswith("Abri Visual Studio Code"))
        self.mock["startfile"].assert_called_once_with("shell:AppsFolder\\Microsoft.VisualStudioCode")

    def test_app_hidden_in_the_tray_is_asked_twice_then_reported_honestly(self) -> None:
        self.running = Sequence({"discord.exe"})

        result = launch_app("discord")

        self.assertEqual(self.mock["startfile"].call_count, 2)
        self.mock["front"].assert_not_called()
        self.assertNotIn("Abri", result)
        self.assertIn("bandeja", result)

    def test_app_that_never_shows_a_window_is_not_reported_as_opened(self) -> None:
        result = launch_app("whatsapp")
        self.assertEqual(self.mock["startfile"].call_count, 1)  # não estava rodando: nada de segundo pedido
        self.assertIn("Não posso confirmar que abriu", result)

    def test_already_open_window_is_brought_to_front(self) -> None:
        self.desktop = Sequence([DISCORD])
        self.running = Sequence({"discord.exe"})
        result = launch_app("discord")
        self.assertIn("Discord já estava aberto", result)
        self.mock["front"].assert_called_once_with(7)

    def test_app_window_beats_a_browser_tab_with_the_same_name(self) -> None:
        self.desktop = Sequence([win(5, "Claude - Pessoal - Microsoft\u200b Edge", "msedge.exe"), CLAUDE])
        launch_app("claude")
        self.mock["front"].assert_called_once_with(30)

    def test_opens_on_the_requested_monitor(self) -> None:
        self.desktop = Sequence([], [DISCORD])
        self.screen_of[7] = SCREEN2
        result = launch_app("discord", 3)
        self.assertEqual(self.moved_hwnds(), [7])
        self.assertIn("agora está na tela 3", result)

    def test_builtin_apps_are_found_by_title(self) -> None:
        self.desktop = Sequence([], [win(11, "Calculadora", "applicationframehost.exe")])
        result = launch_app("calculadora")
        self.mock["startfile"].assert_called_once_with("calc")
        self.assertTrue(result.startswith("Abri Calculadora"))

    def test_site_fallback_on_a_monitor_gets_its_own_window(self) -> None:
        self.desktop = Sequence([HUD_WINDOW], [win(70, "Gmail", "msedge.exe"), HUD_WINDOW])
        self.titles[70] = Sequence("Entrada - Gmail")
        self.screen_of[70] = SCREEN2
        result = launch_app("gmail", 1)
        self.mock["startfile"].assert_not_called()
        self.assertEqual(self.moved_hwnds(), [70])
        self.assertIn("tela 1", result)


class CloseConfirmationTests(DesktopCase):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch("pc_control.subprocess.run", return_value=SimpleNamespace(returncode=0))
        self.taskkill = patcher.start()
        self.addCleanup(patcher.stop)

    def test_closes_gracefully_and_confirms_the_process_exited(self) -> None:
        self.running = Sequence({"spotify.exe"}, {"spotify.exe"}, set())

        result = close_app_processes("spotify")

        command = self.taskkill.call_args.args[0]
        self.assertEqual(command, ["taskkill", "/IM", "spotify.exe"])
        self.assertNotIn("/F", command)
        self.assertTrue(result.startswith("Fechei spotify"))

    def test_app_that_goes_to_the_tray_is_reported_as_still_running(self) -> None:
        self.running = Sequence({"whatsapp.root.exe"})
        result = close_app_processes("WhatsApp")
        self.assertNotIn("Fechei", result)
        self.assertIn("continua rodando em segundo plano", result)

    def test_window_that_refuses_to_close_is_reported(self) -> None:
        self.running = Sequence({"whatsapp.root.exe"})
        self.desktop = Sequence([win(4, "WhatsApp", "whatsapp.root.exe")])
        self.assertIn("a janela continua aberta", close_app_processes("WhatsApp"))

    def test_tool_relays_the_honest_result(self) -> None:
        import asyncio

        self.running = Sequence({"whatsapp.root.exe"})
        result = asyncio.run(close_app(FakeRunContext(), name="WhatsApp"))
        self.assertIn("continua rodando", result)
        self.assertNotIn("Pedi para fechar WhatsApp (", result)


# ───────────────────────── mídia: YouTube, lives, Twitch, Spotify ─────────────────────────


def yt_video(video_id: str, title: str, channel: str, *, live: bool = False, upcoming: bool = False) -> dict:
    """A videoRenderer as YouTube puts it in ytInitialData."""
    renderer: dict = {
        "videoId": video_id,
        "title": {"runs": [{"text": title}]},
        "ownerText": {"runs": [{"text": channel}]},
    }
    if live:
        renderer["badges"] = [
            {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_LIVE_NOW", "label": "AO VIVO"}},
            {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_SIMPLE", "label": "Novo"}},
        ]
        renderer["viewCountText"] = {"runs": [{"text": "8.190"}, {"text": " assistindo"}]}
    elif upcoming:
        renderer["upcomingEventData"] = {"startTime": "1792249403"}
        renderer["thumbnailOverlays"] = [{"thumbnailOverlayTimeStatusRenderer": {"style": "UPCOMING"}}]
    else:
        renderer["lengthText"] = {"simpleText": "43:13"}
        renderer["viewCountText"] = {"simpleText": "1.238 visualizações"}
        renderer["thumbnailOverlays"] = [{"thumbnailOverlayTimeStatusRenderer": {"style": "DEFAULT"}}]
    return renderer


def yt_page(*videos: dict) -> str:
    """A YouTube search page reduced to what matters: the ytInitialData script."""
    section = {"itemSectionRenderer": {"contents": [{"videoRenderer": video} for video in videos]}}
    data = {
        "contents": {
            "twoColumnSearchResultsRenderer": {"primaryContents": {"sectionListRenderer": {"contents": [section]}}}
        }
    }
    return f'<html><body><script nonce="abc">var ytInitialData = {json.dumps(data)};</script></body></html>'


def html_response(text: str) -> FakeResponse:
    response = FakeResponse({})
    response.text = text
    response.ok = True
    return response


GAULES_LIVE = yt_video("EkHTNkYzuS0", "FALCONS vs BB | SEMIFINAIS", "Gaules", live=True)
GAULES_VOD = yt_video("g2k4phap5n4", "FURIA EM BUSCA DE MAIS UMA FINAL!", "Gaules")
OTHER_LIVE = yt_video("_rusmWlbKGw", "Divine Liturgie", "Centre Béthanie", live=True)

TWITCH_PROFILE = {
    "@type": "ProfilePage",
    "name": "Gaules - Twitch",
    "mainEntity": {"@type": "Person", "name": "Gaules", "alternateName": "gaules"},
}


def twitch_page(*nodes: dict) -> str:
    graph = json.dumps({"@context": "http://schema.org", "@graph": list(nodes)})
    return f'<html><head><script type="application/ld+json">{graph}</script></head></html>'


def twitch_stream(title: str) -> dict:
    return {
        "@type": "VideoObject",
        "name": "Gaules - Twitch",
        "description": title,
        "publication": {"@type": "BroadcastEvent", "isLiveBroadcast": True},
    }


def spotify_item(kind: str, name: str, artist: str = "", item_id: str = "3OUWMcgPTQIElaufktjDLK") -> dict:
    return {
        "kind": kind,
        "id": item_id,
        "name": name,
        "artist": artist,
        "uri": f"spotify:{kind}:{item_id}",
        "url": f"https://open.spotify.com/{kind}/{item_id}",
    }


class LastMediaIsolation(unittest.TestCase):
    """Each test starts with no remembered media."""

    def setUp(self) -> None:
        patcher = patch.object(pc_control, "_LAST_MEDIA", None)
        patcher.start()
        self.addCleanup(patcher.stop)


class YouTubeLiveTests(LastMediaIsolation):
    def test_parser_reads_live_badge_title_and_channel(self) -> None:
        results = parse_youtube_results(yt_page(GAULES_LIVE, GAULES_VOD))

        self.assertEqual([r["status"] for r in results], ["live", "video"])
        self.assertEqual(results[0]["title"], "FALCONS vs BB | SEMIFINAIS")
        self.assertEqual(results[0]["channel"], "Gaules")
        self.assertEqual(results[0]["viewers"], "8.190 assistindo")
        upcoming = yt_video("aaaaaaaaaaa", "Estreia", "Canal", upcoming=True)
        self.assertEqual(parse_youtube_results(yt_page(upcoming))[0]["status"], "upcoming")

    @patch("pc_control.requests.get")
    def test_live_request_uses_live_filter_and_the_requested_channel(self, mock_get) -> None:
        mock_get.return_value = html_response(yt_page(OTHER_LIVE, GAULES_LIVE))

        video = find_youtube_video("a live do Gaules", live=True)

        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["sp"], "EgJAAQ==")
        self.assertEqual(params["search_query"], "gaules")
        self.assertEqual(video["url"], "https://www.youtube.com/watch?v=EkHTNkYzuS0")
        self.assertEqual((video["channel"], video["status"]), ("Gaules", "live"))
        mock_get.assert_called_once()  # título e canal vieram da busca, sem oEmbed

    @patch("pc_control.requests.get")
    def test_live_request_never_returns_a_recorded_video_or_another_channel(self, mock_get) -> None:
        mock_get.return_value = html_response(yt_page(GAULES_VOD, OTHER_LIVE))

        self.assertIsNone(find_youtube_video("Gaules", live=True))

    @patch("pc_control.requests.get")
    def test_regular_search_says_when_the_first_result_is_live(self, mock_get) -> None:
        mock_get.return_value = html_response(yt_page(GAULES_LIVE, GAULES_VOD))

        video = find_youtube_video("gaules")

        self.assertNotIn("sp", mock_get.call_args.kwargs["params"])
        self.assertEqual(video["status"], "live")
        self.assertIn("ao vivo agora", describe_youtube(video))

    @patch("pc_control.requests.get")
    def test_regular_video_is_not_called_live(self, mock_get) -> None:
        mock_get.return_value = html_response(yt_page(GAULES_VOD))

        video = find_youtube_video("gaules furia")

        self.assertEqual(video["status"], "video")
        message = describe_youtube(video)
        self.assertIn("não é ao vivo", message)
        self.assertNotIn("ao vivo agora", message)

    def test_close_hint_quotes_titles_with_apostrophes(self) -> None:
        video = {"title": "Guns N' Roses - Patience", "channel": "Guns N' Roses", "status": "video", "viewers": ""}

        self.assertIn('name="Guns N\' Roses - Patience"', describe_youtube(video))

    def test_live_requests_are_detected_without_catching_song_titles(self) -> None:
        self.assertTrue(wants_live("live do Gaules"))
        self.assertTrue(wants_live("Gaules ao vivo"))
        self.assertTrue(wants_live("a live da Alanzoka"))
        self.assertFalse(wants_live("Live and Let Die"))
        self.assertFalse(wants_live("lo-fi para estudar"))
        self.assertEqual(live_subject("a live do Gaules no YouTube"), "gaules")


class PlayYouTubeToolTests(LastMediaIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_opens_the_live_and_reports_real_title_and_channel(self) -> None:
        video = {
            "url": "https://www.youtube.com/watch?v=EkHTNkYzuS0",
            "title": "FALCONS vs BB | SEMIFINAIS",
            "channel": "Gaules",
            "thumbnail": "",
            "status": "live",
            "viewers": "8.190 assistindo",
        }
        with patch("pc_control.find_youtube_video", return_value=video) as find, patch(
            "pc_control.webbrowser.open"
        ) as browser:
            result = await play_youtube(FakeRunContext(), query="live do Gaules")

        find.assert_called_once_with("live do Gaules", True)  # "live do" liga o modo live sozinho
        browser.assert_called_once_with(video["url"], 2)
        self.assertIn("FALCONS vs BB | SEMIFINAIS", result)
        self.assertIn("canal Gaules", result)
        self.assertIn("ao vivo agora", result)
        self.assertNotIn("está tocando", result)
        self.assertEqual(pc_control._LAST_MEDIA["title"], "FALCONS vs BB | SEMIFINAIS")

    async def test_without_a_live_nothing_opens_and_twitch_is_offered(self) -> None:
        channel = {
            "login": "gaules",
            "name": "Gaules",
            "live": True,
            "rerun": False,
            "title": "SEMIFINAL AO VIVO",
            "url": "https://www.twitch.tv/gaules",
        }
        with patch("pc_control.find_youtube_video", return_value=None), patch(
            "pc_control.lookup_twitch_channel", return_value=channel
        ), patch("pc_control.webbrowser.open") as browser:
            result = await play_youtube(FakeRunContext(), query="Gaules", live=True)

        browser.assert_not_called()
        self.assertIn("Não encontrei uma live", result)
        self.assertIn("ao vivo na Twitch", result)
        self.assertIn("open_streaming('Twitch', 'gaules')", result)
        self.assertIn("Não diga que está tocando", result)

    async def test_twitch_rerun_is_not_offered_as_live(self) -> None:
        channel = {
            "login": "gaules",
            "name": "Gaules",
            "live": True,
            "rerun": True,
            "title": "RERUN: Jogos Variados!",
            "url": "https://www.twitch.tv/gaules",
        }
        with patch("pc_control.find_youtube_video", return_value=None), patch(
            "pc_control.lookup_twitch_channel", return_value=channel
        ), patch("pc_control.webbrowser.open"):
            result = await play_youtube(FakeRunContext(), query="Gaules", live=True)

        self.assertIn("reprise", result)
        self.assertNotIn("Ofereça abrir", result)


class TwitchTests(LastMediaIsolation, unittest.IsolatedAsyncioTestCase):
    def test_channel_page_live_rerun_offline_and_missing(self) -> None:
        live = parse_twitch_channel(twitch_page(twitch_stream("SEMIFINAL AO VIVO"), TWITCH_PROFILE), "gaules")
        self.assertEqual((live["name"], live["live"], live["rerun"]), ("Gaules", True, False))
        self.assertEqual(live["title"], "SEMIFINAL AO VIVO")

        rerun = parse_twitch_channel(twitch_page(twitch_stream("RERUN: Jogos Variados!"), TWITCH_PROFILE), "gaules")
        self.assertTrue(rerun["rerun"])

        offline = parse_twitch_channel(twitch_page({"@type": "ItemList", "itemListElement": []}, TWITCH_PROFILE), "gaules")
        self.assertFalse(offline["live"])
        self.assertIn("offline", twitch_summary(offline))

        self.assertIsNone(parse_twitch_channel("<html>Página não encontrada</html>", "naoexiste"))

    def test_login_comes_from_the_spoken_name(self) -> None:
        self.assertEqual(twitch_login("a live do Gaules"), "gaules")
        self.assertEqual(twitch_login("jovem nerd"), "jovemnerd")
        self.assertIsNone(twitch_login("x"))

    async def test_open_streaming_twitch_opens_the_channel_and_says_if_it_is_live(self) -> None:
        page = html_response(twitch_page(twitch_stream("SEMIFINAL AO VIVO"), TWITCH_PROFILE))
        with patch("pc_control.requests.get", return_value=page), patch("pc_control.webbrowser.open") as browser:
            result = await open_streaming(FakeRunContext(), service="Twitch", query="Gaules")

        browser.assert_called_once_with("https://www.twitch.tv/gaules", 2)
        self.assertIn("ao vivo na Twitch agora", result)
        self.assertEqual(pc_control._LAST_MEDIA["title"], "Gaules")


class SpotifyLookupTests(unittest.TestCase):
    def test_reads_kind_name_and_artist_from_search_results(self) -> None:
        track = parse_spotify_result(
            "https://open.spotify.com/track/7snQQk1zcKl8gZ92AnueZW",
            "Sweet Child O' Mine - música e letra de Guns N' Roses | Spotify",
        )
        self.assertEqual((track["kind"], track["name"], track["artist"]), ("track", "Sweet Child O' Mine", "Guns N' Roses"))
        self.assertEqual(track["uri"], "spotify:track:7snQQk1zcKl8gZ92AnueZW")

        album = parse_spotify_result(
            "https://open.spotify.com/album/3OUWMcgPTQIElaufktjDLK", "Greatest Hits - Compilation by Guns N' Roses | Spotify"
        )
        self.assertEqual((album["kind"], album["name"], album["artist"]), ("album", "Greatest Hits", "Guns N' Roses"))

        artist = parse_spotify_result("https://open.spotify.com/intl-es/artist/3qm84nBOXUEQ2vnTfUTTFC", "Guns N' Roses - Spotify")
        self.assertEqual((artist["kind"], artist["name"]), ("artist", "Guns N' Roses"))
        self.assertIsNone(parse_spotify_result("https://www.youtube.com/watch?v=x", "Guns N' Roses"))

    def test_prefers_tracks_and_albums_and_ignores_unrelated_results(self) -> None:
        items = [
            spotify_item("artist", "Guns N' Roses", item_id="3qm84nBOXUEQ2vnTfUTTFC"),
            spotify_item("playlist", "This Is Guns N' Roses", item_id="37i9dQZF1DZ06evO1Ziym4"),
            spotify_item("track", "Down Under", "Overdriver Duo", item_id="0taadKzaHhkPsR2TqrvD6L"),
            spotify_item("album", "Greatest Hits", "Guns N' Roses"),
        ]
        self.assertEqual(pick_spotify_item("Guns N' Roses", items)["kind"], "album")
        self.assertEqual(pick_spotify_item("Guns N' Roses", items[:2])["kind"], "playlist")
        self.assertIsNone(pick_spotify_item("Sweet Child O' Mine", items))

    @patch("pc_control.win_desktop.process_windows")
    def test_now_playing_comes_from_the_spotify_window_title(self, mock_windows) -> None:
        def window(title: str) -> win_desktop.Window:
            return win_desktop.Window(hwnd=5, title=title, process="spotify.exe", pid=7)

        mock_windows.return_value = [window("GDI+ Window (Spotify.exe)"), window("Spotify Premium")]
        self.assertEqual(spotify_now_playing(), "")
        mock_windows.return_value = [window("Default IME"), window("Guns N' Roses - Patience")]
        self.assertEqual(spotify_now_playing(), "Guns N' Roses - Patience")
        mock_windows.return_value = []
        self.assertIsNone(spotify_now_playing())


class FakeSpotifyApp:
    """Spotify desktop seen through its window title; WM_APPCOMMAND play/pause toggles it."""

    def __init__(self, title: str | None, after_play: str = "") -> None:
        self.title = title
        self.after_play = after_play
        self.commands = 0

    def now_playing(self) -> str | None:
        return self.title

    def app_command(self, hwnd: int, command: int) -> None:
        self.commands += 1
        self.title = self.after_play if self.title == "" else ""


@patch.object(pc_control, "IS_WINDOWS", True)
@patch("pc_control.time.sleep")
@patch("pc_control.webbrowser.open")
@patch("pc_control.os.startfile", create=True)
@patch("pc_control.spotify_app_installed", return_value=True)
class PlaySpotifyTests(unittest.TestCase):
    WINDOW = win_desktop.Window(hwnd=5, title="Spotify Premium", process="spotify.exe", pid=7)

    def run_with(self, app: FakeSpotifyApp, items: list[dict]) -> dict:
        with patch("pc_control.find_spotify_items", return_value=items), patch(
            "pc_control.spotify_now_playing", side_effect=app.now_playing
        ), patch("pc_control._spotify_window", return_value=self.WINDOW), patch(
            "pc_control.win_desktop.send_app_command", side_effect=app.app_command
        ):
            return play_spotify("Guns N' Roses")

    def test_confirms_playback_when_the_app_starts_the_album(self, _installed, startfile, browser, _sleep) -> None:
        app = FakeSpotifyApp("")
        startfile.side_effect = lambda uri: setattr(app, "title", "Guns N' Roses - Welcome To The Jungle")

        result = self.run_with(app, [spotify_item("album", "Greatest Hits", "Guns N' Roses")])

        startfile.assert_called_once_with("spotify:album:3OUWMcgPTQIElaufktjDLK")
        self.assertEqual(result["state"], "playing")
        self.assertEqual(app.commands, 0)
        self.assertIn(
            "Tocando agora no app do Spotify: 'Guns N' Roses - Welcome To The Jungle'",
            describe_spotify(result, "Guns N' Roses"),
        )
        browser.assert_not_called()

    def test_presses_play_on_the_spotify_window_when_it_opened_paused(self, _installed, _startfile, _browser, _sleep) -> None:
        app = FakeSpotifyApp("", after_play="Guns N' Roses - Welcome To The Jungle")

        result = self.run_with(app, [spotify_item("album", "Greatest Hits", "Guns N' Roses")])

        self.assertEqual(result["state"], "playing")
        self.assertEqual(app.commands, 1)

    def test_pauses_again_when_play_resumed_something_else(self, _installed, _startfile, _browser, _sleep) -> None:
        app = FakeSpotifyApp("", after_play="Metallica - One")

        result = self.run_with(app, [spotify_item("album", "Greatest Hits", "Guns N' Roses")])

        self.assertEqual(result["state"], "opened")
        self.assertEqual(app.commands, 2)  # play e, ao ver a música errada, pausa de volta
        self.assertEqual(app.title, "")
        message = describe_spotify(result, "Guns N' Roses")
        self.assertIn("não consegui confirmar", message)
        self.assertIn("Não diga que está tocando", message)

    def test_reports_what_keeps_playing_when_the_link_did_not_switch(self, _installed, _startfile, _browser, _sleep) -> None:
        app = FakeSpotifyApp("Metallica - One")

        result = self.run_with(app, [spotify_item("album", "Greatest Hits", "Guns N' Roses")])

        self.assertEqual(result["state"], "opened")
        self.assertEqual(app.commands, 0)  # tocando outra coisa: play/pause pausaria, então não mexe
        self.assertIn("continua tocando 'Metallica - One'", describe_spotify(result, "Guns N' Roses"))

    def test_without_a_link_only_the_search_opens(self, _installed, startfile, _browser, _sleep) -> None:
        result = self.run_with(FakeSpotifyApp(""), [])

        startfile.assert_called_once_with("spotify:search:Guns%20N%27%20Roses")
        self.assertEqual(result["state"], "search")
        self.assertIn("abri só a busca", describe_spotify(result, "Guns N' Roses"))

    def test_unreadable_app_is_reported_as_unverified(self, _installed, _startfile, _browser, _sleep) -> None:
        result = self.run_with(FakeSpotifyApp(None), [spotify_item("track", "Patience", "Guns N' Roses")])

        self.assertEqual(result["state"], "unverified")
        self.assertIn("Não afirme que está tocando", describe_spotify(result, "Guns N' Roses"))

    def test_falls_back_to_spotify_web_without_the_app(self, installed, startfile, browser, _sleep) -> None:
        installed.return_value = False

        result = self.run_with(FakeSpotifyApp(None), [spotify_item("track", "Patience", "Guns N' Roses")])

        startfile.assert_not_called()
        browser.assert_called_once_with("https://open.spotify.com/track/3OUWMcgPTQIElaufktjDLK", 2)
        self.assertEqual(result["state"], "web")
        self.assertIn("apertar play", describe_spotify(result, "Guns N' Roses"))

    def test_falls_back_to_spotify_web_when_the_link_does_not_open(self, _installed, startfile, browser, _sleep) -> None:
        startfile.side_effect = OSError("sem protocolo spotify:")

        with self.assertLogs("jarvis-pc", "WARNING"):
            result = self.run_with(FakeSpotifyApp(""), [spotify_item("track", "Patience", "Guns N' Roses")])

        self.assertEqual(result["state"], "web")
        browser.assert_called_once()


class SpotifyToolTests(LastMediaIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_open_streaming_spotify_plays_through_the_app(self) -> None:
        played = {
            "state": "playing",
            "item": spotify_item("album", "Greatest Hits", "Guns N' Roses"),
            "url": "https://open.spotify.com/album/3OUWMcgPTQIElaufktjDLK",
            "now": "Guns N' Roses - Welcome To The Jungle",
        }
        with patch("pc_control.play_spotify", return_value=played) as play, patch("pc_control.webbrowser.open") as browser:
            result = await open_streaming(FakeRunContext(), service="Spotify", query="Guns N' Roses")

        play.assert_called_once_with("Guns N' Roses")
        browser.assert_not_called()  # nada de abrir a busca web por cima
        self.assertIn("Tocando agora", result)
        self.assertEqual(pc_control._LAST_MEDIA["where"], "app")

    async def test_other_services_say_that_nothing_plays_yet(self) -> None:
        with patch("pc_control.webbrowser.open"):
            result = await open_streaming(FakeRunContext(), service="Netflix", query="Homem de Ferro")
        self.assertIn("nada está tocando", result)


class FakeBrowser:
    """Tabs of one browser window: Ctrl+Tab moves on, Ctrl+W closes the active tab."""

    def __init__(self, *tabs: str) -> None:
        self.tabs = list(tabs)
        self.index = 0
        self.closed: list[str] = []

    def title(self) -> str:
        return self.tabs[self.index]

    def hotkey(self, *keys: str) -> None:
        if keys == ("ctrl", "tab"):
            self.index = (self.index + 1) % len(self.tabs)
        elif keys == ("ctrl", "w"):
            self.closed.append(self.tabs.pop(self.index))
            self.index = min(self.index, len(self.tabs) - 1)


@patch.object(pc_control, "IS_WINDOWS", True)
@patch("pc_control.time.sleep")
@patch("pc_control.win_desktop.bring_to_front", return_value=True)
@patch("pc_control._browser_windows", return_value=[win_desktop.Window(hwnd=1, title="x", process="msedge.exe", pid=1)])
class CloseMediaTabTests(LastMediaIsolation):
    def close(self, browser: FakeBrowser, name: str | None) -> str:
        with patch("pc_control._active_title", side_effect=browser.title), patch("pyautogui.hotkey", side_effect=browser.hotkey):
            return browser_tab_action("close", name)

    def test_generic_name_closes_the_exact_media_tab_among_other_youtube_tabs(self, *_mocks) -> None:
        pc_control.remember_media("YouTube", "Guns N' Roses - Patience", "https://www.youtube.com/watch?v=ErvgV4P6Fzc")
        browser = FakeBrowser(
            "J.A.R.V.I.S. - Microsoft Edge",
            "Aula de Python - YouTube - Microsoft Edge",
            "Guns N' Roses - Patience - YouTube - Microsoft Edge",
        )

        result = self.close(browser, "aba de reprodução")

        self.assertEqual(browser.closed, ["Guns N' Roses - Patience - YouTube - Microsoft Edge"])
        self.assertIn("Fechei", result)
        self.assertIsNone(pc_control._LAST_MEDIA)

    def test_service_name_prefers_the_media_title_then_any_tab_of_the_service(self, *_mocks) -> None:
        pc_control.remember_media("YouTube", "Guns N' Roses - Patience", "https://www.youtube.com/watch?v=ErvgV4P6Fzc")
        self.assertEqual(pc_control.media_tab_targets("YouTube"), ["guns n' roses - patience", "youtube"])
        self.assertEqual(pc_control.media_tab_targets("aba do YouTube"), ["guns n' roses - patience", "youtube"])
        self.assertEqual(pc_control.media_tab_targets("Tudo Gostoso"), ["tudo gostoso"])
        browser = FakeBrowser("J.A.R.V.I.S. - Microsoft Edge", "Aula de Python - YouTube - Microsoft Edge")

        self.close(browser, "YouTube")  # a aba do vídeo já não existe: cai para a do serviço

        self.assertEqual(browser.closed, ["Aula de Python - YouTube - Microsoft Edge"])

    def test_spotify_app_is_not_mistaken_for_a_tab(self, *_mocks) -> None:
        pc_control.remember_media("Spotify", "Spotify", "https://open.spotify.com/album/x", where="app")
        browser = FakeBrowser("J.A.R.V.I.S. - Microsoft Edge", "Gmail - Microsoft Edge")

        with self.assertRaises(PCControlError) as ctx:
            self.close(browser, "aba de reprodução")

        self.assertEqual(browser.closed, [])
        self.assertIn("close_app('Spotify')", str(ctx.exception))

    def test_hud_tab_is_never_closed_and_the_error_names_the_last_media(self, *_mocks) -> None:
        pc_control.remember_media("YouTube", "Guns N' Roses - Patience", "https://www.youtube.com/watch?v=ErvgV4P6Fzc")
        browser = FakeBrowser("J.A.R.V.I.S. - Microsoft Edge", "Guns N' Roses - Patience - YouTube - Microsoft Edge")

        with self.assertRaises(PCControlError) as ctx:
            self.close(browser, None)

        self.assertEqual(browser.closed, [])
        self.assertIn("Guns N' Roses - Patience", str(ctx.exception))


class MediaHonestyTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_control_says_it_does_not_close_anything(self) -> None:
        with patch("pc_control.press_media_key") as press:
            result = await media_control(FakeRunContext(), action="play_pause")
        press.assert_called_once_with("play_pause")
        self.assertIn("não fecha nada", result)

    def test_prompt_separates_closing_from_pausing_and_opening_from_playing(self) -> None:
        self.assertIn("Fechar nunca é pausar", AGENT_INSTRUCTION)
        self.assertIn('"abri" não é "está tocando"', AGENT_INSTRUCTION)
