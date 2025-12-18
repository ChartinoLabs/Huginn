# Muninn: Parser Project Brief

This document provides a high-level overview of Muninn, a companion parser library for Huginn. This serves as a handoff document for separate development of the parser project.

## Naming

**Muninn** is named after Odin's second raven in Norse mythology. While Huginn ("thought") gathers information, Muninn ("memory") remembers and interprets. The parser library "remembers" how to parse CLI output into structured data.

## Motivation

### The Problem

Infrastructure test automation requires parsing unstructured CLI output into structured data. For example, converting:

```
Neighbor ID     Pri   State           Dead Time   Address         Interface
10.1.1.1          1   FULL/DR         00:00:38    192.168.1.1     Ethernet1/1
10.1.1.2          1   FULL/BDR        00:00:33    192.168.1.2     Ethernet1/2
```

Into:

```python
{
    "10.1.1.1": {
        "priority": 1,
        "state": "FULL/DR",
        "dead_time": "00:00:38",
        "address": "192.168.1.1",
        "interface": "Ethernet1/1"
    },
    "10.1.1.2": {
        "priority": 1,
        "state": "FULL/BDR",
        "dead_time": "00:00:33",
        "address": "192.168.1.2",
        "interface": "Ethernet1/2"
    }
}
```

### Existing Solutions and Their Limitations

#### Cisco Genie Parsers

**Pros:**

- Comprehensive coverage of Cisco platforms
- Well-tested, production-quality
- Consistent output schemas

**Cons:**

- Bundled with PyATS - cannot install parsers alone
- Requires creating mock PyATS device objects to use parsers
- Heavy import overhead (PyATS is slow to load)
- Not truly open source (compiled code)
- Poor type hints due to compilation

#### TextFSM / ntc-templates

**Pros:**

- Widely adopted
- Large template library

**Cons:**

- TextFSM is a separate DSL to learn
- Returns list-of-dictionaries pattern (not ideal for keyed lookups)
- Templates can be difficult to debug
- No schema definition or validation

#### TTP (Template Text Parser)

**Pros:**

- More Pythonic than TextFSM
- XML/YAML template definitions

**Cons:**

- Still a separate DSL
- Less community adoption
- Learning curve for template syntax

### The Gap

There is no parser library that:

- Is installable and usable independently (no framework dependency)
- Uses pure Python for parsing logic (no separate DSL)
- Provides validated, typed output schemas
- Has comprehensive test coverage
- Supports multiple vendors with consistent patterns

## Project Goals

### Primary Goals

- **Standalone Installation**: Muninn must be pip-installable without requiring Huginn or any test framework. Users should be able to:

```python
import muninn
result = muninn.parse("nxos", "show ip ospf neighbor", raw_output)
```

- **Pure Python Implementation**: Parsing logic implemented in Python using regular expressions. No external DSL or template language.
- **Schema Validation**: Each parser defines an output schema. Parsed output is validated against the schema to ensure consistency.
- **Comprehensive Testing**: Every parser has extensive test coverage with real-world output samples from actual devices.
- **Type Safety**: Full type annotations throughout. Parsed output types are well-defined and IDE-friendly.

### Secondary Goals

1. **Multi-Vendor Support**: Support major network operating systems:
   - Cisco: IOS-XE, NX-OS, IOS-XR, ACI
   - Arista: EOS
   - Juniper: Junos
   - Palo Alto: PAN-OS
   - Others as needed

2. **Extensibility**: Clear patterns for adding new parsers. Community contributions should be straightforward.

3. **Performance**: Fast parsing suitable for large-scale test execution. Avoid unnecessary overhead.

4. **Documentation**: Every parser documented with example input/output and schema definition.

## Design Principles

### Complete Decoupling from Huginn

Muninn has no knowledge of or dependency on Huginn. The interface is simple:

```python
def parse(os: str, command: str, output: str) -> dict:
    """Parse CLI output into structured data.

    Args:
        os: Operating system identifier (e.g., "nxos", "iosxe")
        command: The command that produced the output
        output: Raw CLI output string

    Returns:
        Parsed structured data

    Raises:
        ParserNotFoundError: No parser for os/command combination
        ParseError: Parser failed to parse output
    """
```

This simple interface means:

- Any Python project can use Muninn
- No framework concepts leak into the parser library
- Testing parsers is straightforward
- Huginn is just one possible consumer among many

### Parser Architecture (High-Level)

Each parser consists of:

1. **Parser Class**: Python class implementing parsing logic
2. **Schema Definition**: Expected output structure (likely Pydantic or TypedDict)
3. **Test Suite**: Unit tests with real device output samples

Parsers are organized by OS and command:

```txt
muninn/
├── parsers/
│   ├── nxos/
│   │   ├── show_ip_ospf_neighbor.py
│   │   ├── show_ip_route.py
│   │   └── ...
│   ├── iosxe/
│   │   ├── show_ip_ospf_neighbor.py
│   │   └── ...
│   └── ...
├── schemas/
│   ├── ospf.py
│   └── ...
└── registry.py  # Parser index/lookup
```

### Schema Consistency

Where possible, parsers for the same conceptual data (e.g., OSPF neighbors) should produce consistent schemas across operating systems. This enables writing OS-agnostic test logic:

```python
# Same schema regardless of device.os
ospf_data = muninn.parse(device.os, "show ip ospf neighbor", output)
for neighbor_id, neighbor in ospf_data.items():
    assert neighbor["state"].startswith("FULL")
```

## Scope Boundaries

### In Scope

- CLI output parsing for network devices
- Server/appliance CLI parsing where applicable
- Schema definitions and validation
- Parser registry and lookup
- Comprehensive test suites

### Out of Scope

- Device connectivity (Huginn's responsibility)
- Test execution logic (Huginn's responsibility)
- API response parsing (typically already JSON/structured)
- Configuration generation or templating

## Integration with Huginn

While decoupled, Muninn is designed for seamless Huginn integration:

```python
# In a Huginn test
import muninn

async def gather_state(self, context: Context) -> dict:
    state = {}
    for device in context.targets:
        output = await device.execute("show ip ospf neighbor")
        parsed = muninn.parse(device.os, "show ip ospf neighbor", output)
        state[device.name] = parsed
    return state
```

Huginn may provide convenience wrappers, but the underlying Muninn call remains simple and direct.

## Success Criteria

Muninn is successful when:

1. **Independence**: Users can `pip install muninn` and use it without any other dependencies
2. **Coverage**: Parsers exist for common commands across major platforms
3. **Reliability**: Parsers are well-tested and handle edge cases gracefully
4. **Usability**: API is simple, documentation is clear, types are helpful
5. **Performance**: Parsing is fast enough to not bottleneck test execution

## Next Steps

This brief provides context and goals. Detailed implementation decisions (specific schema design, parser base class implementation, test infrastructure, etc.) should be developed separately as part of the Muninn project.

Recommended initial focus:

1. Define the core API and parser interface
2. Implement parser registry and lookup
3. Create schema validation approach
4. Build first parsers (suggest: NX-OS OSPF, BGP, interface status)
5. Establish test patterns with real device output

## Related Documents

- [Huginn Overview](01-overview.md): How Huginn uses parsers
- [Test Authoring](05-test-authoring.md): Parser integration patterns
