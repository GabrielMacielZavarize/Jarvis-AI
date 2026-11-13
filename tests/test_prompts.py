"""Regras do prompt por ferramenta ligada (prompts.build_feature_rules) e o núcleo das tarefas."""

from __future__ import annotations

import asyncio
import re
import unittest
from unittest.mock import patch

from prompts import AGENT_INSTRUCTION, build_agent_instructions, build_feature_rules
from settings import load_settings
from tool_routing import GROUPS, ToolRouter
from tools import build_tools

BASE = {"GOOGLE_API_KEY": "test-key", "JARVIS_MEMORY_EMBEDDINGS": "false"}
EVERYTHING = {
    **BASE,
    "JARVIS_PROACTIVE": "true",
    "JARVIS_ENABLE_CALENDAR": "true",
    "JARVIS_OSINT_NETWORK": "true",
}

DAY_TOOLS = (
    "add_task", "add_note", "list_tasks", "complete_task", "remove_task", "daily_briefing", "focus_session",
    "get_quotes", "convert_value", "network_speed",
)  # fmt: skip

# Uma frase que só existe na regra de cada ferramenta do dia a dia.
DAY_MARKERS = {
    "add_note": 'Nota solta ("anota aí',
    "add_task": "Algo a fazer",
    "list_tasks": '= list_tasks (show "tarefas"',
    "complete_task": "= complete_task",
    "remove_task": "= remove_task",
    "daily_briefing": "= daily_briefing",
    "focus_session": "= focus_session",
    "get_quotes": "= get_quotes",
    "convert_value": "conta local: não precisa de internet",
    "network_speed": "= network_speed",
}


def rules(env: dict[str, str]) -> str:
    return build_feature_rules(load_settings(env)) or ""


def tool_names(env: dict[str, str]) -> set[str]:
    return {getattr(tool, "id", None) or tool.info.name for tool in build_tools(load_settings(env))}


class DayRulesTests(unittest.TestCase):
    def test_every_day_rule_is_there_when_day_is_on(self) -> None:
        text = rules(EVERYTHING)
        for tool, marker in DAY_MARKERS.items():
            self.assertIn(marker, text, tool)
            self.assertIn(tool, text, tool)

    def test_nothing_of_the_day_when_it_is_off(self) -> None:
        text = rules({**EVERYTHING, "JARVIS_ENABLE_DAY": "false"})
        for tool in DAY_TOOLS:
            self.assertNotIn(tool, text, tool)
        self.assertNotIn("# Dia a dia", text)
        self.assertIn("# Olho de Deus", text)

    def test_note_task_fact_and_reminder_are_told_apart(self) -> None:
        text = rules(EVERYTHING)
        self.assertIn('("anota aí: ideia do painel"', text)
        self.assertIn("= add_note", text)
        self.assertIn('"tenho que fechar o relatório até sexta"', text)
        self.assertIn("= add_task", text)
        self.assertIn("nunca uma hora", text)
        self.assertIn("= remember, não nota", text)
        self.assertIn('"me lembra às 15h de ligar pro contador"', text)
        self.assertIn("= set_reminder", text)
        self.assertIn("= set_timer", text)

    def test_the_fact_rule_needs_memory_and_the_reminder_rule_needs_proactive(self) -> None:
        no_memory = rules({**EVERYTHING, "JARVIS_ENABLE_MEMORY": "false"})
        self.assertNotIn("remember", no_memory)
        self.assertIn("add_note", no_memory)
        no_reminders = rules({**EVERYTHING, "JARVIS_PROACTIVE": "false"})
        self.assertNotIn("set_reminder", no_reminders)
        self.assertIn("set_timer", no_reminders)
        self.assertIn("remember", no_reminders)

    def test_focus_session_is_not_the_routine_nor_the_timer(self) -> None:
        with_routines = rules(EVERYTHING)
        self.assertIn('nem a rotina "modo foco"', with_routines)
        self.assertIn('"modo foco" dito sozinho é a rotina (run_routine)', with_routines)
        self.assertIn("Não é um set_timer", with_routines)
        without = rules({**EVERYTHING, "JARVIS_ENABLE_ROUTINES": "false"})
        self.assertNotIn("run_routine", without)
        self.assertIn('"modo foco" dito sozinho também é focus_session', without)

    def test_briefing_x_good_morning_routine_x_agenda(self) -> None:
        text = rules(EVERYTHING)
        self.assertIn('rotina "bom dia" (run_routine), não o briefing', text)
        self.assertIn("continua sendo get_agenda", text)
        self.assertNotIn("get_agenda", rules({**EVERYTHING, "JARVIS_ENABLE_CALENDAR": "false"}))
        self.assertNotIn('rotina "bom dia"', rules({**EVERYTHING, "JARVIS_ENABLE_ROUTINES": "false"}))

    def test_unit_conversion_needs_no_network(self) -> None:
        text = rules(EVERYTHING)
        self.assertIn("conta local: não precisa de internet", text)
        self.assertIn("nunca calcula de cabeça", text)

    def test_cinema_no_longer_swallows_modo_foco(self) -> None:
        self.assertIn('"Modo cinema", "esconde os painéis" = set_hud_appearance(cinema=true)', AGENT_INSTRUCTION)
        self.assertNotIn('"Modo cinema", "modo foco"', AGENT_INSTRUCTION)


