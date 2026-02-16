"""Unit tests for runtime broker protocol selection and dispatch."""

import asyncio
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
from huginn.enums import BrokerType, ConnectionProtocol
from huginn.models import ConnectionDefinition, Device
from huginn.runtime_broker import RuntimeBroker, RuntimeBrokerError


@dataclass
class _FakeBroker:
    broker_name: str
    connect_calls: int = 0
    disconnect_calls: int = 0
    execute_calls: int = 0
    get_calls: int = 0
    edit_calls: int = 0

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        self.connect_calls += 1
        return ConnectionHandle(
            broker_id=self.broker_name,
            device_name=config.device_name,
            connection_type=self.broker_name,
            state=ConnectionState.CONNECTED,
        )

    async def disconnect(self, handle: ConnectionHandle) -> None:
        self.disconnect_calls += 1
        return None

    async def execute(self, handle: ConnectionHandle, command: str) -> CommandResult:
        self.execute_calls += 1
        return CommandResult(output=f"{self.broker_name}:execute:{command}")

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: object,
    ) -> CommandResult:
        self.get_calls += 1
        return CommandResult(output=f"{self.broker_name}:get:{path}")

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: object,
    ) -> CommandResult:
        self.edit_calls += 1
        return CommandResult(output=f"{self.broker_name}:edit:{config}")


@pytest.mark.asyncio
async def test_runtime_broker_uses_ssh_for_execute() -> None:
    """Execute dispatches to SSH broker for ssh protocol devices."""
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    result = await runtime.execute(device, "show version")

    assert result.output == "ssh:execute:show version"


@pytest.mark.asyncio
async def test_runtime_broker_maps_https_to_http_broker() -> None:
    """HTTPS protocol is routed to HTTP broker implementation."""
    runtime = RuntimeBroker(
        required_brokers={BrokerType.HTTP},
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="https")

    await runtime.connect_targets([device], {BrokerType.HTTP})
    result = await runtime.get(device, "/health")

    assert result.output == "http:get:/health"


@pytest.mark.asyncio
async def test_runtime_broker_uses_netconf_for_edit() -> None:
    """NETCONF protocol devices dispatch edit operations to netconf broker."""
    runtime = RuntimeBroker(
        required_brokers={BrokerType.NETCONF},
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="netconf")

    await runtime.connect_targets([device], {BrokerType.NETCONF})
    result = await runtime.edit(device, "<config/>")

    assert result.output == "netconf:edit:<config/>"


@pytest.mark.asyncio
async def test_runtime_broker_errors_on_missing_default_credential() -> None:
    """Device connection fails when required default credential is absent."""
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device(protocol="ssh", credentials={})

    with pytest.raises(RuntimeBrokerError, match="missing credential 'default'"):
        await runtime.connect_targets([device], {BrokerType.SSH})


@pytest.mark.asyncio
async def test_runtime_broker_requires_explicit_broker_when_multiple_connected() -> (
    None
):
    """Operations require broker selection when device has multiple transports."""
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH, BrokerType.NETCONF},
        ssh_broker=_fake_broker("ssh"),
        http_broker=_fake_broker("http"),
        netconf_broker=_fake_broker("netconf"),
    )
    device = _device_with_connections(protocols=["ssh", "netconf"])

    await runtime.connect_targets(
        [device],
        {BrokerType.SSH, BrokerType.NETCONF},
    )

    with pytest.raises(RuntimeBrokerError, match="multiple connected brokers"):
        await runtime.execute(device, "show version")

    result = await runtime.for_protocol("netconf").execute(device, "<rpc/>")
    assert result.output == "netconf:execute:<rpc/>"


@pytest.mark.asyncio
async def test_runtime_broker_reuses_existing_connections() -> None:
    """Repeated connect requests reuse existing target+broker handles."""
    ssh_fake = _FakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    await runtime.connect_targets([device], {BrokerType.SSH})

    assert ssh_fake.connect_calls == 1


@pytest.mark.asyncio
async def test_runtime_broker_caches_execute_by_default() -> None:
    """Repeated execute calls reuse cached output by default."""
    ssh_fake = _FakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    first = await runtime.execute(device, "show version")
    second = await runtime.execute(device, "show version")

    assert first.output == second.output
    assert ssh_fake.execute_calls == 1


@pytest.mark.asyncio
async def test_runtime_broker_execute_can_bypass_cache() -> None:
    """use_cache=False forces backend execution for execute calls."""
    ssh_fake = _FakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    await runtime.execute(device, "show version", use_cache=False)
    await runtime.execute(device, "show version", use_cache=False)

    assert ssh_fake.execute_calls == 2


