"""Tests for the SSH key handling shared by the SSH and NETCONF brokers.

Without a private key, the brokers tell asyncssh to offer no keys, so that a
password login does not first offer every default key on the machine. The
``use_default_keys`` connection option restores asyncssh's default key loading.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from huginn.brokers import (
    ConnectionConfig,
    ConnectionError,
    NETCONFBroker,
    SSHBroker,
)
from huginn.brokers._scrapli_auth import build_auth_kwargs

PASSWORD_ONLY = {"username": "admin", "password": "secret"}
WITH_KEY = {
    "username": "admin",
    "password": "secret",
    "private_key": "/home/automation/.ssh/id_ed25519",
}

BrokerClass = type[SSHBroker] | type[NETCONFBroker]

BROKERS = [
    pytest.param(SSHBroker, "huginn.brokers.ssh.AsyncScrapli", "nxos", id="ssh"),
    pytest.param(
        NETCONFBroker,
        "huginn.brokers.netconf.AsyncNetconfDriver",
        "iosxe",
        id="netconf",
    ),
]


def _config(
    os: str,
    credentials: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> ConnectionConfig:
    """Build a connection config for router1 at a documentation address."""
    return ConnectionConfig(
        device_name="router1",
        host="192.0.2.10",
        port=22,
        os=os,
        credentials=credentials,
        options=options or {},
    )


async def _driver_kwargs(
    broker_class: BrokerClass,
    driver_path: str,
    config: ConnectionConfig,
) -> dict[str, Any]:
    """Connect with a mocked driver and return the kwargs it was built with."""
    with patch(driver_path) as mock_driver_class:
        mock_driver = AsyncMock()
        mock_driver.server_capabilities = []
        mock_driver.isalive = MagicMock(return_value=True)
        mock_driver_class.return_value = mock_driver
        await broker_class(broker_id="test").connect(config)
    mock_driver_class.assert_called_once()
    return dict(mock_driver_class.call_args.kwargs)


@pytest.mark.parametrize(("broker_class", "driver_path", "os"), BROKERS)
class TestBrokerDriverKwargs:
    """The driver kwargs each broker builds for the three key cases."""

    @pytest.mark.asyncio
    async def test_private_key_offers_only_that_key(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """A private key is passed on and no transport option is added."""
        kwargs = await _driver_kwargs(broker_class, driver_path, _config(os, WITH_KEY))

        assert kwargs["auth_private_key"] == WITH_KEY["private_key"]
        assert kwargs["auth_password"] == "secret"
        assert "transport_options" not in kwargs

    @pytest.mark.asyncio
    async def test_no_private_key_offers_no_keys(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """Without a private key, asyncssh is told to offer no keys."""
        kwargs = await _driver_kwargs(
            broker_class, driver_path, _config(os, PASSWORD_ONLY)
        )

        assert "auth_private_key" not in kwargs
        assert kwargs["auth_password"] == "secret"
        assert kwargs["transport_options"] == {"asyncssh": {"client_keys": None}}

    @pytest.mark.asyncio
    async def test_use_default_keys_restores_default_key_loading(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """use_default_keys leaves scrapli's default key loading in place."""
        config = _config(os, PASSWORD_ONLY, {"use_default_keys": True})

        kwargs = await _driver_kwargs(broker_class, driver_path, config)

        assert "transport_options" not in kwargs
        assert "use_default_keys" not in kwargs

    @pytest.mark.asyncio
    async def test_use_default_keys_false_is_consumed(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """use_default_keys: false is consumed and keys stay off."""
        config = _config(os, PASSWORD_ONLY, {"use_default_keys": False})

        kwargs = await _driver_kwargs(broker_class, driver_path, config)

        assert "use_default_keys" not in kwargs
        assert kwargs["transport_options"] == {"asyncssh": {"client_keys": None}}

    @pytest.mark.asyncio
    async def test_user_transport_options_are_merged(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """The testbed's transport_options are merged, not replaced."""
        user_options = {
            "transport_options": {
                "asyncssh": {"keepalive_interval": 30},
                "other": {"flag": True},
            }
        }
        config = _config(os, PASSWORD_ONLY, user_options)

        kwargs = await _driver_kwargs(broker_class, driver_path, config)

        assert kwargs["transport_options"] == {
            "asyncssh": {"client_keys": None, "keepalive_interval": 30},
            "other": {"flag": True},
        }
        # The testbed's own mapping is not modified.
        assert user_options["transport_options"]["asyncssh"] == {
            "keepalive_interval": 30
        }

    @pytest.mark.asyncio
    async def test_user_client_keys_wins(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """A client_keys the testbed sets takes precedence."""
        config = _config(
            os,
            PASSWORD_ONLY,
            {"transport_options": {"asyncssh": {"client_keys": ["/tmp/key"]}}},
        )

        kwargs = await _driver_kwargs(broker_class, driver_path, config)

        assert kwargs["transport_options"] == {
            "asyncssh": {"client_keys": ["/tmp/key"]}
        }

    @pytest.mark.asyncio
    async def test_auth_private_key_option_is_not_overridden(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """An auth_private_key connection option keeps its key."""
        config = _config(os, PASSWORD_ONLY, {"auth_private_key": "/tmp/key"})

        kwargs = await _driver_kwargs(broker_class, driver_path, config)

        assert kwargs["auth_private_key"] == "/tmp/key"
        assert "transport_options" not in kwargs

    @pytest.mark.asyncio
    async def test_invalid_use_default_keys_raises(
        self, broker_class: BrokerClass, driver_path: str, os: str
    ) -> None:
        """A non-boolean use_default_keys is rejected."""
        config = _config(os, PASSWORD_ONLY, {"use_default_keys": "yes"})

        with pytest.raises(ConnectionError, match="use_default_keys"):
            await _driver_kwargs(broker_class, driver_path, config)


class TestBuildAuthKwargs:
    """Edge cases of build_auth_kwargs itself."""

    def test_transport_options_none_is_treated_as_empty(self) -> None:
        """transport_options: null is treated as no options."""
        kwargs = build_auth_kwargs(PASSWORD_ONLY, {"transport_options": None})

        assert kwargs["transport_options"] == {"asyncssh": {"client_keys": None}}

    def test_non_mapping_transport_options_raises(self) -> None:
        """A non-mapping transport_options is rejected."""
        with pytest.raises(ConnectionError, match="transport_options"):
            build_auth_kwargs(PASSWORD_ONLY, {"transport_options": ["asyncssh"]})

    def test_non_mapping_asyncssh_options_raises(self) -> None:
        """A non-mapping transport_options.asyncssh is rejected."""
        with pytest.raises(ConnectionError, match=r"transport_options\.asyncssh"):
            build_auth_kwargs(
                PASSWORD_ONLY, {"transport_options": {"asyncssh": "client_keys"}}
            )

    def test_empty_private_key_counts_as_unset(self) -> None:
        """An empty private_key offers no keys, like a missing one."""
        kwargs = build_auth_kwargs({**PASSWORD_ONLY, "private_key": ""}, {})

        assert kwargs["transport_options"] == {"asyncssh": {"client_keys": None}}


class _ConnectCalledError(Exception):
    """Raised by the patched asyncssh connect to stop the open early."""


TRANSPORTS = [
    pytest.param(
        SSHBroker,
        "scrapli.transport.plugins.asyncssh.transport.connect",
        "nxos",
        id="ssh",
    ),
    pytest.param(
        NETCONFBroker,
        "scrapli_netconf.transport.plugins.asyncssh.transport.connect",
        "iosxe",
        id="netconf",
    ),
]


@pytest.mark.parametrize(("broker_class", "connect_path", "os"), TRANSPORTS)
class TestAsyncsshConnectArgs:
    """What scrapli's real asyncssh transport passes to ``asyncssh.connect``.

    These run the real scrapli drivers and patch only ``asyncssh.connect``, so
    they fail if scrapli changes the order in which it merges
    ``transport_options`` over its own authentication arguments.
    """

    async def _connect_args(
        self,
        broker_class: BrokerClass,
        connect_path: str,
        config: ConnectionConfig,
    ) -> dict[str, Any]:
        """Connect with the real driver and return asyncssh.connect's kwargs."""
        mock_connect = MagicMock(side_effect=_ConnectCalledError)
        with patch(connect_path, mock_connect):
            with pytest.raises(ConnectionError):
                await broker_class(broker_id="test").connect(config)
        mock_connect.assert_called_once()
        return dict(mock_connect.call_args.kwargs)

    @pytest.mark.asyncio
    async def test_no_private_key_passes_client_keys_none(
        self, broker_class: BrokerClass, connect_path: str, os: str
    ) -> None:
        """Without a private key, asyncssh.connect gets client_keys=None."""
        config = _config(os, PASSWORD_ONLY, {"auth_strict_key": False})

        args = await self._connect_args(broker_class, connect_path, config)

        assert args["client_keys"] is None
        assert args["password"] == "secret"

    @pytest.mark.asyncio
    async def test_private_key_passes_that_key(
        self, broker_class: BrokerClass, connect_path: str, os: str, tmp_path: Path
    ) -> None:
        """With a private key, asyncssh.connect gets only that key."""
        # scrapli resolves the key path when the driver is built.
        key_file = tmp_path / "id_ed25519"
        key_file.write_text("not a real key\n")
        credentials = {**PASSWORD_ONLY, "private_key": str(key_file)}
        config = _config(os, credentials, {"auth_strict_key": False})

        args = await self._connect_args(broker_class, connect_path, config)

        assert args["client_keys"] == str(key_file)

    @pytest.mark.asyncio
    async def test_use_default_keys_passes_scrapli_default(
        self, broker_class: BrokerClass, connect_path: str, os: str
    ) -> None:
        """use_default_keys passes scrapli's default, which loads ~/.ssh keys."""
        config = _config(
            os, PASSWORD_ONLY, {"auth_strict_key": False, "use_default_keys": True}
        )

        args = await self._connect_args(broker_class, connect_path, config)

        # scrapli's default, which asyncssh treats as "load the default keys".
        assert args["client_keys"] == ""
