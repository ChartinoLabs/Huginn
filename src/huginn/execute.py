"""Ad-hoc command execution against testbed devices.

This module provides the SDK for executing commands on testbed devices
using Huginn's built-in brokers (SSH, HTTP, NETCONF). It is designed
to be imported directly by consumers such as tac-quicksilver, with a
thin CLI wrapper in ``cli.py``.

Typical SDK usage::

    from huginn.execute import ExecuteCommandSpec, execute_commands
    from huginn.loaders import load_testbed

    testbed = load_testbed(Path("testbed.yaml"))
    specs = [ExecuteCommandSpec(device="spine-01", command="show version")]
    results = await execute_commands(testbed=testbed, specs=specs)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from huginn.enums import BrokerType
from huginn.loaders import ConfigurationError
from huginn.models import Testbed
from huginn.output import Output
from huginn.runtime_broker import (
    RuntimeBroker,
    RuntimeBrokerError,
    normalize_broker_key,
)
from huginn.utils.commands import is_command_unsupported


@dataclass(frozen=True)
class ExecuteCommandSpec:
    """One command to execute against a testbed device.

    Attributes:
        device: Device name as it appears in the testbed.
        command: CLI command string or API path to execute.
        broker: Broker type to use (``ssh``, ``http``, or ``netconf``).
    """

    device: str
    command: str
    broker: str = "ssh"


@dataclass
class ExecuteCommandResult:
    """Result of executing one command.

    Attributes:
        device: Device name the command was executed against.
        command: The command string that was executed.
        broker: Broker type that was used.
        device_os: OS identifier from the testbed device definition.
        raw_output: Raw text output from the command.
        elapsed_ms: Execution time in milliseconds.
        error: Error message if the command failed, otherwise ``None``.
    """

    device: str
    command: str
    broker: str
    device_os: str | None = None
    raw_output: str | None = None
    elapsed_ms: float | None = None
    error: str | None = None


def load_command_specs(path: Path) -> list[ExecuteCommandSpec]:
    """Load batch command specifications from a YAML file.

    The file must contain a YAML list of mappings. Each mapping requires
    ``device`` and either ``command`` or ``path`` (an alias for HTTP/NETCONF
    ergonomics). The ``broker`` field is optional and defaults to ``ssh``.

    Args:
        path: Path to the YAML file.

    Returns:
        List of command specifications.

    Raises:
        ConfigurationError: If the file structure is invalid.
    """
    data = _read_command_specs_yaml(path)
    specs = [_parse_one_spec(idx, entry) for idx, entry in enumerate(data)]

    if not specs:
        raise ConfigurationError("Command specs file contains no entries")

    return specs


def _read_command_specs_yaml(path: Path) -> list[dict[str, object]]:
    """Read and validate the top-level structure of a command specs file."""
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as err:
        raise ConfigurationError(
            f"Failed to read command specs from {path}: {err}"
        ) from err

    if not isinstance(data, list):
        raise ConfigurationError(
            f"Command specs file must contain a YAML list, got {type(data).__name__}"
        )
    return data


def _parse_one_spec(
    idx: int,
    entry: object,
) -> ExecuteCommandSpec:
    """Parse and validate a single command spec entry."""
    if not isinstance(entry, dict):
        raise ConfigurationError(f"Command spec #{idx + 1} must be a mapping")

    fields = cast(dict[str, object], entry)
    device = fields.get("device")
    if not device or not isinstance(device, str):
        raise ConfigurationError(
            f"Command spec #{idx + 1} is missing required 'device' field"
        )

    command = fields.get("command") or fields.get("path")
    if not command or not isinstance(command, str):
        raise ConfigurationError(
            f"Command spec #{idx + 1} is missing required 'command' or 'path' field"
        )

    broker_raw = fields.get("broker", "ssh")
    if not isinstance(broker_raw, str):
        raise ConfigurationError(
            f"Command spec #{idx + 1} has invalid 'broker' field: expected string"
        )

    return ExecuteCommandSpec(device=device, command=command, broker=broker_raw)


async def execute_commands(
    *,
    testbed: Testbed,
    specs: list[ExecuteCommandSpec],
    output: Output | None = None,
) -> list[ExecuteCommandResult]:
    """Execute command specifications against testbed devices.

    This is the core SDK entry point. It connects to the required devices,
    executes each command using the appropriate broker, and returns results
    with raw output.

    Args:
        testbed: Loaded testbed containing device definitions.
        specs: List of command specifications to execute.
        output: Optional output handler for status messages. Pass ``None``
            for silent operation (SDK callers).

    Returns:
        List of results, one per spec, in the same order.

    Raises:
        ConfigurationError: If a spec references an unknown device or
            an unsupported broker type.
    """
    _validate_specs(testbed, specs)
    required_brokers = _compute_required_brokers(specs)
    unique_devices = _compute_unique_devices(testbed, specs)

    runtime_broker = RuntimeBroker(required_brokers=required_brokers)
    connected_devices: set[str] = set()

    try:
        connected_devices = await _connect_devices(
            runtime_broker=runtime_broker,
            testbed=testbed,
            device_names=[d.name for d in unique_devices],
            required_brokers=required_brokers,
            output=output,
        )

        results: list[ExecuteCommandResult] = []
        for spec in specs:
            result = await _execute_one(
                runtime_broker=runtime_broker,
                testbed=testbed,
                spec=spec,
                connected_devices=connected_devices,
                output=output,
            )
            results.append(result)

        return results
    finally:
        await runtime_broker.disconnect_targets()


def _validate_specs(
    testbed: Testbed,
    specs: list[ExecuteCommandSpec],
) -> None:
    """Validate that all specs reference known devices and broker types."""
    for spec in specs:
        if spec.device not in testbed.devices:
            available = sorted(testbed.devices.keys())
            bullet_list = "\n".join(f"  - {name}" for name in available)
            raise ConfigurationError(
                f"Device '{spec.device}' not found in testbed. "
                f"Available devices:\n{bullet_list}"
            )
        normalized = normalize_broker_key(spec.broker)
        if normalized not in {
            BrokerType.SSH,
            BrokerType.HTTP,
            BrokerType.NETCONF,
        }:
            raise ConfigurationError(
                f"Invalid broker '{spec.broker}' for device '{spec.device}': "
                f"unsupported broker type. "
                f"Supported: ssh, http, netconf"
            )


def _compute_required_brokers(
    specs: list[ExecuteCommandSpec],
) -> set[BrokerType]:
    """Determine the set of broker types needed across all specs."""
    return {BrokerType(normalize_broker_key(spec.broker)) for spec in specs}


def _compute_unique_devices(
    testbed: Testbed,
    specs: list[ExecuteCommandSpec],
) -> list[Any]:
    """Return the unique Device objects referenced by the specs."""
    seen: set[str] = set()
    devices = []
    for spec in specs:
        if spec.device not in seen:
            seen.add(spec.device)
            devices.append(testbed.devices[spec.device])
    return devices


async def _connect_devices(
    *,
    runtime_broker: RuntimeBroker,
    testbed: Testbed,
    device_names: list[str],
    required_brokers: set[BrokerType],
    output: Output | None,
) -> set[str]:
    """Connect to devices individually, tolerating per-device failures."""
    connected: set[str] = set()
    for name in device_names:
        device = testbed.devices[name]
        try:
            await runtime_broker.connect_targets([device], required_brokers)
            connected.add(name)
            if output:
                output.status(f"Connected to {name}")
        except RuntimeBrokerError as err:
            if output:
                output.warning(f"Failed to connect to {name}: {err}")
    return connected


async def _execute_one(
    *,
    runtime_broker: RuntimeBroker,
    testbed: Testbed,
    spec: ExecuteCommandSpec,
    connected_devices: set[str],
    output: Output | None,
) -> ExecuteCommandResult:
    """Execute a single command spec and return the result."""
    device = testbed.devices[spec.device]
    broker_key = normalize_broker_key(spec.broker)

    if spec.device not in connected_devices:
        return ExecuteCommandResult(
            device=spec.device,
            command=spec.command,
            broker=spec.broker,
            device_os=device.os,
            error=f"Device '{spec.device}' is not connected",
        )

    try:
        if broker_key == BrokerType.SSH:
            cmd_result = await runtime_broker.execute(
                device,
                spec.command,
                broker=broker_key,
                use_cache=False,
            )
        else:
            cmd_result = await runtime_broker.get(
                device,
                spec.command,
                broker=broker_key,
                use_cache=False,
            )

        if output:
            output.status(
                f"Executed on {spec.device} via {spec.broker}: {spec.command} "
                f"({cmd_result.elapsed_ms:.0f}ms)"
            )

        error_msg = None
        if broker_key == BrokerType.SSH and is_command_unsupported(
            cmd_result.output,
        ):
            error_msg = "Device rejected command as invalid or unsupported"
            if output:
                output.warning(f"Command rejected on {spec.device}: {spec.command}")

        return ExecuteCommandResult(
            device=spec.device,
            command=spec.command,
            broker=spec.broker,
            device_os=device.os,
            raw_output=cmd_result.output,
            elapsed_ms=cmd_result.elapsed_ms,
            error=error_msg,
        )
    except RuntimeBrokerError as err:
        if output:
            output.warning(f"Command failed on {spec.device}: {spec.command} — {err}")
        return ExecuteCommandResult(
            device=spec.device,
            command=spec.command,
            broker=spec.broker,
            device_os=device.os,
            error=str(err),
        )
