from __future__ import annotations

import json
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
