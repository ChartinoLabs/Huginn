# Connection Broker Plugin Architecture

This document describes the plugin architecture for connection brokers in Huginn, enabling extensible device connectivity through well-defined protocols.

## Overview

Connection brokers are responsible for establishing and managing connections to devices, executing commands, and returning results. Rather than embedding specific connection libraries (Scrapli, Netmiko, ncclient, etc.) directly into the core framework, Huginn defines a **Connection Broker Protocol** that implementations must satisfy.

This architecture provides:

- **Flexibility**: Users choose connection libraries that fit their environment
- **Independent versioning**: Broker implementations evolve separately from the core framework
- **Reduced core dependencies**: Core framework remains lean; users install only needed brokers
- **Community extensibility**: Third parties can create brokers without modifying core code

## Design Principles

1. **Protocol-first**: The contract between core and brokers is defined by Python protocols, not inheritance
2. **Async-native**: All broker operations are async to support concurrent device operations
3. **Capability-aware**: Brokers declare their capabilities; core adapts accordingly
4. **Configuration passthrough**: Broker-specific options flow through without core interpretation
5. **Fail-fast validation**: Broker compatibility is verified at startup, not runtime

## Protocol Versioning

The broker protocol is versioned to maintain compatibility as the framework evolves.

### Version Scheme

Protocols use semantic versioning with a major version suffix:

```python
ConnectionBrokerProtocol_v1  # Initial stable protocol
ConnectionBrokerProtocol_v2  # Future breaking changes
```

### Compatibility Rules

- **Major version changes**: Breaking changes to required methods or signatures
- **Minor additions**: New optional methods with default implementations
- **Patch fixes**: Documentation clarifications, no code changes

### Protocol Version Declaration

Brokers declare which protocol version(s) they support:

```python
class ScraплиSSHBroker:
    """SSH connection broker using Scrapli."""

    PROTOCOL_VERSION = "1"  # Supports ConnectionBrokerProtocol_v1

    # Alternative: support multiple versions
    PROTOCOL_VERSIONS = ["1", "2"]  # Supports v1 and v2
```

The framework validates protocol compatibility at broker registration:

```python
# Framework startup
broker = load_broker("huginn-broker-scrapli")
if not is_compatible(broker, required_version="1"):
    raise IncompatibleBrokerError(
        f"Broker {broker.name} supports protocol v{broker.PROTOCOL_VERSION}, "
        f"but framework requires v1"
    )
```

## Broker Protocol Definition

### Core Protocol (v1)

