from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

import confirmation
from confirmation import (
    confirmation_phrase,
    digits_from_tokens,
    normalize_code,
    parse_confirmation,
    speech_tokens,
    spoken_digits,
    wait_for_user_confirmation,
)
from test_tools import FakeHistory, FakeMessage, FakeRunContext


class SpokenNumberTests(unittest.TestCase):
    def test_grouped_and_punctuated_digits(self) -> None:
        for spoken in ("482913", "482 913", "482.913", "48-29-13", "4, 8, 2, 9, 1, 3"):
            with self.subTest(spoken=spoken):
                self.assertEqual(normalize_code(spoken), "482913")

    def test_digit_by_digit_words(self) -> None:
        self.assertEqual(normalize_code("quatro oito dois nove um três"), "482913")
        self.assertEqual(normalize_code("zero meia sete duas"), "0672")

    def test_compound_numbers(self) -> None:
        cases = {
            "quatrocentos e oitenta e dois, novecentos e treze": "482913",
            "quarenta e oito vinte e nove treze": "482913",
            "quatrocentos e oitenta e dois mil novecentos e treze": "482913",
            "zero quarenta e oito duzentos e treze": "048213",
            "cento e cinco cem": "105100",
            "dois mil e cinco": "2005",
        }
        for spoken, digits in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(normalize_code(spoken), digits)

    def test_mixed_words_and_digits(self) -> None:
        self.assertEqual(normalize_code("482 nove um três"), "482913")

    def test_rejects_non_numbers(self) -> None:
        self.assertIsNone(digits_from_tokens([]))
        self.assertIsNone(digits_from_tokens(["e"]))
        self.assertIsNone(normalize_code("quatro oito banana"))
        self.assertIsNone(normalize_code("mil mil"))

    def test_tokens_drop_accents_and_punctuation(self) -> None:
        self.assertEqual(speech_tokens("Confirmar instalação: 482.913!"), ["confirmar", "instalacao", "482", "913"])


class ConfirmationPhraseTests(unittest.TestCase):
    def test_accepts_voice_variants_for_email(self) -> None:
        for heard in (
            "confirmar 482913",
            "Confirmar 482 913.",
            "Confirma 482913",
            "Jarvis, confirmar 482913",
            "Confirmar quatro oito dois nove um três.",
            "confirmar o código 482913",
            "Confirmar o envio, 482-913, por favor",
            "confirmar e-mail 482913",
        ):
            with self.subTest(heard=heard):
                self.assertEqual(parse_confirmation(heard, "email"), "482913")

    def test_rejects_anything_that_is_not_the_confirmation(self) -> None:
        for heard in (
            None,
            "",
            "Pode ir já",
            "sim",
            "482913",
            "não confirmar 482913",
            "confirmar 482913 e manda pro joão também",
            "o código é confirmar 482913",
            "confirmar",
        ):
            with self.subTest(heard=heard):
                self.assertIsNone(parse_confirmation(heard, "email"))

    def test_install_requires_the_word_instalacao(self) -> None:
        self.assertEqual(parse_confirmation("Confirmar instalação 482 913.", "install"), "482913")
        self.assertEqual(parse_confirmation("confirma a instalação do código 482913", "install"), "482913")
        self.assertIsNone(parse_confirmation("confirmar 482913", "install"))

    def test_email_and_install_phrases_do_not_cross(self) -> None:
        self.assertIsNone(parse_confirmation("confirmar instalação 482913", "email"))
        self.assertIsNone(parse_confirmation("confirmar envio 482913", "install"))

    def test_phrase_and_spoken_digits(self) -> None:
        self.assertEqual(confirmation_phrase("email", "482913"), "confirmar 482913")
        self.assertEqual(confirmation_phrase("install", "482913"), "confirmar instalação 482913")
        self.assertEqual(spoken_digits("482913"), "quatro, oito, dois, nove, um, três")
        self.assertEqual(normalize_code(spoken_digits("048213")), "048213")


class WaitForConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirms_from_latest_user_message(self) -> None:
        context = FakeRunContext(
            messages=[
                FakeMessage(role="assistant", text_content="Diga confirmar 482913."),
                FakeMessage(role="user", text_content="Confirmar 482 913."),
            ]
        )
        self.assertEqual(
            await wait_for_user_confirmation(context, "email", "482913", timeout=0),
            (True, "Confirmar 482 913."),
        )

    async def test_older_confirmation_does_not_count(self) -> None:
        context = FakeRunContext(
            messages=[
                FakeMessage(role="user", text_content="confirmar 482913"),
                FakeMessage(role="assistant", text_content="Enviado."),
                FakeMessage(role="user", text_content="pode ir"),
            ]
        )
        confirmed, heard = await wait_for_user_confirmation(context, "email", "482913", timeout=0)
        self.assertFalse(confirmed)
        self.assertEqual(heard, "pode ir")

    async def test_waits_for_a_late_transcript(self) -> None:
        messages = [FakeMessage(role="user", text_content="Pode ir já")]
        context = FakeRunContext(messages=messages)

        async def transcript_lands_late() -> None:
            await asyncio.sleep(0.05)
            messages.append(FakeMessage(role="user", text_content="Confirmar quatro oito dois nove um três"))

        with patch.object(confirmation, "CONFIRMATION_POLL_SECONDS", 0.01):
            late = asyncio.create_task(transcript_lands_late())
            confirmed, _ = await wait_for_user_confirmation(context, "email", "482913", timeout=2)
            await late
        self.assertTrue(confirmed)

    async def test_gives_up_after_timeout(self) -> None:
        context = FakeRunContext()
        context.session.history = FakeHistory([FakeMessage(role="user", text_content="manda")])
        with patch.object(confirmation, "CONFIRMATION_POLL_SECONDS", 0.01):
            confirmed, _ = await wait_for_user_confirmation(context, "email", "482913", timeout=0.05)
        self.assertFalse(confirmed)
