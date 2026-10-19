from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import presence
from camera import CameraError
from presence import (
    CAMERA_OFF,
    INPUT_GRACE_S,
    OwnerProfile,
    Presence,
    PresenceMachine,
    PresenceService,
    Sighting,
    Tuning,
    build_welcome_instruction,
    human_minutes,
)
from server import PRESENCE_TOOL_NAMES, create_app
from settings import SettingsError, load_settings
from wake_hub import WakeHub

TUNING = Tuning(arrive_s=1.5, gap_s=1.2, leave_s=20.0, away_s=300.0, welcome_s=120.0)
CAMERA_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "JARVIS_ENABLE_CAMERA": "true",
    "JARVIS_PRESENCE": "true",
}


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def run(machine: PresenceMachine, clock: Clock, seconds: float, face: bool, active: bool = False, step: float = 0.5):
    """Feeds the machine at ~2 fps for `seconds` and returns every event."""
    events = []
    end = clock.now + seconds
    while clock.now < end - 1e-9:
        clock.now += step
        events += machine.observe(face, active, clock.now)
    return events


class PresenceMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.machine = PresenceMachine(TUNING, self.clock())

    def settle_present(self) -> None:
        events = run(self.machine, self.clock, 2, face=True)
        self.assertEqual([event.kind for event in events], ["arrived"])
        self.assertIsNone(events[0].away_s)  # a primeira vez não é "voltou"

    def test_a_glimpse_is_not_an_arrival(self) -> None:
        self.settle_present()
        run(self.machine, self.clock, 60, face=False)
        self.assertIs(self.machine.state, Presence.AWAY)

        for _ in range(3):  # passou na frente da câmera e foi embora
            events = run(self.machine, self.clock, 1.0, face=True) + run(self.machine, self.clock, 3, face=False)
            self.assertEqual(events, [])
        self.assertIs(self.machine.state, Presence.AWAY)

    def test_short_detector_misses_do_not_reset_the_arrival(self) -> None:
        self.settle_present()
        run(self.machine, self.clock, 200, face=False)
        events = []
        for face in [True, True, False, True, True, False, True]:  # rosto de lado de vez em quando
            self.clock.now += 0.5
            events += self.machine.observe(face, False, self.clock.now)
        self.assertEqual([event.kind for event in events], ["arrived"])

    def test_leaves_only_after_leave_s_without_anything(self) -> None:
        self.settle_present()
        last_seen = self.clock.now
        self.assertEqual(run(self.machine, self.clock, 19, face=False), [])
        self.assertIs(self.machine.state, Presence.PRESENT)

        events = run(self.machine, self.clock, 2, face=False)
        self.assertEqual([event.kind for event in events], ["left"])
        self.assertEqual(events[0].at, last_seen)  # a saída conta da última vez que foi visto
        self.assertEqual(self.machine.since, last_seen)

    def test_looking_at_the_side_monitor_while_typing_keeps_him_present(self) -> None:
        self.settle_present()
        self.assertEqual(run(self.machine, self.clock, 120, face=False, active=True), [])
        self.assertIs(self.machine.state, Presence.PRESENT)

    def test_a_face_flicker_while_present_does_not_leave(self) -> None:
        self.settle_present()
        for _ in range(10):
            self.assertEqual(run(self.machine, self.clock, 15, face=False) + run(self.machine, self.clock, 0.5, face=True), [])
        self.assertIs(self.machine.state, Presence.PRESENT)

    def test_keyboard_alone_does_not_bring_him_back(self) -> None:
        self.settle_present()
        run(self.machine, self.clock, 60, face=False)
        self.assertEqual(run(self.machine, self.clock, 60, face=False, active=True), [])
        self.assertIs(self.machine.state, Presence.AWAY)

    def test_away_long_fires_once_counting_from_the_departure(self) -> None:
        self.settle_present()
        left_at = self.clock.now
        events = run(self.machine, self.clock, 299, face=False)
        self.assertEqual([event.kind for event in events], ["left"])

        events = run(self.machine, self.clock, 600, face=False)
        self.assertEqual([event.kind for event in events], ["away_long"])
        self.assertAlmostEqual(events[0].at - left_at, 300, delta=0.6)

    def test_returning_reports_how_long_he_was_away(self) -> None:
        self.settle_present()
        left_at = self.clock.now
        run(self.machine, self.clock, 600, face=False)
        events = run(self.machine, self.clock, 2, face=True)

        self.assertEqual([event.kind for event in events], ["arrived"])
        self.assertAlmostEqual(events[0].away_s, 600, delta=1)
        self.assertGreater(events[0].at, left_at)
        self.assertIs(self.machine.state, Presence.PRESENT)

        # Sai de novo: o "away_long" volta a valer para a nova ausência.
        events = run(self.machine, self.clock, 400, face=False)
        self.assertEqual([event.kind for event in events], ["left", "away_long"])

    def test_starting_with_nobody_counts_as_away_from_the_start(self) -> None:
        events = run(self.machine, self.clock, 30, face=False)
        self.assertEqual([event.kind for event in events], ["left"])
        self.assertIs(self.machine.state, Presence.AWAY)

    def test_starting_while_typing_is_present_without_a_face(self) -> None:
        events = run(self.machine, self.clock, 1, face=False, active=True)
        self.assertEqual([event.kind for event in events], ["arrived"])


