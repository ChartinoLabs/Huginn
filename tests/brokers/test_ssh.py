"""Tests for SSHBroker implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)

from huginn.brokers import (
    AuthenticationError,
    CommandError,
    ConfigurationError,
    ConnectionConfig,
    ConnectionError,
    ConnectionHandle,
    ConnectionState,
    InvalidHandleError,
    NotConnectedError,
    SSHBroker,
    TimeoutError,
)


@pytest.fixture
def broker() -> SSHBroker:
    """Create an SSHBroker instance for testing."""
    return SSHBroker(broker_id="test-broker")


@pytest.fixture
def connection_config() -> ConnectionConfig:
    """Create a ConnectionConfig for testing."""
    return ConnectionConfig(
        device_name="router1",
        host="192.168.1.1",
        port=22,
        os="nxos",
        credentials={"username": "admin", "password": "secret"},
        options={},
    )


@pytest.fixture
def connection_handle() -> ConnectionHandle:
    """Create a ConnectionHandle for testing."""
    return ConnectionHandle(
        broker_id="test-broker",
        device_name="router1",
        connection_type="ssh",
        state=ConnectionState.CONNECTED,
        metadata={"host": "192.168.1.1", "port": 22},
    )


class TestSSHBrokerProperties:
    """Tests for SSHBroker properties."""

    def test_name(self, broker: SSHBroker) -> None:
        """Test broker name property."""
        assert broker.name == "ssh"

    def test_connection_type(self, broker: SSHBroker) -> None:
        """Test broker connection_type property."""
        assert broker.connection_type == "ssh"

    def test_capabilities(self, broker: SSHBroker) -> None:
        """Test broker capabilities."""
        capabilities = broker.capabilities()
        assert capabilities == {"execute", "configure", "get", "edit"}

    def test_protocol_version(self, broker: SSHBroker) -> None:
        """Test PROTOCOL_VERSION attribute."""
        assert broker.PROTOCOL_VERSION == 1
        assert SSHBroker.PROTOCOL_VERSION == 1


class TestCacheKey:
    """Tests for cache_key method."""

    def test_cache_key_execute(self, broker: SSHBroker) -> None:
        """Test cache_key returns command for execute operations."""
        key = broker.cache_key("execute", command="show version")
        assert key == "show version"

    def test_cache_key_configure(self, broker: SSHBroker) -> None:
        """Test cache_key returns None for configure operations."""
        key = broker.cache_key("configure", commands=["interface eth0"])
        assert key is None

    def test_cache_key_unknown_operation(self, broker: SSHBroker) -> None:
        """Test cache_key returns None for unknown operations."""
        key = broker.cache_key("unknown")
        assert key is None


class TestPlatformMapping:
    """Tests for OS to Scrapli platform mapping."""

    def test_map_nxos(self, broker: SSHBroker) -> None:
        """Test mapping nxos to cisco_nxos."""
        assert broker._get_scrapli_platform("nxos") == "cisco_nxos"

    def test_map_iosxe(self, broker: SSHBroker) -> None:
        """Test mapping iosxe to cisco_iosxe."""
        assert broker._get_scrapli_platform("iosxe") == "cisco_iosxe"

    def test_map_iosxr(self, broker: SSHBroker) -> None:
        """Test mapping iosxr to cisco_iosxr."""
        assert broker._get_scrapli_platform("iosxr") == "cisco_iosxr"

    def test_map_eos(self, broker: SSHBroker) -> None:
        """Test mapping eos to arista_eos."""
        assert broker._get_scrapli_platform("eos") == "arista_eos"

    def test_map_junos(self, broker: SSHBroker) -> None:
        """Test mapping junos to juniper_junos."""
        assert broker._get_scrapli_platform("junos") == "juniper_junos"

    def test_missing_os_raises_error(self, broker: SSHBroker) -> None:
        """Test that None OS raises ConnectionError."""
        with pytest.raises(ConnectionError) as exc_info:
            broker._get_scrapli_platform(None)
        assert "OS must be specified" in str(exc_info.value)

    def test_unsupported_os_raises_error(self, broker: SSHBroker) -> None:
        """Test that unsupported OS raises ConnectionError."""
        with pytest.raises(ConnectionError) as exc_info:
            broker._get_scrapli_platform("unsupported_os")
        assert "Unsupported OS" in str(exc_info.value)
        assert "unsupported_os" in str(exc_info.value)


class TestConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, broker: SSHBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test successful connection."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver_class.return_value = mock_driver

            handle = await broker.connect(connection_config)

            mock_driver.open.assert_awaited_once()
            assert handle.broker_id == "test-broker"
            assert handle.device_name == "router1"
            assert handle.connection_type == "ssh"
            assert handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_auth_failure(
        self, broker: SSHBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection with authentication failure."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.open.side_effect = ScrapliAuthenticationFailed("Auth failed")
            mock_driver_class.return_value = mock_driver

            with pytest.raises(AuthenticationError) as exc_info:
                await broker.connect(connection_config)

            assert "Authentication failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_connection_failure(
        self, broker: SSHBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection failure."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.open.side_effect = ScrapliConnectionError("Connection refused")
            mock_driver_class.return_value = mock_driver

            with pytest.raises(ConnectionError) as exc_info:
                await broker.connect(connection_config)

            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_timeout(
        self, broker: SSHBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection timeout."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.open.side_effect = ScrapliTimeout("Timed out")
            mock_driver_class.return_value = mock_driver

            with pytest.raises(TimeoutError) as exc_info:
                await broker.connect(connection_config)

            assert "timed out" in str(exc_info.value)


class TestDisconnect:
    """Tests for disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful disconnect."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            await broker.disconnect(connection_handle)

            mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_invalid_handle(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test disconnect with invalid handle."""
        with pytest.raises(InvalidHandleError):
            await broker.disconnect(connection_handle)


class TestIsAlive:
    """Tests for is_alive method."""

    @pytest.mark.asyncio
    async def test_is_alive_true(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns True for active connection."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            # isalive is a sync method, so use MagicMock for it
            mock_driver.isalive = MagicMock(return_value=True)
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is True

    @pytest.mark.asyncio
    async def test_is_alive_false(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns False for dead connection."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            # isalive is a sync method, so use MagicMock for it
            mock_driver.isalive = MagicMock(return_value=False)
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is False

    @pytest.mark.asyncio
    async def test_is_alive_no_connection(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test is_alive returns False for non-existent connection."""
        result = await broker.is_alive(connection_handle)
        assert result is False


class TestReconnect:
    """Tests for reconnect method."""

    @pytest.mark.asyncio
    async def test_reconnect_success(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful reconnect."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            new_handle = await broker.reconnect(connection_handle)

            assert new_handle.device_name == connection_handle.device_name
            assert new_handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_invalid_handle(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test reconnect with no stored config."""
        with pytest.raises(InvalidHandleError):
            await broker.reconnect(connection_handle)


class TestExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful command execution."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_response = MagicMock()
            mock_response.result = "Cisco IOS version 15.1"
            mock_driver.send_command.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.execute(connection_handle, "show version")

            assert result.output == "Cisco IOS version 15.1"
            assert result.cached is False
            assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_not_connected(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test execute when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.execute(connection_handle, "show version")

    @pytest.mark.asyncio
    async def test_execute_timeout(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test execute timeout."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.send_command.side_effect = ScrapliTimeout("Command timed out")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.execute(connection_handle, "show version")

    @pytest.mark.asyncio
    async def test_execute_command_error(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test execute with command error."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.send_command.side_effect = Exception("Command failed")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(CommandError):
                await broker.execute(connection_handle, "show version")


class TestConfigure:
    """Tests for configure method."""

    @pytest.mark.asyncio
    async def test_configure_success(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful configuration."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_response1 = MagicMock()
            mock_response1.result = "interface configured"
            mock_response2 = MagicMock()
            mock_response2.result = "ip address set"
            mock_driver.send_commands.return_value = [mock_response1, mock_response2]
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.configure(
                connection_handle,
                ["interface eth0", "ip address 10.0.0.1 255.255.255.0"],
            )

            assert "interface configured" in result.output
            assert "ip address set" in result.output
            assert result.cached is False

    @pytest.mark.asyncio
    async def test_configure_not_connected(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test configure when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.configure(connection_handle, ["interface eth0"])

    @pytest.mark.asyncio
    async def test_configure_timeout(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test configure timeout."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.send_commands.side_effect = ScrapliTimeout("Config timed out")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.configure(connection_handle, ["interface eth0"])

    @pytest.mark.asyncio
    async def test_configure_error(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test configure with error."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.send_commands.side_effect = Exception("Config failed")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(ConfigurationError):
                await broker.configure(connection_handle, ["interface eth0"])


class TestGet:
    """Tests for get method."""

    @pytest.mark.asyncio
    async def test_get_delegates_to_execute(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test that get delegates to execute."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_response = MagicMock()
            mock_response.result = "Interface Status\neth0: up"
            mock_driver.send_command.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.get(connection_handle, "show interfaces")

            mock_driver.send_command.assert_called_once_with("show interfaces")
            assert "Interface Status" in result.output
            assert result.cached is False

    @pytest.mark.asyncio
    async def test_get_not_connected(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test get when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.get(connection_handle, "show version")


class TestEdit:
    """Tests for edit method."""

    @pytest.mark.asyncio
    async def test_edit_delegates_to_configure(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test that edit parses config and delegates to configure."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_response1 = MagicMock()
            mock_response1.result = "interface configured"
            mock_response2 = MagicMock()
            mock_response2.result = "ip set"
            mock_driver.send_commands.return_value = [mock_response1, mock_response2]
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.edit(
                connection_handle,
                "interface eth0\nip address 10.0.0.1 255.255.255.0",
            )

            # Verify send_commands was called with parsed commands
            mock_driver.send_commands.assert_called_once()
            call_args = mock_driver.send_commands.call_args[0][0]
            assert call_args == ["interface eth0", "ip address 10.0.0.1 255.255.255.0"]

            assert "interface configured" in result.output
            assert "ip set" in result.output

    @pytest.mark.asyncio
    async def test_edit_strips_empty_lines(
        self,
        broker: SSHBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test that edit strips empty lines from config."""
        with patch("huginn.brokers.ssh.AsyncScrapli") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_response = MagicMock()
            mock_response.result = "done"
            mock_driver.send_commands.return_value = [mock_response]
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            await broker.edit(
                connection_handle,
                "\n  \ninterface eth0\n\n  \n",
            )

            call_args = mock_driver.send_commands.call_args[0][0]
            assert call_args == ["interface eth0"]

    @pytest.mark.asyncio
    async def test_edit_not_connected(
        self, broker: SSHBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test edit when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.edit(connection_handle, "interface eth0")
