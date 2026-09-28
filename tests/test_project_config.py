"""Tests for project defaults loaded from ``[tool.huginn]`` in pyproject.toml."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from huginn import cli
from huginn.cli import app
from huginn.loaders import ConfigurationError
from huginn.project_config import ProjectConfig, load_project_config
from huginn.relearn import RelearnInput

_ENV_VARS = (
    "HUGINN_PLAN",
    "HUGINN_TESTBED",
    "HUGINN_INVENTORY_PLUGIN",
    "HUGINN_PARAMETERS_DIR",
    "HUGINN_RESULTS_DIR",
    "HUGINN_OUTPUT_DIR",
    "HUGINN_LOG_FILE",
    "HUGINN_LOG_LEVEL",
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a project directory with a plan, testbed and no HUGINN_* env."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "plans").mkdir()
    (tmp_path / "inventory").mkdir()
    (tmp_path / "inventory" / "lab.yaml").write_text("devices: {}\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_pyproject(project_root: Path, body: str) -> None:
    (project_root / "pyproject.toml").write_text(body, encoding="utf-8")


_FULL_PYPROJECT = """
[tool.huginn]
test_plan = "plans"
testbed = "inventory/lab.yaml"
parameters_dir = "state/parameters"
results_dir = "state/results"
output_dir = "state/artifacts"
log_file = "logs/huginn.log"
log_level = "warning"
"""


# ---------------------------------------------------------------------------
# load_project_config
# ---------------------------------------------------------------------------


def test_load_project_config_without_pyproject_is_empty(tmp_path: Path) -> None:
    """No pyproject.toml yields an empty configuration."""
    assert load_project_config(tmp_path) == ProjectConfig()


def test_load_project_config_without_huginn_table_is_empty(tmp_path: Path) -> None:
    """A pyproject.toml without [tool.huginn] yields an empty configuration."""
    _write_pyproject(tmp_path, '[project]\nname = "demo"\n')
    assert load_project_config(tmp_path) == ProjectConfig()


def test_load_project_config_resolves_relative_paths(tmp_path: Path) -> None:
    """Relative paths resolve against the directory holding pyproject.toml."""
    _write_pyproject(tmp_path, _FULL_PYPROJECT)

    config = load_project_config(tmp_path)

    assert config.test_plan == tmp_path / "plans"
    assert config.testbed == tmp_path / "inventory" / "lab.yaml"
    assert config.parameters_dir == tmp_path / "state" / "parameters"
    assert config.results_dir == tmp_path / "state" / "results"
    assert config.output_dir == tmp_path / "state" / "artifacts"
    assert config.log_file == tmp_path / "logs" / "huginn.log"
    assert config.log_level == "WARNING"


def test_load_project_config_keeps_absolute_paths(tmp_path: Path) -> None:
    """Absolute paths are used as given."""
    absolute = tmp_path / "elsewhere" / "results"
    _write_pyproject(tmp_path, f'[tool.huginn]\nresults_dir = "{absolute}"\n')

    assert load_project_config(tmp_path).results_dir == absolute


def test_load_project_config_reads_plugins_table(tmp_path: Path) -> None:
    """The [tool.huginn.plugins] sub-table is allowed and parsed."""
    _write_pyproject(
        tmp_path,
        """
[tool.huginn]
log_level = "DEBUG"

[tool.huginn.plugins]
brokers = ["ssh"]
reporters = []

