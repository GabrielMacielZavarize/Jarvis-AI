from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from livekit import rtc

import computer_use as cu
import dictation
from computer_use import FocusedField, KeyEvent, WindowInfo
from dictation import DictationController, DictationText, edit_between, parse_utterance, said_after_write, write_once
from test_computer_use import CHROME, NOTEPAD, TERMINAL, WHATSAPP, FakeDesktop, say
from test_tools import FakeHistory, FakeMessage

HUD = WindowInfo(20, "J.A.R.V.I.S. — Google Chrome", "Chrome_WidgetWin_1", "chrome.exe")


def setUpModule() -> None:
    # Mesma rede de segurança do test_computer_use: nada aqui mexe no teclado de verdade.
    from test_computer_use import setUpModule as guard

    guard()


def tearDownModule() -> None:
    from test_computer_use import tearDownModule as release

    release()


def dictate(*utterances: str) -> str:
    text = DictationText()
    for utterance in utterances:
        text.feed(utterance)
    return text.text


# ───────────────────────── normalização: fala → texto ─────────────────────────


class SpokenPunctuationTests(unittest.TestCase):
    def test_dictated_punctuation_replaces_what_the_transcriber_added(self) -> None:
        self.assertEqual(dictate("Oi, vírgula, tudo bem, ponto de interrogação."), "Oi, tudo bem?")
        self.assertEqual(dictate("chego amanhã ponto final"), "Chego amanhã.")
        self.assertEqual(dictate("que legal ponto de exclamação"), "Que legal!")
        self.assertEqual(dictate("lista dois pontos arroz ponto e vírgula feijão"), "Lista: arroz; feijão")

    def test_without_dictated_punctuation_the_transcriber_punctuation_stays(self) -> None:
        self.assertEqual(dictate("Oi, tudo bem?"), "Oi, tudo bem?")
        _, explicit = parse_utterance("Oi, tudo bem?")
        self.assertFalse(explicit)

    def test_ponto_and_virgula_as_plain_words(self) -> None:
        self.assertEqual(dictate("estou no ponto de ônibus"), "Estou no ponto de ônibus.")
        self.assertEqual(dictate("faltou uma vírgula aqui"), "Faltou uma vírgula aqui.")
        self.assertEqual(dictate("cheguei ponto"), "Cheguei.")

    def test_new_line_and_new_paragraph(self) -> None:
        self.assertEqual(dictate("oi nova linha tudo bem"), "Oi\nTudo bem")
        self.assertEqual(dictate("título novo parágrafo texto"), "Título\n\nTexto")
        self.assertEqual(dictate("um", "pula linha", "dois"), "Um.\nDois.")

    def test_accents_and_case_do_not_matter_for_commands(self) -> None:
        self.assertEqual(dictate("oi VIRGULA tudo bem Ponto De Interrogacao"), "Oi, tudo bem?")


class AutomaticPunctuationTests(unittest.TestCase):
    def test_sentence_gets_a_period_and_a_question_gets_a_question_mark(self) -> None:
        self.assertEqual(dictate("Chego em 10 minutos"), "Chego em 10 minutos.")
        self.assertEqual(dictate("Onde você está"), "Onde você está?")
        self.assertEqual(dictate("O que você acha"), "O que você acha?")

    def test_capital_at_the_start_of_each_sentence(self) -> None:
        self.assertEqual(dictate("chego em 10 minutos", "tudo bem"), "Chego em 10 minutos. Tudo bem.")

    def test_spoken_comma_after_a_pause_replaces_the_automatic_period(self) -> None:
        text = dictate("Chego em 10 minutos", "vírgula Gabriel")
        self.assertEqual(text, "Chego em 10 minutos, Gabriel")

    def test_continuation_loses_the_transcriber_capital_but_names_keep_it(self) -> None:
        self.assertEqual(dictate("oi vírgula", "Tudo bem"), "Oi, tudo bem.")
        self.assertEqual(dictate("oi vírgula", "Gabriel"), "Oi, Gabriel.")
        self.assertEqual(dictate("abre vírgula", "PhpStorm"), "Abre, PhpStorm.")

    def test_one_shot_write_keeps_the_words_without_adding_a_period(self) -> None:
        self.assertEqual(write_once("chego em 10 minutos"), "Chego em 10 minutos")
        self.assertEqual(write_once("oi vírgula já vou"), "Oi, já vou")


