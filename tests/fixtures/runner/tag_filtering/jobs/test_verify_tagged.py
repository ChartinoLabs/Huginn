"""Fixture job selected by tag filtering."""

from huginn import Context, ResultStatus, TestCase


class VerifyTagged(TestCase):
    """Emit tag-specific check."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Record that the tagged case executed."""
        context.results.add_result(ResultStatus.PASSED, "ran:ospf")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
