"""Fixture job that should be skipped for hierarchical no-match."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class VerifyNoMatch(TestCase):
    """Writes marker if executed unexpectedly."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Write marker to flag unexpected execution."""
        Path("hierarchy.unexpected").write_text("ran", encoding="utf-8")
        context.results.add_result(ResultStatus.PASSED, "should not run")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
