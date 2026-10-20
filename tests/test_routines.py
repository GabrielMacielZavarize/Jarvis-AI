from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import routines
from routines import (
    PENDING_ROUTINE_S,
    RoutineError,
    RoutineScheduler,
    build_report,
    claim_scheduled,
    confirm_routine_step,
    default_routines,
    delete_routine,
    describe_schedule,
    execute_routine,
    find_routine,
    is_failure,
    list_routines,
    load_routines,
    parse_days,
    parse_step,
    parse_time,
    run_routine,
    run_scheduled,
    save_routine,
    save_routines,
    schedule_routine,
    summary_for_prompt,
    user_said_yes,
)
from settings import load_settings
from test_tools import FakeMessage, FakeRunContext
from wake_hub import PENDING_BROWSER_S, WakeHub

PC_SETTINGS = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_PC_CONTROL": "true", "JARVIS_HOME_CITY": "Criciúma"})
NO_PC_SETTINGS = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_HOME_CITY": "Criciúma"})
MONDAY = dt.datetime(2026, 10, 19, 8, 0, 5)  # segunda-feira
SATURDAY = dt.datetime(2026, 10, 24, 8, 0, 5)


def user(*texts: str) -> list[FakeMessage]:
    return [FakeMessage("user", text) for text in texts]


