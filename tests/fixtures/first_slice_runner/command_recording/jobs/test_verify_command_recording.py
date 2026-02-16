"""Fixture job for command execution recording validation."""

from huginn import Context, ResultStatus, TestCase


class VerifyCommandRecording(TestCase):
    """Execute one command and record it via result collector API."""

    async def setup(self, context: Context) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: Context) -> None:
        """Record both check outcome and command execution details."""
        device = context.targets[0]
        output = await context.broker.execute(device, "show version")
        context.results.add_command_execution(
            device=device.name,
            command="show version",
            output=output,
            parsed={"vendor": "cisco"},
        )
        context.results.add_result(ResultStatus.PASSED, "command recorded")

    async def cleanup(self, context: Context) -> None:
        """No-op cleanup for fixture."""
        return None
