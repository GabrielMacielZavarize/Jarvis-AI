"""Aparelho novo no Wi-Fi (ODD-42): leitura da tabela ARP (Windows e Linux, saídas falsas), o registro
com aprendizado em silêncio, endereço privado em grupo, o monitor do motor de avisos e as rotas do HUD.
Nenhum teste lê a rede nem o ``rede_aparelhos.json`` de verdade."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import requests
from fastapi.testclient import TestClient

import netwatch
import osint
import proactive
from proactive import NetworkMonitor, Notice, ProactiveEngine, configure_alerts
from server import create_app
from settings import SettingsError, load_settings
from test_proactive import BRT, FakeClock, FakeHub, FileTestCase, at
from test_tools import FakeRunContext

LOCAL = "http://127.0.0.1:8000"

WINDOWS_ARP = """
Interface: 192.168.0.10 --- 0x4
  Endereço IP           Endereço Físico       Tipo
  192.168.0.1           f4-6d-04-11-22-33     dinâmico
  192.168.0.23          3c-22-fb-aa-bb-cc     dinâmico
  192.168.0.77          da-a1-19-12-34-56     dinâmico
  192.168.0.255         ff-ff-ff-ff-ff-ff     estático
  224.0.0.22            01-00-5e-00-00-16     estático
  239.255.255.250       01-00-5e-7f-ff-fa     estático