class EditingCommandTests(unittest.TestCase):
    def test_delete_last_word(self) -> None:
        self.assertEqual(dictate("Oi, tudo bem?", "apaga a última palavra"), "Oi, tudo")
        self.assertEqual(dictate("um dois três apagar última palavra quatro"), "Um dois quatro.")

    def test_delete_last_sentence(self) -> None:
        self.assertEqual(dictate("Oi.", "Tudo bem?", "apaga a última frase"), "Oi.")
        self.assertEqual(dictate("Só uma frase", "apaga a frase"), "")
        self.assertEqual(dictate("linha um nova linha linha dois", "apaga a última frase"), "Linha um\n")

    def test_undo_goes_back_one_utterance_at_a_time(self) -> None:
        text = DictationText()
        text.feed("primeira")
        text.feed("segunda")
        self.assertEqual(text.feed("desfaz").after, "Primeira.")
        self.assertEqual(text.feed("desfazer").after, "")
        self.assertEqual(text.feed("desfaz").after, "")

    def test_undo_inside_an_utterance_drops_only_that_utterance(self) -> None:
        self.assertEqual(dictate("primeira", "isso não desfaz segunda"), "Primeira. Segunda.")

    def test_all_caps_until_turned_off(self) -> None:
        self.assertEqual(dictate("tudo maiúsculo urgente", "ainda"), "URGENTE. AINDA.")
        self.assertEqual(dictate("tudo maiúsculo urgente fim do maiúsculo agora"), "URGENTE agora.")
        self.assertEqual(dictate("caixa alta oi tudo minúsculo tchau"), "OI tchau.")

    def test_deleting_never_reaches_text_that_was_already_in_the_field(self) -> None:
        text = DictationText()
        outcome = text.feed("apaga a última palavra")
        self.assertEqual(outcome.edit, (0, ""))
        outcome = text.feed("desfaz")
        self.assertEqual(outcome.edit, (0, ""))

    def test_end_of_dictation_types_what_came_before_it(self) -> None:
        text = DictationText()
        outcome = text.feed("até amanhã fim do ditado obrigado")
        self.assertTrue(outcome.ended)
        self.assertEqual(outcome.after, "Até amanhã.")
        for phrase in ("Jarvis, fim do ditado.", "encerra o ditado", "parar ditado", "sair do modo ditado"):
            with self.subTest(phrase=phrase):
                self.assertTrue(DictationText().feed(phrase).ended)
                self.assertEqual(DictationText().feed(phrase).after, "")

    def test_edit_is_backspaces_plus_new_keys(self) -> None:
        self.assertEqual(edit_between("Oi, tudo bem.", "Oi, tudo bem, Gabriel"), (1, ", Gabriel"))
        self.assertEqual(edit_between("Oi, tudo", "Oi"), (6, ""))
        self.assertEqual(edit_between("", "Oi"), (0, "Oi"))

    def test_rollback_forgets_an_utterance_that_could_not_be_typed(self) -> None:
        text = DictationText()
        text.feed("primeira")
        outcome = text.feed("tudo maiúsculo segunda")
        text.rollback(outcome)
        self.assertEqual((text.text, text.caps), ("Primeira.", False))
        self.assertEqual(text.feed("desfaz").after, "")


class WriteHereTests(unittest.TestCase):
    def test_takes_the_users_own_words(self) -> None:
        self.assertEqual(said_after_write("Jarvis, escreve aqui: chego em 10 minutos."), "chego em 10 minutos.")
        self.assertEqual(said_after_write("Digita aí que eu já vou"), "eu já vou")
        self.assertIsNone(said_after_write("abre o bloco de notas"))
        self.assertIsNone(said_after_write(None))


# ───────────────────────── controlador (máquina de estados) ─────────────────────────


class FakeSession(rtc.EventEmitter):
    def __init__(self, *said: str) -> None:
        super().__init__()
        self.userdata: dict[str, Any] = {}
        self.history = FakeHistory([FakeMessage("user", text) for text in said])


class FakeHandle:
    def __init__(self) -> None:
        self.interrupt = Mock()


def heard(item: str | None, text: str, final: bool = False) -> SimpleNamespace:
    return SimpleNamespace(transcript=text, is_final=final, item_id=item)


