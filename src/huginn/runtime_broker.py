"""Runtime broker abstraction for protocol-aware target operations."""

from dataclasses import dataclass

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


@dataclass(frozen=True)
class RuntimeBrokerClient:
    """A protocol-pinned broker view for test job access."""

    _runtime_broker: "RuntimeBroker"
    _broker_key: str

    async def execute(self, target: Device, command: str) -> CommandResult:
        """Execute a command using the pinned broker type."""
        return await self._runtime_broker.execute(
            target,
            command,
            broker=self._broker_key,
        )

    async def get(self, target: Device, path: str, **kwargs: object) -> CommandResult:
        """Run a GET-style operation using the pinned broker type."""
        return await self._runtime_broker.get(
            target,
            path,
            broker=self._broker_key,
            **kwargs,
        )

    async def edit(
        self,
        target: Device,
        config: str,
        **kwargs: object,
    ) -> CommandResult:
        """Run an edit-style operation using the pinned broker type."""
        return await self._runtime_broker.edit(
            target,
            config,
            broker=self._broker_key,
            **kwargs,
        )


class RuntimeBroker:
    """Broker facade used by test jobs at runtime."""

    def __init__(
        self,
        *,
        required_brokers: set[str] | None = None,
        ssh_broker: ConnectionBrokerProtocolV1 | None = None,
        http_broker: ConnectionBrokerProtocolV1 | None = None,
        netconf_broker: ConnectionBrokerProtocolV1 | None = None,
    ) -> None:
        """Initialize runtime broker facade with required broker instances."""
        required = required_brokers or {"ssh"}
        self._brokers = _build_brokers(
            required_brokers=required,
            ssh_broker=ssh_broker,
            http_broker=http_broker,
            netconf_broker=netconf_broker,
        )
        self._handles: dict[tuple[str, str], ConnectionHandle] = {}

    async def connect_targets(
        self,
        targets: list[Device],
        required_brokers: set[str],
    ) -> None:
        """Open required broker connections for all target devices."""
        required_keys = _normalize_required_brokers(required_brokers)
        try:
            for device in targets:
                for broker_key in required_keys:
                    connection = _select_connection(
                        device=device,
                        broker_key=broker_key,
                    )
                    credential = _resolve_credential(device, connection.credential)
                    config = ConnectionConfig(
                        device_name=device.name,
                        host=connection.host,
                        port=connection.port,
                        os=device.os,
                        credentials=credential,
                        options=connection.options,
                    )
                    handle = await self._brokers[broker_key].connect(config)
                    self._handles[(device.name, broker_key)] = handle
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def disconnect_targets(self) -> None:
        """Close any established target connections."""
        handles = list(self._handles.items())
        self._handles.clear()
        try:
            for (_, broker_key), handle in handles:
                await self._brokers[broker_key].disconnect(handle)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def execute(
        self,
        target: Device,
        command: str,
        *,
        broker: str | None = None,
    ) -> CommandResult:
        """Execute a command for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        try:
            return await self._brokers[broker_key].execute(handle, command)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def get(
        self,
        target: Device,
        path: str,
        *,
        broker: str | None = None,
        **kwargs: object,
    ) -> CommandResult:
        """Run a GET-style operation for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        try:
            return await self._brokers[broker_key].get(handle, path, **kwargs)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def edit(
        self,
        target: Device,
        config: str,
        *,
        broker: str | None = None,
        **kwargs: object,
    ) -> CommandResult:
        """Run an edit-style operation for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        try:
            return await self._brokers[broker_key].edit(handle, config, **kwargs)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    def for_protocol(self, protocol: str) -> RuntimeBrokerClient:
        """Return a protocol-pinned broker client for job use."""
        broker_key = normalize_broker_key(protocol)
        if broker_key not in self._brokers:
            raise RuntimeBrokerError(
                f"Broker '{broker_key}' was not planned for this run"
            )
        return RuntimeBrokerClient(_runtime_broker=self, _broker_key=broker_key)

    def _resolve_broker_key(self, *, target: Device, broker: str | None) -> str:
        """Resolve broker key for an operation call."""
        available = [
            broker_key
            for (device_name, broker_key) in self._handles
            if device_name == target.name
        ]
        if not available:
            raise RuntimeBrokerError(f"Device '{target.name}' is not connected")

        if broker is not None:
            requested = normalize_broker_key(broker)
            if requested not in available:
                raise RuntimeBrokerError(
                    f"Device '{target.name}' is not connected via '{requested}'"
                )
            return requested

        if len(available) == 1:
            return available[0]

        raise RuntimeBrokerError(
            f"Device '{target.name}' has multiple connected brokers "
            f"{sorted(available)}; "
            "specify broker explicitly"
        )

    def _require_handle(self, *, target: Device, broker_key: str) -> ConnectionHandle:
        """Get a connected handle for a target+broker pair."""
        handle = self._handles.get((target.name, broker_key))
        if handle is None:
            raise RuntimeBrokerError(
                f"Device '{target.name}' is not connected via '{broker_key}'"
            )
        return handle


def _build_brokers(
    *,
    required_brokers: set[str],
    ssh_broker: ConnectionBrokerProtocolV1 | None,
    http_broker: ConnectionBrokerProtocolV1 | None,
    netconf_broker: ConnectionBrokerProtocolV1 | None,
) -> dict[str, ConnectionBrokerProtocolV1]:
    """Instantiate only required broker implementations for the run."""
    normalized = _normalize_required_brokers(required_brokers)
    available: dict[str, ConnectionBrokerProtocolV1] = {}
    if "ssh" in normalized:
        available["ssh"] = ssh_broker or SSHBroker()
    if "http" in normalized:
        available["http"] = http_broker or HTTPBroker()
    if "netconf" in normalized:
        available["netconf"] = netconf_broker or NETCONFBroker()
    return available


def _normalize_required_brokers(required_brokers: set[str]) -> set[str]:
    """Normalize and validate required broker identifiers."""
    if not required_brokers:
        raise RuntimeBrokerError("At least one broker must be required")
    return {normalize_broker_key(broker) for broker in required_brokers}


def _select_connection(*, device: Device, broker_key: str) -> ConnectionDefinition:
    """Select connection definition matching the requested broker key."""
    protocol_preferences = _preferred_protocols_for_broker(broker_key)
    for protocol in protocol_preferences:
        for connection in device.connections.values():
            if connection.protocol == protocol:
                return connection
    raise RuntimeBrokerError(
        f"Device '{device.name}' has no connection for broker '{broker_key}'"
    )


def _preferred_protocols_for_broker(broker_key: str) -> tuple[str, ...]:
    """Return preferred connection protocol order for a broker key."""
    if broker_key == "ssh":
        return ("ssh",)
    if broker_key == "http":
        return ("https", "http", "rest")
    if broker_key == "netconf":
        return ("netconf",)
    raise RuntimeBrokerError(f"Unsupported broker key '{broker_key}'")


def normalize_broker_key(protocol: str) -> str:
    """Normalize protocol/broker aliases into canonical broker keys."""
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
