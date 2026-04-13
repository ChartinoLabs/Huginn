"""Tests for HTTPBroker implementation."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ServerTimeoutError

from huginn.brokers import (
    AuthenticationError,
    CapabilityError,
    ConfigurationError,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
    HTTPBroker,
    InvalidHandleError,
    NotConnectedError,
    TimeoutError,
)


@pytest.fixture
def broker() -> HTTPBroker:
    """Create an HTTPBroker instance for testing."""
    return HTTPBroker(broker_id="test-broker")


@pytest.fixture
def connection_config() -> ConnectionConfig:
    """Create a ConnectionConfig for testing."""
    return ConnectionConfig(
        device_name="api-server",
        host="api.example.com",
        port=443,
        credentials={"username": "admin", "password": "secret"},
        options={"verify_ssl": False},
    )


@pytest.fixture
def token_config() -> ConnectionConfig:
    """Create a ConnectionConfig with token auth for testing."""
    return ConnectionConfig(
        device_name="api-server",
        host="api.example.com",
        port=443,
        credentials={"token": "my-api-token", "token_type": "Bearer"},
        options={},
    )


@pytest.fixture
def connection_handle() -> ConnectionHandle:
    """Create a ConnectionHandle for testing."""
    return ConnectionHandle(
        broker_id="test-broker",
        device_name="api-server",
        connection_type="http",
        state=ConnectionState.CONNECTED,
        metadata={"base_url": "https://api.example.com"},
    )


class TestHTTPBrokerProperties:
    """Tests for HTTPBroker properties."""

    def test_name(self, broker: HTTPBroker) -> None:
        """Test broker name property."""
        assert broker.name == "http"

    def test_connection_type(self, broker: HTTPBroker) -> None:
        """Test broker connection_type property."""
        assert broker.connection_type == "http"

    def test_capabilities(self, broker: HTTPBroker) -> None:
        """Test broker capabilities."""
        capabilities = broker.capabilities()
        assert capabilities == {"get", "edit"}

    def test_protocol_version(self, broker: HTTPBroker) -> None:
        """Test PROTOCOL_VERSION attribute."""
        assert broker.PROTOCOL_VERSION == 1
        assert HTTPBroker.PROTOCOL_VERSION == 1


class TestCacheKey:
    """Tests for cache_key method."""

    def test_cache_key_get(self, broker: HTTPBroker) -> None:
        """Test cache_key returns path for GET operations."""
        key = broker.cache_key("get", path="/api/v1/devices")
        assert key == "/api/v1/devices"

    def test_cache_key_edit(self, broker: HTTPBroker) -> None:
        """Test cache_key returns None for edit operations."""
        key = broker.cache_key("edit", path="/api/v1/devices", method="POST")
        assert key is None

    def test_cache_key_unknown_operation(self, broker: HTTPBroker) -> None:
        """Test cache_key returns None for unknown operations."""
        key = broker.cache_key("unknown")
        assert key is None


class TestConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, broker: HTTPBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test successful session creation."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            handle = await broker.connect(connection_config)

            assert handle.broker_id == "test-broker"
            assert handle.device_name == "api-server"
            assert handle.connection_type == "http"
            assert handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_with_token_auth(
        self, broker: HTTPBroker, token_config: ConnectionConfig
    ) -> None:
        """Test session creation with token authentication."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            handle = await broker.connect(token_config)

            assert handle.device_name == "api-server"
            # Verify Authorization header was set
            call_kwargs = mock_session_class.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer my-api-token"

    @pytest.mark.asyncio
    async def test_connect_custom_base_url(self, broker: HTTPBroker) -> None:
        """Test session creation with custom base_url."""
        config = ConnectionConfig(
            device_name="api-server",
            host="unused",
            port=443,
            options={"base_url": "https://custom.api.com/v2"},
        )
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            await broker.connect(config)

            call_kwargs = mock_session_class.call_args.kwargs
            assert call_kwargs["base_url"] == "https://custom.api.com/v2"


class TestDisconnect:
    """Tests for disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful disconnect."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            await broker.disconnect(connection_handle)

            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_invalid_handle(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test disconnect with invalid handle."""
        with pytest.raises(InvalidHandleError):
            await broker.disconnect(connection_handle)


