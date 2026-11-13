"""Sessão de foco no servidor (FOC-47) e o que ela faz com a presença (PRS-25), o motor de avisos
(PRO-28) e a bandeja (BAN-41). O relógio é injetado: nenhum teste espera de verdade, e nenhum toca no
``foco.json`` real (o conftest aponta o arquivo para uma pasta temporária)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import focus
import tray
from focus import AWAY_GRACE_S, FocusSession, clean_config, spoken_left
import proactive
from proactive import Notice, ProactiveEngine, ReminderMonitor, add_reminder, load_state
from server import create_app
from tray import TrayController, TrayToasts

T0 = 1_800_000_000.0
MIN = 60.0
BRT = dt.timezone(dt.timedelta(hours=-3))


class Clock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FocusCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "foco.json"
        self.clock = Clock()

    def session(self) -> FocusSession:
        return FocusSession(self.path, now=self.clock)


class BlockTests(FocusCase):
    def test_config_stays_inside_the_limits(self) -> None:
        self.assertEqual(clean_config({"work": 0, "rest": 999, "cycles": -3}), {"work": 1, "rest": 60, "cycles": 1})
        self.assertEqual(clean_config({"work": 50.4, "rest": None}), {"work": 50, "rest": 5, "cycles": 4})
        self.assertEqual(clean_config({"work": True, "cycles": float("nan")}), {"work": 25, "rest": 5, "cycles": 4})
        self.assertEqual(clean_config(None, {"work": 40, "rest": 8, "cycles": 2}), {"work": 40, "rest": 8, "cycles": 2})

    def test_starts_on_the_first_work_block(self) -> None:
        focus_session = self.session()
        self.assertFalse(focus_session.holding())
        focus_session.start({"work": 25, "rest": 5, "cycles": 4})
        snap = focus_session.snapshot()
        self.assertEqual((snap["running"], snap["phase"], snap["cycle"], snap["cycles"]), (True, "work", 1, 4))
        self.assertEqual((snap["remaining_s"], snap["ends_at_ms"], snap["now_ms"]), (1500, round((T0 + 25 * MIN) * 1000), round(T0 * 1000)))
        self.assertTrue(focus_session.holding())

    def test_alternates_focus_and_rest_and_ends_without_a_rest_after_the_last_block(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 2, "rest": 1, "cycles": 2})
        self.clock.advance(2 * MIN - 1)
        self.assertEqual(focus_session.tick(), [])

        self.clock.advance(1)
        (event,) = focus_session.tick()
        self.assertEqual((event.kind, event.title), ("rest", "Hora da pausa"))
        self.assertEqual(event.message, "Bloco 1 de 2 concluído. 1 min de descanso.")
        self.assertEqual(focus_session.snapshot()["phase"], "rest")
        self.assertFalse(focus_session.holding())  # na pausa os avisos que esperavam podem sair

        self.clock.advance(MIN)
        (event,) = focus_session.tick()
        self.assertEqual((event.kind, event.message), ("work", "Bloco 2 de 2: 2 min."))
        self.assertTrue(focus_session.holding())

        self.clock.advance(2 * MIN)
        (event,) = focus_session.tick()
        self.assertEqual((event.kind, event.title), ("done", "Sessão de foco concluída"))
        self.assertEqual(event.message, "2 blocos de 2 min. Bom trabalho.")
        self.assertFalse(focus_session.snapshot()["running"])
        self.assertEqual(focus_session.snapshot()["remaining_s"], 0)
        self.assertEqual(focus_session.tick(), [])

    def test_a_server_that_was_off_goes_through_every_block_without_accumulating_delay(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 10, "rest": 5, "cycles": 3})
        self.clock.advance(27 * MIN)  # foco (10), pausa (5), foco (10) já passaram; está na segunda pausa
        events = focus_session.tick()
        self.assertEqual([event.kind for event in events], ["rest", "work", "rest"])
        snap = focus_session.snapshot()
        self.assertEqual((snap["phase"], snap["cycle"], snap["remaining_s"]), ("rest", 2, 3 * 60))
        self.clock.advance(600 * MIN)
        self.assertEqual(focus_session.tick()[-1].kind, "done")

    def test_skipping_counts_the_next_block_from_now(self) -> None:
        focus_session = self.session()
        self.assertEqual(focus_session.skip(), [])
        focus_session.start({"work": 25, "rest": 5, "cycles": 2})
        self.clock.advance(3 * MIN)
        (event,) = focus_session.skip()
        self.assertEqual(event.kind, "rest")
        self.assertEqual(focus_session.snapshot()["remaining_s"], 5 * 60)
        self.clock.advance(MIN)
        focus_session.skip()  # pausa -> segundo bloco
        (last,) = focus_session.skip()  # segundo e último bloco -> acabou
        self.assertEqual(last.kind, "done")
        self.assertFalse(focus_session.running)

    def test_stop_clears_the_session_and_keeps_the_times(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 50, "rest": 10, "cycles": 2})
        focus_session.stop()
        snap = focus_session.snapshot()
        self.assertEqual((snap["running"], snap["work"], snap["rest"], snap["cycles"]), (False, 50, 10, 2))
        # "Começar" sem tempos repete os da última sessão.
        focus_session.start()
        self.assertEqual(focus_session.snapshot()["remaining_s"], 50 * 60)

    def test_the_last_event_is_kept_for_the_hud(self) -> None:
        focus_session = self.session()
        self.assertIsNone(focus_session.snapshot()["last_event"])
        focus_session.start({"work": 1, "rest": 1, "cycles": 2})
        self.clock.advance(MIN)
        focus_session.tick()
        last = focus_session.snapshot()["last_event"]
        self.assertEqual((last["seq"], last["kind"], last["title"]), (1, "rest", "Hora da pausa"))
        self.assertEqual(last["at_ms"], round((T0 + MIN) * 1000))

    def test_spoken_time_left(self) -> None:
        self.assertEqual(spoken_left(14 * 60), "14 min")
        self.assertEqual(spoken_left(3 * 60 + 5), "3 min e 5 s")
        self.assertEqual(spoken_left(12 * 60 + 5), "12 min")
        self.assertEqual(spoken_left(45), "45 s")
        self.assertEqual(spoken_left(-3), "0 s")

    def test_report_for_the_voice_tool(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 25, "rest": 5, "cycles": 4})
        self.clock.advance(MIN)
        self.assertEqual(
            focus_session.report(), {"running": True, "phase": "work", "cycle": 1, "cycles": 4, "paused": False, "remaining_s": 24 * 60}
        )


class PresenceTests(FocusCase):
    def running(self, work: int = 25) -> FocusSession:
        focus_session = self.session()
        focus_session.start({"work": work, "rest": 5, "cycles": 2})
        return focus_session

    def test_without_presence_nothing_changes(self) -> None:
        focus_session = self.running()
        self.clock.advance(10 * MIN)
        self.assertEqual(focus_session.tick(None), [])
        self.clock.advance(5 * MIN)
        self.assertEqual(focus_session.tick(None), [])
        self.assertFalse(focus_session.paused)
        self.assertEqual(focus_session.snapshot()["remaining_s"], 10 * 60)
        self.clock.advance(10 * MIN)
        self.assertEqual([event.kind for event in focus_session.tick(None)], ["rest"])

    def test_a_short_absence_does_not_pause(self) -> None:
        focus_session = self.running()
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S - 1)
        self.assertEqual(focus_session.tick(False), [])
        self.assertFalse(focus_session.paused)
        # Voltou a tempo: a contagem da ausência recomeça do zero na próxima saída.
        self.clock.advance(1)
        focus_session.tick(True)
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S - 1)
        focus_session.tick(False)
        self.assertFalse(focus_session.paused)

    def test_a_long_absence_pauses_without_losing_the_time_it_took(self) -> None:
        focus_session = self.running()
        self.clock.advance(10 * MIN)
        focus_session.tick(True)
        focus_session.tick(False)  # saiu aos 10 min: faltavam 15
        self.clock.advance(AWAY_GRACE_S)
        (event,) = focus_session.tick(False)
        self.assertEqual(event.kind, "paused")
        self.assertTrue(focus_session.paused)
        snap = focus_session.snapshot()
        self.assertEqual((snap["paused"], snap["paused_reason"], snap["remaining_s"], snap["ends_at_ms"]), (True, "away", 15 * 60, None))
        self.assertTrue(focus_session.holding())  # os avisos continuam esperando o fim do bloco

        # Horas fora: nada anda.
        self.clock.advance(3 * 3600)
        self.assertEqual(focus_session.tick(False), [])
        self.assertEqual(focus_session.snapshot()["remaining_s"], 15 * 60)

    def test_coming_back_resumes_and_says_how_much_is_left(self) -> None:
        focus_session = self.running()
        self.clock.advance(10 * MIN)
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S)
        focus_session.tick(False)
        self.clock.advance(20 * MIN)
        (event,) = focus_session.tick(True)
        self.assertEqual((event.kind, event.title), ("resumed", "Foco retomado"))
        self.assertEqual(event.message, "Bem-vindo de volta. Faltam 15 min do bloco 1 de 2.")
        snap = focus_session.snapshot()
        self.assertEqual((snap["paused"], snap["remaining_s"], snap["last_event"]["kind"]), (False, 15 * 60, "resumed"))
        # E a contagem anda de novo, até o fim do bloco.
        self.clock.advance(15 * MIN)
        self.assertEqual([event.kind for event in focus_session.tick(True)], ["rest"])

    def test_turning_presence_off_during_the_pause_resumes_quietly(self) -> None:
        focus_session = self.running()
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S)
        focus_session.tick(False)
        self.assertTrue(focus_session.paused)
        self.clock.advance(MIN)
        self.assertEqual(focus_session.tick(None), [])
        self.assertFalse(focus_session.paused)
        self.assertEqual(focus_session.snapshot()["remaining_s"], 25 * 60)  # o tempo parado não foi gasto

    def test_leaving_during_the_rest_is_expected_and_pauses_nothing(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 3, "rest": 5, "cycles": 2})
        self.clock.advance(3 * MIN)
        focus_session.tick(True)
        self.assertEqual(focus_session.snapshot()["phase"], "rest")  # a pausa vai até os 8 min
        self.clock.advance(3 * MIN)
        self.assertEqual(focus_session.tick(False), [])  # 3 min fora, na pausa: normal
        self.assertFalse(focus_session.paused)
        # A pausa acaba com a pessoa ainda longe: o próximo bloco (até os 11 min) começa e, só então, a ausência pausa.
        self.clock.advance(3 * MIN)
        self.assertEqual([event.kind for event in focus_session.tick(False)], ["work"])
        self.assertFalse(focus_session.paused)
        self.clock.advance(AWAY_GRACE_S)
        self.assertEqual([event.kind for event in focus_session.tick(False)], ["paused"])
        self.assertEqual(focus_session.snapshot()["remaining_s"], 2 * 60)

    def test_a_block_that_ends_while_away_is_not_stretched_by_the_pause(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 2, "rest": 5, "cycles": 2})
        self.clock.advance(MIN)
        focus_session.tick(False)  # saiu com 1 min para o fim
        self.clock.advance(MIN)
        # O bloco acabou antes de a tolerância passar: vira pausa, e a ausência não pausa o descanso.
        self.assertEqual([event.kind for event in focus_session.tick(False)], ["rest"])
        self.assertFalse(focus_session.paused)

    def test_stopping_and_skipping_clear_the_pause(self) -> None:
        focus_session = self.running()
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S)
        focus_session.tick(False)
        (event,) = focus_session.skip()
        self.assertEqual(event.kind, "rest")
        self.assertFalse(focus_session.paused)
        focus_session.stop()
        self.assertFalse(focus_session.paused)


class FileTests(FocusCase):
    def test_the_session_survives_a_restart(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 30, "rest": 10, "cycles": 3})
        self.clock.advance(35 * MIN)
        focus_session.tick()  # foco 1 acabou, pausa em andamento
        again = self.session()
        snap = again.snapshot()
        self.assertEqual((snap["running"], snap["phase"], snap["cycle"], snap["remaining_s"]), (True, "rest", 1, 5 * 60))
        self.assertEqual((snap["work"], snap["rest"], snap["cycles"]), (30, 10, 3))

    def test_a_pause_by_absence_survives_a_restart_with_the_time_that_was_left(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 25, "rest": 5, "cycles": 2})
        focus_session.tick(False)
        self.clock.advance(AWAY_GRACE_S)
        focus_session.tick(False)
        self.clock.advance(3600)
        again = self.session()
        snap = again.snapshot()
        self.assertEqual((snap["paused"], snap["remaining_s"]), (True, 25 * 60))
        self.assertEqual([event.kind for event in again.tick(True)], ["resumed"])

    def test_blocks_that_passed_while_the_server_was_off_are_caught_up_on_the_next_tick(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 10, "rest": 5, "cycles": 2})
        self.clock.advance(60 * MIN)
        again = self.session()
        self.assertEqual([event.kind for event in again.tick()], ["rest", "work", "done"])
        self.assertFalse(again.running)
        self.assertFalse(self.session().running)  # e o arquivo ficou em dia

    def test_a_stopped_session_keeps_only_the_times(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 40, "rest": 8, "cycles": 2})
        focus_session.stop()
        again = self.session()
        self.assertEqual((again.running, again.config), (False, {"work": 40, "rest": 8, "cycles": 2}))

    def test_the_file_has_no_secrets_and_is_plain_json(self) -> None:
        focus_session = self.session()
        focus_session.start({"work": 25, "rest": 5, "cycles": 4})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["config", "session", "version"])
        self.assertEqual(sorted(data["session"]), ["cycle", "ends_at", "paused", "phase", "remaining_s", "running"])

    def test_a_broken_file_is_set_aside_and_the_session_starts_over(self) -> None:
        self.path.write_text("{quebrado", encoding="utf-8")
        self.assertFalse(self.session().running)
        self.assertFalse(self.path.exists())
        self.assertEqual(len(list(self.path.parent.glob("foco.corrompido-*.json"))), 1)

    def test_junk_inside_the_file_never_crashes(self) -> None:
        for session in (
            {"running": True, "ends_at": "amanhã"},
            {"running": True, "paused": True, "remaining_s": -5},
            {"running": True, "phase": "rest", "cycle": 99, "ends_at": T0 + 60},
            "lixo",
        ):
            self.path.write_text(json.dumps({"config": {"work": "x", "cycles": 99}, "session": session}), encoding="utf-8")
            loaded = self.session()
            self.assertLessEqual(loaded.config["cycles"], 12)
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertFalse(self.session().running)

    def test_an_unwritable_file_does_not_stop_the_session(self) -> None:
        focus_session = FocusSession(self.path.parent / "nao" / "existe" / "foco.json", now=self.clock)
        focus_session.start({"work": 25, "rest": 5, "cycles": 4})
        self.assertTrue(focus_session.running)


# ───────────────────────── motor de avisos ─────────────────────────


class FakeHub:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.triggers: list[tuple[float, str]] = []

    def notify(self, event: dict) -> None:
        self.events.append(event)

    def trigger(self, score: float, reason: str = "wake") -> dict:
        self.triggers.append((score, reason))
        return {"accepted": True, "opened_browser": False}


class FixedMonitor:
    topic = "downloads"
    interval = 5.0

    def __init__(self) -> None:
        self.queue: list[Notice] = []

    def check(self, now: dt.datetime, clock: float) -> list[Notice]:
        out, self.queue = self.queue, []
        return out


class EngineHoldTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch("proactive.REMINDERS_FILE", Path(folder.name) / "lembretes.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.focusing = False
        self.hub = FakeHub()
        self.monitor = FixedMonitor()
        self.mono = 1000.0
        self.wall = dt.datetime(2026, 10, 19, 14, 0, tzinfo=BRT)
        self.engine = ProactiveEngine(
            self.hub,
            [self.monitor],
            quiet_hours=None,
            clock=lambda: self.mono,
            now=lambda: self.wall,
            hold=lambda: self.focusing,
        )
        self.engine.agent_poll()  # o link está aberto: o que fala vai para a fila do agente

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += dt.timedelta(seconds=seconds)

    async def test_without_focus_everything_goes_as_always(self) -> None:
        self.monitor.queue = [Notice("downloads", "normal", "Download concluído", "a.pdf")]
        routed = await self.engine.tick()
        self.assertEqual([way for _, way in routed], ["speak"])
        self.assertEqual(self.engine.held, [])

    async def test_non_critical_notices_wait_for_the_end_of_the_focus_block(self) -> None:
        self.focusing = True
        self.monitor.queue = [
            Notice("downloads", "normal", "Download concluído", "Download concluído: a.pdf."),
            Notice("battery", "high", "Bateria baixa", "Bateria em 18%."),
        ]
        self.assertEqual(await self.engine.tick(), [])
        self.assertEqual(self.hub.events, [])  # nem no HUD: nada interrompe o bloco
        self.assertEqual(self.engine.agent_poll(), [])
        self.assertEqual(len(self.engine.held), 2)

        # O bloco acaba: tudo sai junto, pelo caminho de sempre, dizendo quando chegou.
        self.focusing = False
        self.advance(25 * 60)
        self.engine.agent_poll()
        routed = await self.engine.tick()
        self.assertEqual([(notice.title, way) for notice, way in routed], [("Download concluído", "speak"), ("Bateria baixa", "speak")])
        self.assertEqual(routed[0][0].message, "Download concluído: a.pdf. (chegou às 14:00, durante o foco)")
        self.assertEqual(self.engine.held, [])
        self.assertEqual(await self.engine.tick(), [])  # e só uma vez

    async def test_critical_notices_and_the_focus_own_notices_get_through(self) -> None:
        self.focusing = True
        self.monitor.queue = [
            Notice("battery", "critical", "Bateria crítica", "Bateria em 9%."),
            Notice("reminders", "critical", "Lembrete", "Remédio (urgente)"),
            Notice("focus", "normal", "Hora da pausa", "Bloco 1 de 4 concluído."),
            Notice("tasks", "normal", "Tarefas", "2 tarefas atrasadas."),
        ]
        routed = await self.engine.tick()
        self.assertEqual([notice.title for notice, _ in routed], ["Bateria crítica", "Lembrete", "Hora da pausa"])
        self.assertEqual([notice.title for _, notice in self.engine.held], ["Tarefas"])

    async def test_a_dispatch_straight_from_the_focus_notice_is_not_held(self) -> None:
        self.focusing = True
        routed = self.engine.dispatch([Notice("focus", "normal", "De volta ao foco", "Bloco 2 de 4: 25 min.")])
        self.assertEqual([way for _, way in routed], ["speak"])

    async def test_held_notices_are_not_repeated_and_the_list_has_a_limit(self) -> None:
        self.focusing = True
        same = Notice("downloads", "normal", "Download", "x", id="d1")
        self.engine.dispatch([same])
        self.engine.dispatch([Notice("downloads", "normal", "Download", "x", id="d1")])
        self.assertEqual(len(self.engine.held), 1)
        self.engine.dispatch([Notice("downloads", "normal", f"Download {n}", "x", id=f"n{n}") for n in range(60)])
        self.assertEqual(len(self.engine.held), 30)
        self.assertEqual(self.engine.held[-1][1].title, "Download 59")

    async def test_a_broken_gate_never_blocks_the_notices(self) -> None:
        def broken() -> bool:
            raise RuntimeError("quebrou")

        self.engine.hold = broken
        routed = self.engine.dispatch([Notice("downloads", "normal", "Download", "x")])
        self.assertEqual([way for _, way in routed], ["speak"])

    async def test_the_route_is_decided_when_they_are_released(self) -> None:
        self.focusing = True
        self.engine.dispatch([Notice("battery", "high", "Bateria baixa", "Bateria em 18%.")])
        self.focusing = False
        self.engine.agent_seen_at = None  # o link fechou durante o foco: aviso alto abre o link
        routed = await self.engine.tick()
        self.assertEqual([way for _, way in routed], ["wake"])
        self.assertEqual(self.hub.triggers, [(1.0, "notice")])


class HeldQueueRestartTests(unittest.IsolatedAsyncioTestCase):
    """A fila dos avisos segurados durante o foco fica no ``lembretes.json``: um reinício do Jarvis no meio
    do bloco não pode perdê-los, nem repeti-los, e isso inclui o lembrete que venceu nesse intervalo."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "lembretes.json"
        patcher = patch("proactive.REMINDERS_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.focusing = True
        self.mono = 1000.0
        self.wall = dt.datetime(2026, 10, 19, 14, 0, tzinfo=BRT)

    def boot(self, monitors: list | None = None) -> tuple[ProactiveEngine, FakeHub, FixedMonitor]:
        """Um "Jarvis" novo: motor, hub e monitores novos, o mesmo arquivo."""
        hub = FakeHub()
        monitor = FixedMonitor()
        engine = ProactiveEngine(
            hub,
            monitors if monitors is not None else [monitor],
            quiet_hours=None,
            clock=lambda: self.mono,
            now=lambda: self.wall,
            hold=lambda: self.focusing,
        )
        engine.agent_poll()  # o link está aberto
        return engine, hub, monitor

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += dt.timedelta(seconds=seconds)

    async def test_held_notices_survive_a_restart_and_come_out_once(self) -> None:
        first, _, monitor = self.boot()
        monitor.queue = [
            Notice("downloads", "normal", "Download concluído", "Download concluído: a.pdf.", id="d1"),
            Notice("battery", "high", "Bateria baixa", "Bateria em 18%.", id="b1"),
        ]
        self.assertEqual(await first.tick(), [])
        self.assertTrue(self.path.exists())

        # O Jarvis reinicia no meio do bloco: nada na memória, o foco ainda corre.
        second, hub, _ = self.boot()
        self.assertEqual([notice.title for _, notice in second.held], ["Download concluído", "Bateria baixa"])
        self.assertEqual(await second.tick(), [])  # continua segurando
        self.assertEqual(hub.events, [])

        # O bloco acaba: a segunda instância entrega, na ordem, dizendo quando chegaram.
        self.focusing = False
        self.advance(25 * MIN)
        second.agent_poll()
        routed = await second.tick()
        self.assertEqual([(notice.title, way) for notice, way in routed], [("Download concluído", "speak"), ("Bateria baixa", "speak")])
        self.assertEqual(routed[0][0].message, "Download concluído: a.pdf. (chegou às 14:00, durante o foco)")

        # Um terceiro reinício e uma segunda instância viva ao mesmo tempo: ninguém repete.
        third, hub3, _ = self.boot()
        self.assertEqual(third.held, [])
        self.assertEqual(await third.tick(), [])
        self.assertEqual(await second.tick(), [])
        self.assertEqual(hub3.events, [])

    async def test_a_reminder_that_came_due_during_focus_is_not_lost_by_a_restart(self) -> None:
        add_reminder("Ligar para o contador", self.wall + dt.timedelta(minutes=10), now=self.wall)
        first, _, _ = self.boot([ReminderMonitor()])
        self.advance(11 * MIN)
        self.assertEqual(await first.tick(), [])  # venceu durante o foco: espera
        state = load_state()
        self.assertEqual(state["reminders"], [])  # já saiu da lista de lembretes...
        self.assertEqual([entry["notice"]["message"] for entry in state["held"]], ["Ligar para o contador"])  # ...e está na fila, na mesma gravação

        second, hub, _ = self.boot([ReminderMonitor()])  # reinício
        self.focusing = False
        self.advance(20 * MIN)
        second.agent_poll()
        routed = await second.tick()
        self.assertEqual([(notice.title, way) for notice, way in routed], [("Lembrete", "speak")])
        self.assertEqual(routed[0][0].message, "Ligar para o contador (chegou às 14:11, durante o foco)")
        self.assertEqual(load_state()["held"], [])
        self.assertEqual(await second.tick(), [])  # e não volta

    async def test_a_reminder_never_sits_in_both_files_nor_in_neither(self) -> None:
        add_reminder("Pagar o boleto", self.wall + dt.timedelta(minutes=1), now=self.wall)
        engine, _, _ = self.boot([ReminderMonitor()])
        self.advance(2 * MIN)
        engine.collect()  # só a coleta: o aviso ainda não foi despachado
        state = load_state()
        self.assertEqual((len(state["reminders"]), len(state["held"])), (0, 1))

    async def test_an_urgent_reminder_does_not_wait_and_is_not_stored(self) -> None:
        add_reminder("Remédio", self.wall + dt.timedelta(minutes=1), now=self.wall, urgent=True)
        engine, _, _ = self.boot([ReminderMonitor()])
        self.advance(2 * MIN)
        engine.agent_poll()
        routed = await engine.tick()
        self.assertEqual([(notice.priority, way) for notice, way in routed], [("critical", "speak")])
        self.assertEqual(load_state()["held"], [])

    async def test_a_reminder_after_the_block_goes_straight_out(self) -> None:
        add_reminder("Beber água", self.wall + dt.timedelta(minutes=1), now=self.wall)
        self.focusing = False
        engine, _, _ = self.boot([ReminderMonitor()])
        self.advance(2 * MIN)
        engine.agent_poll()
        routed = await engine.tick()
        self.assertEqual([notice.message for notice, _ in routed], ["Beber água"])
        self.assertEqual(load_state()["held"], [])

    async def test_if_focus_ended_while_jarvis_was_off_they_are_delivered_on_start(self) -> None:
        first, _, monitor = self.boot()
        monitor.queue = [Notice("tasks", "normal", "Tarefas", "2 tarefas atrasadas.", id="t1")]
        await first.tick()
        self.focusing = False  # o bloco acabou com o Jarvis desligado
        self.advance(3 * 3600)
        second, _, _ = self.boot()
        routed = await second.tick()
        self.assertEqual([notice.title for notice, _ in routed], ["Tarefas"])
        self.assertEqual(routed[0][0].message, "2 tarefas atrasadas. (chegou às 14:00, durante o foco)")

    async def test_one_that_arrived_on_another_day_says_the_date(self) -> None:
        first, _, monitor = self.boot()
        monitor.queue = [Notice("tasks", "normal", "Tarefas", "2 tarefas atrasadas.", id="t1")]
        await first.tick()
        self.focusing = False
        self.advance(26 * 3600)
        second, _, _ = self.boot()
        routed = await second.tick()
        self.assertEqual(routed[0][0].message, "2 tarefas atrasadas. (chegou em 19/10 às 14:00, durante o foco)")

    async def test_the_route_is_decided_after_the_restart(self) -> None:
        first, _, monitor = self.boot()
        monitor.queue = [Notice("battery", "high", "Bateria baixa", "Bateria em 18%.", id="b1")]
        await first.tick()
        self.focusing = False
        second, hub, _ = self.boot()
        second.agent_seen_at = None  # o link está fechado: aviso alto abre o link
        routed = await second.tick()
        self.assertEqual([way for _, way in routed], ["wake"])
        self.assertEqual(hub.triggers, [(1.0, "notice")])

    async def test_the_same_notice_is_not_stored_twice_and_the_queue_has_a_limit_across_restarts(self) -> None:
        first, _, monitor = self.boot()
        monitor.queue = [Notice("downloads", "normal", "Download", "x", id="d1")]
        await first.tick()
        second, _, monitor2 = self.boot()
        monitor2.queue = [Notice("downloads", "normal", "Download", "x", id="d1")]
        await second.tick()
        self.assertEqual(len(second.held), 1)
        monitor2.queue = [Notice("downloads", "normal", f"Download {n}", "x", id=f"n{n}") for n in range(60)]
        self.advance(10)
        await second.tick()
        self.assertEqual(len(second.held), 30)
        self.assertEqual(second.held[-1][1].title, "Download 59")

    async def test_if_the_queue_cannot_be_saved_the_notice_is_not_lost(self) -> None:
        engine, hub, _ = self.boot()
        with patch("proactive.hold_notice", side_effect=OSError("disco cheio")):
            routed = engine.dispatch([Notice("downloads", "normal", "Download", "x", id="d1")])
        self.assertEqual([way for _, way in routed], ["speak"])  # sai agora, em vez de sumir
        self.assertEqual(engine.held, [])

    async def test_a_damaged_queue_is_ignored_entry_by_entry(self) -> None:
        good = {"arrived_at": "2026-10-19T14:00:00-03:00", "notice": {"id": "d1", "topic": "downloads", "priority": "normal", "title": "Download", "message": "a.pdf"}}
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "reminders": [],
                    "held": [
                        good,
                        "lixo",
                        {"arrived_at": "ontem", "notice": good["notice"]},
                        {"arrived_at": good["arrived_at"], "notice": {**good["notice"], "priority": "urgentíssimo"}},
                        {"arrived_at": good["arrived_at"], "notice": {**good["notice"], "topic": "inventado", "id": "x"}},
                        {"arrived_at": good["arrived_at"], "notice": {"id": "", "topic": "tasks", "priority": "normal", "title": "t", "message": "m"}},
                    ],
                }
            ),
            encoding="utf-8",
        )
        engine, _, _ = self.boot()
        self.assertEqual([notice.id for _, notice in engine.held], ["d1"])

    async def test_other_data_in_the_file_is_kept_when_the_queue_changes(self) -> None:
        add_reminder("Mais tarde", self.wall + dt.timedelta(days=1), now=self.wall)
        proactive.set_muted(["disk"], None)
        engine, _, monitor = self.boot()
        monitor.queue = [Notice("downloads", "normal", "Download", "x", id="d1")]
        await engine.tick()
        self.focusing = False
        await engine.tick()
        state = load_state()
        self.assertEqual([item["text"] for item in state["reminders"]], ["Mais tarde"])
        self.assertIn("disk", state["muted"])