[tool.huginn.plugins.config.html]
title = "Lab"
""",
    )

    config = load_project_config(tmp_path)

    assert config.log_level == "DEBUG"
    assert config.plugins.brokers == ["ssh"]
    assert config.plugins.reporters == []
    assert config.plugins.hooks is None
    assert config.plugins.plugin_options == {"html": {"title": "Lab"}}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('mode = "learning"', "Unknown key(s) in [tool.huginn]: mode"),
        ("parallel_tests = true", "Unknown key(s) in [tool.huginn]: parallel_tests"),
        ("test_plan = 5", "'test_plan' must be a non-empty string"),
        ('results_dir = ["results"]', "'results_dir' must be a non-empty string"),
        ('log_file = ""', "'log_file' must be a non-empty string"),
        ("inventory_plugin = true", "'inventory_plugin' must be a non-empty string"),
        ("log_level = 10", "'log_level' must be a non-empty string"),
        ('log_level = "verbose"', "'log_level' must be one of DEBUG, INFO"),
        ('plugins = "all"', "[tool.huginn.plugins] must be a table"),
        (
            'testbed = "testbed.yaml"\ninventory_plugin = "huginn-netbox"',
            "'testbed' and 'inventory_plugin' are mutually exclusive",
        ),
    ],
)
def test_load_project_config_rejects_invalid_tables(
    tmp_path: Path, body: str, message: str
) -> None:
    """Unknown keys, wrong types and conflicting keys raise ConfigurationError."""
    _write_pyproject(tmp_path, f"[tool.huginn]\n{body}\n")

    with pytest.raises(ConfigurationError) as excinfo:
        load_project_config(tmp_path)

    assert message in str(excinfo.value)


def test_load_project_config_rejects_invalid_toml(tmp_path: Path) -> None:
    """A malformed pyproject.toml is reported as a ConfigurationError."""
    _write_pyproject(tmp_path, "[tool.huginn\n")

    with pytest.raises(ConfigurationError, match="Invalid"):
        load_project_config(tmp_path)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


class _CapturedError(Exception):
    """Stops a command once the patched call has recorded its arguments."""


def _capture(monkeypatch: pytest.MonkeyPatch, target: str) -> dict[str, Any]:
    """Patch ``huginn.cli.<target>`` to record its kwargs and stop the command."""
    captured: dict[str, Any] = {}

    def _fake(*args: object, **kwargs: object) -> None:
        captured["args"] = args
        captured.update(kwargs)
        raise _CapturedError

    monkeypatch.setattr(cli, target, _fake)
    return captured


def _capture_async(monkeypatch: pytest.MonkeyPatch, target: str) -> dict[str, Any]:
    """Patch an async ``huginn.cli.<target>`` to record its kwargs and stop."""
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: object) -> None:
        captured.update(kwargs)
        raise _CapturedError

    monkeypatch.setattr(cli, target, _fake)
    return captured


def _invoke(args: list[str], env: dict[str, str] | None = None) -> Any:  # noqa: ANN401
    """Invoke the CLI and return the result."""
    return CliRunner().invoke(app, args, env=env)


def _assert_captured(result: Any) -> None:  # noqa: ANN401
    """Assert that the command reached the patched call."""
    assert isinstance(result.exception, _CapturedError), result.output


def test_run_uses_project_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run takes plan, testbed and every directory from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture_async(monkeypatch, "run_test_plan")

    _assert_captured(_invoke(["run", "--mode", "testing"]))

    assert captured["plan_path"] == project / "plans"
    assert captured["testbed_path"] == project / "inventory" / "lab.yaml"
    assert captured["inventory_plugin"] is None
    assert captured["parameters_dir"] == project / "state" / "parameters"
    assert captured["results_dir"] == project / "state" / "results"
    assert captured["output_dir"] == project / "state" / "artifacts"


def test_validate_uses_project_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate takes plan and testbed from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture_async(monkeypatch, "validate_inputs")

    _assert_captured(_invoke(["validate"]))

    assert captured["plan_path"] == project / "plans"
    assert captured["testbed_path"] == project / "inventory" / "lab.yaml"


def test_relearn_uses_project_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relearn takes plan, testbed and every directory from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    resolved: dict[str, Any] = {}

    def _fake_targets(results_dir: Path, *_args: object) -> RelearnInput:
        resolved["results_dir"] = results_dir
        return RelearnInput(test_ids=["t1"], scenario_ids=["s"], phase_ids=["p"])

    monkeypatch.setattr(cli, "_resolve_relearn_targets", _fake_targets)
    captured = _capture(monkeypatch, "_execute_relearn")

    _assert_captured(_invoke(["relearn"]))

    assert resolved["results_dir"] == project / "state" / "results"
    assert captured["plan_path"] == project / "plans"
    assert captured["testbed_path"] == project / "inventory" / "lab.yaml"
    assert captured["parameters_dir"] == project / "state" / "parameters"
    assert captured["results_dir"] == project / "state" / "results"
    assert captured["output_dir"] == project / "state" / "artifacts"


def test_reconcile_uses_project_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconcile takes plan, results and parameters dirs from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture(monkeypatch, "_run_reconcile")

    _assert_captured(_invoke(["reconcile", "--phase", "post-change"]))

    plan, _phase, _scenario, results_dir, parameters_dir, _output = captured["args"]
    assert plan == project / "plans"
    assert results_dir == project / "state" / "results"
    assert parameters_dir == project / "state" / "parameters"


def test_prune_uses_project_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prune takes plan and results dir from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    run_json = project / "run.json"
    monkeypatch.setattr(
        cli,
        "parse_applicability_from_run",
        lambda _path: cli.PruneInput(partial_tests=[], full_tests=[]),
    )
    captured = _capture(monkeypatch, "load_test_plan")
    results_dirs: list[Path] = []
    monkeypatch.setattr(
        cli,
        "find_latest_learning_results",
        lambda results_dir: results_dirs.append(results_dir) or run_json,
    )

    _assert_captured(_invoke(["prune", "--remove-orphans"]))

    assert captured["args"] == (project / "plans",)
    assert results_dirs == [project / "state" / "results"]


def test_execute_uses_project_testbed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute takes its testbed from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured: dict[str, Any] = {}

    def _fake_load_testbed(path: Path) -> None:
        captured["testbed"] = path
        raise _CapturedError

    monkeypatch.setattr("huginn.loaders.load_testbed", _fake_load_testbed)

    _assert_captured(_invoke(["execute", "--device", "r1", "-c", "show version"]))

    assert captured["testbed"] == project / "inventory" / "lab.yaml"


@pytest.mark.parametrize("subcommand", ["new", "into"])
def test_inject_uses_project_test_plan(
    project: Path, monkeypatch: pytest.MonkeyPatch, subcommand: str
) -> None:
    """Both inject subcommands take their plan from [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    (project / "jobs").mkdir()
    captured = _capture(monkeypatch, "load_test_plan")
    args = {
        "new": ["inject", "new", "jobs", "--phase", "pre-change"],
        "into": ["inject", "into", "some-group", "jobs"],
    }[subcommand]

    _assert_captured(_invoke(args))

    assert captured["args"] == (project / "plans",)


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--mode", "testing"],
        ["validate"],
        ["reconcile", "--phase", "post-change"],
        ["relearn"],
        ["prune"],
        ["execute", "--device", "r1", "-c", "show version"],
    ],
    ids=["run", "validate", "reconcile", "relearn", "prune", "execute"],
)
def test_commands_use_project_logging_defaults(
    project: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """Every command with logging options takes log_file and log_level."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture(monkeypatch, "_build_output")

    _assert_captured(_invoke(args))

    assert captured["log_file"] == project / "logs" / "huginn.log"
    assert captured["log_level"] == "WARNING"


def test_env_var_overrides_project_default(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A HUGINN_* environment variable beats the [tool.huginn] value."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture(monkeypatch, "_build_output")

    _assert_captured(
        _invoke(
            ["prune"], env={"HUGINN_LOG_LEVEL": "ERROR", "HUGINN_LOG_FILE": "e.log"}
        )
    )

    assert captured["log_level"] == "ERROR"
    assert captured["log_file"] == Path("e.log")


def test_cli_flag_overrides_env_var_and_project_default(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit CLI flag beats both the env var and [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture(monkeypatch, "_build_output")

    _assert_captured(
        _invoke(
            ["prune", "--log-level", "DEBUG"],
            env={"HUGINN_LOG_LEVEL": "ERROR"},
        )
    )

    assert captured["log_level"] == "DEBUG"


def test_without_pyproject_built_in_defaults_apply(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no pyproject.toml the built-in defaults are unchanged."""
    (project / "test_plan").mkdir()
    (project / "testbed.yaml").write_text("devices: {}\n")
    captured = _capture_async(monkeypatch, "run_test_plan")
    logging_options: dict[str, Any] = {}
    real_build_output = cli._build_output

    def _record_output(**kwargs: Any) -> cli.Output:  # noqa: ANN401
        logging_options.update(kwargs)
        return real_build_output(**kwargs)

    monkeypatch.setattr(cli, "_build_output", _record_output)

    _assert_captured(_invoke(["run", "--mode", "testing"]))

    assert captured["plan_path"] == project / "test_plan"
    assert captured["testbed_path"] == project / "testbed.yaml"
    assert captured["parameters_dir"] == project / "parameters"
    assert captured["results_dir"] == project / "results"
    assert captured["output_dir"] is None
    assert logging_options["log_level"] == "INFO"
    assert logging_options["log_file"] is None


def test_cli_inventory_plugin_overrides_project_testbed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--inventory-plugin on the CLI drops a testbed set in [tool.huginn]."""
    _write_pyproject(project, _FULL_PYPROJECT)
    captured = _capture_async(monkeypatch, "run_test_plan")

    _assert_captured(_invoke(["run", "-m", "testing", "-i", "huginn-netbox"]))

    assert captured["testbed_path"] is None
    assert captured["inventory_plugin"] == "huginn-netbox"


def test_cli_testbed_overrides_project_inventory_plugin(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--testbed on the CLI drops an inventory plugin set in [tool.huginn]."""
    _write_pyproject(project, '[tool.huginn]\ninventory_plugin = "huginn-netbox"\n')
    (project / "plans" / "plan.yaml").write_text("scenarios: []\n")
    captured = _capture_async(monkeypatch, "validate_inputs")

    _assert_captured(
        _invoke(
            [
                "validate",
                "-p",
                str(project / "plans"),
                "-t",
                str(project / "inventory" / "lab.yaml"),
            ]
        )
    )

    assert captured["testbed_path"] == project / "inventory" / "lab.yaml"
    assert captured["inventory_plugin"] is None


def test_project_inventory_plugin_is_used(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inventory plugin from [tool.huginn] replaces the default testbed."""
    _write_pyproject(
        project,
        '[tool.huginn]\ntest_plan = "plans"\ninventory_plugin = "huginn-netbox"\n',
    )
    (project / "testbed.yaml").write_text("devices: {}\n")
    captured = _capture_async(monkeypatch, "run_test_plan")

    _assert_captured(_invoke(["run", "-m", "testing"]))

    assert captured["testbed_path"] is None
    assert captured["inventory_plugin"] == "huginn-netbox"


def test_cli_testbed_and_inventory_plugin_remain_exclusive(
    project: Path,
) -> None:
    """Passing both options explicitly is still rejected."""
    result = _invoke(
        [
            "validate",
            "-p",
            str(project / "plans"),
            "-t",
            str(project / "inventory" / "lab.yaml"),
            "-i",
            "huginn-netbox",
        ]
    )

    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_invalid_project_config_fails_command(project: Path) -> None:
    """An invalid [tool.huginn] table aborts the command with exit code 1."""
    _write_pyproject(project, '[tool.huginn]\nmode = "learning"\n')

    result = _invoke(["prune", "-p", str(project / "plans")])

    assert result.exit_code == 1
    assert "Unknown key(s) in [tool.huginn]: mode" in result.output


def test_version_ignores_invalid_project_config(project: Path) -> None:
    """The version command still works when [tool.huginn] is invalid."""
    _write_pyproject(project, '[tool.huginn]\nmode = "learning"\n')

    result = _invoke(["version"])

    assert result.exit_code == 0
    assert result.output.startswith("huginn v")


def test_help_labels_project_defaults(project: Path) -> None:
    """--help shows which defaults come from pyproject.toml."""
    _write_pyproject(project, _FULL_PYPROJECT)

    result = _invoke(["prune", "--help"])

    assert result.exit_code == 0
    assert "plans from pyproject.toml" in result.output
    assert "state/results from pyproject.toml" in result.output
    assert "WARNING from pyproject.toml" in result.output


def test_project_plugins_reach_the_registry(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[tool.huginn.plugins] still configures the plugin registry for run."""
    _write_pyproject(
        project,
        _FULL_PYPROJECT + '\n[tool.huginn.plugins]\nreporters = ["html"]\n',
    )
    captured = _capture_async(monkeypatch, "run_test_plan")

    _assert_captured(_invoke(["run", "--mode", "testing"]))

    assert captured["registry"]._config.reporters == ["html"]
