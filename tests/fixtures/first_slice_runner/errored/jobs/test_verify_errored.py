"""Fixture job module for errored first-slice scenario."""

from pathlib import Path

from huginn import Context, TestCase


class VerifySomething(TestCase):
    """Fixture test case that raises at execution time."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Raise an error to validate runner error handling."""
        raise RuntimeError("boom")

    async def cleanup(self, context: Context) -> None:
        """Write a marker so tests can assert cleanup happened."""
        Path("cleanup.marker").write_text("done", encoding="utf-8")
