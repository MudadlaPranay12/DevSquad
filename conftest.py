"""Pytest configuration for DEV-SQUAD.

The production bridge requires a pairing token. Tests use a deterministic local
token and an isolated SQLite database so they never touch developer data.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DEV_SQUAD_TOKEN", "test-token")
os.environ.setdefault("DEV_SQUAD_REQUIRE_TOKEN", "1")


@pytest.fixture(autouse=True)
def isolated_case_store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_SQUAD_DB", str(tmp_path / "devsquad-test.db"))
    monkeypatch.setenv("DEV_SQUAD_TOKEN", "test-token")
    monkeypatch.setenv("DEV_SQUAD_REQUIRE_TOKEN", "1")
    yield
