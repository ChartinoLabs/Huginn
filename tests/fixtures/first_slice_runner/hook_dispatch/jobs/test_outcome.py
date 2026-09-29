"""Fixture job whose outcome depends on its test ID."""

import asyncio
from pathlib import Path

from huginn import Context, ResultStatus, TestCase

_PREFIX_STATUSES = {
    "failed": ResultStatus.FAILED,
    "lost": ResultStatus.LOST_APPLICABILITY,
}


class Outcome(TestCase):
    """Write a marker per step, then pass, fail or raise.

    A test ID starting with ``errored`` raises, one starting with ``failed``
    fails and one starting with ``lost`` loses applicability. One starting
    with ``slow`` waits 0.3 seconds, then passes. Others pass.
    """

    async def setup(self, context: Context) -> None:
        """Write a setup marker."""
        _mark(context, "setup")

    async def test(self, context: Context) -> None:
        """Write a test marker and record the outcome for this test ID."""
        _mark(context, "test")
        if context.test_id.startswith("slow"):
            await asyncio.sleep(0.3)
        if context.test_id.startswith("errored"):
            raise RuntimeError("boom")
        prefix = context.test_id.split("-")[0]
        status = _PREFIX_STATUSES.get(prefix, ResultStatus.PASSED)
        context.results.add_result(status, f"outcome {status.value}")

    async def cleanup(self, context: Context) -> None:
        """Write a cleanup marker."""
        _mark(context, "cleanup")


def _mark(context: Context, step: str) -> None:
    """Record that ``step`` ran for this test case."""
    markers = Path("executed") / context.test_id
    markers.mkdir(parents=True, exist_ok=True)
    (markers / step).write_text("ran", encoding="utf-8")
