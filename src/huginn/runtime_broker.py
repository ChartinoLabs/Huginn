"""Runtime broker abstraction for protocol-aware target operations."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, cast

from huginn.brokers import (
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
)
from huginn.brokers.http import HTTPBroker
from huginn.brokers.netconf import NETCONFBroker
from huginn.brokers.protocol import CommandResult
from huginn.brokers.ssh import SSHBroker
from huginn.enums import BrokerType, ConnectionProtocol
from huginn.models import ConnectionDefinition, CredentialFields, Device
from huginn.plugin_registry import PluginRegistry

_CacheOperation = Literal["execute", "get"]
_CacheKwargs = tuple[tuple[str, str], ...]
_CacheKey = tuple[_CacheOperation, str, str, str, _CacheKwargs]
_Operation = Callable[[], Awaitable[CommandResult]]


class RuntimeBrokerError(RuntimeError):
    """Raised when runtime broker operations cannot be completed."""


@dataclass(frozen=True)
class RuntimeBrokerClient:
    """A protocol-pinned broker view for test job access."""

    _runtime_broker: "RuntimeBroker"
    _broker_key: str

    async def execute(
        self,
        target: Device,
        command: str,
        *,
        use_cache: bool = True,
        bust_cache: bool = False,
    ) -> CommandResult:
        """Execute a command using the pinned broker type."""
        return await self._runtime_broker.execute(
            target,
            command,
            broker=self._broker_key,
            use_cache=use_cache,
            bust_cache=bust_cache,
        )

    async def get(
        self,
        target: Device,
        path: str,
        **kwargs: object,
    ) -> CommandResult:
        """Run a GET-style operation using the pinned broker type."""
        return await self._runtime_broker._get_with_pinned_broker(
            target,
            path,
            broker=self._broker_key,
            kwargs=kwargs,
        )

    async def edit(
        self,
        target: Device,
        config: str,
        **kwargs: object,
    ) -> CommandResult:
        """Run an edit-style operation using the pinned broker type."""
        return await self._runtime_broker.edit(
            target,
            config,
            broker=self._broker_key,
            **kwargs,
        )


class RuntimeBroker:
    """Broker facade used by test jobs at runtime."""

    def __init__(
        self,
        *,
        required_brokers: set[BrokerType] | set[str] | None = None,
        registry: PluginRegistry | None = None,
        broker_overrides: dict[str, ConnectionBrokerProtocolV1] | None = None,
        ssh_broker: ConnectionBrokerProtocolV1 | None = None,
        http_broker: ConnectionBrokerProtocolV1 | None = None,
        netconf_broker: ConnectionBrokerProtocolV1 | None = None,
    ) -> None:
        """Initialize runtime broker facade with required broker instances.

        Args:
            required_brokers: Set of broker types needed for this run.
            registry: Plugin registry for discovering broker implementations.
                If None, falls back to direct imports of built-in brokers.
            broker_overrides: Pre-built broker instances keyed by type name.
                Takes precedence over registry discovery.
            ssh_broker: Deprecated. Use broker_overrides instead. Kept for
                backward compatibility with existing tests.
            http_broker: Deprecated. Use broker_overrides instead.
            netconf_broker: Deprecated. Use broker_overrides instead.
        """
        required = required_brokers or {BrokerType.SSH}
        overrides = _merge_legacy_overrides(
            broker_overrides=broker_overrides,
            ssh_broker=ssh_broker,
            http_broker=http_broker,
            netconf_broker=netconf_broker,
        )
        self._brokers: dict[str, ConnectionBrokerProtocolV1] = _build_brokers(
            required_brokers={str(b) for b in required},
            registry=registry,
            overrides=overrides,
        )
        self._handles: dict[tuple[str, str], ConnectionHandle] = {}
        self._inflight_connections: dict[
            tuple[str, str],
            asyncio.Task[ConnectionHandle],
        ] = {}
        self._operation_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._command_cache: dict[_CacheKey, CommandResult] = {}
        self._inflight_commands: dict[_CacheKey, asyncio.Task[CommandResult]] = {}

    async def connect_targets(
        self,
        targets: list[Device],
        required_brokers: set[BrokerType] | set[str],
    ) -> None:
        """Open required broker connections for all target devices."""
        required_keys = _normalize_required_broker_strings(required_brokers)
        try:
            tasks: list[asyncio.Task[None]] = []
            for device in targets:
                for broker_key in required_keys:
                    tasks.append(
                        asyncio.create_task(
                            self._connect_target_broker_pair(device, broker_key)
                        )
                    )
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def _connect_target_broker_pair(
        self,
        device: Device,
        broker_key: str,
    ) -> None:
        """Connect one target+broker pair once across concurrent callers."""
        handle_key = (device.name, broker_key)
        if handle_key in self._handles:
            return

        task = self._inflight_connections.get(handle_key)
        if task is None:
            task = asyncio.create_task(self._open_connection(device, broker_key))
            self._inflight_connections[handle_key] = task

        try:
            handle = await task
        except Exception:
            self._inflight_connections.pop(handle_key, None)
            raise

        self._handles.setdefault(handle_key, handle)
        self._inflight_connections.pop(handle_key, None)

    async def _open_connection(
        self,
        device: Device,
        broker_key: str,
    ) -> ConnectionHandle:
        """Open and return one runtime connection handle."""
        connection = _select_connection(
            device=device,
            broker_key=broker_key,
        )
        credential = _resolve_credential(device, connection.credential)
        config = ConnectionConfig(
            device_name=device.name,
            host=connection.host,
            port=connection.port,
            os=device.os,
            credentials=credential,
            options=connection.options,
        )
        return await self._brokers[broker_key].connect(config)

    async def disconnect_targets(self) -> None:
        """Close any established target connections."""
        handles = list(self._handles.items())
        self._handles.clear()
        try:
            tasks = [
                asyncio.create_task(self._brokers[broker_key].disconnect(handle))
                for (_, broker_key), handle in handles
            ]
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    async def execute(
        self,
        target: Device,
        command: str,
        *,
        broker: BrokerType | str | None = None,
        use_cache: bool = True,
        bust_cache: bool = False,
    ) -> CommandResult:
        """Execute a command for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        cache_key = _build_cache_key(
            operation="execute",
            target=target,
            broker_key=broker_key,
            payload=command,
            kwargs={},
        )
        return await self._run_cached_operation(
            cache_key=cache_key,
            use_cache=use_cache,
            bust_cache=bust_cache,
            lock_key=(target.name, broker_key),
            operation=lambda: self._brokers[broker_key].execute(handle, command),
        )

    async def send_interactive(
        self,
        target: Device,
        interact_events: list[tuple[str, str]] | list[tuple[str, str, bool]],
        *,
        broker: BrokerType | str | None = None,
    ) -> CommandResult:
        """Execute an interactive command sequence on a target device.

        This bypasses the cache since interactive commands are inherently
        stateful and should never be cached.

        Args:
            target: The device to interact with.
            interact_events: List of (input, expected_prompt) or
                (input, expected_prompt, hidden) tuples.
            broker: Optional broker type override.

        Returns:
            The command result.
        """
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        broker_instance = self._brokers[broker_key]
        if not hasattr(broker_instance, "send_interactive"):
            raise RuntimeBrokerError(
                f"Broker '{broker_key}' does not support interactive commands"
            )
        send_interactive = cast(
            Callable[..., Awaitable[CommandResult]], broker_instance.send_interactive
        )
        lock = self._operation_locks.setdefault(
            (target.name, broker_key), asyncio.Lock()
        )
        async with lock:
            return await send_interactive(handle, interact_events)

    async def get(
        self,
        target: Device,
        path: str,
        *,
        broker: BrokerType | str | None = None,
        use_cache: bool = True,
        bust_cache: bool = False,
        **kwargs: object,
    ) -> CommandResult:
        """Run a GET-style operation for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        cache_key = _build_cache_key(
            operation="get",
            target=target,
            broker_key=broker_key,
            payload=path,
            kwargs=kwargs,
        )
        return await self._run_cached_operation(
            cache_key=cache_key,
            use_cache=use_cache,
            bust_cache=bust_cache,
            lock_key=(target.name, broker_key),
            operation=lambda: self._brokers[broker_key].get(handle, path, **kwargs),
        )

    async def edit(
        self,
        target: Device,
        config: str,
        *,
        broker: BrokerType | str | None = None,
        **kwargs: object,
    ) -> CommandResult:
        """Run an edit-style operation for a target device."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        handle = self._require_handle(target=target, broker_key=broker_key)
        return await self._run_operation(
            operation=lambda: self._brokers[broker_key].edit(handle, config, **kwargs),
            lock_key=(target.name, broker_key),
        )

    def clear_cache(self) -> None:
        """Clear all cached command responses for the active run."""
        self._command_cache.clear()

    def invalidate_execute_cache(
        self,
        *,
        target: Device,
        command: str,
        broker: BrokerType | str | None = None,
    ) -> None:
        """Invalidate one cached execute response for a target command."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        cache_key = _build_cache_key(
            operation="execute",
            target=target,
            broker_key=broker_key,
            payload=command,
            kwargs={},
        )
        self._command_cache.pop(cache_key, None)

    def invalidate_get_cache(
        self,
        *,
        target: Device,
        path: str,
        broker: BrokerType | str | None = None,
        **kwargs: object,
    ) -> None:
        """Invalidate one cached get response for a target/path/kwargs tuple."""
        broker_key = self._resolve_broker_key(target=target, broker=broker)
        cache_key = _build_cache_key(
            operation="get",
            target=target,
            broker_key=broker_key,
            payload=path,
            kwargs=kwargs,
        )
        self._command_cache.pop(cache_key, None)

    def for_protocol(
        self,
        protocol: str | ConnectionProtocol | BrokerType,
    ) -> RuntimeBrokerClient:
        """Return a protocol-pinned broker client for job use."""
        broker_key = normalize_broker_key(protocol)
        if broker_key not in self._brokers:
            raise RuntimeBrokerError(
                f"Broker '{broker_key}' was not planned for this run"
            )
        return RuntimeBrokerClient(_runtime_broker=self, _broker_key=broker_key)

    async def _get_with_pinned_broker(
        self,
        target: Device,
        path: str,
        *,
        broker: str,
        kwargs: dict[str, object],
    ) -> CommandResult:
        """Proxy get() for pinned clients while validating cache controls."""
        normalized_kwargs = dict(kwargs)
        use_cache = self._pop_bool_option(
            normalized_kwargs,
            "use_cache",
            default=True,
        )
        bust_cache = self._pop_bool_option(
            normalized_kwargs,
            "bust_cache",
            default=False,
        )
        return await self.get(
            target,
            path,
            broker=broker,
            use_cache=use_cache,
            bust_cache=bust_cache,
            **normalized_kwargs,
        )

    @staticmethod
    def _pop_bool_option(
        kwargs: dict[str, object],
        key: str,
        *,
        default: bool,
    ) -> bool:
        """Pop and validate boolean option from keyword arguments."""
        raw_value = kwargs.pop(key, default)
        if not isinstance(raw_value, bool):
            raise RuntimeBrokerError(f"'{key}' must be a boolean value")
        return raw_value

    async def _run_cached_operation(
        self,
        *,
        cache_key: _CacheKey,
        use_cache: bool,
        bust_cache: bool,
        lock_key: tuple[str, str],
        operation: _Operation,
    ) -> CommandResult:
        """Execute an operation with cache and single-flight semantics."""
        if bust_cache:
            self._command_cache.pop(cache_key, None)

        if not use_cache:
            return await self._run_operation(operation, lock_key=lock_key)

        cached = self._command_cache.get(cache_key)
        if cached is not None:
            return cached

        task = self._inflight_commands.get(cache_key)
        if task is None:
            task = asyncio.create_task(
                self._run_operation(operation, lock_key=lock_key)
            )
            self._inflight_commands[cache_key] = task

        try:
            result = await task
        except Exception:
            self._inflight_commands.pop(cache_key, None)
            raise

        self._command_cache[cache_key] = result
        self._inflight_commands.pop(cache_key, None)
        return result

    async def _run_operation(
        self,
        operation: _Operation,
        *,
        lock_key: tuple[str, str] | None = None,
    ) -> CommandResult:
        """Run one broker operation and normalize raised errors."""
        if lock_key is not None:
            return await self._run_locked_operation(
                lock_key=lock_key, operation=operation
            )

        return await self._run_unlocked_operation(operation)

    async def _run_locked_operation(
        self,
        *,
        lock_key: tuple[str, str],
        operation: _Operation,
    ) -> CommandResult:
        """Run one broker operation under per-device+broker lock."""
        lock = self._operation_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            return await self._run_unlocked_operation(operation)

    async def _run_unlocked_operation(self, operation: _Operation) -> CommandResult:
        """Run one broker operation and normalize raised errors."""
        try:
            return await operation()
        except Exception as error:  # noqa: BLE001
            raise RuntimeBrokerError(str(error)) from error

    def _resolve_broker_key(
        self,
        *,
        target: Device,
        broker: BrokerType | str | None,
    ) -> str:
        """Resolve broker key for an operation call."""
        available: list[str] = [
            broker_key
            for (device_name, broker_key) in self._handles
            if device_name == target.name
        ]
        if not available:
            raise RuntimeBrokerError(f"Device '{target.name}' is not connected")

        if broker is not None:
            requested = broker
            if requested not in available:
                raise RuntimeBrokerError(
                    f"Device '{target.name}' is not connected via '{requested}'"
                )
            return requested

        if len(available) == 1:
            return available[0]

        raise RuntimeBrokerError(
            f"Device '{target.name}' has multiple connected brokers "
            f"{sorted(available)}; "
            "specify broker explicitly"
        )

    def _require_handle(
        self,
        *,
        target: Device,
        broker_key: str,
    ) -> ConnectionHandle:
        """Get a connected handle for a target+broker pair."""
        handle = self._handles.get((target.name, broker_key))
        if handle is None:
            raise RuntimeBrokerError(
                f"Device '{target.name}' is not connected via '{broker_key}'"
            )
        return handle


def _build_brokers(
    *,
    required_brokers: set[str],
    registry: PluginRegistry | None,
    overrides: dict[str, ConnectionBrokerProtocolV1] | None,
) -> dict[str, ConnectionBrokerProtocolV1]:
    """Instantiate required broker implementations via registry or fallback."""
    if not required_brokers:
        raise RuntimeBrokerError("At least one broker must be required")

    normalized = {normalize_broker_key(b) for b in required_brokers}
    overrides = overrides or {}
    available: dict[str, ConnectionBrokerProtocolV1] = {}

    for broker_name in normalized:
        if broker_name in overrides:
            available[broker_name] = overrides[broker_name]
        elif registry is not None:
            available[broker_name] = registry.resolve_broker(broker_name)
        else:
            available[broker_name] = _fallback_instantiate(broker_name)

    return available


def _fallback_instantiate(broker_name: str) -> ConnectionBrokerProtocolV1:
    """Instantiate a built-in broker by name without the registry.

    Used when no PluginRegistry is provided (backward compat for tests).
    """
    fallback_map: dict[str, type[ConnectionBrokerProtocolV1]] = {
        BrokerType.SSH: SSHBroker,
        BrokerType.HTTP: HTTPBroker,
        BrokerType.NETCONF: NETCONFBroker,
    }
    cls = fallback_map.get(broker_name)
    if cls is None:
        raise RuntimeBrokerError(
            f"No built-in broker for '{broker_name}'. "
            "Provide a PluginRegistry to discover third-party brokers."
        )
    return cls()


def _merge_legacy_overrides(
    *,
    broker_overrides: dict[str, ConnectionBrokerProtocolV1] | None,
    ssh_broker: ConnectionBrokerProtocolV1 | None,
    http_broker: ConnectionBrokerProtocolV1 | None,
    netconf_broker: ConnectionBrokerProtocolV1 | None,
) -> dict[str, ConnectionBrokerProtocolV1] | None:
    """Merge deprecated named broker params into unified overrides dict."""
    merged: dict[str, ConnectionBrokerProtocolV1] = {}
    if broker_overrides:
        merged.update(broker_overrides)
    if ssh_broker is not None:
        merged[BrokerType.SSH] = ssh_broker
    if http_broker is not None:
        merged[BrokerType.HTTP] = http_broker
    if netconf_broker is not None:
        merged[BrokerType.NETCONF] = netconf_broker
    return merged or None


def _normalize_required_broker_strings(
    required_brokers: set[BrokerType] | set[str],
) -> set[str]:
    """Normalize and validate required broker identifiers to strings."""
    if not required_brokers:
        raise RuntimeBrokerError("At least one broker must be required")
    return {normalize_broker_key(broker) for broker in required_brokers}


def _select_connection(
    *,
    device: Device,
    broker_key: str,
) -> ConnectionDefinition:
    """Select connection definition matching the requested broker key."""
    protocol_preferences = _preferred_protocols_for_broker(broker_key)
    for protocol in protocol_preferences:
        for connection in device.connections.values():
            if connection.protocol == protocol:
                return connection
    raise RuntimeBrokerError(
        f"Device '{device.name}' has no connection for broker '{broker_key}'"
    )


def _preferred_protocols_for_broker(
    broker_key: str,
) -> tuple[ConnectionProtocol, ...]:
    """Return preferred connection protocol order for a broker key."""
    if broker_key == BrokerType.SSH:
        return (ConnectionProtocol.SSH,)
    if broker_key == BrokerType.HTTP:
        return (
            ConnectionProtocol.HTTPS,
            ConnectionProtocol.HTTP,
            ConnectionProtocol.REST,
        )
    if broker_key == BrokerType.NETCONF:
        return (ConnectionProtocol.NETCONF,)
    raise RuntimeBrokerError(f"Unsupported broker key '{broker_key}'")


def normalize_broker_key(
    protocol: str | ConnectionProtocol | BrokerType,
) -> str:
    """Normalize protocol/broker aliases into canonical broker keys.

    Built-in protocols are mapped to their canonical BrokerType string.
    Unknown protocols are passed through as-is to support third-party
    broker types discovered via the plugin registry.
    """
    if protocol in {BrokerType.SSH, ConnectionProtocol.SSH, "ssh"}:
        return BrokerType.SSH
    if protocol in {
        BrokerType.HTTP,
        ConnectionProtocol.HTTP,
        ConnectionProtocol.HTTPS,
        ConnectionProtocol.REST,
        "http",
        "https",
        "rest",
    }:
        return BrokerType.HTTP
    if protocol in {BrokerType.NETCONF, ConnectionProtocol.NETCONF, "netconf"}:
        return BrokerType.NETCONF
    return str(protocol)


def _resolve_credential(
    device: Device,
    credential_name: str | None,
) -> CredentialFields:
    """Resolve connection credential by name with default fallback."""
    resolved_name = credential_name or "default"
    if resolved_name not in device.credentials:
        raise RuntimeBrokerError(
            f"Device '{device.name}' is missing credential '{resolved_name}'"
        )
    return device.credentials[resolved_name]


def _build_cache_key(
    *,
    operation: _CacheOperation,
    target: Device,
    broker_key: str,
    payload: str,
    kwargs: dict[str, object],
) -> _CacheKey:
    """Build canonical cache key for an operation call."""
    normalized_kwargs = tuple(
        sorted((key, repr(value)) for key, value in kwargs.items())
    )
    return (operation, target.name, broker_key, payload, normalized_kwargs)
