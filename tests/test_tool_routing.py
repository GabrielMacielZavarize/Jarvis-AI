from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types
from livekit.agents import llm

import tool_routing
from prompts import build_agent_instructions
from settings import SettingsError, load_settings
from tool_routing import GROUPS, ToolRouter, declaration_count, route_tools, should_route, tool_name
from tools import build_tools, get_current_time, get_weather, set_timer

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

    async def setup(self) -> FakeToolset:
        self.setup_calls += 1
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
    """AgentSession double: current_agent, generate_reply and the speech_created event."""

    def __init__(self) -> None:
        self.current_agent = FakeAgent()
        self.generate_reply = MagicMock()
        self.handlers: dict[str, list] = {}
        self.userdata: dict = {}

    def on(self, event: str, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler) -> None:
        self.handlers.get(event, []).remove(handler)

    def speak(self) -> None:
        handle = SimpleNamespace(wait_for_playout=AsyncMock())
        for handler in list(self.handlers.get("speech_created", [])):
            handler(SimpleNamespace(speech_handle=handle))


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
        for name in ("get_weather", "get_current_time", "set_timer", "show_on_hud", "remember", "change_voice", "end_session", "run_routine", "use_tools"):
            self.assertIn(name, core)
        self.assertIn("get_agenda", names(router.members["agenda"]))
        self.assertIn("open_app", names(router.members["janelas"]))
        self.assertNotIn("open_app", core)
        # Nada se perde: núcleo + grupos = todas as ferramentas.
        grouped = [tool for members in router.members.values() for tool in members]
        self.assertEqual(sorted(names(router.core + grouped)), sorted(names(tools)))
        self.assertLess(len(core), len(tools) / 2)

    def test_tools_unknown_to_the_groups_stay_in_the_core(self) -> None:
        from livekit.agents import function_tool

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


class ResolveAndSelectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ToolRouter(build_tools(load_settings(ALL_FEATURES)), max_loaded=2)

    def test_names_as_the_model_writes_them(self) -> None:
        self.assertEqual(self.router.resolve(["Agenda", "câmera", "janela", "Mídia"]), (["agenda", "camera", "janelas", "midia"], []))
        self.assertEqual(self.router.resolve(["Mouse e teclado"]), (["mouse"], []))
        self.assertEqual(self.router.resolve(["teletransporte"]), ([], ["teletransporte"]))

    def test_oldest_group_leaves_past_the_limit(self) -> None:
        self.assertEqual(self.router.select(["agenda"]), ["agenda"])
        self.assertEqual(self.router.select(["email"]), ["email"])
        self.assertEqual(self.router.select(["agenda"]), [])  # já estava: só fica mais recente
        self.assertEqual(self.router.select(["mouse"]), ["mouse"])
        self.assertEqual(self.router.loaded, ["agenda", "mouse"])
        self.assertIn("get_agenda", names(self.router.agent_tools()))
        self.assertNotIn("draft_email", names(self.router.agent_tools()))

    def test_one_request_may_load_more_groups_than_the_limit(self) -> None:
        self.router.select(["agenda", "email", "mouse"])
        self.assertEqual(self.router.loaded, ["agenda", "email", "mouse"])


class UseToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch("tool_routing.tool_status", new=AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.github = FakeToolset("github", ("list_issues",))
        self.router = ToolRouter([*build_tools(load_settings(ALL_FEATURES)), self.github])
        self.session = FakeSession()

    def context(self, callbacks: list | None = None) -> SimpleNamespace:
        handle = SimpleNamespace(add_done_callback=callbacks.append) if callbacks is not None else None
        return SimpleNamespace(session=self.session, speech_handle=handle, userdata=self.session.userdata)

    async def test_loads_after_the_short_reply_and_goes_on_with_the_request(self) -> None:
        callbacks: list = []
        with patch("tools._tool_reply_is_new_speech", return_value=True):
            result = await self.router.use_tools(self.context(callbacks), groups=["agenda"])
        self.assertIn("Carregando as ferramentas de Agenda", result)
        self.assertIn("Um instante", result)
        self.assertEqual(self.session.current_agent.updates, [])  # nada muda no meio da resposta

        callbacks[0](None)  # a chamada da ferramenta terminou
        await settle()
        self.assertEqual(self.session.current_agent.updates, [])  # ainda falta a frase curta
        self.session.speak()
        await settle()

        (loaded,) = self.session.current_agent.updates
        self.assertIn("get_agenda", names(loaded))
        self.assertNotIn("open_app", names(loaded))
        instructions = self.session.generate_reply.call_args.kwargs["instructions"]
        self.assertIn("Agenda", instructions)
        self.assertIn("Continue agora o último pedido", instructions)

    async def test_pipeline_reply_reuses_the_tool_speech(self) -> None:
        callbacks: list = []
        with patch("tools._tool_reply_is_new_speech", return_value=False):
            await self.router.use_tools(self.context(callbacks), groups=["janelas", "midia"])
        callbacks[0](None)
        await settle()
        loaded = names(self.session.current_agent.tools)
        self.assertIn("open_app", loaded)
        self.assertIn("set_volume", loaded)

    async def test_group_already_loaded_changes_nothing(self) -> None:
        self.router.select(["agenda"])
        result = await self.router.use_tools(self.context([]), groups=["agenda"])
        self.assertIn("já estão com você", result)
        self.assertEqual(self.session.current_agent.updates, [])
        self.session.generate_reply.assert_not_called()

    async def test_unknown_group_lists_the_real_ones(self) -> None:
        result = await self.router.use_tools(self.context([]), groups=["teletransporte"])
        self.assertIn("Não existe grupo teletransporte", result)
        self.assertIn("agenda", result)
        self.assertEqual(self.router.loaded, [])

    async def test_mcp_server_connects_when_its_group_comes_in(self) -> None:
        callbacks: list = []
        with patch("tools._tool_reply_is_new_speech", return_value=False):
            await self.router.use_tools(self.context(callbacks), groups=["github"])
        self.assertEqual(self.github.setup_calls, 0)
        callbacks[0](None)
        await settle()
        self.assertEqual(self.github.setup_calls, 1)
        self.assertIn(self.github, self.session.current_agent.tools)
        await self.router.aclose()
        self.assertEqual(self.github.closed, 1)

    async def test_pending_confirmation_keeps_its_tool_while_groups_change(self) -> None:
        self.session.userdata["pending_calendar"] = {"code": "482913"}
        core = names(self.router.session_tools())
        for groups in (["agenda"], ["email"], ["mouse"], ["janelas"], ["midia"], ["tela"]):
            callbacks: list = []
            with patch("tools._tool_reply_is_new_speech", return_value=False):
                await self.router.use_tools(self.context(callbacks), groups=groups)
            callbacks[0](None)
            await settle()
        self.assertNotIn("agenda", self.router.loaded)  # o grupo saiu...
        self.assertIn("confirm_calendar_change", core)  # ...a confirmação nunca esteve nele
        self.assertNotIn("confirm_calendar_change", names(self.session.current_agent.tools))


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
        self.assertIn("- agenda: Google Agenda", instructions)
        self.assertNotIn("# Ferramentas sob demanda", build_agent_instructions())

    def test_runtime_starts_with_the_core_and_an_empty_agent(self) -> None:
        runtime = runtime_for({**ALL_FEATURES, "JARVIS_TOOL_ROUTING": "true"})
        session_tools = names(runtime.session.tools)
        self.assertIn("use_tools", session_tools)
        self.assertNotIn("get_agenda", session_tools)
        self.assertEqual(runtime.agent.tools, [])
        self.assertIsNotNone(runtime.router)
        self.assertIn("# Ferramentas sob demanda", runtime.agent.instructions)

    def test_runtime_without_routing_is_as_before(self) -> None:
        runtime = runtime_for({**ALL_FEATURES, "JARVIS_TOOL_ROUTING": "false"})
        self.assertIn("get_agenda", names(runtime.session.tools))
        self.assertNotIn("use_tools", names(runtime.session.tools))
        self.assertIsNone(runtime.router)
        self.assertNotIn("# Ferramentas sob demanda", runtime.agent.instructions)

    def test_fallback_model_keeps_the_loaded_groups(self) -> None:
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


# ───────────── livekit-agents 1.8.8: o que o update_tools faz com o Gemini Live ─────────────


class FakeLiveConnection:
    """One Gemini Live websocket: records what was sent, hands out a resumption handle."""

    def __init__(self, number: int) -> None:
        self.number = number
        self.sent: list[list[str]] = []
        self.closed = asyncio.Event()
        self.ready = asyncio.Event()

    async def send_client_content(self, turns, turn_complete=True) -> None:
        self.sent.append([part.text for turn in turns for part in turn.parts if part.text])
        self.ready.set()

    async def send_tool_response(self, function_responses) -> None:
        self.sent.append(["<tool>"])

    async def send_realtime_input(self, **_: object) -> None:
        return None

    async def receive(self):
        await self.ready.wait()
        update = types.LiveServerSessionResumptionUpdate(resumable=True, new_handle=f"handle-{self.number}")
        yield types.LiveServerMessage(session_resumption_update=update)
        await self.closed.wait()

    async def close(self) -> None:
        self.closed.set()


class FakeGenAIClient:
    def __init__(self, *_: object, **__: object) -> None:
        self.connections: list[tuple[types.LiveConnectConfig, FakeLiveConnection]] = []
        outer = self

        class Connect:
            def __init__(self, config: types.LiveConnectConfig) -> None:
                self.config = config

            async def __aenter__(self) -> FakeLiveConnection:
                connection = FakeLiveConnection(len(outer.connections) + 1)
                outer.connections.append((self.config, connection))
                return connection

            async def __aexit__(self, *_: object) -> bool:
                return False

        self.aio = SimpleNamespace(
            live=SimpleNamespace(connect=lambda model, config: Connect(config)),
            aclose=AsyncMock(),
        )


def declared(config: types.LiveConnectConfig) -> list[str]:
    return [fn.name for tool in config.tools or [] for fn in tool.function_declarations or []]


class GeminiUpdateToolsTests(unittest.IsolatedAsyncioTestCase):
    """Pins the plugin behavior FER-33 relies on (see the module docstring of tool_routing)."""

    async def asyncSetUp(self) -> None:
        from livekit.plugins import google

        patcher = patch("livekit.plugins.google.realtime.realtime_api.GenAIClient", FakeGenAIClient)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.model = google.realtime.RealtimeModel(api_key="test-key")
        self.rt = self.model.session()
        self.client = self.rt._client
        await self.wait_connections(1)  # a sessão conecta assim que é criada, ainda sem ferramentas

    async def asyncTearDown(self) -> None:
        await self.rt.aclose()

    async def wait_connections(self, count: int) -> None:
        for _ in range(500):
            if len(self.client.connections) >= count:
                await settle(20)
                return
            await asyncio.sleep(0.002)
        self.fail(f"esperava {count} conexões, vieram {len(self.client.connections)}")

    async def test_update_tools_reopens_the_session_and_keeps_the_conversation(self) -> None:
        self.assertFalse(self.model.capabilities.mutable_tools)
        chat = llm.ChatContext.empty()
        chat.add_message(role="user", content="Que horas são?")
        chat.add_message(role="assistant", content="São dez horas.")
        await self.rt.update_chat_ctx(chat)
        await settle(20)
        _, first = self.client.connections[0]
        self.assertEqual(first.sent, [["Que horas são?", "São dez horas."]])
        self.assertEqual(self.rt.session_resumption_handle, "handle-1")

        later = chat.copy()
        later.add_message(role="user", content="Marca dentista sexta.")
        self.rt._chat_ctx = later  # a transcrição que chegou depois do último handle
        started = time.perf_counter()
        await self.rt.update_tools([get_weather, set_timer])
        await self.wait_connections(2)
        elapsed = time.perf_counter() - started

        config, second = self.client.connections[1]
        self.assertTrue(first.closed.is_set())
        self.assertEqual(declared(config), ["get_weather", "set_timer"])
        self.assertEqual(config.session_resumption.handle, "handle-1")
        # O histórico volta pelo handle; só o que veio depois dele é reenviado.
        self.assertEqual(second.sent[0], ["Marca dentista sexta."])
        self.assertLess(elapsed, 1.0)  # custo local; o real é o handshake com o Google

    async def test_reply_asked_right_after_update_tools_goes_to_the_new_session(self) -> None:
        await self.rt.update_tools([get_weather, set_timer])
        future = self.rt.generate_reply(instructions="Continue o pedido.")
        await self.wait_connections(2)
        _, second = self.client.connections[1]
        self.assertTrue(any("Continue o pedido." in text for sent in second.sent for text in sent))
        future.cancel()

    async def test_same_tools_do_not_reconnect(self) -> None:
        await self.rt.update_tools([get_weather])
        await self.wait_connections(2)
        await self.rt.update_tools([get_weather])
        await settle(20)
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.client.connections), 2)


if __name__ == "__main__":
    unittest.main()