# ───────────────────────── servidor ─────────────────────────

LOCAL = "http://127.0.0.1"
ENV = {"GOOGLE_API_KEY": "test-key"}


class FakePresence:
    def __init__(self) -> None:
        self.reading = {"running": True, "state": "present"}
        self.on_welcome = None
        self.journal = SimpleNamespace(add=lambda *args: None)

    def state(self) -> dict:
        return dict(self.reading)

    def start(self) -> str:
        return "ligada"

    def stop(self) -> None:
        pass


class ServerFocusTests(FocusCase):
    def client(self, env: dict | None = None, **kwargs) -> TestClient:
        patcher = patch.dict(os.environ, {**ENV, **(env or {})}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.focus = self.session()
        app = create_app(reload_env=False, focus_session=self.focus, **kwargs)
        return TestClient(app, base_url=LOCAL)

    def test_the_hud_reads_and_commands_the_session(self) -> None:
        client = self.client()
        idle = client.get("/api/focus").json()
        self.assertEqual((idle["enabled"], idle["running"], idle["work"]), (True, False, 25))

        started = client.post("/api/focus", json={"command": "start", "work": 10, "rest": 2, "cycles": 2}).json()
        self.assertEqual((started["running"], started["phase"], started["remaining_s"], started["cycles"]), (True, "work", 600, 2))
        self.assertTrue(self.path.exists())

        self.clock.advance(60)
        self.assertEqual(client.post("/api/focus", json={"command": "status"}).json()["remaining_s"], 540)
        skipped = client.post("/api/focus", json={"command": "skip"}).json()
        self.assertEqual((skipped["phase"], skipped["last_event"]["kind"]), ("rest", "rest"))
        stopped = client.post("/api/focus", json={"command": "stop"}).json()
        self.assertEqual((stopped["running"], stopped["rest"]), (False, 2))
        self.assertEqual(client.post("/api/focus", json={"command": "dançar"}).status_code, 422)

    def test_limits_are_enforced_by_the_server(self) -> None:
        client = self.client()
        body = client.post("/api/focus", json={"command": "start", "work": 9999, "rest": 0, "cycles": 99}).json()
        self.assertEqual((body["work"], body["rest"], body["cycles"]), (180, 1, 12))

    def test_only_this_computer_answers(self) -> None:
        client = self.client()
        other = TestClient(client.app, base_url="http://192.168.0.20")
        self.assertEqual(other.get("/api/focus").status_code, 403)
        self.assertEqual(other.post("/api/focus", json={"command": "start"}).status_code, 403)
        cross = client.post("/api/focus", json={"command": "start"}, headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(cross.status_code, 403)
        self.assertFalse(self.focus.running)

    def test_with_the_day_off_there_is_no_session(self) -> None:
        client = self.client({"JARVIS_ENABLE_DAY": "false"})
        self.assertEqual(client.get("/api/focus").json(), {"enabled": False})
        self.assertEqual(client.post("/api/focus", json={"command": "start"}).status_code, 403)
        self.assertFalse(self.focus.running)

    def test_the_server_counts_the_session_with_no_tab_open_and_tells_the_engine(self) -> None:
        engines: list[ProactiveEngine] = []

        def build(hub) -> ProactiveEngine:
            engine = ProactiveEngine(hub, [], quiet_hours=None)
            engine.agent_poll()  # o link está aberto
            engines.append(engine)
            return engine

        client = self.client({"JARVIS_PROACTIVE": "true"}, proactive=build)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 1, "rest": 1, "cycles": 2})
            self.clock.advance(61)
            deadline = time.monotonic() + 5
            while not engines[0].agent_queue and time.monotonic() < deadline:
                time.sleep(0.02)
            queued = [notice for _, notice in engines[0].agent_queue]
            self.assertEqual([(notice.topic, notice.title) for notice in queued], [("focus", "Hora da pausa")])
            self.assertEqual(self.focus.snapshot()["phase"], "rest")
            # E o aviso entra pelo mesmo caminho dos outros: o HUD o recebe como "notice".
            self.assertEqual([event["topic"] for event in engines[0].recent], ["focus"])

    def test_the_engine_holds_notices_only_while_a_focus_block_runs(self) -> None:
        engines: list[ProactiveEngine] = []

        def build(hub) -> ProactiveEngine:
            engine = ProactiveEngine(hub, [], quiet_hours=None)
            engines.append(engine)
            return engine

        client = self.client({"JARVIS_PROACTIVE": "true"}, proactive=build)
        with client:
            engine = engines[0]
            self.assertFalse(engine.hold())
            self.focus.start({"work": 25, "rest": 5, "cycles": 2})
            self.assertTrue(engine.hold())
            engine.dispatch([Notice("downloads", "normal", "Download", "x")])
            self.assertEqual(len(engine.held), 1)
            self.focus.skip()  # pausa
            self.assertFalse(engine.hold())
            self.focus.stop()
            self.assertFalse(engine.hold())

    def test_with_the_day_off_the_engine_does_not_hold_anything(self) -> None:
        engines: list[ProactiveEngine] = []

        def build(hub) -> ProactiveEngine:
            engine = ProactiveEngine(hub, [], quiet_hours=None)
            engines.append(engine)
            return engine

        client = self.client({"JARVIS_PROACTIVE": "true", "JARVIS_ENABLE_DAY": "false"}, proactive=build)
        with client:
            self.focus.start({"work": 25, "rest": 5, "cycles": 2})
            self.assertFalse(engines[0].hold())

    def test_presence_pauses_and_resumes_through_the_server_loop(self) -> None:
        presence = FakePresence()
        env = {"JARVIS_ENABLE_CAMERA": "true", "JARVIS_PRESENCE": "true"}
        client = self.client(env, presence_service=presence)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 25, "rest": 5, "cycles": 2})
            presence.reading["state"] = "away"
            self.clock.advance(1)
            self.wait_for(lambda: self.focus._away_since is not None)
            self.clock.advance(AWAY_GRACE_S)
            self.wait_for(lambda: self.focus.paused)
            presence.reading["state"] = "present"
            self.wait_for(lambda: not self.focus.paused)
            self.assertEqual(self.focus.snapshot()["last_event"]["kind"], "resumed")

    def test_presence_off_never_pauses(self) -> None:
        presence = FakePresence()
        presence.reading["state"] = "away"
        client = self.client({}, presence_service=presence)  # JARVIS_PRESENCE desligado
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 25, "rest": 5, "cycles": 2})
            self.clock.advance(AWAY_GRACE_S * 5)
            time.sleep(0.15)
            self.assertFalse(self.focus.paused)

    def test_unknown_presence_does_not_count_as_away(self) -> None:
        presence = FakePresence()
        presence.reading["state"] = "unknown"
        env = {"JARVIS_ENABLE_CAMERA": "true", "JARVIS_PRESENCE": "true"}
        client = self.client(env, presence_service=presence)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 25, "rest": 5, "cycles": 2})
            self.clock.advance(AWAY_GRACE_S * 5)
            time.sleep(0.15)
            self.assertFalse(self.focus.paused)

    @staticmethod
    def wait_for(condition, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert condition(), "a condição não chegou a valer"


# ───────────────────────── bandeja ─────────────────────────

TRAY_ENV = {**ENV, tray.SECRET_ENV: "s3cret"}


class TrayToastTests(FocusCase):
    def client(self, env: dict, **kwargs) -> TestClient:
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.focus = self.session()
        return TestClient(create_app(reload_env=False, focus_session=self.focus, **kwargs), base_url=LOCAL)

    def test_queue_hands_each_toast_over_once(self) -> None:
        toasts = TrayToasts()
        toasts.push("Hora da pausa", "Bloco 1 de 4 concluído. 5 min de descanso.")
        self.assertEqual(toasts.drain(), ["Hora da pausa. Bloco 1 de 4 concluído. 5 min de descanso."])
        self.assertEqual(toasts.drain(), [])
        for number in range(25):
            toasts.push("t", str(number))
        self.assertEqual(len(toasts.drain()), tray.MAX_TOASTS)

    def test_block_change_with_no_tab_becomes_a_tray_notification(self) -> None:
        client = self.client(TRAY_ENV)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 1, "rest": 1, "cycles": 2})
            self.clock.advance(61)
            deadline = time.monotonic() + 5
            toasts: list[str] = []
            while not toasts and time.monotonic() < deadline:
                toasts = client.get("/api/tray/state", headers={tray.SECRET_HEADER: "s3cret"}).json()["toasts"]
                time.sleep(0.02)
            self.assertEqual(toasts, ["Hora da pausa. Bloco 1 de 2 concluído. 1 min de descanso."])
            again = client.get("/api/tray/state", headers={tray.SECRET_HEADER: "s3cret"}).json()
            self.assertEqual(again["toasts"], [])

    def test_without_the_tray_nothing_piles_up(self) -> None:
        client = self.client(ENV)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 1, "rest": 1, "cycles": 2})
            self.clock.advance(61)
            ServerFocusTests.wait_for(lambda: self.focus.snapshot()["phase"] == "rest")
            time.sleep(0.1)
            self.assertEqual(client.app.state.tray_toasts.drain(), [])

    def test_a_spoken_notice_does_not_also_pop_a_windows_notification(self) -> None:
        def build(hub) -> ProactiveEngine:
            engine = ProactiveEngine(hub, [], quiet_hours=None)
            engine.agent_poll()  # link aberto: o Jarvis fala
            return engine

        client = self.client({**TRAY_ENV, "JARVIS_PROACTIVE": "true"}, proactive=build)
        with patch.object(focus, "TICK_S", 0.01), client:
            self.focus.start({"work": 1, "rest": 1, "cycles": 2})
            self.clock.advance(61)
            ServerFocusTests.wait_for(lambda: self.focus.snapshot()["phase"] == "rest")
            time.sleep(0.1)
            self.assertEqual(client.app.state.tray_toasts.drain(), [])

    def test_the_icon_shows_what_the_server_sends(self) -> None:
        class Http:
            def get(self, url, headers, timeout):
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"link": False, "listening": False, "toasts": ["Hora da pausa. Bloco 1 de 4 concluído.", "  ", 7]},
                )

        shown: list[str] = []
        controller = TrayController(hud_url="http://127.0.0.1:8000", secret="s", http=Http())
        controller.on_message = shown.append
        controller.poll()
        self.assertEqual(shown, ["Hora da pausa. Bloco 1 de 4 concluído."])

    def test_an_old_server_without_toasts_is_fine(self) -> None:
        class Http:
            def get(self, url, headers, timeout):
                return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"link": True})

        shown: list[str] = []
        controller = TrayController(hud_url="http://127.0.0.1:8000", secret="s", http=Http())
        controller.on_message = shown.append
        self.assertTrue(controller.poll().link)
        self.assertEqual(shown, [])


class RunLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_loop_announces_events_and_survives_a_failure(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        clock = Clock()
        session = FocusSession(Path(folder.name) / "foco.json", now=clock)
        session.start({"work": 1, "rest": 1, "cycles": 2})
        clock.advance(61)
        heard: list[list[str]] = []
        calls = {"present": 0}

        def present() -> bool | None:
            calls["present"] += 1
            if calls["present"] == 1:
                raise RuntimeError("câmera caiu")
            return None

        async def announce(events) -> None:
            heard.append([event.kind for event in events])

        with patch.object(focus, "TICK_S", 0.01):
            task = asyncio.create_task(session.run(present, announce))
            for _ in range(200):
                if heard:
                    break
                await asyncio.sleep(0.01)
            task.cancel()
        self.assertEqual(heard, [["rest"]])

    async def test_the_loop_waits_while_the_day_is_off(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        clock = Clock()
        session = FocusSession(Path(folder.name) / "foco.json", now=clock)
        session.start({"work": 1, "rest": 1, "cycles": 2})
        clock.advance(61)
        heard: list[int] = []
        with patch.object(focus, "TICK_S", 0.01):
            task = asyncio.create_task(session.run(lambda: None, lambda events: heard.append(len(events)), lambda: False))
            await asyncio.sleep(0.1)
            task.cancel()
        self.assertEqual(heard, [])


if __name__ == "__main__":
    unittest.main()
