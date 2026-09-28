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
        host: 10.1.1.1
        port: 443
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

A credential is a mapping of string fields. No field is required by the loader, and every value must be a string. Each broker reads only the fields it supports and ignores the rest:

```yaml
credentials:
  default:
    username: admin
    password: ${PASSWORD}

  ssh-key:
    username: automation
    private_key: /home/automation/.ssh/id_ed25519

  api-token:
    token: ${API_TOKEN}
    token_type: Bearer
```

| Field         | Brokers            | Description                                                    |
| ------------- | ------------------ | -------------------------------------------------------------- |
| `username`    | SSH, NETCONF, HTTP | Authentication username                                        |
| `password`    | SSH, NETCONF, HTTP | Authentication password                                        |
| `private_key` | SSH, NETCONF       | Path to a private key file for SSH key authentication          |
| `token`       | HTTP               | API token sent in the `Authorization` header                   |
| `token_type`  | HTTP               | Prefix for the `Authorization` header value. Default: `Bearer` |

The HTTP broker uses basic authentication when the credential has both `username` and `password`. Otherwise, if it has a `token`, it sends `Authorization: <token_type> <token>`. A credential with only `username` and `token` therefore authenticates with the token.

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

| Field | Type   | Description                                                                                  |
| ----- | ------ | -------------------------------------------------------------------------------------------- |
| `os`  | string | Operating system identifier (used for SSH/NETCONF platform selection and OS-based targeting) |

#### Optional Fields

| Field         | Type         | Description                                  |
| ------------- | ------------ | -------------------------------------------- |
| `groups`      | list[string] | Group memberships for targeting              |
| `credentials` | dict         | Device-specific named credentials            |
| `metadata`    | dict         | Arbitrary key-value data accessible in tests |
| `connections` | dict         | Named connection configurations              |

### Connection Types

Every connection accepts four common fields. Any other key is passed to the broker as a connection option.

| Field        | Type    | Required | Description                                                  |
| ------------ | ------- | -------- | ------------------------------------------------------------ |
| `protocol`   | string  | Yes      | One of `ssh`, `netconf`, `http`, `https`, or `rest`          |
| `host`       | string  | Yes      | IP address or hostname. Required for every protocol          |
| `port`       | integer | No       | Default: `22` for every protocol (see each connection below) |
| `credential` | string  | No       | Named credential reference. Default: `default`               |

The protocol selects the broker that uses the connection:

| Protocol                | Broker  | Library         |
| ----------------------- | ------- | --------------- |
| `ssh`                   | SSH     | scrapli         |
| `netconf`               | NETCONF | scrapli-netconf |
| `https`, `http`, `rest` | HTTP    | aiohttp         |

When a device has several HTTP connections, the framework prefers `https`, then `http`, then `rest`.

If `credential` is omitted, `credentials.default` is used automatically.

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
    auth_strict_key: false           # Optional: host key verification (scrapli default: true)
    timeout_socket: 30               # Optional: connection timeout
    timeout_ops: 60                  # Optional: operation timeout
```

Options are passed through to the scrapli driver as keyword arguments, so any scrapli driver argument is accepted. The broker uses the `asyncssh` transport. Overriding `transport` with a synchronous transport such as `ssh2` fails, because the broker uses scrapli's async driver.

#### NETCONF Connection

For NETCONF interaction via scrapli-netconf:

```yaml
connections:
  netconf:
    protocol: netconf                # Required
    host: 10.1.1.1                   # Required: IP or hostname
    port: 830                        # Optional: see below
    credential: default              # Optional: reference to named credential
    # NETCONF-specific options:
    auth_strict_key: false           # Optional: host key verification
    timeout_ops: 60                  # Optional: operation timeout
```

The loader defaults `port` to `22`, and the NETCONF broker replaces port `22` with `830`. As a result, NETCONF connects to port 830 whether `port` is omitted or set to `22`, and NETCONF over port 22 is not possible. As with SSH, options are passed through to the scrapli-netconf driver.

#### REST API Connection

For HTTP/HTTPS API interaction via aiohttp. The `http`, `https`, and `rest` protocols all use the HTTP broker and accept the same options:

```yaml
connections:
  rest:
    protocol: rest                   # Required
    host: 10.1.1.1                   # Required: IP or hostname
    port: 443                        # Optional: default 22, see below
    credential: api-admin            # Optional: reference to named credential
    # REST-specific options:
    scheme: https                    # Optional: default https
    verify_ssl: false                # Optional: SSL verification (default: true)
    timeout: 30                      # Optional: total request timeout (default: 30)
    timeout_connect: 10              # Optional: connect timeout (default: 10)
    headers:                         # Optional: extra default headers
      X-Request-Source: huginn
