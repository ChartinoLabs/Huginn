"""Shared pytest configuration for test suite."""

import logging
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def stable_terminal_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep CLI output wrapping deterministic across environments."""
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")


@pytest.fixture(autouse=True)
def reset_huginn_logger() -> Iterator[None]:
    """Close the ``huginn`` logger's handlers after each test.

    ``Output`` attaches a file handler that opens its file on the first
    record. Left attached, a later test that logs would write to the log
    path of an earlier test, which may be ``./huginn.log`` in the checkout.
    """
    yield
    logger = logging.getLogger("huginn")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
