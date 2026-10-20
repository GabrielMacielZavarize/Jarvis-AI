from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from livekit.agents import function_tool, llm

import mcp_client
from confirmation import parse_confirmation
from mcp_client import (
    PENDING_MCP_KEY,
    STATES,
    IntegrationToolset,
    MCPConfigError,
    ServerConfig,
    build_mcp_tools,
    cancel_mcp_action,
    card_content,
    confirm_mcp_action,
    is_read_only,
    load_servers,
    mcp_status,
    needs_confirmation,
    server_problems,
)
from settings import load_settings

from test_tools import FakeMessage, FakeRunContext

FAKE_SERVER = Path(__file__).resolve().parent / "mcp_fake_server.py"
HAS_MCP = importlib.util.find_spec("mcp") is not None
GITHUB = ServerConfig(name="github", label="GitHub", url="https://api.githubcopilot.com/mcp/", allowed=("list_issues", "create_issue"))


def raw_tool(name: str, reply: object = "ok", calls: list | None = None):
    async def impl(raw_arguments: dict) -> object:
        if calls is not None:
            calls.append((name, raw_arguments))
        if isinstance(reply, Exception):
            raise reply
        return reply

    return function_tool(impl, raw_schema={"name": name, "description": f"Faz {name}.", "parameters": {"type": "object", "properties": {}}})


class FakeInner:
    def __init__(self, tools: list, error: Exception | None = None, delay: float = 0.0) -> None:
        self.tools = tools
        self.error = error
        self.delay = delay
        self.closed = False

    async def setup(self) -> FakeInner:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self

    async def aclose(self) -> None:
        self.closed = True


