from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from livekit.agents import RunContext, ToolError, function_tool, llm

import tool_routing
from prompts import build_agent_instructions
from settings import SettingsError, load_settings
from tool_routing import GROUPS, ToolRouter, declaration_count, describe_tool, route_tools, should_route, tool_name
from tools import build_tools, end_session, get_current_time, get_weather, set_timer

ALL_FEATURES = {
    "GOOGLE_API_KEY": "test-key",
    "JARVIS_ENABLE_EMAIL_TOOL": "true",
    "GMAIL_USER": "jarvis@example.com",
    "GMAIL_APP_PASSWORD": "secret",
    "JARVIS_ENABLE_PC_CONTROL": "true",
    "JARVIS_ENABLE_APP_INSTALL": "true",
    "JARVIS_ENABLE_CAMERA": "true",
    "JARVIS_ENABLE_GESTURES": "true",
    "JARVIS_ENABLE_COMPUTER_USE": "true",
    "JARVIS_ENABLE_CALENDAR": "true",
    "JARVIS_PROACTIVE": "true",
    "JARVIS_PRESENCE": "true",
    "JARVIS_MEMORY_EMBEDDINGS": "false",
}


class FakeToolset(llm.Toolset):
    """Stands in for mcp_client.IntegrationToolset: a config with the allowed tools, setup/aclose."""

    def __init__(self, name: str, allowed: tuple[str, ...]) -> None:
        super().__init__(id=f"mcp_{name}")
        self.config = SimpleNamespace(name=name, label=name.capitalize(), allowed=allowed)
        self.setup_calls = 0
        self.closed = 0
        self.calls: list[dict] = []

    async def setup(self) -> FakeToolset:
        self.setup_calls += 1
        await asyncio.sleep(0)  # o servidor demora um pouco para subir
        calls = self.calls

        async def run(raw_arguments: dict) -> str:
            calls.append(raw_arguments)
            return f"{len(raw_arguments)} argumento(s)"

        schema = {
            "name": f"{self.config.name}_{self.config.allowed[0]}",
            "description": f"[{self.config.label} via MCP] lista coisas",
            "parameters": {"type": "object", "properties": {"state": {"type": "string"}}},
        }
        self._tools = [function_tool(run, raw_schema=schema)]
        return self

    async def aclose(self) -> None:
        self.closed += 1


class FakeAgent:
    def __init__(self) -> None:
        self.tools: list = []
        self.updates: list[list] = []

    async def update_tools(self, tools: list) -> None:
        self.tools = list(tools)
        self.updates.append(list(tools))


class FakeSession:
    """AgentSession double: what RunContext and the tools read from it."""

    def __init__(self) -> None:
        self.current_agent = FakeAgent()
        self.generate_reply = MagicMock()
        self.userdata: dict = {}
        self._global_run_state = None


def run_context(session: FakeSession, name: str = "run_tool") -> RunContext:
    call = llm.FunctionCall(call_id="call-1", name=name, arguments="{}")
    return RunContext(session=session, speech_handle=SimpleNamespace(num_steps=1), function_call=call)


def names(tools: list) -> list[str]:
    return [tool_name(tool) or tool.id for tool in tools]


async def settle(rounds: int = 6) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class GroupTests(unittest.TestCase):
    def test_confirmation_tools_never_go_to_a_group(self) -> None:
        router = ToolRouter(build_tools(load_settings(ALL_FEATURES)))
        core = names(router.core)
        for name in ("confirm_email_send", "confirm_app_install", "confirm_screen_action", "confirm_calendar_change", "confirm_routine_step"):
            self.assertIn(name, core)
        for group in GROUPS:
            self.assertFalse([tool for tool in group.tools if tool.startswith("confirm_")], group.name)

    def test_core_keeps_the_basics_and_groups_take_the_rest(self) -> None:
        tools = build_tools(load_settings(ALL_FEATURES))
        router = ToolRouter(tools)
        core = names(router.session_tools())
        for name in ("get_weather", "get_current_time", "set_timer", "show_on_hud", "remember", "change_voice", "end_session", "run_routine", "use_tools", "run_tool"):
            self.assertIn(name, core)
        self.assertIn("get_agenda", names(router.members["agenda"]))
        self.assertIn("open_app", names(router.members["janelas"]))
        self.assertNotIn("open_app", core)
        # Nada se perde: núcleo + grupos = todas as ferramentas.
        grouped = [tool for members in router.members.values() for tool in members]
        self.assertEqual(sorted(names(router.core + grouped)), sorted(names(tools)))
        self.assertLess(len(core), len(tools) / 2)

    def test_tools_unknown_to_the_groups_stay_in_the_core(self) -> None:
        @function_tool()
        async def brand_new_tool() -> str:
            """A tool another module added."""
            return "ok"

        router = ToolRouter([get_weather, brand_new_tool])
        self.assertEqual(names(router.core), ["get_weather", "brand_new_tool"])
        self.assertEqual(router.groups, {})

    def test_each_mcp_server_is_its_own_group(self) -> None:
        github = FakeToolset("github", ("list_issues", "issue_read"))
        router = ToolRouter([get_weather, github])
        self.assertIn("github", router.groups)
        self.assertEqual(router.members["github"], [github])
        self.assertIn("GitHub".lower(), router.summary().lower())


