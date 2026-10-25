"""Fixture module defining helper classes alongside its TestCase subclass."""

from typing import TypedDict

from huginn import TestCase


class InterfaceParameters(TypedDict):
    """Helper type that job discovery must skip."""

    state: str


class ParseFailureError(Exception):
    """Helper exception that job discovery must skip."""


class VerifyWithHelpers(TestCase):
    """TestCase subclass defined after the module's helper classes."""

    async def setup(self, context: object) -> None:
        """No-op setup for fixture."""
        return None

    async def test(self, context: object) -> None:
        """No-op test body for fixture."""
        return None

    async def cleanup(self, context: object) -> None:
        """No-op cleanup for fixture."""
        return None
