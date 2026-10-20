from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import computer_use as cu
from computer_use import FocusedField, MouseEvent, PointedElement, WindowInfo
from gestures import GestureEngine, GestureService
from hand_fixtures import absent, end_of, hold
from test_computer_use import CHROME, NOTEPAD, UAC, FakeDesktop, context, located, say
from test_gestures import FakeTracker, armed_machine, play

HUD = WindowInfo(20, "J.A.R.V.I.S. — HUD", "Chrome_WidgetWin_1", "chrome.exe")
PLAY = PointedElement("Reproduzir (k)", 50000, False)
SEARCH = PointedElement("Pesquisar", cu.UIA_EDIT, False)
PASSWORD = PointedElement("Senha", cu.UIA_EDIT, True)
PAGE = PointedElement("YouTube", cu.UIA_DOCUMENT, False)
SPOT = (500, 400)  # tela 1


def setUpModule() -> None:
    from test_computer_use import setUpModule as guard_mouse
    from test_gestures import setUpModule as guard_gestures

    guard_mouse()
    guard_gestures()


def tearDownModule() -> None:
    from test_computer_use import tearDownModule as release_mouse
    from test_gestures import tearDownModule as release_gestures

    release_gestures()
    release_mouse()


class PointedDesktop(FakeDesktop):
    """FakeDesktop + the gestures' pointed spot, the crosshair and the element under the finger."""

    def __init__(self) -> None:
        super().__init__()
        self.pointed: tuple[int, int] | None = SPOT
        self.element: PointedElement | None = PLAY
        self.marks: list[tuple[tuple[int, int], float, str, int]] = []

    def point(self, max_age: float) -> tuple[int, int] | None:
        assert max_age == cu.POINT_MAX_AGE_S
        return self.pointed

    def mark(self, point: tuple[int, int], seconds: float, title: str) -> bool:
        # Quantos eventos de mouse já tinham saído: a mira tem que vir antes do clique.
        self.marks.append((point, seconds, title, len(self.mouse)))
        return True

    def install(self, test: unittest.TestCase) -> PointedDesktop:
        super().install(test)
        cu.set_pointer(self.point, self.mark)
        test.addCleanup(cu.set_pointer, None)
        for item in (
            patch.object(cu, "element_at", side_effect=lambda point: self.element),
            patch.object(cu, "POINT_PREVIEW_S", 0),
        ):
            item.start()
            test.addCleanup(item.stop)
        return self


CLICK = [MouseEvent(cu.MOUSEEVENTF_LEFTDOWN), MouseEvent(cu.MOUSEEVENTF_LEFTUP)]


class HereWordsTests(unittest.TestCase):
    def test_here_in_the_speech_or_as_the_target(self) -> None:
        self.assertTrue(cu.refers_here("Jarvis, clica aqui"))
        self.assertTrue(cu.refers_here("digita olá ali"))
        self.assertTrue(cu.refers_here("clica onde eu tô apontando"))
        self.assertTrue(cu.refers_here("clica", "isso aqui"))
        self.assertFalse(cu.refers_here("clica no botão de play", "botão de play"))
        self.assertFalse(cu.refers_here("tira daqui"))

    def test_text_fields(self) -> None:
        self.assertTrue(cu.is_text_field(SEARCH, CHROME))
        self.assertTrue(cu.is_text_field(PointedElement("Texto", cu.UIA_DOCUMENT), NOTEPAD))
        self.assertFalse(cu.is_text_field(PAGE, CHROME))  # a página do navegador inteira
        self.assertFalse(cu.is_text_field(PLAY, CHROME))
        self.assertFalse(cu.is_text_field(None, CHROME))

    def test_without_gestures_there_is_no_point(self) -> None:
        cu.set_pointer(None)
        self.assertIsNone(cu.pointed_point())
        cu.set_pointer(MagicMock(side_effect=RuntimeError("câmera caiu")))
        self.addCleanup(cu.set_pointer, None)
        self.assertIsNone(cu.pointed_point())


class PointedClickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.desk = PointedDesktop().install(self)

    async def test_click_here_clicks_the_pointed_spot_without_the_vision_model(self) -> None:
        ctx = context("Jarvis, clica aqui")

        result = await cu.click_on_screen(ctx, target="aqui")

        self.assertEqual(self.desk.cursor, SPOT)
        self.assertEqual(self.desk.mouse, CLICK)
        self.assertEqual(self.desk.prompts, [])  # o Gemini não foi chamado
        self.assertIn("Clique em 'Reproduzir (k)' na tela 1 (500, 400)", result)
        self.assertIn("apontou com o dedo", result)
        self.assertEqual(self.desk.marks, [(SPOT, cu.POINT_MARK_S, "CLICANDO AQUI", 0)])
        self.assertEqual(ctx.userdata[cu.STATE_KEY]["log"][-1]["text"].split(" O lugar")[0], result.split(" O lugar")[0])

    async def test_the_hud_card_shows_where_it_clicks(self) -> None:
        with patch("computer_use.show_card") as card, patch("computer_use.send_screenshot") as shot:
            await cu.click_on_screen(context("clica aqui"), target="aqui")
        payload = card.await_args.args[1]
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["screen"], "tela 1")
        self.assertEqual(shot.await_args.args[1], "tela 1")

    async def test_here_in_the_speech_is_enough(self) -> None:
        result = await cu.click_on_screen(context("clica aqui no play"), target="play")
        self.assertEqual(self.desk.mouse, CLICK)
        self.assertEqual(self.desk.prompts, [])
        self.assertIn("'Reproduzir (k)'", result)

    async def test_without_recent_pointing_it_is_the_old_click(self) -> None:
        self.desk.pointed = None
        self.desk.replies.append(located(index=2))
        result = await cu.click_on_screen(context("Jarvis, clica aqui no play"), target="play")
        self.assertEqual(result, "Clique em 'Play' na tela 3 (-1224, 1302).")
        self.assertEqual(len(self.desk.prompts), 1)
        self.assertEqual(self.desk.marks, [])

    async def test_pointing_without_saying_here_uses_the_description(self) -> None:
        self.desk.replies.append(located(index=2))
        await cu.click_on_screen(context("clica no botão de play"), target="botão de play")
        self.assertEqual(len(self.desk.prompts), 1)
        self.assertEqual(self.desk.cursor, (-1224, 1302))

    async def test_reading_request_never_clicks_even_pointing(self) -> None:
        result = await cu.click_on_screen(context("o que é isso aqui?"), target="aqui")
        self.assertTrue(result.startswith("Recusado"))
        self.assertEqual(self.desk.events, [])
        self.assertEqual(self.desk.marks, [])

    async def test_pointing_at_the_hud_is_refused(self) -> None:
        self.desk.under_point = HUD
        result = await cu.click_on_screen(context("clica aqui"), target="aqui")
        self.assertIn("HUD", result)
        self.assertEqual(self.desk.events, [])
        self.assertEqual(self.desk.moves, [])

    async def test_forbidden_windows_are_refused(self) -> None:
        self.desk.under_point = UAC
        result = await cu.click_on_screen(context("clica aqui"), target="aqui")
        self.assertIn("UAC", result)
        self.assertEqual(self.desk.events, [])
        self.assertEqual(self.desk.marks, [])

    async def test_password_field_is_refused(self) -> None:
        self.desk.element = PASSWORD
        result = await cu.click_on_screen(context("clica aqui"), target="aqui")
        self.assertTrue(result.startswith("Recusado"))
        self.assertEqual(self.desk.events, [])

    async def test_off_screen_point_is_refused(self) -> None:
        self.desk.pointed = (2200, 1460)  # no vão entre a tela 1 e a do notebook
        result = await cu.click_on_screen(context("clica aqui"), target="aqui")
        self.assertIn("fora das telas", result)
        self.assertEqual(self.desk.events, [])

    async def test_risky_element_waits_for_the_code_with_the_crosshair_on(self) -> None:
        self.desk.element = PointedElement("Enviar", 50000, False)
        ctx = context("clica aqui")

        result = await cu.click_on_screen(ctx, target="aqui")

        self.assertTrue(result.startswith("PRECISA CONFIRMAÇÃO"))
        self.assertEqual(self.desk.events, [])
        self.assertEqual(self.desk.marks, [(SPOT, cu.POINT_PENDING_MARK_S, "CONFIRMAR CLIQUE AQUI?", 0)])
        pending = ctx.userdata[cu.PENDING_KEY]
        self.assertTrue(pending["pointed"])

        say(ctx, f"confirmar clique {pending['code']}")
        done = await cu.confirm_screen_action(ctx, code=pending["code"])

        self.assertIn("Confirmado", done)
        self.assertEqual(self.desk.mouse, CLICK)
        self.assertEqual(self.desk.cursor, SPOT)
        self.assertEqual(self.desk.marks[-1], (SPOT, cu.POINT_MARK_S, "CLICANDO AQUI", 0))

    async def test_unreadable_spot_also_needs_the_code(self) -> None:
        self.desk.element = None  # app sem UI Automation (jogo, vídeo em tela cheia)
        ctx = context("clica aqui")
        result = await cu.click_on_screen(ctx, target="aqui")
        self.assertTrue(result.startswith("PRECISA CONFIRMAÇÃO"))
        self.assertIn("Não consegui ler o que tem nesse ponto", result)
        self.assertIn("onde o senhor apontou", result)
        self.assertEqual(self.desk.events, [])

    async def test_confirmation_refused_when_another_window_took_the_spot(self) -> None:
        self.desk.element = PointedElement("Excluir", 50000, False)
        ctx = context("clica aqui")
        await cu.click_on_screen(ctx, target="aqui")
        code = ctx.userdata[cu.PENDING_KEY]["code"]
        self.desk.under_point = NOTEPAD
        say(ctx, f"confirmar clique {code}")
        self.assertIn("A tela mudou", await cu.confirm_screen_action(ctx, code=code))
        self.assertEqual(self.desk.events, [])

    async def test_right_click_here(self) -> None:
        result = await cu.click_on_screen(context("clica com o direito aqui"), target="aqui", button="right")
        self.assertIn("Clique direito", result)
        self.assertEqual(
            self.desk.mouse, [MouseEvent(cu.MOUSEEVENTF_RIGHTDOWN), MouseEvent(cu.MOUSEEVENTF_RIGHTUP)]
        )


class TypeHereTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.desk = PointedDesktop().install(self)
        self.desk.element = SEARCH
        self.desk.foreground = CHROME

    def typed(self) -> list[Any]:
        return self.desk.keys

    async def test_type_here_clicks_the_pointed_field_first(self) -> None:
        ctx = context("digita olá aqui")

        result = await cu.type_text(ctx, text="olá")

        self.assertEqual(self.desk.mouse, CLICK)
        self.assertEqual(self.desk.cursor, SPOT)
        self.assertTrue(self.typed())
        self.assertIn("Digitei 3 caractere(s)", result)
        self.assertIn("campo 'Pesquisar' onde o usuário apontou", result)
        self.assertEqual(self.desk.marks, [(SPOT, cu.POINT_MARK_S, "DIGITANDO AQUI", 0)])

    async def test_click_here_then_type_does_not_click_twice(self) -> None:
        ctx = context("clica aqui e digita olá")
        await cu.click_on_screen(ctx, target="aqui")
        result = await cu.type_text(ctx, text="olá")
        self.assertEqual(self.desk.mouse, CLICK)
        self.assertNotIn("Antes cliquei", result)

    async def test_not_a_text_field_types_nothing(self) -> None:
        self.desk.element = PLAY
        result = await cu.type_text(context("digita olá aqui"), text="olá")
        self.assertIn("não é um campo de texto", result)
        self.assertEqual(self.desk.events, [])

    async def test_browser_page_is_not_a_field(self) -> None:
        self.desk.element = PAGE
        result = await cu.type_text(context("digita k aqui"), text="k")
        self.assertIn("não é um campo de texto", result)
        self.assertEqual(self.desk.events, [])

    async def test_unknown_element_types_nothing(self) -> None:
        self.desk.element = None
        result = await cu.type_text(context("digita olá aqui"), text="olá")
        self.assertIn("Não consegui ver", result)
        self.assertEqual(self.desk.events, [])

    async def test_password_field_and_forbidden_window_are_refused(self) -> None:
        self.desk.element = PASSWORD
        self.assertTrue((await cu.type_text(context("digita olá aqui"), text="olá")).startswith("Recusado"))
        self.desk.element = SEARCH
        self.desk.under_point = UAC
        self.assertTrue((await cu.type_text(context("digita olá aqui"), text="olá")).startswith("Recusado"))
        self.desk.under_point = HUD
        self.assertIn("HUD", await cu.type_text(context("digita olá aqui"), text="olá"))
        self.assertEqual(self.desk.events, [])

    async def test_the_focused_field_is_still_checked_after_the_click(self) -> None:
        self.desk.focus = FocusedField("Senha", True)
        result = await cu.type_text(context("digita olá aqui"), text="olá")
        self.assertTrue(result.startswith("Recusado"))
        self.assertEqual(self.typed(), [])

    async def test_without_pointing_types_in_the_focused_field(self) -> None:
        self.desk.pointed = None
        await cu.type_text(context("digita olá aqui"), text="olá")
        self.assertEqual(self.desk.mouse, [])
        self.assertTrue(self.typed())