class RoutingModeTests(unittest.TestCase):
    def test_setting_defaults_to_auto_and_accepts_booleans(self) -> None:
        self.assertEqual(load_settings({}).tool_routing, "auto")
        self.assertEqual(load_settings({"JARVIS_TOOL_ROUTING": "AUTO"}).tool_routing, "auto")
        self.assertEqual(load_settings({"JARVIS_TOOL_ROUTING": "yes"}).tool_routing, "true")
        self.assertEqual(load_settings({"JARVIS_TOOL_ROUTING": "0"}).tool_routing, "false")
        with self.assertRaises(SettingsError):
            load_settings({"JARVIS_TOOL_ROUTING": "talvez"})

    def test_auto_routes_only_big_tool_sets(self) -> None:
        small = build_tools(load_settings({"GOOGLE_API_KEY": "k"}))
        big = build_tools(load_settings(ALL_FEATURES))
        self.assertLessEqual(declaration_count(small), tool_routing.AUTO_MIN_TOOLS)
        self.assertGreater(declaration_count(big), tool_routing.AUTO_MIN_TOOLS)
        self.assertFalse(should_route("auto", small))
        self.assertTrue(should_route("auto", big))
        self.assertTrue(should_route("true", small))
        self.assertFalse(should_route("false", big))

    def test_mcp_servers_count_their_allowed_tools(self) -> None:
        server = FakeToolset("github", tuple(f"tool_{n}" for n in range(70)))
        self.assertEqual(declaration_count([get_weather, server]), 71)
        self.assertTrue(should_route("auto", [get_weather, server]))

    def test_false_keeps_every_tool_as_today(self) -> None:
        tools = build_tools(load_settings(ALL_FEATURES))
        routed, router = route_tools(tools, "false")
        self.assertIs(routed, tools)
        self.assertIsNone(router)

    def test_nothing_to_group_means_no_router(self) -> None:
        routed, router = route_tools([get_weather, set_timer], "true")
        self.assertEqual(routed, [get_weather, set_timer])
        self.assertIsNone(router)


class ResolveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ToolRouter(build_tools(load_settings(ALL_FEATURES)))

    def test_names_as_the_model_writes_them(self) -> None:
        self.assertEqual(self.router.resolve(["Agenda", "câmera", "janela", "Mídia"]), (["agenda", "camera", "janelas", "midia"], []))
        self.assertEqual(self.router.resolve(["Mouse e teclado"]), (["mouse"], []))
        self.assertEqual(self.router.resolve(["teletransporte"]), ([], ["teletransporte"]))

    def test_tool_descriptions_carry_the_parameters_without_pydantic_titles(self) -> None:
        entry = describe_tool(get_weather)
        self.assertEqual(entry["name"], "get_weather")
        self.assertIn("weather", entry["description"])
        self.assertEqual(entry["parameters"]["required"], ["city"])
        self.assertNotIn("title", json.dumps(entry))
        self.assertNotIn("parameters", describe_tool(end_session))  # sem parâmetros, sem ruído

    def test_every_real_group_describes_its_tools(self) -> None:
        for group, members in self.router.members.items():
            for tool in members:
                entry = describe_tool(tool)
                self.assertTrue(entry["name"] and entry["description"], f"{group}: {entry}")
                json.dumps(entry)  # vai como texto para o modelo