class StoreCase(unittest.IsolatedAsyncioTestCase):
    """Every test gets its own rotinas.json, HUD publishing off and a fixed clock."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / "rotinas.json"
        for target, value in (
            ("routines.ROUTINES_FILE", self.file),
            ("routines.CONFIRMATION_WAIT_SECONDS", 0.0),
            ("routines._now", lambda: MONDAY),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cards: list[dict] = []
        show = patch("routines.show_card", AsyncMock(side_effect=lambda kind, data: self.cards.append(json.loads(json.dumps(data))) or True))
        show.start()
        self.addCleanup(show.stop)
        status = patch("routines.tool_status", AsyncMock(return_value=True))
        status.start()
        self.addCleanup(status.stop)
        self.settings = patch("routines._settings", return_value=PC_SETTINGS)
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def tools(self, **overrides: object) -> dict[str, AsyncMock]:
        """Fake every tool a routine can call; each returns a plain success line by default."""
        answers = {
            ("tools", "get_weather"): "Criciúma: 22 °C, céu limpo.",
            ("tools", "search_news"): "1. Manchete A (G1)\n2. Manchete B (Folha)",
            ("tools", "set_timer"): "Timer 'Pomodoro' iniciado para 25 minutos.",
            ("tools", "show_on_hud"): "Painel exibido no HUD.",
            ("pc_control", "manage_layouts"): "Layout 'trabalho' aplicado: 4 janelas no lugar.",
            ("pc_control", "play_youtube"): "Abri 'Lo-fi beats' do canal Lofi Girl, AO VIVO.",
            ("pc_control", "open_app"): "Abri o Notion.",
            ("pc_control", "set_volume"): "Volume em 15%.",
            ("pc_control", "arrange_windows"): "Minimizei 5 janelas.",
            ("pc_control", "media_control"): "Tecla de mídia 'stop' enviada.",
            ("pc_control", "lock_computer"): "Tela bloqueada.",
            ("pc_control", "close_app"): "Fechei o Discord.",
        }
        mocks: dict[str, AsyncMock] = {}
        for (module, name), answer in answers.items():
            value = overrides.get(name, answer)
            mock = value if isinstance(value, AsyncMock) else AsyncMock(return_value=value)
            mocks[name] = mock
            patcher = patch(f"{module}.{name}", mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        reminders = patch("routines.reminders_text", return_value="Lembretes: Reunião de segunda-feira às 9h.")
        reminders.start()
        self.addCleanup(reminders.stop)
        return mocks


class StepParsingTests(unittest.TestCase):
    def test_reads_actions_in_english_or_portuguese(self) -> None:
        self.assertEqual(parse_step("app: Notion").raw, "app: Notion")
        self.assertEqual(parse_step("abrir: Notion").raw, "app: Notion")
        self.assertEqual(parse_step("Música: lo-fi para estudar").raw, "youtube: lo-fi para estudar")
        self.assertEqual(parse_step("midia: pausar").raw, "media: stop")
        self.assertEqual(parse_step("volume: 20%").raw, "volume: 20")
        self.assertEqual(parse_step("volume: mudo").raw, "volume: mute")
        self.assertEqual(parse_step("clima").raw, "weather")
        self.assertEqual(parse_step("bloquear").raw, "lock")

    def test_refuses_what_a_routine_cannot_do(self) -> None:
        for raw in ("email: chefe@empresa.com", "instalar: VLC", "clique: botão comprar", "", "volume: 300", "timer: logo", "app:"):
            with self.subTest(raw=raw), self.assertRaises(RoutineError):
                parse_step(raw)

    def test_only_locking_and_closing_apps_are_dangerous(self) -> None:
        self.assertEqual({name for name, action in routines.ACTIONS.items() if action.dangerous}, {"lock", "close"})
        self.assertTrue(parse_step("fechar: Discord").dangerous)
        self.assertFalse(parse_step("app: Discord").dangerous)

    def test_failure_detection_of_tool_answers(self) -> None:
        for text in (
            "Não tenho um layout chamado 'trabalho'. Salvos: estudo.",
            "Não encontrei nenhum app ou site conhecido chamado 'Notio'.",
            "Cidade 'Xyz' não encontrada.",
            "Ocorreu um erro ao buscar notícias sobre 'tecnologia'.",
            "Bloquear a tela só está disponível no Windows por enquanto.",
            "NADA foi fechado: o HUD não está conectado.",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_failure(text))
        for text in ("Abri o Notion.", "Volume em 15%.", "Timer 'Pomodoro' iniciado para 25 minutos.",
                     "Não há janelas abertas para minimizar: a área de trabalho já está à mostra."):
            with self.subTest(text=text):
                self.assertFalse(is_failure(text))


class ScheduleParsingTests(unittest.TestCase):
    def test_days(self) -> None:
        self.assertEqual(parse_days("todo dia útil"), (0, 1, 2, 3, 4))
        self.assertEqual(parse_days("dias úteis"), (0, 1, 2, 3, 4))
        self.assertEqual(parse_days("todos os dias"), tuple(range(7)))
        self.assertEqual(parse_days("fim de semana"), (5, 6))
        self.assertEqual(parse_days("segunda, quarta e sexta"), (0, 2, 4))
        self.assertEqual(parse_days("sábados"), (5,))
        self.assertEqual(parse_days("de segunda a quinta"), (0, 1, 2, 3))
        with self.assertRaises(RoutineError):
            parse_days("quando der")

    def test_times(self) -> None:
        self.assertEqual(parse_time("8h"), "08:00")
        self.assertEqual(parse_time("às 08:00"), "08:00")
        self.assertEqual(parse_time("7h30"), "07:30")
        self.assertEqual(parse_time("8 e meia"), "08:30")
        self.assertEqual(parse_time("10 da noite"), "22:00")
        for bad in ("cedo", "25h", "8:75"):
            with self.subTest(bad=bad), self.assertRaises(RoutineError):
                parse_time(bad)

    def test_description(self) -> None:
        self.assertEqual(describe_schedule({"days": [0, 1, 2, 3, 4], "time": "08:00"}), "dias úteis às 8h")
        self.assertEqual(describe_schedule({"days": [0, 2], "time": "07:30"}), "segunda e quarta às 7h30")
        self.assertIsNone(describe_schedule(None))


class StorageTests(StoreCase):
    def test_first_run_uses_the_factory_routines(self) -> None:
        loaded = load_routines()
        self.assertEqual(list(loaded), ["bom dia", "modo foco", "modo jogo", "boa noite"])
        self.assertIn("layout: trabalho", loaded["bom dia"]["steps"])
        self.assertIn("timer: 25 Pomodoro", loaded["modo foco"]["steps"])
        self.assertEqual(loaded["boa noite"]["steps"][-1], "lock")
        self.assertFalse(self.file.exists())

    def test_round_trip_and_bad_entries_are_dropped(self) -> None:
        data = default_routines()
        data["estudo"] = {"name": "Estudo", "aliases": [], "steps": ["app: Notion", "email: x"], "schedule": {"days": "dias úteis", "time": "8h"}}
        data["vazia"] = {"name": "Vazia", "steps": ["email: x"]}
        save_routines(data)
        loaded = load_routines()
        self.assertEqual(loaded["estudo"]["steps"], ["app: Notion"])
        self.assertEqual(loaded["estudo"]["schedule"], {"days": [0, 1, 2, 3, 4], "time": "08:00", "enabled": True})
        self.assertNotIn("vazia", loaded)

    def test_a_corrupted_file_is_not_overwritten(self) -> None:
        self.file.write_text("{not json", encoding="utf-8")
        self.assertEqual(list(load_routines()), list(default_routines()))
        self.assertEqual(self.file.read_text(encoding="utf-8"), "{not json")

    def test_finds_a_routine_the_way_it_is_spoken(self) -> None:
        saved = {**default_routines(), "estudo": {"name": "Estudo", "aliases": [], "steps": ["app: Notion"], "schedule": None}}
        for spoken, key in (
            ("Bom dia, Jarvis", "bom dia"),
            ("modo foco", "modo foco"),
            ("foco", "modo foco"),
            ("ativa o modo jogo", "modo jogo"),
            ("rotina de estudo", "estudo"),
            ("boa noitê", "boa noite"),
        ):
            with self.subTest(spoken=spoken):
                self.assertEqual(find_routine(spoken, saved), key)
        with self.assertRaises(RoutineError):
            find_routine("modo festa", saved)

    def test_prompt_summary_lists_names_and_schedule(self) -> None:
        data = default_routines()
        data["bom dia"]["schedule"] = {"days": [0, 1, 2, 3, 4], "time": "08:00", "enabled": True}
        summary = summary_for_prompt(data)
        self.assertIn("- Bom dia (também: bom dia jarvis, rotina da manha, manha; agendada dias úteis às 8h)", summary)
        self.assertIn("- Modo foco", summary)


class ExecutionTests(StoreCase):
    async def test_good_morning_runs_every_step_in_order(self) -> None:
        mocks = self.tools()
        context = FakeRunContext(messages=user("Bom dia, Jarvis"))

        result = await run_routine(context, name="bom dia jarvis")

        mocks["get_weather"].assert_awaited_once_with(context, city="Criciúma")
        mocks["search_news"].assert_awaited_once()
        mocks["manage_layouts"].assert_awaited_once_with(context, action="apply", name="trabalho")
        mocks["play_youtube"].assert_awaited_once_with(context, query="playlist lo-fi para trabalhar")
        self.assertIn("Rotina 'Bom dia': 6 de 6 passos concluídos.", result)
        self.assertIn("Bom dia, senhor. Agora são 08:00 de segunda-feira, 19 de outubro.", result)
        self.assertIn("Criciúma: 22 °C", result)
        self.assertIn("Reunião de segunda-feira às 9h", result)
        self.assertNotIn("FALHOU", result)
        final = self.cards[-1]
        self.assertEqual(final["status"], "done")
        self.assertEqual(final["trigger"], "voz")
        self.assertEqual([step["status"] for step in final["steps"]], ["ok"] * 6)
        self.assertEqual(final["steps"][1]["label"], "Clima em Criciúma")
        # The panel showed each step running before it finished.
        self.assertIn("running", [step["status"] for card in self.cards for step in card["steps"]])

    async def test_a_failed_step_does_not_stop_the_others(self) -> None:
        mocks = self.tools(
            manage_layouts="Não tenho um layout chamado 'trabalho'. Salvos: nenhum.",
            search_news=AsyncMock(side_effect=RuntimeError("DDGS caiu")),
        )

        result = await run_routine(FakeRunContext(messages=user("bom dia jarvis")), name="bom dia")

        mocks["play_youtube"].assert_awaited_once()
        self.assertIn("4 de 6 passos concluídos", result)
        self.assertIn("Layout · trabalho: FALHOU — Não tenho um layout chamado 'trabalho'", result)
        self.assertIn("Notícias · principais notícias do Brasil hoje: FALHOU — erro inesperado (RuntimeError).", result)
        self.assertIn("Diga claramente o que falhou", result)
        self.assertEqual(self.cards[-1]["status"], "partial")
        self.assertEqual([s["status"] for s in self.cards[-1]["steps"]], ["ok", "ok", "error", "ok", "error", "ok"])

    async def test_a_stuck_step_times_out(self) -> None:
        async def never(*_: object, **__: object) -> str:
            await asyncio.sleep(5)
            return "nunca"

        self.tools(play_youtube=AsyncMock(side_effect=never))
        with patch("routines.STEP_TIMEOUT_S", 0.05):
            result = await run_routine(FakeRunContext(messages=user("bom dia")), name="bom dia")
        self.assertIn("YouTube · playlist lo-fi para trabalhar: FALHOU — não terminou em 0.05 segundos.", result)

    async def test_without_pc_control_the_pc_steps_fail_and_the_rest_runs(self) -> None:
        mocks = self.tools()
        self.settings.stop()
        with patch("routines._settings", return_value=NO_PC_SETTINGS):
            result = await run_routine(FakeRunContext(messages=user("bom dia")), name="bom dia")
        self.settings.start()
        mocks["manage_layouts"].assert_not_awaited()
        mocks["get_weather"].assert_awaited_once()
        self.assertIn("4 de 6 passos concluídos", result)
        self.assertIn("JARVIS_ENABLE_PC_CONTROL=true", result)

    async def test_focus_mode_minimizes_lowers_the_volume_and_starts_a_pomodoro(self) -> None:
        mocks = self.tools()
        context = FakeRunContext(messages=user("modo foco"))
        await run_routine(context, name="modo foco")
        mocks["arrange_windows"].assert_awaited_once_with(context, action="show_desktop")
        mocks["set_volume"].assert_awaited_once_with(context, action="set", level=15)
        mocks["set_timer"].assert_awaited_once_with(context, minutes=25.0, label="Pomodoro")

    async def test_unknown_routine(self) -> None:
        self.assertIn("Não tenho uma rotina chamada 'festa'", await run_routine(FakeRunContext(), name="festa"))

    async def test_list_shows_the_routines(self) -> None:
        result = await list_routines(FakeRunContext())
        self.assertIn("Boa noite: Cumprimento, Salvar layout · noite, Pausar a mídia, Bloquear o PC", result)


class DangerousStepTests(StoreCase):
    async def test_good_night_never_locks_without_a_new_yes(self) -> None:
        mocks = self.tools()
        context = FakeRunContext(messages=user("boa noite, Jarvis"))

        result = await run_routine(context, name="boa noite")

        mocks["lock_computer"].assert_not_awaited()
        mocks["manage_layouts"].assert_awaited_once_with(context, action="save", name="noite")
        mocks["media_control"].assert_awaited_once_with(context, action="stop")
        self.assertIn("PRECISA CONFIRMAÇÃO: falta bloquear o pc", result)
        self.assertEqual(self.cards[-1]["status"], "confirm")

        # The model confirming on its own, with the request that started the routine, does nothing.
        refused = await confirm_routine_step(context)
        self.assertIn("NADA foi feito", refused)
        mocks["lock_computer"].assert_not_awaited()

        context.session.history.messages().append(FakeMessage("assistant", "Posso bloquear o computador?"))
        context.session.history.messages().append(FakeMessage("user", "não, espera"))
        self.assertIn("NADA foi feito", await confirm_routine_step(context))

        context.session.history.messages().append(FakeMessage("user", "sim, pode bloquear"))
        done = await confirm_routine_step(context)
        mocks["lock_computer"].assert_awaited_once()
        self.assertEqual(done, "Bloquear o PC: feito.")
        self.assertEqual(self.cards[-1]["status"], "done")
        self.assertIn("Não há nenhum passo", await confirm_routine_step(context))

    async def test_cancel_and_expiry(self) -> None:
        mocks = self.tools()
        context = FakeRunContext(messages=user("boa noite"))
        await run_routine(context, name="boa noite")
        self.assertIn("ficou de fora", await confirm_routine_step(context, cancel=True))
        self.assertEqual(self.cards[-1]["steps"][-1]["status"], "cancelled")

        await run_routine(context, name="boa noite")
        context.userdata[routines.PENDING_KEY]["expires"] = 0
        context.session.history.messages().append(FakeMessage("user", "sim"))
        self.assertIn("Não há nenhum passo", await confirm_routine_step(context))
        mocks["lock_computer"].assert_not_awaited()

    def test_yes_grammar(self) -> None:
        for text in ("sim", "Sim, pode.", "pode bloquear", "Jarvis, pode", "claro", "ok"):
            with self.subTest(text=text):
                self.assertTrue(user_said_yes(text))
        for text in ("não", "pode não", "espera", "boa noite jarvis", "", "sim mas cancela", "deixa pra lá"):
            with self.subTest(text=text):
                self.assertFalse(user_said_yes(text))


class EditingTests(StoreCase):
    async def test_creates_a_routine_from_the_users_request(self) -> None:
        context = FakeRunContext(messages=user("Cria uma rotina estudo que abre o Notion e põe lo-fi"))
        result = await save_routine(context, name="estudo", steps=["app: Notion", "youtube: lo-fi para estudar"])

        self.assertEqual(result, "Rotina 'estudo' criada: Abrir app · Notion, YouTube · lo-fi para estudar.")
        saved = json.loads(self.file.read_text(encoding="utf-8"))["routines"]["estudo"]
        self.assertEqual(saved["steps"], ["app: Notion", "youtube: lo-fi para estudar"])
        self.assertIn("bom dia", load_routines())

        mocks = self.tools()
        await run_routine(FakeRunContext(messages=user("roda a rotina estudo")), name="estudo")
        mocks["open_app"].assert_awaited_once()
        mocks["play_youtube"].assert_awaited_once()

    async def test_edits_append_and_replace(self) -> None:
        context = FakeRunContext(messages=user("coloca um timer de 50 minutos no modo foco"))
        await save_routine(context, name="foco", steps=["timer: 50 Foco longo"], mode="append")
        self.assertEqual(load_routines()["modo foco"]["steps"][-1], "timer: 50 Foco longo")
        self.assertEqual(len(load_routines()["modo foco"]["steps"]), 5)

        await save_routine(context, name="modo foco", steps=["minimize", "volume: 10"])
        self.assertEqual(load_routines()["modo foco"]["steps"], ["minimize", "volume: 10"])

    async def test_a_similar_new_name_creates_a_new_routine(self) -> None:
        context = FakeRunContext(messages=user("cria a rotina jogo 2 que abre o Minecraft"))
        await save_routine(context, name="jogo 2", steps=["app: Minecraft"])
        saved = load_routines()
        self.assertEqual(saved["jogo 2"]["steps"], ["app: Minecraft"])
        self.assertEqual(saved["modo jogo"]["steps"], default_routines()["modo jogo"]["steps"])

    async def test_warns_that_dangerous_steps_will_ask(self) -> None:
        context = FakeRunContext(messages=user("cria a rotina saída que fecha o Discord"))
        result = await save_routine(context, name="saída", steps=["close: Discord"])
        self.assertIn("sempre vão pedir confirmação", result)

    async def test_refuses_invalid_steps_and_requests_that_did_not_come_from_the_user(self) -> None:
        context = FakeRunContext(messages=user("cria uma rotina relatório"))
        self.assertIn("NADA foi salvo: Não sei fazer o passo 'email: chefe@x.com'", await save_routine(context, name="relatório", steps=["email: chefe@x.com"]))

        # A page or email the model read asked for it; the user talked about something else.
        injected = FakeRunContext(messages=user("lê esse site pra mim"))
        self.assertEqual(await save_routine(injected, name="backdoor", steps=["site: evil.example"]), routines.NOT_ASKED)
        self.assertEqual(await delete_routine(injected, name="bom dia"), routines.NOT_ASKED)
        self.assertEqual(await schedule_routine(injected, name="boa noite", time_of_day="3h"), routines.NOT_ASKED)
        self.assertFalse(self.file.exists())

    async def test_delete(self) -> None:
        context = FakeRunContext(messages=user("apaga a rotina modo jogo"))
        self.assertEqual(await delete_routine(context, name="modo jogo"), "Rotina 'Modo jogo' apagada.")
        self.assertNotIn("modo jogo", load_routines())

    async def test_schedule_and_cancel(self) -> None:
        context = FakeRunContext(messages=user("todo dia útil às 8h roda o bom dia"))
        result = await schedule_routine(context, name="bom dia", time_of_day="8h", days="todo dia útil")
        self.assertIn("Rotina 'Bom dia' agendada: dias úteis às 8h.", result)
        self.assertEqual(load_routines()["bom dia"]["schedule"], {"days": [0, 1, 2, 3, 4], "time": "08:00", "enabled": True})

        context = FakeRunContext(messages=user("para de rodar o bom dia sozinho"))
        self.assertIn("não roda mais sozinha", await schedule_routine(context, name="bom dia", cancel=True))
        self.assertIsNone(load_routines()["bom dia"]["schedule"])


class FakeMonotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = default_routines()
        self.data["bom dia"]["schedule"] = {"days": [0, 1, 2, 3, 4], "time": "08:00", "enabled": True}
        self.wall = MONDAY.replace(hour=7, minute=59, second=0)
        self.mono = FakeMonotonic()
        self.due: list[str] = []
        self.scheduler = RoutineScheduler(load=lambda: self.data, now=lambda: self.wall, monotonic=self.mono, on_due=self.due.append)

    def test_fires_once_a_day_at_the_time(self) -> None:
        self.assertEqual(self.scheduler.tick(), [])
        self.wall = MONDAY  # 08:00:05
        self.assertEqual(self.scheduler.tick(), ["bom dia"])
        self.wall = MONDAY.replace(minute=1)
        self.assertEqual(self.scheduler.tick(), [])
        self.assertEqual(self.due, ["bom dia"])

        self.wall = MONDAY + dt.timedelta(days=1)  # terça, 08:00:05
        self.assertEqual(self.scheduler.tick(), ["bom dia"])
        self.assertEqual(self.scheduler.scheduled_count(), 1)

    def test_skips_other_days_and_catches_up_only_briefly(self) -> None:
        self.wall = SATURDAY
        self.assertEqual(self.scheduler.tick(), [])
        self.wall = MONDAY.replace(minute=9)  # PC acordou às 8h09
        self.assertEqual(self.scheduler.tick(), ["bom dia"])
        self.scheduler.fired.clear()
        self.wall = MONDAY.replace(minute=11)
        self.assertEqual(self.scheduler.tick(), [])

    def test_disabled_schedule_never_fires(self) -> None:
        self.data["bom dia"]["schedule"]["enabled"] = False
        self.wall = MONDAY
        self.assertEqual(self.scheduler.tick(), [])
        self.assertEqual(self.scheduler.scheduled_count(), 0)

    def test_the_agent_claims_each_fired_routine_once_until_it_expires(self) -> None:
        self.wall = MONDAY
        self.scheduler.tick()
        self.assertEqual(self.scheduler.claim(), "bom dia")
        self.assertIsNone(self.scheduler.claim())

        self.wall = MONDAY + dt.timedelta(days=1)
        self.scheduler.tick()
        self.mono.now += PENDING_ROUTINE_S + 1  # o link nunca abriu
        self.assertIsNone(self.scheduler.claim())

    def test_a_broken_trigger_does_not_stop_the_scheduler(self) -> None:
        self.scheduler.on_due = MagicMock(side_effect=RuntimeError("navegador"))
        self.wall = MONDAY
        self.assertEqual(self.scheduler.tick(), ["bom dia"])
        self.assertEqual(self.scheduler.claim(), "bom dia")


class WakeRoutineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeMonotonic()
        self.hub = WakeHub(clock=self.clock)

    def test_open_tab_gets_the_wake_with_the_routine(self) -> None:
        client = self.hub.connect("tab-12345678")
        self.assertEqual(self.hub.trigger_routine("bom dia"), {"accepted": True, "opened_browser": False})
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 1.0, "routine": "bom dia"})
        self.assertFalse(self.hub.listening())  # o detector não disputa o microfone

    def test_without_a_tab_the_browser_opens_and_the_first_tab_gets_it(self) -> None:
        self.assertEqual(self.hub.trigger_routine("bom dia"), {"accepted": True, "opened_browser": True})
        self.clock.now += PENDING_BROWSER_S - 1
        client = self.hub.connect("tab-12345678")
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 1.0, "routine": "bom dia"})

    def test_an_open_conversation_needs_no_wake(self) -> None:
        client = self.hub.connect("tab-12345678")
        self.hub.update("tab-12345678", session_active=True, visible=True, mic_label=None)
        self.assertEqual(self.hub.trigger_routine("bom dia"), {"accepted": False, "opened_browser": False})
        self.assertTrue(client.queue.empty())

    def test_plain_wakes_carry_no_routine(self) -> None:
        client = self.hub.connect("tab-12345678")
        self.hub.trigger(0.9)
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 0.9})


class ServerRoutineTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = default_routines()
        self.data["bom dia"]["schedule"] = {"days": [0, 1, 2, 3, 4], "time": "08:00", "enabled": True}
        self.scheduler = RoutineScheduler(load=lambda: self.data, now=lambda: MONDAY)
        self.opened: list[str] = []
        from server import create_app

        self.app = create_app(reload_env=False, routine_scheduler=self.scheduler, open_browser=self.opened.append)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")

    def test_status_and_claim(self) -> None:
        body = self.client.get("/api/status").json()
        self.assertEqual(body["routines"], {"enabled": True, "scheduled": 1, "context_triggers": 0})
        self.assertEqual(self.client.post("/api/routines/claim").json(), {"routine": None})

        self.scheduler.tick()
        self.assertEqual(self.client.post("/api/routines/claim").json(), {"routine": "bom dia"})
        self.assertEqual(self.client.post("/api/routines/claim").json(), {"routine": None})

    def test_due_routine_opens_the_browser_when_no_tab_is_open(self) -> None:
        self.app.state.hud_url = "http://127.0.0.1:8000"
        with patch("server.threading.Thread") as thread:
            self.scheduler.tick()
        thread.assert_called_once_with(target=self.opened.append, args=("http://127.0.0.1:8000",), daemon=True)
        self.assertEqual(self.app.state.wake_hub.undelivered_routine, "bom dia")

    def test_claim_only_answers_this_computer(self) -> None:
        other = TestClient(self.app, base_url="http://jarvis.example.com")
        self.assertEqual(other.post("/api/routines/claim").status_code, 403)
        cross_site = self.client.post("/api/routines/claim", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(cross_site.status_code, 403)


class FakeAgentSession:
    def __init__(self) -> None:
        self.userdata: dict = {}
        self.replies: list[str] = []

    def generate_reply(self, *, instructions: str) -> None:
        self.replies.append(instructions)


class AgentSideTests(StoreCase):
    async def test_scheduled_run_speaks_the_result(self) -> None:
        mocks = self.tools(manage_layouts="Não tenho um layout chamado 'trabalho'.")
        session = FakeAgentSession()

        run = await run_scheduled(session, "bom dia")

        self.assertEqual(run.status, "partial")
        mocks["play_youtube"].assert_awaited_once()
        self.assertEqual(self.cards[-1]["trigger"], "agenda")
        self.assertEqual(len(session.replies), 1)
        self.assertIn("A rotina agendada 'Bom dia' acabou de rodar sozinha", session.replies[0])
        self.assertIn("Layout · trabalho: FALHOU", session.replies[0])

    async def test_scheduled_good_night_still_waits_for_the_yes(self) -> None:
        mocks = self.tools()
        session = FakeAgentSession()
        await run_scheduled(session, "boa noite")
        mocks["lock_computer"].assert_not_awaited()
        self.assertIn("PRECISA CONFIRMAÇÃO", session.replies[0])

    async def test_two_runs_of_the_same_routine_do_not_overlap(self) -> None:
        release = asyncio.Event()

        async def slow(*_: object, **__: object) -> str:
            await release.wait()
            return "Abri."

        self.tools(play_youtube=AsyncMock(side_effect=slow))
        first = asyncio.create_task(run_routine(FakeRunContext(messages=user("bom dia")), name="bom dia"))
        await asyncio.sleep(0.01)
        self.assertEqual(await run_routine(FakeRunContext(messages=user("bom dia")), name="bom dia"), "A rotina 'Bom dia' já está rodando.")
        release.set()
        self.assertIn("6 de 6", await first)

    def test_claim_scheduled(self) -> None:
        response = MagicMock()
        response.json.return_value = {"routine": "bom dia"}
        post = MagicMock(return_value=response)
        self.assertEqual(claim_scheduled("http://127.0.0.1:8000/", post=post), "bom dia")
        post.assert_called_once_with("http://127.0.0.1:8000/api/routines/claim", timeout=3)

        response.json.return_value = {"routine": None}
        self.assertIsNone(claim_scheduled("http://127.0.0.1:8000", post=post))
        self.assertIsNone(claim_scheduled("http://127.0.0.1:8000", post=MagicMock(side_effect=OSError("offline"))))

    def test_report_without_failures(self) -> None:
        run = routines.RoutineRun(key="x", name="X", trigger="voz", results=[])
        self.assertIn("Rotina 'X': 0 de 0 passos concluídos.", build_report(run))

    def test_instructions_list_the_routines(self) -> None:
        from prompts import build_agent_instructions

        text = build_agent_instructions(routines=summary_for_prompt(default_routines()))
        self.assertIn("# Rotinas salvas", text)
        self.assertIn("- Boa noite", text)
        self.assertIn("run_routine", text)


if __name__ == "__main__":
    unittest.main()