```python
from typing import Protocol, runtime_checkable, Any
from dataclasses import dataclass
from enum import Enum, auto


class ConnectionState(Enum):
    """Connection lifecycle states."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


@dataclass
class ConnectionHandle:
    """Opaque handle representing an active connection."""
    broker_id: str          # Broker instance identifier
    device_name: str        # Device this connection is for
    connection_type: str    # e.g., "ssh", "netconf", "https"
    state: ConnectionState
    metadata: dict[str, Any] = None  # Broker-specific metadata


@dataclass
class CommandResult:
    """
    Result of a command execution.

    For CLI commands (SSH):
        - output: Raw command output text
        - structured: Parsed data (if parser applied), or None

    For API/NETCONF operations:
        - output: Response as string (JSON string or XML string)
        - structured: Same response as parsed dict
        Both fields contain the same data in different formats for consistency.
    """
    output: str                      # Raw output string
    structured: dict[str, Any] = None  # Structured/parsed data
    elapsed_ms: int = 0              # Execution time in milliseconds
    cached: bool = False             # Whether result came from cache


@dataclass
class ConnectionConfig:
    """Connection configuration passed to broker."""
    device_name: str
    host: str
    port: int
    credentials: dict[str, str]      # username, password, token, etc.
    options: dict[str, Any]          # Broker-specific options (passthrough)


@runtime_checkable
class ConnectionBrokerProtocol_v1(Protocol):
    """
    Connection Broker Protocol v1

    Defines the contract between Huginn core and connection broker implementations.
    All methods are async to support concurrent device operations.
    """

    # ─────────────────────────────────────────────────────────────────
    # Identity & Capabilities
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Human-readable broker name (e.g., 'Scrapli SSH Broker')."""
        ...

    @property
    def connection_type(self) -> str:
        """
        Connection type this broker handles.

        Standard types: 'ssh', 'netconf', 'restconf', 'https', 'gnmi', 'snmp'
        Custom types are allowed for vendor-specific protocols.
        """
        ...

    def capabilities(self) -> set[str]:
        """
        Return set of capability identifiers this broker supports.

        Standard capabilities:
        - 'execute': Can execute CLI commands (required for SSH)
        - 'configure': Can enter configuration mode and apply config
        - 'get': Can perform GET operations (required for REST/NETCONF)
        - 'edit': Can perform edit/POST operations
        - 'subscribe': Can subscribe to streaming telemetry
        - 'batch': Can execute multiple commands atomically
        - 'rollback': Can rollback configuration changes

        Example:
            return {'execute', 'configure', 'batch'}
        """
        ...

    # ─────────────────────────────────────────────────────────────────
    # Caching Support
    # ─────────────────────────────────────────────────────────────────

    def cache_key(
        self,
        operation: str,
        target: str,
        params: dict[str, Any] | None = None
    ) -> str | None:
        """
        Generate a cache key for an operation.

        The broker controls cache key generation, enabling protocol-specific
        logic such as:
        - SSH: Use command string directly
        - NETCONF: Normalize XPath, handle namespace prefixes
        - REST: Canonicalize URL, strip non-significant query params

        Args:
            operation: Operation type ('execute', 'get', 'configure', etc.)
            target: Command string, URL path, or XPath depending on protocol
            params: Optional parameters (query params, filter options, etc.)

        Returns:
            Cache key string if operation is cacheable, None if it should
            never be cached (e.g., configuration commands, POST requests).

        Examples:
            # SSH broker
            cache_key('execute', 'show ip route', None)
            → 'show ip route'

            cache_key('configure', 'interface eth0', None)
            → None  # Configuration commands are never cached

            # NETCONF broker
            cache_key('get', '/interfaces/interface[name="eth0"]', None)
            → '/interfaces/interface[name="eth0"]'  # Normalized

            # REST broker
            cache_key('get', '/api/v1/interfaces', {'format': 'json'})
            → '/api/v1/interfaces'  # Query params stripped

            cache_key('edit', '/api/v1/config', None)
            → None  # POST/PUT/PATCH never cached
        """
        ...

    # ─────────────────────────────────────────────────────────────────
    # Connection Lifecycle
    # ─────────────────────────────────────────────────────────────────

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        """
        Establish a connection to a device.

        Args:
            config: Connection configuration including host, credentials, options

        Returns:
            ConnectionHandle representing the active connection

        Raises:
            ConnectionError: If connection cannot be established
            AuthenticationError: If authentication fails
            TimeoutError: If connection times out
        """
        ...

    async def disconnect(self, handle: ConnectionHandle) -> None:
        """
        Gracefully close a connection.

        Args:
            handle: Connection handle from connect()

        Raises:
            InvalidHandleError: If handle is invalid or already closed
        """
        ...

    async def is_alive(self, handle: ConnectionHandle) -> bool:
        """
        Check if a connection is still active.

        Args:
            handle: Connection handle to check

        Returns:
            True if connection is alive and usable, False otherwise
        """
        ...

    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle:
        """
        Reconnect a dropped connection.

        Args:
            handle: Original connection handle (may be in ERROR state)

        Returns:
            New ConnectionHandle for the reestablished connection

        Raises:
            ConnectionError: If reconnection fails
        """
        ...

    # ─────────────────────────────────────────────────────────────────
    # Command Execution (capability: 'execute')
    # ─────────────────────────────────────────────────────────────────

    async def execute(
        self,
        handle: ConnectionHandle,
        command: str,
        timeout: int | None = None
    ) -> CommandResult:
        """
        Execute a command on the device.

        Args:
            handle: Active connection handle
            command: Command string to execute
            timeout: Optional timeout in seconds (overrides default)

        Returns:
            CommandResult with output and optional structured data

        Raises:
            NotConnectedError: If handle is not connected
            CommandError: If command execution fails
            TimeoutError: If command times out
            CapabilityError: If broker doesn't support 'execute'
        """
        ...

    # ─────────────────────────────────────────────────────────────────
    # Configuration (capability: 'configure')
    # ─────────────────────────────────────────────────────────────────

    async def configure(
        self,
        handle: ConnectionHandle,
        commands: str | list[str],
        commit: bool = True
    ) -> CommandResult:
        """
        Apply configuration commands to the device.

        Args:
            handle: Active connection handle
            commands: Single command or list of configuration commands
            commit: Whether to commit changes (for platforms that support it)

        Returns:
            CommandResult with any output from configuration

        Raises:
            NotConnectedError: If handle is not connected
            ConfigurationError: If configuration fails
            CapabilityError: If broker doesn't support 'configure'
        """
        ...

    # ─────────────────────────────────────────────────────────────────
    # REST/NETCONF Operations (capabilities: 'get', 'edit')
    # ─────────────────────────────────────────────────────────────────

    async def get(
        self,
        handle: ConnectionHandle,
        path: str,
        params: dict[str, Any] | None = None
    ) -> CommandResult:
        """
        Perform a GET operation (REST endpoint or NETCONF get).

        Args:
            handle: Active connection handle
            path: Resource path (URL path for REST, XPath/filter for NETCONF)
            params: Optional query parameters or filter options

        Returns:
            CommandResult with structured data in 'structured' field

        Raises:
            NotConnectedError: If handle is not connected
            OperationError: If GET fails
            CapabilityError: If broker doesn't support 'get'
        """
        ...

    async def edit(
        self,
        handle: ConnectionHandle,
        path: str,
        data: dict[str, Any],
        method: str = "POST"
    ) -> CommandResult:
        """
        Perform an edit operation (REST POST/PUT/PATCH or NETCONF edit-config).

        Args:
            handle: Active connection handle
            path: Resource path
            data: Data to send
            method: HTTP method for REST ('POST', 'PUT', 'PATCH', 'DELETE')
                   Ignored for NETCONF (uses edit-config)

        Returns:
            CommandResult with response data

        Raises:
            NotConnectedError: If handle is not connected
            OperationError: If edit fails
            CapabilityError: If broker doesn't support 'edit'
        """
        ...
```

