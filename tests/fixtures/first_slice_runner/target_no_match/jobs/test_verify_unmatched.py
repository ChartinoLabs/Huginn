"""Fixture job that should be skipped when targets do not match."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class VerifyUnmatched(TestCase):
    """Write marker if test executes unexpectedly."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Write marker to indicate unexpected execution."""
        Path("unexpected.execution").write_text("ran", encoding="utf-8")
        context.results.add_result(ResultStatus.PASSED, "should not run")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
