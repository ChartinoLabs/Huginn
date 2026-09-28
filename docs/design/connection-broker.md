# Connection Broker Plugin Architecture

This document describes the plugin architecture for connection brokers in Huginn, enabling extensible device connectivity through well-defined protocols.

## Implementation Status

| Component                                                                                 | Status              |
| ----------------------------------------------------------------------------------------- | ------------------- |
| `ConnectionBrokerProtocolV1` protocol definition                                          | Implemented         |
| Data classes (`ConnectionHandle`, `CommandResult`, `ConnectionConfig`, `ConnectionState`) | Implemented         |
| Exception hierarchy (`BrokerError` and subclasses)                                        | Implemented         |
| In-tree SSH broker (Scrapli)                                                              | Implemented         |
| In-tree HTTP broker (aiohttp)                                                             | Implemented         |
| In-tree NETCONF broker (scrapli_netconf)                                                  | Implemented         |
| `RuntimeBroker` manager with caching and connection pooling                               | Implemented         |
| Capability declaration (`capabilities()`, `PROTOCOL_VERSION`)                             | Implemented         |
| Capability-aware routing in `RuntimeBroker`                                               | Not yet implemented |
| Configuration passthrough via `options` dict                                              | Implemented         |
| Entry point discovery (`huginn.brokers`) and `[tool.huginn.plugins] brokers` filter       | Implemented         |
| `[tool.huginn.brokers]` explicit broker configuration                                     | Not yet implemented |
| Conformance test suite (`huginn-broker-conformance`)                                      | Not yet implemented |
| Broker extraction to separate packages                                                    | Not yet implemented |

## Overview

Connection brokers are responsible for establishing and managing connections to devices, executing commands, and returning results. Rather than embedding specific connection libraries (Scrapli, Netmiko, ncclient, etc.) directly into the core framework, Huginn defines a **Connection Broker Protocol** that implementations must satisfy.

This architecture provides:

- **Flexibility**: Users choose connection libraries that fit their environment
- **Independent versioning**: Broker implementations can evolve separately from the core framework
- **Reduced core dependencies**: Core framework remains lean; users install only needed brokers
- **Community extensibility**: Third parties can create brokers without modifying core code

## Design Principles

