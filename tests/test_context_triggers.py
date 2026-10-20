from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from context_triggers import (
    GLOBAL_GAP_S,
    PROBE_INTERVALS,
    ContextWatcher,
    app_matches,
    describe_trigger,
    parse_trigger,
    set_routine_trigger,
    valid_triggers,
)
from routines import (
    RoutineError,
    RoutineScheduler,
    claim_scheduled,
    default_routines,
    list_routines,
    load_routines,
    run_scheduled,
    save_routine,
    save_routines,
    summary_for_prompt,
)
from settings import SettingsError, load_settings
from test_routines import MONDAY, FakeAgentSession, FakeMonotonic, StoreCase, user
from test_tools import FakeRunContext
from wake_hub import WakeHub


class FakeProbes:
    """What the PC looks like right now; each test changes it between ticks."""

    def __init__(self) -> None:
        self.running: set[str] | None = {"explorer.exe", "chrome.exe"}
        self.focused: str | None = "explorer.exe"
        self.devices: set[str] | None = {"Alto-falantes (Realtek)"}
        self.network: str | None = "Casa"
        self.calls: dict[str, int] = {}

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def processes(self) -> set[str] | None:
        self._count("processes")
        if self.running is None:
            raise OSError("psutil falhou")
        return set(self.running)

    def foreground(self) -> str | None:
        self._count("foreground")
        return self.focused

    def audio_devices(self) -> set[str] | None:
        self._count("audio")
        return None if self.devices is None else set(self.devices)

    def wifi(self) -> str | None:
        self._count("wifi")
        return self.network


def routine_with(*triggers: dict, name: str = "Modo foco") -> dict:
    return {"name": name, "aliases": [], "steps": ["minimize"], "schedule": None, "triggers": list(triggers)}


class ParsingTests(unittest.TestCase):
    def test_kinds_and_aliases(self) -> None:
        self.assertEqual(parse_trigger("app", "PhpStorm"), {"when": "app", "value": "PhpStorm", "enabled": True})
        self.assertEqual(parse_trigger("abrir", " PhpStorm ")["when"], "app")
        self.assertEqual(parse_trigger("fone")["when"], "audio")
        self.assertEqual(parse_trigger("voltar", "qualquer coisa"), {"when": "chegar", "value": "", "enabled": True})
        self.assertEqual(parse_trigger("Wi-Fi", "Casa")["when"], "wifi")
        self.assertEqual(parse_trigger("app", "Steam", cooldown_minutes=5)["cooldown_minutes"], 5.0)

    def test_refuses_what_it_cannot_watch(self) -> None:
        with self.assertRaisesRegex(RoutineError, "Não conheço o gatilho"):
            parse_trigger("email", "chefe")
        with self.assertRaisesRegex(RoutineError, "precisa de um nome"):
            parse_trigger("app")
        with self.assertRaisesRegex(RoutineError, "entre 1 minuto e 24 horas"):
            parse_trigger("app", "Steam", cooldown_minutes=0)

    def test_file_triggers_are_validated(self) -> None:
        raw = [
            {"when": "app", "value": "PhpStorm"},
            {"when": "app", "value": "phpstorm"},  # repetido
            {"when": "telepatia"},
            "app: Steam",
            {"when": "audio", "enabled": False},
            {"when": "wifi", "value": "Casa"},
            {"when": "sair"},
        ]
        triggers = valid_triggers(raw)
        self.assertEqual([t["when"] for t in triggers], ["app", "audio", "wifi", "sair"])
        self.assertFalse(triggers[1]["enabled"])

    def test_descriptions(self) -> None:
        self.assertEqual(describe_trigger(parse_trigger("app", "PhpStorm")), "quando o PhpStorm abrir")
        self.assertEqual(describe_trigger(parse_trigger("audio")), "quando um fone conectar")
        self.assertEqual(describe_trigger(parse_trigger("sair", enabled=False)), "quando você sair da frente do PC (desligado)")

    def test_app_names_match_process_names(self) -> None:
        self.assertTrue(app_matches("PhpStorm", "phpstorm64.exe"))
        self.assertTrue(app_matches("VS Code", "Code.exe"))
        self.assertTrue(app_matches("Visual Studio Code", "Code.exe"))
        self.assertTrue(app_matches("Word", "WINWORD.EXE"))
        self.assertFalse(app_matches("PhpStorm", "pycharm64.exe"))
        self.assertFalse(app_matches("", "pycharm64.exe"))


