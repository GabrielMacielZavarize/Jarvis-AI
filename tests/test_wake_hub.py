from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from server import create_app
from settings import load_settings
from wake_hub import PENDING_BROWSER_S, PENDING_WAKE_S, WakeHub, hud_events

LIVEKIT_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "LIVEKIT_URL": "wss://jarvis.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "a-very-long-test-secret-with-enough-entropy",
}
WAKE_ENV = {**LIVEKIT_ENV, "JARVIS_WAKE_WORD": "true", "JARVIS_WAKE_SECRET": "s3cret"}
DETECTOR = {"X-Jarvis-Wake": "s3cret"}
TAB = "tab-12345678"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def queued(hub: WakeHub, client_id: str) -> list[dict]:
    queue = hub.clients[client_id].queue
    return [queue.get_nowait() for _ in range(queue.qsize())]


class WakeHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.hub = WakeHub(clock=self.clock)

    def test_wake_without_hud_opens_the_browser_and_waits_for_it(self) -> None:
        result = self.hub.trigger(0.9)

        self.assertEqual(result, {"accepted": True, "opened_browser": True})
        self.assertFalse(self.hub.listening())
        self.hub.connect(TAB)
        self.assertEqual(queued(self.hub, TAB), [{"type": "wake", "score": 0.9}])

    def test_browser_that_never_shows_up_gives_the_mic_back(self) -> None:
        self.hub.trigger(0.9)
        self.clock.now += PENDING_BROWSER_S + 1

        self.assertTrue(self.hub.listening())
        self.hub.connect(TAB)
        self.assertEqual(queued(self.hub, TAB), [])

    def test_only_the_visible_tab_connects(self) -> None:
        self.hub.connect("tab-visible-1")
        self.clock.now += 1
        self.hub.connect("tab-hidden-22")
        self.hub.update("tab-hidden-22", session_active=False, visible=False, mic_label=None)

        self.assertEqual(self.hub.trigger(0.8)["opened_browser"], False)
        self.assertEqual(queued(self.hub, "tab-visible-1"), [{"type": "wake", "score": 0.8}])
        self.assertEqual(queued(self.hub, "tab-hidden-22"), [])

    def test_detector_pauses_during_the_link_and_resumes_after(self) -> None:
        self.hub.connect(TAB)
        self.hub.trigger(0.8)
        self.assertFalse(self.hub.detector_state()["listen"])

        self.hub.update(TAB, session_active=True, visible=True, mic_label="Headset")
        self.clock.now += PENDING_WAKE_S + 60
        self.assertFalse(self.hub.listening())
        self.assertEqual(self.hub.trigger(0.9)["accepted"], False)

        self.hub.update(TAB, session_active=False, visible=True, mic_label="Headset")
        self.assertEqual(self.hub.detector_state(), {"listen": True, "mic_label": "Headset"})

    def test_failed_or_ignored_wake_resumes_listening_at_once(self) -> None:
        self.hub.connect(TAB)
        self.hub.trigger(0.8)

        self.hub.wake_handled()

        self.assertTrue(self.hub.listening())

    def test_closed_tab_does_not_hold_the_detector(self) -> None:
        client = self.hub.connect(TAB)
        self.hub.update(TAB, session_active=True, visible=True, mic_label=None)

        self.hub.disconnect(client)

        self.assertTrue(self.hub.listening())

    def test_detector_goes_offline_when_it_stops_polling(self) -> None:
        self.assertFalse(self.hub.detector_online())
        self.hub.detector_state()
        self.assertTrue(self.hub.detector_online())
        self.clock.now += 10
        self.assertFalse(self.hub.detector_online())


class HudEventsTests(unittest.TestCase):
    def test_stream_sends_config_status_wake_and_ends_on_shutdown(self) -> None:
        hub = WakeHub()
        settings = load_settings({"GOOGLE_API_KEY": "x", "JARVIS_WAKE_WORD": "true", "JARVIS_WAKE_SILENCE_SECONDS": "45"})

        async def scenario() -> list[dict]:
            stream = hud_events(hub, TAB, settings)
            hub.detector_state()  # o detector está consultando o servidor
            events = [json.loads((await anext(stream))[6:]) for _ in range(2)]
            hub.trigger(0.77)
            events.append(json.loads((await anext(stream))[6:]))
            hub.close()
            async for chunk in stream:
                events.append(json.loads(chunk[6:]))
            return events

        events = asyncio.run(scenario())

        self.assertEqual(events[0], {"type": "config", "enabled": True, "silence_s": 45})
        self.assertEqual(events[1], {"type": "status", "detector": True, "listening": True})
        self.assertEqual(events[2], {"type": "wake", "score": 0.77})
        self.assertEqual(events[3], {"type": "status", "detector": True, "listening": False})
        self.assertEqual(len(events), 4)
        self.assertEqual(hub.clients, {})

    def test_status_never_says_listening_without_the_detector(self) -> None:
        hub = WakeHub()

        self.assertEqual(hub.status(), {"type": "status", "detector": False, "listening": False})


