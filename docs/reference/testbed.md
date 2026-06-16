# Testbed Specification

This document defines the YAML schema for Huginn testbed files. A testbed describes the infrastructure inventory - devices, their connection parameters, groupings, and metadata.

## Overview

The testbed file serves as the single source of truth for target infrastructure. It defines:

- **Devices**: Individual targets (network devices, servers, appliances)
- **Connections**: How to connect to each device (SSH, REST API, etc.)
- **Groups**: Logical groupings for targeting tests
- **Metadata**: Arbitrary key-value data for test logic

## Schema

### Top-Level Structure

```yaml
# testbed.yaml
---
name: <testbed-name>          # Optional: human-readable name
credentials:                   # Optional: shared credential definitions
  <credential-name>:
    username: <username>
    password: <password>
    # Additional auth fields as needed

devices:
  <device-name>:                # Device key serves as the identifier
    os: <operating-system>
    groups: [<group>, ...]      # Optional
    metadata: {}                # Optional
    connections:
      <connection-name>:
        # Connection-specific parameters
```

### Credentials

Credentials support a hierarchical resolution model, allowing global defaults with device-specific overrides.

#### Global Credentials

Define shared credentials at the top level:

```yaml
credentials:
  default:                           # Special: used when no credential specified
    username: admin
    password: ${DEFAULT_PASSWORD}

  tacacs:                            # Named credential
    username: tacacs_user
    password: ${TACACS_PASSWORD}

  api-readonly:
    username: api_reader
    token: ${API_TOKEN}
```

The `default` credential is special - it's used automatically when a connection doesn't specify a credential reference.

#### Device-Specific Credentials

Devices can define their own credentials that override or extend global credentials:

```yaml
devices:
  spine-01:
    os: nxos
    credentials:                     # Device-specific credentials
      ssh:
        username: spine_admin
        password: ${SPINE_PASSWORD}
      api:
        username: spine_api
        token: ${SPINE_API_TOKEN}
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.1
        credential: ssh              # → device.credentials.ssh
      rest:
        protocol: rest
        base_url: https://10.1.1.1
        credential: api              # → device.credentials.api
```

#### Credential Resolution

When a connection specifies `credential: <name>`, resolution follows this order:

1. **Device credentials**: Look for `device.credentials.<name>`
2. **Global credentials**: If not found, look for `credentials.<name>`

When a connection has no `credential` specified:

3. **Global default**: Use `credentials.default`

```yaml
credentials:
  default:
    username: admin
    password: ${DEFAULT_PASS}
  tacacs:
    username: tacacs_user
    password: ${TACACS_PASS}

devices:
  # Device with custom credentials
  spine-01:
    os: nxos
    credentials:
      tacacs:                        # Shadows global "tacacs"
        username: spine_tacacs
        password: ${SPINE_TACACS}
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.1
        credential: tacacs           # → device.credentials.tacacs (spine_tacacs)

  # Device using global credentials
  leaf-01:
    os: nxos
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.2
        credential: tacacs           # → credentials.tacacs (tacacs_user)

  # Device using default credentials
  leaf-02:
    os: nxos
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.3
        # No credential specified   → credentials.default (admin)
```

#### Credential Fields

**MVP Release**: Username and password authentication only.

```yaml
credentials:
  default:
    username: admin
    password: ${PASSWORD}

  tacacs:
    username: tacacs_user
    password: ${TACACS_PASSWORD}
```

| Field      | Type   | Required | Description             |
| ---------- | ------ | -------- | ----------------------- |
| `username` | string | Yes      | Authentication username |
| `password` | string | Yes      | Authentication password |

**Future Release**: Additional authentication mechanisms planned for future releases:

- **SSH key authentication**: `private_key`, `private_key_passphrase`
- **Token/API key authentication**: `token`
- **Certificate authentication**: `certificate`, `private_key`

### Device Definition

Each device is a key under `devices`. The key serves as the device identifier/name:

```yaml
devices:
  spine-01:                              # Device key = identifier
    os: nxos                             # Required: operating system identifier
    groups:                              # Optional: list of group memberships
      - spine
      - datacenter-1
      - fabric-core
    metadata:                            # Optional: arbitrary key-value data
      location: DC1-Row5-Rack12
      serial: FDO12345678
      role: spine
      vendor: cisco
    connections:
      ssh:                               # Connection name (arbitrary)
        # Connection parameters...
```

