"""Fixture learning job that learns a constant state."""

from huginn import Context, LearningTestCase, ResultStatus


class Learn(LearningTestCase):
    """Learn a constant state, and pass when comparing it."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Return a constant state."""
        return {"state": "ok"}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Pass regardless of the learned state."""
        context.results.add_result(ResultStatus.PASSED, "compared")
