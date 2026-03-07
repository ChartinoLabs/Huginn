"""HTTP connection broker using aiohttp.

This module provides an HTTP broker implementation that uses aiohttp
for RESTful API connectivity. It supports GET and edit (POST/PUT/PATCH/DELETE)
operations.
"""

import json
import time
import uuid
from typing import Any

import aiohttp
from aiohttp import ClientResponseError, ClientTimeout, ServerTimeoutError

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


class HTTPBroker:
    """HTTP connection broker using aiohttp.

    This broker manages HTTP sessions for RESTful API interactions using
    aiohttp's ClientSession. It supports GET and edit operations.

    Unlike SSH connections which maintain a persistent channel, HTTP
    connections are stateless. This broker manages a session with
    connection pooling and shared configuration (headers, auth, timeouts).

    Attributes:
        PROTOCOL_VERSION: The protocol version this broker implements.
    """

    PROTOCOL_VERSION: int = PROTOCOL_VERSION

    def __init__(self, broker_id: str | None = None) -> None:
        """Initialize the HTTP broker.

        Args:
            broker_id: Optional unique identifier for this broker instance.
                      If not provided, a UUID will be generated.
        """
        self._broker_id = broker_id or str(uuid.uuid4())
        self._sessions: dict[str, aiohttp.ClientSession] = {}
        self._configs: dict[str, ConnectionConfig] = {}

    @property
    def name(self) -> str:
        """Return the broker name."""
        return "http"

    @property
    def connection_type(self) -> str:
        """Return the connection type this broker handles."""
        return "http"

    def capabilities(self) -> set[str]:
        """Return the set of capabilities this broker supports.

        Returns:
            Set containing 'get' and 'edit' for REST operations.
        """
        return {"get", "edit"}

    def cache_key(self, operation: str, **kwargs: Any) -> str | None:  # noqa: ANN401
        """Generate a cache key for the given operation.

        GET operations are cacheable by path. Edit operations (POST/PUT/PATCH/DELETE)
        are not cacheable since they modify state.

        Args:
            operation: The operation type.
            **kwargs: Operation-specific arguments.

        Returns:
            The path string for GET operations, None for edit operations.
        """
        if operation == "get":
            return kwargs.get("path")
        return None

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        """Create an HTTP session for API interactions.

        Args:
            config: Connection configuration including host, credentials, options.

        Returns:
            A handle representing the session.

        Raises:
            ConnectionError: If session cannot be created.
        """
        # Build base URL from host and port
        scheme = config.options.get("scheme", "https")
        base_url = config.options.get("base_url")
        if base_url is None:
            port_suffix = f":{config.port}" if config.port not in (80, 443) else ""
            base_url = f"{scheme}://{config.host}{port_suffix}"

        # Build default headers
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(config.options.get("headers", {}))

        # Add authentication
        auth = None
        if "username" in config.credentials and "password" in config.credentials:
            auth = aiohttp.BasicAuth(
                config.credentials["username"],
                config.credentials["password"],
            )
        elif "token" in config.credentials:
            token = config.credentials["token"]
            token_type = config.credentials.get("token_type", "Bearer")
            headers["Authorization"] = f"{token_type} {token}"

        # Configure timeouts
        timeout_total = config.options.get("timeout", 30)
        timeout_connect = config.options.get("timeout_connect", 10)
        timeout = ClientTimeout(total=timeout_total, connect=timeout_connect)

        # SSL verification
        ssl_verify = config.options.get("verify_ssl", True)
        connector = aiohttp.TCPConnector(ssl=ssl_verify)

        try:
            session = aiohttp.ClientSession(
                base_url=base_url,
                headers=headers,
                auth=auth,
                timeout=timeout,
                connector=connector,
            )
        except Exception as e:
            raise ConnectionError(f"Failed to create HTTP session: {e}") from e

        self._sessions[config.device_name] = session
        self._configs[config.device_name] = config

        return ConnectionHandle(
            broker_id=self._broker_id,
            device_name=config.device_name,
            connection_type=self.connection_type,
            state=ConnectionState.CONNECTED,
            metadata={"base_url": base_url},
        )

    async def disconnect(self, handle: ConnectionHandle) -> None:
        """Close an HTTP session.

        Args:
            handle: The connection handle to disconnect.

        Raises:
            InvalidHandleError: If the handle is invalid.
        """
        if handle.device_name not in self._sessions:
            raise InvalidHandleError(f"No session found for {handle.device_name}")

        session = self._sessions.pop(handle.device_name)
        self._configs.pop(handle.device_name, None)
        await session.close()

    async def is_alive(self, handle: ConnectionHandle) -> bool:
        """Check if a session is still usable.

        For HTTP, this checks if the session exists and is not closed.

        Args:
            handle: The connection handle to check.

        Returns:
            True if the session is usable, False otherwise.
        """
        if handle.device_name not in self._sessions:
            return False

        session = self._sessions[handle.device_name]
        return not session.closed

    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle:
        """Recreate an HTTP session.

        Args:
            handle: The connection handle to reconnect.

        Returns:
            A new handle for the recreated session.

        Raises:
            InvalidHandleError: If no config exists for this handle.
            ConnectionError: If reconnection fails.
        """
        if handle.device_name not in self._configs:
            raise InvalidHandleError(f"No configuration found for {handle.device_name}")

        if handle.device_name in self._sessions:
            session = self._sessions.pop(handle.device_name)
            try:
                await session.close()
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
        """Execute a command.

        HTTP broker does not support execute operations.
        Use get() or edit() for REST API interactions.

        Args:
            handle: The connection handle.
            command: The command to execute.
            **kwargs: Additional options.

        Raises:
            CapabilityError: Always, as HTTP does not support execute.
        """
        raise CapabilityError(
            "HTTP broker does not support execute. Use get() or edit() instead."
        )

    async def configure(
        self,
        handle: ConnectionHandle,
        commands: list[str],
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Send configuration commands.

        HTTP broker does not support configure operations.
        Use edit() for REST API modifications.

        Args:
            handle: The connection handle.
            commands: List of configuration commands.
            **kwargs: Additional options.

        Raises:
            CapabilityError: Always, as HTTP does not support configure.
        """
        raise CapabilityError(
            "HTTP broker does not support configure. Use edit() instead."
        )

    def _parse_request_body(self, config: str | Any) -> Any:  # noqa: ANN401
        """Parse request body, attempting JSON decode if string.

        Args:
            config: The request body (JSON string or already parsed).

        Returns:
            Parsed JSON object if config was a valid JSON string,
            otherwise returns config as-is.
        """
        if isinstance(config, str):
            try:
                return json.loads(config)
            except json.JSONDecodeError:
                return config
        return config

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform an HTTP GET request.

        Args:
            handle: The connection handle.
            path: The API endpoint path (e.g., "/api/v1/interfaces").
            **kwargs: Additional options:
                - params: Query parameters dict
                - headers: Additional headers dict

        Returns:
            CommandResult with response body and optional parsed JSON.

        Raises:
            NotConnectedError: If not connected.
            AuthenticationError: If authentication fails (401/403).
            TimeoutError: If the request times out.
            OperationError: If the request fails.
        """
        if handle.device_name not in self._sessions:
            raise NotConnectedError(f"No session for {handle.device_name}")

        session = self._sessions[handle.device_name]
        params = kwargs.get("params")
        headers = kwargs.get("headers")

        start_time = time.monotonic()
        try:
            async with session.get(path, params=params, headers=headers) as response:
                body = await response.text()
                elapsed_ms = (time.monotonic() - start_time) * 1000

                # Try to parse JSON
                structured = None
                try:
                    structured = await response.json()
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    pass

                # Check for auth errors
                if response.status in (401, 403):
                    raise AuthenticationError(
                        f"Authentication failed for {path}: {response.status}"
                    )

                # Raise for other error status codes
                response.raise_for_status()

                return CommandResult(
                    output=body,
                    structured=structured,
                    elapsed_ms=elapsed_ms,
                    cached=False,
                )
        except AuthenticationError:
            raise
        except ServerTimeoutError as e:
            raise TimeoutError(f"GET {path} timed out: {e}") from e
        except ClientResponseError as e:
            raise OperationError(f"GET {path} failed: {e.status} {e.message}") from e
        except Exception as e:
            raise OperationError(f"GET {path} failed: {e}") from e

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> CommandResult:
        """Perform an HTTP edit operation (POST/PUT/PATCH/DELETE).

        Args:
            handle: The connection handle.
            config: The request body (JSON string or will be serialized).
            **kwargs: Additional options:
                - path: The API endpoint path (required)
                - method: HTTP method (default: "POST")
                - headers: Additional headers dict
                - params: Query parameters dict

        Returns:
            CommandResult with response body and optional parsed JSON.

        Raises:
            NotConnectedError: If not connected.
            ConfigurationError: If path is not provided.
            AuthenticationError: If authentication fails (401/403).
            TimeoutError: If the request times out.
            OperationError: If the request fails.
        """
        if handle.device_name not in self._sessions:
            raise NotConnectedError(f"No session for {handle.device_name}")

        path = kwargs.get("path")
        if not path:
            raise ConfigurationError("path is required for edit operations")

        session = self._sessions[handle.device_name]
        method = kwargs.get("method", "POST").upper()
        headers = kwargs.get("headers")
        params = kwargs.get("params")
        data = self._parse_request_body(config)

        start_time = time.monotonic()
        try:
            async with session.request(
                method, path, json=data, headers=headers, params=params
            ) as response:
                body = await response.text()
                elapsed_ms = (time.monotonic() - start_time) * 1000

                # Try to parse JSON
                structured = None
                try:
                    structured = await response.json()
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    pass

                # Check for auth errors
                if response.status in (401, 403):
                    raise AuthenticationError(
                        f"Authentication failed for {method} {path}: {response.status}"
                    )

                # Raise for other error status codes
                response.raise_for_status()

                return CommandResult(
                    output=body,
                    structured=structured,
                    elapsed_ms=elapsed_ms,
                    cached=False,
                )
        except AuthenticationError:
            raise
        except ServerTimeoutError as e:
            raise TimeoutError(f"{method} {path} timed out: {e}") from e
        except ClientResponseError as e:
            raise OperationError(
                f"{method} {path} failed: {e.status} {e.message}"
            ) from e
        except Exception as e:
            raise OperationError(f"{method} {path} failed: {e}") from e
