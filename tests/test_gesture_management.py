"""Painel Gestos do HUD (GST-18): catálogo, API do servidor e os botões pelo RPC do agente."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import gesture_mapping
import gestures
from gestures import GestureService, handle_panel_request, serve_gesture_panel

from test_gestures import FakeTracker, endless_frames


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "gestos.json"

    def entry(self, catalog: dict[str, Any], gesture: str) -> dict[str, Any]:
        return next(item for item in catalog["gestures"] if item["id"] == gesture)

    def test_defaults_and_reference_lists(self) -> None:
        catalog = gesture_mapping.catalog(self.path)
        ok = self.entry(catalog, "ok")
        self.assertEqual(ok["binding"], {"tipo": "acao", "acao": "play_pause"})
        self.assertEqual(ok["label"], "tocar/pausar a mídia")
        self.assertFalse(ok["custom"])
        self.assertEqual(self.entry(catalog, "joinha")["binding"], {"tipo": "nada"})
        self.assertEqual(len(catalog["gestures"]), len(gesture_mapping.GESTURES))
        self.assertIn({"id": "play_pause", "label": "tocar/pausar a mídia"}, catalog["actions"])
        self.assertTrue(any(item["name"] == "polegar para baixo segurado" for item in catalog["fixed"]))

    def test_marks_custom_ones_and_twins(self) -> None:
        gesture_mapping.set_binding("joinha", "action", "play_pause", self.path)
        catalog = gesture_mapping.catalog(self.path)
        joinha = self.entry(catalog, "joinha")
        self.assertTrue(joinha["custom"])
        self.assertEqual(joinha["default"], "nada (livre para personalizar)")
        self.assertEqual(joinha["same_as"], ["OK (👌)"])
        self.assertEqual(self.entry(catalog, "ok")["same_as"], ["joinha (👍)"])
        self.assertEqual(self.entry(catalog, "rock")["same_as"], [])


class GestureApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from server import create_app

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "gestos.json"
        patcher = patch.object(gesture_mapping, "GESTURES_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        layouts = patch("server._layout_names", return_value=["trabalho"])
        layouts.start()
        self.addCleanup(layouts.stop)
        self.client = TestClient(create_app(reload_env=False), base_url="http://127.0.0.1")

    def test_lists_with_layouts(self) -> None:
        data = self.client.get("/api/gestures").json()
        self.assertEqual(data["layouts"], ["trabalho"])
        self.assertIn("enabled", data)
        self.assertIn("calibrated", data)
        self.assertEqual(len(data["gestures"]), len(gesture_mapping.GESTURES))

    def test_set_and_reset_write_gestos_json(self) -> None:
        response = self.client.put("/api/gestures/rock", json={"kind": "app", "value": "spotify"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("rock (🤘) agora vai abrir o app spotify", response.json()["message"])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["rock"], {"tipo": "app", "nome": "spotify"})
        self.assertEqual(gesture_mapping.binding_for("rock", self.path).label, "abrir o app spotify")

        response = self.client.delete("/api/gestures/rock")
        self.assertIn("voltou ao padrão", response.json()["message"])
        self.assertNotIn("rock", json.loads(self.path.read_text(encoding="utf-8")))

        self.client.put("/api/gestures/joinha", json={"kind": "none"})
        self.client.delete("/api/gestures")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {})

    def test_same_refusals_as_the_voice(self) -> None:
        for body in (
            {"kind": "keys", "value": "alt+f4"},
            {"kind": "keys", "value": "ctrl+w"},
            {"kind": "keys", "value": "a"},
            {"kind": "action", "value": "fechar a janela"},
        ):
            response = self.client.put("/api/gestures/ok", json=body)
            self.assertEqual(response.status_code, 400, body)
            self.assertTrue(response.json()["detail"])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.client.put("/api/gestures/punho", json={"kind": "none"}).status_code, 400)
        self.assertEqual(self.client.put("/api/gestures/ok", json={"kind": "teleporte", "value": "x"}).status_code, 422)

    def test_other_sites_cannot_change_gestures(self) -> None:
        response = self.client.put(
            "/api/gestures/rock", json={"kind": "site", "value": "evil.example"}, headers={"Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.path.exists())


class PanelButtonTests(unittest.TestCase):
    def service(self, stop: threading.Event) -> GestureService:
        return GestureService(
            frames_factory=lambda: (endless_frames(stop), "teste"),
            actions_factory=MagicMock,
            overlay_factory=lambda: None,
            tracker_factory=lambda: FakeTracker([]),
            panel_factory=lambda: None,
        )

    def test_buttons_reply_with_the_service_state(self) -> None:
        stop = threading.Event()
        service = self.service(stop)
        try:
            off = handle_panel_request('{"action": "status"}', service)
            self.assertEqual((off["ok"], off["running"], off["state"]), (True, False, "off"))
            on = handle_panel_request('{"action": "on"}', service)
            self.assertIn("Gestos ligados", on["message"])
            self.assertTrue(on["running"])
            self.assertEqual(on["source"], "teste")
            armed = handle_panel_request('{"action": "arm"}', service)
            self.assertEqual(armed["message"], "Gestos armados.")
        finally:
            handle_panel_request('{"action": "off"}', service)
            stop.set()
        self.assertFalse(service.running)

    def test_unknown_or_broken_requests_change_nothing(self) -> None:
        service = MagicMock()
        service.snapshot.return_value = {"running": False, "state": "off"}
        for payload in ('{"action": "format_c"}', "não é json", "[]"):
            reply = handle_panel_request(payload, service)
            self.assertFalse(reply["ok"])
        service.start.assert_not_called()
        service.stop.assert_not_called()

    def test_rpc_is_registered_on_the_room(self) -> None:
        room = MagicMock()
        service = MagicMock()
        service.describe.return_value = "Os gestos estão desligados."
        service.snapshot.return_value = {"running": False, "state": "off"}
        serve_gesture_panel(room, service)
        method, handler = room.local_participant.register_rpc_method.call_args.args
        self.assertEqual(method, gestures.GESTURE_RPC_METHOD)
        reply = json.loads(asyncio.run(handler(MagicMock(payload='{"action": "status"}'))))
        self.assertEqual(reply["message"], "Os gestos estão desligados.")


if __name__ == "__main__":
    unittest.main()
