"""Fixture job validating hierarchical target intersection."""

from huginn import Context, ResultStatus, TestCase


class VerifyHierarchical(TestCase):
    """Emit selected target device names for assertions."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Record selected targets from merged hierarchy selectors."""
        for device in context.targets:
            context.results.add_result(ResultStatus.PASSED, f"selected:{device.name}")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
