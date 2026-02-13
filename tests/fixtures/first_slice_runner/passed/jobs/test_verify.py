"""Fixture job module for passing first-slice scenario."""

from huginn import ResultStatus, TestCase


class VerifySomething(TestCase):
    """Simple passing fixture test case."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """Record a passing result for fixture run."""
        context.results.add_result(ResultStatus.PASSED, "all good")

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
