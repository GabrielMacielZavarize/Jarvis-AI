from __future__ import annotations

import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from PIL import Image

import vision
from jarvis import _local_url
from settings import DEFAULT_HUD_URL, load_settings

from test_tools import FakeRunContext


def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), (30, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def fake_response(status: int = 200, *, content: bytes = b"", json: dict | None = None) -> MagicMock:
    response = MagicMock(status_code=status, content=content)
    response.json.return_value = json if json is not None else {}
    return response


def realtime_context() -> tuple[FakeRunContext, MagicMock]:
    context = FakeRunContext()
    push_video = MagicMock()
    context.session.current_agent = SimpleNamespace(realtime_llm_session=SimpleNamespace(push_video=push_video))
    return context, push_video


class CameraSettingsTests(unittest.TestCase):
    def test_camera_is_off_by_default(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "x"})
        self.assertFalse(settings.camera_enabled)
        self.assertIsNone(settings.camera_device)
        self.assertEqual(settings.hud_url, DEFAULT_HUD_URL)

    def test_camera_settings(self) -> None:
        settings = load_settings(
            {"JARVIS_ENABLE_CAMERA": "true", "JARVIS_CAMERA": "FHD", "JARVIS_HUD_URL": "http://127.0.0.1:8080/"}
        )
        self.assertTrue(settings.camera_enabled)
        self.assertEqual(settings.camera_device, "FHD")
        self.assertEqual(settings.hud_url, "http://127.0.0.1:8080")

    def test_agent_gets_a_reachable_hud_url(self) -> None:
        self.assertEqual(_local_url("127.0.0.1", 8000), "http://127.0.0.1:8000")
        self.assertEqual(_local_url("0.0.0.0", 8080), "http://127.0.0.1:8080")
        self.assertEqual(_local_url("::1", 8000), "http://[::1]:8000")


class LookAtCameraTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, {"JARVIS_HUD_URL": "http://127.0.0.1:8123"})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_sends_snapshot_to_model_and_hud(self) -> None:
        context, push_video = realtime_context()
        with patch("vision.requests.request", return_value=fake_response(content=jpeg_bytes())) as request, patch(
            "vision.send_screenshot", new=AsyncMock(return_value=True)
        ) as send:
            result = await vision.look_at_camera(context, "que livro é esse?")

        request.assert_called_once()
        self.assertEqual(request.call_args.args, ("GET", "http://127.0.0.1:8123/api/camera/snapshot"))
        push_video.assert_called_once()
        frame = push_video.call_args.args[0]
        self.assertEqual((frame.width, frame.height), (64, 36))
        send.assert_awaited_once()
        self.assertEqual(send.call_args.kwargs["topic"], "jarvis.camera")
        self.assertEqual(send.call_args.kwargs["attributes"], {"question": "que livro é esse?"})
        self.assertIn("enviada a você como imagem", result)
        self.assertIn('"que livro é esse?"', result)

    async def test_clear_error_when_hud_server_is_down(self) -> None:
        context, push_video = realtime_context()
        with patch("vision.requests.request", side_effect=requests.ConnectionError()):
            result = await vision.look_at_camera(context)

        self.assertIn("Não consegui olhar pela câmera", result)
        self.assertIn("servidor do HUD não está rodando em http://127.0.0.1:8123", result)
        self.assertIn("python jarvis.py", result)
        push_video.assert_not_called()

    async def test_reports_why_the_camera_failed(self) -> None:
        context, _ = realtime_context()
        busy = fake_response(503, json={"detail": "Não consegui abrir a webcam 'ASUS FHD webcam'."})
        with patch("vision.requests.request", return_value=busy):
            result = await vision.look_at_camera(context)
        self.assertEqual(result, "Não consegui olhar pela câmera: Não consegui abrir a webcam 'ASUS FHD webcam'.")

    async def test_model_without_images_is_honest(self) -> None:
        with patch("vision.requests.request", return_value=fake_response(content=jpeg_bytes())), patch(
            "vision.send_screenshot", new=AsyncMock(return_value=True)
        ):
            result = await vision.look_at_camera(FakeRunContext())
        self.assertIn("não recebe imagens", result)


class CameraViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_show_opens_panel_and_confirms_feed(self) -> None:
        states = [{"enabled": True, "active": False}, {"enabled": True, "active": True, "streaming": True}]
        with patch("vision.camera_state", side_effect=states), patch(
            "vision.show_card", new=AsyncMock(return_value=True)
        ) as show:
            result = await vision.camera_view(FakeRunContext(), "show")
        show.assert_awaited_once_with("camera", {})
        self.assertIn("Câmera ligada", result)

    async def test_show_when_camera_is_disabled(self) -> None:
        with patch("vision.camera_state", return_value={"enabled": False}), patch("vision.show_card", new=AsyncMock()) as show:
            result = await vision.camera_view(FakeRunContext(), "show")
        show.assert_not_awaited()
        self.assertIn("JARVIS_ENABLE_CAMERA=false", result)

    async def test_show_without_hud(self) -> None:
        with patch("vision.camera_state", return_value={"enabled": True}), patch(
            "vision.show_card", new=AsyncMock(return_value=False)
        ):
            result = await vision.camera_view(FakeRunContext(), "show")
        self.assertIn("NADA foi aberto", result)

    async def test_show_reports_camera_error(self) -> None:
        states = [{"enabled": True}, {"enabled": True, "active": False, "error": "A webcam está em uso."}]
        with patch("vision.camera_state", side_effect=states), patch("vision.show_card", new=AsyncMock(return_value=True)):
            result = await vision.camera_view(FakeRunContext(), "show")
        self.assertIn("não ligou: A webcam está em uso.", result)

    async def test_hide_closes_panel(self) -> None:
        hud = AsyncMock(return_value={"changed": [{"kind": "camera"}], "open": []})
        with patch("vision.hud_request", new=hud), patch(
            "vision.camera_state", return_value={"active": True, "users": 0}
        ), patch("vision.POLL_SECONDS", 0):
            result = await vision.camera_view(FakeRunContext(), "hide")
        hud.assert_awaited_once_with("close", {"targets": ["camera"], "kinds": ["camera"]})
        self.assertIn("desliga sozinha", result)

    async def test_hide_warns_when_something_else_uses_the_camera(self) -> None:
        with patch("vision.hud_request", new=AsyncMock(return_value={"changed": [{}]})), patch(
            "vision.camera_state", return_value={"active": True, "users": 1}
        ), patch("vision.POLL_SECONDS", 0):
            result = await vision.camera_view(FakeRunContext(), "hide")
        self.assertIn("continua ligada", result)

    async def test_hide_when_panel_is_not_open(self) -> None:
        with patch("vision.hud_request", new=AsyncMock(return_value={"changed": [], "open": []})):
            result = await vision.camera_view(FakeRunContext(), "hide")
        self.assertIn("não estava aberto", result)

    async def test_off_turns_camera_off_and_closes_panel(self) -> None:
        hud = AsyncMock(return_value=None)
        with patch("vision.requests.request", return_value=fake_response(json={"active": False})) as request, patch(
            "vision.hud_request", new=hud
        ):
            result = await vision.camera_view(FakeRunContext(), "off")
        self.assertEqual(request.call_args.args[0], "POST")
        self.assertTrue(request.call_args.args[1].endswith("/api/camera/off"))
        hud.assert_awaited_once()
        self.assertIn("Câmera desligada", result)

    async def test_off_when_server_is_down(self) -> None:
        with patch("vision.requests.request", side_effect=requests.ConnectionError()):
            result = await vision.camera_view(FakeRunContext(), "off")
        self.assertIn("NADA mudou na câmera", result)
