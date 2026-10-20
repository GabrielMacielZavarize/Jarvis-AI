import unittest

from backends import build_backend_components
from settings import load_settings
from tools import build_tools

BASE_TOOLS = [
    "get_weather",
    "search_web",
    "search_news",
    "get_current_time",
    "run_diagnostics",
    "set_timer",
    "get_timers",
    "show_on_hud",
    "manage_hud_panels",
    "set_hud_appearance",
    "check_microphone",
    "end_session",
    "change_voice",
    "remember",
    "recall",
    "forget",
    "diary_lookup",
    "forget_diary",
    "list_routines",
    "run_routine",
    "confirm_routine_step",
    "save_routine",
    "delete_routine",
    "schedule_routine",
]


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

    def test_gemini_session_survives_long_links_and_honors_the_turn_settings(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key", "JARVIS_END_OF_SPEECH_MS": "600"})

        opts = build_backend_components(settings, "gemini-3.1-flash-live-preview").llm._opts

        self.assertEqual(opts.model, "gemini-3.1-flash-live-preview")
        # Without compression Gemini Live ends audio sessions after ~15 min.
        self.assertIsNotNone(opts.context_window_compression.sliding_window)
        self.assertEqual(opts.realtime_input_config.automatic_activity_detection.silence_duration_ms, 600)

        default = build_backend_components(load_settings({"GOOGLE_API_KEY": "test-key"})).llm._opts
        self.assertEqual(default.model, "gemini-3.8-live")
        self.assertFalse(default.realtime_input_config)

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
            BASE_TOOLS,
        )
        self.assertEqual(
            [tool.__name__ for tool in enabled_tools],
            [
                *BASE_TOOLS,
                "check_email_address",
                "draft_email",
                "confirm_email_send",
                "cancel_pending_email",
            ],
        )


class ToolSchemaTests(unittest.TestCase):
    def test_every_tool_builds_the_schema_the_realtime_models_send(self) -> None:
        from livekit.agents import llm

        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
                "GMAIL_USER": "jarvis@example.com",
                "GMAIL_APP_PASSWORD": "secret",
                "JARVIS_ENABLE_PC_CONTROL": "true",
                "JARVIS_ENABLE_APP_INSTALL": "true",
                "JARVIS_ENABLE_CAMERA": "true",
                "JARVIS_ENABLE_GESTURES": "true",
                "JARVIS_ENABLE_COMPUTER_USE": "true",
                "JARVIS_ENABLE_CALENDAR": "true",
                "JARVIS_PROACTIVE": "true",
                "JARVIS_PRESENCE": "true",
            }
        )

        for tool in build_tools(settings):
            with self.subTest(tool=tool.__name__):
                llm.utils.build_legacy_openai_schema(tool, internally_tagged=True)
