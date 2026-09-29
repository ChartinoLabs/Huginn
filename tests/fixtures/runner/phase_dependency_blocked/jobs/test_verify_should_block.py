"""Fixture job that should never execute when dependency blocks."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class VerifyShouldBlock(TestCase):
    """Write marker if executed unexpectedly."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Record execution marker to detect unexpected execution."""
        Path("phase2.executed").write_text("unexpected", encoding="utf-8")
        context.results.add_result(ResultStatus.PASSED, "should not run")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
