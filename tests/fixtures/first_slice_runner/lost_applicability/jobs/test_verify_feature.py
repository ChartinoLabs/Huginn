"""Fixture learning job whose command support is chosen by a file."""

from pathlib import Path

from huginn import CommandSupportResult, Context, LearningTestCase, ResultStatus


class VerifyFeature(LearningTestCase):
    """Learn and compare per-device state under the standard ``devices`` key.

    Devices named, one per line, in ``unsupported.txt`` in the working
    directory do not support the job's command.
    """

    async def check_command_support(self, context: Context) -> CommandSupportResult:
        """Mark the devices listed in unsupported.txt as not applicable."""
        path = Path("unsupported.txt")
        unsupported = (
            set(path.read_text(encoding="utf-8").split()) if path.exists() else set()
        )
        return CommandSupportResult(
            applicable=[d for d in context.targets if d.name not in unsupported],
            not_applicable={
                d.name: "Device does not support 'show feature'"
                for d in context.targets
                if d.name in unsupported
            },
        )

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Return one entry per supported device."""
        return {"devices": {d.name: {"enabled": True} for d in context.targets}}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Pass for every device still present."""
        devices = current.get("devices")
        if isinstance(devices, dict):
            for name in devices:
                context.results.add_result(ResultStatus.PASSED, f"{name}: matched")