### Exception Hierarchy

Brokers must raise exceptions from a standardized hierarchy:

```python
class BrokerError(Exception):
    """Base exception for all broker errors."""
    pass


class ConnectionError(BrokerError):
    """Failed to establish or maintain connection."""
    pass


class AuthenticationError(ConnectionError):
    """Authentication failed."""
    pass


class TimeoutError(BrokerError):
    """Operation timed out."""
    pass


class NotConnectedError(BrokerError):
    """Operation attempted on disconnected handle."""
    pass


class InvalidHandleError(BrokerError):
    """Invalid or expired connection handle."""
    pass


class CommandError(BrokerError):
    """Command execution failed."""
    pass


class ConfigurationError(BrokerError):
    """Configuration operation failed."""
    pass


class OperationError(BrokerError):
    """Generic operation failure (GET/edit)."""
    pass


class CapabilityError(BrokerError):
    """Broker doesn't support requested capability."""
    pass
```

## Discovery Mechanism

Brokers are discovered through two complementary mechanisms:

### 1. Entry Points (Automatic Discovery)

Brokers register via Python entry points for automatic discovery:

```toml
# In broker package's pyproject.toml
[project.entry-points."huginn.brokers"]
scrapli-ssh = "huginn_broker_scrapli:SSHBroker"
scrapli-netconf = "huginn_broker_scrapli:NETCONFBroker"
```