class WatcherCase(unittest.TestCase):
    def setUp(self) -> None:
        self.probes = FakeProbes()
        self.clock = FakeMonotonic()
        self.presence_state: str | None = "off"
        self.routines = {"modo foco": routine_with({"when": "app", "value": "PhpStorm", "enabled": True})}
        self.fired: list[tuple[str, str]] = []
        self.watcher = ContextWatcher(
            fire=lambda key, reason: self.fired.append((key, reason)),
            load=lambda: self.routines,
            probes=self.probes,
            presence=lambda: self.presence_state,
            clock=self.clock,
            cooldown_minutes=30,
        )

    def later(self, seconds: float) -> None:
        self.clock.now += seconds


class EdgeTests(WatcherCase):
    def test_an_app_already_open_at_start_does_not_fire(self) -> None:
        self.probes.running |= {"phpstorm64.exe"}
        self.assertEqual(self.watcher.tick(), [])
        self.later(10)
        self.assertEqual(self.watcher.tick(), [])

    def test_opening_the_app_fires_once(self) -> None:
        self.watcher.tick()
        self.later(10)
        self.probes.running |= {"phpstorm64.exe", "fsnotifier.exe"}
        self.assertEqual(self.watcher.tick(), [("modo foco", "o PhpStorm abriu")])
        for _ in range(5):
            self.later(10)
            self.assertEqual(self.watcher.tick(), [])
        self.assertEqual(self.fired, [("modo foco", "o PhpStorm abriu")])

    def test_cooldown_stops_a_loop_of_reopening(self) -> None:
        self.watcher.tick()
        for _ in range(3):  # abre e fecha o app várias vezes em poucos minutos
            self.later(10)
            self.probes.running.add("phpstorm64.exe")
            self.watcher.tick()
            self.later(10)
            self.probes.running.discard("phpstorm64.exe")
            self.watcher.tick()
        self.assertEqual(len(self.fired), 1)

        self.later(30 * 60)
        self.probes.running.add("phpstorm64.exe")
        self.assertEqual(len(self.watcher.tick()), 1)

    def test_a_trigger_can_have_its_own_cooldown(self) -> None:
        self.routines["modo foco"]["triggers"][0]["cooldown_minutes"] = 2
        self.watcher.tick()
        for expected in (1, 1, 2):
            self.later(PROBE_INTERVALS["processes"])
            self.probes.running.add("phpstorm64.exe")
            self.watcher.tick()
            self.later(55)
            self.probes.running.discard("phpstorm64.exe")
            self.watcher.tick()
            self.assertEqual(len(self.fired), expected)

    def test_one_event_matching_two_triggers_fires_the_routine_once(self) -> None:
        self.routines["modo foco"]["triggers"].append({"when": "foco", "value": "PhpStorm", "enabled": True})
        self.watcher.tick()
        self.later(10)
        self.probes.running.add("phpstorm64.exe")
        self.probes.focused = "phpstorm64.exe"
        self.assertEqual(self.watcher.tick(), [("modo foco", "o PhpStorm abriu")])

    def test_global_gap_breaks_chains_between_routines(self) -> None:
        self.routines["modo jogo"] = routine_with({"when": "app", "value": "Steam", "enabled": True}, name="Modo jogo")
        self.routines["discord"] = routine_with({"when": "app", "value": "Discord", "enabled": True}, name="Discord")
        self.watcher.tick()
        self.later(10)
        self.probes.running |= {"steam.exe", "phpstorm64.exe"}
        self.assertEqual([key for key, _ in self.watcher.tick()], ["modo foco"])
        self.later(10)
        self.probes.running.add("discord.exe")  # aberto pela rotina que acabou de rodar
        self.assertEqual(self.watcher.tick(), [])
        self.later(GLOBAL_GAP_S)
        self.probes.running.discard("discord.exe")
        self.watcher.tick()
        self.later(10)
        self.probes.running.add("discord.exe")
        self.assertEqual([key for key, _ in self.watcher.tick()], ["discord"])

    def test_disabled_triggers_and_unused_probes_stay_quiet(self) -> None:
        self.routines["modo foco"]["triggers"][0]["enabled"] = False
        self.watcher.tick()
        self.probes.running.add("phpstorm64.exe")
        self.later(10)
        self.assertEqual(self.watcher.tick(), [])
        self.assertEqual(self.probes.calls, {})
        self.assertEqual(self.watcher.trigger_count(), 0)

    def test_only_the_probes_in_use_are_read_and_slow_ones_less_often(self) -> None:
        self.routines["modo foco"]["triggers"].append({"when": "audio", "value": "", "enabled": True})
        for _ in range(10):
            self.watcher.tick()
            self.later(3)
        self.assertEqual(set(self.probes.calls), {"processes", "audio"})
        self.assertEqual(self.probes.calls["audio"], 2)  # 30 s com leitura a cada 15 s
        self.assertEqual(self.probes.calls["processes"], 5)  # a cada 5 s, com o vigia a cada 3 s

    def test_a_failing_probe_never_fires(self) -> None:
        self.watcher.tick()
        self.later(10)
        self.probes.running = None
        self.watcher.tick()
        self.later(10)
        self.probes.running = {"phpstorm64.exe"}
        self.assertEqual(self.watcher.tick(), [])  # voltou a ler: é a nova base

    def test_reset_takes_a_new_baseline(self) -> None:
        self.watcher.tick()
        self.watcher.reset()
        self.probes.running.add("phpstorm64.exe")
        self.later(10)
        self.assertEqual(self.watcher.tick(), [])


