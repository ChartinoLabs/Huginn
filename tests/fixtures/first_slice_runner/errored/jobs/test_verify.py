"""Fixture job module for errored first-slice scenario."""

from pathlib import Path

from huginn import TestCase


class VerifySomething(TestCase):
    """Fixture test case that raises at execution time."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """Raise an error to validate runner error handling."""
        raise RuntimeError("boom")

    async def cleanup(self, context: object) -> None:
        """Write a marker so tests can assert cleanup happened."""
        Path("cleanup.marker").write_text("done", encoding="utf-8")
