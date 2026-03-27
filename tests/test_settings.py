import unittest

from settings import SettingsError, load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_to_gemini_backend(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key"})

        self.assertEqual(settings.backend, "gemini-realtime")
        self.assertEqual(settings.google_voice, "Charon")
        self.assertEqual(settings.google_model, "gemini-2.5-flash-native-audio-preview-12-2025")

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
            "Use algo como 'gemini-2.5-flash-native-audio-preview-12-2025' ou um modelo com "
            "'-live-' / '-native-audio-' no nome.",
            settings.backend_validation_errors(),
        )

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
