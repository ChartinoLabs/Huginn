"""Fixture action job that does not inherit LearningTestCase."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class ApplyChange(TestCase):
    """Write an execution marker and pass, like a change or action job."""

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Write a marker and pass."""
        markers = Path("executed")
        markers.mkdir(exist_ok=True)
        (markers / context.test_id).write_text("ran", encoding="utf-8")
        context.results.add_result(ResultStatus.PASSED, "change applied")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
