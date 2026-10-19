"""LAN-26: celular na rede de casa com pareamento, token por aparelho e revogação."""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from camera import CameraHub
from lan_access import (
    CODE_TTL_S,
    COOKIE_NAME,
    MAX_CODE_ATTEMPTS,
    DeviceRegistry,
    PairingError,
    ensure_certificates,
    is_loopback_peer,
)
from server import create_app
from tests.test_camera import FakeFactory
from wake_hub import WakeHub

LOCAL = "http://127.0.0.1:8000"
PHONE_URL = "https://192.168.0.5:8000"
PHONE_PEER = ("192.168.0.20", 51234)
ENV = {
    "GOOGLE_API_KEY": "test-key",
    "JARVIS_ENABLE_CAMERA": "true",
    "LIVEKIT_URL": "wss://jarvis.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "a-very-long-test-secret-with-enough-entropy",
}
# Rotas que nunca podem responder a um aparelho sem token (inclui uma inexistente).
PROTECTED = [
    ("GET", "/api/status"),
    ("POST", "/api/token"),
    ("GET", "/api/camera/state"),
    ("GET", "/api/camera/snapshot"),
    ("GET", "/api/camera/stream"),
    ("POST", "/api/camera/on"),
    ("POST", "/api/camera/off"),
    ("GET", "/api/screenshots/ultimo.png"),
    ("GET", "/api/wake/events?client=abcdefgh-1234"),
    ("POST", "/api/wake/hud"),
    ("GET", "/api/lan/info"),
    ("POST", "/api/lan/pairing"),
    ("GET", "/api/lan/qr.svg"),
    ("DELETE", "/api/lan/devices/abc"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
]


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.clock = Clock()
        self.registry = DeviceRegistry(self.dir / "aparelhos.json", clock=self.clock)

    def test_code_has_six_digits_and_expires(self) -> None:
        state = self.registry.start_pairing()
        self.assertRegex(state["code"], r"^\d{6}$")
        self.assertEqual(state["expires_in"], CODE_TTL_S)
        self.clock.now += CODE_TTL_S + 1
        self.assertIsNone(self.registry.pairing_state()["code"])
        with self.assertRaises(PairingError):
            self.registry.pair(state["code"], "Pixel")

    def test_pairing_consumes_code_and_issues_token(self) -> None:
        code = self.registry.start_pairing()["code"]
        device, token = self.registry.pair(code, "Pixel do Gabriel")
        self.assertEqual(device.name, "Pixel do Gabriel")
        self.assertEqual(self.registry.authenticate(token).id, device.id)
        self.assertIsNone(self.registry.authenticate("chute"))
        self.assertIsNone(self.registry.pairing_state()["code"])
        with self.assertRaises(PairingError):
            self.registry.pair(code, "Outro")

    def test_wrong_attempts_burn_the_code(self) -> None:
        code = self.registry.start_pairing()["code"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(MAX_CODE_ATTEMPTS):
            with self.assertRaises(PairingError):
                self.registry.pair(wrong, None)
        with self.assertRaises(PairingError):
            self.registry.pair(code, None)  # nem o certo vale mais

    def test_new_code_replaces_the_old_one(self) -> None:
        first = self.registry.start_pairing()["code"]
        second = self.registry.start_pairing()["code"]
        if first != second:
            with self.assertRaises(PairingError):
                self.registry.pair(first, None)
        self.registry.pair(second, None)

    def test_revoke_and_persistence_keep_only_hashes(self) -> None:
        device, token = self.registry.pair(self.registry.start_pairing()["code"], "iPhone")
        raw = (self.dir / "aparelhos.json").read_text(encoding="utf-8")
        self.assertNotIn(token, raw)
        reloaded = DeviceRegistry(self.dir / "aparelhos.json", clock=self.clock)
        self.assertEqual(reloaded.authenticate(token).id, device.id)
        self.assertEqual([d["name"] for d in reloaded.devices()], ["iPhone"])
        self.assertTrue(reloaded.revoke(device.id))
        self.assertFalse(reloaded.revoke(device.id))
        self.assertIsNone(DeviceRegistry(self.dir / "aparelhos.json").authenticate(token))

    def test_corrupt_file_means_no_devices(self) -> None:
        (self.dir / "aparelhos.json").write_text("{nada", encoding="utf-8")
        self.assertEqual(DeviceRegistry(self.dir / "aparelhos.json").devices(), [])

    def test_device_names_are_cleaned(self) -> None:
        device, _ = self.registry.pair(self.registry.start_pairing()["code"], "  <b>\nX</b>  " + "a" * 80)
        self.assertNotIn("\n", device.name)
        self.assertLessEqual(len(device.name), 40)
        unnamed, _ = self.registry.pair(self.registry.start_pairing()["code"], "   ")
        self.assertEqual(unnamed.name, "Celular")

    def test_loopback_peers(self) -> None:
        for host in ("127.0.0.1", "::1", "testclient"):
            self.assertTrue(is_loopback_peer(host), host)
        for host in ("192.168.0.20", "10.0.0.2", "", None, "evil"):
            self.assertFalse(is_loopback_peer(host), host)


class LanServerTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, ENV, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hub = CameraHub(FakeFactory(), linger=0)
        self.addCleanup(self.hub.off)
        self.registry = DeviceRegistry(None)
        self.app = create_app(reload_env=False, camera_hub=self.hub, devices=self.registry)
        self.app.state.lan_urls = [PHONE_URL]
        self.pc = TestClient(self.app, base_url=LOCAL)

    def phone(self) -> TestClient:
        return TestClient(self.app, base_url=PHONE_URL, client=PHONE_PEER)

    def pair_phone(self, name: str = "Pixel") -> TestClient:
        code = self.pc.post("/api/lan/pairing").json()["code"]
        phone = self.phone()
        response = phone.post("/api/lan/pair", json={"code": code, "name": name})
        self.assertEqual(response.status_code, 200, response.text)
        return phone

    def test_pc_keeps_working_without_token(self) -> None:
        self.assertEqual(self.pc.get("/api/status").status_code, 200)
        self.assertEqual(self.pc.post("/api/token", json={}).status_code, 200)
        self.assertEqual(self.pc.get("/api/camera/state").status_code, 200)
        me = self.pc.get("/api/lan/me").json()
        self.assertTrue(me["local"])
        self.assertTrue(self.pc.get("/api/status").json()["lan"])

    def test_nothing_answers_an_unpaired_phone(self) -> None:
        phone = self.phone()
        for method, path in PROTECTED:
            response = phone.request(method, path)
            self.assertEqual(response.status_code, 401, f"{method} {path}")
        self.assertFalse(self.hub.state()["active"])
        forged = phone.get("/api/status", headers={"Authorization": "Bearer chute", "Cookie": f"{COOKIE_NAME}=chute"})
        self.assertEqual(forged.status_code, 401)

    def test_unpaired_phone_can_only_ask_and_pair(self) -> None:
        phone = self.phone()
        me = phone.get("/api/lan/me").json()
        self.assertEqual(me, {"local": False, "paired": False, "device": None})
        self.assertEqual(phone.post("/api/lan/pair", json={"code": "123456"}).status_code, 403)

    def test_pairing_sets_a_strict_http_only_cookie(self) -> None:
        code = self.pc.post("/api/lan/pairing").json()["code"]
        response = self.phone().post("/api/lan/pair", json={"code": code, "name": "Pixel"})
        cookie = response.headers["set-cookie"].lower()
        self.assertIn(f"{COOKIE_NAME}=", cookie)
        for flag in ("httponly", "secure", "samesite=strict", "max-age="):
            self.assertIn(flag, cookie)
        self.assertNotIn("token", response.json())  # só no cookie, fora do alcance do JavaScript

    def test_paired_phone_uses_voice_and_camera(self) -> None:
        phone = self.pair_phone()
        self.assertTrue(phone.get("/api/lan/me").json()["paired"])
        self.assertEqual(phone.get("/api/status").status_code, 200)
        token = phone.post("/api/token", json={})
        self.assertEqual(token.status_code, 200)
        self.assertIn("participant_token", token.json())
        snapshot = phone.get("/api/camera/snapshot")
        self.assertEqual(snapshot.status_code, 200)
        self.assertTrue(snapshot.content.startswith(b"\xff\xd8"))

    def test_bearer_token_also_works(self) -> None:
        code = self.registry.start_pairing()["code"]
        _, token = self.registry.pair(code, "script")
        response = self.phone().get("/api/status", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)

    def test_paired_phone_cannot_manage_devices(self) -> None:
        phone = self.pair_phone()
        device_id = self.registry.devices()[0]["id"]
        self.assertEqual(phone.get("/api/lan/info").status_code, 403)
        self.assertEqual(phone.post("/api/lan/pairing").status_code, 403)
        self.assertEqual(phone.delete(f"/api/lan/devices/{device_id}").status_code, 403)
        self.assertEqual(len(self.registry.devices()), 1)

    def test_other_sites_cannot_reach_through_the_phone(self) -> None:
        phone = self.pair_phone()
        cross = {"Sec-Fetch-Site": "cross-site"}
        self.assertEqual(phone.get("/api/status", headers=cross).status_code, 403)
        self.assertEqual(phone.post("/api/lan/pair", json={"code": "1"}, headers=cross).status_code, 403)

    def test_pc_lists_and_revokes_devices(self) -> None:
        phone = self.pair_phone("Pixel")
        info = self.pc.get("/api/lan/info").json()
        self.assertTrue(info["enabled"])
        self.assertEqual(info["urls"], [PHONE_URL])
        self.assertEqual([d["name"] for d in info["devices"]], ["Pixel"])
        self.assertNotIn("token_hash", json.dumps(info))
        after = self.pc.delete(f"/api/lan/devices/{info['devices'][0]['id']}").json()
        self.assertEqual(after["devices"], [])
        self.assertEqual(phone.get("/api/status").status_code, 401)
        self.assertEqual(phone.get("/api/camera/snapshot").status_code, 401)
        self.assertFalse(phone.get("/api/lan/me").json()["paired"])
        self.assertEqual(self.pc.delete("/api/lan/devices/nenhum").status_code, 404)

    def test_revoking_cuts_the_running_camera_feed(self) -> None:
        phone = self.pair_phone()
        device_id = self.registry.devices()[0]["id"]
        threading.Timer(0.3, self.registry.revoke, args=(device_id,)).start()
        safety = threading.Timer(4, self.hub.off)
        safety.start()
        self.addCleanup(safety.cancel)
        started = time.monotonic()
        response = phone.get("/api/camera/stream")
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content.split(b"--frame\r\n")), 2)
        self.assertTrue(self._wait(lambda: self.hub.state()["users"] == 0))

    def test_pair_url_and_qr_for_the_pc(self) -> None:
        info = self.pc.post("/api/lan/pairing").json()
        self.assertEqual(info["pair_url"], f"{PHONE_URL}/#parear={info['code']}")
        qr = self.pc.get("/api/lan/qr.svg")
        self.assertEqual(qr.status_code, 200)
        self.assertIn("<svg", qr.text)
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', qr.text)  # vale como arquivo de imagem
        cancelled = self.pc.delete("/api/lan/pairing").json()
        self.assertIsNone(cancelled["code"])
        self.assertEqual(self.pc.get("/api/lan/qr.svg").status_code, 404)

    def test_management_refuses_dns_rebinding(self) -> None:
        rebinding = TestClient(self.app, base_url="http://evil.example:8000")
        self.assertEqual(rebinding.post("/api/lan/pairing").status_code, 403)
        self.assertEqual(rebinding.get("/api/lan/info").status_code, 403)

    def test_pairing_needs_lan_mode(self) -> None:
        self.app.state.lan_urls = []
        self.assertEqual(self.pc.post("/api/lan/pairing").status_code, 409)
        self.assertFalse(self.pc.get("/api/lan/info").json()["enabled"])

    def test_ca_certificate_download_is_public(self) -> None:
        self.assertEqual(self.phone().get("/api/lan/ca.crt").status_code, 404)
        directory = Path(tempfile.mkdtemp())
        self.app.state.tls = ensure_certificates(["192.168.0.5"], directory, hostname="jarvis-pc")
        response = self.phone().get("/api/lan/ca.crt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/x-x509-ca-cert")
        self.assertIn(b"BEGIN CERTIFICATE", response.content)
        self.assertNotIn(b"PRIVATE", response.content)

    @staticmethod
    def _wait(condition, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.01)
        return condition()


