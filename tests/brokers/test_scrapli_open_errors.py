"""Tests for how the SSH and NETCONF brokers report errors opening a connection."""

import asyncio
from unittest.mock import AsyncMock, patch

import asyncssh
import pytest
from scrapli.exceptions import ScrapliAuthenticationFailed

from huginn.brokers import (
    AuthenticationError,
    BrokerError,
    ConnectionConfig,
    ConnectionError,
    NETCONFBroker,
    SSHBroker,
    TimeoutError,
)

_BROKERS = [
    pytest.param(SSHBroker, "huginn.brokers.ssh.AsyncScrapli", 22, id="ssh"),
    pytest.param(
        NETCONFBroker, "huginn.brokers.netconf.AsyncNetconfDriver", 830, id="netconf"
    ),
]


def _timeout_auth_failure() -> ScrapliAuthenticationFailed:
    """Build the error scrapli's asyncssh transport raises when open times out."""
    error = ScrapliAuthenticationFailed("timed out opening connection to device")
    error.__cause__ = asyncio.TimeoutError()
    return error


async def _connect_with_open_error(
    broker_class: type[SSHBroker] | type[NETCONFBroker],
    driver_path: str,
    port: int,
    open_error: Exception,
) -> BrokerError:
    """Connect with a driver whose open() raises, and return the broker error."""
    config = ConnectionConfig(
        device_name="router1",
        host="192.0.2.10",
        port=port,
        os="iosxe",
        credentials={"username": "admin", "password": "admin"},
    )
    with patch(driver_path) as mock_driver_class:
        mock_driver = AsyncMock()
        mock_driver.open.side_effect = open_error
        mock_driver_class.return_value = mock_driver

        with pytest.raises(BrokerError) as exc_info:
            await broker_class(broker_id="test-broker").connect(config)
    return exc_info.value


@pytest.mark.asyncio
@pytest.mark.parametrize(("broker_class", "driver_path", "port"), _BROKERS)
async def test_open_timeout_is_reported_as_timeout(
    broker_class: type[SSHBroker] | type[NETCONFBroker],
    driver_path: str,
    port: int,
) -> None:
    """A timeout that scrapli reports as an auth failure becomes TimeoutError."""
    error = await _connect_with_open_error(
        broker_class, driver_path, port, _timeout_auth_failure()
    )

    assert isinstance(error, TimeoutError)
    assert str(error) == (
        "Connection timed out to 192.0.2.10: timed out opening connection to device"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("broker_class", "driver_path", "port"), _BROKERS)
async def test_rejected_login_is_reported_as_authentication_failure(
    broker_class: type[SSHBroker] | type[NETCONFBroker],
    driver_path: str,
    port: int,
) -> None:
    """An auth failure that is not caused by a timeout stays AuthenticationError."""
    open_error = ScrapliAuthenticationFailed("all authentication methods failed")
    open_error.__cause__ = asyncssh.PermissionDenied("denied")

    error = await _connect_with_open_error(broker_class, driver_path, port, open_error)

    assert isinstance(error, AuthenticationError)
    assert str(error) == (
        "Authentication failed for 192.0.2.10: all authentication methods failed"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("broker_class", "driver_path", "port"), _BROKERS)
async def test_unwrapped_transport_error_names_the_host(
    broker_class: type[SSHBroker] | type[NETCONFBroker],
    driver_path: str,
    port: int,
) -> None:
    """An asyncssh error that scrapli does not wrap becomes ConnectionError."""
    error = await _connect_with_open_error(
        broker_class, driver_path, port, asyncssh.ConnectionLost("Connection lost")
    )

    assert isinstance(error, ConnectionError)
    assert str(error) == "Connection failed to 192.0.2.10: Connection lost"
    assert isinstance(error.__cause__, asyncssh.ConnectionLost)


@pytest.mark.asyncio
@pytest.mark.parametrize(("broker_class", "driver_path", "port"), _BROKERS)
async def test_error_without_message_uses_its_type_name(
    broker_class: type[SSHBroker] | type[NETCONFBroker],
    driver_path: str,
    port: int,
) -> None:
    """An error with an empty message is described by its type name."""
    error = await _connect_with_open_error(broker_class, driver_path, port, OSError())

    assert str(error) == "Connection failed to 192.0.2.10: OSError"
