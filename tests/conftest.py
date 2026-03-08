"""Shared pytest configuration for test suite."""

import pytest


@pytest.fixture(autouse=True)
def stable_terminal_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI output wrapping deterministic across environments."""
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
