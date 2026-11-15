"""Ferramentas sob demanda (protocolo FER-33): o Gemini Live só vê as ferramentas do assunto.

Com tudo ligado o Jarvis passa de 75 ferramentas (cerca de 14 mil tokens só de declarações) e,
com as integrações MCP, de 100. Com tantas o modelo escolhe pior. Aqui elas viram:

- um núcleo sempre declarado: clima, pesquisa, hora, timers, HUD, memória, tarefas e notas, voz, encerrar, tudo
  o que não está em grupo nenhum (inclusive ferramentas novas) e TODAS as de confirmar e cancelar
  por código, para uma confirmação pendente nunca perder a sua ferramenta;
- grupos (agenda, email, tela, janelas, mídia, mouse, gestos, câmera, rotinas, avisos, apps e um
  por servidor MCP) que o modelo usa em dois passos, na mesma resposta:
  ``use_tools(["agenda"])`` devolve as ferramentas do grupo com os parâmetros, e
  ``run_tool("get_agenda", '{"day": "hoje"}')`` executa uma delas.

Por que não ``Agent.update_tools``: no Gemini Live (livekit-agents 1.8.8) ele fecha a conexão e
reabre com o handle de retomada. Isso deixava ~7 s de silêncio, a resposta em andamento sem
ferramenta (o modelo emendava "não consigo acessar sua agenda" no "um instante") e, nos logs de
outubro de 2026, nenhuma ferramenta de grupo chegou a ser chamada depois da troca: a sessão
retomada seguiu com as declarações do começo. Com ``run_tool`` nada reconecta, as declarações
ficam as mesmas a conversa inteira e o pedido é feito na mesma resposta em que o modelo pediu o
grupo. No 1.8.11 o plugin passou a abrir uma sessão nova e reenviar a conversa em texto, mas a
troca no meio de uma resposta ainda descarta a fila e a resposta em andamento; o ``run_tool``
continua evitando tudo isso.

As integrações MCP conectam em segundo plano quando o link abre (``warm_up``): o primeiro pedido
ao Notion não espera o servidor subir, e o ``mcp_status`` não diz mais "conectando" à toa.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any

from livekit.agents import RunContext, ToolError, function_tool, llm
from livekit.agents.llm.utils import build_legacy_openai_schema, prepare_function_arguments

from confirmation import strip_accents
from hud import tool_status

logger = logging.getLogger("jarvis-tool-routing")

PROTOCOL = "FER-33"
ROUTING_MODES = ("auto", "true", "false")
# "auto" liga a separação quando a sessão passa disso (MCP conta as ferramentas do "permitir").
AUTO_MIN_TOOLS = 60
# Descrição de cada ferramenta na resposta do use_tools (as dos grupos cabem folgadas nisso).
MAX_DESCRIPTION_CHARS = 700
READY_NOTE = (
    "Agora, nesta mesma resposta e sem dizer nada antes, chame run_tool com o name de uma delas e os "
    "arguments em JSON. Só fale depois do resultado do run_tool, contando o que ele disse de verdade."
)


@dataclass(frozen=True)
class ToolGroup:
    name: str
    label: str
    description: str
    tools: tuple[str, ...]


# Confirmar e cancelar (confirm_*, cancel_*) ficam fora de propósito: estão sempre no núcleo. Tarefas e
# notas (add_task, add_note, list_tasks, complete_task, remove_task) também: são pedidos de todo dia e,
# se ficassem num grupo, "anota aí" cairia no remember (que está no núcleo) por falta da ferramenta certa.
GROUPS: tuple[ToolGroup, ...] = (
    ToolGroup(
        "agenda",
        "Agenda",
        "Google Agenda: compromissos do dia, próxima reunião, marcar, mudar ou desmarcar eventos",
        ("get_agenda", "next_meeting", "prepare_calendar_event", "prepare_calendar_update", "prepare_calendar_delete"),
    ),
    ToolGroup("email", "Email", "escrever e enviar email, conferir um endereço", ("check_email_address", "draft_email")),
    ToolGroup(
        "tela",
        "Assistente de tela",
        "ler, explicar ou copiar o que está na tela, erros, prints, ficar de olho numa janela",
        ("look_at_screen", "explain_screen", "copy_fix", "take_screenshot", "watch_screen"),
    ),
    ToolGroup(
        "janelas",
        "Janelas e apps",
        "abrir e fechar apps, sites, abas, pastas, mover janelas entre telas, layouts, bloquear o PC",
        (
            "open_app", "close_app", "open_website", "save_shortcut", "browser_tab", "open_folder",
            "manage_window", "manage_screens", "manage_layouts", "arrange_windows", "lock_computer",
        ),
    ),  # fmt: skip
    ToolGroup(
        "midia",
        "Mídia",
        "YouTube, Netflix e streaming, tocar, pausar, pular, volume",
        ("play_youtube", "open_streaming", "media_control", "set_volume"),
    ),
    ToolGroup(
        "mouse",
        "Mouse e teclado",
        "clicar, digitar, rolar, atalhos de teclado, modo ditado",
        ("click_on_screen", "move_mouse", "type_text", "press_keys", "scroll", "do_on_screen", "start_dictation", "write_here"),
    ),
    ToolGroup("gestos", "Gestos", "ligar e desligar os gestos das mãos, atalhos de gesto", ("gesture_control", "gesture_shortcuts")),
    ToolGroup(
        "camera",
        "Câmera e presença",
        "olhar pela webcam, mostrar a câmera, presença (chegar e sair da frente do PC)",
        ("look_at_camera", "camera_view", "presence_control"),
    ),
    ToolGroup(
        "rotinas",
        "Rotinas",
        "listar, criar, apagar ou agendar rotinas e os gatilhos por contexto (rodar uma rotina não precisa do grupo)",
        ("list_routines", "save_routine", "delete_routine", "schedule_routine", "set_routine_trigger"),
    ),
    ToolGroup(
        "avisos",
        "Lembretes e avisos",
        'aviso numa hora marcada ("me lembra às 15h de..."), listar e cancelar lembretes, avisos proativos (bateria, downloads...)',
        ("set_reminder", "list_reminders", "cancel_reminder", "configure_alerts"),
    ),
    ToolGroup(
        "diario",
        "Diário",
        "o que foi conversado em outros dias, apagar algo do diário",
        ("diary_lookup", "forget_diary"),
    ),
    ToolGroup("apps", "Instalar apps", "procurar e instalar aplicativos", ("search_apps", "prepare_app_install")),
    ToolGroup(
        "dia",
        "Dia a dia",
        "briefing do dia (\"como está o meu dia?\"), sessão de foco/Pomodoro com blocos e pausas, cotações de moedas, conversão de moedas e de unidades (comprimento, peso, temperatura...), velocidade da internet. As tarefas e notas ficam sempre com você",
        ("daily_briefing", "focus_session", "get_quotes", "convert_value", "network_speed"),
    ),
    ToolGroup(
        "olho",
        "Olho de Deus",
        "consultas em fontes públicas: localizar IP (inclusive o meu), investigar domínio, link suspeito ou golpe, CNPJ, CEP, DDD, email em vazamentos, usuário em sites, minha rede (portas e aparelhos). Nunca CPF, telefone ou dados de pessoas",
        ("osint_lookup",),
    ),
)


def tool_name(tool: Any) -> str | None:
    """Name the model sees for a function tool (None for toolsets)."""
    if isinstance(tool, llm.Toolset):
        return None
    resolved = tool if isinstance(tool, llm.Tool) else llm.tool_context._resolve_wrapped_tool(tool)
    return getattr(resolved, "id", None) or getattr(getattr(tool, "info", None), "name", None)


def _mcp_config(tool: Any) -> Any | None:
    return getattr(tool, "config", None) if isinstance(tool, llm.Toolset) else None


def declaration_count(tools: list[Any]) -> int:
    """How many tools the model would see; an MCP server counts its allowed tools."""
    total = 0
    for tool in tools:
        config = _mcp_config(tool)
        if config is not None:
            total += len(getattr(config, "allowed", ()))
        elif isinstance(tool, llm.Toolset):
            total += len(tool.tools)
        else:
            total += 1
    return total


def should_route(mode: str, tools: list[Any]) -> bool:
    if mode == "true":
        return True
    if mode == "false":
        return False
    return declaration_count(tools) > AUTO_MIN_TOOLS


def _key(text: str) -> str:
    return strip_accents(text).strip().lower().replace(" ", "_")


def _without_titles(schema: Any) -> Any:
    """The JSON schema without pydantic's "title" keys (noise for the model, ~15% of the text)."""
    if isinstance(schema, dict):
        return {key: _without_titles(value) for key, value in schema.items() if key != "title"}
    if isinstance(schema, list):
        return [_without_titles(item) for item in schema]
    return schema


