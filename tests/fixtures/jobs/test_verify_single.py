"""Fixture module exposing one TestCase subclass."""

from huginn import TestCase


class VerifySomething(TestCase):
    """Single subclass fixture for loader tests."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
