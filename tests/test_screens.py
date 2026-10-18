"""Telas numeradas como nas Configurações, nomes, apelidos, layouts e ações em lote (tudo com mocks)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pc_control
import win_desktop
from pc_control import PCControlError, apply_layout, arrange_action, layouts_action, save_layout, screens_action
from prompts import AGENT_INSTRUCTION
from test_pc_control import DesktopCase, win
from win_desktop import DisplayTarget, Monitor

_GUARDS: list[Any] = []


def setUpModule() -> None:
    """Safety net: no test here may focus, move, open or close anything on the real desktop."""
    targets = [
        "win_desktop.bring_to_front",
        "win_desktop.move_to_monitor",
        "win_desktop.restore_placement",
        "win_desktop.show_window",
        "win_desktop.close_window",
        "pc_control.os.startfile",
        "pc_control.subprocess.Popen",
        "pc_control.subprocess.run",
        "pc_control.webbrowser.open",
    ]
    for target in targets:

        def forbid(*_args: Any, _target: str = target, **_kwargs: Any) -> None:
            raise AssertionError(f"o teste chamou {_target} de verdade")

        guard = patch(target, side_effect=forbid, create=True)
        guard.start()
        _GUARDS.append(guard)


def tearDownModule() -> None:
    while _GUARDS:
        _GUARDS.pop().stop()


# Dados lidos na máquina do Gabriel (GetMonitorInfo + QueryDisplayConfig, 2026-10-18).
# Gabarito do "Identificar" das Configurações: 1 = notebook, 2 = vertical, 3 = de cima.
ADAPTER = r"\\?\PCI#VEN_8086&DEV_7D51&SUBSYS_13E41043&REV_03#3&11583659&0&10#{5b45201d-f2f2-4f3b-85bb-30ff1f953599}"
RAW = [
    Monitor(1, 0, 0, 2560, 1440, (0, 0, 2560, 1392), True, device=r"\\.\DISPLAY1"),
    Monitor(2, 0, 1474, 1920, 2674, (0, 1474, 1920, 2602), False, device=r"\\.\DISPLAY2"),
    Monitor(3, -1440, 124, 0, 2684, (-1440, 124, 0, 2636), False, device=r"\\.\DISPLAY3"),
]
TARGETS = [  # na ordem em que o QueryDisplayConfig devolve
    DisplayTarget(r"\\.\DISPLAY2", ADAPTER, 0x800050, win_desktop.OUTPUT_INTERNAL, 0, "", "CMN1441#UID8388688"),
    DisplayTarget(r"\\.\DISPLAY1", ADAPTER, 0x9038, win_desktop.OUTPUT_HDMI, 0, "FY27QHCB", "FYH2700#UID36920"),
    DisplayTarget(
        r"\\.\DISPLAY3", ADAPTER, 0x5046, win_desktop.OUTPUT_DISPLAYPORT_EXTERNAL, 4, "GF270A", "QHX2700#UID20550"
    ),
]
SCREENS = win_desktop.number_monitors(RAW, TARGETS, {})
NOTEBOOK, VERTICAL, TOP = SCREENS


class NumberingTests(unittest.TestCase):
    def test_real_setup_matches_the_settings_identify_numbers(self) -> None:
        self.assertEqual([(m.number, m.device) for m in SCREENS], [
            (1, r"\\.\DISPLAY2"), (2, r"\\.\DISPLAY3"), (3, r"\\.\DISPLAY1"),
        ])  # fmt: skip
        self.assertTrue(NOTEBOOK.internal)
        self.assertEqual((NOTEBOOK.width, NOTEBOOK.height), (1920, 1200))
        self.assertEqual((VERTICAL.orientation, VERTICAL.model), ("vertical", "GF270A"))
        self.assertTrue(TOP.primary)
        self.assertEqual(TOP.hardware_id, "FYH2700#UID36920")

    def test_automatic_names_come_from_hardware_and_position(self) -> None:
        self.assertEqual((NOTEBOOK.name, NOTEBOOK.aliases), ("notebook", ("de baixo",)))
        self.assertEqual((VERTICAL.name, VERTICAL.aliases), ("vertical", ("da esquerda",)))
        self.assertEqual((TOP.name, TOP.aliases), ("de cima", ("horizontal",)))
        self.assertEqual(TOP.label, "monitor de cima (tela 3)")
        self.assertEqual(NOTEBOOK.label, "notebook (tela 1)")

    def test_settings_order_puts_internal_then_displayport_then_hdmi(self) -> None:
        self.assertEqual(
            [t.device for t in win_desktop.settings_order(TARGETS)], [r"\\.\DISPLAY2", r"\\.\DISPLAY3", r"\\.\DISPLAY1"]
        )
        two_hdmi = [
            DisplayTarget("B", ADAPTER, 2, win_desktop.OUTPUT_HDMI, 1),
            DisplayTarget("A", ADAPTER, 1, win_desktop.OUTPUT_HDMI, 0),
        ]
        self.assertEqual([t.device for t in win_desktop.settings_order(two_hdmi)], ["A", "B"])

    def test_confirmed_numbers_win_and_unplugged_screens_leave_no_hole(self) -> None:
        config = {"FYH2700#UID36920": {"numero": 1}, "CMN1441#UID8388688": {"numero": 3}}
        swapped = win_desktop.number_monitors(RAW, TARGETS, config)
        self.assertEqual([m.name for m in swapped], ["de cima", "vertical", "notebook"])
        self.assertTrue(swapped[0].confirmed)
        self.assertFalse(swapped[1].confirmed)

        unplugged = win_desktop.number_monitors(RAW[:2], TARGETS[:2], {
            "CMN1441#UID8388688": {"numero": 1}, "QHX2700#UID20550": {"numero": 2}, "FYH2700#UID36920": {"numero": 3},
        })  # fmt: skip
        self.assertEqual([(m.number, m.name) for m in unplugged], [(1, "notebook"), (2, "de cima")])

    def test_without_display_config_it_falls_back_to_the_device_number(self) -> None:
        plain = win_desktop.number_monitors(RAW, [], {})
        self.assertEqual([m.device for m in plain], [r"\\.\DISPLAY1", r"\\.\DISPLAY2", r"\\.\DISPLAY3"])
        self.assertFalse(any(m.internal for m in plain))

    def test_hardware_id_from_device_path(self) -> None:
        path = r"\\?\DISPLAY#QHX2700#4&b182007&0&UID20550#{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}"
        self.assertEqual(win_desktop.hardware_id_from_path(path), "QHX2700#UID20550")
        self.assertEqual(win_desktop.hardware_id_from_path("", "fallback"), "fallback")

    def test_layout_description_has_numbers_and_names(self) -> None:
        text = win_desktop.describe_monitors(SCREENS)
        self.assertIn("tela 1: notebook, 1920x1200 horizontal, abaixo da principal", text)
        self.assertIn("tela 2: monitor vertical (GF270A)", text)
        self.assertIn("tela 3: monitor de cima (FY27QHCB), 2560x1440 horizontal, principal", text)


class FindMonitorTests(unittest.TestCase):
    def test_numbers_words_and_names(self) -> None:
        cases = {
            "1": NOTEBOOK, "tela 1": NOTEBOOK, "Tela um": NOTEBOOK, "notebook": NOTEBOOK, "a tela do notebook": NOTEBOOK,
            "de baixo": NOTEBOOK, "2": VERTICAL, "segunda": VERTICAL, "o monitor vertical": VERTICAL,
            "em pé": VERTICAL, "da esquerda": VERTICAL, "monitor de cima": TOP, "pro monitor de cima": TOP,
            "terceira tela": TOP, "principal": TOP, "horizontal": TOP,
        }  # fmt: skip
        for reference, expected in cases.items():
            with self.subTest(reference=reference):
                self.assertEqual(win_desktop.find_monitor(reference, SCREENS).number, expected.number)
        self.assertIs(win_desktop.find_monitor(3, SCREENS), TOP)

    def test_nicknames(self) -> None:
        screens = win_desktop.number_monitors(RAW, TARGETS, {"QHX2700#UID20550": {"apelidos": ["tela de código"]}})
        self.assertEqual(win_desktop.find_monitor("tela de código", screens).name, "vertical")
        self.assertEqual(win_desktop.find_monitor("na tela de codigo", screens).name, "vertical")
        self.assertEqual(win_desktop.find_monitor("código", screens).name, "vertical")
        self.assertIn("apelido 'tela de código'", win_desktop.describe_monitors(screens))

    def test_unknown_or_ambiguous_screens_are_errors_with_the_options(self) -> None:
        for reference in ("tela 7", "cozinha", "da direita", ""):
            with self.subTest(reference=reference), self.assertRaises(ValueError) as ctx:
                win_desktop.find_monitor(reference, SCREENS)
            if reference:
                self.assertIn("1 (notebook), 2 (vertical), 3 (de cima)", str(ctx.exception))


class ScreensDesktop(DesktopCase):
    """DesktopCase with the real three monitors, placements that keep their rect, and minimize."""

    def setUp(self) -> None:
        super().setUp()
        self.mock["monitors"].return_value = SCREENS
        self.mock["show"].side_effect = self.fake_show
        self.minimized: set[int] = set()
        self.normal: dict[int, tuple[int, int, int, int]] = {}
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for patcher in (
            patch.object(win_desktop, "SCREENS_FILE", self.folder / "telas.json"),
            patch.object(pc_control, "LAYOUTS_FILE", self.folder / "layouts.json"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.windows_now: list[win_desktop.Window] = []
        self.desktop = lambda: list(self.windows_now)

    def place(self, window: win_desktop.Window, screen: Monitor, rect: tuple[int, int, int, int] | None = None,
              maximized: bool = False) -> None:  # fmt: skip
        self.windows_now.append(window)
        self.screen_of[window.hwnd] = screen
        if rect is not None:
            self.normal[window.hwnd] = rect
        if maximized:
            self.maximized.add(window.hwnd)

    def fake_placement(self, hwnd: int) -> win_desktop.Placement | None:
        screen = self.screen_of.get(hwnd)
        if screen is None:
            return None
        left, top, right, bottom = screen.work
        normal = self.normal.get(hwnd, (left + 100, top + 100, right - 100, bottom - 100))
        if hwnd in self.minimized:
            show = win_desktop.SW_SHOWMINIMIZED
        else:
            show = win_desktop.SW_MAXIMIZE if hwnd in self.maximized else win_desktop.SW_SHOWNORMAL
        return win_desktop.Placement(0, show, (-1, -1), (-1, -1), normal)

    def fake_move(self, hwnd: int, screen: Monitor, maximize: bool | None = None, focus: bool = True) -> None:
        self.screen_of[hwnd] = screen
        self.normal.pop(hwnd, None)

    def fake_restore(self, hwnd: int, placement: win_desktop.Placement, focus: bool = True) -> None:
        self.screen_of[hwnd] = win_desktop.monitor_for_rect(placement.normal, SCREENS)
        self.normal[hwnd] = placement.normal
        self.minimized.discard(hwnd)
        self.maximized.discard(hwnd)
        if placement.maximized:
            self.maximized.add(hwnd)

    def fake_show(self, hwnd: int, command: int) -> None:
        if command == win_desktop.SW_MINIMIZE:
            self.minimized.add(hwnd)


HUD = win(1, "J.A.R.V.I.S. e mais 2 páginas - Pessoal - Microsoft\u200b Edge", "msedge.exe")
CHROME = win(10, "GitHub - Google Chrome", "chrome.exe")
PHPSTORM = win(11, "Jarvis-AI – tools.py", "phpstorm64.exe")
SPOTIFY = win(12, "Spotify Premium", "spotify.exe")


class ScreenNameToolTests(ScreensDesktop):
    def test_tela_1_is_the_notebook_not_display1(self) -> None:
        self.place(CHROME, TOP)
        result = pc_control.window_action("chrome", "move", "1")
        self.assertIs(self.screen_of[10], NOTEBOOK)
        self.assertIn("agora está no notebook (tela 1)", result)

    def test_screens_by_name_in_every_tool(self) -> None:
        self.place(CHROME, NOTEBOOK)
        self.assertIn("no monitor de cima (tela 3)", pc_control.window_action("chrome", "move", "monitor de cima"))
        self.assertIn("monitor vertical (tela 2) e maximizada", pc_control.window_action("chrome", "maximize", "vertical"))
        self.assertIn("voltou para onde estava: monitor de cima (tela 3)", pc_control.window_action("chrome", "back", None))
        self.assertIs(pc_control.pick_monitor("notebook"), NOTEBOOK)
        self.assertIs(pc_control.pick_monitor(""), TOP)  # vazio = nenhuma tela pedida → principal
        with self.assertRaises(PCControlError) as ctx:
            pc_control.window_action("chrome", "move", "cozinha")
        self.assertIn("Não sei qual é a tela 'cozinha'", str(ctx.exception))

    def test_capture_label_uses_the_name(self) -> None:
        with patch("pc_control.win_desktop.grab_monitor", return_value="imagem") as grab:
            image, label = pc_control.capture_screen("de cima")
        grab.assert_called_once_with(TOP)
        self.assertEqual((image, label), ("imagem", "monitor de cima (tela 3)"))

    def test_failed_move_names_both_screens(self) -> None:
        self.place(CHROME, TOP)
        self.mock["move"].side_effect = None  # o Windows ignorou o pedido
        result = pc_control.window_action("chrome", "move", "notebook")
        self.assertIn("para o notebook (tela 1), mas ela ficou no monitor de cima (tela 3)", result)


class ScreenSettingsTests(ScreensDesktop):
    def setUp(self) -> None:
        super().setUp()
        self.mock["monitors"].side_effect = lambda: win_desktop.number_monitors(
            RAW, TARGETS, win_desktop.load_screen_config()
        )

    def saved(self) -> dict[str, Any]:
        return json.loads((self.folder / "telas.json").read_text(encoding="utf-8"))

    def test_list_says_the_numbering_is_estimated_until_confirmed(self) -> None:
        self.assertIn("estimada", screens_action("list"))
        self.assertIn("tela 1 = notebook, tela 2 = monitor vertical, tela 3 = monitor de cima", screens_action("confirm"))
        self.assertEqual(self.saved()["CMN1441#UID8388688"]["numero"], 1)
        self.assertIn("confirmada", screens_action("list"))

    def test_nickname_is_saved_and_works_everywhere(self) -> None:
        result = screens_action("nickname", screen="vertical", name="tela de código")
        self.assertIn("monitor vertical (tela 2) agora também atende por 'tela de código'", result)
        self.assertEqual(self.saved()["QHX2700#UID20550"]["apelidos"], ["tela de código"])
        self.assertEqual(pc_control.pick_monitor("tela de código").number, 2)

        with self.assertRaises(PCControlError):
            screens_action("nickname", screen="notebook", name="vertical")  # já é o nome de outra tela
        with self.assertRaises(PCControlError):
            screens_action("nickname", screen="notebook", name="tela 2")

        self.assertIn("Esqueci", screens_action("forget_nickname", name="Tela de Código"))
        with self.assertRaises(PCControlError):
            pc_control.pick_monitor("tela de código")

    def test_renumber_swaps_with_the_screen_that_had_the_number(self) -> None:
        result = screens_action("renumber", screen="de cima", number=1)
        self.assertIn("tela 1 = monitor de cima, tela 2 = monitor vertical, tela 3 = notebook", result)
        self.assertEqual(pc_control.pick_monitor("1").name, "de cima")
        with self.assertRaises(PCControlError):
            screens_action("renumber", screen="notebook", number=4)


class FourWindows(ScreensDesktop):
    def setUp(self) -> None:
        super().setUp()
        self.place(HUD, TOP)
        self.place(CHROME, TOP, maximized=True)
        self.place(PHPSTORM, VERTICAL, rect=(-1300, 300, -200, 1500))
        self.place(SPOTIFY, NOTEBOOK)


class BulkTests(FourWindows):
    def test_gather_everything_on_the_notebook_and_undo(self) -> None:
        result = arrange_action("gather", "notebook")
        self.assertIn("Levei 2 janelas para o notebook (tela 1)", result)
        self.assertIn("HUD ficou onde estava", result)
        self.assertIs(self.screen_of[1], TOP)  # o HUD não sai do lugar
        self.assertEqual([self.screen_of[h] for h in (10, 11, 12)], [NOTEBOOK] * 3)
        self.assertNotIn(12, self.moved_hwnds())  # já estava lá

        result = arrange_action("undo")
        self.assertIn("2 janelas de volta", result)
        self.assertIs(self.screen_of[10], TOP)
        self.assertIn(10, self.maximized)
        self.assertEqual(self.normal[11], (-1300, 300, -200, 1500))
        self.assertEqual(pc_control.MEMORY.positions, {})  # o desfazer consome a mesma memória do 'back'
        with self.assertRaises(PCControlError):
            arrange_action("undo")

    def test_move_everything_from_one_screen_to_another(self) -> None:
        result = arrange_action("move_all", "de cima", "notebook")
        self.assertIn("Levei 1 janela para o monitor de cima (tela 3): 'Spotify Premium'", result)
        self.assertEqual(self.moved_hwnds(), [12])
        self.assertIn("Não há janelas abertas no notebook (tela 1)", arrange_action("move_all", "vertical", "notebook"))

    def test_single_window_back_still_works_after_a_batch(self) -> None:
        arrange_action("gather", "notebook")
        self.assertIn("voltou para onde estava: monitor vertical (tela 2)", pc_control.window_action("phpstorm", "back", None))
        self.assertIn("1 janela de volta", arrange_action("undo"))  # só o Chrome faltava voltar
        self.assertIs(self.screen_of[10], TOP)

    def test_show_desktop_minimizes_all_but_the_hud_and_undo_brings_them_back(self) -> None:
        result = arrange_action("show_desktop")
        self.assertIn("Minimizei 3 janelas", result)
        self.assertEqual(self.minimized, {10, 11, 12})
        result = arrange_action("undo")
        self.assertIn("3 janelas de volta", result)
        self.assertEqual(self.minimized, set())
        focus = {call.args[0]: call.kwargs.get("focus") for call in self.mock["restore"].call_args_list}
        self.assertEqual(focus, {12: False, 11: False, 10: True})  # a de cima da pilha volta por último, em foco

    def test_bulk_actions_need_screens(self) -> None:
        with self.assertRaises(PCControlError):
            arrange_action("gather", None)
        with self.assertRaises(PCControlError):
            arrange_action("move_all", "notebook", "notebook")


class LayoutTests(FourWindows):
    def saved_layouts(self) -> dict[str, Any]:
        return json.loads((self.folder / "layouts.json").read_text(encoding="utf-8"))

    def test_save_captures_app_screen_and_relative_position(self) -> None:
        result = save_layout("modo trabalho")
        self.assertIn("Layout 'trabalho' salvo: 4 janelas", result)
        entries = self.saved_layouts()["trabalho"]["janelas"]
        phpstorm = next(entry for entry in entries if entry["processo"] == "phpstorm64.exe")
        self.assertEqual(phpstorm["app"], "phpstorm")
        self.assertEqual((phpstorm["tela"], phpstorm["tela_id"], phpstorm["tela_nome"]), (2, "QHX2700#UID20550", "vertical"))
        self.assertEqual(phpstorm["posicao"], [140, 176, 1240, 1376])
        chrome = next(entry for entry in entries if entry["processo"] == "chrome.exe")
        self.assertEqual((chrome["app"], chrome["maximizada"]), ("chrome", True))

    def test_apply_reopens_missing_apps_puts_windows_back_and_undo(self) -> None:
        save_layout("trabalho")
        arrange_action("gather", "vertical")
        self.windows_now.remove(SPOTIFY)
        del self.screen_of[12]

        def launch(name: str, monitor: Any = None) -> str:
            self.place(win(13, "Spotify Free", "spotify.exe"), VERTICAL)
            return "Abri Spotify."

        with patch("pc_control.resolve_app", return_value=("Spotify", "shell:AppsFolder\\Spotify", False)), patch(
            "pc_control.launch_app", side_effect=launch
        ) as launched:
            result = layouts_action("apply", "modo trabalho")

        launched.assert_called_once_with("spotify")
        self.assertIn("Layout 'trabalho' aplicado: 4 janelas no lugar", result)
        self.assertIn("Abri spotify", result)
        self.assertIs(self.screen_of[10], TOP)
        self.assertIn(10, self.maximized)
        self.assertEqual(self.normal[11], (-1300, 300, -200, 1500))
        self.assertIs(self.screen_of[13], NOTEBOOK)

        self.assertIn("layout 'trabalho'", arrange_action("undo"))
        self.assertEqual([self.screen_of[h] for h in (10, 11, 13)], [VERTICAL] * 3)

    def test_layout_follows_the_physical_monitor_when_numbers_change(self) -> None:
        save_layout("trabalho")
        renumbered = win_desktop.number_monitors(RAW, TARGETS, {"QHX2700#UID20550": {"numero": 3}})
        self.mock["monitors"].return_value = renumbered
        arrange_action("gather", "notebook")
        apply_layout("trabalho")
        self.assertEqual(self.screen_of[11].hardware_id, "QHX2700#UID20550")  # a vertical, agora "tela 3"

    def test_apps_that_cannot_be_reopened_are_reported(self) -> None:
        save_layout("trabalho")
        self.windows_now.remove(CHROME)
        with patch("pc_control.resolve_app", return_value=("Chrome", "https://chrome.com", True)):
            result = apply_layout("trabalho")
        self.assertIn("Não abri: chrome (não é um app instalado)", result)
        self.assertIn("3 janelas no lugar", result)

    def test_list_and_delete(self) -> None:
        self.assertIn("Nenhum layout salvo", layouts_action("list"))
        save_layout("trabalho")
        save_layout("Estudo")
        self.assertIn("(substituí o anterior com esse nome)", save_layout("modo trabalho"))
        listing = layouts_action("list")
        self.assertIn("'trabalho' (4 janelas", listing)
        self.assertIn("'Estudo'", listing)
        with self.assertRaises(PCControlError):
            layouts_action("delete", "trab")  # apagar exige o nome certo
        self.assertIn("apagado", layouts_action("delete", "layout trabalho"))
        self.assertEqual(list(self.saved_layouts()), ["Estudo"])
        with self.assertRaises(PCControlError):
            layouts_action("apply", "jogo")


class PromptTests(unittest.TestCase):
    def test_prompt_teaches_screen_names_layouts_and_batch_undo(self) -> None:
        for text in ('monitor="notebook"', "manage_screens(nickname", "manage_layouts(apply", "arrange_windows(undo)"):
            self.assertIn(text, AGENT_INSTRUCTION)
        self.assertIn("Identificar", AGENT_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
