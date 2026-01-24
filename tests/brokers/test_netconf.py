"""Tests for NETCONFBroker implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)

from huginn.brokers import (
    AuthenticationError,
    CapabilityError,
    ConfigurationError,
    ConnectionConfig,
    ConnectionError,
    ConnectionHandle,
    ConnectionState,
    InvalidHandleError,
    NETCONFBroker,
    NotConnectedError,
    TimeoutError,
)


@pytest.fixture
def broker() -> NETCONFBroker:
    """Create a NETCONFBroker instance for testing."""
    return NETCONFBroker(broker_id="test-broker")


@pytest.fixture
def connection_config() -> ConnectionConfig:
    """Create a ConnectionConfig for testing."""
    return ConnectionConfig(
        device_name="router1",
        host="192.168.1.1",
        port=830,
        os="iosxe",
        credentials={"username": "admin", "password": "secret"},
        options={},
    )


@pytest.fixture
def connection_handle() -> ConnectionHandle:
    """Create a ConnectionHandle for testing."""
    return ConnectionHandle(
        broker_id="test-broker",
        device_name="router1",
        connection_type="netconf",
        state=ConnectionState.CONNECTED,
        metadata={"host": "192.168.1.1", "port": 830},
    )


class TestNETCONFBrokerProperties:
    """Tests for NETCONFBroker properties."""

    def test_name(self, broker: NETCONFBroker) -> None:
        """Test broker name property."""
        assert broker.name == "netconf"

    def test_connection_type(self, broker: NETCONFBroker) -> None:
        """Test broker connection_type property."""
        assert broker.connection_type == "netconf"

    def test_capabilities(self, broker: NETCONFBroker) -> None:
        """Test broker capabilities."""
        capabilities = broker.capabilities()
        assert capabilities == {"get", "edit"}

    def test_protocol_version(self, broker: NETCONFBroker) -> None:
        """Test PROTOCOL_VERSION attribute."""
        assert broker.PROTOCOL_VERSION == 1
        assert NETCONFBroker.PROTOCOL_VERSION == 1


class TestCacheKey:
    """Tests for cache_key method."""

    def test_cache_key_get_with_filter(self, broker: NETCONFBroker) -> None:
        """Test cache_key returns filter for GET operations."""
        key = broker.cache_key("get", filter="<interfaces/>")
        assert key == "<interfaces/>"

    def test_cache_key_get_with_path(self, broker: NETCONFBroker) -> None:
        """Test cache_key returns path for GET operations."""
        key = broker.cache_key("get", path="/interfaces")
        assert key == "/interfaces"

    def test_cache_key_edit(self, broker: NETCONFBroker) -> None:
        """Test cache_key returns None for edit operations."""
        key = broker.cache_key("edit", config="<config>...</config>")
        assert key is None

    def test_cache_key_unknown_operation(self, broker: NETCONFBroker) -> None:
        """Test cache_key returns None for unknown operations."""
        key = broker.cache_key("unknown")
        assert key is None


class TestPlatformMapping:
    """Tests for OS to NETCONF platform mapping."""

    def test_map_iosxe(self, broker: NETCONFBroker) -> None:
        """Test mapping iosxe to cisco_iosxe."""
        assert broker._get_netconf_platform("iosxe") == "cisco_iosxe"

    def test_map_nxos(self, broker: NETCONFBroker) -> None:
        """Test mapping nxos to cisco_nxos."""
        assert broker._get_netconf_platform("nxos") == "cisco_nxos"

    def test_map_iosxr(self, broker: NETCONFBroker) -> None:
        """Test mapping iosxr to cisco_iosxr."""
        assert broker._get_netconf_platform("iosxr") == "cisco_iosxr"

    def test_map_junos(self, broker: NETCONFBroker) -> None:
        """Test mapping junos to juniper_junos."""
        assert broker._get_netconf_platform("junos") == "juniper_junos"

    def test_missing_os_raises_error(self, broker: NETCONFBroker) -> None:
        """Test that None OS raises ConnectionError."""
        with pytest.raises(ConnectionError) as exc_info:
            broker._get_netconf_platform(None)
        assert "OS must be specified" in str(exc_info.value)

    def test_unsupported_os_raises_error(self, broker: NETCONFBroker) -> None:
        """Test that unsupported OS raises ConnectionError."""
        with pytest.raises(ConnectionError) as exc_info:
            broker._get_netconf_platform("unsupported_os")
        assert "Unsupported OS" in str(exc_info.value)
        assert "unsupported_os" in str(exc_info.value)


class TestConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, broker: NETCONFBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test successful connection."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = ["urn:ietf:params:netconf:base:1.1"]
            mock_driver_class.return_value = mock_driver

            handle = await broker.connect(connection_config)

            mock_driver.open.assert_awaited_once()
            assert handle.broker_id == "test-broker"
            assert handle.device_name == "router1"
            assert handle.connection_type == "netconf"
            assert handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_default_port(self, broker: NETCONFBroker) -> None:
        """Test connection uses port 830 by default when port 22 is specified."""
        config = ConnectionConfig(
            device_name="router1",
            host="192.168.1.1",
            port=22,  # SSH default, should be converted to 830
            os="iosxe",
            credentials={"username": "admin", "password": "secret"},
        )
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver_class.return_value = mock_driver

            handle = await broker.connect(config)

            call_kwargs = mock_driver_class.call_args.kwargs
            assert call_kwargs["port"] == 830
            assert handle.metadata["port"] == 830

    @pytest.mark.asyncio
    async def test_connect_auth_failure(
        self, broker: NETCONFBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection with authentication failure."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.open.side_effect = ScrapliAuthenticationFailed("Auth failed")
            mock_driver_class.return_value = mock_driver

            with pytest.raises(AuthenticationError) as exc_info:
                await broker.connect(connection_config)

            assert "Authentication failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_connection_failure(
        self, broker: NETCONFBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection failure."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.open.side_effect = ScrapliConnectionError("Connection refused")
            mock_driver_class.return_value = mock_driver

            with pytest.raises(ConnectionError) as exc_info:
                await broker.connect(connection_config)

            assert "Connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connect_timeout(
        self, broker: NETCONFBroker, connection_config: ConnectionConfig
    ) -> None:
        """Test connection timeout."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
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
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful disconnect."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            await broker.disconnect(connection_handle)

            mock_driver.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_invalid_handle(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test disconnect with invalid handle."""
        with pytest.raises(InvalidHandleError):
            await broker.disconnect(connection_handle)


class TestIsAlive:
    """Tests for is_alive method."""

    @pytest.mark.asyncio
    async def test_is_alive_true(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns True for active connection."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.isalive = MagicMock(return_value=True)
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is True

    @pytest.mark.asyncio
    async def test_is_alive_false(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test is_alive returns False for dead connection."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.isalive = MagicMock(return_value=False)
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.is_alive(connection_handle)

            assert result is False

    @pytest.mark.asyncio
    async def test_is_alive_no_connection(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test is_alive returns False for non-existent connection."""
        result = await broker.is_alive(connection_handle)
        assert result is False


class TestReconnect:
    """Tests for reconnect method."""

    @pytest.mark.asyncio
    async def test_reconnect_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful reconnect."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            new_handle = await broker.reconnect(connection_handle)

            assert new_handle.device_name == connection_handle.device_name
            assert new_handle.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_reconnect_invalid_handle(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test reconnect with no stored config."""
        with pytest.raises(InvalidHandleError):
            await broker.reconnect(connection_handle)


class TestExecute:
    """Tests for execute method (raw RPC)."""

    @pytest.mark.asyncio
    async def test_execute_rpc_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful RPC execution."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply>...</rpc-reply>"
            mock_driver.rpc.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.execute(connection_handle, "<get-schema/>")

            assert result.output == "<rpc-reply>...</rpc-reply>"
            assert result.cached is False

    @pytest.mark.asyncio
    async def test_execute_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test execute when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.execute(connection_handle, "<get-schema/>")

    @pytest.mark.asyncio
    async def test_execute_timeout(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test execute timeout."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.rpc.side_effect = ScrapliTimeout("RPC timed out")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.execute(connection_handle, "<get-schema/>")


class TestConfigure:
    """Tests for configure method (unsupported)."""

    @pytest.mark.asyncio
    async def test_configure_raises_capability_error(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
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
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful GET request."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<data><interfaces/></data>"
            mock_driver.get.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.get(connection_handle, "<interfaces/>")

            mock_driver.get.assert_called_once()
            assert result.output == "<data><interfaces/></data>"
            assert result.cached is False

    @pytest.mark.asyncio
    async def test_get_config_from_source(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test get-config from specific datastore."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<data><config/></data>"
            mock_driver.get_config.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.get(
                connection_handle, "<interfaces/>", source="running"
            )

            mock_driver.get_config.assert_called_once_with(
                source="running",
                filter_="<interfaces/>",
                filter_type="subtree",
            )
            assert result.output == "<data><config/></data>"

    @pytest.mark.asyncio
    async def test_get_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test GET when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.get(connection_handle, "<interfaces/>")

    @pytest.mark.asyncio
    async def test_get_timeout(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test GET timeout."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.get.side_effect = ScrapliTimeout("GET timed out")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.get(connection_handle, "<interfaces/>")


class TestEdit:
    """Tests for edit-config operations."""

    @pytest.mark.asyncio
    async def test_edit_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful edit-config."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_response.failed = False
            mock_driver.edit_config.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.edit(
                connection_handle,
                "<config><interfaces/></config>",
            )

            mock_driver.edit_config.assert_called_once_with(
                config="<config><interfaces/></config>",
                target="running",
            )
            assert result.output == "<rpc-reply><ok/></rpc-reply>"

    @pytest.mark.asyncio
    async def test_edit_to_candidate(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit-config to candidate datastore."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_response.failed = False
            mock_driver.edit_config.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            await broker.edit(
                connection_handle,
                "<config><interfaces/></config>",
                target="candidate",
            )

            mock_driver.edit_config.assert_called_once_with(
                config="<config><interfaces/></config>",
                target="candidate",
            )

    @pytest.mark.asyncio
    async def test_edit_failure(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit-config failure."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-error>Invalid config</rpc-error>"
            mock_response.failed = True
            mock_driver.edit_config.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(ConfigurationError) as exc_info:
                await broker.edit(
                    connection_handle,
                    "<config><invalid/></config>",
                )

            assert "edit-config failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_edit_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test edit when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.edit(connection_handle, "<config/>")

    @pytest.mark.asyncio
    async def test_edit_timeout(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test edit timeout."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.edit_config.side_effect = ScrapliTimeout("Timed out")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(TimeoutError):
                await broker.edit(connection_handle, "<config/>")


class TestLockUnlock:
    """Tests for lock/unlock operations."""

    @pytest.mark.asyncio
    async def test_lock_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful lock."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_driver.lock.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.lock(connection_handle, "running")

            mock_driver.lock.assert_called_once_with(target="running")
            assert result.output == "<rpc-reply><ok/></rpc-reply>"

    @pytest.mark.asyncio
    async def test_lock_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test lock when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.lock(connection_handle)

    @pytest.mark.asyncio
    async def test_unlock_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful unlock."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_driver.unlock.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.unlock(connection_handle, "candidate")

            mock_driver.unlock.assert_called_once_with(target="candidate")
            assert result.output == "<rpc-reply><ok/></rpc-reply>"

    @pytest.mark.asyncio
    async def test_unlock_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test unlock when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.unlock(connection_handle)


class TestCommitDiscard:
    """Tests for commit/discard operations."""

    @pytest.mark.asyncio
    async def test_commit_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful commit."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_driver.commit.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.commit(connection_handle)

            mock_driver.commit.assert_called_once()
            assert result.output == "<rpc-reply><ok/></rpc-reply>"

    @pytest.mark.asyncio
    async def test_commit_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test commit when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.commit(connection_handle)

    @pytest.mark.asyncio
    async def test_commit_failure(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test commit failure."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_driver.commit.side_effect = Exception("Commit failed")
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)

            with pytest.raises(ConfigurationError) as exc_info:
                await broker.commit(connection_handle)

            assert "commit failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_discard_success(
        self,
        broker: NETCONFBroker,
        connection_config: ConnectionConfig,
        connection_handle: ConnectionHandle,
    ) -> None:
        """Test successful discard."""
        with patch("huginn.brokers.netconf.AsyncNetconfDriver") as mock_driver_class:
            mock_driver = AsyncMock()
            mock_driver.server_capabilities = []
            mock_response = MagicMock()
            mock_response.result = "<rpc-reply><ok/></rpc-reply>"
            mock_driver.discard.return_value = mock_response
            mock_driver_class.return_value = mock_driver

            await broker.connect(connection_config)
            result = await broker.discard_changes(connection_handle)

            mock_driver.discard.assert_called_once()
            assert result.output == "<rpc-reply><ok/></rpc-reply>"

    @pytest.mark.asyncio
    async def test_discard_not_connected(
        self, broker: NETCONFBroker, connection_handle: ConnectionHandle
    ) -> None:
        """Test discard when not connected."""
        with pytest.raises(NotConnectedError):
            await broker.discard_changes(connection_handle)


class TestProtocolCompliance:
    """Tests for protocol compliance."""

    def test_netconf_broker_is_protocol_compliant(self) -> None:
        """Test that NETCONFBroker implements the protocol."""
        from huginn.brokers import ConnectionBrokerProtocolV1

        broker = NETCONFBroker()
        assert isinstance(broker, ConnectionBrokerProtocolV1)
