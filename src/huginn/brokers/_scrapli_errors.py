"""Translate exceptions from opening a scrapli connection into broker errors.

Shared by the SSH and NETCONF brokers, which both open connections through
scrapli's asyncssh transport.
"""

import asyncio

from scrapli.exceptions import (
    ScrapliAuthenticationFailed,
    ScrapliConnectionError,
    ScrapliTimeout,
)

from huginn.brokers.exceptions import (
    AuthenticationError,
    BrokerError,
    ConnectionError,
    TimeoutError,
)


def translate_open_error(error: Exception, *, host: str) -> BrokerError:
    """Return the broker error for an exception raised while opening a connection.

    scrapli's asyncssh transport raises ``ScrapliAuthenticationFailed`` when
    opening the connection times out, so a timeout is told apart from a real
    authentication failure by the exception's ``__cause__``. Exceptions scrapli
    does not wrap, such as asyncssh's ``ConnectionLost``, become
    ``ConnectionError``.

    Args:
        error: The exception raised by the driver's ``open()``.
        host: The host the connection was opened to.

    Returns:
        The broker error to raise from the original exception.
    """
    if isinstance(error, ScrapliAuthenticationFailed):
        if isinstance(error.__cause__, asyncio.TimeoutError):
            return TimeoutError(f"Connection timed out to {host}: {error}")
        return AuthenticationError(f"Authentication failed for {host}: {error}")
    if isinstance(error, ScrapliTimeout):
        return TimeoutError(f"Connection timed out to {host}: {error}")
    if isinstance(error, ScrapliConnectionError):
        return ConnectionError(f"Connection failed to {host}: {error}")
    detail = str(error) or type(error).__name__
    return ConnectionError(f"Connection failed to {host}: {detail}")
