"""Minimal broker used for first-slice runner integration."""

from typing import Any

from huginn.brokers.protocol import CommandResult


class NullBroker:
    """No-op broker placeholder until full connection orchestration lands."""

    def is_connected(self, _: str) -> bool:
        """Return connected state for all devices in first slice."""
        return True

    async def execute(self, _: Any, command: str) -> CommandResult:  # noqa: ANN401
        """Return a deterministic placeholder command result."""
        return CommandResult(output=f"not-executed: {command}")
