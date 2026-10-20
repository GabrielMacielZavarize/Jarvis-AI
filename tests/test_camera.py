from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import camera
from camera import CameraError, CameraHub, pick_camera
from server import CAMERA_TOOL_NAMES, DIARY_TOOL_NAMES, MEMORY_TOOL_NAMES, ROUTINE_TOOL_NAMES, TOOL_NAMES, create_app

LOCAL = "http://127.0.0.1:8000"


class FakeSource:
    """Webcam de mentira: quadros numerados (o valor dos pixels é o número do quadro)."""

    def __init__(self, interval: float = 0.004, fail_after: int | None = None) -> None:
        self.name = "ASUS FHD webcam"
        self.backend = "FAKE"
        self.interval = interval
        self.fail_after = fail_after
        self.count = 0
        self.closed = False

    def read(self) -> np.ndarray | None:
        time.sleep(self.interval)
        if self.fail_after is not None and self.count >= self.fail_after:
            return None
        self.count += 1
        return np.full((6, 8, 3), self.count % 256, dtype=np.uint8)

    def close(self) -> None:
        self.closed = True


class FakeFactory:
    def __init__(self, **source_kwargs) -> None:
        self.source_kwargs = source_kwargs
        self.opened: list[FakeSource] = []

    def __call__(self) -> FakeSource:
        source = FakeSource(**self.source_kwargs)
        self.opened.append(source)
        return source