"""

LINUX_NEIGH = """192.168.0.1 dev wlp2s0 lladdr f4:6d:04:11:22:33 REACHABLE
192.168.0.23 dev wlp2s0 lladdr 3c:22:fb:aa:bb:cc STALE
192.168.0.99 dev wlp2s0  FAILED
fe80::1 dev wlp2s0 lladdr f4:6d:04:11:22:33 router STALE
"""


def arp(output: str, code: int = 0) -> Any:
    return lambda command, **kwargs: SimpleNamespace(stdout=output, returncode=code)


def seen(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"ip": ip, "mac": mac} for ip, mac in pairs]


ROUTER = ("192.168.0.1", "f4:6d:04:11:22:33")
TV = ("192.168.0.23", "3c:22:fb:aa:bb:cc")
PHONE = ("192.168.0.77", "da:a1:19:12:34:56")  # da = 1101 1010: bit "localmente administrado" ligado
PHONE_B = ("192.168.0.78", "ca:a1:19:12:34:57")
GUEST = ("192.168.0.50", "00:1a:2b:3c:4d:5e")


class MacTests(unittest.TestCase):
    def test_private_addresses_have_the_locally_administered_bit(self) -> None:
        self.assertTrue(netwatch.is_private_mac("da:a1:19:12:34:56"))
        self.assertTrue(netwatch.is_private_mac("02:00:00:00:00:01"))
        self.assertTrue(netwatch.is_private_mac("6a:00:00:00:00:01"))
        self.assertFalse(netwatch.is_private_mac("f4:6d:04:11:22:33"))
        self.assertFalse(netwatch.is_private_mac("3c:22:fb:aa:bb:cc"))
        self.assertFalse(netwatch.is_private_mac("lixo"))

    def test_names_are_one_short_printable_line(self) -> None:
        self.assertEqual(netwatch.clean_name("  TV   da\nsala \x00"), "TV da sala")
        self.assertEqual(len(netwatch.clean_name("x" * 200)), netwatch.MAX_NAME_CHARS)
        self.assertEqual(netwatch.clean_name(None), "")


class ReadNeighborsTests(unittest.TestCase):
    def test_windows_output(self) -> None:
        with patch("osint.platform.system", return_value="Windows"):
            found = netwatch.read_neighbors(arp(WINDOWS_ARP))
        self.assertEqual(found, seen(ROUTER, TV, PHONE))

    def test_linux_output_skips_failed_and_ipv6_entries(self) -> None:
        with patch("osint.platform.system", return_value="Linux"):
            found = netwatch.read_neighbors(arp(LINUX_NEIGH))
        self.assertEqual([item["ip"] for item in found], ["192.168.0.1", "192.168.0.23"])

    def test_it_asks_the_system_only_for_what_it_already_knows(self) -> None:
        calls: list[list[str]] = []

        def run(command: list[str], **kwargs: Any) -> Any:
            calls.append(command)
            return SimpleNamespace(stdout="")

        with patch("osint.platform.system", return_value="Linux"):
            netwatch.read_neighbors(run)
        with patch("osint.platform.system", return_value="Windows"):
            netwatch.read_neighbors(run)
        self.assertEqual(calls, [["ip", "neigh", "show"], ["arp", "-a"]])  # leitura da tabela: nada de ping nem de varredura

    def test_a_command_that_fails_is_an_empty_list(self) -> None:
        def broken(command: list[str], **kwargs: Any) -> Any:
            raise FileNotFoundError("arp")

        def slow(command: list[str], **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired("arp", 8)

        self.assertEqual(netwatch.read_neighbors(broken), [])
        self.assertEqual(netwatch.read_neighbors(slow), [])


class DeviceFileCase(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "rede_aparelhos.json"
        patcher = patch("netwatch.DEVICES_FILE", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)


class ObserveTests(DeviceFileCase):
    def observe(self, found: list[dict[str, str]], now: dt.datetime) -> dict[str, list[dict[str, Any]]]:
        return netwatch.observe(found, now, self.path)

    def test_the_first_run_learns_the_network_in_silence(self) -> None:
        news = self.observe(seen(ROUTER, TV, PHONE), at(19, 10))
        self.assertEqual(news, {"public": [], "private": []})
        devices = netwatch.load(self.path)["devices"]
        self.assertEqual(sorted(devices), sorted([ROUTER[1], TV[1], PHONE[1]]))
        self.assertTrue(all(device["known"] and device["origin"] == "aprendido" for device in devices.values()))

    def test_it_keeps_learning_for_30_minutes_because_the_arp_table_fills_up_slowly(self) -> None:
        self.observe(seen(ROUTER), at(19, 10, 0))
        self.assertEqual(self.observe(seen(ROUTER, TV), at(19, 10, 25)), {"public": [], "private": []})
        news = self.observe(seen(ROUTER, TV, GUEST), at(19, 10, 31))
        self.assertEqual([device["mac"] for device in news["public"]], [GUEST[1]])

    def test_an_empty_table_does_not_start_the_learning_clock(self) -> None:
        self.observe([], at(19, 9, 0))
        self.assertIsNone(netwatch.load(self.path)["learning_until"])
        self.observe(seen(ROUTER), at(19, 10, 0))
        self.assertEqual(self.observe(seen(ROUTER, TV), at(19, 10, 20)), {"public": [], "private": []})

    def test_a_new_device_is_reported_once_even_after_a_restart(self) -> None:
        self.observe(seen(ROUTER), at(19, 10))
        news = self.observe(seen(ROUTER, GUEST), at(19, 11))
        self.assertEqual([(device["ip"], device["mac"]) for device in news["public"]], [GUEST])
        # Mesmo arquivo, outra execução: já foi avisado.
        self.assertEqual(self.observe(seen(ROUTER, GUEST), at(19, 11, 5)), {"public": [], "private": []})
        stored = netwatch.load(self.path)["devices"][GUEST[1]]
        self.assertEqual((stored["known"], stored["origin"], stored["first_seen"]), (False, "novo", at(19, 11).isoformat()))

    def test_a_known_device_that_changes_ip_is_not_new(self) -> None:
        self.observe(seen(ROUTER, TV), at(19, 10))
        self.assertEqual(self.observe(seen(ROUTER, ("192.168.0.90", TV[1])), at(19, 12)), {"public": [], "private": []})
        self.assertEqual(netwatch.load(self.path)["devices"][TV[1]]["ip"], "192.168.0.90")

    def test_private_addresses_are_grouped_and_throttled(self) -> None:
        self.observe(seen(ROUTER), at(19, 10))
        first = self.observe(seen(ROUTER, PHONE, PHONE_B, GUEST), at(19, 11))
        self.assertEqual([device["mac"] for device in first["public"]], [GUEST[1]])
        self.assertEqual(sorted(device["mac"] for device in first["private"]), sorted([PHONE[1], PHONE_B[1]]))
        # O mesmo celular troca de endereço de novo: não avisa antes de 6 horas...
        rotated = ("192.168.0.79", "6e:11:22:33:44:55")
        self.assertEqual(self.observe(seen(ROUTER, rotated), at(19, 14)), {"public": [], "private": []})
        # ...e quando passam, avisa o que ficou pendente, de uma vez.
        later = self.observe(seen(ROUTER, rotated), at(19, 17, 5))
        self.assertEqual([device["mac"] for device in later["private"]], [rotated[1]])
        self.assertTrue(netwatch.load(self.path)["devices"][rotated[1]]["private"])

    def test_a_device_you_named_while_it_waited_in_the_queue_is_never_reported(self) -> None:
        self.observe(seen(ROUTER), at(19, 10))
        self.observe(seen(ROUTER, PHONE), at(19, 11))  # avisa o primeiro grupo privado
        rotated = ("192.168.0.79", "6e:11:22:33:44:55")
        self.assertEqual(self.observe(seen(ROUTER, rotated), at(19, 12)), {"public": [], "private": []})  # espera o intervalo de 6 horas
        netwatch.update_device(rotated[1], name="Meu celular", path=self.path)
        self.assertEqual(self.observe(seen(ROUTER, rotated), at(19, 20)), {"public": [], "private": []})

    def test_a_forgotten_device_comes_back_as_new(self) -> None:
        self.observe(seen(ROUTER), at(19, 10))
        self.observe(seen(ROUTER, GUEST), at(19, 11))
        netwatch.forget_device(GUEST[1], self.path)
        news = self.observe(seen(ROUTER, GUEST), at(19, 12))
        self.assertEqual(len(news["public"]), 1)

    def test_the_file_has_a_limit(self) -> None:
        self.observe(seen(ROUTER), at(19, 10))
        many = [(f"10.0.{n // 250}.{n % 250 + 1}", f"00:00:5e:00:{n // 256:02x}:{n % 256:02x}") for n in range(netwatch.MAX_DEVICES + 40)]
        self.observe(seen(*many), at(19, 11))
        self.assertLessEqual(len(netwatch.load(self.path)["devices"]), netwatch.MAX_DEVICES)

    def test_an_unreadable_file_is_kept_as_a_copy(self) -> None:
        self.path.write_text("{ não é json", encoding="utf-8")
        self.observe(seen(ROUTER), at(19, 10))
        self.assertEqual(len(list(self.path.parent.glob("rede_aparelhos.corrompido-*"))), 1)
        self.assertIn(ROUTER[1], netwatch.load(self.path)["devices"])

    def test_junk_entries_in_the_file_are_dropped(self) -> None:
        self.path.write_text('{"devices": {"nao-e-mac": {"name": "x"}, "aa:bb:cc:dd:ee:ff": "lixo", "00:1a:2b:3c:4d:5e": {"name": "TV\\u0000 sala", "known": true}}}', encoding="utf-8")
        devices = netwatch.load(self.path)["devices"]
        self.assertEqual(list(devices), ["00:1a:2b:3c:4d:5e"])
        self.assertEqual(devices["00:1a:2b:3c:4d:5e"]["name"], "TV sala")


class EditTests(DeviceFileCase):
    def setUp(self) -> None:
        super().setUp()
        netwatch.observe(seen(ROUTER), at(19, 10), self.path)
        netwatch.observe(seen(ROUTER, GUEST, PHONE), at(19, 11), self.path)

    def test_naming_marks_the_device_as_known(self) -> None:
        device = netwatch.update_device(GUEST[1], name="  Notebook   do João ", path=self.path)
        self.assertEqual((device["name"], device["known"]), ("Notebook do João", True))

    def test_known_without_name_and_back_again(self) -> None:
        self.assertTrue(netwatch.update_device(GUEST[1], known=True, path=self.path)["known"])
        self.assertFalse(netwatch.update_device(GUEST[1], known=False, path=self.path)["known"])
        # Desmarcar não gera aviso de novo: o aparelho só volta para a lista de "não revisados".
        self.assertEqual(netwatch.observe(seen(ROUTER, GUEST), at(19, 12), self.path), {"public": [], "private": []})

    def test_listing_puts_the_unreviewed_first(self) -> None:
        listing = netwatch.listing(self.path, now=at(19, 11, 10))
        self.assertEqual({device["mac"] for device in listing["devices"][:2]}, {PHONE[1], GUEST[1]})
        self.assertEqual(listing["unreviewed"], 2)
        self.assertFalse(listing["devices"][0]["known"])
        self.assertTrue(listing["devices"][-1]["known"])  # o roteador, aprendido
        netwatch.update_device(GUEST[1], name="Visita", path=self.path)
        self.assertEqual(netwatch.listing(self.path, now=at(19, 11, 10))["unreviewed"], 1)

    def test_learning_flag_follows_the_clock(self) -> None:
        self.assertTrue(netwatch.listing(self.path, now=at(19, 10, 10))["learning"])
        self.assertFalse(netwatch.listing(self.path, now=at(19, 11, 0))["learning"])

    def test_unknown_mac_is_an_error(self) -> None:
        with self.assertRaises(netwatch.DeviceNotFound):
            netwatch.update_device("aa:aa:aa:aa:aa:aa", name="x", path=self.path)
        with self.assertRaises(netwatch.DeviceNotFound):
            netwatch.forget_device("aa:aa:aa:aa:aa:aa", self.path)

    def test_forgetting_removes_it(self) -> None:
        netwatch.forget_device(GUEST[1].upper().replace(":", "-"), self.path)
        self.assertNotIn(GUEST[1], netwatch.load(self.path)["devices"])


class NetworkMonitorTests(DeviceFileCase):
    def setUp(self) -> None:
        super().setUp()
        self.table: list[dict[str, str]] = []
        self.reads = 0
        self.monitor = NetworkMonitor(path=self.path, read=self.read)

    def read(self) -> list[dict[str, str]]:
        self.reads += 1
        return list(self.table)

    def check(self, now: dt.datetime) -> list[Notice]:
        return self.monitor.check(now, 0.0)

    def test_first_reading_is_silent_and_a_new_device_is_one_notice(self) -> None:
        self.table = seen(ROUTER, TV)
        self.assertEqual(self.check(at(19, 10)), [])
        self.table = seen(ROUTER, TV, GUEST)
        self.assertEqual(self.check(at(19, 10, 20)), [])  # ainda aprendendo (até as 10h30)
        self.table = seen(ROUTER, TV, GUEST, ("192.168.0.60", "00:11:22:33:44:55"))
        notices = self.check(at(19, 11))
        self.assertEqual(len(notices), 1)
        notice = notices[0]
        self.assertEqual((notice.topic, notice.priority, notice.title), ("network", "normal", "Aparelho novo na rede"))
        self.assertEqual(
            notice.message,
            "Aparelho novo no Wi-Fi: 192.168.0.60 (endereço 00:11:22:33:44:55). Se for seu, dê um nome a ele em Olho de Deus, Minha rede.",
        )
        self.assertEqual(self.check(at(19, 11, 5)), [])

    def test_several_new_devices_are_one_notice_with_a_limit_on_the_names(self) -> None:
        self.table = seen(ROUTER)
        self.check(at(19, 10))
        self.table = seen(ROUTER, *[(f"192.168.0.{20 + n}", f"00:11:22:33:44:{n:02x}") for n in range(5)])
        notice = self.check(at(19, 11))[0]
        self.assertTrue(notice.message.startswith("5 aparelhos novos no Wi-Fi: 192.168.0.20 (endereço 00:11:22:33:44:00)"))
        self.assertIn("e mais 2.", notice.message)

    def test_private_addresses_get_their_own_grouped_notice(self) -> None:
        self.table = seen(ROUTER)
        self.check(at(19, 10))
        self.table = seen(ROUTER, PHONE, PHONE_B, GUEST)
        notices = self.check(at(19, 11))
        self.assertEqual([notice.title for notice in notices], ["Aparelho novo na rede", "Aparelho novo (endereço privado)"])
        private = notices[1]
        self.assertTrue(private.message.startswith("2 aparelhos novos com endereço privado: 192.168.0.77"))
        self.assertIn("endereço aleatório", private.message)
        self.assertNotEqual(notices[0].id, private.id)

    def test_nothing_changes_means_no_notice_and_a_failed_read_does_not_forget_anyone(self) -> None:
        self.table = seen(ROUTER, TV)
        self.check(at(19, 10))
        self.table = []  # o comando falhou ou a tabela esvaziou
        self.assertEqual(self.check(at(19, 11)), [])
        self.assertEqual(sorted(netwatch.load(self.path)["devices"]), sorted([ROUTER[1], TV[1]]))
        self.table = seen(ROUTER, TV)
        self.assertEqual(self.check(at(19, 11, 5)), [])

    def test_it_only_reads_every_five_minutes_in_the_engine(self) -> None:
        self.assertEqual(self.monitor.interval, 300.0)
        self.assertEqual(self.monitor.topic, "network")


class NetworkEngineTests(FileTestCase):
    """O motor leva o aviso pelo caminho de sempre: voz, HUD, silêncio e assunto silenciado."""

    def setUp(self) -> None:
        super().setUp()
        patcher = patch("netwatch.DEVICES_FILE", self.folder / "rede_aparelhos.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = FakeClock(at(19, 10))
        self.hub = FakeHub()
        self.table = seen(ROUTER)

    def settings(self, **env: str) -> Any:
        return load_settings({"GOOGLE_API_KEY": "k", "JARVIS_PROACTIVE": "true", **env})

    def engine(self, quiet: str = "23:00-07:00") -> ProactiveEngine:
        engine = ProactiveEngine.for_settings(
            self.settings(JARVIS_NETWORK_WATCH="true", JARVIS_OSINT_NETWORK="true", JARVIS_QUIET_HOURS=quiet),
            self.hub,
            path=self.path,
            devices_path=self.folder / "rede_aparelhos.json",
            clock=self.clock.clock,
            now=self.clock.now,
        )
        engine.monitors = [NetworkMonitor(path=self.folder / "rede_aparelhos.json", read=lambda: list(self.table))]
        engine.agent_poll()  # o link está aberto
        return engine

    async def newcomer(self, engine: ProactiveEngine) -> list[Any]:
        await engine.tick()  # aprende
        self.clock.advance(31 * 60)
        self.table = seen(ROUTER, GUEST)
        engine.agent_poll()
        return await engine.tick()

    def test_monitor_only_exists_when_the_switch_is_on(self) -> None:
        def topics(settings: Any) -> list[str]:
            return [monitor.topic for monitor in ProactiveEngine.for_settings(settings, self.hub, path=self.path).monitors]

        self.assertNotIn("network", topics(self.settings()))
        self.assertIn("network", topics(self.settings(JARVIS_NETWORK_WATCH="true", JARVIS_OSINT_NETWORK="true")))

    async def test_speaks_when_the_link_is_open(self) -> None:
        routed = await self.newcomer(self.engine())
        self.assertEqual([(notice.topic, way) for notice, way in routed], [("network", "speak")])

    async def test_quiet_hours_keep_it_on_the_hud(self) -> None:
        self.clock.wall = at(19, 23, 30)
        routed = await self.newcomer(self.engine())
        self.assertEqual([way for _, way in routed], ["hud"])
        self.assertEqual(self.hub.triggers, [])
        self.assertEqual(self.hub.events[-1]["topic"], "network")  # continua no HUD

    async def test_never_wakes_the_link_even_with_it_closed(self) -> None:
        engine = self.engine()
        self.clock.advance(60)  # o agente parou de perguntar: o link fechou
        await engine.tick()
        self.clock.advance(31 * 60)
        self.table = seen(ROUTER, GUEST)
        routed = await engine.tick()
        self.assertEqual([way for _, way in routed], ["hud"])
        self.assertEqual(self.hub.triggers, [])

    async def test_a_muted_topic_stays_on_the_hud_without_voice(self) -> None:
        proactive.set_muted(["network"], None, self.path)
        routed = await self.newcomer(self.engine())
        self.assertEqual([way for _, way in routed], ["hud"])

    async def test_voice_can_mute_and_unmute_the_network_topic(self) -> None:
        with patch("proactive.tool_status", AsyncMock()), patch("proactive.REMINDERS_FILE", self.path):
            for word in ("rede", "wifi", "aparelhos", "network"):
                await configure_alerts(FakeRunContext(), "mute", word)
                self.assertIn("network", proactive.load_state(self.path)["muted"], word)
                await configure_alerts(FakeRunContext(), "unmute", "network")
                self.assertNotIn("network", proactive.load_state(self.path)["muted"])

    async def test_during_a_focus_block_the_notice_waits_for_the_end(self) -> None:
        engine = self.engine()
        engine.hold = lambda: True
        routed = await self.newcomer(engine)
        self.assertEqual(routed, [])
        self.assertEqual([notice.topic for _, notice in engine.held], ["network"])


class SettingsTests(unittest.TestCase):
    def load(self, **env: str) -> Any:
        return load_settings({"GOOGLE_API_KEY": "k", **env})

    def test_off_by_default(self) -> None:
        self.assertFalse(self.load().network_watch_enabled)
        self.assertFalse(self.load(JARVIS_NETWORK_WATCH="false").network_watch_enabled)

    def test_it_needs_the_network_lookup(self) -> None:
        self.assertTrue(self.load(JARVIS_NETWORK_WATCH="true", JARVIS_OSINT_NETWORK="true").network_watch_enabled)
        with self.assertRaisesRegex(SettingsError, "JARVIS_OSINT_NETWORK"):
            self.load(JARVIS_NETWORK_WATCH="true")
        with self.assertRaisesRegex(SettingsError, "JARVIS_OSINT_NETWORK"):
            self.load(JARVIS_NETWORK_WATCH="true", JARVIS_OSINT_NETWORK="false")

    def test_it_needs_the_eye_of_god_on(self) -> None:
        with self.assertRaisesRegex(SettingsError, "JARVIS_ENABLE_OSINT"):
            self.load(JARVIS_NETWORK_WATCH="true", JARVIS_OSINT_NETWORK="true", JARVIS_ENABLE_OSINT="false")

    def test_a_bad_value_is_refused(self) -> None:
        with self.assertRaises(SettingsError):
            self.load(JARVIS_NETWORK_WATCH="talvez")

    def test_env_example_documents_it_and_the_device_file_is_ignored(self) -> None:
        root = Path(__file__).resolve().parent.parent
        self.assertIn("JARVIS_NETWORK_WATCH=false", (root / ".env.example").read_text(encoding="utf-8"))
        self.assertIn("rede_aparelhos.json", (root / ".gitignore").read_text(encoding="utf-8"))


class LookupNetworkTests(DeviceFileCase):
    @staticmethod
    def no_internet(*args: Any, **kwargs: Any) -> Any:
        raise requests.ConnectionError("sem rede")

    def test_the_lookup_shows_names_and_marks_private_addresses(self) -> None:
        netwatch.observe(seen(ROUTER, TV, PHONE), at(19, 10), self.path)
        netwatch.update_device(TV[1], name="TV da sala", path=self.path)
        with patch("osint.platform.system", return_value="Windows"):
            result = osint.lookup_network(
                http=SimpleNamespace(get=self.no_internet),
                run=arp(WINDOWS_ARP),
                ports=lambda: [],
                addresses=lambda: ["192.168.0.10"],
            )
        items = next(item for item in result["lists"] if item["title"].startswith("Aparelhos"))["items"]
        self.assertEqual(
            items,
            [
                "192.168.0.1 · f4:6d:04:11:22:33",
                "192.168.0.23 · 3c:22:fb:aa:bb:cc · TV da sala",
                "192.168.0.77 · da:a1:19:12:34:56 · endereço privado",
            ],
        )


class RouteTests(DeviceFileCase):
    def client(self, env: dict[str, str] | None = None, base_url: str = LOCAL, **kwargs: Any) -> TestClient:
        base = {"GOOGLE_API_KEY": "test-key", "JARVIS_OSINT_NETWORK": "true", "JARVIS_NETWORK_WATCH": "true"}
        patcher = patch.dict(os.environ, {**base, **(env or {})}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app(reload_env=False, **kwargs), base_url=base_url)

    def setUp(self) -> None:
        super().setUp()
        netwatch.observe(seen(ROUTER), at(19, 10), self.path)
        netwatch.observe(seen(ROUTER, GUEST), at(19, 11), self.path)

    def test_status_says_whether_the_watch_is_on(self) -> None:
        self.assertEqual(self.client().get("/api/status").json()["osint"], {"enabled": True, "network": True, "network_watch": True})
        self.assertTrue(self.client().get("/api/osint").json()["network_watch"])

    def test_lists_names_and_forgets(self) -> None:
        client = self.client()
        listing = client.get("/api/osint/network/devices").json()
        self.assertTrue(listing["watching"])
        self.assertEqual(listing["unreviewed"], 1)
        self.assertEqual(listing["devices"][0]["mac"], GUEST[1])

        named = client.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "Visita"})
        self.assertEqual((named.status_code, named.json()["name"], named.json()["known"]), (200, "Visita", True))
        self.assertEqual(client.get("/api/osint/network/devices").json()["unreviewed"], 0)

        gone = client.delete(f"/api/osint/network/devices/{GUEST[1]}")
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(client.delete(f"/api/osint/network/devices/{GUEST[1]}").status_code, 404)

    def test_bad_mac_and_unknown_device(self) -> None:
        client = self.client()
        self.assertEqual(client.patch("/api/osint/network/devices/lixo", json={"name": "x"}).status_code, 422)
        self.assertEqual(client.patch("/api/osint/network/devices/aa:aa:aa:aa:aa:aa", json={"name": "x"}).status_code, 404)

    def test_only_this_pc_can_use_them(self) -> None:
        phone = self.client(base_url="http://192.168.0.5:8000")
        self.assertEqual(phone.get("/api/osint/network/devices").status_code, 403)
        self.assertEqual(phone.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "x"}).status_code, 403)
        self.assertEqual(phone.delete(f"/api/osint/network/devices/{GUEST[1]}").status_code, 403)
        self.assertEqual(netwatch.load(self.path)["devices"][GUEST[1]]["name"], "")

    def test_a_paired_phone_cannot_reach_them_even_though_it_reaches_the_rest_of_the_eye(self) -> None:
        from lan_access import DeviceRegistry
        from test_lan_access import PHONE_PEER, PHONE_URL

        pc = self.client(devices=DeviceRegistry(None))
        pc.app.state.lan_urls = [PHONE_URL]
        code = pc.post("/api/lan/pairing").json()["code"]
        phone = TestClient(pc.app, base_url=PHONE_URL, client=PHONE_PEER)
        self.assertEqual(phone.post("/api/lan/pair", json={"code": code, "name": "Pixel"}).status_code, 200)
        self.assertEqual(phone.get("/api/osint").status_code, 200)  # o Olho de Deus em si o celular pareado usa
        for response in (
            phone.get("/api/osint/network/devices"),
            phone.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "x"}),
            phone.delete(f"/api/osint/network/devices/{GUEST[1]}"),
        ):
            self.assertEqual(response.status_code, 403)
            self.assertIn("próprio computador", response.json()["detail"])
        self.assertEqual(netwatch.load(self.path)["devices"][GUEST[1]]["name"], "")
        self.assertEqual(pc.get("/api/osint/network/devices").status_code, 200)

    def test_a_cross_site_request_is_refused(self) -> None:
        response = self.client().get("/api/osint/network/devices", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(response.status_code, 403)

    def test_without_the_network_lookup_or_the_eye_the_list_is_closed(self) -> None:
        off = self.client({"JARVIS_OSINT_NETWORK": "false", "JARVIS_NETWORK_WATCH": "false"})
        response = off.get("/api/osint/network/devices")
        self.assertEqual(response.status_code, 403)
        self.assertIn("JARVIS_OSINT_NETWORK", response.json()["detail"])
        self.assertEqual(off.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "x"}).status_code, 403)
        eye_off = self.client({"JARVIS_ENABLE_OSINT": "false", "JARVIS_NETWORK_WATCH": "false"})
        self.assertEqual(eye_off.get("/api/osint/network/devices").status_code, 403)

    def test_a_very_long_name_is_cut_not_stored_whole(self) -> None:
        client = self.client()
        self.assertEqual(client.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "x" * 201}).status_code, 422)
        long = client.patch(f"/api/osint/network/devices/{GUEST[1]}", json={"name": "y" * 100})
        self.assertEqual(len(long.json()["name"]), netwatch.MAX_NAME_CHARS)


if __name__ == "__main__":
    unittest.main()