The framework discovers all installed brokers at startup:

```python
from importlib.metadata import entry_points

def discover_brokers() -> dict[str, type]:
    """Discover all installed connection brokers."""
    brokers = {}
    eps = entry_points(group="huginn.brokers")
    for ep in eps:
        broker_class = ep.load()
        brokers[ep.name] = broker_class
    return brokers
```

### 2. Explicit Configuration (Override)

Users can explicitly specify brokers in configuration:

```toml
# pyproject.toml
[tool.huginn.brokers]
# Map connection types to specific broker implementations
ssh = "huginn-broker-scrapli:ssh"        # Use Scrapli for SSH
netconf = "huginn-broker-ncclient"        # Use ncclient for NETCONF
https = "huginn-broker-httpx"             # Use httpx for HTTPS

# Or use a single broker package for multiple types
# ssh = "huginn-broker-netmiko"           # Alternative: use Netmiko
```

### Resolution Order

1. **Explicit configuration**: If `[tool.huginn.brokers]` specifies a broker for a connection type, use it
2. **Entry point discovery**: Otherwise, use discovered broker that handles the connection type
3. **Built-in brokers**: Fall back to in-tree implementations (during initial development phase)

### Conflict Resolution

If multiple brokers claim the same connection type:

```python
# Multiple SSH brokers discovered
brokers = {
    'scrapli-ssh': ScrapliSSHBroker,      # connection_type = 'ssh'
    'netmiko-ssh': NetmikoSSHBroker,      # connection_type = 'ssh'
}
```

Resolution:

1. If explicitly configured, use configured broker
2. If not configured, log warning and use first discovered (alphabetically by entry point name)
3. User can resolve by adding explicit configuration

## Configuration Passthrough

Broker-specific options are passed through without core framework interpretation.

### Testbed Configuration

```yaml
# testbed.yaml
devices:
  spine-01:
    os: nxos
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.1
        port: 22
        credential: default
        # Broker-specific options (passed directly to broker)
        options:
          transport: asyncssh          # Scrapli-specific
          auth_strict_key: false       # Scrapli-specific
          transport_options:           # Scrapli-specific
            exclusive: true

      netconf:
        protocol: netconf
        host: 10.1.1.1
        port: 830
        credential: default
        options:
          hostkey_verify: false        # ncclient-specific
          device_params:               # ncclient-specific
            name: nexus
```

### Framework Configuration

Global broker defaults in `pyproject.toml`:

```toml
[tool.huginn.brokers.options.ssh]
# Default options for SSH brokers
transport = "asyncssh"
auth_strict_key = false
timeout_socket = 30
timeout_ops = 60

[tool.huginn.brokers.options.netconf]
# Default options for NETCONF brokers
hostkey_verify = false
timeout = 60

[tool.huginn.brokers.options.https]
# Default options for HTTPS brokers
verify_ssl = true
timeout = 30
```

### Option Resolution

Options are merged with this precedence (highest to lowest):

1. Device-level `options` in testbed
2. Global broker options in `pyproject.toml`
3. Broker's built-in defaults

```python
def resolve_options(
    device_options: dict,
    global_options: dict,
    broker_defaults: dict
) -> dict:
    """Merge options with proper precedence."""
    result = broker_defaults.copy()
    result.update(global_options)
    result.update(device_options)
    return result
```

## Capability Negotiation

Not all brokers support all operations. The framework adapts based on declared capabilities.

### Capability Declaration

```python
class ScrapliSSHBroker:
    def capabilities(self) -> set[str]:
        return {'execute', 'configure', 'batch'}


class HTTPXRESTBroker:
    def capabilities(self) -> set[str]:
        return {'get', 'edit'}


class NCClientNETCONFBroker:
    def capabilities(self) -> set[str]:
        return {'get', 'edit', 'configure', 'subscribe', 'rollback'}
```

