"""Fixture module exposing multiple TestCase subclasses."""

from huginn import TestCase


class FirstCase(TestCase):
    """First fixture class for selection tests."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None


class SecondCase(TestCase):
    """Second fixture class for explicit class selection tests."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
