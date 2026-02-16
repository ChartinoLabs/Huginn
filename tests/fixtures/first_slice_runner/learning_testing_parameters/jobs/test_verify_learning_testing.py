"""Fixture job module for learning/testing parameter persistence."""

from huginn import Context, LearningTestCase, ResultStatus


class VerifyLearnedParameters(LearningTestCase):
    """Save parameters in learning mode and compare in testing mode."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Collect deterministic state used for learning/testing assertions."""
        return {
            "target_count": len(context.targets),
            "target_names": sorted(device.name for device in context.targets),
        }

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Compare learned and current state in testing mode."""
        if expected == current:
            context.results.add_result(ResultStatus.PASSED, "parameters matched")
            return

        context.results.add_result(
            ResultStatus.FAILED,
            f"parameters mismatched: expected={expected}, current={current}",
        )