#### Required Fields

| Field | Type   | Description                                                                 |
| ----- | ------ | --------------------------------------------------------------------------- |
| `os`  | string | Operating system identifier (used for parser selection, OS-based targeting) |

#### Optional Fields

| Field         | Type         | Description                                  |
| ------------- | ------------ | -------------------------------------------- |
| `groups`      | list[string] | Group memberships for targeting              |
| `credentials` | dict         | Device-specific named credentials            |
| `metadata`    | dict         | Arbitrary key-value data accessible in tests |
| `connections` | dict         | Named connection configurations              |

### Connection Types

#### SSH Connection

For CLI-based interaction via scrapli:

```yaml
connections:
  ssh:
    protocol: ssh                    # Required
    host: 10.1.1.1                   # Required: IP or hostname
    port: 22                         # Optional: default 22
    credential: default              # Optional: reference to named credential
    # SSH-specific options:
    transport: asyncssh              # Optional: asyncssh (default), ssh2
    auth_strict_key: false           # Optional: host key verification
    timeout_socket: 30               # Optional: connection timeout
    timeout_ops: 60                  # Optional: operation timeout
```

If `credential` is omitted, `credentials.default` is used automatically.

#### REST API Connection

For HTTP/HTTPS API interaction via httpx:

```yaml
connections:
  rest:
    protocol: rest                   # Required
    base_url: https://10.1.1.1       # Required: API base URL
    port: 443                        # Optional: included in base_url typically
    credential: api-admin            # Optional: reference to named credential
    # REST-specific options:
    verify_ssl: false                # Optional: SSL verification
    timeout: 30                      # Optional: request timeout
    headers:                         # Optional: default headers
      Content-Type: application/json
      Accept: application/json
```

If `credential` is omitted, `credentials.default` is used automatically.

#### Multiple Connections

Devices can have multiple connection methods:

```yaml
devices:
  apic-01:
    os: aci
    credentials:
      api:                           # Device-specific API credential
        username: apic_admin
        password: ${APIC_PASSWORD}
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.10
        # No credential → uses credentials.default
      rest:
        protocol: rest
        base_url: https://10.1.1.10
        credential: api              # → device.credentials.api
        verify_ssl: false
```

Tests can specify which connection to use, or the framework can select a default.

### Groups

Groups enable logical organization for test targeting. A device can belong to multiple groups.

```yaml
devices:
  spine-01:
    os: nxos
    groups:
      - spine           # Role-based
      - datacenter-1    # Location-based
      - fabric-a        # Fabric membership
      - production      # Environment

  leaf-01:
    os: nxos
    groups:
      - leaf
      - datacenter-1
      - fabric-a
      - production
      - border          # Additional role

  leaf-02:
    os: nxos
    groups:
      - leaf
      - datacenter-1
      - fabric-a
      - production
```

Groups are arbitrary strings. Common patterns:

| Pattern       | Examples                              | Use Case                    |
| ------------- | ------------------------------------- | --------------------------- |
| Role          | `spine`, `leaf`, `border`, `firewall` | Target by function          |
| Location      | `datacenter-1`, `building-a`, `row-5` | Target by physical location |
| Environment   | `production`, `staging`, `lab`        | Target by environment       |
| Fabric/Domain | `fabric-a`, `vrf-red`, `zone-dmz`     | Target by logical domain    |

### Metadata

Arbitrary key-value data attached to devices. Accessible in tests for conditional logic.

```yaml
devices:
  server-01:
    os: linux
    metadata:
      vendor: dell
      model: PowerEdge R740
      serial: ABCD1234
      oob_ip: 192.168.1.101
      oob_type: idrac
      rack: DC1-R05-U20
      owner: network-team
      criticality: high
```

Metadata is not interpreted by the framework - it's passed through to tests.

## Complete Example

