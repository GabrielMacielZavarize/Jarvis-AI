from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mcp_client
from mcp_client import (
    PENDING_MCP_KEY,
    STATES,
    IntegrationToolset,
    MCPConfigError,
    ServerConfig,
    build_mcp_tools,
    confirm_mcp_action,
    is_sensitive,
    load_servers,
    needs_confirmation,
)

from test_mcp import HAS_MCP, FakeInner, raw_tool, write_config
from test_tools import FakeMessage, FakeRunContext

FAKE_HOME = Path(__file__).resolve().parent / "mcp_fake_home_assistant.py"
EXAMPLE = Path(__file__).resolve().parent.parent / "mcp.example.json"
ALLOWED = ("GetLiveContext", "HassTurnOn", "HassTurnOff", "HassLightSet")
WRITES = ("HassTurnOn", "HassTurnOff", "HassLightSet")
HOME = ServerConfig(
    name="home_assistant",
    label="Home Assistant",
    url="http://192.168.0.10:8123/api/mcp",
    token_env="HOME_ASSISTANT_TOKEN",
    allowed=ALLOWED,
    no_confirm=WRITES,
)


class HomeConfigTests(unittest.TestCase):
    def test_the_example_has_home_assistant(self) -> None:
        home = next(server for server in load_servers(EXAMPLE) if server.name == "home_assistant")

        self.assertEqual((home.label, home.transport, home.token_env), ("Home Assistant", "http", "HOME_ASSISTANT_TOKEN"))
        self.assertIn("GetLiveContext", home.allowed)
        self.assertIn("HassTurnOn", home.no_confirm)

    def test_http_only_for_the_home_network(self) -> None:
        for url in ("http://192.168.0.10:8123/api/mcp", "http://10.0.0.5:8123/api/mcp", "http://[fd00::5]:8123/api/mcp"):
            with self.subTest(url=url):
                self.assertTrue(load_servers(write_config(self, {"casa": {"url": url}})))
        for url in ("http://homeassistant.local:8123/api/mcp", "http://8.8.8.8/api/mcp", "http://169.254.1.1/api/mcp"):
            with self.subTest(url=url), self.assertRaises(MCPConfigError):
                load_servers(write_config(self, {"casa": {"url": url}}))

    def test_light_and_volume_run_but_doors_locks_and_alarms_ask_for_the_code(self) -> None:
        self.assertFalse(needs_confirmation(HOME, "HassTurnOff", {"name": "luz do escritório"}))
        self.assertFalse(needs_confirmation(HOME, "HassTurnOn", {"name": "ar da sala", "domain": ["climate"]}))
        self.assertFalse(needs_confirmation(HOME, "HassLightSet", {"area": "Sala", "brightness": 40}))
        self.assertFalse(needs_confirmation(HOME, "GetLiveContext"))
        for tool, arguments in [
            ("HassTurnOff", {"name": "Porta da Frente", "domain": ["lock"]}),
            ("HassTurnOn", {"name": "Portão"}),
            ("HassTurnOn", {"area": "garagem", "domain": ["cover"]}),
            ("HassTurnOn", {"device_class": ["garage"]}),
            ("HassTurnOff", {"domain": ["alarm_control_panel"]}),
            ("HassTurnOff", {"name": "câmera do quintal"}),
            ("HassTurnOff", {"name": "fechadura"}),
        ]:
            with self.subTest(tool=tool, arguments=arguments):
                self.assertTrue(needs_confirmation(HOME, tool, arguments))

    def test_sensitive_names_win_over_sem_confirmar(self) -> None:
        config = ServerConfig(name="casa", label="Casa", command="x", no_confirm=("abrir_portao", "unlockFrontDoor"))
        self.assertTrue(needs_confirmation(config, "abrir_portao"))
        self.assertTrue(needs_confirmation(config, "unlockFrontDoor"))
        self.assertTrue(needs_confirmation(config, "GetCameraSnapshot"))

    def test_reading_with_a_sensitive_word_is_still_reading(self) -> None:
        github = ServerConfig(name="github", label="GitHub", command="x")
        self.assertFalse(needs_confirmation(github, "search_issues", {"query": "porta da garagem"}))
        self.assertFalse(is_sensitive("HassTurnOn", {"name": "luz do corredor", "area": "portaria"}))
        self.assertTrue(is_sensitive("HassTurnOn", {"name": ["Portões"]}))


class HomeToolsetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for item in (
            patch("mcp_client.show_card", AsyncMock()),
            patch("mcp_client.tool_status", AsyncMock()),
            patch("confirmation.CONFIRMATION_WAIT_SECONDS", 0),
        ):
            item.start()
            self.addCleanup(item.stop)
        STATES.clear()
        self.calls: list = []

    async def tools(self) -> dict:
        inner = FakeInner([raw_tool(name, f"{name} ok", self.calls) for name in ALLOWED])
        toolset = IntegrationToolset(HOME, lambda: inner, timeout=2.0)
        await toolset.setup()
        return {tool.info.name: tool for tool in toolset.tools}

    async def test_the_light_goes_off_without_a_code(self) -> None:
        tools = await self.tools()
        context = FakeRunContext(messages=[FakeMessage("user", "apaga a luz do escritório")])

        result = await tools["home_assistant_HassTurnOff"](context, raw_arguments={"name": "luz do escritório"})

        self.assertIn("HassTurnOff ok", result)
        self.assertEqual(self.calls, [("HassTurnOff", {"name": "luz do escritório"})])
        self.assertNotIn(PENDING_MCP_KEY, context.userdata)

    async def test_unlocking_the_front_door_waits_for_the_code(self) -> None:
        tools = await self.tools()
        context = FakeRunContext(messages=[FakeMessage("user", "destranca a porta da frente")])
        arguments = {"name": "porta da frente", "domain": ["lock"]}

        prepared = await tools["home_assistant_HassTurnOff"](context, raw_arguments=arguments)

        self.assertIn("ainda NÃO executada", prepared)
        self.assertEqual(self.calls, [])
        code = context.userdata[PENDING_MCP_KEY]["code"]
        context.session.history.messages().append(FakeMessage("user", f"confirmar integração {code}"))
        self.assertIn("HassTurnOff ok", await confirm_mcp_action(context, code))
        self.assertEqual(self.calls, [("HassTurnOff", arguments)])

    async def test_asking_about_the_door_just_reads(self) -> None:
        tools = await self.tools()
        result = await tools["home_assistant_GetLiveContext"](raw_arguments={})
        self.assertIn("GetLiveContext ok", result)
        self.assertIn("nunca ordem", result)


@unittest.skipUnless(HAS_MCP, "precisa de pip install 'livekit-agents[mcp]'")
class FakeHomeAssistantTests(unittest.IsolatedAsyncioTestCase):
    """The Home Assistant tools over stdio (tests/mcp_fake_home_assistant.py), through the livekit client."""

    def setUp(self) -> None:
        for item in (patch("mcp_client.show_card", AsyncMock()), patch("mcp_client.tool_status", AsyncMock())):
            item.start()
            self.addCleanup(item.stop)
        self.settings = SimpleNamespace(mcp_timeout=20.0)
        self.path = write_config(
            self,
            {
                "home_assistant": {
                    "comando": sys.executable,
                    "args": [str(FAKE_HOME)],
                    "permitir": list(ALLOWED),
                    "sem_confirmar": list(WRITES),
                }
            },
        )

    async def test_light_runs_door_waits_and_state_is_read(self) -> None:
        tools = build_mcp_tools(self.settings, env={}, path=self.path)
        toolset = next(tool for tool in tools if isinstance(tool, IntegrationToolset))
        await toolset.setup()
        self.addAsyncCleanup(toolset.aclose)
        names = {tool.info.name: tool for tool in toolset.tools}
        self.assertEqual(set(names), {f"home_assistant_{name}" for name in ALLOWED})

        state = await names["home_assistant_GetLiveContext"](raw_arguments={})
        self.assertIn("porta da frente", state)
        self.assertIn("locked", state)

        context = FakeRunContext(messages=[FakeMessage("user", "apaga a luz do escritório")])
        light = await names["home_assistant_HassTurnOff"](context, raw_arguments={"name": "luz do escritório"})
        self.assertIn("Turned off luz do escritório", light)

        context = FakeRunContext(messages=[FakeMessage("user", "abre o portão da garagem")])
        prepared = await names["home_assistant_HassTurnOn"](context, raw_arguments={"name": "portão da garagem", "domain": ["cover"]})
        self.assertIn("ainda NÃO executada", prepared)
        self.assertIn("portão da garagem\n  state: 'closed'", await names["home_assistant_GetLiveContext"](raw_arguments={}))
        code = context.userdata[PENDING_MCP_KEY]["code"]
        context.session.history.messages().append(FakeMessage("user", f"confirmar integração {code}"))
        self.assertIn("Turned on portão da garagem cover", await confirm_mcp_action(context, code))

    async def test_check_says_which_tools_ask_for_the_code(self) -> None:
        text = "\n".join(await mcp_client.check_servers(self.settings, env={}, path=self.path))
        self.assertIn("Home Assistant: conectado (stdio).", text)
        self.assertIn("liberada: GetLiveContext\n", text + "\n")
        self.assertIn("liberada: HassTurnOn (pede código se mexer em porta, fechadura, portão, alarme ou câmera)", text)


if __name__ == "__main__":
    unittest.main()
