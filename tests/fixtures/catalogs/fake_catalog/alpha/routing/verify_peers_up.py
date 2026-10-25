"""Fixture job for catalog import tests."""

from huginn import TestCase


class VerifyPeersUp(TestCase):
    """Fixture job that does nothing."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
