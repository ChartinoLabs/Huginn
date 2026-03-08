"""Fixture job module for learning-mode deduplication."""

import json
from pathlib import Path

from huginn import Context, LearningTestCase, ResultStatus


class VerifyLearningDeduplication(LearningTestCase):
    """Record learning invocations while saving deterministic state."""

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Persist a counter so tests can assert learning only ran once."""
        counter_path = Path("learning-invocations.json")
        if counter_path.exists():
            payload = json.loads(counter_path.read_text(encoding="utf-8"))
            count = int(payload.get("count", 0))
        else:
            count = 0

        counter_path.write_text(
            json.dumps({"count": count + 1}, indent=2),
            encoding="utf-8",
        )
        return {"target_names": sorted(device.name for device in context.targets)}

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
