import unittest

from backends import build_backend_components
from settings import load_settings
from tools import build_tools


class BackendTests(unittest.TestCase):
    def test_gemini_backend_builds_realtime_components(self) -> None:
        settings = load_settings(
            {
                "JARVIS_BACKEND": "gemini-realtime",
                "GOOGLE_API_KEY": "test-key",
            }
        )

        components = build_backend_components(settings)

        self.assertTrue(components.is_realtime)
        self.assertEqual(type(components.llm).__name__, "RealtimeModel")
        self.assertIsNone(components.stt)
        self.assertIsNone(components.tts)

    def test_openai_realtime_backend_builds_realtime_components(self) -> None:
        settings = load_settings(
            {
                "JARVIS_BACKEND": "openai-realtime",
                "OPENAI_API_KEY": "test-key",
            }
        )

        components = build_backend_components(settings)

        self.assertTrue(components.is_realtime)
        self.assertEqual(type(components.llm).__name__, "RealtimeModel")

    def test_openai_compatible_backend_builds_pipeline_components(self) -> None:
        settings = load_settings(
            {
                "JARVIS_BACKEND": "openai-compatible-pipeline",
                "OPENAI_API_KEY": "test-key",
            }
        )

        components = build_backend_components(settings)

        self.assertFalse(components.is_realtime)
        self.assertEqual(type(components.llm).__name__, "LLM")
        self.assertEqual(type(components.stt).__name__, "STT")
        self.assertEqual(type(components.tts).__name__, "TTS")

    def test_email_tools_are_registered_only_when_enabled(self) -> None:
        disabled_settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
            }
        )
        enabled_settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
                "GMAIL_USER": "jarvis@example.com",
                "GMAIL_APP_PASSWORD": "secret",
            }
        )

        disabled_tools = build_tools(disabled_settings)
        enabled_tools = build_tools(enabled_settings)

        self.assertEqual(
            [tool.__name__ for tool in disabled_tools],
            ["get_weather", "search_web"],
        )
        self.assertEqual(
            [tool.__name__ for tool in enabled_tools],
            [
                "get_weather",
                "search_web",
                "draft_email",
                "confirm_email_send",
                "cancel_pending_email",
            ],
        )