### Capability Checking

The framework checks capabilities before invoking operations:

```python
async def execute_command(broker, handle, command):
    if 'execute' not in broker.capabilities():
        raise CapabilityError(
            f"Broker '{broker.name}' does not support 'execute'. "
            f"Available capabilities: {broker.capabilities()}"
        )
    return await broker.execute(handle, command)
```

### Graceful Degradation

For optional capabilities, the framework can degrade gracefully:

```python
async def apply_config(broker, handle, commands, with_rollback=True):
    if 'configure' not in broker.capabilities():
        raise CapabilityError("Broker doesn't support configuration")

    if with_rollback and 'rollback' not in broker.capabilities():
        logger.warning(
            f"Broker '{broker.name}' doesn't support rollback. "
            "Configuration will be applied without rollback capability."
        )
        with_rollback = False

    return await broker.configure(handle, commands, commit=True)
```

## In-Tree Broker Implementations

During the initial development phase, Huginn includes reference implementations for common protocols. These will be extracted to separate packages as the project matures.

### Included Brokers

| Broker | Connection Type | Library | Capabilities |
|--------|----------------|---------|--------------|
| `SSHBroker` | `ssh` | Scrapli | execute, configure, batch |
| `NETCONFBroker` | `netconf` | Scrapli (netconf) | get, edit, configure, rollback |
| `RESTCONFBroker` | `restconf` | httpx | get, edit |
| `HTTPSBroker` | `https` | httpx | get, edit |

### Module Structure

```
huginn/
├── brokers/
│   ├── __init__.py           # Broker registry and base classes
│   ├── protocol.py           # Protocol definitions (v1, exceptions)
│   ├── ssh.py                # SSHBroker implementation
│   ├── netconf.py            # NETCONFBroker implementation
│   ├── restconf.py           # RESTCONFBroker implementation
│   └── https.py              # HTTPSBroker implementation
```

### Future Extraction

When extracting to separate packages:

1. Create new package (e.g., `huginn-broker-scrapli`)
2. Move implementation code
3. Add entry point registration
4. Deprecate in-tree version with warning
5. Remove in-tree version after deprecation period

```python
# In-tree deprecation
import warnings

class SSHBroker:
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "Built-in SSHBroker is deprecated. "
            "Install 'huginn-broker-scrapli' instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(*args, **kwargs)
```

## Conformance Testing

A test suite validates broker implementations against the protocol specification.

### Test Package

```bash
pip install huginn-broker-conformance
```

### Running Conformance Tests

```bash
# Test a broker package
huginn-broker-test huginn-broker-scrapli

# Test with specific connection type
huginn-broker-test huginn-broker-scrapli --type ssh

# Test against mock device (no real device needed)
huginn-broker-test huginn-broker-scrapli --mock
```

### Test Categories

1. **Protocol Compliance**
   - Broker class has required attributes (`name`, `connection_type`, `PROTOCOL_VERSION`)
   - All required methods are implemented
   - Methods have correct signatures
   - Return types match protocol specification

2. **Capability Honesty**
   - Declared capabilities match implemented methods
   - Undeclared capabilities raise `CapabilityError`

3. **Exception Compliance**
   - Errors raise from the standard exception hierarchy
   - Exception messages are descriptive

4. **Lifecycle Correctness**
   - Connect returns valid handle
   - Disconnect is idempotent
   - Operations on disconnected handle raise `NotConnectedError`
   - `is_alive` correctly reflects connection state

5. **Concurrency Safety** (if applicable)
   - Multiple concurrent operations don't corrupt state
   - Connection handles are independent

### Example Conformance Test