@pytest.mark.asyncio
async def test_runtime_broker_execute_can_bust_cache() -> None:
    """bust_cache=True refreshes a previously cached execute command."""
    ssh_fake = _FakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    await runtime.execute(device, "show version")
    await runtime.execute(device, "show version", bust_cache=True)

    assert ssh_fake.execute_calls == 2


@pytest.mark.asyncio
async def test_runtime_broker_invalidate_execute_cache() -> None:
    """Explicit execute-cache invalidation forces next command refresh."""
    ssh_fake = _FakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    await runtime.execute(device, "show version")
    runtime.invalidate_execute_cache(target=device, command="show version")
    await runtime.execute(device, "show version")

    assert ssh_fake.execute_calls == 2


@pytest.mark.asyncio
async def test_runtime_broker_deduplicates_concurrent_execute_requests() -> None:
    """Concurrent identical execute calls share one in-flight backend call."""
    ssh_fake = _SlowFakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await runtime.connect_targets([device], {BrokerType.SSH})
    await asyncio.gather(
        runtime.execute(device, "show version"),
        runtime.execute(device, "show version"),
    )

    assert ssh_fake.execute_calls == 1


@pytest.mark.asyncio
async def test_runtime_broker_caches_get_with_kwargs() -> None:
    """Identical get calls with kwargs reuse cached output."""
    netconf_fake = _FakeBroker("netconf")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.NETCONF},
        netconf_broker=_fake_broker_instance(netconf_fake),
    )
    device = _device(protocol="netconf")

    await runtime.connect_targets([device], {BrokerType.NETCONF})
    await runtime.get(device, "/interfaces", datastore="running")
    await runtime.get(device, "/interfaces", datastore="running")

    assert netconf_fake.get_calls == 1


@pytest.mark.asyncio
async def test_runtime_broker_invalidate_get_cache() -> None:
    """Explicit get-cache invalidation refreshes the next request."""
    netconf_fake = _FakeBroker("netconf")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.NETCONF},
        netconf_broker=_fake_broker_instance(netconf_fake),
    )
    device = _device(protocol="netconf")

    await runtime.connect_targets([device], {BrokerType.NETCONF})
    await runtime.get(device, "/interfaces", datastore="running")
    runtime.invalidate_get_cache(
        target=device,
        path="/interfaces",
        datastore="running",
    )
    await runtime.get(device, "/interfaces", datastore="running")

    assert netconf_fake.get_calls == 2


@pytest.mark.asyncio
async def test_runtime_broker_deduplicates_concurrent_connect_requests() -> None:
    """Concurrent connect calls share one in-flight connect per target+broker."""
    ssh_fake = _SlowFakeBroker("ssh")
    runtime = RuntimeBroker(
        required_brokers={BrokerType.SSH},
        ssh_broker=_fake_broker_instance(ssh_fake),
    )
    device = _device(protocol="ssh")

    await asyncio.gather(
        runtime.connect_targets([device], {BrokerType.SSH}),
        runtime.connect_targets([device], {BrokerType.SSH}),
    )

    assert ssh_fake.connect_calls == 1


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
                protocol=ConnectionProtocol(protocol),
                host="10.0.0.1",
                port=443 if protocol in {"http", "https", "rest"} else 22,
                credential=None,
                options={},
            )
        },
    )


def _device_with_connections(*, protocols: list[str]) -> Device:
    """Build a device with multiple connection definitions."""
    connections = {
        protocol: ConnectionDefinition(
            name=protocol,
            protocol=ConnectionProtocol(protocol),
            host="10.0.0.1",
            port=443 if protocol in {"http", "https", "rest"} else 22,
            credential=None,
            options={},
        )
        for protocol in protocols
    }
    return Device(
        name="spine-01",
        os="nxos",
        credentials=_default_credentials(),
        connections=connections,
    )


def _default_credentials() -> dict[str, dict[str, str]]:
    return {"default": {"username": "admin", "password": "admin"}}


@dataclass
class _SlowFakeBroker(_FakeBroker):
    """Fake broker that yields during connect to force call overlap."""

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        await asyncio.sleep(0.01)
        return await super().connect(config)

    async def execute(self, handle: ConnectionHandle, command: str) -> CommandResult:
        """Yield during execute to force concurrent command overlap."""
        await asyncio.sleep(0.01)
        return await super().execute(handle, command)


def _fake_broker(name: str) -> ConnectionBrokerProtocolV1:
    return cast(ConnectionBrokerProtocolV1, _FakeBroker(name))


def _fake_broker_instance(broker: _FakeBroker) -> ConnectionBrokerProtocolV1:
    return cast(ConnectionBrokerProtocolV1, broker)
