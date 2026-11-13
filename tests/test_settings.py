import unittest

from settings import SettingsError, load_settings


class OsintSettingsTests(unittest.TestCase):
    def test_urlhaus_key_is_optional_and_never_printed(self) -> None:
        self.assertIsNone(load_settings({"GOOGLE_API_KEY": "k"}).urlhaus_key)
        self.assertIsNone(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_URLHAUS_KEY": "  "}).urlhaus_key)
        self.assertIsNone(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_URLHAUS_KEY": "sua-chave-do-urlhaus"}).urlhaus_key)
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_URLHAUS_KEY": " abc123 "})
        self.assertEqual(settings.urlhaus_key, "abc123")
        self.assertNotIn("abc123", repr(settings))

    def test_watch_domains_default_to_none(self) -> None:
        self.assertEqual(load_settings({"GOOGLE_API_KEY": "k"}).osint_watch_domains, ())
        self.assertEqual(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_OSINT_WATCH_DOMAINS": " "}).osint_watch_domains, ())

    def test_watch_domains_accept_commas_spaces_urls_and_accents(self) -> None:
        raw = "Exemplo.com.br, loja.exemplo.com.br;https://www.outro.com/pagina?x=1  exemplo.com.br. bücher.example"
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_OSINT_WATCH_DOMAINS": raw})
        self.assertEqual(
            settings.osint_watch_domains,
            ("exemplo.com.br", "loja.exemplo.com.br", "www.outro.com", "xn--bcher-kva.example"),
        )

    def test_watch_domains_reject_what_is_not_a_domain(self) -> None:
        for bad in ("localhost", "192.168.0.1", "192.168.0.10", "exemplo", "-ruim.com", "a b@c.com", "http://", "nome_com_underscore.com"):
            with self.assertRaisesRegex(SettingsError, "JARVIS_OSINT_WATCH_DOMAINS", msg=bad):
                load_settings({"GOOGLE_API_KEY": "k", "JARVIS_OSINT_WATCH_DOMAINS": f"ok.com,{bad}"})
        many = ",".join(f"site{index}.com" for index in range(21))
        with self.assertRaisesRegex(SettingsError, "até 20"):
            load_settings({"GOOGLE_API_KEY": "k", "JARVIS_OSINT_WATCH_DOMAINS": many})


class SettingsTests(unittest.TestCase):
    def test_defaults_to_gemini_backend(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key"})

        self.assertEqual(settings.backend, "gemini-realtime")
        self.assertEqual(settings.google_voice, "Charon")
        self.assertEqual(settings.google_model, "gemini-3.8-live")

    def test_gemini_fallback_models_and_rotation(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key"})
        self.assertEqual(
            settings.google_models,
            ("gemini-3.8-live", "gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-preview-12-2025"),
        )
        self.assertEqual(settings.model_rotation, "fallback")
        self.assertEqual(settings.end_of_speech_ms, 0)

        custom = load_settings(
            {
                "GOOGLE_API_KEY": "test-key",
                "GOOGLE_MODEL": "gemini-3.1-flash-live-preview",
                "GOOGLE_FALLBACK_MODELS": "gemini-3.8-live, gemini-3.1-flash-live-preview",
                "JARVIS_MODEL_ROTATION": "Rotate",
                "JARVIS_END_OF_SPEECH_MS": "600",
            }
        )
        # The primary model is never repeated among the fallbacks.
        self.assertEqual(custom.google_models, ("gemini-3.1-flash-live-preview", "gemini-3.8-live"))
        self.assertEqual(custom.model_rotation, "rotate")
        self.assertEqual(custom.end_of_speech_ms, 600)

        self.assertEqual(load_settings({"GOOGLE_API_KEY": "k", "GOOGLE_FALLBACK_MODELS": ""}).google_fallback_models, ())

    def test_gemini_fallback_options_are_validated(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "test-key", "GOOGLE_FALLBACK_MODELS": "gemini-2.5-flash-lite"})
        self.assertTrue(any("GOOGLE_FALLBACK_MODELS" in error for error in settings.backend_validation_errors()))
        for env in ({"JARVIS_MODEL_ROTATION": "aleatorio"}, {"JARVIS_END_OF_SPEECH_MS": "50"}, {"JARVIS_END_OF_SPEECH_MS": "9000"}):
            with self.subTest(env=env), self.assertRaises(SettingsError):
                load_settings({"GOOGLE_API_KEY": "test-key", **env})

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
        # The link only closes by "tchau, Jarvis" or the button unless the .env asks otherwise.
        self.assertEqual(settings.wake_silence_seconds, 0)
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

    def test_one_wake_word_per_persona(self) -> None:
        self.assertEqual(load_settings({"GOOGLE_API_KEY": "test-key"}).wake_words, ("jarvis",))

        settings = load_settings(
            {"GOOGLE_API_KEY": "test-key", "JARVIS_WAKE_WORDS": "Jarvis, Friday", "JARVIS_WAKE_THRESHOLD": "0.4"}
        )
        self.assertEqual(settings.wake_words, ("jarvis", "friday"))
        # "Friday" é comum em músicas e na TV: começa mais exigente que o "Jarvis".
        self.assertEqual(settings.wake_thresholds, (("jarvis", 0.4), ("friday", 0.7)))

        tuned = load_settings(
            {"GOOGLE_API_KEY": "test-key", "JARVIS_WAKE_WORDS": "jarvis,friday", "JARVIS_WAKE_THRESHOLD_FRIDAY": "0,85"}
        )
        self.assertEqual(tuned.wake_threshold_for("friday"), 0.85)
        self.assertEqual(tuned.wake_threshold_for("jarvis"), 0.5)

    def test_wake_word_rejects_bad_numbers(self) -> None:
        for env in (
            {"JARVIS_WAKE_THRESHOLD": "alto"},
            {"JARVIS_WAKE_THRESHOLD": "1.5"},
            {"JARVIS_WAKE_SILENCE_SECONDS": "5"},
            {"JARVIS_WAKE_SILENCE_SECONDS": "-1"},
            {"JARVIS_WAKE_WORDS": "jarvis,ultron"},
            {"JARVIS_WAKE_WORDS": "friday", "JARVIS_WAKE_THRESHOLD_FRIDAY": "2"},
        ):
            with self.subTest(env=env), self.assertRaises(SettingsError):
                load_settings({"GOOGLE_API_KEY": "test-key", **env})
