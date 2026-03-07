"""Fixture job module for failing first-slice scenario."""

from huginn import Context, ResultStatus, TestCase


class VerifySomething(TestCase):
    """Simple failing fixture test case."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Record a failing result for fixture run."""
        context.results.add_result(ResultStatus.FAILED, "failed check")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
