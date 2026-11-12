"""Nenhum teste grava no saude.db real nem manda eventos de saúde ao servidor do PC, e nenhum
depende da persona que o dono escolheu no HUD (persona.json)."""

from __future__ import annotations

import pytest

import health
import personas


@pytest.fixture(autouse=True)
def _isolated_health(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "DB_FILE", tmp_path / "saude.db")
    monkeypatch.setattr(health, "_post", lambda url, body: None)


@pytest.fixture(autouse=True)
def _isolated_persona(tmp_path, monkeypatch):
    # Com "stealth" salvo no persona.json de verdade, os testes de voz esperavam a voz errada.
    monkeypatch.setattr(personas, "PERSONA_FILE", tmp_path / "persona.json")