def wait_until(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class PickCameraTests(unittest.TestCase):
    NAMES = ["ASUS IR camera", "ASUS FHD webcam"]

    def test_default_skips_infrared_camera(self) -> None:
        self.assertEqual(pick_camera(self.NAMES), 1)

    def test_by_name_or_index(self) -> None:
        self.assertEqual(pick_camera(self.NAMES, "fhd"), 1)
        self.assertEqual(pick_camera(self.NAMES, "1"), 1)

    def test_infrared_is_never_chosen(self) -> None:
        with self.assertRaisesRegex(CameraError, "infravermelha"):
            pick_camera(self.NAMES, "0")
        with self.assertRaisesRegex(CameraError, "Não achei"):
            pick_camera(self.NAMES, "IR camera")
        with self.assertRaisesRegex(CameraError, "infravermelhas"):
            pick_camera(["Integrated IR Camera"])

    def test_missing_camera(self) -> None:
        with self.assertRaisesRegex(CameraError, "Nenhuma webcam"):
            pick_camera([])
        with self.assertRaisesRegex(CameraError, "Não achei a câmera 'Logitech'.*ASUS FHD webcam"):
            pick_camera(self.NAMES, "Logitech")


class CameraHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FakeFactory()
        self.hub = CameraHub(self.factory, linger=0)
        self.addCleanup(self.hub.off)

    def test_camera_starts_on_demand_and_stops_when_unused(self) -> None:
        frames = self.hub.frames()
        self.assertEqual(self.factory.opened, [])  # criar o iterador não liga nada
        self.assertFalse(self.hub.state()["active"])

        first = next(frames)
        self.assertEqual(first.shape, (6, 8, 3))
        self.assertFalse(first.flags.writeable)
        self.assertTrue(self.hub.state()["active"])
        self.assertEqual(self.hub.state()["users"], 1)

        frames.close()
        self.assertTrue(wait_until(lambda: not self.hub.state()["active"]))
        self.assertTrue(self.factory.opened[0].closed)
        self.assertIsNone(self.hub.latest())

    def test_each_next_returns_a_newer_frame(self) -> None:
        frames = self.hub.frames()
        values = [int(next(frames)[0, 0, 0]) for _ in range(5)]
        frames.close()
        self.assertEqual(values, sorted(set(values)))

    def test_many_consumers_get_every_newest_frame_without_stealing(self) -> None:
        got: dict[str, list[int]] = {"fast": [], "slow": []}

        def consume(name: str, count: int, delay: float) -> None:
            for frame in self.hub.frames():
                got[name].append(int(frame[0, 0, 0]))
                time.sleep(delay)
                if len(got[name]) >= count:
                    break

        threads = [
            threading.Thread(target=consume, args=("fast", 30, 0)),
            threading.Thread(target=consume, args=("slow", 5, 0.03)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        self.assertEqual(len(got["fast"]), 30)
        self.assertEqual(len(got["slow"]), 5)
        # Um único dispositivo aberto para os dois consumidores.
        self.assertEqual(len(self.factory.opened), 1)
        # O lento pula quadros (recebe sempre o mais recente) em vez de acumular fila.
        self.assertGreater(got["slow"][-1] - got["slow"][0], 4)
        self.assertTrue(wait_until(lambda: not self.hub.state()["active"]))

    def test_reference_count_keeps_camera_on_until_last_user(self) -> None:
        first = self.hub.start()
        second = self.hub.start()
        self.assertEqual(self.hub.state()["users"], 2)
        self.hub.stop(first)
        self.assertIsNotNone(self.hub.wait_frame(second, 0))
        self.assertTrue(self.hub.state()["active"])
        self.hub.stop(second)
        self.hub.stop(second)  # devolver duas vezes não quebra a contagem
        self.assertTrue(wait_until(lambda: not self.hub.state()["active"]))
        self.assertEqual(self.hub.state()["users"], 0)

    def test_linger_holds_camera_briefly(self) -> None:
        hub = CameraHub(self.factory, linger=0.3)
        self.addCleanup(hub.off)
        hub.snapshot_jpeg()
        self.assertTrue(hub.state()["active"])
        hub.snapshot_jpeg()
        self.assertEqual(len(self.factory.opened), 1)  # o segundo snapshot reaproveitou a câmera
        self.assertTrue(wait_until(lambda: not hub.state()["active"]))

    def test_off_ends_every_consumer_right_away(self) -> None:
        frames = self.hub.frames()
        next(frames)
        ticket = self.hub.start()
        self.hub.off()
        self.assertEqual(list(frames), [])  # termina normalmente, sem erro
        self.assertIsNone(self.hub.wait_frame(ticket, 0))
        state = self.hub.state()
        self.assertFalse(state["active"])
        self.assertEqual(state["users"], 0)
        self.assertTrue(self.factory.opened[0].closed)

    def test_camera_can_be_turned_on_again_after_off(self) -> None:
        next(self.hub.frames())
        self.hub.off()
        frames = self.hub.frames()
        self.assertIsNotNone(next(frames))
        frames.close()
        self.assertEqual(len(self.factory.opened), 2)

    def test_snapshot_is_a_fresh_jpeg(self) -> None:
        data = self.hub.snapshot_jpeg(quality=80)
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertTrue(wait_until(lambda: not self.hub.state()["active"]))

    def test_latest_does_not_turn_camera_on(self) -> None:
        self.assertIsNone(self.hub.latest())
        self.assertEqual(self.factory.opened, [])
        with self.hub.session() as ticket:
            self.hub.wait_frame(ticket, 0)
            frame, taken = self.hub.latest()
            self.assertEqual(frame.shape, (6, 8, 3))
            self.assertAlmostEqual(taken, time.time(), delta=2)

    def test_open_failure_raises_camera_error(self) -> None:
        def busy() -> FakeSource:
            raise CameraError("Não consegui abrir a webcam 'ASUS FHD webcam'.")

        hub = CameraHub(busy, linger=0)
        with self.assertRaisesRegex(CameraError, "Não consegui abrir"):
            next(hub.frames())
        with self.assertRaisesRegex(CameraError, "Não consegui abrir"):
            hub.snapshot_jpeg()
        self.assertEqual(hub.state()["users"], 0)
        self.assertIn("Não consegui abrir", hub.state()["error"])

    def test_camera_that_stops_sending_frames_raises(self) -> None:
        hub = CameraHub(FakeFactory(interval=0.001, fail_after=2), linger=0)
        self.addCleanup(hub.off)
        with self.assertRaisesRegex(CameraError, "parou de enviar"):
            for _ in hub.frames(timeout=3):
                pass

    def test_pin_keeps_camera_on_until_off(self) -> None:
        self.hub.pin()
        time.sleep(0.05)
        state = self.hub.state()
        self.assertTrue(state["active"] and state["pinned"])
        self.hub.off()
        self.assertFalse(self.hub.state()["active"])
        self.assertFalse(self.hub.state()["pinned"])

    def test_stream_jpeg_is_encoded_once_per_frame(self) -> None:
        with self.hub.session() as ticket:
            data, seq = self.hub.next_jpeg(ticket, 0)
            frame, _, same_seq = self.hub.wait_frame(ticket, seq - 1)
            self.assertIs(self.hub.jpeg_of(frame, same_seq, 70), data)

    def test_default_source_respects_the_env_flag(self) -> None:
        with patch.dict(os.environ, {"JARVIS_ENABLE_CAMERA": "false"}), patch("camera.open_camera") as open_camera:
            with self.assertRaisesRegex(CameraError, "JARVIS_ENABLE_CAMERA=true"):
                camera._default_source()
            open_camera.assert_not_called()
        with patch.dict(os.environ, {"JARVIS_ENABLE_CAMERA": "true", "JARVIS_CAMERA": "FHD"}), patch(
            "camera.open_camera"
        ) as open_camera:
            camera._default_source()
            open_camera.assert_called_once_with("FHD")


CAMERA_ENV = {"GOOGLE_API_KEY": "test-key", "JARVIS_ENABLE_CAMERA": "true"}


class CameraServerTests(unittest.TestCase):
    def client(self, env: dict[str, str], hub: CameraHub | None = None, base_url: str = LOCAL) -> TestClient:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hub = hub or CameraHub(FakeFactory(), linger=0)
        self.addCleanup(self.hub.off)
        return TestClient(create_app(reload_env=False, camera_hub=self.hub), base_url=base_url)

    def test_status_lists_camera_tools_only_when_enabled(self) -> None:
        body = self.client(CAMERA_ENV).get("/api/status").json()
        self.assertTrue(body["camera"])
        self.assertEqual(body["tools"], TOOL_NAMES + MEMORY_TOOL_NAMES + DIARY_TOOL_NAMES + ROUTINE_TOOL_NAMES + CAMERA_TOOL_NAMES)
        self.assertFalse(self.client({"GOOGLE_API_KEY": "x"}).get("/api/status").json()["camera"])

    def test_disabled_camera_never_turns_on(self) -> None:
        client = self.client({"GOOGLE_API_KEY": "test-key"})
        for method, path in (("GET", "/api/camera/snapshot"), ("GET", "/api/camera/stream"), ("POST", "/api/camera/on")):
            response = client.request(method, path)
            self.assertEqual(response.status_code, 403, path)
            self.assertIn("JARVIS_ENABLE_CAMERA", response.json()["detail"])
        state = client.get("/api/camera/state").json()
        self.assertFalse(state["enabled"])
        self.assertFalse(state["active"])

    def test_snapshot_returns_jpeg_and_releases_camera(self) -> None:
        client = self.client(CAMERA_ENV)
        response = client.get("/api/camera/snapshot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.content.startswith(b"\xff\xd8"))
        self.assertTrue(wait_until(lambda: not self.hub.state()["active"]))

    def test_snapshot_reports_busy_camera(self) -> None:
        def busy() -> FakeSource:
            raise CameraError("Não consegui abrir a webcam: ela pode estar em uso por outro programa.")

        response = self.client(CAMERA_ENV, CameraHub(busy, linger=0)).get("/api/camera/snapshot")
        self.assertEqual(response.status_code, 503)
        self.assertIn("em uso", response.json()["detail"])

    def test_stream_is_mjpeg_and_ends_when_camera_is_turned_off(self) -> None:
        client = self.client(CAMERA_ENV)
        threading.Timer(0.3, self.hub.off).start()
        response = client.get("/api/camera/stream")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "multipart/x-mixed-replace; boundary=frame")
        parts = response.content.split(b"--frame\r\n")[1:]
        self.assertGreater(len(parts), 3)
        self.assertTrue(parts[0].startswith(b"Content-Type: image/jpeg\r\nContent-Length: "))
        self.assertIn(b"\r\n\r\n\xff\xd8", parts[0])
        self.assertEqual(self.hub.state()["users"], 0)

    def test_state_on_and_off(self) -> None:
        client = self.client(CAMERA_ENV)
        on = client.post("/api/camera/on").json()
        self.assertTrue(on["active"] and on["pinned"])
        self.assertEqual(on["device"], "ASUS FHD webcam")
        state = client.get("/api/camera/state").json()
        self.assertTrue(state["enabled"] and state["active"])
        off = client.post("/api/camera/off").json()
        self.assertFalse(off["active"])
        self.assertEqual(off["users"], 0)

    def test_state_turns_camera_off_when_disabled_in_env(self) -> None:
        client = self.client(CAMERA_ENV)
        client.post("/api/camera/on")
        os.environ["JARVIS_ENABLE_CAMERA"] = "false"
        state = client.get("/api/camera/state").json()
        self.assertFalse(state["enabled"])
        self.assertFalse(state["active"])

    def test_camera_only_answers_this_computer(self) -> None:
        remote = self.client(CAMERA_ENV, base_url="http://192.168.0.10:8000")
        self.assertEqual(remote.get("/api/camera/snapshot").status_code, 403)
        self.assertEqual(remote.get("/api/camera/state").status_code, 403)
        rebinding = self.client(CAMERA_ENV, base_url="http://evil.example:8000")
        self.assertEqual(rebinding.get("/api/camera/stream").status_code, 403)

    def test_other_sites_in_the_browser_cannot_use_the_camera(self) -> None:
        client = self.client(CAMERA_ENV)
        cross = {"Sec-Fetch-Site": "cross-site"}
        self.assertEqual(client.get("/api/camera/stream", headers=cross).status_code, 403)
        self.assertEqual(client.post("/api/camera/on", headers=cross).status_code, 403)
        self.assertEqual(client.post("/api/camera/off", headers={"Sec-Fetch-Site": "same-site"}).status_code, 403)
        self.assertFalse(self.hub.state()["active"])
        same = client.get("/api/camera/snapshot", headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(same.status_code, 200)