# Ferramentas de grupo de mentira com os nomes das de verdade: registram como foram chamadas.
CALLS: list[tuple] = []


@function_tool()
async def get_agenda(context: RunContext, day: str = "hoje") -> str:
    """Compromissos de um dia.

    Args:
        day: hoje, amanhã ou uma data.
    """
    CALLS.append((context, day))
    return f"Agenda de {day}: dentista às 15h."


@function_tool()
async def gesture_control(context: RunContext, action: str) -> str:
    """Liga e desliga os gestos.

    Args:
        action: on ou off.
    """
    raise ToolError("Não consegui ligar os gestos: a webcam não enviou imagens em 8 s.")


class UseToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch("tool_routing.tool_status", new=AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)
        CALLS.clear()
        self.github = FakeToolset("github", ("list_issues",))
        self.router = ToolRouter([get_weather, get_agenda, gesture_control, set_timer, self.github])
        self.session = FakeSession()
        self.context = run_context(self.session, "use_tools")

    async def test_use_tools_hands_the_group_in_the_same_reply_without_reconnecting(self) -> None:
        result = await self.router.use_tools(self.context, groups=["agenda"])
        self.assertIn("Ferramentas de Agenda", result)
        line = next(line for line in result.splitlines() if line.startswith("{"))
        entry = json.loads(line)
        self.assertEqual(entry["name"], "get_agenda")
        self.assertIn("day", entry["parameters"]["properties"])
        self.assertIn("nesta mesma resposta", result)
        self.assertIn("run_tool", result)
        self.assertNotIn("Um instante", result)
        # Nada de update_tools nem de generate_reply: o Gemini Live não reconecta.
        self.assertEqual(self.session.current_agent.updates, [])
        self.session.generate_reply.assert_not_called()
        self.assertEqual(self.router.used, ["agenda"])

    async def test_run_tool_runs_the_real_tool_with_the_call_context(self) -> None:
        context = run_context(self.session)
        result = await self.router.run_tool(context, name="get_agenda", arguments='{"day": "amanhã"}')
        self.assertEqual(result, "Agenda de amanhã: dentista às 15h.")
        self.assertEqual(CALLS, [(context, "amanhã")])
        self.assertEqual(await self.router.run_tool(context, name="get_agenda"), "Agenda de hoje: dentista às 15h.")
        self.assertEqual(self.router.used, ["agenda"])

    async def test_wrong_arguments_come_back_with_the_right_parameters(self) -> None:
        with self.assertRaises(ToolError) as caught:
            await self.router.run_tool(run_context(self.session), name="gesture_control", arguments='{"acao": "on"}')
        self.assertIn("Parâmetros de gesture_control", str(caught.exception))
        self.assertIn('"action"', str(caught.exception))

    async def test_the_tool_error_reaches_the_model_as_is(self) -> None:
        with self.assertRaises(ToolError) as caught:
            await self.router.run_tool(run_context(self.session), name="gesture_control", arguments='{"action": "on"}')
        self.assertIn("webcam não enviou imagens", str(caught.exception))

    async def test_unknown_tool_points_to_use_tools(self) -> None:
        with self.assertRaises(ToolError) as caught:
            await self.router.run_tool(run_context(self.session), name="teleport", arguments="{}")
        self.assertIn("use_tools", str(caught.exception))
        with self.assertRaises(ToolError):  # as do núcleo não passam por aqui: o modelo já as tem
            await self.router.run_tool(run_context(self.session), name="get_weather", arguments='{"city": "Criciúma"}')

    async def test_unknown_group_lists_the_real_ones(self) -> None:
        result = await self.router.use_tools(self.context, groups=["teletransporte"])
        self.assertIn("Não existe grupo teletransporte", result)
        self.assertIn("agenda", result)
        self.assertEqual(self.router.used, [])

    async def test_mcp_server_warms_up_once_and_its_tools_run_through_run_tool(self) -> None:
        self.router.warm_up()
        result, again = await asyncio.gather(
            self.router.use_tools(self.context, groups=["github"]),
            self.router.use_tools(self.context, groups=["github"]),
        )
        self.assertEqual(self.github.setup_calls, 1)  # o aquecimento e os dois pedidos dividem a conexão
        self.assertIn("github_list_issues", result)
        self.assertEqual(result, again)
        output = await self.router.run_tool(run_context(self.session), name="github_list_issues", arguments='{"state": "open"}')
        self.assertEqual(output, "1 argumento(s)")
        self.assertEqual(self.github.calls, [{"state": "open"}])
        await self.router.aclose()
        self.assertEqual(self.github.closed, 1)

    async def test_mcp_server_never_connected_is_not_closed(self) -> None:
        await self.router.aclose()
        self.assertEqual(self.github.closed, 0)

    async def test_offline_server_says_so_instead_of_an_empty_list(self) -> None:
        async def offline(toolset: FakeToolset) -> FakeToolset:
            toolset._tools = []
            return toolset

        with patch.object(FakeToolset, "setup", offline):
            result = await self.router.use_tools(self.context, groups=["github"])
        self.assertIn("nenhuma ferramenta disponível", result)

    def test_confirmations_stay_in_the_core(self) -> None:
        router = ToolRouter(build_tools(load_settings(ALL_FEATURES)))
        core = names(router.session_tools())
        self.assertIn("confirm_calendar_change", core)
        self.assertIn("run_tool", core)
        self.assertIn("use_tools", core)