class GestureMarkTests(unittest.TestCase):
    """The crosshair stays on the spot Jarvis is about to click, even after the hand drops."""

    def setUp(self) -> None:
        self.overlay = MagicMock()
        self.actions = MagicMock()
        self.actions.virtual_bounds.return_value = (-1440, 0, 2560, 2684)
        self.now = 0.0
        self.engine = GestureEngine([], self.actions, tracker=FakeTracker([]), overlay=self.overlay, clock=lambda: self.now)
        self.engine.machine, self.t = armed_machine()

    def test_mark_holds_the_crosshair_and_the_title(self) -> None:
        self.now = self.t
        self.engine.mark_point((300, 200), 2.0, "CLICANDO AQUI")
        self.engine._refresh_overlay(self.t + 1.0)
        self.overlay.aim.assert_called_with((300, 200))
        self.assertEqual(self.engine.view(self.t + 1.0).title, "CLICANDO AQUI")

        self.engine._refresh_overlay(self.t + 2.5)
        self.overlay.aim.assert_called_with(None)  # sem mão à vista, a mira some no fim

    def test_synthetic_hand_points_and_jarvis_clicks_there(self) -> None:
        point = hold("point", self.t, 0.6, center=(0.3, 0.3))
        gone = absent(end_of(point), 0.5)
        play(self.engine.machine, point, gone)
        self.now = end_of(gone)

        desk = PointedDesktop()
        desk.install(self)
        cu.set_pointer(self.engine.pointed_screen_point, self.engine.mark_point)
        pixel = self.engine.pointed_screen_point(cu.POINT_MAX_AGE_S)
        self.assertIsNotNone(pixel)
        self.assertTrue(any(m.left <= pixel[0] < m.right and m.top <= pixel[1] < m.bottom for m in win_screens()))

        import asyncio

        result = asyncio.run(cu.click_on_screen(context("Jarvis, clica aqui"), target="aqui"))

        self.assertIn("apontou com o dedo", result)
        self.assertEqual(desk.cursor, pixel)
        self.assertEqual(desk.mouse, CLICK)
        self.engine._refresh_overlay(self.now + 0.5)
        self.overlay.aim.assert_called_with(pixel)  # a mão já baixou, mas a mira marca o clique
        self.assertEqual(self.engine.view(self.now + 0.5).title, "CLICANDO AQUI")

    def test_service_marks_only_with_gestures_on(self) -> None:
        service = GestureService()
        self.assertFalse(service.mark_point((1, 2), 1.0, "CLICANDO AQUI"))
        engine = MagicMock()
        service._engine = engine
        with patch.object(GestureService, "running", new=True):
            self.assertTrue(service.mark_point((1, 2), 1.0, "CLICANDO AQUI"))
        engine.mark_point.assert_called_once_with((1, 2), 1.0, "CLICANDO AQUI")


def win_screens() -> list[Any]:
    from test_computer_use import SCREENS

    return SCREENS


class RegistrationTests(unittest.TestCase):
    def test_build_tools_wires_the_pointer_only_with_gestures_and_mouse(self) -> None:
        import gestures
        from settings import load_settings
        from tools import build_tools

        self.addCleanup(cu.set_pointer, None)
        cu.set_pointer(None)
        build_tools(load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_COMPUTER_USE": "true"}))
        self.assertIsNone(cu.POINTER)
        build_tools(
            load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_COMPUTER_USE": "true", "JARVIS_ENABLE_GESTURES": "true"})
        )
        self.assertEqual(cu.POINTER, gestures.SERVICE.pointed_screen_point)
        self.assertEqual(cu.MARKER, gestures.SERVICE.mark_point)

    def test_prompt_tells_the_model_about_click_here(self) -> None:
        from prompts import AGENT_INSTRUCTION

        self.assertIn('click_on_screen("aqui")', AGENT_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
