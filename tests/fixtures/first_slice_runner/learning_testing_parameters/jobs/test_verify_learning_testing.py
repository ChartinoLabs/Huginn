"""Fixture job module for learning/testing parameter persistence."""

from huginn import Context, ExecutionMode, ResultStatus, TestCase


class VerifyLearnedParameters(TestCase):
    """Save parameters in learning mode and compare in testing mode."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Exercise context.parameters save/load behavior by execution mode."""
        current = {
            "target_count": len(context.targets),
            "target_names": sorted(device.name for device in context.targets),
        }

        if context.mode == ExecutionMode.LEARNING:
            await context.parameters.save(current)
            context.results.add_result(ResultStatus.PASSED, "parameters learned")
            return

        expected = await context.parameters.load()
        if expected == current:
            context.results.add_result(ResultStatus.PASSED, "parameters matched")
            return

        context.results.add_result(
            ResultStatus.FAILED,
            f"parameters mismatched: expected={expected}, current={current}",
        )

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