```python
# huginn_broker_conformance/tests/test_protocol.py

import pytest
from huginn.brokers.protocol import ConnectionBrokerProtocol_v1

def test_broker_is_protocol_compliant(broker_class):
    """Verify broker implements the protocol."""
    assert isinstance(broker_class, type)
    assert issubclass(broker_class, ConnectionBrokerProtocol_v1) or \
           isinstance(broker_class(), ConnectionBrokerProtocol_v1)


def test_broker_declares_version(broker_class):
    """Verify broker declares protocol version."""
    assert hasattr(broker_class, 'PROTOCOL_VERSION')
    assert broker_class.PROTOCOL_VERSION in ("1", "2")


def test_capabilities_match_methods(broker_instance):
    """Verify declared capabilities have implementations."""
    caps = broker_instance.capabilities()

    if 'execute' in caps:
        assert hasattr(broker_instance, 'execute')
        assert callable(broker_instance.execute)

    if 'configure' in caps:
        assert hasattr(broker_instance, 'configure')
        assert callable(broker_instance.configure)

    # ... etc
```

## Integration with Connection Broker Manager

The core framework's `ConnectionBrokerManager` coordinates all broker instances.

### Manager Responsibilities

```python
class ConnectionBrokerManager:
    """
    Manages broker instances and routes operations to appropriate brokers.

    This is the component that tests interact with via context.broker.
    It handles:
    - Broker discovery and instantiation
    - Connection pooling across all brokers
    - Cache storage (brokers control cache keys via cache_key() method)
    - Routing operations to correct broker based on connection type
    """

    def __init__(self, config: FrameworkConfig):
        self.brokers: dict[str, ConnectionBrokerProtocol_v1] = {}
        self.connections: dict[tuple[str, str], ConnectionHandle] = {}  # (device, type) → handle
        self.cache: CommandCache = CommandCache()
        self._discover_and_register_brokers(config)

    async def connect_all(self, devices: list[Device]) -> ConnectionReport:
        """Connect to all devices using appropriate brokers."""
        ...

    async def execute(
        self,
        device: DeviceAdapter,
        command: str,
        connection_type: str = "ssh",
        use_cache: bool = True
    ) -> str:
        """Execute command through appropriate broker."""
        broker = self._get_broker(connection_type)
        handle = self._get_handle(device.name, connection_type)

        # Broker determines cache key (protocol-specific logic)
        cache_key = None
        if use_cache:
            cache_key = broker.cache_key("execute", command)
            if cache_key is not None:
                cached = self.cache.get(device.name, connection_type, cache_key)
                if cached is not None:
                    return cached

        result = await broker.execute(handle, command)

        # Store in cache if broker provided a cache key
        if cache_key is not None:
            self.cache.set(device.name, connection_type, cache_key, result.output)

        return result.output

    async def get(
        self,
        device: DeviceAdapter,
        path: str,
        connection_type: str = "https",
        params: dict | None = None,
        use_cache: bool = True
    ) -> dict:
        """Perform GET operation through appropriate broker."""
        broker = self._get_broker(connection_type)
        handle = self._get_handle(device.name, connection_type)

        # Broker determines cache key (may normalize path, strip params, etc.)
        cache_key = None
        if use_cache:
            cache_key = broker.cache_key("get", path, params)
            if cache_key is not None:
                cached = self.cache.get(device.name, connection_type, cache_key)
                if cached is not None:
                    return cached

        result = await broker.get(handle, path, params)

        if cache_key is not None:
            self.cache.set(device.name, connection_type, cache_key, result.structured)

        return result.structured
```

### Cache Storage

The manager owns the cache storage, keyed by `(device_name, connection_type, cache_key)`:

