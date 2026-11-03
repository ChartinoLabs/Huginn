"""Tests for the execute module (SDK + CLI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from huginn.brokers.protocol import (
    CommandResult,
    ConnectionBrokerProtocolV1,
    ConnectionConfig,
    ConnectionHandle,
    ConnectionState,
)
from huginn.cli import app
from huginn.enums import BrokerType, ConnectionProtocol
from huginn.execute import (
    ExecuteCommandResult,
    ExecuteCommandSpec,
    execute_commands,
    load_command_specs,
)
from huginn.loaders import ConfigurationError
from huginn.models import ConnectionDefinition, Device, Testbed
from huginn.output import Output
from huginn.runtime_broker import RuntimeBroker, RuntimeBrokerError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeBroker:
    broker_name: str
    connect_calls: int = 0
    disconnect_calls: int = 0
    execute_calls: int = 0
    get_calls: int = 0

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

    async def execute(
        self, handle: ConnectionHandle, command: str, **kwargs: object
    ) -> CommandResult:
        self.execute_calls += 1
        return CommandResult(output=f"output-of:{command}", elapsed_ms=42.0)

    async def get(
        self, handle: ConnectionHandle, path: str, **kwargs: object
    ) -> CommandResult:
        self.get_calls += 1
        return CommandResult(output=f"get-output-of:{path}", elapsed_ms=55.0)


@dataclass
class _FailingBroker(_FakeBroker):
    """Broker that raises RuntimeBrokerError on execute."""

    async def execute(
        self, handle: ConnectionHandle, command: str, **kwargs: object
    ) -> CommandResult:
        self.execute_calls += 1
        raise RuntimeBrokerError(f"execute failed: {command}")


@dataclass
class _RejectingBroker(_FakeBroker):
    """Broker that returns device-rejected output for any command."""

    async def execute(
        self, handle: ConnectionHandle, command: str, **kwargs: object
    ) -> CommandResult:
        self.execute_calls += 1
        return CommandResult(
            output="% Invalid input detected at '^' marker.",
            elapsed_ms=10.0,
        )


def _fake_broker(name: str) -> ConnectionBrokerProtocolV1:
    return cast(ConnectionBrokerProtocolV1, _FakeBroker(name))


def _failing_broker(name: str) -> ConnectionBrokerProtocolV1:
    return cast(ConnectionBrokerProtocolV1, _FailingBroker(name))


def _default_credentials() -> dict[str, dict[str, str]]:
    return {"default": {"username": "admin", "password": "admin"}}


def _make_device(
    name: str = "spine-01",
    os: str = "nxos",
    protocol: str = "ssh",
) -> Device:
    proto = ConnectionProtocol(protocol)
    port = 443 if protocol in {"http", "https", "rest"} else 22
    return Device(
        name=name,
        os=os,
        credentials=_default_credentials(),
        connections={
            protocol: ConnectionDefinition(
                name=protocol,
                protocol=proto,
                host="10.0.0.1",
                port=port,
                credential=None,
                options={},
            )
        },
    )


def _make_testbed(*devices: Device) -> Testbed:
    return Testbed(
        devices={d.name: d for d in devices},
        credentials=_default_credentials(),
    )


# ---------------------------------------------------------------------------
# load_command_specs tests
# ---------------------------------------------------------------------------


class TestLoadCommandSpecs:
    """Tests for loading batch command specification YAML files."""

    def test_single_entry_default_broker(self, tmp_path: Path) -> None:
        """Single entry with default broker resolves to ssh."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("- device: spine-01\n  command: show version\n")
        specs = load_command_specs(spec_file)

        assert len(specs) == 1
        assert specs[0].device == "spine-01"
        assert specs[0].command == "show version"
        assert specs[0].broker == "ssh"

    def test_multiple_entries_mixed_brokers(self, tmp_path: Path) -> None:
        """Multiple entries with explicit brokers."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text(
            "- device: spine-01\n"
            "  command: show version\n"
            "  broker: ssh\n"
            "- device: ctrl-01\n"
            "  command: /api/v1/status\n"
            "  broker: http\n"
        )
        specs = load_command_specs(spec_file)

        assert len(specs) == 2
        assert specs[0].broker == "ssh"
        assert specs[1].broker == "http"
        assert specs[1].command == "/api/v1/status"

    def test_path_alias_for_command(self, tmp_path: Path) -> None:
        """The 'path' key is accepted as an alias for 'command'."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text(
            "- device: ctrl-01\n  path: /api/v1/devices\n  broker: http\n"
        )
        specs = load_command_specs(spec_file)

        assert specs[0].command == "/api/v1/devices"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        """Missing 'device' key raises ConfigurationError."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("- command: show version\n")

        with pytest.raises(ConfigurationError, match="missing required 'device'"):
            load_command_specs(spec_file)

    def test_missing_command_and_path_raises(self, tmp_path: Path) -> None:
        """Missing both 'command' and 'path' raises ConfigurationError."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("- device: spine-01\n")

        with pytest.raises(
            ConfigurationError, match="missing required 'command' or 'path'"
        ):
            load_command_specs(spec_file)

    def test_non_list_yaml_raises(self, tmp_path: Path) -> None:
        """Non-list root raises ConfigurationError."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("device: spine-01\ncommand: show version\n")

        with pytest.raises(ConfigurationError, match="YAML list"):
            load_command_specs(spec_file)

    def test_empty_list_raises(self, tmp_path: Path) -> None:
        """Empty list raises ConfigurationError."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("[]\n")

        with pytest.raises(ConfigurationError, match="no entries"):
            load_command_specs(spec_file)

    @pytest.mark.parametrize(
        ("content", "match"),
        [
            pytest.param(
                "- device: r1\n  command: [bad\n",
                r"(?s)Failed to read command specs from .*commands\.yaml:.*line \d+",
                id="invalid-yaml",
            ),
            pytest.param(
                "device: r1\n",
                r"commands\.yaml must contain a YAML list, got dict",
                id="top-level-mapping",
            ),
            pytest.param(
                "",
                r"commands\.yaml must contain a YAML list, got null",
                id="empty-file",
            ),
            pytest.param(
                "[]\n",
                r"commands\.yaml contains no entries",
                id="empty-list",
            ),
            pytest.param(
                "- show version\n",
                r"#1 in .*commands\.yaml must be a mapping, got str",
                id="entry-not-mapping",
            ),
            pytest.param(
                "- device: r1\n  command: show version\n- command: show clock\n",
                r"#2 in .*commands\.yaml is missing required 'device' field",
                id="missing-device-second-entry",
            ),
            pytest.param(
                "- device: r1\n",
                r"#1 in .*commands\.yaml is missing required 'command' or 'path'",
                id="missing-command",
            ),
            pytest.param(
                "- device: 101\n  command: show version\n",
                r"#1 in .*commands\.yaml has invalid 'device' field: "
                r"expected string, got int",
                id="device-wrong-type",
            ),
            pytest.param(
                "- device: r1\n  command: 5\n",
                r"#1 in .*commands\.yaml has invalid 'command' field: "
                r"expected string, got int",
                id="command-wrong-type",
            ),
            pytest.param(
                "- device: r1\n  path: [a, b]\n",
                r"#1 in .*commands\.yaml has invalid 'path' field: "
                r"expected string, got list",
                id="path-wrong-type",
            ),
            pytest.param(
                "- device: ''\n  command: show version\n",
                r"#1 in .*commands\.yaml has empty 'device' field",
                id="device-empty",
            ),
            pytest.param(
                "- device: r1\n  command: show version\n  broker: 3\n",
                r"#1 in .*commands\.yaml has invalid 'broker' field: "
                r"expected string, got int",
                id="broker-wrong-type",
            ),
        ],
    )
    def test_malformed_file_names_file_and_location(
        self, tmp_path: Path, content: str, match: str
    ) -> None:
        """Each malformed file raises ConfigurationError naming file and field."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text(content)

        with pytest.raises(ConfigurationError, match=match):
            load_command_specs(spec_file)

    def test_empty_command_falls_back_to_path(self, tmp_path: Path) -> None:
        """An empty 'command' still falls back to 'path', as before."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text(
            "- device: ctrl-01\n  command: ''\n  path: /api/v1/status\n"
        )

        specs = load_command_specs(spec_file)

        assert specs[0].command == "/api/v1/status"


