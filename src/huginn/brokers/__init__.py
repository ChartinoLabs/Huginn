"""Connection broker implementations for Huginn.

This module provides the protocol definitions and implementations for
connection brokers that manage device connections.

Classes:
    ConnectionBrokerProtocolV1: Protocol interface for connection brokers.
    SSHBroker: SSH connection broker using Scrapli.
    HTTPBroker: HTTP connection broker using aiohttp.
    NETCONFBroker: NETCONF connection broker using scrapli_netconf.

Data Classes:
    ConnectionHandle: Handle representing a managed connection.
    ConnectionConfig: Configuration for establishing a connection.
    CommandResult: Result of executing a command.

Enums:
    ConnectionState: State of a connection.

Exceptions:
    BrokerError: Base exception for broker errors.
    ConnectionError: Connection establishment failed.
    AuthenticationError: Authentication failed.
    TimeoutError: Operation timed out.
    NotConnectedError: Operation attempted on disconnected device.
    InvalidHandleError: Invalid connection handle.
    CommandError: Command execution failed.
    ConfigurationError: Configuration operation failed.
    OperationError: Generic operation error.
    CapabilityError: Unsupported capability.
"""

from huginn.brokers.exceptions import (
    AuthenticationError,
    BrokerError,
    CapabilityError,
    CommandError,
    ConfigurationError,
    ConnectionError,
    InvalidHandleError,
    NotConnectedError,
    OperationError,
    TimeoutError,
)
from huginn.brokers.http import HTTPBroker
from huginn.brokers.netconf import NETCONFBroker
from huginn.brokers.protocol import (
    CommandResult,
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
)
from huginn.brokers.ssh import SSHBroker

__all__ = [
    # Protocol
    "ConnectionBrokerProtocolV1",
    # Data classes
    "CommandResult",
    "ConnectionConfig",
    "ConnectionHandle",
    # Enums
    "ConnectionState",
    # Implementations
    "HTTPBroker",
    "NETCONFBroker",
    "SSHBroker",
    # Exceptions
    "AuthenticationError",
    "BrokerError",
    "CapabilityError",
    "CommandError",
    "ConfigurationError",
    "ConnectionError",
    "InvalidHandleError",
    "NotConnectedError",
    "OperationError",
    "TimeoutError",
]
