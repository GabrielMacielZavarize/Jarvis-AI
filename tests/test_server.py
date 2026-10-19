from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from server import (
    EMAIL_TOOL_NAMES,
    INSTALL_TOOL_NAMES,
    MEMORY_TOOL_NAMES,
    PC_TOOL_NAMES,
    ROUTINE_TOOL_NAMES,
    TOOL_NAMES,
    create_app,
)
from settings import load_settings
from tools import build_tools

# A memória vem ligada por padrão (JARVIS_ENABLE_MEMORY=true).
DEFAULT_TOOLS = TOOL_NAMES + MEMORY_TOOL_NAMES + ROUTINE_TOOL_NAMES

LOCAL = "http://127.0.0.1:8000"

LIVEKIT_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "LIVEKIT_URL": "wss://jarvis.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "a-very-long-test-secret-with-enough-entropy",
}


class ServerTests(unittest.TestCase):
    def client(self, env: dict[str, str], base_url: str = "http://testserver") -> TestClient:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app(reload_env=False), base_url=base_url)

    def test_status_reports_missing_livekit(self) -> None:
        response = self.client({"GOOGLE_API_KEY": "test-key"}).get("/api/status")

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(body["ready"])
        self.assertFalse(body["livekit_configured"])
        self.assertEqual(body["backend"], "gemini-realtime")
        self.assertNotIn("test-key", response.text)

    def test_status_ready_when_configured(self) -> None:
        body = self.client(LIVEKIT_ENV).get("/api/status").json()

        self.assertTrue(body["ready"])
        self.assertEqual(body["tools"], DEFAULT_TOOLS)
        self.assertTrue(body["memory"])
        self.assertNotIn(LIVEKIT_ENV["LIVEKIT_API_SECRET"], str(body))

    def test_ambient_mode_without_home_city_or_calendar_is_empty(self) -> None:
        body = self.client({"GOOGLE_API_KEY": "test-key"}, LOCAL).get("/api/ambient").json()

        self.assertEqual(body, {"weather": None, "next_event": None})

    def test_ambient_mode_shows_the_weather_of_the_home_city(self) -> None:
        home = {"name": "Criciúma", "latitude": -28.68, "longitude": -49.37}
        now = {"temperature": 22.4, "code": 2, "label": "Parcialmente nublado", "is_day": 1, "max": 26, "min": 17}
        with (
            patch("server._geocode_home", return_value=home),
            patch("weather.current_conditions", return_value=now) as conditions,
            patch.dict("server._AMBIENT_CACHE", clear=True),
        ):
            client = self.client({"GOOGLE_API_KEY": "test-key", "JARVIS_HOME_CITY": "Criciúma"}, LOCAL)
            first = client.get("/api/ambient").json()
            client.get("/api/ambient")

        self.assertEqual(first["weather"], {"city": "Criciúma", **now})
        # The second request inside the cache window does not go to the network.
        conditions.assert_called_once_with(-28.68, -49.37)

    def test_live_system_numbers_only_for_this_computer(self) -> None:
        client = self.client({"GOOGLE_API_KEY": "test-key"}, LOCAL)
        body = client.get("/api/system/live").json()
        self.assertEqual(set(body), {"cpu", "per_core", "memory"})

        other_site = client.get("/api/system/live", headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(other_site.status_code, 403)
        self.assertEqual(self.client({"GOOGLE_API_KEY": "test-key"}, "http://192.168.0.10:8000").get("/api/system/live").status_code, 403)

    def test_token_requires_livekit(self) -> None:
        response = self.client({"GOOGLE_API_KEY": "test-key"}).post("/api/token", json={})

        self.assertEqual(response.status_code, 503)

    def test_token_uses_standard_endpoint_format(self) -> None:
        response = self.client(LIVEKIT_ENV).post(
            "/api/token",
            json={
                "room_name": "jarvis-demo",
                "participant_name": "Tony",
                "room_config": {"agents": [{"agent_name": "jarvis"}]},
            },
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["server_url"], LIVEKIT_ENV["LIVEKIT_URL"])

        claims = jwt.decode(
            body["participant_token"],
            LIVEKIT_ENV["LIVEKIT_API_SECRET"],
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        self.assertEqual(claims["video"]["room"], "jarvis-demo")
        self.assertEqual(claims["name"], "Tony")
        self.assertEqual(claims["roomConfig"]["agents"][0]["agentName"], "jarvis")

    def test_token_rejects_unsafe_names(self) -> None:
        response = self.client(LIVEKIT_ENV).post(
            "/api/token",
            json={"room_name": "../../etc", "participant_name": "<script>"},
        )

        claims = jwt.decode(
            response.json()["participant_token"],
            options={"verify_signature": False},
        )
        self.assertTrue(claims["video"]["room"].startswith("jarvis-"))
        self.assertEqual(claims["name"], "Operador")

    def test_tool_catalog_matches_registered_tools(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
                "GMAIL_USER": "jarvis@example.com",
                "GMAIL_APP_PASSWORD": "secret",
            }
        )

        self.assertEqual(
            [tool.__name__ for tool in build_tools(settings)],
            DEFAULT_TOOLS + EMAIL_TOOL_NAMES,
        )

    def test_pc_control_tools_are_opt_in(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key", "JARVIS_ENABLE_PC_CONTROL": "true"})

        self.assertEqual([tool.__name__ for tool in build_tools(settings)], DEFAULT_TOOLS + PC_TOOL_NAMES)
        body = self.client({**LIVEKIT_ENV, "JARVIS_ENABLE_PC_CONTROL": "true"}).get("/api/status").json()
        self.assertTrue(body["pc_control"])
        self.assertEqual(body["tools"], DEFAULT_TOOLS + PC_TOOL_NAMES)
        self.assertIsNone(body["home"])

    def test_app_install_tools_are_opt_in(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key", "JARVIS_ENABLE_APP_INSTALL": "true"})

        self.assertEqual([tool.__name__ for tool in build_tools(settings)], DEFAULT_TOOLS + INSTALL_TOOL_NAMES)
        body = self.client({**LIVEKIT_ENV, "JARVIS_ENABLE_APP_INSTALL": "true"}).get("/api/status").json()
        self.assertTrue(body["app_install"])
        self.assertEqual(body["tools"], DEFAULT_TOOLS + INSTALL_TOOL_NAMES)
        self.assertFalse(self.client(LIVEKIT_ENV).get("/api/status").json()["app_install"])
