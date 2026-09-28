"""Fixture learning job that records that it ran."""

from pathlib import Path

from huginn import Context, LearningTestCase, ResultStatus


class LearnState(LearningTestCase):
    """Write an execution marker, then learn or compare a constant state.

    A test ID starting with ``errored`` raises instead.
    """

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Write a marker and return a constant state."""
        markers = Path("executed")
        markers.mkdir(exist_ok=True)
        (markers / context.test_id).write_text("ran", encoding="utf-8")
        if context.test_id.startswith("errored"):
            raise RuntimeError("boom")
        return {"state": "ok"}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Pass in testing mode regardless of the learned state."""
        context.results.add_result(ResultStatus.PASSED, "compared")
