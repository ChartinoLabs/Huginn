"""Fixture module with documentation metadata attributes."""

from huginn import LearningTestCase


class VerifyWithMetadata(LearningTestCase):
    """Test case with all metadata attributes populated."""

    DESCRIPTION = "Verify BGP neighbor adjacency"
    SETUP = "Ensure BGP is configured on both peers"
    PROCEDURE = "Check neighbor state via show commands"
    PASS_FAIL_CRITERIA = "Neighbor must be in Established state"

    async def gather_state(self, context: object) -> dict[str, object]:
        return {}

    async def compare_state(
        self,
        context: object,
        learned: dict[str, object],
        current: dict[str, object],
    ) -> None:
        return None
