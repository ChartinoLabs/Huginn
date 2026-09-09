"""Fixture module with documentation metadata attributes."""

from huginn import Context, LearningTestCase


class VerifyWithMetadata(LearningTestCase):
    """Test case with all metadata attributes populated."""

    DESCRIPTION = "Verify BGP neighbor adjacency"
    SETUP = "Ensure BGP is configured on both peers"
    PROCEDURE = "Check neighbor state via show commands"
    PASS_FAIL_CRITERIA = "Neighbor must be in Established state"

    async def gather_state(self, context: Context) -> dict[str, object]:
        """Return empty state for fixture."""
        return {}

    async def compare_state(
        self,
        *,
        expected: dict[str, object],
        current: dict[str, object],
        context: Context,
    ) -> None:
        """No-op comparison for fixture."""