```python
class CommandCache:
    """
    Thread-safe cache storage for command/operation results.

    Cache keys are provided by brokers via their cache_key() method,
    enabling protocol-specific caching logic while keeping storage
    centralized in the manager.
    """

    def __init__(self):
        self._cache: dict[tuple[str, str, str], Any] = {}
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, device: str, conn_type: str, key: str) -> Any | None:
        """Retrieve cached value, or None if not cached."""
        return self._cache.get((device, conn_type, key))

    def set(self, device: str, conn_type: str, key: str, value: Any) -> None:
        """Store value in cache."""
        self._cache[(device, conn_type, key)] = value

    def clear(self, device: str | None = None, conn_type: str | None = None) -> None:
        """Clear cache entries. If device/conn_type specified, clear only matching."""
        if device is None and conn_type is None:
            self._cache.clear()
        else:
            keys_to_remove = [
                k for k in self._cache
                if (device is None or k[0] == device)
                and (conn_type is None or k[1] == conn_type)
            ]
            for k in keys_to_remove:
                del self._cache[k]

    def stats(self) -> dict:
        """Return cache statistics."""
        return {
            "entries": len(self._cache),
            "by_device": Counter(k[0] for k in self._cache),
            "by_type": Counter(k[1] for k in self._cache),
        }
```

### Broker Selection

```python
def _get_broker(self, connection_type: str) -> ConnectionBrokerProtocol_v1:
    """Get broker instance for connection type."""
    if connection_type not in self.brokers:
        raise ValueError(
            f"No broker registered for connection type '{connection_type}'. "
            f"Available types: {list(self.brokers.keys())}"
        )
    return self.brokers[connection_type]

def _get_handle(self, device_name: str, connection_type: str) -> ConnectionHandle:
    """Get connection handle for device and connection type."""
    key = (device_name, connection_type)
    if key not in self.connections:
        raise NotConnectedError(
            f"No {connection_type} connection to device '{device_name}'"
        )
    return self.connections[key]
```

## Complete Example

### Broker Implementation

```python
# huginn_broker_scrapli/ssh.py
"""Scrapli-based SSH connection broker."""

from scrapli import AsyncScrapli
from scrapli.exceptions import ScrapliAuthenticationFailed, ScrapliConnectionError

from huginn.brokers.protocol import (
    ConnectionBrokerProtocol_v1,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
    CommandResult,
    AuthenticationError,
    ConnectionError,
    CommandError,
    CapabilityError,
)


class SSHBroker:
    """SSH connection broker using Scrapli."""

    PROTOCOL_VERSION = "1"

    def __init__(self):
        self._connections: dict[str, AsyncScrapli] = {}

    @property
    def name(self) -> str:
        return "Scrapli SSH Broker"

    @property
    def connection_type(self) -> str:
        return "ssh"

    def capabilities(self) -> set[str]:
        return {"execute", "configure", "batch"}

    def cache_key(
        self,
        operation: str,
        target: str,
        params: dict | None = None
    ) -> str | None:
        # Configuration commands are never cached
        if operation == "configure":
            return None
        # For execute, use the command string directly
        if operation == "execute":
            return target
        # SSH doesn't support other operations
        return None

    async def connect(self, config: ConnectionConfig) -> ConnectionHandle:
        options = config.options or {}

        scrapli_config = {
            "host": config.host,
            "port": config.port,
            "auth_username": config.credentials.get("username"),
            "auth_password": config.credentials.get("password"),
            "auth_strict_key": options.get("auth_strict_key", False),
            "transport": options.get("transport", "asyncssh"),
            "timeout_socket": options.get("timeout_socket", 30),
            "timeout_ops": options.get("timeout_ops", 60),
        }

        # Platform-specific settings
        platform = options.get("platform", "cisco_nxos")

        try:
            conn = AsyncScrapli(platform=platform, **scrapli_config)
            await conn.open()
        except ScrapliAuthenticationFailed as e:
            raise AuthenticationError(f"Authentication failed: {e}") from e
        except ScrapliConnectionError as e:
            raise ConnectionError(f"Connection failed: {e}") from e

        handle = ConnectionHandle(
            broker_id=id(self),
            device_name=config.device_name,
            connection_type="ssh",
            state=ConnectionState.CONNECTED,
            metadata={"platform": platform},
        )

        self._connections[config.device_name] = conn
        return handle

    async def disconnect(self, handle: ConnectionHandle) -> None:
        conn = self._connections.pop(handle.device_name, None)
        if conn:
            await conn.close()
        handle.state = ConnectionState.DISCONNECTED

    async def is_alive(self, handle: ConnectionHandle) -> bool:
        conn = self._connections.get(handle.device_name)
        if not conn:
            return False
        return conn.isalive()

    async def reconnect(self, handle: ConnectionHandle) -> ConnectionHandle:
        conn = self._connections.get(handle.device_name)
        if conn:
            await conn.close()
            await conn.open()
            handle.state = ConnectionState.CONNECTED
        return handle

    async def execute(
        self,
        handle: ConnectionHandle,
        command: str,
        timeout: int | None = None
    ) -> CommandResult:
        if "execute" not in self.capabilities():
            raise CapabilityError("SSH broker doesn't support execute")

        conn = self._connections.get(handle.device_name)
        if not conn or not conn.isalive():
            raise NotConnectedError(f"Not connected to {handle.device_name}")

        import time
        start = time.perf_counter()

        try:
            result = await conn.send_command(command, timeout_ops=timeout)
        except Exception as e:
            raise CommandError(f"Command failed: {e}") from e

        elapsed = int((time.perf_counter() - start) * 1000)

        return CommandResult(
            output=result.result,
            elapsed_ms=elapsed,
            cached=False,
        )

    async def configure(
        self,
        handle: ConnectionHandle,
        commands: str | list[str],
        commit: bool = True
    ) -> CommandResult:
        if "configure" not in self.capabilities():
            raise CapabilityError("SSH broker doesn't support configure")

        conn = self._connections.get(handle.device_name)
        if not conn or not conn.isalive():
            raise NotConnectedError(f"Not connected to {handle.device_name}")

        if isinstance(commands, str):
            commands = [commands]

        try:
            result = await conn.send_configs(commands)
        except Exception as e:
            raise ConfigurationError(f"Configuration failed: {e}") from e

        return CommandResult(output=result.result)

    # GET and edit not supported for SSH - raise CapabilityError
    async def get(self, handle, path, params=None):
        raise CapabilityError("SSH broker doesn't support GET operations")

    async def edit(self, handle, path, data, method="POST"):
        raise CapabilityError("SSH broker doesn't support edit operations")
```

