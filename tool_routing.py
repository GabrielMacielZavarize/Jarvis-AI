"""Ferramentas sob demanda (protocolo FER-33): o Gemini Live só vê as ferramentas do assunto.

Com tudo ligado o Jarvis passa de 75 ferramentas (cerca de 14 mil tokens só de declarações) e,
com as integrações MCP, de 100. Com tantas o modelo escolhe pior. Aqui elas viram:

- um núcleo sempre presente: clima, pesquisa, hora, timers, HUD, memória, voz, encerrar, tudo
  o que não está em grupo nenhum (inclusive ferramentas novas) e TODAS as de confirmar e cancelar
  por código, para uma confirmação pendente nunca perder a sua ferramenta;
- grupos (agenda, email, tela, janelas, mídia, mouse, gestos, câmera, rotinas, avisos, apps e um
  por servidor MCP) que entram quando o modelo chama ``use_tools(["agenda"])``.

No Gemini Live, ``Agent.update_tools`` reabre a conexão (livekit-agents 1.8.8 marca a sessão para
reiniciar e reconecta com o handle de retomada). Reabrir no meio de uma resposta descarta o que
estava na fila e a resposta da ferramenta em andamento, então a troca espera a frase curta do
modelo terminar ("Um instante.") e só depois atualiza as ferramentas e pede a continuação do
pedido com ``generate_reply``. A transcrição final da fala do usuário só chega quando a resposta
do Gemini termina, tarde demais para escolher as ferramentas daquele pedido; por isso a escolha é
do modelo, pelo ``use_tools``, e não pela transcrição.

Os grupos ficam carregados até o fim da conversa; passando de ``MAX_LOADED_GROUPS``, o usado há
mais tempo sai na próxima troca (nenhuma reconexão extra).
"""

from __future__ import annotations

import asyncio
import difflib
import logging
from dataclasses import dataclass
from typing import Any

from livekit.agents import RunContext, function_tool, llm

from confirmation import strip_accents
from hud import tool_status

logger = logging.getLogger("jarvis-tool-routing")

PROTOCOL = "FER-33"
ROUTING_MODES = ("auto", "true", "false")
# "auto" liga a separação quando a sessão passa disso (MCP conta as ferramentas do "permitir").
AUTO_MIN_TOOLS = 60
MAX_LOADED_GROUPS = 4
CONTINUE_INSTRUCTION = (
    "As ferramentas de {labels} já estão com você. Continue agora o último pedido do usuário usando "
    'essas ferramentas, sem dizer "um instante" de novo e sem pedir que ele repita.'
)


@dataclass(frozen=True)
class ToolGroup:
    name: str
    label: str
    description: str
    tools: tuple[str, ...]


# Confirmar e cancelar (confirm_*, cancel_*) ficam fora de propósito: estão sempre no núcleo.
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
        "lembretes com dia e hora, listar lembretes, avisos proativos",
        ("set_reminder", "list_reminders", "cancel_reminder", "configure_alerts"),
    ),
    ToolGroup(
        "diario",
        "Diário",
        "o que foi conversado em outros dias, apagar algo do diário",
        ("diary_lookup", "forget_diary"),
    ),
    ToolGroup("apps", "Instalar apps", "procurar e instalar aplicativos", ("search_apps", "prepare_app_install")),
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


