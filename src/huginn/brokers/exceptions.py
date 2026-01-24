"""Exception hierarchy for connection brokers.

All broker-related exceptions inherit from BrokerError, allowing
callers to catch all broker exceptions with a single except clause
or specific exceptions as needed.
"""


class BrokerError(Exception):
    """Base exception for all broker errors."""


class ConnectionError(BrokerError):
    """Failed to establish connection to device."""


class AuthenticationError(BrokerError):
    """Authentication failed when connecting to device."""


class TimeoutError(BrokerError):
    """Operation timed out."""


class NotConnectedError(BrokerError):
    """Attempted operation on a device that is not connected."""


class InvalidHandleError(BrokerError):
    """The connection handle is invalid or expired."""


class CommandError(BrokerError):
    """Command execution failed."""


class ConfigurationError(BrokerError):
    """Configuration operation failed."""


class OperationError(BrokerError):
    """Generic operation error."""


class CapabilityError(BrokerError):
    """Broker does not support the requested capability."""