### Package Configuration

```toml
# huginn-broker-scrapli/pyproject.toml
[project]
name = "huginn-broker-scrapli"
version = "1.0.0"
description = "Scrapli-based connection brokers for Huginn"
requires-python = ">=3.11"
dependencies = [
    "huginn>=1.0.0",
    "scrapli[asyncssh]>=2024.1.0",
]

[project.entry-points."huginn.brokers"]
scrapli-ssh = "huginn_broker_scrapli:SSHBroker"
scrapli-netconf = "huginn_broker_scrapli:NETCONFBroker"

[project.optional-dependencies]
dev = [
    "huginn-broker-conformance",
    "pytest",
    "pytest-asyncio",
]
```

## Migration Path

### Phase 1: In-Tree (Current)

All brokers live in the core `huginn` package. This enables rapid iteration on the protocol without cross-package coordination.

### Phase 2: Extraction Ready

- Protocol is stable (no breaking changes for 6+ months)
- Conformance test suite is comprehensive
- At least one external broker exists and works

### Phase 3: Extraction

1. Create `huginn-broker-scrapli` package with in-tree implementations
2. Add deprecation warnings to in-tree versions
3. Update documentation to recommend external packages
4. Core `huginn` adds external brokers as optional dependencies

### Phase 4: Removal

1. Remove deprecated in-tree implementations
2. External broker packages are the only option
3. Core `huginn` has no connection library dependencies

## Related Documents

- [Architecture](02-architecture.md): Connection Broker's role in the system
- [Testbed Specification](03-testbed-spec.md): Connection configuration in testbeds
- [Configuration](06-configuration.md): Broker configuration in pyproject.toml
- [Future Considerations](99-future-considerations.md): Long-term evolution