class EyeRulesTests(unittest.TestCase):
    def test_eye_rules_are_there_when_osint_is_on(self) -> None:
        text = rules(EVERYTHING)
        self.assertIn("# Olho de Deus", text)
        self.assertIn("osint_lookup(kind, target)", text)
        self.assertIn("Só fontes públicas", text)
        for refused in ("CPF", "telefone", "email de outra pessoa"):
            self.assertIn(refused, text)

    def test_the_password_check_is_only_in_the_hud(self) -> None:
        text = rules(EVERYTHING)
        self.assertIn("Nunca peça nem aceite senha por voz", text)
        self.assertIn('painel "Senha vazada?"', text)
        self.assertIn("área Olho de Deus do HUD", text)

    def test_nothing_of_the_eye_when_it_is_off(self) -> None:
        text = rules({**EVERYTHING, "JARVIS_ENABLE_OSINT": "false"})
        self.assertNotIn("osint_lookup", text)
        self.assertNotIn("Olho de Deus", text)
        self.assertNotIn("Senha vazada", text)
        self.assertIn("# Dia a dia", text)

    def test_my_network_follows_its_switch(self) -> None:
        self.assertIn('osint_lookup("rede")', rules(EVERYTHING))
        off = rules({**EVERYTHING, "JARVIS_OSINT_NETWORK": "false"})
        self.assertNotIn('osint_lookup("rede")', off)
        self.assertIn("JARVIS_OSINT_NETWORK", off)


class WiringTests(unittest.TestCase):
    def test_no_features_no_extra_rules(self) -> None:
        env = {**BASE, "JARVIS_ENABLE_DAY": "false", "JARVIS_ENABLE_OSINT": "false"}
        self.assertIsNone(build_feature_rules(load_settings(env)))
        self.assertEqual(build_agent_instructions(), AGENT_INSTRUCTION)

    def test_rules_come_after_the_common_rules_and_before_the_context(self) -> None:
        text = build_agent_instructions(home_city="Criciúma", feature_rules=rules(EVERYTHING))
        self.assertTrue(text.index("# Dia a dia") > text.index("# Exemplos"))
        self.assertTrue(text.index("# Olho de Deus") < text.index("# Contexto do usuário"))

    def test_the_agent_gets_the_rules_of_its_session(self) -> None:
        from backends import build_runtime

        def instructions(env: dict[str, str]) -> str:
            async def build():
                with patch("backends._monitor_layout", return_value=None):
                    return build_runtime(load_settings(env), load_vad=False)

            return asyncio.run(build()).agent.instructions

        self.assertIn("osint_lookup(kind, target)", instructions(BASE))
        off = instructions({**BASE, "JARVIS_ENABLE_OSINT": "false", "JARVIS_ENABLE_DAY": "false"})
        self.assertNotIn("osint_lookup", off)
        self.assertNotIn("add_note", off)

    def test_every_tool_named_in_the_rules_exists_in_that_session(self) -> None:
        known = tool_names({**EVERYTHING, "JARVIS_ENABLE_PC_CONTROL": "true"})
        variants = [
            EVERYTHING,
            BASE,
            {**EVERYTHING, "JARVIS_ENABLE_MEMORY": "false", "JARVIS_PROACTIVE": "false"},
            {**EVERYTHING, "JARVIS_ENABLE_ROUTINES": "false", "JARVIS_ENABLE_CALENDAR": "false"},
            {**EVERYTHING, "JARVIS_ENABLE_DAY": "false"},
            {**EVERYTHING, "JARVIS_ENABLE_OSINT": "false"},
        ]
        for env in variants:
            available = tool_names(env)
            for word in set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", rules(env))):
                if word in known:
                    self.assertIn(word, available, f"{word} está no prompt mas não na sessão {env}")


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ToolRouter(build_tools(load_settings(EVERYTHING)))

    def test_tasks_and_notes_stay_in_the_core_next_to_remember(self) -> None:
        core = {getattr(tool, "id", None) or tool.info.name for tool in self.router.core}
        for name in ("add_task", "add_note", "list_tasks", "complete_task", "remove_task", "remember"):
            self.assertIn(name, core)
        grouped = {name for group in GROUPS for name in group.tools}
        self.assertFalse(grouped & {"add_task", "add_note", "list_tasks", "complete_task", "remove_task"})

    def test_the_rest_of_the_day_still_loads_on_demand(self) -> None:
        self.assertEqual(
            {getattr(t, "id", None) or t.info.name for t in self.router.members["dia"]},
            {"daily_briefing", "focus_session", "get_quotes", "convert_value", "network_speed"},
        )

    def test_group_lines_tell_the_model_what_each_group_is_for(self) -> None:
        summary = self.router.summary() or ""
        dia = next(line for line in summary.splitlines() if line.startswith("- dia:"))
        for word in ("briefing", "foco", "cotações", "conversão", "velocidade da internet"):
            self.assertIn(word, dia)
        olho = next(line for line in summary.splitlines() if line.startswith("- olho:"))
        for word in ("IP", "golpe", "CNPJ", "vazamentos", "Nunca CPF"):
            self.assertIn(word, olho)
        avisos = next(line for line in summary.splitlines() if line.startswith("- avisos:"))
        self.assertIn("me lembra às 15h", avisos)


if __name__ == "__main__":
    unittest.main()
