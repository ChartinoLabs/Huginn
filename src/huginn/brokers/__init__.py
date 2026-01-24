"""Connection broker implementations for Huginn.

This module provides the protocol definitions and implementations for
connection brokers that manage device connections.

Classes:
    ConnectionBrokerProtocol_v1: Protocol interface for connection brokers.
    SSHBroker: SSH connection broker using Scrapli.

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
