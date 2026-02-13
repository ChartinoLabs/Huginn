"""Runtime broker abstraction for protocol-aware target operations."""

from huginn.brokers import (
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
    HTTPBroker,
    NETCONFBroker,
    SSHBroker,
)
from huginn.brokers.protocol import CommandResult
from huginn.models import ConnectionDefinition, Device


class RuntimeBrokerError(RuntimeError):
    """Raised when runtime broker operations cannot be completed."""


class RuntimeBroker:
    """Broker facade used by test jobs at runtime."""

    def __init__(
        self,
        ssh_broker: ConnectionBrokerProtocolV1 | None = None,
        http_broker: ConnectionBrokerProtocolV1 | None = None,
        netconf_broker: ConnectionBrokerProtocolV1 | None = None,
    ) -> None:
        """Initialize runtime broker facade and backing broker instances."""
        self._brokers: dict[str, ConnectionBrokerProtocolV1] = {
            "ssh": ssh_broker or SSHBroker(),
            "http": http_broker or HTTPBroker(),
            "netconf": netconf_broker or NETCONFBroker(),
        }
        self._handles: dict[str, ConnectionHandle] = {}
        self._connection_types: dict[str, str] = {}

    async def connect_targets(self, targets: list[Device]) -> None:
        """Open broker connections for all target devices."""
        try:
            for device in targets:
                connection = _select_connection(device)
                broker_key = _protocol_to_broker_key(connection.protocol)
                broker = self._brokers[broker_key]
                credential = _resolve_credential(device, connection.credential)
                config = ConnectionConfig(
                    device_name=device.name,
                    host=connection.host,
                    port=connection.port,
                    os=device.os,
                    credentials=credential,
                    options=connection.options,
                )
                self._handles[device.name] = await broker.connect(config)
                self._connection_types[device.name] = broker_key
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def disconnect_targets(self) -> None:
        """Close any established target connections."""
        handles = list(self._handles.items())
        self._handles.clear()
        connection_types = self._connection_types
        self._connection_types = {}
        try:
            for device_name, handle in handles:
                broker_key = connection_types[device_name]
                await self._brokers[broker_key].disconnect(handle)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def execute(self, target: Device, command: str) -> CommandResult:
        """Execute a command on a target via SSH."""
        handle = self._handles.get(target.name)
        if handle is None:
            raise RuntimeBrokerError(f"Device '{target.name}' is not connected")
        try:
            broker = self._broker_for_target(target)
            return await broker.execute(handle, command)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def get(self, target: Device, path: str, **kwargs: object) -> CommandResult:
        """Run a GET-style operation on the selected target broker."""
        handle = self._require_handle(target)
        try:
            broker = self._broker_for_target(target)
            return await broker.get(handle, path, **kwargs)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def edit(
        self,
        target: Device,
        config: str,
        **kwargs: object,
    ) -> CommandResult:
        """Run an edit-style operation on the selected target broker."""
        handle = self._require_handle(target)
        try:
            broker = self._broker_for_target(target)
            return await broker.edit(handle, config, **kwargs)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    def _require_handle(self, target: Device) -> ConnectionHandle:
        """Get a connected handle for a target or raise runtime error."""
        handle = self._handles.get(target.name)
        if handle is None:
            raise RuntimeBrokerError(f"Device '{target.name}' is not connected")
        return handle

    def _broker_for_target(self, target: Device) -> ConnectionBrokerProtocolV1:
        """Resolve broker instance for an already-connected target device."""
        broker_key = self._connection_types.get(target.name)
        if broker_key is None:
            raise RuntimeBrokerError(f"Device '{target.name}' has no broker mapping")
        return self._brokers[broker_key]


def _select_connection(device: Device) -> ConnectionDefinition:
    """Select preferred connection definition for a device."""
    preferred_protocols = ("ssh", "https", "http", "rest", "netconf")
    for protocol in preferred_protocols:
        for connection in device.connections.values():
            if connection.protocol == protocol:
                return connection
    raise RuntimeBrokerError(f"Device '{device.name}' has no supported connection")


def _protocol_to_broker_key(protocol: str) -> str:
    """Map connection protocol identifiers to runtime broker keys."""
    if protocol == "ssh":
        return "ssh"
    if protocol in {"http", "https", "rest"}:
        return "http"
    if protocol == "netconf":
        return "netconf"
    raise RuntimeBrokerError(f"Unsupported connection protocol '{protocol}'")


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