1. **Protocol-first**: The contract between core and brokers is defined by Python protocols, not inheritance
2. **Async-native**: All broker operations are async to support concurrent device operations
3. **Capability-aware**: Brokers declare their capabilities (see [Capability Negotiation](#capability-negotiation) for how far the framework uses them today)
4. **Configuration passthrough**: Broker-specific options flow through without core interpretation
5. **Fail-fast validation**: Broker compatibility is verified at startup, not runtime

## Protocol Versioning

The broker protocol is versioned to maintain compatibility as the framework evolves.

### Version Scheme

Protocols use an integer major version suffix:

```python
ConnectionBrokerProtocolV1  # Initial stable protocol
ConnectionBrokerProtocolV2  # Future breaking changes
```

### Compatibility Rules

- **Major version changes**: Breaking changes to required methods or signatures
- **Minor additions**: New optional methods with default implementations
- **Patch fixes**: Documentation clarifications, no code changes

### Protocol Version Declaration

Brokers declare which protocol version they support via a class-level constant:

```python
class SSHBroker:
    """SSH connection broker using Scrapli."""

    PROTOCOL_VERSION: int = 1  # Supports ConnectionBrokerProtocolV1
```

## Broker Protocol Definition

### Core Protocol (V1)

```python
from typing import Protocol, runtime_checkable, Any
from dataclasses import dataclass, field
from enum import Enum


class ConnectionState(Enum):
    """Connection lifecycle states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectionHandle:
    """Opaque handle representing an active connection."""

    broker_id: str
    device_name: str
    connection_type: str
    state: ConnectionState
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    """Result of a command execution."""

    output: str  # Raw output string
    structured: dict[str, Any] | None = None  # Structured/parsed data
    elapsed_ms: float = 0.0  # Execution time in milliseconds
    cached: bool = False  # Whether result came from cache


@dataclass
class ConnectionConfig:
    """Connection configuration passed to broker."""

    device_name: str
    host: str
    port: int
    os: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ConnectionBrokerProtocolV1(Protocol):
    """Connection Broker Protocol V1.

    Defines the contract between Huginn core and connection broker
    implementations. All methods are async to support concurrent
    device operations.
    """

    # ─── Identity & Capabilities ──────────────────────────────────

    @property
    def name(self) -> str:
        """Human-readable broker name."""
        ...

    @property
    def connection_type(self) -> str:
        """Connection type this broker handles (e.g., 'ssh', 'netconf')."""
        ...

    def capabilities(self) -> set[str]:
        """Return set of capability identifiers this broker supports.

        Standard capabilities:
        - 'execute': Can execute CLI commands
        - 'configure': Can send configuration commands
        - 'get': Can perform GET operations (NETCONF/RESTCONF)
        - 'edit': Can perform edit-config operations
        - 'batch': Can batch multiple operations
        """
        ...

    # ─── Caching Support ──────────────────────────────────────────

    def cache_key(self, operation: str, **kwargs: Any) -> str | None:
        """Generate a cache key for an operation.

        Returns None for operations that should never be cached
        (e.g., configuration commands). RuntimeBroker does not call
        this method; see Caching below.
        """
        ...

    # ─── Connection Lifecycle ─────────────────────────────────────

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle: ...
    async def disconnect(self, handle: ConnectionHandle) -> None: ...
    async def is_alive(self, handle: ConnectionHandle) -> bool: ...
    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle: ...

    # ─── Operations ───────────────────────────────────────────────

    async def execute(
        self,
        handle: ConnectionHandle,
        command: str,
        **kwargs: Any,
    ) -> CommandResult:
        """Execute a command on the device."""
        ...

    async def configure(
        self,
        handle: ConnectionHandle,
        commands: list[str],
        **kwargs: Any,
    ) -> CommandResult:
        """Apply configuration commands to the device."""
        ...

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        **kwargs: Any,
    ) -> CommandResult:
        """Perform a GET operation (REST endpoint or NETCONF get)."""
        ...

    async def edit(
        self,
        handle: ConnectionHandle,
        config: str,
        **kwargs: Any,
    ) -> CommandResult:
        """Perform an edit operation (REST POST/PUT or NETCONF edit-config)."""
        ...
```

### Exception Hierarchy

Brokers must raise exceptions from a standardized hierarchy:

```python
class BrokerError(Exception):
    """Base exception for all broker errors."""


class ConnectionError(BrokerError): ...


class AuthenticationError(BrokerError): ...


class TimeoutError(BrokerError): ...


class NotConnectedError(BrokerError): ...


class InvalidHandleError(BrokerError): ...


class CommandError(BrokerError): ...


class ConfigurationError(BrokerError): ...


class OperationError(BrokerError): ...


class CapabilityError(BrokerError): ...
```

## In-Tree Broker Implementations

All brokers currently live in the core `huginn` package. This enables rapid iteration on the protocol without cross-package coordination.

### Included Brokers

| Broker          | Connection Type | Library         | Capabilities                  |
| --------------- | --------------- | --------------- | ----------------------------- |
| `SSHBroker`     | `ssh`           | Scrapli         | execute, configure, get, edit |
| `HTTPBroker`    | `http`          | aiohttp         | get, edit                     |
| `NETCONFBroker` | `netconf`       | scrapli_netconf | get, edit                     |

SSH broker's `get()` delegates to `execute()` and `edit()` delegates to `configure()`, so SSH devices can be accessed through the same `get`/`edit` interface as NETCONF and HTTP devices.

### Additional Methods Beyond Protocol

Some brokers provide methods beyond the protocol definition:

- **SSH**: `send_interactive()` for commands requiring interactive prompts (e.g., confirmation dialogs)
- **NETCONF**: `lock()`, `unlock()`, `commit()`, `discard_changes()` for advanced NETCONF datastore operations

`RuntimeBroker.send_interactive()` forwards to the SSH broker's `send_interactive()` after checking that the broker has one. The NETCONF datastore methods are not exposed through `RuntimeBroker`, so jobs using `context.broker` cannot call them.

### Module Structure

```
huginn/
├── brokers/
│   ├── __init__.py           # Protocol, data class, and exception exports
│   ├── protocol.py           # Protocol definition, data classes
│   ├── exceptions.py         # Exception hierarchy
│   ├── ssh.py                # SSHBroker (Scrapli)
│   ├── http.py               # HTTPBroker (aiohttp)
│   ├── netconf.py            # NETCONFBroker (scrapli_netconf)
│   └── null.py               # NullBroker (no-op, for testing)
```

## RuntimeBroker

The `RuntimeBroker` class is the framework's broker manager that coordinates all broker instances. Tests interact with it via `context.broker`.

### Responsibilities

- Instantiating broker instances through the plugin registry
- Connection pooling across all brokers
- Routing operations to the broker a device is connected through
- Command result caching
- Per-device operation locking for serial execution
- Single-flight semantics (concurrent identical requests share one execution)

### Key Interface

```python
class RuntimeBroker:
    async def connect_targets(
        self,
        targets: list[Device],
        required_brokers: set[BrokerType] | set[str],
    ) -> None:
        """Open one connection per target and required broker."""
        ...

    async def disconnect_targets(self) -> None:
        """Disconnect all active connections."""
        ...

    async def execute(
        self,
        target: Device,
        command: str,
        *,
        broker: BrokerType | str | None = None,
        use_cache: bool = True,
        bust_cache: bool = False,
    ) -> CommandResult:
        """Execute a command through the broker the target is connected to."""
        ...

    async def send_interactive(
        self,
        target: Device,
        interact_events: list[tuple[str, str]] | list[tuple[str, str, bool]],
        *,
        broker: BrokerType | str | None = None,
    ) -> CommandResult:
        """Run an interactive command sequence (never cached)."""
        ...

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
        """Perform a GET operation; extra kwargs go to the broker."""
        ...

    async def edit(
        self,
        target: Device,
        config: str,
        *,
        broker: BrokerType | str | None = None,
        **kwargs: object,
    ) -> CommandResult:
        """Perform an edit operation (never cached)."""
        ...

    def clear_cache(self) -> None:
        """Clear all cached results."""
        ...

    def invalidate_execute_cache(
        self,
        *,
        target: Device,
        command: str,
        broker: BrokerType | str | None = None,
    ) -> None:
        """Drop one cached execute result."""
        ...

    def invalidate_get_cache(
        self,
        *,
        target: Device,
        path: str,
        broker: BrokerType | str | None = None,
        **kwargs: object,
    ) -> None:
        """Drop one cached get result for a path and kwargs."""
        ...

    def for_protocol(
        self,
        protocol: str | ConnectionProtocol | BrokerType,
    ) -> RuntimeBrokerClient:
        """Return a client pinned to one broker (execute, get, edit)."""
        ...
```

When `broker` is omitted, `RuntimeBroker` uses the only broker the target is connected through. If the target is connected through more than one, the call raises `RuntimeBrokerError` and the job must pass `broker` or use `for_protocol()`.

### Caching

Caching is built directly into `RuntimeBroker` rather than a separate class. Cacheable operations are `execute` and `get`; `edit` is never cached since it's stateful.

Cache keys are tuples of `(operation, target_name, broker_type, payload, kwargs)`, built by `RuntimeBroker` itself. Every `execute` and `get` call is cached unless the caller passes `use_cache=False`; `bust_cache=True` replaces any cached entry. The broker's `cache_key()` method is not consulted.

When multiple concurrent requests target the same cache key, single-flight semantics ensure only one actual execution occurs; other callers wait for and share the result.

## Configuration Passthrough

Broker-specific options are passed through without core framework interpretation.

### Testbed Configuration

```yaml
# testbed.yaml
devices:
  spine-01:
    os: nxos
    credentials:
      default:
        username: admin
        password: admin
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.1
        port: 22
        # Any other key is a broker-specific option
        auth_strict_key: false
        timeout_ops: 60
      netconf:
        protocol: netconf
        host: 10.1.1.1
        port: 830
```

### Option Resolution

Every connection key other than `protocol`, `host`, `port`, and `credential` is collected into the broker's `ConnectionConfig.options` dict. The broker interprets them according to its underlying library's requirements. Do not nest options under an `options:` key: the loader would pass it through as a single option literally named `options`. See [Connection Types](../reference/testbed.md#connection-types) for the options each broker accepts.

## Capability Negotiation

Not all brokers support all operations. Each broker declares its capabilities, but the framework does not yet use the declaration.

### Capability Declaration

```python
class SSHBroker:
    def capabilities(self) -> set[str]:
        return {"execute", "configure", "get", "edit"}


class HTTPBroker:
    def capabilities(self) -> set[str]:
        return {"get", "edit"}


class NETCONFBroker:
    def capabilities(self) -> set[str]:
        return {"get", "edit"}
```

### Capability Checking

`RuntimeBroker` does not call `capabilities()` or check `PROTOCOL_VERSION` before invoking an operation. It routes each call to the broker the target is connected through, and a broker that doesn't support the operation raises `CapabilityError` itself (for example, `HTTPBroker.execute()` and `NETCONFBroker.configure()`). `RuntimeBroker` wraps the error in `RuntimeBrokerError`.

## Plugin Discovery

Brokers are discovered through the `huginn.brokers` entry point group. The in-tree brokers register themselves this way in Huginn's own `pyproject.toml`:

```toml
[project.entry-points."huginn.brokers"]
ssh = "huginn.brokers.ssh:SSHBroker"
http = "huginn.brokers.http:HTTPBroker"
netconf = "huginn.brokers.netconf:NETCONFBroker"
```

`PluginRegistry.resolve_broker()` loads the entry point whose name matches the broker type a run requires (`ssh`, `http`, or `netconf`) and instantiates it. An installed package that registers an entry point under one of those names is found the same way.

A project can restrict which discovered brokers are available with the `brokers` list under `[tool.huginn.plugins]`:

```toml
# pyproject.toml
[tool.huginn.plugins]
brokers = ["ssh", "netconf"]
```

Requiring a broker that is installed but not in the list fails with `Broker '<name>' is installed but not enabled in plugin configuration`. When the key is absent, every discovered broker is available. `huginn run` and `huginn relearn` resolve brokers this way; `huginn execute` instantiates the in-tree brokers directly and ignores both entry points and the filter.

## Future: Broker Configuration and Extraction

The following sections describe planned work for when brokers are extracted from the core framework into separate packages. None of this is currently implemented.

### Explicit Configuration

Users will be able to explicitly specify brokers in configuration:

```toml
# pyproject.toml
[tool.huginn.brokers]
ssh = "huginn-broker-scrapli:ssh"
netconf = "huginn-broker-ncclient"
https = "huginn-broker-httpx"
```

### Resolution Order

1. **Explicit configuration**: If `[tool.huginn.brokers]` specifies a broker for a connection type, use it
2. **Entry point discovery**: Otherwise, use the discovered broker registered for the connection type (current behavior)
3. **Built-in brokers**: Fall back to in-tree implementations (during transition period)

### Conformance Testing

A conformance test suite will validate broker implementations against the protocol specification:

```bash
pip install huginn-broker-conformance

# Test a broker package
huginn-broker-test huginn-broker-scrapli --type ssh
```

Test categories:

1. **Protocol compliance** - required attributes, method signatures, return types
2. **Capability honesty** - declared capabilities match implemented methods
3. **Exception compliance** - errors use the standard exception hierarchy
4. **Lifecycle correctness** - connect/disconnect/reconnect/is_alive behavior
5. **Concurrency safety** - multiple concurrent operations don't corrupt state

### Migration Path

**Phase 1: In-Tree (Current)**
All brokers live in the core `huginn` package. This enables rapid iteration on the protocol without cross-package coordination.

**Phase 2: Extraction Ready**

- Protocol is stable (no breaking changes for 6+ months)
- Conformance test suite is comprehensive
- At least one external broker exists and works

**Phase 3: Extraction**

1. Create external packages (e.g., `huginn-broker-scrapli`)
2. Add deprecation warnings to in-tree versions
3. Update documentation to recommend external packages

**Phase 4: Removal**

1. Remove deprecated in-tree implementations
2. Core `huginn` has no connection library dependencies

## Related Documents

- [Architecture](../design/architecture.md): Connection Broker's role in the system
- [Testbed Specification](../reference/testbed.md): Connection configuration in testbeds
- [Configuration](../reference/configuration.md): Project settings in pyproject.toml