def typed_text(events: list[Any]) -> str:
    """What the fake field shows after the key events (layout of FakeDesktop.stroke_for)."""
    out: list[str] = []
    shift = False
    for event in events:
        if not isinstance(event, KeyEvent):
            continue
        up = bool(event.flags & cu.KEYEVENTF_KEYUP)
        if event.vk == 0x10:
            shift = not up
            continue
        if up:
            continue
        if event.flags & cu.KEYEVENTF_UNICODE:
            out.append(chr(event.scan))
        elif event.vk == 0x08:
            if out:
                out.pop()
        elif event.vk == 0x0D:
            out.append("⇧\n" if shift else "\n")
        elif 0x41 <= event.vk <= 0x5A:
            out.append(chr(event.vk) if shift else chr(event.vk).lower())
        else:
            out.append(chr(event.vk))
    return "".join(out)


class ControllerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.desktop = FakeDesktop().install(self)
        for item in (
            patch.object(dictation, "DICTATION_SETTLE_SECONDS", 0.01),
            patch.object(dictation, "WATCH_POLL_SECONDS", 0.01),
            patch("dictation.tool_status", AsyncMock()),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.session = FakeSession("Jarvis, modo ditado")
        self.published: list[dict[str, Any]] = []
        self.beeps: list[str] = []
        self.hud_connected = True

        async def publish(event_type: str, **payload: Any) -> bool:
            self.published.append({"type": event_type, **payload})
            return self.hud_connected

        self.controller = DictationController(self.session, publish=publish, beeper=self.beeps.append).attach()
        self.session.userdata[dictation.STATE_KEY] = self.controller

    async def asyncTearDown(self) -> None:
        if self.controller.active:
            await self.controller.stop("fim do teste")
        await self.controller.wait_idle()

    async def speak(self, item: str | None, *parts: str, final: bool = True) -> None:
        """Partial transcripts as Gemini sends them (cumulative), then the final one."""
        text = ""
        for part in parts:
            text = f"{text} {part}".strip()
            self.session.emit("user_input_transcribed", heard(item, text))
        if final:
            self.session.emit("user_input_transcribed", heard(item, text, final=True))
        await asyncio.sleep(0.05)
        await self.controller.wait_idle()

    @property
    def field(self) -> str:
        return typed_text(self.desktop.events)

    def states(self) -> list[str]:
        return [event["state"] for event in self.published]


class DictationFlowTests(ControllerTestCase):
    async def test_types_what_the_user_says_but_never_the_command_that_started_it(self) -> None:
        self.session.emit("user_input_transcribed", heard("GI_start", "Jarvis, modo"))
        await self.controller.start()
        # A final da fala "modo ditado" chega depois que o ditado ligou: não é texto.
        await self.speak("GI_start", "Jarvis, modo ditado.")
        await self.speak("GI_1", "Oi,", "vírgula,", "tudo bem", "ponto de interrogação.")
        await self.speak("GI_2", "Chego em", "10 minutos")

        self.assertEqual(self.field, "Oi, tudo bem? Chego em 10 minutos.")
        self.assertEqual(self.states(), ["on", "typing", "typing"])
        self.assertEqual(self.published[-1]["tail"], "Oi, tudo bem? Chego em 10 minutos.")
        self.assertEqual(self.published[-1]["typed"], " Chego em 10 minutos.")
        self.assertEqual(self.published[0]["beep"], "start")
        self.assertEqual(self.published[-1]["beep"], "tick")

    async def test_a_pause_is_enough_the_final_transcript_only_completes_it(self) -> None:
        await self.controller.start()
        await self.speak("GI_1", "Chego em", "10 minutos", final=False)
        self.assertEqual(self.field, "Chego em 10 minutos.")
        # A final do Gemini só vem depois da resposta (suprimida) dele e não repete nada.
        await self.speak("GI_1", "Chego em 10 minutos")
        self.assertEqual(self.field, "Chego em 10 minutos.")
        await self.speak("GI_1", "Chego em 10 minutos e meio")
        self.assertEqual(self.field, "Chego em 10 minutos. E meio.")

    async def test_editing_commands_press_backspace_only_over_dictated_text(self) -> None:
        await self.controller.start()
        await self.speak("GI_1", "Oi, tudo bem?")
        await self.speak("GI_2", "apaga a última palavra")
        self.assertEqual(self.field, "Oi, tudo")
        await self.speak("GI_3", "desfaz")
        self.assertEqual(self.field, "Oi, tudo bem?")
        backspaces = [e for e in self.desktop.keys if e.vk == 0x08 and not e.flags & cu.KEYEVENTF_KEYUP]
        self.assertEqual(len(backspaces), 5)
        self.assertEqual(self.published[2]["commands"], ["apaga a última palavra"])

    async def test_end_of_dictation_turns_it_off_with_the_end_beep(self) -> None:
        await self.controller.start()
        await self.speak("GI_1", "até amanhã", "fim do ditado")
        self.assertFalse(self.controller.active)
        self.assertFalse(dictation.dictating(self.session))
        self.assertEqual(self.field, "Até amanhã.")
        self.assertEqual(self.states()[-1], "off")
        self.assertEqual(self.published[-1]["beep"], "end")
        await self.speak("GI_2", "isso não é mais ditado")
        self.assertEqual(self.field, "Até amanhã.")

    async def test_pipeline_backends_without_item_ids_use_only_final_transcripts(self) -> None:
        await self.controller.start()
        self.session.emit("user_input_transcribed", heard(None, "parcial"))
        await self.speak(None, "primeira frase")
        await self.speak(None, "segunda frase")
        self.assertEqual(self.field, "Primeira frase. Segunda frase.")

    async def test_first_text_said_with_the_command(self) -> None:
        await self.controller.start("oi vírgula tudo bem")
        self.assertEqual(self.field, "Oi, tudo bem")

    async def test_without_a_hud_the_beep_comes_from_the_pc(self) -> None:
        self.hud_connected = False
        await self.controller.start()
        await self.speak("GI_1", "oi")
        await self.controller.stop()
        self.assertEqual(self.beeps, ["start", "tick", "end"])


class SilenceTests(ControllerTestCase):
    async def test_jarvis_does_not_answer_while_dictating(self) -> None:
        idle, during, right_after, later = FakeHandle(), FakeHandle(), FakeHandle(), FakeHandle()
        self.session.emit("speech_created", SimpleNamespace(speech_handle=idle))
        await self.controller.start()
        self.session.emit("speech_created", SimpleNamespace(speech_handle=during))
        await self.controller.stop()
        self.session.emit("speech_created", SimpleNamespace(speech_handle=right_after))
        with patch.object(dictation, "STOP_GRACE_SECONDS", -1):
            self.session.emit("speech_created", SimpleNamespace(speech_handle=later))

        idle.interrupt.assert_not_called()
        during.interrupt.assert_called_once_with(force=True)
        right_after.interrupt.assert_called_once_with(force=True)  # a resposta ao "fim do ditado"
        later.interrupt.assert_not_called()

    async def test_mouse_and_keyboard_tools_refuse_while_dictating(self) -> None:
        await self.controller.start()
        context = SimpleNamespace(session=self.session, userdata=self.session.userdata)
        say(context, "clica no botão de play")
        with self.assertRaisesRegex(cu.ComputerUseError, "modo ditado"):
            await cu._authorize(context)


class GuardTests(ControllerTestCase):
    async def test_chat_apps_get_shift_enter_so_nothing_is_sent(self) -> None:
        self.desktop.foreground = WHATSAPP
        await self.controller.start()
        await self.speak("GI_1", "oi nova linha tudo bem")
        self.assertEqual(self.field, "Oi⇧\nTudo bem")

    async def test_password_field_is_refused_and_the_dictation_goes_on(self) -> None:
        await self.controller.start()
        self.desktop.focus = FocusedField("Senha", True)
        await self.speak("GI_1", "minha frase")
        self.assertEqual(self.field, "")
        self.assertTrue(self.controller.active)
        self.assertEqual(self.published[-1]["state"], "warn")
        self.assertEqual(self.published[-1]["beep"], "error")
        self.desktop.focus = FocusedField("Editor de texto", False)
        await self.speak("GI_2", "outra frase")
        self.assertEqual(self.field, "Outra frase.")  # a recusada não conta para o desfaz

    async def test_secrets_terminals_and_the_hud_are_refused(self) -> None:
        await self.controller.start()
        await self.speak("GI_1", "4111 1111 1111 1111")
        self.desktop.foreground = TERMINAL
        await self.speak("GI_2", "rm tudo")
        self.desktop.foreground = HUD
        await self.speak("GI_3", "oi")
        self.assertEqual(self.field, "")
        self.assertEqual(self.states(), ["on", "warn", "warn", "warn"])
        self.assertIn("HUD", self.published[-1]["message"])

    async def test_moving_the_mouse_while_typing_stops_the_dictation(self) -> None:
        await self.controller.start()
        moves = iter([(100, 100), (100, 100), (400, 300)])
        with patch.object(cu, "_get_cursor", side_effect=lambda: next(moves, (400, 300))):
            await self.speak("GI_1", "uma frase bem comprida para digitar")
        self.assertFalse(self.controller.active)
        self.assertIn("mexeu no mouse", self.published[-1]["message"])
        self.assertEqual(self.published[-1]["beep"], "error")

    async def test_esc_between_utterances_stops_the_dictation(self) -> None:
        await self.controller.start()
        with patch.object(cu, "_escape_down", return_value=True):
            await asyncio.sleep(0.05)
        self.assertFalse(self.controller.active)
        self.assertIn("ESC", self.published[-1]["message"])

    async def test_long_silence_turns_it_off(self) -> None:
        with patch.object(dictation, "DICTATION_IDLE_SECONDS", 0.02):
            await self.controller.start()
            await asyncio.sleep(0.08)
        self.assertFalse(self.controller.active)
        self.assertEqual(self.states()[-1], "off")

    async def test_new_focused_window_starts_fresh_so_deletes_stay_in_it(self) -> None:
        await self.controller.start()
        await self.speak("GI_1", "texto no bloco")
        self.desktop.foreground = CHROME
        await self.speak("GI_2", "apaga a última frase")
        await self.speak("GI_3", "busca")
        self.assertEqual(self.field, "Texto no bloco.Busca.")  # nada apagado no outro campo
        self.assertEqual(self.published[-1]["window"], CHROME.title)


# ───────────────────────── ferramentas ─────────────────────────


class ToolTests(ControllerTestCase):
    def context(self, *said: str) -> SimpleNamespace:
        self.session.history = FakeHistory([FakeMessage("user", text) for text in said])
        return SimpleNamespace(session=self.session, userdata=self.session.userdata)

    async def test_start_dictation_needs_the_users_request(self) -> None:
        with patch.object(dictation, "START_WAIT_SECONDS", 0.05):
            reply = await dictation.start_dictation(self.context("o que tem na tela?"))
        self.assertIn("Não liguei", reply)
        self.assertFalse(self.controller.active)

        reply = await dictation.start_dictation(self.context("Jarvis, modo ditado"))
        self.assertTrue(self.controller.active)
        self.assertIn("NÃO responda", reply)
        self.assertIn(NOTEPAD.title, reply)

    async def test_start_dictation_only_on_windows(self) -> None:
        with patch.object(cu, "IS_WINDOWS", False):
            reply = await dictation.start_dictation(self.context("modo ditado"))
        self.assertIn("só funciona no Windows", reply)

    async def test_write_here_types_the_users_own_words(self) -> None:
        with patch("dictation.publish_hud_event", AsyncMock(return_value=True)) as publish:
            reply = await dictation.write_here(self.context("Escreve aqui: chego em 10 minutos"), "chego em dez minutos")
        self.assertEqual(self.field, "Chego em 10 minutos")
        self.assertIn("Nada foi enviado", reply)
        self.assertEqual(publish.await_args.kwargs["state"], "once")

    async def test_write_here_in_whatsapp_never_presses_plain_enter(self) -> None:
        self.desktop.foreground = WHATSAPP
        with patch("dictation.publish_hud_event", AsyncMock(return_value=True)):
            await dictation.write_here(self.context("escreve aqui oi nova linha já vou"), "")
        self.assertEqual(self.field, "Oi⇧\nJá vou")

    async def test_controller_is_created_once_per_session(self) -> None:
        session = FakeSession()
        first = dictation.watch_dictation(session)
        self.assertIs(dictation.controller_for(session), first)
        self.assertFalse(dictation.dictating(session))


if __name__ == "__main__":
    unittest.main()
