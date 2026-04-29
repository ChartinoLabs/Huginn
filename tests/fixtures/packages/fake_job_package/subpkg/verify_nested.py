"""Fixture module exposing multiple TestCase subclasses from a subpackage."""

from huginn import TestCase


class FirstNestedCase(TestCase):
    """First subclass for explicit-class loader tests."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None


class SecondNestedCase(TestCase):
    """Second subclass for explicit-class loader tests."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