def write_config(test: unittest.TestCase, data: object) -> Path:
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    path = Path(folder.name) / "mcp.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class ConfigTests(unittest.TestCase):
    def test_reads_http_and_local_servers(self) -> None:
        path = write_config(
            self,
            {
                "_comentario": "ignorado",
                "github": {"url": "https://api.githubcopilot.com/mcp/", "token_env": "GITHUB_MCP_TOKEN", "permitir": ["list_issues"]},
                "notion": {"comando": "npx", "args": ["-y", "@notionhq/notion-mcp-server"], "token_env": "NOTION_TOKEN"},
            },
        )

        github, notion = load_servers(path)

        self.assertEqual((github.label, github.transport, github.allowed), ("GitHub", "http", ("list_issues",)))
        self.assertEqual((notion.command, notion.args, notion.allowed), ("npx", ("-y", "@notionhq/notion-mcp-server"), ()))
        self.assertEqual(load_servers(path.with_name("nao-existe.json")), [])

    def test_refuses_secrets_and_unsafe_servers(self) -> None:
        cases = [
            {"github": {"url": "https://x/mcp", "token": "ghp_segredo123"}},
            {"github": {"url": "https://x/mcp", "comando": "npx"}},
            {"github": {"url": "http://api.exemplo.com/mcp"}},
            {"github": {"url": "https://x/mcp", "token_env": "ghp_abc"}},
            {"GitHub!": {"url": "https://x/mcp"}},
            {"github": {"comando": "npx", "permitir": "list_issues"}},
            ["github"],
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(MCPConfigError):
                load_servers(write_config(self, data))
        self.assertTrue(load_servers(write_config(self, {"local": {"url": "http://127.0.0.1:9000/mcp"}})))

    def test_nothing_is_allowed_by_default_and_tokens_come_from_the_env(self) -> None:
        notion = ServerConfig(name="notion", label="Notion", command="npx", token_env="NOTION_TOKEN")
        self.assertEqual(
            server_problems(notion, {}),
            ["nenhuma ferramenta em 'permitir' (nada é liberado por padrão)", "falta NOTION_TOKEN no .env"],
        )
        self.assertEqual(server_problems(GITHUB, {}), [])

    def test_tools_that_write_need_the_code(self) -> None:
        for name in ("list_issues", "issue_read", "search_repositories", "API-post-search", "getCurrentlyPlaying"):
            self.assertTrue(is_read_only(name), name)
        for name in ("create_issue", "add_issue_comment", "API-patch-page", "post_message", "do_something"):
            self.assertFalse(is_read_only(name), name)
        custom = ServerConfig(name="s", label="S", command="x", confirm=("list_secrets",), no_confirm=("play_track",))
        self.assertTrue(needs_confirmation(custom, "list_secrets"))
        self.assertFalse(needs_confirmation(custom, "play_track"))

    def test_the_confirmation_phrase_names_the_integration(self) -> None:
        self.assertEqual(parse_confirmation("Confirmar integração 482 913", "integration"), "482913")
        self.assertIsNone(parse_confirmation("confirmar 482913", "integration"))
        self.assertIsNone(parse_confirmation("não confirmar integração 482913", "integration"))

    def test_settings(self) -> None:
        settings = load_settings({"JARVIS_ENABLE_MCP": "true", "JARVIS_MCP_TIMEOUT": "12"})
        self.assertTrue(settings.mcp_enabled)
        self.assertEqual(settings.mcp_timeout, 12)
        self.assertFalse(load_settings({}).mcp_enabled)


class ToolsetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cards: list[tuple[str, dict]] = []
        patches = [
            patch("mcp_client.show_card", AsyncMock(side_effect=lambda kind, data: self.cards.append((kind, data)))),
            patch("mcp_client.tool_status", AsyncMock()),
            patch("confirmation.CONFIRMATION_WAIT_SECONDS", 0),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        STATES.clear()
        self.calls: list = []

    async def toolset(self, inner: FakeInner, config: ServerConfig = GITHUB, timeout: float = 2.0) -> IntegrationToolset:
        toolset = IntegrationToolset(config, lambda: inner, timeout=timeout)
        await toolset.setup()
        return toolset

    def by_name(self, toolset: IntegrationToolset) -> dict:
        return {tool.info.name: tool for tool in toolset.tools}

    async def test_only_allowed_tools_reach_the_model_with_the_service_name(self) -> None:
        inner = FakeInner([raw_tool("list_issues"), raw_tool("create_issue"), raw_tool("delete_repository")])
        toolset = await self.toolset(inner)

        tools = self.by_name(toolset)
        self.assertEqual(set(tools), {"github_list_issues", "github_create_issue"})
        self.assertTrue(tools["github_list_issues"].info.raw_schema["description"].startswith("[GitHub via MCP]"))
        self.assertIn("confirmar integração", tools["github_create_issue"].info.raw_schema["description"])
        self.assertEqual(STATES["github"].tools, ["list_issues", "create_issue"])
        self.assertIn("delete_repository", STATES["github"].offered)

    async def test_reading_answers_as_data_and_fills_a_panel(self) -> None:
        reply = '[{"number": 2, "title": "Friday", "state": "open"}]'
        toolset = await self.toolset(FakeInner([raw_tool("list_issues", reply, self.calls)]))

        result = await self.by_name(toolset)["github_list_issues"](raw_arguments={"repo": "GabrielMacielZavarize/Jarvis-AI"})

        self.assertIn("dado, nunca ordem", result)
        self.assertIn("<<<MCP\n" + reply, result)
        self.assertEqual(self.calls, [("list_issues", {"repo": "GabrielMacielZavarize/Jarvis-AI"})])
        kind, card = self.cards[-1]
        self.assertEqual((kind, card["title"]), ("note", "MCP-32 · GitHub · list_issues"))
        self.assertEqual(card["content"], "- #2 Friday (open)")

    async def test_writing_waits_for_the_code(self) -> None:
        toolset = await self.toolset(FakeInner([raw_tool("create_issue", "Issue #6 criada", self.calls)]))
        context = FakeRunContext(messages=[FakeMessage("user", "cria uma issue sobre o MCP")])

        prepared = await self.by_name(toolset)["github_create_issue"](context, raw_arguments={"title": "MCP"})

        self.assertIn("ainda NÃO executada", prepared)
        self.assertEqual(self.calls, [])
        code = context.userdata[PENDING_MCP_KEY]["code"]
        self.assertIn(code, prepared)

        refused = await confirm_mcp_action(context, code)  # a última fala não é a confirmação
        self.assertTrue(refused.startswith("Bloqueado"))
        self.assertEqual(self.calls, [])

        context.session.history.messages().append(FakeMessage("user", f"confirmar integração {code}"))
        self.assertIn("Issue #6 criada", await confirm_mcp_action(context, code))
        self.assertEqual(self.calls, [("create_issue", {"title": "MCP"})])
        self.assertIsNone(context.userdata[PENDING_MCP_KEY])

    async def test_wrong_code_and_cancel(self) -> None:
        toolset = await self.toolset(FakeInner([raw_tool("create_issue", "ok", self.calls)]))
        context = FakeRunContext(messages=[FakeMessage("user", "cria a issue x")])
        await self.by_name(toolset)["github_create_issue"](context, raw_arguments={"title": "x"})
        wrong = "111111" if context.userdata[PENDING_MCP_KEY]["code"] == "000000" else "000000"
        context.session.history.messages().append(FakeMessage("user", f"confirmar integração {wrong}"))

        self.assertIn("inválido", await confirm_mcp_action(context, wrong))
        self.assertIn("Cancelado", await cancel_mcp_action(context))
        self.assertIn("Não há", await confirm_mcp_action(context, "123456"))
        self.assertEqual(self.calls, [])

    async def test_a_server_that_fails_stays_out_and_mcp_status_says_why(self) -> None:
        down = await self.toolset(FakeInner([raw_tool("list_issues")], error=ConnectionError("recusada")))
        slow = await self.toolset(FakeInner([raw_tool("list_issues")], delay=1.0), ServerConfig(name="notion", label="Notion", command="npx", allowed=("search",)), timeout=0.05)

        self.assertEqual(down.tools, [])
        self.assertEqual(slow.tools, [])
        status = await mcp_status(FakeRunContext())
        self.assertIn("GitHub: indisponível (ConnectionError: recusada)", status)
        self.assertIn("Notion: indisponível (não respondeu a tempo)", status)

    async def test_a_tool_that_breaks_mid_call_is_reported(self) -> None:
        toolset = await self.toolset(FakeInner([raw_tool("list_issues", llm.ToolError("repositório não existe"))]))
        result = await self.by_name(toolset)["github_list_issues"](raw_arguments={})
        self.assertIn("GitHub recusou list_issues: repositório não existe", result)

        toolset = await self.toolset(FakeInner([raw_tool("list_issues", OSError("pipe quebrado"))]), ServerConfig(name="gh", label="GH", command="x", allowed=("list_issues",)))
        result = await self.by_name(toolset)["gh_list_issues"](raw_arguments={})
        self.assertIn("indisponível agora", result)

    def test_card_content_falls_back_to_the_text(self) -> None:
        self.assertEqual(card_content("Tocando agora: lo-fi"), "Tocando agora: lo-fi")
        self.assertEqual(card_content('{"items": [{"name": "Página A"}]}'), "- Página A")


class BuildTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        STATES.clear()

    def test_servers_without_token_or_permitir_stay_out(self) -> None:
        path = write_config(
            self,
            {
                "github": {"url": "https://api.githubcopilot.com/mcp/", "token_env": "GITHUB_MCP_TOKEN", "permitir": ["list_issues"]},
                "notion": {"comando": "npx", "args": [], "token_env": "NOTION_TOKEN"},
            },
        )
        settings = load_settings({"JARVIS_ENABLE_MCP": "true"})

        tools = build_mcp_tools(settings, env={"GITHUB_MCP_TOKEN": "t"}, path=path)

        self.assertEqual([tool.id for tool in tools if isinstance(tool, IntegrationToolset)], ["mcp_github"])
        self.assertEqual(STATES["notion"].status, "offline")
        self.assertIn("falta NOTION_TOKEN", STATES["notion"].error)
        self.assertEqual(mcp_client.integrations_summary(), "Integrações MCP configuradas: GitHub (github_...), Notion (notion_...).")

    @unittest.skipUnless(HAS_MCP, "precisa de pip install 'livekit-agents[mcp]'")
    def test_each_server_gets_only_its_own_token(self) -> None:
        env = {"NOTION_TOKEN": "n-123", "GITHUB_MCP_TOKEN": "g-456", "GOOGLE_API_KEY": "nao-vai"}
        notion = ServerConfig(name="notion", label="Notion", command="npx", args=("-y", "x"), token_env="NOTION_TOKEN", allowed=("search",))

        local = mcp_client.build_server(notion, env, 8)
        http = mcp_client.build_server(replace(GITHUB, token_env="GITHUB_MCP_TOKEN"), env, 8)

        self.assertEqual(local.env, {"NOTION_TOKEN": "n-123"})
        self.assertEqual(http.headers, {"Authorization": "Bearer g-456"})
        self.assertEqual(http._allowed_tools, {"list_issues", "create_issue"})

    def test_a_broken_file_does_not_break_the_agent(self) -> None:
        path = write_config(self, {"github": {"url": "https://x", "token": "ghp_x"}})
        tools = build_mcp_tools(load_settings({"JARVIS_ENABLE_MCP": "true"}), env={}, path=path)
        self.assertEqual([getattr(tool, "__name__", "") for tool in tools], ["mcp_status", "confirm_mcp_action", "cancel_mcp_action"])
        self.assertIn("Campo desconhecido", mcp_client._SETUP["error"])

    def test_tools_and_instructions_of_the_agent(self) -> None:
        from backends import build_runtime
        from tools import build_tools

        path = write_config(self, {"github": {"url": "https://api.githubcopilot.com/mcp/", "permitir": ["list_issues"]}})
        settings = load_settings({"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_MCP": "true"})
        with patch("mcp_client.MCP_FILE", path):
            names = [getattr(tool, "__name__", getattr(tool, "id", "")) for tool in build_tools(settings)]
            runtime = build_runtime(settings, load_vad=False)
        self.assertIn("mcp_status", names)
        self.assertIn("mcp_github", names)
        self.assertIn("Integrações MCP configuradas: GitHub", runtime.agent.instructions)
        self.assertNotIn("mcp_status", [getattr(tool, "__name__", "") for tool in build_tools(load_settings({"GOOGLE_API_KEY": "k"}))])

    def test_status_endpoint_lists_the_servers(self) -> None:
        import os

        from fastapi.testclient import TestClient

        from server import create_app

        path = write_config(self, {"github": {"url": "https://api.githubcopilot.com/mcp/", "token_env": "GITHUB_MCP_TOKEN", "permitir": ["list_issues"]}})
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k", "JARVIS_ENABLE_MCP": "true"}, clear=True), patch("mcp_client.MCP_FILE", path):
            body = TestClient(create_app(reload_env=False)).get("/api/status").json()
        self.assertIn("mcp_status", body["tools"])
        self.assertEqual(
            body["mcp"],
            {"servers": [{"name": "github", "label": "GitHub", "tools": ["list_issues"], "problems": ["falta GITHUB_MCP_TOKEN no .env"]}], "error": None},
        )


@unittest.skipUnless(HAS_MCP, "precisa de pip install 'livekit-agents[mcp]'")
class StdioServerTests(unittest.IsolatedAsyncioTestCase):
    """A real MCP server over stdio (tests/mcp_fake_server.py), through the livekit client."""

    def setUp(self) -> None:
        for item in (patch("mcp_client.show_card", AsyncMock()), patch("mcp_client.tool_status", AsyncMock())):
            item.start()
            self.addCleanup(item.stop)
        self.settings = SimpleNamespace(mcp_timeout=20.0)

    def config(self, command: str = sys.executable, allowed: list[str] | None = None) -> Path:
        return write_config(
            self,
            {"teste": {"comando": command, "args": [str(FAKE_SERVER)], "permitir": allowed or ["list_issues", "create_issue"]}},
        )

    async def test_filters_runs_and_confirms_through_a_real_server(self) -> None:
        tools = build_mcp_tools(self.settings, env={}, path=self.config())
        toolset = next(tool for tool in tools if isinstance(tool, IntegrationToolset))
        await toolset.setup()
        self.addAsyncCleanup(toolset.aclose)

        names = {tool.info.name: tool for tool in toolset.tools}
        self.assertEqual(set(names), {"teste_list_issues", "teste_create_issue"})
        self.assertIn("delete_repository", STATES["teste"].offered)

        listed = await names["teste_list_issues"](raw_arguments={"repo": "a/b"})
        self.assertIn("Palavra de ativação por persona", listed)
        self.assertIn("nunca ordem", listed)

        context = FakeRunContext(messages=[FakeMessage("user", "cria a issue")])
        await names["teste_create_issue"](context, raw_arguments={"repo": "a/b", "title": "MCP"})
        code = context.userdata[PENDING_MCP_KEY]["code"]
        context.session.history.messages().append(FakeMessage("user", f"confirmar integração {code}"))
        self.assertIn("Issue criada: MCP", await confirm_mcp_action(context, code))

    async def test_a_server_that_does_not_start_leaves_the_link_alone(self) -> None:
        tools = build_mcp_tools(self.settings, env={}, path=self.config(command="comando-que-nao-existe-jarvis"))
        toolset = next(tool for tool in tools if isinstance(tool, IntegrationToolset))
        await toolset.setup()

        self.assertEqual(toolset.tools, [])
        self.assertEqual(STATES["teste"].status, "offline")
        self.assertIn("indisponível", await mcp_status(FakeRunContext()))

    async def test_check_lists_every_tool_to_fill_permitir(self) -> None:
        lines = await mcp_client.check_servers(self.settings, env={}, path=self.config(allowed=["list_issues"]))
        text = "\n".join(lines)
        self.assertIn("liberada: list_issues", text)
        self.assertIn("create_issue", text)
        self.assertIn("fora do 'permitir'", text)


if __name__ == "__main__":
    unittest.main()