# ---------------------------------------------------------------------------
# execute_commands SDK tests
# ---------------------------------------------------------------------------


class TestExecuteCommands:
    """Tests for the core SDK execute_commands function."""

    @pytest.mark.asyncio
    async def test_ssh_dispatches_to_execute(self) -> None:
        """SSH broker specs dispatch to broker.execute()."""
        ssh = _FakeBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="spine-01", command="show version")]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert len(results) == 1
        assert results[0].raw_output == "output-of:show version"
        assert results[0].elapsed_ms == 42.0
        assert results[0].error is None
        assert results[0].device_os == "nxos"
        assert ssh.execute_calls == 1

    @pytest.mark.asyncio
    async def test_http_dispatches_to_get(self) -> None:
        """HTTP broker specs dispatch to broker.get()."""
        http = _FakeBroker("http")
        device = _make_device(name="ctrl-01", protocol="https")
        testbed = _make_testbed(device)
        specs = [
            ExecuteCommandSpec(
                device="ctrl-01", command="/api/v1/status", broker="http"
            )
        ]

        results = await _run_with_broker(testbed, specs, http_broker=http)

        assert results[0].raw_output == "get-output-of:/api/v1/status"
        assert http.get_calls == 1

    @pytest.mark.asyncio
    async def test_netconf_dispatches_to_get(self) -> None:
        """NETCONF broker specs dispatch to broker.get()."""
        netconf = _FakeBroker("netconf")
        device = _make_device(name="rtr-01", protocol="netconf")
        testbed = _make_testbed(device)
        specs = [
            ExecuteCommandSpec(
                device="rtr-01",
                command="<get><filter/></get>",
                broker="netconf",
            )
        ]

        results = await _run_with_broker(testbed, specs, netconf_broker=netconf)

        assert results[0].raw_output == "get-output-of:<get><filter/></get>"
        assert netconf.get_calls == 1

    @pytest.mark.asyncio
    async def test_unknown_device_raises(self) -> None:
        """Unknown device name raises ConfigurationError."""
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="no-such-device", command="show version")]

        with pytest.raises(ConfigurationError, match="not found in testbed"):
            await execute_commands(testbed=testbed, specs=specs)

    @pytest.mark.asyncio
    async def test_per_command_error_captured(self) -> None:
        """Broker errors on individual commands are captured, not raised."""
        ssh = _FailingBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="spine-01", command="bad-cmd")]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert len(results) == 1
        assert results[0].error is not None
        assert "execute failed" in results[0].error
        assert results[0].raw_output is None

    @pytest.mark.asyncio
    async def test_disconnect_called_on_success(self) -> None:
        """disconnect_targets is called after successful execution."""
        ssh = _FakeBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="spine-01", command="show version")]

        await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert ssh.disconnect_calls >= 1

    @pytest.mark.asyncio
    async def test_device_os_populated(self) -> None:
        """device_os is populated from the testbed device definition."""
        ssh = _FakeBroker("ssh")
        device = _make_device(name="leaf-01", os="iosxe")
        testbed = _make_testbed(device)
        specs = [ExecuteCommandSpec(device="leaf-01", command="show version")]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert results[0].device_os == "iosxe"

    @pytest.mark.asyncio
    async def test_output_none_works(self) -> None:
        """Passing output=None (silent SDK mode) does not raise."""
        ssh = _FakeBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="spine-01", command="show version")]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh, output=None)

        assert results[0].error is None

    @pytest.mark.asyncio
    async def test_invalid_broker_type_raises(self) -> None:
        """Invalid broker string raises ConfigurationError."""
        testbed = _make_testbed(_make_device())
        specs = [
            ExecuteCommandSpec(
                device="spine-01", command="show version", broker="invalid"
            )
        ]

        with pytest.raises(ConfigurationError, match="Invalid broker"):
            await execute_commands(testbed=testbed, specs=specs)

    @pytest.mark.asyncio
    async def test_invalid_command_detected_as_error(self) -> None:
        """SSH output containing device rejection markers sets result.error."""
        ssh = _RejectingBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [ExecuteCommandSpec(device="spine-01", command="show foobar")]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert len(results) == 1
        assert results[0].error is not None
        assert (
            "invalid" in results[0].error.lower()
            or "unsupported" in results[0].error.lower()
        )
        assert results[0].raw_output is not None

    @pytest.mark.asyncio
    async def test_unknown_device_error_lists_available(self) -> None:
        """Error for unknown device includes a bulleted list of available names."""
        testbed = _make_testbed(
            _make_device(name="TAC-R2"),
        )
        specs = [ExecuteCommandSpec(device="tac-r2", command="show version")]

        with pytest.raises(ConfigurationError, match="- TAC-R2"):
            await execute_commands(testbed=testbed, specs=specs)

    @pytest.mark.asyncio
    async def test_multiple_commands_same_device(self) -> None:
        """Multiple commands on the same device share one connection."""
        ssh = _FakeBroker("ssh")
        testbed = _make_testbed(_make_device())
        specs = [
            ExecuteCommandSpec(device="spine-01", command="show version"),
            ExecuteCommandSpec(device="spine-01", command="show ip route"),
        ]

        results = await _run_with_broker(testbed, specs, ssh_broker=ssh)

        assert len(results) == 2
        assert results[0].raw_output == "output-of:show version"
        assert results[1].raw_output == "output-of:show ip route"
        assert ssh.connect_calls == 1
        assert ssh.execute_calls == 2


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    """Tests for the execute CLI command."""

    def test_device_without_command_rejected(self) -> None:
        """--device without --command is rejected."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["execute", "-t", "/dev/null", "--device", "spine-01"],
        )
        assert result.exit_code != 0

    def test_command_without_device_rejected(self) -> None:
        """--command without --device is rejected."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["execute", "-t", "/dev/null", "--command", "show version"],
        )
        assert result.exit_code != 0

    def test_device_and_commands_mutually_exclusive(self, tmp_path: Path) -> None:
        """--device/--command and --commands together are rejected."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text("- device: spine-01\n  command: show version\n")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "execute",
                "-t",
                "/dev/null",
                "--device",
                "spine-01",
                "--command",
                "show version",
                "--commands",
                str(spec_file),
            ],
        )
        assert result.exit_code != 0

    def test_neither_device_nor_commands_rejected(self) -> None:
        """No --device and no --commands is rejected."""
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["execute", "-t", "/dev/null"],
        )
        assert result.exit_code != 0

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            pytest.param(
                "- device: r1\n  command: [bad\n",
                "Failed to read command specs from",
                id="invalid-yaml",
            ),
            pytest.param("device: r1\n", "must contain a YAML list", id="mapping"),
            pytest.param(
                "- device: r1\n", "missing required 'command'", id="missing-field"
            ),
            pytest.param(
                "- device: r1\n  command: 5\n",
                "invalid 'command' field",
                id="wrong-type",
            ),
        ],
    )
    def test_malformed_commands_file_is_clean_error(
        self, tmp_path: Path, content: str, expected: str
    ) -> None:
        """A malformed --commands file gives one ERROR line and exit 1."""
        spec_file = tmp_path / "commands.yaml"
        spec_file.write_text(content)

        result = CliRunner().invoke(
            app,
            ["execute", "-t", "/dev/null", "--commands", str(spec_file)],
        )

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        output = " ".join(result.output.split())
        assert "ERROR:" in output
        assert expected in output
        assert "commands.yaml" in output
        assert "Traceback" not in output


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _run_with_broker(
    testbed: Testbed,
    specs: list[ExecuteCommandSpec],
    *,
    ssh_broker: _FakeBroker | None = None,
    http_broker: _FakeBroker | None = None,
    netconf_broker: _FakeBroker | None = None,
    output: Output | None = None,
) -> list[ExecuteCommandResult]:
    """Run execute_commands with injected fake brokers.

    This patches RuntimeBroker construction to inject test brokers.
    """
    from unittest.mock import patch

    fake_ssh = cast(ConnectionBrokerProtocolV1, ssh_broker or _FakeBroker("ssh"))
    fake_http = cast(ConnectionBrokerProtocolV1, http_broker or _FakeBroker("http"))
    fake_netconf = cast(
        ConnectionBrokerProtocolV1, netconf_broker or _FakeBroker("netconf")
    )

    original_init = RuntimeBroker.__init__

    def patched_init(
        self: RuntimeBroker,
        *,
        required_brokers: set[BrokerType] | None = None,
        **kwargs: object,
    ) -> None:
        original_init(
            self,
            required_brokers=required_brokers,
            ssh_broker=fake_ssh,
            http_broker=fake_http,
            netconf_broker=fake_netconf,
        )

    with patch.object(RuntimeBroker, "__init__", patched_init):
        return await execute_commands(
            testbed=testbed,
            specs=specs,
            output=output,
        )