class OtherKindsTests(WatcherCase):
    def test_headphones_connecting(self) -> None:
        self.routines["lofi"] = routine_with({"when": "audio", "value": "", "enabled": True}, name="Lo-fi")
        self.watcher.tick()
        self.later(PROBE_INTERVALS["audio"])
        self.probes.devices.add("Fones de ouvido (WH-1000XM4)")
        self.assertEqual(self.watcher.tick(), [("lofi", "o aparelho de áudio Fones de ouvido (WH-1000XM4) conectou")])

    def test_a_named_audio_device(self) -> None:
        self.routines["lofi"] = routine_with({"when": "audio", "value": "xm4", "enabled": True}, name="Lo-fi")
        self.watcher.tick()
        self.later(PROBE_INTERVALS["audio"])
        self.probes.devices.add("Headset (Logitech G435)")
        self.assertEqual(self.watcher.tick(), [])
        self.later(PROBE_INTERVALS["audio"])
        self.probes.devices.add("Fones de ouvido (WH-1000XM4)")
        self.assertEqual(len(self.watcher.tick()), 1)

    def test_focus_follows_the_front_window(self) -> None:
        self.routines["modo foco"]["triggers"] = [{"when": "foco", "value": "PhpStorm", "enabled": True}]
        self.probes.running.add("phpstorm64.exe")
        self.watcher.tick()
        self.later(3)
        self.probes.focused = "phpstorm64.exe"
        self.assertEqual(self.watcher.tick(), [("modo foco", "o PhpStorm ficou em foco")])

    def test_wifi(self) -> None:
        self.routines["trabalho"] = routine_with({"when": "wifi", "value": "Escritorio", "enabled": True}, name="Trabalho")
        self.probes.network = ""
        self.watcher.tick()
        self.later(PROBE_INTERVALS["wifi"])
        self.probes.network = "escritório"
        self.assertEqual(self.watcher.tick(), [("trabalho", "o computador entrou na rede Wi-Fi Escritorio")])

    def test_arriving_and_leaving(self) -> None:
        self.routines = {
            "bom dia": routine_with({"when": "chegar", "value": "", "enabled": True}, name="Bom dia"),
            "boa noite": routine_with({"when": "sair", "value": "", "enabled": True}, name="Boa noite"),
        }
        self.watcher.tick()
        for state in ("unknown", "present"):  # presença ligando e vendo você: é a base
            self.later(3)
            self.presence_state = state
            self.assertEqual(self.watcher.tick(), [])
        self.later(GLOBAL_GAP_S)
        self.presence_state = "away"
        self.assertEqual(self.watcher.tick(), [("boa noite", "você saiu da frente do computador")])
        self.later(GLOBAL_GAP_S)
        self.presence_state = "present"
        self.assertEqual(self.watcher.tick(), [("bom dia", "você voltou para a frente do computador")])

    def test_presence_turned_off_and_on_is_not_an_arrival(self) -> None:
        self.routines = {"bom dia": routine_with({"when": "chegar", "value": "", "enabled": True}, name="Bom dia")}
        self.presence_state = "away"
        self.watcher.tick()
        self.later(3)
        self.presence_state = "off"
        self.watcher.tick()
        self.later(3)
        self.presence_state = "present"
        self.assertEqual(self.watcher.tick(), [])