class FakeSystem:
    def __init__(self) -> None:
        self.idle: float | None = 999.0
        self.is_locked = False
        self.playing = True
        self.paused = 0
        self.locks = 0

    def idle_seconds(self) -> float | None:
        return self.idle

    def locked(self) -> bool:
        return self.is_locked

    def pause_media(self) -> bool:
        if not self.playing:
            return False
        self.playing = False
        self.paused += 1
        return True

    def lock(self) -> None:
        self.locks += 1
        self.is_locked = True


ME = Sighting(faces=1)
NOBODY = Sighting(faces=0)


class PresenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.system = FakeSystem()
        self.welcomes: list[float] = []
        self.service = PresenceService(lock=True, system=self.system, clock=self.clock, tuning=TUNING)
        self.service.on_welcome = lambda: self.welcomes.append(self.clock.now)

    def feed(self, sighting: Sighting, seconds: float) -> list[str]:
        kinds = []
        end = self.clock.now + seconds
        while self.clock.now < end - 1e-9:
            self.clock.now += 0.5
            kinds += [event.kind for event in self.service.tick(sighting)]
        return kinds

    def test_welcome_back_with_what_happened_while_away(self) -> None:
        self.feed(ME, 5)
        left_at = self.clock.now
        # Um timer criado antes de sair termina no meio da ausência (anotado com horário futuro).
        self.service.journal.add("o timer 'macarrão' terminou às 12:10", left_at + 200)
        self.service.journal.add("lembrete de antes", left_at - 100)
        self.feed(NOBODY, 600)
        self.assertEqual(self.welcomes, [])
        self.system.is_locked = False  # já desbloqueou

        self.feed(ME, 3)

        self.assertEqual(len(self.welcomes), 1)
        welcome = self.service.consume_welcome()
        self.assertIsNotNone(welcome)
        self.assertAlmostEqual(welcome.away_s, 600, delta=1)
        self.assertEqual(welcome.notes[0], "o timer 'macarrão' terminou às 12:10")
        self.assertTrue(any("pausei a mídia" in note for note in welcome.notes))
        self.assertTrue(any("bloqueei o computador" in note for note in welcome.notes))
        self.assertNotIn("lembrete de antes", welcome.notes)
        self.assertIsNone(self.service.consume_welcome())  # uma conversa só

    def test_no_welcome_after_a_short_break(self) -> None:
        self.feed(ME, 5)
        self.feed(NOBODY, 60)
        self.feed(ME, 3)
        self.assertEqual(self.welcomes, [])
        self.assertIsNone(self.service.consume_welcome())

    def test_away_long_pauses_media_and_locks_once(self) -> None:
        self.feed(ME, 5)
        kinds = self.feed(NOBODY, 1200)
        self.assertEqual(kinds, ["left", "away_long"])
        self.assertEqual((self.system.paused, self.system.locks), (1, 1))

    def test_lock_can_be_turned_off_by_voice(self) -> None:
        self.assertIn("não vou bloquear", presence.voice_action(self.service, "lock_off"))
        self.feed(ME, 5)
        self.feed(NOBODY, 400)
        self.assertEqual((self.system.paused, self.system.locks), (1, 0))

    def test_nothing_playing_means_no_media_key(self) -> None:
        self.system.playing = False
        self.feed(ME, 5)
        self.feed(NOBODY, 400)
        self.assertEqual(self.system.paused, 0)
        notes = [note.text for note in self.service.journal.between(0, self.clock.now)]
        self.assertFalse(any("mídia" in note for note in notes))

    def test_welcome_waits_for_the_screen_to_be_unlocked(self) -> None:
        self.feed(ME, 5)
        self.feed(NOBODY, 600)  # bloqueou
        self.assertTrue(self.system.is_locked)
        self.feed(ME, 30)  # chegou e está digitando a senha
        self.assertEqual(self.welcomes, [])
        self.assertIsNone(self.service.consume_welcome())

        self.system.is_locked = False
        self.feed(ME, 1)
        self.assertEqual(len(self.welcomes), 1)
        self.assertIsNotNone(self.service.consume_welcome())

    def test_unused_welcome_expires(self) -> None:
        self.feed(ME, 5)
        self.feed(NOBODY, 600)
        self.system.is_locked = False
        self.feed(ME, 3)
        self.feed(ME, presence.WELCOME_TTL_S + 5)
        self.assertIsNone(self.service.consume_welcome())

    def test_input_keeps_him_present(self) -> None:
        self.feed(ME, 5)
        self.system.idle = INPUT_GRACE_S - 5
        self.assertEqual(self.feed(NOBODY, 120), [])

    def test_recognized_owner_and_strangers(self) -> None:
        owner = Sighting(faces=1, owner=True, similarity=0.8)
        stranger = Sighting(faces=1, owner=False, similarity=0.1)
        self.service.set_lock(False)
        self.feed(owner, 5)
        self.feed(NOBODY, 200)
        self.assertEqual(self.feed(stranger, 30), [])  # outra pessoa sentou: não é "chegou"
        self.assertIsNone(self.service.consume_welcome())
        self.feed(NOBODY, 400)
        self.feed(stranger, 5)  # a anotação anterior tem mais de 5 min: anota de novo
        self.assertEqual(self.feed(owner, 3), ["arrived"])

        welcome = self.service.consume_welcome()
        strangers = [note for note in welcome.notes if "não reconheci" in note]
        self.assertEqual(len(strangers), 2)

    def test_state_for_the_hud(self) -> None:
        state = self.service.state()
        self.assertFalse(state["running"])
        self.assertEqual(state["state"], "off")
        self.assertTrue(state["lock"])
        self.assertEqual(state["away_minutes"], 5.0)


