"""Unit tests for runtime broker protocol selection and dispatch."""

from dataclasses import dataclass
from typing import cast

import pytest

from huginn.brokers.protocol import (
    CommandResult,
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
)
from huginn.models import ConnectionDefinition, Device
from huginn.runtime_broker import RuntimeBroker, RuntimeBrokerError


@dataclass
class _FakeBroker:
    broker_name: str

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        return ConnectionHandle(
            broker_id=self.broker_name,
            device_name=config.device_name,
            connection_type=self.broker_name,
            state=ConnectionState.CONNECTED,
        )

    async def disconnect(self, handle: ConnectionHandle) -> None:
        return None

    async def execute(self, handle: ConnectionHandle, command: str) -> CommandResult:
        return CommandResult(output=f"{self.broker_name}:execute:{command}")

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: object,
    ) -> CommandResult:
        return CommandResult(output=f"{self.broker_name}:get:{path}")

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: object,
    ) -> CommandResult:
        return CommandResult(output=f"{self.broker_name}:edit:{config}")


@pytest.mark.asyncio
async def test_runtime_broker_uses_ssh_for_execute() -> None:
    """Execute dispatches to SSH broker for ssh protocol devices."""
    runtime = RuntimeBroker(
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device])
    result = await runtime.execute(device, "show version")

    assert result.output == "ssh:execute:show version"


@pytest.mark.asyncio
async def test_runtime_broker_maps_https_to_http_broker() -> None:
    """HTTPS protocol is routed to HTTP broker implementation."""
    runtime = RuntimeBroker(
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="https")

    await runtime.connect_targets([device])
    result = await runtime.get(device, "/health")

    assert result.output == "http:get:/health"


@pytest.mark.asyncio
async def test_runtime_broker_uses_netconf_for_edit() -> None:
    """NETCONF protocol devices dispatch edit operations to netconf broker."""
    runtime = RuntimeBroker(
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="netconf")

    await runtime.connect_targets([device])
    result = await runtime.edit(device, "<config/>")

    assert result.output == "netconf:edit:<config/>"


@pytest.mark.asyncio
async def test_runtime_broker_errors_on_missing_default_credential() -> None:
    """Device connection fails when required default credential is absent."""
    runtime = RuntimeBroker(
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="ssh", credentials={})

    with pytest.raises(RuntimeBrokerError, match="missing credential 'default'"):
        await runtime.connect_targets([device])


def _device(
    *,
    protocol: str,
    credentials: dict[str, dict[str, str]] | None = None,
) -> Device:
    """Build a minimal test device with one connection definition."""
    return Device(
        name="spine-01",
        os="nxos",
        credentials=credentials if credentials is not None else _default_credentials(),
        connections={
            protocol: ConnectionDefinition(
                name=protocol,
                protocol=protocol,
                host="10.0.0.1",
                port=443 if protocol in {"http", "https", "rest"} else 22,
                credential=None,
                options={},
            )
        },
    )


def _default_credentials() -> dict[str, dict[str, str]]:
    return {"default": {"username": "admin", "password": "admin"}}


def _fake_broker(name: str) -> ConnectionBrokerProtocolV1:
    return cast(ConnectionBrokerProtocolV1, _FakeBroker(name))