class RunForeverTests(WatcherCase):
    def test_runs_while_enabled_and_forgets_when_turned_off(self) -> None:
        switch = {"on": True}

        async def scenario() -> None:
            task = asyncio.create_task(self.watcher.run_forever(lambda: switch["on"], interval=0.001))
            await asyncio.sleep(0.02)
            self.later(10)
            self.probes.running.add("phpstorm64.exe")
            await asyncio.sleep(0.02)
            switch["on"] = False
            await asyncio.sleep(0.02)
            self.assertEqual(self.watcher.states, {})
            task.cancel()

        asyncio.run(scenario())
        self.assertEqual(self.fired, [("modo foco", "o PhpStorm abriu")])

    def test_a_broken_fire_does_not_stop_the_watcher(self) -> None:
        self.watcher.fire = MagicMock(side_effect=RuntimeError("navegador"))
        self.watcher.tick()
        self.later(10)
        self.probes.running.add("phpstorm64.exe")
        self.assertEqual(len(self.watcher.tick()), 1)


class SchedulerFireTests(unittest.TestCase):
    def test_fired_routine_is_claimed_once_with_its_reason(self) -> None:
        mono = FakeMonotonic()
        due: list[str] = []
        scheduler = RoutineScheduler(load=default_routines, now=lambda: MONDAY, monotonic=mono, on_due=due.append)
        scheduler.fire("modo foco", "o PhpStorm abriu")
        self.assertEqual(due, ["modo foco"])
        key = scheduler.claim()
        self.assertEqual(key, "modo foco")
        self.assertEqual(scheduler.claim_reason(key), "o PhpStorm abriu")
        self.assertIsNone(scheduler.claim_reason(key))
        self.assertIsNone(scheduler.claim())

    def test_wake_carries_the_context_reason(self) -> None:
        hub = WakeHub(clock=FakeMonotonic())
        client = hub.connect("tab-12345678")
        hub.trigger_routine("modo foco", "context")
        self.assertEqual(client.queue.get_nowait(), {"type": "wake", "score": 1.0, "reason": "context", "routine": "modo foco"})


class ServerContextTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.routines = {"modo foco": routine_with({"when": "app", "value": "PhpStorm", "enabled": True})}
        self.probes = FakeProbes()
        self.clock = FakeMonotonic()
        self.watcher = ContextWatcher(load=lambda: self.routines, probes=self.probes, presence=lambda: "off", clock=self.clock)
        self.scheduler = RoutineScheduler(load=lambda: self.routines, now=lambda: MONDAY)
        from server import create_app

        self.app = create_app(reload_env=False, routine_scheduler=self.scheduler, context_watcher=self.watcher, open_browser=MagicMock())
        self.client = TestClient(self.app, base_url="http://127.0.0.1")

    def test_status_counts_the_triggers(self) -> None:
        self.assertEqual(self.client.get("/api/status").json()["routines"]["context_triggers"], 1)
        with patch.dict(os.environ, {"JARVIS_CONTEXT_TRIGGERS": "false"}):
            self.assertEqual(self.client.get("/api/status").json()["routines"]["context_triggers"], 0)

    def test_a_fired_routine_opens_the_link_and_the_agent_learns_why(self) -> None:
        tab = self.app.state.wake_hub.connect("tab-12345678")
        self.watcher.tick()
        self.clock.now += 10
        self.probes.running.add("phpstorm64.exe")
        self.watcher.tick()
        self.assertEqual(tab.queue.get_nowait(), {"type": "wake", "score": 1.0, "reason": "context", "routine": "modo foco"})
        self.assertEqual(self.client.post("/api/routines/claim").json(), {"routine": "modo foco", "context": "o PhpStorm abriu"})
        self.assertEqual(self.client.post("/api/routines/claim").json(), {"routine": None})


class SettingsTests(unittest.TestCase):
    def test_env_switches(self) -> None:
        settings = load_settings({"GOOGLE_API_KEY": "k"})
        self.assertTrue(settings.context_triggers_enabled)
        self.assertEqual(settings.context_cooldown_minutes, 30)
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_CONTEXT_TRIGGERS": "false", "JARVIS_CONTEXT_COOLDOWN_MINUTES": "5"})
        self.assertFalse(settings.context_triggers_enabled)
        self.assertEqual(settings.context_cooldown_minutes, 5)
        with self.assertRaises(SettingsError):
            load_settings({"GOOGLE_API_KEY": "k", "JARVIS_CONTEXT_COOLDOWN_MINUTES": "0"})


