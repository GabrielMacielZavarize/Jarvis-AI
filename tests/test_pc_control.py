from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pc_control
from pc_control import (
    PCControlError,
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
    @patch("pc_control._focus", return_value=True)
    @patch("pc_control._browser_windows", return_value=[object()])
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
