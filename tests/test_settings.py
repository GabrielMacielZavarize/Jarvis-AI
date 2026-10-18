import unittest

from settings import SettingsError, load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_to_gemini_backend(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key"})

        self.assertEqual(settings.backend, "gemini-realtime")
        self.assertEqual(settings.google_voice, "Charon")
        self.assertEqual(settings.google_model, "gemini-3.8-live")

    def test_invalid_backend_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings({"JARVIS_BACKEND": "claude"})

    def test_openai_backend_requires_api_key(self) -> None:
        settings = load_settings({"JARVIS_BACKEND": "openai-realtime"})

        self.assertIn(
            "OPENAI_API_KEY é obrigatório quando JARVIS_BACKEND=openai-realtime.",
            settings.backend_validation_errors(),
        )

    def test_gemini_realtime_rejects_non_live_model(self) -> None:
        settings = load_settings(
            {
                "JARVIS_BACKEND": "gemini-realtime",
                "GOOGLE_API_KEY": "test-key",
                "GOOGLE_MODEL": "gemini-2.5-flash-lite",
            }
        )

        self.assertIn(
            "GOOGLE_MODEL precisa ser um modelo compatível com Gemini Live API. "
            "Use 'gemini-3.8-live' ou outro modelo com 'live' ou '-native-audio' no nome.",
            settings.backend_validation_errors(),
        )

    def test_gemini_realtime_accepts_live_models(self) -> None:
        for model in (
            "gemini-3.8-live",
            "gemini-3.8-live-extended-thinking",
            "gemini-3.1-flash-live-preview",
            "gemini-live-2.5-flash-native-audio",
            "gemini-2.5-flash-native-audio-preview-12-2025",
        ):
            with self.subTest(model=model):
                settings = load_settings({"GOOGLE_API_KEY": "test-key", "GOOGLE_MODEL": model})
                self.assertEqual(settings.backend_validation_errors(), [])

    def test_example_placeholders_count_as_missing(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "your-google-api-key",
                "LIVEKIT_URL": "wss://your-project.livekit.cloud",
                "LIVEKIT_API_KEY": "your-livekit-api-key",
                "LIVEKIT_API_SECRET": "your-livekit-api-secret",
            }
        )

        self.assertIsNone(settings.google_api_key)
        self.assertIn(
            "GOOGLE_API_KEY é obrigatório quando JARVIS_BACKEND=gemini-realtime.",
            settings.backend_validation_errors(),
        )
        self.assertEqual(len(settings.livekit_validation_errors()), 3)

    def test_email_tool_requires_gmail_credentials(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
            }
        )

        self.assertEqual(
            settings.email_validation_errors(),
            [
                "GMAIL_USER é obrigatório quando JARVIS_ENABLE_EMAIL_TOOL=true.",
                "GMAIL_APP_PASSWORD é obrigatório quando JARVIS_ENABLE_EMAIL_TOOL=true.",
                "Defina GMAIL_USER ou JARVIS_ALLOWED_EMAILS para liberar pelo menos um destinatário autorizado.",
            ],
        )

    def test_allowed_emails_falls_back_to_gmail_user(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_ENABLE_EMAIL_TOOL": "true",
                "GMAIL_USER": "Jarvis@example.com",
                "GMAIL_APP_PASSWORD": "secret",
            }
        )

        self.assertEqual(settings.effective_allowed_emails, ("jarvis@example.com",))

    def test_app_install_is_opt_in(self) -> None:
        self.assertFalse(load_settings({"GOOGLE_API_KEY": "test-key"}).app_install_enabled)
        self.assertTrue(
            load_settings({"GOOGLE_API_KEY": "test-key", "JARVIS_ENABLE_APP_INSTALL": "true"}).app_install_enabled
        )
        with self.assertRaises(SettingsError):
            load_settings({"GOOGLE_API_KEY": "test-key", "JARVIS_ENABLE_APP_INSTALL": "talvez"})

    def test_wake_word_is_opt_in_with_sane_defaults(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key"})

        self.assertFalse(settings.wake_word_enabled)
        self.assertEqual(settings.wake_threshold, 0.5)
        self.assertEqual(settings.wake_silence_seconds, 30)
        self.assertIsNone(settings.wake_mic)

    def test_wake_word_options(self) -> None:
        settings = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "JARVIS_WAKE_WORD": "true",
                "JARVIS_WAKE_THRESHOLD": "0,35",
                "JARVIS_WAKE_SILENCE_SECONDS": "0",
                "JARVIS_WAKE_MIC": "Microphone Array",
            }
        )

        self.assertTrue(settings.wake_word_enabled)
        self.assertEqual(settings.wake_threshold, 0.35)
        self.assertEqual(settings.wake_silence_seconds, 0)
        self.assertEqual(settings.wake_mic, "Microphone Array")

    def test_wake_word_rejects_bad_numbers(self) -> None:
        for env in (
            {"JARVIS_WAKE_THRESHOLD": "alto"},
            {"JARVIS_WAKE_THRESHOLD": "1.5"},
            {"JARVIS_WAKE_SILENCE_SECONDS": "5"},
            {"JARVIS_WAKE_SILENCE_SECONDS": "-1"},
        ):
            with self.subTest(env=env), self.assertRaises(SettingsError):
                load_settings({"GOOGLE_API_KEY": "test-key", **env})
