"""Fixture job used across multiple test cases for reuse checks."""

from huginn import Context, ResultStatus, TestCase


class VerifyShared(TestCase):
    """Simple test case that records one passing check."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Record one passing check."""
        context.results.add_result(ResultStatus.PASSED, "shared pass")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
