"""Nenhum teste grava no saude.db real nem manda eventos de saúde ao servidor do PC."""

from __future__ import annotations

import pytest

import health


@pytest.fixture(autouse=True)
def _isolated_health(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "DB_FILE", tmp_path / "saude.db")
    monkeypatch.setattr(health, "_post", lambda url, body: None)
