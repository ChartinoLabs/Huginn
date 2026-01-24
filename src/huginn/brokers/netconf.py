"""NETCONF connection broker using scrapli_netconf.

This module provides a NETCONF broker implementation that uses scrapli_netconf
for NETCONF protocol connectivity. It supports get and edit-config operations.
"""

import time
import uuid
from typing import Any

from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)
from scrapli_netconf import AsyncNetconfDriver

from huginn.brokers.exceptions import (
    AuthenticationError,
    CapabilityError,
    ConfigurationError,
    ConnectionError,
    InvalidHandleError,
    NotConnectedError,
    OperationError,
    TimeoutError,
)
from huginn.brokers.protocol import (
    CommandResult,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
)

PROTOCOL_VERSION = 1

# Mapping from testbed OS identifiers to scrapli_netconf platform strings.
# NETCONF implementations vary by vendor, requiring platform-specific handling.
OS_TO_NETCONF_PLATFORM: dict[str, str] = {
    "iosxe": "cisco_iosxe",
    "nxos": "cisco_nxos",
    "iosxr": "cisco_iosxr",
    "junos": "juniper_junos",
}


class NETCONFBroker:
    """NETCONF connection broker using scrapli_netconf.

    This broker manages NETCONF connections to network devices using
    scrapli_netconf's AsyncNetconfDriver. It supports get and edit-config
    operations following the NETCONF protocol (RFC 6241).

    The broker maps testbed OS identifiers to scrapli_netconf platform strings:
    - iosxe → cisco_iosxe
    - nxos → cisco_nxos
    - iosxr → cisco_iosxr
    - junos → juniper_junos

    Attributes:
        PROTOCOL_VERSION: The protocol version this broker implements.
    """

    PROTOCOL_VERSION: int = PROTOCOL_VERSION

    def __init__(self, broker_id: str | None = None) -> None:
        """Initialize the NETCONF broker.

        Args:
            broker_id: Optional unique identifier for this broker instance.
                      If not provided, a UUID will be generated.
        """
        self._broker_id = broker_id or str(uuid.uuid4())
        self._connections: dict[str, AsyncNetconfDriver] = {}
        self._configs: dict[str, ConnectionConfig] = {}

    @property
    def name(self) -> str:
        """Return the broker name."""
        return "netconf"

    @property
    def connection_type(self) -> str:
        """Return the connection type this broker handles."""
        return "netconf"

    def capabilities(self) -> set[str]:
        """Return the set of capabilities this broker supports.

        Returns:
            Set containing 'get' and 'edit' for NETCONF operations.
        """
        return {"get", "edit"}

    def cache_key(self, operation: str, **kwargs: Any) -> str | None:  # noqa: ANN401
        """Generate a cache key for the given operation.

        GET operations are cacheable by filter/path. Edit operations
        are not cacheable since they modify device configuration.

        Args:
            operation: The operation type.
            **kwargs: Operation-specific arguments.

        Returns:
            The filter or path for get operations, None for edit.
        """
        if operation == "get":
            # Use filter or path as cache key
            return kwargs.get("filter") or kwargs.get("path")
        return None

    def _get_netconf_platform(self, os: str | None) -> str:
        """Map testbed OS identifier to scrapli_netconf platform string.

        Args:
            os: The testbed OS identifier (e.g., "nxos", "iosxe").

        Returns:
            The scrapli_netconf platform string (e.g., "cisco_nxos").

        Raises:
            ConnectionError: If the OS is not provided or not supported.
        """
        if os is None:
            raise ConnectionError("OS must be specified in connection config")

        platform = OS_TO_NETCONF_PLATFORM.get(os)
        if platform is None:
            supported = ", ".join(sorted(OS_TO_NETCONF_PLATFORM.keys()))
            raise ConnectionError(f"Unsupported OS '{os}'. Supported: {supported}")
        return platform

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        """Establish a NETCONF connection to a device.

        Args:
            config: Connection configuration including host, port, credentials, os.

        Returns:
            A handle representing the connection.

        Raises:
            ConnectionError: If connection cannot be established or OS unsupported.
            AuthenticationError: If authentication fails.
        """
        platform = self._get_netconf_platform(config.os)

        # Default NETCONF port is 830
        port = config.port if config.port != 22 else 830

        driver_kwargs: dict[str, Any] = {
            "host": config.host,
            "port": port,
            "platform": platform,
            "transport": "asyncssh",
        }

        if "username" in config.credentials:
            driver_kwargs["auth_username"] = config.credentials["username"]
        if "password" in config.credentials:
            driver_kwargs["auth_password"] = config.credentials["password"]
        if "private_key" in config.credentials:
            driver_kwargs["auth_private_key"] = config.credentials["private_key"]

        # Allow additional scrapli options
        driver_kwargs.update(config.options)

        driver = AsyncNetconfDriver(**driver_kwargs)

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

        # Extract server capabilities if available
        server_capabilities = []
        if hasattr(driver, "server_capabilities") and driver.server_capabilities:
            server_capabilities = list(driver.server_capabilities)

        return ConnectionHandle(
            broker_id=self._broker_id,
            device_name=config.device_name,
            connection_type=self.connection_type,
            state=ConnectionState.CONNECTED,
            metadata={
                "host": config.host,
                "port": port,
                "server_capabilities": server_capabilities,
            },
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
        """Execute a raw RPC command.

        This method sends a raw NETCONF RPC and returns the response.
        For standard operations, prefer get() or edit().

        Args:
            handle: The connection handle.
            command: The RPC XML to execute.
            **kwargs: Additional options.

        Returns:
            The RPC result with XML response.

        Raises:
            NotConnectedError: If not connected.
            TimeoutError: If the RPC times out.
            OperationError: If RPC execution fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"Not connected to {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.rpc(filter_=command)
        except ScrapliTimeout as e:
            raise TimeoutError(f"RPC timed out on {handle.device_name}: {e}") from e
        except Exception as e:
            raise OperationError(f"RPC failed on {handle.device_name}: {e}") from e
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
        """Send configuration commands.

        NETCONF broker does not support CLI-style configure operations.
        Use edit() for NETCONF edit-config operations.

        Args:
            handle: The connection handle.
            commands: List of configuration commands.
            **kwargs: Additional options.

        Raises:
            CapabilityError: Always, as NETCONF uses edit-config instead.
        """
        raise CapabilityError(
            "NETCONF broker does not support configure. Use edit() instead."
        )

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform a NETCONF get or get-config operation.

        Args:
            handle: The connection handle.
            path: XPath filter or subtree filter for the get operation.
            **kwargs: Additional options:
                - source: Config datastore ("running", "candidate", "startup").
                         If not specified, uses get (operational + config data).
                - filter_type: "xpath" or "subtree" (default: "subtree").

        Returns:
            CommandResult with XML response.

        Raises:
            NotConnectedError: If not connected.
            TimeoutError: If the operation times out.
            OperationError: If the operation fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]
        source = kwargs.get("source")
        filter_type = kwargs.get("filter_type", "subtree")

        start_time = time.monotonic()
        try:
            if source:
                # get-config from specific datastore
                response = await driver.get_config(
                    source=source,
                    filter_=path,
                    filter_type=filter_type,
                )
            else:
                # get (operational + config data)
                response = await driver.get(filter_=path, filter_type=filter_type)

            elapsed_ms = (time.monotonic() - start_time) * 1000

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except ScrapliTimeout as e:
            raise TimeoutError(f"GET timed out on {handle.device_name}: {e}") from e
        except Exception as e:
            raise OperationError(f"GET failed on {handle.device_name}: {e}") from e

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform a NETCONF edit-config operation.

        Args:
            handle: The connection handle.
            config: XML configuration payload to apply.
            **kwargs: Additional options:
                - target: Target datastore ("running" or "candidate").
                         Default: "running".

        Returns:
            CommandResult with operation result.

        Raises:
            NotConnectedError: If not connected.
            ConfigurationError: If the edit-config operation fails.
            TimeoutError: If the operation times out.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]
        target = kwargs.get("target", "running")

        start_time = time.monotonic()
        try:
            response = await driver.edit_config(config=config, target=target)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Check if the response indicates an error
            if response.failed:
                raise ConfigurationError(
                    f"edit-config failed on {handle.device_name}: {response.result}"
                )

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except ConfigurationError:
            raise
        except ScrapliTimeout as e:
            raise TimeoutError(
                f"edit-config timed out on {handle.device_name}: {e}"
            ) from e
        except Exception as e:
            raise ConfigurationError(
                f"edit-config failed on {handle.device_name}: {e}"
            ) from e

    async def lock(
        self,
        handle: ConnectionHandle,
        target: str = "running",
    ) -> CommandResult:
        """Lock a configuration datastore.

        Args:
            handle: The connection handle.
            target: Target datastore to lock ("running" or "candidate").

        Returns:
            CommandResult with lock result.

        Raises:
            NotConnectedError: If not connected.
            OperationError: If the lock operation fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.lock(target=target)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            raise OperationError(f"lock failed on {handle.device_name}: {e}") from e

    async def unlock(
        self,
        handle: ConnectionHandle,
        target: str = "running",
    ) -> CommandResult:
        """Unlock a configuration datastore.

        Args:
            handle: The connection handle.
            target: Target datastore to unlock ("running" or "candidate").

        Returns:
            CommandResult with unlock result.

        Raises:
            NotConnectedError: If not connected.
            OperationError: If the unlock operation fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.unlock(target=target)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            raise OperationError(f"unlock failed on {handle.device_name}: {e}") from e

    async def commit(self, handle: ConnectionHandle) -> CommandResult:
        """Commit candidate configuration to running.

        Args:
            handle: The connection handle.

        Returns:
            CommandResult with commit result.

        Raises:
            NotConnectedError: If not connected.
            ConfigurationError: If the commit fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.commit()
            elapsed_ms = (time.monotonic() - start_time) * 1000

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            raise ConfigurationError(
                f"commit failed on {handle.device_name}: {e}"
            ) from e

    async def discard_changes(self, handle: ConnectionHandle) -> CommandResult:
        """Discard candidate configuration changes.

        Args:
            handle: The connection handle.

        Returns:
            CommandResult with discard result.

        Raises:
            NotConnectedError: If not connected.
            OperationError: If the discard fails.
        """
        if handle.device_name not in self._connections:
            raise NotConnectedError(f"No session for {handle.device_name}")

        driver = self._connections[handle.device_name]

        start_time = time.monotonic()
        try:
            response = await driver.discard()
            elapsed_ms = (time.monotonic() - start_time) * 1000

            return CommandResult(
                output=response.result,
                elapsed_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            raise OperationError(f"discard failed on {handle.device_name}: {e}") from e
