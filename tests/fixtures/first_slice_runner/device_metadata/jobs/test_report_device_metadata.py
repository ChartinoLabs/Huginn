"""Fixture job that reports the metadata of each target device."""

import json
from typing import cast

from huginn import Context, LearningTestCase, ResultStatus


class ReportDeviceMetadata(LearningTestCase):
    """Record `device.metadata` and whether it rejects mutation."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Report each target's metadata, then try to mutate it."""
        for device in context.targets:
            context.results.add_result(
                ResultStatus.INFO,
                f"{device.name}={json.dumps(device.metadata, sort_keys=True)}",
            )
            uplinks = cast(list[str], device.metadata["uplinks"])
            try:
                uplinks.append("mutated")
            except TypeError:
                context.results.add_result(ResultStatus.INFO, "read-only")
        return {}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """Pass whenever testing mode runs."""
        context.results.add_result(ResultStatus.PASSED, "compared")
