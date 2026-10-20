from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, patch

import voices
from settings import load_settings
from voices import (
    DEFAULT_VOICE,
    GEMINI_VOICES,
    RECOMMENDED_VOICES,
    build_voice_tools,
    canonical_voice,
    effective_voice,
    match_voice,
    save_voice,
    saved_voice,
)

from test_tools import FakeRunContext


class VoiceSettingsTests(unittest.TestCase):
    def test_default_is_the_calm_deep_voice(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "k"})
        self.assertEqual(settings.google_voice, "Charon")
        self.assertEqual(DEFAULT_VOICE, "Charon")
        self.assertEqual(RECOMMENDED_VOICES[0], "Charon")
        self.assertEqual(settings.backend_validation_errors(), [])

    def test_jarvis_voice_wins_over_google_voice_and_fixes_the_case(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "k", "GOOGLE_VOICE": "Puck", "JARVIS_VOICE": "orus"})
        self.assertEqual(settings.google_voice, "Orus")
        self.assertEqual(load_settings({"GOOGLE_VOICE": "Puck"}).google_voice, "Puck")

    def test_unknown_voice_is_a_configuration_error(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_VOICE": "Darth Vader"})
        errors = settings.backend_validation_errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("JARVIS_VOICE inválida: 'Darth Vader'", errors[0])
        self.assertIn("Charon", errors[0])

    def test_unknown_voice_is_fine_on_openai(self) -> None:
        settings = load_settings({"JARVIS_BACKEND": "openai-realtime", "OPENAI_API_KEY": "k", "JARVIS_VOICE": "x"})
        self.assertEqual(settings.backend_validation_errors(), [])

    def test_catalog_matches_the_voices_the_plugin_accepts(self) -> None:
        from livekit.plugins.google.realtime.api_proto import Voice

        self.assertEqual(set(GEMINI_VOICES), set(get_args(Voice)))
        self.assertTrue(set(RECOMMENDED_VOICES) <= set(GEMINI_VOICES))

    def test_backend_uses_the_effective_voice(self) -> None:
        from backends import build_backend_components

        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_VOICE": "Iapetus"})
        with (
            patch("backends.effective_voice", return_value="Orus") as chosen,
            patch("backends.load_persona", return_value=SimpleNamespace(id="jarvis")),
        ):
            components = build_backend_components(settings)
        chosen.assert_called_once_with("Iapetus", persona="jarvis")
        self.assertEqual(components.llm._opts.voice, "Orus")


class PersonaPromptTests(unittest.TestCase):
    def test_prompt_has_the_butler_tone_and_the_voice_tool(self) -> None:
        from prompts import AGENT_INSTRUCTION

        self.assertIn("mordomo britânico", AGENT_INSTRUCTION)
        self.assertIn('trate o usuário\n  por "senhor"', AGENT_INSTRUCTION)
        self.assertIn("Humor seco", AGENT_INSTRUCTION)
        self.assertIn("no máximo duas frases", AGENT_INSTRUCTION)
        self.assertIn("change_voice(set", AGENT_INSTRUCTION)
        self.assertIn("change_voice(list)", AGENT_INSTRUCTION)


class VoiceMatchingTests(unittest.TestCase):
    def test_canonical_names(self) -> None:
        self.assertEqual(canonical_voice("CHARON"), "Charon")
        self.assertEqual(canonical_voice(" zubenelgenubi "), "Zubenelgenubi")
        self.assertIsNone(canonical_voice("Jarvis"))
        self.assertIsNone(canonical_voice(None))

    def test_spoken_names_with_transcription_noise(self) -> None:
        self.assertEqual(match_voice("Óros"), "Orus")
        self.assertEqual(match_voice("a voz do Charon"), "Charon")
        self.assertEqual(match_voice("voz Iapetus"), "Iapetus")
        self.assertEqual(match_voice("Rasalgheti"), "Rasalgethi")
        self.assertIsNone(match_voice("banana"))
        self.assertIsNone(match_voice(""))


class VoiceFileTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "voz.json"

    def test_saved_choice_wins_and_reset_goes_back(self) -> None:
        self.assertIsNone(saved_voice(self.path))
        self.assertEqual(effective_voice("Iapetus", self.path), "Iapetus")
        save_voice("Orus", self.path)
        self.assertEqual(saved_voice(self.path), "Orus")
        self.assertEqual(effective_voice("Iapetus", self.path), "Orus")
        save_voice(None, self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(effective_voice(None, self.path), "Charon")
        save_voice(None, self.path)  # nada para apagar: sem erro

    def test_each_protocol_keeps_its_own_voice(self) -> None:
        # The other protocols start on their own voice, never on JARVIS_VOICE.
        self.assertEqual(effective_voice("Iapetus", self.path, persona="friday"), "Kore")
        self.assertEqual(effective_voice("Iapetus", self.path, persona="mark3"), "Orus")
        self.assertEqual(effective_voice("Iapetus", self.path, persona="stealth"), "Enceladus")
        save_voice("Aoede", self.path, persona="friday")
        save_voice("Orus", self.path)
        self.assertEqual(effective_voice("Iapetus", self.path, persona="friday"), "Aoede")
        self.assertEqual(effective_voice("Iapetus", self.path), "Orus")
        save_voice(None, self.path, persona="friday")
        self.assertEqual(effective_voice(None, self.path, persona="friday"), "Kore")
        self.assertEqual(saved_voice(self.path), "Orus")

    def test_old_single_voice_file_is_the_jarvis_choice(self) -> None:
        self.path.write_text('{"voice": "Orus"}', encoding="utf-8")
        self.assertEqual(saved_voice(self.path), "Orus")
        self.assertIsNone(saved_voice(self.path, persona="friday"))
        save_voice("Kore", self.path, persona="friday")
        self.assertEqual(saved_voice(self.path), "Orus")
        self.assertEqual(saved_voice(self.path, persona="friday"), "Kore")

    def test_broken_file_is_ignored(self) -> None:
        self.path.write_text("{não é json", encoding="utf-8")
        self.assertIsNone(saved_voice(self.path))
        self.path.write_text('{"voice": "Darth Vader"}', encoding="utf-8")
        self.assertEqual(effective_voice("Kore", self.path), "Kore")


class FakeLiveModel:
    """Stands in for livekit.plugins.google RealtimeModel (only its module name is checked)."""

    __module__ = "livekit.plugins.google.realtime.realtime_api"

    def __init__(self) -> None:
        self.update_options = MagicMock()


class ChangeVoiceToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "voz.json"
        for patcher in (
            patch.object(voices, "VOICE_FILE", self.path),
            patch("voices.tool_status", new=AsyncMock()),
            patch("voices.show_card", new=AsyncMock(return_value=True)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tool(self, env: dict[str, str] | None = None):
        (change_voice,) = build_voice_tools(load_settings({"GOOGLE_API_KEY": "k", **(env or {})}))
        return change_voice

    async def test_list_tells_current_and_recommended_voices(self) -> None:
        result = await self.tool()(FakeRunContext(), action="list")
        self.assertIn("Voz atual: Charon", result)
        self.assertIn("Orus", result)
        card = voices.show_card.await_args
        self.assertEqual(card.args[0], "note")
        self.assertIn("▶ Charon", card.args[1]["content"])

    async def test_set_saves_for_next_session_without_a_live_model(self) -> None:
        context = FakeRunContext()
        result = await self.tool()(context, action="set", voice="óros")
        self.assertIn("Voz Orus salva", result)
        self.assertIn("próxima conversa", result)
        self.assertEqual(saved_voice(self.path), "Orus")

    async def test_set_switches_live_after_the_reply(self) -> None:
        context = FakeRunContext()
        model = FakeLiveModel()
        context.session.llm = model
        callbacks = []
        context.speech_handle = SimpleNamespace(add_done_callback=callbacks.append)
        with patch("tools._tool_reply_is_new_speech", return_value=False):
            result = await self.tool()(context, action="set", voice="Iapetus")
        self.assertIn("A troca acontece assim que você terminar", result)
        model.update_options.assert_not_called()  # ainda falando a confirmação
        callbacks[0](None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        model.update_options.assert_called_once_with(voice="Iapetus")

    async def test_unknown_voice_changes_nothing(self) -> None:
        result = await self.tool()(FakeRunContext(), action="set", voice="Darth Vader")
        self.assertIn("Não existe a voz 'Darth Vader'", result)
        self.assertIsNone(saved_voice(self.path))

    async def test_same_voice_and_reset(self) -> None:
        tool = self.tool({"JARVIS_VOICE": "Orus"})
        self.assertIn("já está falando com a voz Orus", await tool(FakeRunContext(), action="set", voice="orus"))
        await tool(FakeRunContext(), action="set", voice="Puck")
        self.assertEqual(saved_voice(self.path), "Puck")
        result = await tool(FakeRunContext(), action="reset")
        self.assertIn("Voz Orus salva", result)
        self.assertFalse(self.path.exists())

    async def test_openai_backend_explains_instead_of_switching(self) -> None:
        (change_voice,) = build_voice_tools(load_settings({"JARVIS_BACKEND": "openai-realtime", "OPENAI_API_KEY": "k"}))
        result = await change_voice(FakeRunContext(), action="set", voice="Orus")
        self.assertIn("só funciona com o Gemini Live", result)
        self.assertIsNone(saved_voice(self.path))


if __name__ == "__main__":
    unittest.main()
