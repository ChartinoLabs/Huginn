"""Fixture job excluded when filtering by different tags."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class VerifyOther(TestCase):
    """Writes marker if unexpectedly executed."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Write marker to detect unexpected execution."""
        Path("unexpected.tag.execution").write_text("ran", encoding="utf-8")
        context.results.add_result(ResultStatus.PASSED, "ran:bgp")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