class WakeEndpointTests(unittest.TestCase):
    def client(self, env: dict[str, str]) -> tuple[TestClient, MagicMock]:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        browser = MagicMock()
        return TestClient(create_app(reload_env=False, open_browser=browser)), browser

    def test_status_reports_wake_word(self) -> None:
        client, _ = self.client({**WAKE_ENV, "JARVIS_WAKE_SILENCE_SECONDS": "20"})

        self.assertEqual(client.get("/api/status").json()["wake_word"], {"enabled": True, "silence_s": 20})

    def test_detector_needs_the_secret(self) -> None:
        client, _ = self.client(WAKE_ENV)

        self.assertEqual(client.get("/api/wake/detector").status_code, 403)
        self.assertEqual(client.get("/api/wake/detector", headers={"X-Jarvis-Wake": "chute"}).status_code, 403)
        self.assertEqual(client.post("/api/wake/trigger", json={"score": 0.9}).status_code, 403)
        self.assertEqual(client.get("/api/wake/detector", headers=DETECTOR).json(), {"listen": True, "mic_label": None})

    def test_other_sites_cannot_drive_the_hud_endpoints(self) -> None:
        client, _ = self.client(WAKE_ENV)
        cross = {"Sec-Fetch-Site": "cross-site"}

        self.assertEqual(client.post("/api/wake/hud", json={"client": TAB}, headers=cross).status_code, 403)
        self.assertEqual(client.post("/api/wake/result", json={"client": TAB, "result": "failed"}, headers=cross).status_code, 403)
        self.assertEqual(client.get(f"/api/wake/events?client={TAB}", headers=cross).status_code, 403)
        self.assertEqual(client.get("/api/wake/detector", headers={**DETECTOR, **cross}).status_code, 403)

    def test_trigger_without_hud_opens_the_browser_on_the_server_url(self) -> None:
        client, browser = self.client(WAKE_ENV)

        body = client.post("/api/wake/trigger", json={"score": 0.9}, headers=DETECTOR).json()

        self.assertEqual(body, {"accepted": True, "opened_browser": True})
        browser.assert_called_once_with("http://testserver/")
        self.assertFalse(client.get("/api/wake/detector", headers=DETECTOR).json()["listen"])

    def test_hud_report_sets_the_detector_microphone(self) -> None:
        client, _ = self.client(WAKE_ENV)
        client.app.state.wake_hub.connect(TAB)

        client.post("/api/wake/hud", json={"client": TAB, "session_active": False, "mic_label": " Headset (Redmi) "})

        self.assertEqual(client.get("/api/wake/detector", headers=DETECTOR).json(), {"listen": True, "mic_label": "Headset (Redmi)"})
        client.post("/api/wake/hud", json={"client": TAB, "session_active": True, "mic_label": "Headset (Redmi)"})
        self.assertFalse(client.get("/api/wake/detector", headers=DETECTOR).json()["listen"])

    def test_rejects_bad_tab_ids(self) -> None:
        client, _ = self.client(WAKE_ENV)

        self.assertEqual(client.post("/api/wake/hud", json={"client": "../x"}).status_code, 422)

    def test_disabled_wake_word_never_listens(self) -> None:
        client, browser = self.client({**LIVEKIT_ENV, "JARVIS_WAKE_SECRET": "s3cret"})

        self.assertEqual(client.get("/api/wake/detector", headers=DETECTOR).json()["listen"], False)
        self.assertEqual(client.post("/api/wake/trigger", json={"score": 0.9}, headers=DETECTOR).json()["accepted"], False)
        browser.assert_not_called()
        self.assertFalse(client.get("/api/status").json()["wake_word"]["enabled"])


if __name__ == "__main__":
    unittest.main()