class ToolRouter:
    """Splits the tools in core + groups and swaps the loaded groups during the conversation."""

    def __init__(self, tools: list[Any], *, max_loaded: int = MAX_LOADED_GROUPS) -> None:
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
        self.max_loaded = max_loaded
        self.loaded: list[str] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self.use_tools = self._build_use_tools()

    def session_tools(self) -> list[Any]:
        return [*self.core, self.use_tools]

    def agent_tools(self) -> list[Any]:
        return [tool for name in self.loaded for tool in self.members[name]]

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

    def select(self, names: list[str]) -> list[str]:
        """Mark ``names`` as the most recent groups; returns the ones that were not loaded."""
        added = [name for name in names if name not in self.loaded]
        self.loaded = [name for name in self.loaded if name not in names] + list(names)
        while len(self.loaded) > max(self.max_loaded, len(names)):
            dropped = self.loaded.pop(0)
            logger.info("Ferramentas sob demanda: o grupo %s saiu para dar lugar aos novos.", dropped)
        return added

    def labels(self, names: list[str]) -> str:
        return ", ".join(self.groups[name].label for name in names)

    def summary(self) -> str | None:
        """One line per group for the prompt; None when nothing is grouped."""
        if not self.groups:
            return None
        return "\n".join(f"- {name}: {group.description}." for name, group in self.groups.items())

    async def apply(self, session: Any, names: list[str]) -> None:
        """Hand the loaded groups to the current agent and ask it to go on with the request."""
        tools = self.agent_tools()
        for tool in tools:
            if isinstance(tool, llm.Toolset):
                await tool.setup()  # MCP: conecta só quando o grupo entra pela primeira vez
        agent = session.current_agent
        await agent.update_tools(tools)
        logger.info("Ferramentas sob demanda: %s carregado(s).", self.labels(names))
        await tool_status("use_tools", "done", self.labels(names))
        session.generate_reply(instructions=CONTINUE_INSTRUCTION.format(labels=self.labels(names)))

    async def aclose(self) -> None:
        """Close MCP toolsets that this router connected (loaded once, maybe dropped since)."""
        for members in self.members.values():
            for tool in members:
                if isinstance(tool, llm.Toolset):
                    try:
                        await tool.aclose()
                    except Exception:
                        logger.debug("Falha ao fechar %s.", tool.id, exc_info=True)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _apply_after_reply(self, session: Any, names: list[str], wait_for_reply: bool) -> None:
        from tools import _wait_for_farewell

        if wait_for_reply:
            await _wait_for_farewell(session)
        try:
            await self.apply(session, names)
        except Exception:
            logger.exception("Não consegui carregar as ferramentas de %s.", self.labels(names))
            await tool_status("use_tools", "error", self.labels(names))

    def _build_use_tools(self) -> Any:
        router = self

        @function_tool()
        async def use_tools(context: RunContext, groups: list[str]) -> str:
            """Load the tool groups the user's request needs (the groups are listed in the instructions).

            Call it before anything else when the request is about a group whose tools you do not
            have: "o que eu tenho hoje?" = ["agenda"], "abre o Spotify" = ["janelas"], "clica no
            play" = ["mouse"]. Then say only "Um instante." and wait: the tools arrive in a moment
            and you are asked to go on with the request.

            Args:
                groups: One or more group names, e.g. ["agenda"] or ["janelas", "midia"].
            """
            names, unknown = router.resolve(groups)
            if not names:
                return (
                    f"Não existe grupo {', '.join(unknown) or 'nenhum'}. Grupos que existem: "
                    f"{', '.join(router.groups)}. Chame use_tools de novo com um deles."
                )
            added = router.select(names)
            if not added:
                return f"As ferramentas de {router.labels(names)} já estão com você. Use-as agora para o pedido."
            await tool_status("use_tools", "running", router.labels(added))
            from tools import _tool_reply_is_new_speech

            session = context.session
            handle = getattr(context, "speech_handle", None)
            if handle is None:
                router._spawn(router._apply_after_reply(session, added, wait_for_reply=True))
            else:
                wait = _tool_reply_is_new_speech(session)
                handle.add_done_callback(lambda _: router._spawn(router._apply_after_reply(session, added, wait)))
            missing = f" Não existe grupo {', '.join(unknown)}." if unknown else ""
            return (
                f"Carregando as ferramentas de {router.labels(added)}.{missing} Diga só \"Um instante.\" e "
                "mais nada; em seguida as ferramentas chegam e você continua o pedido."
            )

        return use_tools


def route_tools(tools: list[Any], mode: str) -> tuple[list[Any], ToolRouter | None]:
    """Session tools for this conversation, and the router when the tools go by group."""
    if not should_route(mode, tools):
        return tools, None
    router = ToolRouter(tools)
    if not router.groups:
        return tools, None
    return router.session_tools(), router
