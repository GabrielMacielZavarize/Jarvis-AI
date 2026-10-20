from __future__ import annotations

import asyncio
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import personas
from personas import (
    DEFAULT_PERSONA,
    PERSONAS,
    apply_persona,
    greeting,
    load_persona,
    save_persona,
    saved_persona,
    swap_persona,
    wait_quiet,
    watch_persona,
)
from prompts import AGENT_INSTRUCTION, build_agent_instructions, build_initial_reply_instruction, greeting_for


class PersonaFileTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "persona.json"

    def test_nobody_chose_yet_means_jarvis(self) -> None:
        self.assertIsNone(saved_persona(self.path))
        self.assertEqual(load_persona(self.path).id, DEFAULT_PERSONA)

    def test_saved_choice_and_unknown_or_broken_files(self) -> None:
        save_persona("friday", self.path)
        self.assertEqual(saved_persona(self.path), "friday")
        self.assertEqual(load_persona(self.path).name, "F.R.I.D.A.Y.")
        self.path.write_text('{"persona": "ultron"}', encoding="utf-8")
        self.assertIsNone(saved_persona(self.path))
        self.path.write_text("{quebrado", encoding="utf-8")
        self.assertEqual(load_persona(self.path).id, "jarvis")
        with self.assertRaises(ValueError):
            save_persona("ultron", self.path)

    def test_every_hud_theme_is_a_persona(self) -> None:
        from tools import HUD_THEME_NAMES

        self.assertEqual(set(PERSONAS), set(HUD_THEME_NAMES))


class PersonaPromptTests(unittest.TestCase):
    def test_jarvis_prompt_is_unchanged(self) -> None:
        self.assertTrue(AGENT_INSTRUCTION.startswith(PERSONAS["jarvis"].prompt))
        self.assertEqual(build_agent_instructions(), AGENT_INSTRUCTION)

    def test_each_persona_has_its_own_style_and_the_same_rules(self) -> None:
        friday = build_agent_instructions(home_city="Criciúma", persona=PERSONAS["friday"])
        self.assertIn("Você é F.R.I.D.A.Y.", friday)
        self.assertIn('"chefe"', friday)
        self.assertNotIn("mordomo digital britânico de Tony Stark", friday)
        # Tools and safety rules are shared by every persona.
        self.assertIn("chame end_session", friday)
        self.assertIn("O usuário mora em Criciúma", friday)
        self.assertIn("SEU jeito", friday)
        self.assertIn('"em missão"', build_agent_instructions(persona=PERSONAS["mark3"]))
        self.assertIn("modo discreto", build_agent_instructions(persona=PERSONAS["stealth"]))

    def test_greetings_follow_the_persona(self) -> None:
        morning = dt.datetime(2026, 1, 1, 8)
        self.assertEqual(greeting_for(morning), "Bom dia, senhor. Todos os sistemas estão online. Em que posso ajudar?")
        self.assertEqual(greeting(PERSONAS["friday"], morning), "Bom dia, chefe. F.R.I.D.A.Y. na escuta. O que vamos fazer hoje?")
        self.assertIn("Mark III online", greeting_for(dt.datetime(2026, 1, 1, 22), PERSONAS["mark3"]))
        self.assertIn('"Modo discreto. Pode falar."', build_initial_reply_instruction(morning, PERSONAS["stealth"]))

    def test_swap_keeps_memories_and_context(self) -> None:
        jarvis = build_agent_instructions(memories="- [Perfil] Meu nome é Gabriel", persona=PERSONAS["jarvis"])
        friday = swap_persona(jarvis, PERSONAS["jarvis"], PERSONAS["friday"])
        self.assertIn("Você é F.R.I.D.A.Y.", friday)
        self.assertNotIn("Você é J.A.R.V.I.S., a inteligência", friday)
        self.assertIn("Meu nome é Gabriel", friday)
        self.assertEqual(swap_persona(friday, PERSONAS["friday"], PERSONAS["jarvis"]), jarvis)
        # Built for another persona than the one assumed: still swapped, never doubled.
        mark3 = swap_persona(friday, PERSONAS["jarvis"], PERSONAS["mark3"])
        self.assertEqual(mark3.count("# Persona"), 1)
        self.assertIn("armadura Mark III", mark3)