def describe_tool(tool: Any) -> dict[str, Any]:
    """Name, description and parameters of a tool, as use_tools hands them to the model."""
    if isinstance(tool, llm.RawFunctionTool):
        raw = tool.info.raw_schema
        name, description, parameters = raw.get("name"), raw.get("description"), raw.get("parameters")
    else:
        schema = build_legacy_openai_schema(tool, internally_tagged=True)
        name, description, parameters = schema["name"], schema.get("description"), schema.get("parameters")
    description = " ".join((description or "").split())
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
    entry: dict[str, Any] = {"name": name, "description": description}
    parameters = _without_titles(parameters or {})
    if parameters.get("properties"):
        entry["parameters"] = parameters
    return entry


def _compact(entry: dict[str, Any]) -> str:
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


class ToolRouter:
    """Splits the tools in core + groups; use_tools and run_tool reach the grouped ones."""

    def __init__(self, tools: list[Any]) -> None:
        by_tool = {name: group for group in GROUPS for name in group.tools}
        self.core: list[Any] = []
        self.groups: dict[str, ToolGroup] = {}
        self.members: dict[str, list[Any]] = {}
        for tool in tools:
            config = _mcp_config(tool)
            if config is not None:
                group = ToolGroup(config.name, config.label, f"integração {config.label} (ferramentas {config.name}_...)", ())
            else:
                group = by_tool.get(tool_name(tool) or "")
            if group is None:
                self.core.append(tool)
                continue
            self.groups.setdefault(group.name, group)
            self.members.setdefault(group.name, []).append(tool)
        # Grupos que o modelo já pediu nesta conversa (só para o log e o HUD).
        self.used: list[str] = []
        self._connecting: dict[str, asyncio.Task[Any]] = {}
        self.use_tools, self.run_tool = self._build_tools()

    def session_tools(self) -> list[Any]:
        return [*self.core, self.use_tools, self.run_tool]

    def resolve(self, requested: list[str]) -> tuple[list[str], list[str]]:
        """Group names as the model wrote them ("Agenda", "câmera", "janela") -> known names."""
        aliases = {_key(name): name for name in self.groups}
        aliases.update({_key(group.label): name for name, group in self.groups.items()})
        found: list[str] = []
        unknown: list[str] = []
        for raw in requested:
            key = _key(raw)
            match = aliases.get(key) or next(iter(difflib.get_close_matches(key, list(aliases), n=1, cutoff=0.75)), None)
            if match is None:
                unknown.append(raw)
            else:
                name = aliases[match]
                if name not in found:
                    found.append(name)
        return found, unknown

    def labels(self, names: list[str]) -> str:
        return ", ".join(self.groups[name].label for name in names)

    def summary(self) -> str | None:
        """One line per group for the prompt; None when nothing is grouped."""
        if not self.groups:
            return None
        return "\n".join(f"- {name}: {group.description}." for name, group in self.groups.items())

    # ── integrações MCP ──

    def _toolsets(self) -> list[llm.Toolset]:
        return [tool for members in self.members.values() for tool in members if isinstance(tool, llm.Toolset)]

    async def connect(self, toolset: llm.Toolset) -> None:
        """Connect an MCP server once; concurrent callers share the same attempt."""
        task = self._connecting.get(toolset.id)
        if task is None:
            task = asyncio.ensure_future(toolset.setup())
            self._connecting[toolset.id] = task
        await asyncio.shield(task)

    def warm_up(self) -> None:
        """Start connecting every MCP server in the background (call it with the session's loop)."""
        for toolset in self._toolsets():
            task = asyncio.ensure_future(self.connect(toolset))
            task.add_done_callback(_log_failure)

    async def tools_of(self, group: str) -> list[Any]:
        """The function tools of a group; an MCP server connects first if it has not yet."""
        tools: list[Any] = []
        for member in self.members.get(group, []):
            if isinstance(member, llm.Toolset):
                await self.connect(member)
                tools.extend(member.tools)
            else:
                tools.append(member)
        return tools

    async def find(self, name: str) -> tuple[str, Any] | None:
        """(group, tool) for a grouped tool name; None when no group has it."""
        wanted = name.strip()
        for group, members in self.members.items():
            for member in members:
                config = _mcp_config(member)
                if config is not None:
                    if not wanted.startswith(f"{config.name}_"):
                        continue
                    for tool in await self.tools_of(group):
                        if tool_name(tool) == wanted:
                            return group, tool
                elif tool_name(member) == wanted:
                    return group, member
        return None

    async def aclose(self) -> None:
        """Close the MCP toolsets this router connected."""
        for toolset in self._toolsets():
            if toolset.id not in self._connecting:
                continue
            try:
                await toolset.aclose()
            except Exception:
                logger.debug("Falha ao fechar %s.", toolset.id, exc_info=True)

    # ── as duas ferramentas do modelo ──

    async def _catalog(self, names: list[str]) -> str:
        blocks: list[str] = []
        for name in names:
            group = self.groups[name]
            tools = await self.tools_of(name)
            if not tools:
                blocks.append(f"{group.label}: nenhuma ferramenta disponível agora.{_offline_reason(self.members[name])}")
                continue
            lines = "\n".join(_compact(describe_tool(tool)) for tool in tools)
            blocks.append(f"Ferramentas de {group.label} (use com run_tool):\n{lines}")
        return "\n\n".join(blocks)

    def _build_tools(self) -> tuple[Any, Any]:
        router = self

        @function_tool()
        async def use_tools(context: RunContext, groups: list[str]) -> str:
            """Get the tools of the groups the user's request needs (the groups are listed in the instructions).

            Call it first, before saying anything, whenever the request is about a group:
            "o que eu tenho hoje?" = ["agenda"], "abre o Spotify" = ["janelas"], "liga os gestos" =
            ["gestos"], "me mostra a câmera" = ["camera"]. It returns each tool's name, description and
            parameters; then, in this same reply, call run_tool with one of them. Never tell the user
            you cannot do something of a group without calling use_tools and run_tool first.

            Args:
                groups: One or more group names, e.g. ["agenda"] or ["janelas", "midia"].
            """
            names, unknown = router.resolve(groups)
            if not names:
                return (
                    f"Não existe grupo {', '.join(unknown) or 'nenhum'}. Grupos que existem: "
                    f"{', '.join(router.groups)}. Chame use_tools de novo com um deles."
                )
            labels = router.labels(names)
            await tool_status("use_tools", "running", labels)
            catalog = await router._catalog(names)
            for name in names:
                if name not in router.used:
                    router.used.append(name)
            logger.info("Ferramentas sob demanda: %s entregue(s) ao modelo.", labels)
            await tool_status("use_tools", "done", labels)
            missing = f"\n\nNão existe grupo {', '.join(unknown)}." if unknown else ""
            return f"{catalog}{missing}\n\n{READY_NOTE}"

        @function_tool()
        async def run_tool(context: RunContext, name: str, arguments: str = "{}") -> Any:
            """Run one tool of a group, by the name use_tools listed, with its parameters as a JSON object.

            The tools of the groups (get_agenda, open_app, gesture_control, look_at_camera, draft_email,
            notion_..., and the others use_tools lists) only run through here. Speak after its result,
            and say what the result really says.

            Args:
                name: Tool name exactly as use_tools listed it, e.g. "get_agenda".
                arguments: JSON object with that tool's parameters, e.g. '{"day": "amanhã"}'; "{}" when it takes none.
            """
            found = await router.find(name)
            if found is None:
                known = ", ".join(router.groups)
                raise ToolError(
                    f"Não existe a ferramenta {name!r} nos grupos. Chame use_tools com o grupo do pedido "
                    f"({known}) para ver os nomes certos."
                )
            group, tool = found
            try:
                args, kwargs = prepare_function_arguments(fnc=tool, json_arguments=arguments or "{}", call_ctx=context)
            except ToolError as exc:
                raise ToolError(f"{exc}. Parâmetros de {name}: {_compact(describe_tool(tool))}") from exc
            if group not in router.used:
                router.used.append(group)
            logger.info("Ferramentas sob demanda: %s (%s).", name, router.groups[group].label)
            result = tool(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

        return use_tools, run_tool


def _offline_reason(members: list[Any]) -> str:
    """Why an MCP server has no tools (mcp_client.STATES), for the model to repeat."""
    try:
        from mcp_client import STATES
    except Exception:
        return ""
    reasons = []
    for member in members:
        config = _mcp_config(member)
        state = STATES.get(config.name) if config is not None else None
        if state is not None and getattr(state, "error", None):
            reasons.append(f" A integração {config.label} está fora do ar: {state.error}.")
    return "".join(reasons) or " Diga isso ao usuário, sem inventar resultado."


def _log_failure(task: asyncio.Future[Any]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("Integração MCP não conectou em segundo plano: %s", error)


def route_tools(tools: list[Any], mode: str) -> tuple[list[Any], ToolRouter | None]:
    """Session tools for this conversation, and the router when the tools go by group."""
    if not should_route(mode, tools):
        return tools, None
    router = ToolRouter(tools)
    if not router.groups:
        return tools, None
    return router.session_tools(), router