class FakeSensor:
    recognizes = False

    def __init__(self) -> None:
        self.closed = False

    def look(self, frame: np.ndarray) -> Sighting:
        return Sighting(faces=int(frame.mean() > 0))

    def close(self) -> None:
        self.closed = True


def frames(*values: int):
    for value in values:
        frame = np.full((72, 128, 3), value, dtype=np.uint8)
        frame.setflags(write=False)
        yield frame


class PresenceThreadTests(unittest.TestCase):
    def test_runs_on_hub_frames_and_stops_when_the_camera_is_turned_off(self) -> None:
        clock = Clock()
        sensor = FakeSensor()
        seen: list[float] = []

        def ticking() -> float:  # cada leitura do relógio avança meio segundo
            clock.now += 0.5
            seen.append(clock.now)
            return clock.now

        service = PresenceService(
            frames_factory=lambda: frames(*([255] * 6)),
            sensor_factory=lambda: sensor,
            system=FakeSystem(),
            clock=ticking,
            interval=0,
            tuning=TUNING,
        )
        service.start()
        service._thread.join(5)

        state = service.state()
        self.assertFalse(state["running"])
        self.assertTrue(state["camera_off"])
        self.assertEqual(state["error"], CAMERA_OFF)
        self.assertIs(service.machine.state, Presence.PRESENT)
        self.assertTrue(sensor.closed)
        self.assertIn("já estava desligada", service.stop())

    def test_busy_camera_is_retried(self) -> None:
        attempts: list[int] = []
        stop_after = threading.Event()

        def factory():
            attempts.append(1)
            if len(attempts) == 1:
                raise CameraError("A webcam está em uso por outro programa.")
            stop_after.set()
            return frames(255)

        service = PresenceService(
            frames_factory=factory, sensor_factory=FakeSensor, system=FakeSystem(), interval=0, retry_s=0.01, tuning=TUNING
        )
        service.start()
        self.assertTrue(stop_after.wait(5))
        service.stop()
        self.assertGreaterEqual(len(attempts), 2)

    def test_error_is_reported_while_retrying(self) -> None:
        service = PresenceService(
            frames_factory=lambda: (_ for _ in ()).throw(CameraError("Nenhuma webcam encontrada.")),
            sensor_factory=FakeSensor,
            system=FakeSystem(),
            retry_s=30,
            tuning=TUNING,
        )
        service.start()
        try:
            for _ in range(100):
                if service.state()["error"]:
                    break
                threading.Event().wait(0.01)
            self.assertEqual(service.state()["error"], "Nenhuma webcam encontrada.")
            self.assertIn("não está disponível", service.describe())
        finally:
            service.stop()


