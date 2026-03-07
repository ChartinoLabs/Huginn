"""Fixture job for post-change OSPF test."""

from huginn import Context, ResultStatus, TestCase


class VerifyPostOspf(TestCase):
    """Emit marker result for post-change ospf case."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Record marker indicating this test case executed."""
        context.results.add_result(ResultStatus.PASSED, "ran:2.0.0")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