```

| Option            | Default | Description                                                               |
| ----------------- | ------- | ------------------------------------------------------------------------- |
| `base_url`        | (built) | Full base URL. When set, `scheme`, `host`, and `port` are not used for it |
| `scheme`          | `https` | URL scheme used to build the base URL. The protocol name does not set it  |
| `verify_ssl`      | `true`  | Verify the server TLS certificate                                         |
| `timeout`         | `30`    | Total request timeout in seconds                                          |
| `timeout_connect` | `10`    | Connection timeout in seconds                                             |
| `headers`         | (none)  | Headers merged over the defaults                                          |

Without `base_url`, the broker builds `<scheme>://<host>:<port>` and omits the port when it is 80 or 443. Because `port` defaults to `22`, a REST connection with neither `port` nor `base_url` targets `https://<host>:22`. Set `port` (for example `443`) or `base_url` on every HTTP connection. `host` is still required when `base_url` is set. A `base_url` that includes a path must end with `/`.

Requests send `Content-Type: application/json` and `Accept: application/json` by default. Entries in `headers` are added to or override these.

#### Multiple Connections

Devices can have multiple connection methods:

```yaml
devices:
  spine-01:
    os: nxos
    credentials:
      api:                           # Device-specific API credential
        username: nxapi_admin
        password: ${NXAPI_PASSWORD}
    connections:
      ssh:
        protocol: ssh
        host: 10.1.1.10
        # No credential → uses credentials.default
      netconf:
        protocol: netconf
        host: 10.1.1.10
        port: 830
      rest:
        protocol: https
        host: 10.1.1.10
        port: 443
        credential: api              # → device.credentials.api
        verify_ssl: false
```

Connection names are arbitrary. The framework picks a connection by broker, not by name: for each broker a test uses, it takes the first connection on the device whose protocol belongs to that broker. A device therefore uses at most one connection per broker.

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

  # ACI APIC (REST API only, device-specific credentials)
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
      rest:
        protocol: rest
        host: 10.1.100.1
        port: 443
        credential: api               # → device.credentials.api
        verify_ssl: false

  # Server managed through its out-of-band controller API
  server-01:
    os: linux
    groups: [server, datacenter-1, compute, rack-01]
    metadata:
      vendor: dell
      model: PowerEdge R750
      serial: SVT12345
      oob_type: idrac
    connections:
      oob:
        protocol: https
        host: 192.168.100.1
        port: 443
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

The loader accepts any non-empty string for `os`. The SSH and NETCONF brokers map it to a scrapli platform when they connect, and fail with `Unsupported OS` for any value they do not know:

| Identifier | Platform      | SSH | NETCONF |
| ---------- | ------------- | --- | ------- |
| `ios`      | Cisco IOS     | Yes | Yes     |
| `iosxe`    | Cisco IOS-XE  | Yes | Yes     |
| `nxos`     | Cisco NX-OS   | Yes | Yes     |
| `iosxr`    | Cisco IOS-XR  | Yes | Yes     |
| `eos`      | Arista EOS    | Yes | No      |
| `junos`    | Juniper Junos | Yes | Yes     |

`ios` and `iosxe` both map to scrapli's `cisco_iosxe` platform. The HTTP broker does not use `os`, so a device reached only over HTTP can use any identifier, such as `aci`.

The `os` value is also used for OS-based test targeting (`target.os` in the test plan) and is available to tests as `device.os`. It does not set any connection parameter defaults.

## Validation

Checks happen at three points.

### At load time

Commands that read a testbed, such as `huginn run`, `huginn validate`, and `huginn execute`, load it first and stop with a `ConfigurationError` naming the device or connection when:

- The file is not valid YAML, or its root is not a mapping
- `devices` is missing or empty
- A device does not define a non-empty `os`
- `groups` is present but is not a non-empty list of non-empty strings
- `credentials` (global or device) is not a mapping of names to mappings, or a credential field value is not a string
- A connection does not define `protocol` or `host`, or `protocol` is not one of `ssh`, `netconf`, `http`, `https`, or `rest`
- A connection `port` is not an integer, or `credential` is not a string

The loader does not check which options a connection sets, whether a named credential exists, or whether `os` is supported by a broker. Duplicate device keys are not detected: the YAML parser keeps the last entry.

### In huginn validate

`huginn validate` loads the testbed as above and then resolves each test case's targets against it. It reports an error for an unknown device named in `target.devices`, and a warning for a test case that matches no devices. It does not open connections, so it does not check credentials, `os` support, or reachability.

### At connect time

When a run opens a connection, it fails that device's connection if:

- The device has no connection for a broker a test requires
- The connection's `credential` (or `default`, when omitted) is not defined on the device or globally
- The SSH or NETCONF broker does not support the device's `os`
- An SSH or NETCONF connection option is not accepted by the scrapli driver (the HTTP broker ignores options it does not use)
- The device is unreachable or authentication fails

## Related Documents

- [Test Plan Specification](test-plan.md): How to target devices in tests
- [Context API](context-api.md): Accessing testbed data in tests
- [Configuration](configuration.md): Default connection settings
