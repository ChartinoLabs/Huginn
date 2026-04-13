"""Fixture job validating group and os target selectors."""

from huginn import Context, ResultStatus, TestCase


class VerifyTargets(TestCase):
    """Record selected device names for assertion."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Emit one check for each selected target device."""
        for device in context.targets:
            context.results.add_result(ResultStatus.PASSED, f"selected:{device.name}")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