class WindowsSystemTests(unittest.TestCase):
    def test_media_key_only_when_something_is_playing(self) -> None:
        system = presence.WindowsSystem()
        with patch("pc_control.press_media_key") as press:
            with patch.object(system, "_audio_peak", return_value=0.0):
                self.assertFalse(system.pause_media())
            press.assert_not_called()  # play/pause alterna: sem som, daria play
            with patch.object(system, "_audio_peak", return_value=0.4):
                self.assertTrue(system.pause_media())
            press.assert_called_once_with("play_pause")

    def test_lock_uses_pc_control(self) -> None:
        with patch("pc_control.lock_workstation") as lock:
            presence.WindowsSystem().lock()
        lock.assert_called_once_with()

    def test_null_system_outside_windows(self) -> None:
        system = presence.NullSystem()
        self.assertIsNone(system.idle_seconds())
        self.assertFalse(system.pause_media())
        with self.assertRaises(RuntimeError):
            system.lock()


class OwnerProfileTests(unittest.TestCase):
    def test_matches_the_owner_and_not_someone_else(self) -> None:
        rng = np.random.default_rng(3)
        me, other = rng.normal(size=128), rng.normal(size=128)
        samples = [me + rng.normal(scale=0.3, size=128) for _ in range(12)]
        profile = OwnerProfile.from_samples(samples)

        self.assertTrue(profile.matches(me + rng.normal(scale=0.3, size=128)))
        self.assertFalse(profile.matches(other))

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "presenca_rosto.json"
            profile.save(path)
            loaded = OwnerProfile.load(path)
            self.assertNotIn("image", path.read_text(encoding="utf-8"))
        self.assertEqual(loaded.embeddings.shape, profile.embeddings.shape)
        self.assertAlmostEqual(loaded.similarity(me), profile.similarity(me), places=3)

    def test_rejects_mixed_people_and_missing_files(self) -> None:
        rng = np.random.default_rng(4)
        with self.assertRaises(ValueError):
            OwnerProfile.from_samples([rng.normal(size=128) for _ in range(10)])
        with self.assertRaises(ValueError):
            OwnerProfile.from_samples([rng.normal(size=128)])
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(OwnerProfile.load(Path(folder) / "nada.json"))
            broken = Path(folder) / "ruim.json"
            broken.write_text('{"model": "outro", "embeddings": [[1, 2]]}', encoding="utf-8")
            self.assertIsNone(OwnerProfile.load(broken))


class WelcomeTextTests(unittest.TestCase):
    def test_instruction_has_the_greeting_and_the_summary(self) -> None:
        text = build_welcome_instruction(1260, ["o timer 'chá' terminou às 15:02", "pausei a mídia"])
        self.assertIn("Bem-vindo de volta, senhor.", text)
        self.assertIn("21 minutos", text)
        self.assertIn("o timer 'chá' terminou às 15:02; pausei a mídia", text)

        quiet = build_welcome_instruction(200, [])
        self.assertIn("Nada foi registrado", quiet)

    def test_human_minutes(self) -> None:
        self.assertEqual(human_minutes(30), "menos de um minuto")
        self.assertEqual(human_minutes(60), "1 minuto")
        self.assertEqual(human_minutes(3600), "1 hora")
        self.assertEqual(human_minutes(3900), "1 hora e 5 min")