class FakeSession:
    def __init__(self, states: list[tuple[str, str]] | None = None) -> None:
        self._states = list(states or [])
        self.agent_state = "listening"
        self.user_state = "listening"
        self.generate_reply = MagicMock()

    def advance(self) -> None:
        if self._states:
            self.agent_state, self.user_state = self._states.pop(0)


class QuietTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_the_confirmation_to_be_spoken(self) -> None:
        session = FakeSession(
            [("thinking", "listening"), ("speaking", "listening"), ("speaking", "listening"), ("listening", "listening")]
        )
        steps = 0
        sleep = asyncio.sleep

        async def tick(_seconds: float) -> None:
            nonlocal steps
            steps += 1
            session.advance()
            await sleep(0)

        with patch("personas.asyncio.sleep", tick):
            await wait_quiet(session, settle=0.6, limit=10, step=0.2)
        # 3 busy steps, then 3 quiet ones to settle.
        self.assertEqual(steps, 6)
        self.assertEqual(session.agent_state, "listening")

    async def test_gives_up_after_the_limit(self) -> None:
        session = FakeSession()
        session.user_state = "speaking"
        with patch("personas.asyncio.sleep", AsyncMock()):
            await wait_quiet(session, settle=1, limit=1, step=0.25)


class FakeLiveModel:
    __module__ = "livekit.plugins.google.realtime.realtime_api"

    def __init__(self) -> None:
        self.update_options = MagicMock()


class ApplyPersonaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.voice_file = Path(folder.name) / "voz.json"
        patcher = patch("voices.VOICE_FILE", self.voice_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(personas.set_active, "jarvis")

    async def test_switches_instructions_voice_and_introduces_itself(self) -> None:
        llm = FakeLiveModel()
        session = FakeSession()
        agent = SimpleNamespace(
            instructions=build_agent_instructions(persona=PERSONAS["jarvis"]), update_instructions=AsyncMock(), llm=llm
        )
        session.current_agent = agent
        with patch("personas.wait_quiet", AsyncMock()), patch("personas.asyncio.sleep", AsyncMock()):
            await apply_persona(session, agent, PERSONAS["jarvis"], PERSONAS["friday"])

        new_instructions = agent.update_instructions.await_args.args[0]
        self.assertIn("Você é F.R.I.D.A.Y.", new_instructions)
        llm.update_options.assert_called_once_with(voice="Kore")
        self.assertIn("F.R.I.D.A.Y. assumindo", session.generate_reply.call_args.kwargs["instructions"])
        self.assertEqual(personas.active_persona(), "friday")

    async def test_watch_follows_the_file(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "persona.json"
        session = FakeSession()
        agent = SimpleNamespace()
        with patch("personas.apply_persona", AsyncMock()) as applied:
            task = watch_persona(session, lambda: agent, path=path, poll=0.01)
            await asyncio.sleep(0.03)
            save_persona("mark3", path)
            for _ in range(100):
                if applied.await_count:
                    break
                await asyncio.sleep(0.01)
            task.cancel()
        old, new = applied.await_args.args[2:4]
        self.assertEqual((old.id, new.id), ("jarvis", "mark3"))


class PersonaServerTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from server import create_app

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "persona.json"
        patcher = patch("personas.PERSONA_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app(reload_env=False), base_url="http://127.0.0.1")

    def test_post_saves_and_status_reports_it(self) -> None:
        self.assertIsNone(self.client.get("/api/persona").json()["persona"])
        response = self.client.post("/api/persona", json={"persona": "friday"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved_persona(self.path), "friday")
        self.assertEqual(self.client.get("/api/status").json()["persona"], "friday")

    def test_unknown_persona_and_other_sites_are_refused(self) -> None:
        self.assertEqual(self.client.post("/api/persona", json={"persona": "ultron"}).status_code, 400)
        cross = self.client.post("/api/persona", json={"persona": "mark3"}, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(cross.status_code, 403)
        self.assertIsNone(saved_persona(self.path))


if __name__ == "__main__":
    unittest.main()
