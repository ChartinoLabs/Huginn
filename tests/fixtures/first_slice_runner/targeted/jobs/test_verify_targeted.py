"""Fixture job validating target selection behavior."""

from huginn import Context, ResultStatus, TestCase


class VerifyTargeting(TestCase):
    """Assert commands execute for the selected target devices only."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Execute one command per target and record results."""
        for device in context.targets:
            result = await context.broker.execute(device, "show version")
            context.results.add_result(ResultStatus.PASSED, result.output)

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