class VoiceToolTests(StoreCase):
    async def test_add_remove_disable_and_enable(self) -> None:
        context = FakeRunContext(messages=user("quando eu abrir o PhpStorm, roda o modo foco"))
        result = await set_routine_trigger(context, name="modo foco", when="app", value="PhpStorm")
        self.assertIn("Pronto: a rotina 'Modo foco' roda sozinha quando o PhpStorm abrir.", result)
        self.assertIn("passos perigosos ainda pedem o seu sim", result)
        self.assertEqual(load_routines()["modo foco"]["triggers"], [{"when": "app", "value": "PhpStorm", "enabled": True}])
        on_disk = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["routines"]["modo foco"]["triggers"][0]["value"], "PhpStorm")

        context = FakeRunContext(messages=user("desliga o gatilho do modo foco"))
        self.assertIn("Gatilho desligado", await set_routine_trigger(context, name="modo foco", when="app", value="phpstorm", action="disable"))
        self.assertFalse(load_routines()["modo foco"]["triggers"][0]["enabled"])
        await set_routine_trigger(context, name="modo foco", when="app", value="PhpStorm", action="enable")
        self.assertTrue(load_routines()["modo foco"]["triggers"][0]["enabled"])

        context = FakeRunContext(messages=user("para de rodar o modo foco quando eu abrir o PhpStorm"))
        result = await set_routine_trigger(context, name="modo foco", when="app", action="remove")
        self.assertEqual(result, "Pronto: a rotina 'Modo foco' não roda mais quando o PhpStorm abrir.")
        self.assertEqual(load_routines()["modo foco"]["triggers"], [])

    async def test_refuses_requests_that_did_not_come_from_the_user(self) -> None:
        context = FakeRunContext(messages=user("abre o site de notícias"))
        result = await set_routine_trigger(context, name="modo foco", when="app", value="Chrome")
        self.assertIn("NADA foi alterado", result)
        self.assertEqual(load_routines()["modo foco"].get("triggers", []), [])

    async def test_limits(self) -> None:
        context = FakeRunContext(messages=user("quando eu conectar o fone roda o modo foco"))
        for app in ("A1", "B2", "C3", "D4"):
            await set_routine_trigger(context, name="modo foco", when="app", value=app)
        result = await set_routine_trigger(context, name="modo foco", when="audio")
        self.assertIn("no máximo 4 gatilhos", result)
        self.assertIn("NADA foi mudado", await set_routine_trigger(context, name="modo foco", when="wifi", action="remove"))
        self.assertIn("precisa de um nome", await set_routine_trigger(context, name="modo foco", when="wifi"))

    async def test_editing_steps_keeps_the_triggers_and_lists_show_them(self) -> None:
        context = FakeRunContext(messages=user("quando eu abrir o PhpStorm, roda o modo foco"))
        await set_routine_trigger(context, name="modo foco", when="app", value="PhpStorm")
        context = FakeRunContext(messages=user("acrescenta na rotina modo foco abrir o Notion"))
        await save_routine(context, name="modo foco", steps=["app: Notion"], mode="append")
        self.assertEqual(len(load_routines()["modo foco"]["triggers"]), 1)
        self.assertIn("(roda sozinha quando o PhpStorm abrir)", await list_routines(FakeRunContext()))
        self.assertIn("roda sozinha quando o PhpStorm abrir", summary_for_prompt())

    async def test_hand_written_file(self) -> None:
        routines = default_routines()
        routines["bom dia"]["triggers"] = [{"when": "voltar"}, {"when": "app"}]
        save_routines(routines)
        self.assertEqual(load_routines()["bom dia"]["triggers"], [{"when": "chegar", "value": "", "enabled": True}])


class AgentSideTests(StoreCase):
    def test_claim_brings_the_reason(self) -> None:
        response = MagicMock()
        response.json.return_value = {"routine": "modo foco", "context": "o PhpStorm abriu"}
        key = claim_scheduled("http://127.0.0.1:8000", post=MagicMock(return_value=response))
        self.assertEqual(key, "modo foco")
        self.assertEqual(key.context, "o PhpStorm abriu")
        response.json.return_value = {"routine": "bom dia"}
        self.assertIsNone(claim_scheduled("http://127.0.0.1:8000", post=MagicMock(return_value=response)).context)

    async def test_context_run_says_why(self) -> None:
        self.tools()
        response = MagicMock()
        response.json.return_value = {"routine": "modo foco", "context": "o PhpStorm abriu"}
        key = claim_scheduled("http://127.0.0.1:8000", post=MagicMock(return_value=response))
        session = FakeAgentSession()
        run = await run_scheduled(session, key)
        self.assertEqual(run.trigger, "contexto")
        self.assertEqual(self.cards[-1]["trigger"], "contexto")
        self.assertIn("A rotina 'Modo foco' acabou de rodar sozinha porque o PhpStorm abriu.", session.replies[0])

    async def test_context_run_of_good_night_still_waits_for_the_yes(self) -> None:
        mocks = self.tools()
        response = MagicMock()
        response.json.return_value = {"routine": "boa noite", "context": "você saiu da frente do computador"}
        key = claim_scheduled("http://127.0.0.1:8000", post=MagicMock(return_value=response))
        session = FakeAgentSession()
        await run_scheduled(session, key)
        mocks["lock_computer"].assert_not_awaited()
        self.assertIn("PRECISA CONFIRMAÇÃO", session.replies[0])


if __name__ == "__main__":
    unittest.main()