class PresenceSettingsTests(unittest.TestCase):
    def test_off_by_default(self) -> None:
        settings = load_settings({})
        self.assertFalse(settings.presence_enabled)
        self.assertFalse(settings.presence_lock)
        self.assertEqual(settings.presence_away_minutes, 5)

    def test_parses_options(self) -> None:
        settings = load_settings(
            {"JARVIS_PRESENCE": "true", "JARVIS_PRESENCE_AWAY_MINUTES": "2,5", "JARVIS_PRESENCE_LOCK": "yes"}
        )
        self.assertTrue(settings.presence_enabled)
        self.assertTrue(settings.presence_lock)
        self.assertEqual(settings.presence_away_minutes, 2.5)
        with self.assertRaises(SettingsError):
            load_settings({"JARVIS_PRESENCE_AWAY_MINUTES": "0"})


class PresenceServerTests(unittest.TestCase):
    def make(self, env: dict[str, str]) -> tuple[TestClient, PresenceService, list[str]]:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = Clock()
        self.system = FakeSystem()
        service = PresenceService(
            frames_factory=lambda: iter(()),
            sensor_factory=FakeSensor,
            system=self.system,
            clock=self.clock,
            tuning=TUNING,
        )
        opened: list[str] = []
        app = create_app(reload_env=False, presence_service=service, open_browser=opened.append)
        return TestClient(app, base_url="http://127.0.0.1"), service, opened

    def test_status_and_tools_follow_the_setting(self) -> None:
        client, _, _ = self.make(CAMERA_ENV)
        body = client.get("/api/status").json()
        self.assertTrue(body["presence"])
        self.assertEqual(body["tools"][-len(PRESENCE_TOOL_NAMES) :], PRESENCE_TOOL_NAMES)

        client, _, _ = self.make({"GOOGLE_API_KEY": "k"})
        body = client.get("/api/status").json()
        self.assertFalse(body["presence"])
        self.assertNotIn("presence_control", body["tools"])

    def test_disabled_presence_refuses_voice_actions(self) -> None:
        client, _, _ = self.make({"GOOGLE_API_KEY": "k"})
        self.assertFalse(client.get("/api/presence").json()["enabled"])
        response = client.post("/api/presence", json={"action": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("JARVIS_PRESENCE=true", response.json()["detail"])

    def test_presence_needs_the_camera(self) -> None:
        client, service, _ = self.make({"GOOGLE_API_KEY": "k", "JARVIS_PRESENCE": "true"})
        with client:
            self.assertFalse(service.running)
            state = client.get("/api/presence").json()
            self.assertIn("JARVIS_ENABLE_CAMERA=true", state["error"])
            self.assertEqual(client.post("/api/presence", json={"action": "on"}).status_code, 403)

    def test_voice_actions(self) -> None:
        client, service, _ = self.make(CAMERA_ENV)
        reply = client.post("/api/presence", json={"action": "lock_on"}).json()
        self.assertIn("bloqueio o computador", reply["message"])
        self.assertTrue(reply["lock"])
        reply = client.post("/api/presence", json={"action": "lock_off"}).json()
        self.assertFalse(reply["lock"])
        self.assertIn("desligada", client.post("/api/presence", json={"action": "status"}).json()["message"])
        self.assertEqual(client.post("/api/presence", json={"action": "explode"}).status_code, 422)

    def test_lifespan_starts_and_stops_the_service(self) -> None:
        client, service, _ = self.make(CAMERA_ENV)
        with client:
            service._thread.join(2)  # sem quadros: a câmera "foi desligada"
            self.assertTrue(service.state()["camera_off"])
        self.assertFalse(service.running)

    def test_notes_and_welcome_endpoints(self) -> None:
        client, service, _ = self.make(CAMERA_ENV)
        self.assertEqual(client.get("/api/presence/welcome").json(), {"welcome": None})
        client.post("/api/presence/note", json={"text": "o timer 'pão' terminou às 10:00", "at": self.clock.now + 10})
        self.assertEqual(client.post("/api/presence/note", json={"text": ""}).status_code, 422)

        for _ in range(10):
            self.clock.now += 0.5
            service.tick(ME)
        for _ in range(1200):
            self.clock.now += 0.5
            service.tick(NOBODY)
        for _ in range(4):
            self.clock.now += 0.5
            service.tick(ME)

        welcome = client.get("/api/presence/welcome").json()["welcome"]
        self.assertAlmostEqual(welcome["away_s"], 600, delta=1)
        self.assertIn("o timer 'pão' terminou às 10:00", welcome["notes"])
        self.assertEqual(client.get("/api/presence/welcome").json(), {"welcome": None})

    def test_rejects_other_sites(self) -> None:
        client, _, _ = self.make(CAMERA_ENV)
        response = client.get("/api/presence", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)

    def test_arrival_opens_the_link_like_the_wake_word(self) -> None:
        client, service, opened = self.make(CAMERA_ENV)
        with client:
            hub: WakeHub = client.app.state.wake_hub
            hud = hub.connect("tab-12345678")
            service._thread.join(2)
            for _ in range(10):
                self.clock.now += 0.5
                service.tick(ME)
            for _ in range(400):
                self.clock.now += 0.5
                service.tick(NOBODY)
            for _ in range(4):
                self.clock.now += 0.5
                service.tick(ME)
            client.get("/api/status")  # deixa o loop do servidor rodar o agendamento
            event = None
            for _ in range(50):
                if not hud.queue.empty():
                    event = hud.queue.get_nowait()
                    break
                client.get("/api/presence")
            self.assertEqual(event, {"type": "wake", "score": 1.0, "reason": "presence"})
            self.assertEqual(opened, [])


class WakeReasonTests(unittest.TestCase):
    def test_reason_reaches_a_tab_that_opens_later(self) -> None:
        hub = WakeHub(clock=Clock())
        self.assertEqual(hub.trigger(1.0, reason="presence"), {"accepted": True, "opened_browser": True})
        client = hub.connect("tab-12345678")
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 1.0, "reason": "presence"})


