"""Protocol definitions for connection brokers.

This module defines the ConnectionBrokerProtocol_v1 interface that all
broker implementations must follow, along with supporting data types.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeAlias, runtime_checkable

CredentialFields: TypeAlias = dict[str, str]


class ConnectionState(Enum):
    """State of a connection managed by a broker."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectionHandle:
    """Handle representing a connection managed by a broker.

    Attributes:
        broker_id: Unique identifier for the broker instance.
        device_name: Name of the device this connection is for.
        connection_type: Type of connection (e.g., "ssh", "netconf").
        state: Current state of the connection.
        metadata: Optional additional metadata about the connection.
    """

    broker_id: str
    device_name: str
    connection_type: str
    state: ConnectionState
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result of executing a command on a device.

    Attributes:
        output: Raw text output from the command.
        structured: Parsed/structured data if available.
        elapsed_ms: Time taken to execute in milliseconds.
        cached: Whether this result came from cache.
    """

    output: str
    structured: dict[str, Any] | None = None
    elapsed_ms: float = 0.0
    cached: bool = False


@dataclass
class ConnectionConfig:
    """Configuration for establishing a connection.

    Attributes:
        device_name: Logical name for the device.
        host: Hostname or IP address.
        port: Port number for the connection.
        os: Operating system identifier from testbed (e.g., "nxos", "iosxe", "eos").
        credentials: Authentication credentials (username, password, key, etc.).
        options: Additional broker-specific options.
    """

    device_name: str
    host: str
    port: int
    os: str | None = None
    credentials: CredentialFields = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ConnectionBrokerProtocolV1(Protocol):
    """Protocol defining the interface for connection brokers.

    All broker implementations must conform to this protocol to ensure
    interoperability with the connection manager.
    """

    @property
    def name(self) -> str:
        """Return the broker name."""
        ...

    @property
    def connection_type(self) -> str:
        """Return the connection type this broker handles (e.g., 'ssh')."""
        ...

    def capabilities(self) -> set[str]:
        """Return the set of capabilities this broker supports.

        Common capabilities include:
        - 'execute': Can execute commands
        - 'configure': Can send configuration commands
        - 'get': Can perform GET operations (NETCONF/RESTCONF)
        - 'edit': Can perform edit-config operations
        - 'batch': Can batch multiple operations

        Returns:
            Set of capability strings.
        """
        ...

    def cache_key(
        self,
        operation: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> str | None:
        """Generate a cache key for the given operation.

        Args:
            operation: The operation type ('execute', 'configure', etc.).
            **kwargs: Operation-specific arguments.

        Returns:
            A cache key string if the operation is cacheable, None otherwise.
        """
        ...

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        """Establish a connection to a device.

        Args:
            config: Connection configuration.

        Returns:
            A handle representing the connection.

        Raises:
            ConnectionError: If connection cannot be established.
            AuthenticationError: If authentication fails.
        """
        ...

    async def disconnect(self, handle: ConnectionHandle) -> None:
        """Disconnect from a device.

        Args:
            handle: The connection handle to disconnect.

        Raises:
            InvalidHandleError: If the handle is invalid.
        """
        ...

    async def is_alive(self, handle: ConnectionHandle) -> bool:
        """Check if a connection is still alive.

        Args:
            handle: The connection handle to check.

        Returns:
            True if the connection is alive, False otherwise.
        """
        ...

    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle:
        """Reconnect an existing connection.

        Args:
            handle: The connection handle to reconnect.

        Returns:
            A new handle for the reconnected session.

        Raises:
            ConnectionError: If reconnection fails.
        """
        ...

    async def execute(
        self,
        handle: ConnectionHandle,
        command: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Execute a command on the device.

        Args:
            handle: The connection handle.
            command: The command to execute.
            **kwargs: Additional execution options.

        Returns:
            The command result.

        Raises:
            NotConnectedError: If not connected.
            TimeoutError: If the command times out.
            CommandError: If command execution fails.
        """
        ...

    async def configure(
        self,
        handle: ConnectionHandle,
        commands: list[str],
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Send configuration commands to the device.

        Args:
            handle: The connection handle.
            commands: List of configuration commands.
            **kwargs: Additional configuration options.

        Returns:
            The configuration result.

        Raises:
            NotConnectedError: If not connected.
            ConfigurationError: If configuration fails.
        """
        ...

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform a GET operation (for NETCONF/RESTCONF brokers).

        Args:
            handle: The connection handle.
            path: The path or filter for the GET operation.
            **kwargs: Additional options.

        Returns:
            The GET result.

        Raises:
            CapabilityError: If GET is not supported.
        """
        ...

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform an edit-config operation (for NETCONF/RESTCONF brokers).

        Args:
            handle: The connection handle.
            config: The configuration payload.
            **kwargs: Additional options.

        Returns:
            The edit result.

        Raises:
            CapabilityError: If edit is not supported.
        """
        ...
