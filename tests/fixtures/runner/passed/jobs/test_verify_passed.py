"""Fixture job module for passing first-slice scenario."""

from huginn import Context, ResultStatus, TestCase


class VerifySomething(TestCase):
    """Simple passing fixture test case."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Record a passing result for fixture run."""
        context.results.add_result(
            ResultStatus.PASSED,
            "all good "
            f"[scenario={context.scenario}|phase={context.phase}"
            f"|group={context.test_case_group}|test_id={context.test_id}]",
        )

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