class AgentSideTests(unittest.TestCase):
    def test_disabled_presence_makes_no_requests(self) -> None:
        with patch.dict(os.environ, {"JARVIS_PRESENCE": "false"}), patch.object(presence, "presence_request") as request:
            self.assertIsNone(asyncio.run(presence.welcome_instruction()))
            asyncio.run(presence.note_soon("algo"))
        request.assert_not_called()

    def test_welcome_instruction_from_the_server(self) -> None:
        reply = {"welcome": {"away_s": 900, "notes": ["o timer 'bolo' terminou às 16:00"]}}
        with patch.dict(os.environ, {"JARVIS_PRESENCE": "true"}), patch.object(presence, "presence_request", return_value=reply):
            text = asyncio.run(presence.welcome_instruction())
        self.assertIn("Bem-vindo de volta, senhor.", text)
        self.assertIn("15 minutos", text)
        self.assertIn("bolo", text)

    def test_server_offline_falls_back_to_the_normal_greeting(self) -> None:
        def offline(*_args, **_kwargs):
            raise presence.PresenceUnavailable("offline")

        with patch.dict(os.environ, {"JARVIS_PRESENCE": "true"}), patch.object(presence, "presence_request", offline):
            self.assertIsNone(asyncio.run(presence.welcome_instruction()))
            asyncio.run(presence.note_soon("algo"))  # não levanta

    def test_tool_is_registered_only_when_enabled(self) -> None:
        from tools import build_tools

        names = [tool.__name__ for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_PRESENCE": "true"}))]
        self.assertIn("presence_control", names)
        names = [tool.__name__ for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k"}))]
        self.assertNotIn("presence_control", names)


@unittest.skipUnless(
    all(model[2].exists() for model in (presence.DETECTOR_MODEL,)), "modelo do MediaPipe não baixado (.cache/models)"
)
class RealDetectorTests(unittest.TestCase):
    def test_blank_frame_has_no_face(self) -> None:
        try:
            sensor = presence.FaceSensor(None)
        except OSError as exc:  # sem libEGL na máquina de testes
            self.skipTest(str(exc))
        try:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame.setflags(write=False)
            self.assertEqual(sensor.look(frame), Sighting(faces=0))
        finally:
            sensor.close()


if __name__ == "__main__":
    unittest.main()
