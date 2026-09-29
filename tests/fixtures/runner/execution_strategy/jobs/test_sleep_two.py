"""Fixture job for execution strategy timing tests."""

import asyncio

from huginn import Context, ResultStatus, TestCase


class VerifySleepTwo(TestCase):
    """Sleep briefly and emit a marker."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Sleep long enough to measure serial vs parallel behavior."""
        await asyncio.sleep(0.3)
        context.results.add_result(ResultStatus.PASSED, "sleep-two")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
