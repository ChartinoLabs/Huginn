"""Fixture job for failing dependency phase."""

from huginn import Context, ResultStatus, TestCase


class VerifyFailing(TestCase):
    """Emit a failed check so downstream phase is blocked."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Emit a failed check for dependency behavior validation."""
        context.results.add_result(ResultStatus.FAILED, "phase one failed")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