class TestIsAlive:
    """Tests for is_alive method."""

    @pytest.mark.asyncio
    async def test_is_alive_true(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns True for open session."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is True

    @pytest.mark.asyncio
    async def test_is_alive_false_closed(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns False for closed session."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.closed = True
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is False

    @pytest.mark.asyncio
    async def test_is_alive_no_session(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test is_alive returns False for non-existent session."""
        result = await broker.is_alive(connection_handle)
        assert result is False


class TestReconnect:
    """Tests for reconnect method."""

    @pytest.mark.asyncio
    async def test_reconnect_success(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful reconnect."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            new_handle = await broker.reconnect(connection_handle)

            assert new_handle.device_name == connection_handle.device_name
            assert new_handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_invalid_handle(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test reconnect with no stored config."""
        with pytest.raises(InvalidHandleError):
            await broker.reconnect(connection_handle)


class TestExecuteAndConfigure:
    """Tests for execute and configure methods (unsupported)."""

    @pytest.mark.asyncio
    async def test_execute_raises_capability_error(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test that execute raises CapabilityError."""
        with pytest.raises(CapabilityError) as exc_info:
            await broker.execute(connection_handle, "some command")

        assert "execute" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_configure_raises_capability_error(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test that configure raises CapabilityError."""
        with pytest.raises(CapabilityError) as exc_info:
            await broker.configure(connection_handle, ["command1", "command2"])

        assert "configure" in str(exc_info.value).lower()


class TestGet:
    """Tests for GET operations."""

    @pytest.mark.asyncio
    async def test_get_success(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful GET request."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"data": "value"}')
            mock_response.json = AsyncMock(return_value={"data": "value"})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.get(connection_handle, "/api/v1/data")

            assert result.output == '{"data": "value"}'
            assert result.structured == {"data": "value"}
            assert result.cached is False
            assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_get_not_connected(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test GET when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.get(connection_handle, "/api/v1/data")

    @pytest.mark.asyncio
    async def test_get_auth_failure(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test GET with authentication failure."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 401
            mock_response.text = AsyncMock(return_value="Unauthorized")
            mock_response.json = AsyncMock(side_effect=json.JSONDecodeError("", "", 0))
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)

            with pytest.raises(AuthenticationError):
                await broker.get(connection_handle, "/api/v1/data")

    @pytest.mark.asyncio
    async def test_get_timeout(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test GET timeout."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.get = MagicMock(side_effect=ServerTimeoutError("Timeout"))
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.get(connection_handle, "/api/v1/data")


class TestEdit:
    """Tests for edit operations."""

    @pytest.mark.asyncio
    async def test_edit_post_success(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful POST request."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 201
            mock_response.text = AsyncMock(return_value='{"id": 123}')
            mock_response.json = AsyncMock(return_value={"id": 123})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.request = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.edit(
                connection_handle,
                '{"name": "test"}',
                path="/api/v1/resources",
                method="POST",
            )

            assert result.output == '{"id": 123}'
            assert result.structured == {"id": 123}

    @pytest.mark.asyncio
    async def test_edit_put_success(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful PUT request."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.text = AsyncMock(return_value='{"updated": true}')
            mock_response.json = AsyncMock(return_value={"updated": True})
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.request = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.edit(
                connection_handle,
                '{"name": "updated"}',
                path="/api/v1/resources/123",
                method="PUT",
            )

            assert result.structured == {"updated": True}

    @pytest.mark.asyncio
    async def test_edit_delete_success(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful DELETE request."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 204
            mock_response.text = AsyncMock(return_value="")
            mock_response.json = AsyncMock(side_effect=json.JSONDecodeError("", "", 0))
            mock_response.raise_for_status = MagicMock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.request = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)
            result = await broker.edit(
                connection_handle,
                "",
                path="/api/v1/resources/123",
                method="DELETE",
            )

            assert result.output == ""
            assert result.structured is None

    @pytest.mark.asyncio
    async def test_edit_not_connected(
        self, broker: HTTPBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test edit when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.edit(connection_handle, "{}", path="/api/v1/data")

    @pytest.mark.asyncio
    async def test_edit_missing_path(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit without path raises ConfigurationError."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)

            with pytest.raises(ConfigurationError) as exc_info:
                await broker.edit(connection_handle, "{}")

            assert "path" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_edit_auth_failure(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit with authentication failure."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_response = AsyncMock()
            mock_response.status = 403
            mock_response.text = AsyncMock(return_value="Forbidden")
            mock_response.json = AsyncMock(side_effect=json.JSONDecodeError("", "", 0))
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = MagicMock()
            mock_session.request = MagicMock(return_value=mock_response)
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)

            with pytest.raises(AuthenticationError):
                await broker.edit(connection_handle, "{}", path="/api/v1/data")

    @pytest.mark.asyncio
    async def test_edit_timeout(
        self,
        broker: HTTPBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit timeout."""
        with patch("huginn.brokers.http.aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.request = MagicMock(side_effect=ServerTimeoutError("Timeout"))
            mock_session_class.return_value = mock_session

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.edit(connection_handle, "{}", path="/api/v1/data")


class TestProtocolCompliance:
    """Tests for protocol compliance."""

    def test_http_broker_is_protocol_compliant(self) -> None:
        """Test that HTTPBroker implements the protocol."""
        from huginn.brokers import ConnectionBrokerProtocolV1

        broker = HTTPBroker()
        assert isinstance(broker, ConnectionBrokerProtocolV1)