```yaml
# testbed.yaml
---
name: Production Datacenter 1

credentials:
  # Default credentials - used when no credential specified
  default:
    username: netadmin
    password: "${NETWORK_PASSWORD}"

  # Named credentials for specific use cases
  tacacs:
    username: tacacs_user
    password: "${TACACS_PASSWORD}"

  server-admin:
    username: root
    password: "${SERVER_PASSWORD}"

  api-readonly:
    username: api_reader
    token: "${API_TOKEN}"

devices:
  # Spine switches - use default credentials
  spine-01:
    os: nxos
    groups: [spine, datacenter-1, fabric-core]
    metadata:
      vendor: cisco
      model: N9K-C9336C-FX2
      serial: FDO23456789
    connections:
      ssh:
        protocol: ssh
        host: 10.1.0.1
        # No credential specified → uses credentials.default
        transport: asyncssh

  spine-02:
    os: nxos
    groups: [spine, datacenter-1, fabric-core]
    metadata:
      vendor: cisco
      model: N9K-C9336C-FX2
      serial: FDO23456790
    connections:
      ssh:
        protocol: ssh
        host: 10.1.0.2
        credential: tacacs            # → credentials.tacacs (global)

  # Leaf switches
  leaf-01:
    os: nxos
    groups: [leaf, datacenter-1, fabric-access, rack-01]
    metadata:
      vendor: cisco
      model: N9K-C93180YC-FX
      serial: FDO34567890
      vtep_ip: 10.255.0.1
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.1
        # No credential → uses credentials.default

  leaf-02:
    os: nxos
    groups: [leaf, datacenter-1, fabric-access, rack-02]
    metadata:
      vendor: cisco
      model: N9K-C93180YC-FX
      serial: FDO34567891
      vtep_ip: 10.255.0.2
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.2

  # Border leaf with device-specific credentials
  border-01:
    os: nxos
    groups: [leaf, border, datacenter-1, fabric-access]
    credentials:
      ssh:                            # Device-specific credential
        username: border_admin
        password: "${BORDER_PASSWORD}"
    metadata:
      vendor: cisco
      model: N9K-C9364C
      serial: FDO45678901
      vtep_ip: 10.255.0.10
    connections:
      ssh:
        protocol: ssh
        host: 10.1.2.1
        credential: ssh               # → device.credentials.ssh

  # ACI APIC (multiple connection types with different credentials)
  apic-01:
    os: aci
    groups: [apic, datacenter-1, management]
    credentials:
      api:                            # Device-specific API credential
        username: apic_admin
        password: "${APIC_PASSWORD}"
    metadata:
      vendor: cisco
      model: APIC-SERVER-M3
      cluster_id: 1
    connections:
      ssh:
        protocol: ssh
        host: 10.1.100.1
        # No credential → uses credentials.default
      rest:
        protocol: rest
        base_url: https://10.1.100.1
        credential: api               # → device.credentials.api
        verify_ssl: false

  # Server with out-of-band management
  server-01:
    os: linux
    groups: [server, datacenter-1, compute, rack-01]
    metadata:
      vendor: dell
      model: PowerEdge R750
      serial: SVT12345
      oob_type: idrac
    connections:
      ssh:
        protocol: ssh
        host: 10.2.1.1
        credential: server-admin      # → credentials.server-admin (global)
      oob:
        protocol: rest
        base_url: https://192.168.100.1
        credential: server-admin      # → credentials.server-admin (global)
        verify_ssl: false
```

## Environment Variable Substitution

Credentials can reference environment variables to avoid storing secrets in files:

```yaml
credentials:
  default:
    username: "${HUGINN_USERNAME}"
    password: "${HUGINN_PASSWORD}"
```

The framework expands `${VAR_NAME}` syntax at load time.

## Operating System Identifiers

The `os` field uses consistent identifiers for operating systems. Common values:

| Identifier | Platform          |
| ---------- | ----------------- |
| `iosxe`    | Cisco IOS-XE      |
| `nxos`     | Cisco NX-OS       |
| `iosxr`    | Cisco IOS-XR      |
| `aci`      | Cisco ACI         |
| `eos`      | Arista EOS        |
| `junos`    | Juniper Junos     |
| `panos`    | Palo Alto PAN-OS  |
| `fortios`  | Fortinet FortiOS  |
| `linux`    | Generic Linux     |
| `windows`  | Microsoft Windows |

These identifiers are used for:

- OS-based test targeting
- Parser selection (Muninn integration)
- Connection parameter defaults

## Validation

The framework validates testbed files on load:

- All devices have `os` defined
- Referenced credentials can be resolved (device-level or global)
- `credentials.default` exists if any connection omits `credential`
- Connection configurations are valid for their protocol
- No duplicate device keys

Invalid testbeds produce clear error messages indicating the problem location.

## Related Documents

- [Test Plan Specification](test-plan.md): How to target devices in tests
- [Test Authoring](context-api.md): Accessing testbed data in tests
- [Configuration](configuration.md): Default connection settings