class WakeHubPhoneTests(unittest.TestCase):
    def test_wake_heard_by_the_pc_never_goes_to_the_phone(self) -> None:
        hub = WakeHub()
        hub.connect("pc-aba-0001")
        phone = hub.connect("celular-0001", local=False)
        self.assertEqual(hub.trigger(0.9), {"accepted": True, "opened_browser": False})
        self.assertTrue(phone.queue.empty())

    def test_only_the_phone_open_opens_the_pc_browser(self) -> None:
        hub = WakeHub()
        phone = hub.connect("celular-0001", local=False)
        self.assertEqual(hub.trigger(0.9), {"accepted": True, "opened_browser": True})
        self.assertTrue(phone.queue.empty())

    def test_phone_microphone_does_not_steer_the_detector(self) -> None:
        hub = WakeHub()
        hub.connect("pc-aba-0001")
        hub.connect("celular-0001", local=False)
        hub.update("pc-aba-0001", session_active=False, visible=True, mic_label="Headset (Redmi)")
        hub.update("celular-0001", session_active=False, visible=True, mic_label="Microfone do iPhone")
        self.assertEqual(hub.mic_label, "Headset (Redmi)")


class CertificateTests(unittest.TestCase):
    def test_ca_is_constrained_and_signs_the_server_certificate(self) -> None:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec

        directory = Path(tempfile.mkdtemp())
        files = ensure_certificates(["192.168.0.5"], directory, hostname="Jarvis-PC")
        ca = x509.load_pem_x509_certificate(files.ca_cert.read_bytes())
        cert = x509.load_pem_x509_certificate(files.cert.read_bytes())

        constraints = ca.extensions.get_extension_for_class(x509.NameConstraints)
        self.assertTrue(constraints.critical)
        permitted = {str(name.value) for name in constraints.value.permitted_subtrees}
        self.assertIn("192.168.0.0/16", permitted)
        self.assertIn("local", permitted)
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)

        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertIn(ipaddress.ip_address("192.168.0.5"), san.get_values_for_type(x509.IPAddress))
        self.assertIn("jarvis-pc.local", san.get_values_for_type(x509.DNSName))
        self.assertEqual(cert.issuer, ca.subject)
        ca.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        self.assertLessEqual(cert.not_valid_after_utc - cert.not_valid_before_utc, dt.timedelta(days=825))

    def test_new_ip_reissues_only_the_server_certificate(self) -> None:
        directory = Path(tempfile.mkdtemp())
        first = ensure_certificates(["192.168.0.5"], directory, hostname="pc")
        ca_before, cert_before = first.ca_cert.read_bytes(), first.cert.read_bytes()
        ensure_certificates(["192.168.0.5"], directory, hostname="pc")
        self.assertEqual(first.cert.read_bytes(), cert_before)
        ensure_certificates(["192.168.0.77"], directory, hostname="pc")
        self.assertEqual(first.ca_cert.read_bytes(), ca_before)  # o celular continua confiando
        self.assertNotEqual(first.cert.read_bytes(), cert_before)


if __name__ == "__main__":
    unittest.main()
