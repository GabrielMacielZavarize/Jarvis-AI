from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from server import EMAIL_TOOL_NAMES, INSTALL_TOOL_NAMES, MEMORY_TOOL_NAMES, PC_TOOL_NAMES, TOOL_NAMES, create_app
from settings import load_settings
from tools import build_tools

# A memória vem ligada por padrão (JARVIS_ENABLE_MEMORY=true).
DEFAULT_TOOLS = TOOL_NAMES + MEMORY_TOOL_NAMES

LIVEKIT_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "LIVEKIT_URL": "wss://jarvis.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "a-very-long-test-secret-with-enough-entropy",
}


class ServerTests(unittest.TestCase):
    def client(self, env: dict[str, str]) -> TestClient:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app(reload_env=False))

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
