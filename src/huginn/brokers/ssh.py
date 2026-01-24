"""SSH connection broker using Scrapli.

This module provides an SSH broker implementation that uses Scrapli
for device connectivity. It supports execute and configure operations.
"""

import time
import uuid
from typing import Any

from scrapli.driver.generic import AsyncGenericDriver
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)

from huginn.brokers.exceptions import (
    AuthenticationError,
    CapabilityError,
    CommandError,
    ConfigurationError,
    ConnectionError,
    InvalidHandleError,
    NotConnectedError,
    TimeoutError,
)
from huginn.brokers.protocol import (
    CommandResult,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
)

PROTOCOL_VERSION = "1"


class SSHBroker:
    """SSH connection broker using Scrapli.

    This broker manages SSH connections to network devices using
    Scrapli's AsyncGenericDriver. It supports command execution
    and configuration operations.

    Attributes:
        PROTOCOL_VERSION: The protocol version this broker implements.
    """

    PROTOCOL_VERSION = PROTOCOL_VERSION

    def __init__(self, broker_id: str | None = None) -> None:
        """Initialize the SSH broker.

        Args:
            broker_id: Optional unique identifier for this broker instance.
                      If not provided, a UUID will be generated.
        """
        self._broker_id = broker_id or str(uuid.uuid4())
        self._connections: dict[str, AsyncGenericDriver] = {}
        self._configs: dict[str, ConnectionConfig] = {}

    @property
    def name(self) -> str:
        """Return the broker name."""
        return "ssh"

    @property
    def connection_type(self) -> str:
        """Return the connection type this broker handles."""
        return "ssh"

    def capabilities(self) -> set[str]:
        """Return the set of capabilities this broker supports.

        Returns:
            Set containing 'execute' and 'configure'.
        """
        return {"execute", "configure"}

    def cache_key(self, operation: str, **kwargs: Any) -> str | None:  # noqa: ANN401
        """Generate a cache key for the given operation.

        Execute operations are cacheable by command. Configure operations
        are not cacheable since they modify device state.

        Args:
            operation: The operation type.
            **kwargs: Operation-specific arguments.

        Returns:
            The command string for execute operations, None for configure.
        """
        if operation == "execute":
            return kwargs.get("command")
        return None

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        """Establish an SSH connection to a device.

        Args:
            config: Connection configuration including host, port, credentials.

        Returns:
            A handle representing the connection.

        Raises:
            ConnectionError: If connection cannot be established.
            AuthenticationError: If authentication fails.
        """
        driver_kwargs: dict[str, Any] = {
            "host": config.host,
            "port": config.port,
            "transport": "asyncssh",
        }

        if "username" in config.credentials:
            driver_kwargs["auth_username"] = config.credentials["username"]
        if "password" in config.credentials:
            driver_kwargs["auth_password"] = config.credentials["password"]
        if "private_key" in config.credentials:
            driver_kwargs["auth_private_key"] = config.credentials["private_key"]

        driver_kwargs.update(config.options)

        driver = AsyncGenericDriver(**driver_kwargs)

        try:
            await driver.open()
        except ScrapliAuthenticationFailed as e:
            raise AuthenticationError(
                f"Authentication failed for {config.host}: {e}"
            ) from e
        except ScrapliConnectionError as e:
            raise ConnectionError(f"Connection failed to {config.host}: {e}") from e
        except ScrapliTimeout as e:
            raise TimeoutError(f"Connection timed out to {config.host}: {e}") from e

        self._connections[config.device_name] = driver
        self._configs[config.device_name] = config

        return ConnectionHandle(
            broker_id=self._broker_id,
            device_name=config.device_name,
            connection_type=self.connection_type,
            state=ConnectionState.CONNECTED,
            metadata={"host": config.host, "port": config.port},
        )

    async def disconnect(self, handle: ConnectionHandle) -> None:
        """Disconnect from a device.

        Args:
            handle: The connection handle to disconnect.

        Raises:
            InvalidHandleError: If the handle is invalid.
        """
        if handle.device_name not in self._connections:
            raise InvalidHandleError(f"No connection found for {handle.device_name}")

        driver = self._connections.pop(handle.device_name)
        self._configs.pop(handle.device_name, None)
        await driver.close()

    async def is_alive(self, handle: ConnectionHandle) -> bool:
        """Check if a connection is still alive.

        Args:
            handle: The connection handle to check.

        Returns:
            True if the connection is alive, False otherwise.
        """
        if handle.device_name not in self._connections:
            return False

        driver = self._connections[handle.device_name]
        return driver.isalive()

    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle:
        """Reconnect an existing connection.

        Args:
            handle: The connection handle to reconnect.

        Returns:
            A new handle for the reconnected session.

        Raises:
            InvalidHandleError: If no config exists for this handle.
            ConnectionError: If reconnection fails.
        """
        if handle.device_name not in self._configs:
            raise InvalidHandleError(f"No configuration found for {handle.device_name}")

        if handle.device_name in self._connections:
            driver = self._connections.pop(handle.device_name)
            try:
                await driver.close()
            except Exception:
                pass  # nosec B110 - intentional: best-effort cleanup during reconnect

        config = self._configs[handle.device_name]
        return await self.connect(config)

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
            **kwargs: Additional execution options (timeout_ops, etc.).

        Returns:
            The command result with output and timing.

        Raises:
            NotConnectedError: If not connected.
            TimeoutError: If the command times out.
            CommandError: If command execution fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"Not connected to {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.send_command(command, **kwargs)
        except ScrapliTimeout as e:
            raise TimeoutError(f"Command timed out on {handle.device_name}: {e}") from e
        except Exception as e:
            raise CommandError(f"Command failed on {handle.device_name}: {e}") from e
        elapsed_ms = (time.monotonic() - start_time) * 1000

        return CommandResult(
            output=response.result,
            elapsed_ms=elapsed_ms,
            cached=False,
        )

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
            The configuration result with combined output.

        Raises:
            NotConnectedError: If not connected.
            ConfigurationError: If configuration fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"Not connected to {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.send_commands(commands, **kwargs)
        except ScrapliTimeout as e:
            raise TimeoutError(
                f"Configuration timed out on {handle.device_name}: {e}"
            ) from e
        except Exception as e:
            raise ConfigurationError(
                f"Configuration failed on {handle.device_name}: {e}"
            ) from e
        elapsed_ms = (time.monotonic() - start_time) * 1000

        combined_output = "\n".join(r.result for r in response)

        return CommandResult(
            output=combined_output,
            elapsed_ms=elapsed_ms,
            cached=False,
        )

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform a GET operation.

        SSH broker does not support GET operations.

        Args:
            handle: The connection handle.
            path: The path for the GET operation.
            **kwargs: Additional options.

        Raises:
            CapabilityError: Always, as SSH does not support GET.
        """
        raise CapabilityError("SSH broker does not support GET operations")

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform an edit-config operation.

        SSH broker does not support edit operations.

        Args:
            handle: The connection handle.
            config: The configuration payload.
            **kwargs: Additional options.

        Raises:
            CapabilityError: Always, as SSH does not support edit.
        """
        raise CapabilityError("SSH broker does not support edit operations")
