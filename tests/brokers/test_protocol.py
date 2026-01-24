"""Tests for protocol definitions."""

from huginn.brokers import (
    CommandResult,
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
    SSHBroker,
)


class TestConnectionState:
    """Tests for ConnectionState enum."""

    def test_disconnected_value(self) -> None:
        """Test DISCONNECTED enum value."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"

    def test_connecting_value(self) -> None:
        """Test CONNECTING enum value."""
        assert ConnectionState.CONNECTING.value == "connecting"

    def test_connected_value(self) -> None:
        """Test CONNECTED enum value."""
        assert ConnectionState.CONNECTED.value == "connected"

    def test_error_value(self) -> None:
        """Test ERROR enum value."""
        assert ConnectionState.ERROR.value == "error"


class TestConnectionHandle:
    """Tests for ConnectionHandle dataclass."""

    def test_basic_instantiation(self) -> None:
        """Test creating a ConnectionHandle with required fields."""
        handle = ConnectionHandle(
            broker_id="broker-1",
            device_name="router1",
            connection_type="ssh",
            state=ConnectionState.CONNECTED,
        )
        assert handle.broker_id == "broker-1"
        assert handle.device_name == "router1"
        assert handle.connection_type == "ssh"
        assert handle.state == ConnectionState.CONNECTED
        assert handle.metadata == {}

    def test_with_metadata(self) -> None:
        """Test creating a ConnectionHandle with metadata."""
        handle = ConnectionHandle(
            broker_id="broker-1",
            device_name="router1",
            connection_type="ssh",
            state=ConnectionState.CONNECTED,
            metadata={"host": "192.168.1.1", "port": 22},
        )
        assert handle.metadata == {"host": "192.168.1.1", "port": 22}


class TestCommandResult:
    """Tests for CommandResult dataclass."""

    def test_basic_instantiation(self) -> None:
        """Test creating a CommandResult with required fields."""
        result = CommandResult(output="show version output")
        assert result.output == "show version output"
        assert result.structured is None
        assert result.elapsed_ms == 0.0
        assert result.cached is False

    def test_with_all_fields(self) -> None:
        """Test creating a CommandResult with all fields."""
        result = CommandResult(
            output="show version output",
            structured={"version": "1.0"},
            elapsed_ms=150.5,
            cached=True,
        )
        assert result.output == "show version output"
        assert result.structured == {"version": "1.0"}
        assert result.elapsed_ms == 150.5
        assert result.cached is True


class TestConnectionConfig:
    """Tests for ConnectionConfig dataclass."""

    def test_basic_instantiation(self) -> None:
        """Test creating a ConnectionConfig with required fields."""
        config = ConnectionConfig(
            device_name="router1",
            host="192.168.1.1",
            port=22,
        )
        assert config.device_name == "router1"
        assert config.host == "192.168.1.1"
        assert config.port == 22
        assert config.credentials == {}
        assert config.options == {}

    def test_with_credentials_and_options(self) -> None:
        """Test creating a ConnectionConfig with credentials and options."""
        config = ConnectionConfig(
            device_name="router1",
            host="192.168.1.1",
            port=22,
            credentials={"username": "admin", "password": "secret"},
            options={"timeout_socket": 30},
        )
        assert config.credentials == {"username": "admin", "password": "secret"}
        assert config.options == {"timeout_socket": 30}


class TestProtocolRuntimeCheckable:
    """Tests for protocol runtime checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Test that the protocol can be used with isinstance."""
        broker = SSHBroker()
        assert isinstance(broker, ConnectionBrokerProtocolV1)

    def test_non_broker_not_instance(self) -> None:
        """Test that non-brokers are not instances of the protocol."""

        class NotABroker:
            pass

        assert not isinstance(NotABroker(), ConnectionBrokerProtocolV1)
