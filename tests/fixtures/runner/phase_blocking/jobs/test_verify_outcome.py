"""Fixture job whose outcome is chosen by the test ID prefix."""

from pathlib import Path

from huginn import Context, ResultStatus, TestCase


class VerifyOutcome(TestCase):
    """Record an execution marker, then end with the status the test ID names.

    A test ID such as ``failed-1`` ends FAILED, and ``errored-1`` raises.
    """

    async def setup(self, context: Context) -> None:
        """No-op setup."""
        return None

    async def test(self, context: Context) -> None:
        """Write a marker and emit the status named by the test ID prefix."""
        markers = Path("executed")
        markers.mkdir(exist_ok=True)
        (markers / context.test_id).write_text("ran", encoding="utf-8")
        status = context.test_id.split("-", 1)[0]
        if status == "errored":
            raise RuntimeError("boom")
        context.results.add_result(ResultStatus(status), status)

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup."""
        return None
