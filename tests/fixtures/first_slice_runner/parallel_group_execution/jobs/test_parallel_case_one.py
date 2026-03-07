"""Fixture job for parallel execution verification."""

import asyncio

from huginn import Context, ResultStatus, TestCase


class VerifyParallelCaseOne(TestCase):
    """Sleep briefly and report completion marker."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Sleep to make sequential execution measurable in timing checks."""
        await asyncio.sleep(0.3)
        context.results.add_result(ResultStatus.PASSED, "parallel:one")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
