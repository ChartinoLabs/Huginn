"""Runtime broker abstraction for first connected execution path."""

from huginn.brokers import ConnectionConfig, ConnectionHandle, SSHBroker
from huginn.brokers.protocol import CommandResult
from huginn.models import ConnectionDefinition, Device


class RuntimeBrokerError(RuntimeError):
    """Raised when runtime broker operations cannot be completed."""


class RuntimeBroker:
    """Broker facade used by test jobs at runtime."""

    def __init__(self, ssh_broker: SSHBroker | None = None) -> None:
        """Initialize runtime broker facade and backing SSH broker."""
        self._ssh_broker = ssh_broker or SSHBroker()
        self._handles: dict[str, ConnectionHandle] = {}

    async def connect_targets(self, targets: list[Device]) -> None:
        """Open broker connections for all target devices."""
        try:
            for device in targets:
                connection = _select_ssh_connection(device)
                credential = _resolve_credential(device, connection.credential)
                config = ConnectionConfig(
                    device_name=device.name,
                    host=connection.host,
                    port=connection.port,
                    os=device.os,
                    credentials=credential,
                    options=connection.options,
                )
                self._handles[device.name] = await self._ssh_broker.connect(config)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def disconnect_targets(self) -> None:
        """Close any established target connections."""
        handles = list(self._handles.values())
        self._handles.clear()
        try:
            for handle in handles:
                await self._ssh_broker.disconnect(handle)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def execute(self, target: Device, command: str) -> CommandResult:
        """Execute a command on a target via SSH."""
        handle = self._handles.get(target.name)
        if handle is None:
            raise RuntimeBrokerError(f"Device '{target.name}' is not connected")
        try:
            return await self._ssh_broker.execute(handle, command)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error


def _select_ssh_connection(device: Device) -> ConnectionDefinition:
    """Select the SSH connection definition for a device."""
    for connection in device.connections.values():
        if connection.protocol == "ssh":
            return connection
    raise RuntimeBrokerError(f"Device '{device.name}' has no SSH connection")


def _resolve_credential(
    device: Device,
    credential_name: str | None,
) -> dict[str, str]:
    """Resolve connection credential by name with default fallback."""
    resolved_name = credential_name or "default"
    if resolved_name not in device.credentials:
        raise RuntimeBrokerError(
            f"Device '{device.name}' is missing credential '{resolved_name}'"
        )
    return device.credentials[resolved_name]
