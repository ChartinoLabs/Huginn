"""Build the authentication arguments for a scrapli driver.

Shared by the SSH and NETCONF brokers, which both open connections through
scrapli's asyncssh transport.

scrapli passes ``auth_private_key`` to asyncssh as ``client_keys``. When no
private key is set, that value is ``""``, and asyncssh treats any
``client_keys`` other than ``None`` as "load the default keys", so it offers
every ``~/.ssh/id_*`` key before trying the password. Each rejected key costs a
server round trip. To avoid that, a connection without a private key sets
``client_keys=None`` through ``transport_options["asyncssh"]``, which scrapli
merges after its own authentication arguments.
"""

from typing import Any

from huginn.brokers.exceptions import ConnectionError

# Connection option that restores asyncssh's default key loading.
USE_DEFAULT_KEYS_OPTION = "use_default_keys"


def build_auth_kwargs(
    credentials: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Return the scrapli driver kwargs for credentials and connection options.

    Credentials become ``auth_username``, ``auth_password`` and
    ``auth_private_key``. Connection options are merged over them and passed
    through, except ``use_default_keys``, which Huginn consumes.

    When the merged kwargs carry no ``auth_private_key`` and
    ``use_default_keys`` is not true, ``client_keys=None`` is added to
    ``transport_options["asyncssh"]`` so that asyncssh offers no keys. A
    ``client_keys`` the connection options already set is kept, and the
    caller's ``transport_options`` mappings are copied, not modified.

    Args:
        credentials: The resolved credential for the connection.
        options: The connection options from the testbed.

    Returns:
        The kwargs to pass to the scrapli driver, without host, port,
        platform or transport.

    Raises:
        ConnectionError: If ``use_default_keys`` is not a boolean, or
            ``transport_options`` or its ``asyncssh`` entry is not a mapping.
    """
    kwargs = {
        f"auth_{field}": credentials[field]
        for field in ("username", "password", "private_key")
        if field in credentials
    }

    passthrough = dict(options)
    use_default_keys = passthrough.pop(USE_DEFAULT_KEYS_OPTION, False)
    if not isinstance(use_default_keys, bool):
        raise ConnectionError(
            f"Connection option '{USE_DEFAULT_KEYS_OPTION}' must be true or "
            f"false, got {use_default_keys!r}"
        )
    kwargs.update(passthrough)

    if not use_default_keys and not kwargs.get("auth_private_key"):
        kwargs["transport_options"] = _without_default_keys(
            kwargs.get("transport_options")
        )
    return kwargs


def _without_default_keys(transport_options: object) -> dict[str, Any]:
    """Return ``transport_options`` with asyncssh's ``client_keys`` defaulted to None.

    Args:
        transport_options: The ``transport_options`` connection option, if any.

    Returns:
        A new mapping whose ``asyncssh`` entry sets ``client_keys`` to ``None``
        unless it already sets ``client_keys``.

    Raises:
        ConnectionError: If ``transport_options`` or its ``asyncssh`` entry is
            not a mapping.
    """
    outer = _as_mapping(transport_options, "transport_options")
    asyncssh = _as_mapping(outer.get("asyncssh"), "transport_options.asyncssh")
    return {**outer, "asyncssh": {"client_keys": None, **asyncssh}}


def _as_mapping(value: object, name: str) -> dict[str, Any]:
    """Return ``value`` as a mapping, treating ``None`` as empty.

    Args:
        value: The option value.
        name: The option name, for the error message.

    Returns:
        The value, or an empty mapping for ``None``.

    Raises:
        ConnectionError: If the value is neither ``None`` nor a mapping.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConnectionError(
            f"Connection option '{name}' must be a mapping, got {type(value).__name__}"
        )
    return value
