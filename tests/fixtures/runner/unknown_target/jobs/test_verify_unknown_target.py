"""Fixture job for unknown-target validation scenario."""

from huginn import Context, ResultStatus, TestCase


class VerifyUnknownTarget(TestCase):
    """Would pass if it executed, but target resolution should fail first."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """No-op test."""
        context.results.add_result(ResultStatus.PASSED, "should not run")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
