"""Fixture job module for failing first-slice scenario."""

from huginn import ResultStatus, TestCase


class VerifySomething(TestCase):
    """Simple failing fixture test case."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """Record a failing result for fixture run."""
        context.results.add_result(ResultStatus.FAILED, "failed check")

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
