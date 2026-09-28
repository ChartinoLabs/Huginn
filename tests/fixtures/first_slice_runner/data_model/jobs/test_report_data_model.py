"""Fixture job that reports the data model it receives."""

import json
from typing import cast

from huginn import Context, LearningTestCase, ResultStatus


class ReportDataModel(LearningTestCase):
    """Record `context.data_model` and whether it rejects mutation."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Report the data model, then try to mutate it."""
        context.results.add_result(
            ResultStatus.INFO,
            f"data_model={json.dumps(context.data_model, sort_keys=True)}",
        )
        if context.data_model is not None:
            fabric = cast(dict[str, object], context.data_model["fabric"])
            try:
                fabric["name"] = "mutated"
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