def runtime_for(env: dict[str, str]):
    from backends import build_runtime

    async def build():
        with patch("backends._monitor_layout", return_value=None):
            return build_runtime(load_settings(env), load_vad=False)

    return asyncio.run(build())


class PromptAndRuntimeTests(unittest.TestCase):
    def test_prompt_lists_the_groups_only_when_routing(self) -> None:
        router = ToolRouter(build_tools(load_settings(ALL_FEATURES)))
        instructions = build_agent_instructions(tool_groups=router.summary())
        self.assertIn("# Ferramentas sob demanda", instructions)
        self.assertIn("use_tools", instructions)
        self.assertIn("run_tool", instructions)
        self.assertNotIn("Um instante", instructions)
        self.assertIn("- agenda: Google Agenda", instructions)
        self.assertNotIn("# Ferramentas sob demanda", build_agent_instructions())

    def test_runtime_starts_with_the_core_and_an_empty_agent(self) -> None:
        runtime = runtime_for({**ALL_FEATURES, "JARVIS_TOOL_ROUTING": "true"})
        session_tools = names(runtime.session.tools)
        self.assertIn("use_tools", session_tools)
        self.assertIn("run_tool", session_tools)
        self.assertNotIn("get_agenda", session_tools)
        self.assertEqual(runtime.agent.tools, [])
        self.assertIsNotNone(runtime.router)
        self.assertIn("# Ferramentas sob demanda", runtime.agent.instructions)

    def test_runtime_without_routing_is_as_before(self) -> None:
        runtime = runtime_for({**ALL_FEATURES, "JARVIS_TOOL_ROUTING": "false"})
        self.assertIn("get_agenda", names(runtime.session.tools))
        self.assertNotIn("use_tools", names(runtime.session.tools))
        self.assertNotIn("run_tool", names(runtime.session.tools))
        self.assertIsNone(runtime.router)
        self.assertNotIn("# Ferramentas sob demanda", runtime.agent.instructions)

    def test_fallback_model_keeps_the_agent_tools(self) -> None:
        from backends import JarvisAgent, watch_model_failover
        from model_pool import ModelPool
        from test_model_pool import MODELS, Clock
        from test_model_pool import FakeSession as PoolSession

        async def scenario() -> PoolSession:
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            pool = ModelPool(MODELS, path=Path(folder.name) / "modelos.json", clock=Clock())
            agent = JarvisAgent("Você é o Jarvis.", tools=[get_current_time])
            session = PoolSession(agent)
            runtime = SimpleNamespace(settings=load_settings({"GOOGLE_API_KEY": "k"}), session=session, agent=agent, model=MODELS[0])
            watch_model_failover(runtime, pool)
            error = llm.RealtimeModelError(timestamp=0, label="g", error=RuntimeError("429 quota"), recoverable=False)
            session.handlers["error"](SimpleNamespace(error=error))
            await settle()
            return session

        session = asyncio.run(scenario())
        self.assertEqual(names(session.updated[0].tools), ["get_current_time"])


if __name__ == "__main__":
    unittest.main()
