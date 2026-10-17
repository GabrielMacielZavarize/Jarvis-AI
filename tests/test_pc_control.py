from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pc_control
import tempfile
from pathlib import Path

import win_desktop
from pc_control import (
    PCControlError,
    find_window,
    resolve_site,
    save_shortcut_entry,
    window_action,
    best_match,
    browser_tab_action,
    close_app_processes,
    find_youtube_video,
    is_blocked_app,
    launch_app,
    normalize_url,
    streaming_url,
)

from test_tools import FakeResponse


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
    @patch("pc_control.os.startfile", create=True)
    @patch("pc_control.list_start_apps")
    def test_launch_uses_start_menu_and_aliases(self, mock_apps, mock_startfile) -> None:
        mock_apps.return_value = [
            {"name": "Visual Studio Code", "app_id": "Microsoft.VisualStudioCode"},
            {"name": "WhatsApp", "app_id": "5319275A.WhatsAppDesktop!App"},
        ]

        self.assertEqual(launch_app("vs code"), "Visual Studio Code")
        mock_startfile.assert_called_with("shell:AppsFolder\\Microsoft.VisualStudioCode")
        self.assertEqual(launch_app("zap"), "WhatsApp")

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

    @patch.object(pc_control, "IS_WINDOWS", True)
    @patch("pc_control._jarvis_ancestor_names", return_value=set())
    @patch("pc_control.hud_browser_processes", return_value=set())
    @patch("pc_control.find_processes", return_value=["spotify.exe"])
    @patch("pc_control.subprocess.run")
    def test_closes_gracefully_without_force(self, mock_run, _find, _hud, _ancestors) -> None:
        mock_run.return_value = SimpleNamespace(returncode=0)

        self.assertEqual(close_app_processes("spotify"), ["spotify.exe"])
        command = mock_run.call_args.args[0]
        self.assertEqual(command, ["taskkill", "/IM", "spotify.exe"])
        self.assertNotIn("/F", command)


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
    @patch("pc_control.win_desktop.move_to_monitor")
    @patch("pc_control.win_desktop.monitors")
    def test_moves_window_to_numbered_monitor(self, mock_monitors, mock_move, _windows) -> None:
        screen3 = win_desktop.Monitor(3, -1440, 124, 0, 2684, (-1440, 124, 0, 2636), False)
        mock_monitors.return_value = [screen3]

        self.assertIn("tela 3", window_action("configurações", "move", 3))
        mock_move.assert_called_once_with(2, screen3)
        with self.assertRaises(PCControlError):
            window_action("configurações", "move", 7)

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
