"""Nenhum teste grava no saude.db real nem manda eventos de saúde ao servidor do PC, nenhum
depende da persona que o dono escolheu no HUD (persona.json) e nenhum lê ou escreve as tarefas e
o histórico de rede nem a sessão de foco (foco.json) de verdade."""

from __future__ import annotations

import pytest

import focus
import health
import netcheck
import personas
import quotes
import tasks


@pytest.fixture(autouse=True)
def _isolated_health(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "DB_FILE", tmp_path / "saude.db")
    monkeypatch.setattr(health, "_post", lambda url, body: None)


@pytest.fixture(autouse=True)
def _isolated_persona(tmp_path, monkeypatch):
    # Com "stealth" salvo no persona.json de verdade, os testes de voz esperavam a voz errada.
    monkeypatch.setattr(personas, "PERSONA_FILE", tmp_path / "persona.json")


@pytest.fixture(autouse=True)
def _isolated_day(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, "TASKS_FILE", tmp_path / "tarefas.json")
    monkeypatch.setattr(netcheck, "HISTORY_FILE", tmp_path / "rede.json")
    monkeypatch.setattr(focus, "FOCUS_FILE", tmp_path / "foco.json")
    monkeypatch.setattr(netcheck, "_last_run", 0.0)
    # As cotações ficam um minuto em memória: um teste não pode herdar a do anterior.
    quotes._cache.clear()
