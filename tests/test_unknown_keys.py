"""Tests for unknown-key warnings in test plan and testbed files."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from huginn import cli
from huginn.cli import app
from huginn.loaders import ConfigurationError, load_test_plan, load_testbed
from huginn.project_config import load_project_config
from huginn.reconcile import FailingTestCase, ReconcileInput
from huginn.unknown_keys import UnknownKeyWarning
from tests.runner.conftest import _FakeRuntimeBroker

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PLAN: dict[str, Any] = {
    "name": "Plan",
    "description": "A plan",
    "test_cases": {
        "1.0.0": {
            "title": "Verify Something",
            "job": "jobs/test_verify_passed.py",
            "target": {"devices": ["spine-01"]},
        }
    },
    "test_case_groups": {
        "group-1": {
            "name": "Group 1",
            "description": "Recognized, implemented by #281",
            "tests": ["1.0.0"],
            "strategy": {"parallel": {"maximum": 2}},
        }
    },
    "scenarios": {
        "scenario-1": {
            "name": "Scenario 1",
            "description": "Recognized, implemented by #281",
            "phases": {
                "phase-1": {
                    "description": "Recognized, implemented by #281",
                    "test_case_groups": ["group-1"],
                    "strategy": {"serial": None},
                }
            },
        }
    },
}

_TESTBED: dict[str, Any] = {
    "name": "lab",
    "credentials": {"default": {"username": "admin", "password": "admin"}},
    "devices": {
        "spine-01": {
            "os": "nxos",
            "groups": ["spine"],
            "metadata": {"rack": "R1"},
            "credentials": {"api": {"token": "t", "token_type": "Bearer"}},
            "connections": {
                "ssh": {
                    "protocol": "ssh",
                    "host": "10.0.0.1",
                    "port": 22,
                    "timeout_socket": 10,
                    "transport_options": {"anything": True},
                }
            },
        }
    },
}


def _write_yaml(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _plan_warnings(path: Path) -> list[UnknownKeyWarning]:
    warnings: list[UnknownKeyWarning] = []
    load_test_plan(path, unknown_keys=warnings)
    return warnings


def _testbed_warnings(path: Path) -> list[UnknownKeyWarning]:
    warnings: list[UnknownKeyWarning] = []
    load_testbed(path, unknown_keys=warnings)
    return warnings


def _plan(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    """Return a deep copy of the base plan with top-level keys overridden."""
    plan = json.loads(json.dumps(_PLAN))
    plan.update(overrides)
    return plan


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def test_recognized_plan_keys_do_not_warn(tmp_path: Path) -> None:
    """Every key the loader reads, and the reserved description keys, are quiet."""
    plan = _write_yaml(tmp_path / "plan.yaml", _plan())

    assert _plan_warnings(plan) == []


def test_recognized_testbed_keys_and_connection_options_do_not_warn(
    tmp_path: Path,
) -> None:
    """Testbed name, device metadata and connection extras are not unknown keys."""
    testbed = _write_yaml(tmp_path / "testbed.yaml", _TESTBED)

    assert _testbed_warnings(testbed) == []


def _set(data: dict[str, Any], path: tuple[str, ...], key: str) -> None:
    for part in path:
        data = data[part]
    data[key] = "x"


_PHASE = ("scenarios", "scenario-1", "phases", "phase-1")
_GROUP = ("test_case_groups", "group-1")


@pytest.mark.parametrize(
    ("path", "key", "expected_path", "suggestion"),
    [
        ((), "test_case", "test_case", "test_cases"),
        (("test_cases", "1.0.0"), "titel", '["1.0.0"].titel', "title"),
        (
            ("test_cases", "1.0.0", "target"),
            "device",
            '["1.0.0"].target.device',
            "devices",
        ),
        (_GROUP, "owner", "test_case_groups.group-1.owner", None),
        (
            (*_GROUP, "strategy"),
            "paralel",
            "test_case_groups.group-1.strategy.paralel",
            "parallel",
        ),
        (
            ("scenarios", "scenario-1"),
            "phase",
            "scenarios.scenario-1.phase",
            "phases",
        ),
        (
            _PHASE,
            "depend_on",
            "scenarios.scenario-1.phases.phase-1.depend_on",
            "depends_on",
        ),
        (
            _PHASE,
            "test_case_group",
            "scenarios.scenario-1.phases.phase-1.test_case_group",
            "test_case_groups",
        ),
    ],
    ids=[
        "top-level",
        "test-case",
        "target",
        "group",
        "strategy",
        "scenario",
        "phase-depends-on",
        "phase-test-case-groups",
    ],
)
def test_each_plan_level_warns(
    tmp_path: Path,
    path: tuple[str, ...],
    key: str,
    expected_path: str,
    suggestion: str | None,
) -> None:
    """An unknown key at any plan level warns with its path and a suggestion."""
    data = _plan()
    _set(data, path, key)
    plan = _write_yaml(tmp_path / "plan.yaml", data)

    warnings = _plan_warnings(plan)

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.source == plan
    assert warning.key == key
    assert warning.key_path.endswith(expected_path)
    assert warning.suggestion == suggestion
    if suggestion is not None:
        assert f"did you mean '{suggestion}'?" in str(warning)


def test_test_case_path_brackets_dotted_ids(tmp_path: Path) -> None:
    """A test case ID with dots stays one readable segment of the key path."""
    data = _plan()
    _set(data, ("test_cases", "1.0.0"), "tag")
    plan = _write_yaml(tmp_path / "plan.yaml", data)

    (warning,) = _plan_warnings(plan)

    assert warning.key_path == 'test_cases["1.0.0"].tag'
    assert warning.suggestion == "tags"
    assert str(warning) == (
        f"Unknown key 'tag' at 'test_cases[\"1.0.0\"].tag' in {plan}; "
        "did you mean 'tags'?"
    )


@pytest.mark.parametrize(
    ("strategy", "error", "key_path", "suggestion"),
    [
        (
            {"serial": {"maximum": 1}},
            "strategy.serial must be null",
            "test_case_groups.group-1.strategy.serial.maximum",
            None,
        ),
        (
            {"parallel": {"maximun": 1}},
            "strategy.parallel has unsupported keys",
            "test_case_groups.group-1.strategy.parallel.maximun",
            "maximum",
        ),
    ],
    ids=["serial", "parallel"],
)
def test_strategy_sub_keys_warn_before_the_loader_rejects_them(
    tmp_path: Path,
    strategy: dict[str, Any],
    error: str,
    key_path: str,
    suggestion: str | None,
) -> None:
    """The loader rejects extra strategy sub-keys, and the warning is kept."""
    data = _plan()
    data["test_case_groups"]["group-1"]["strategy"] = strategy
    plan = _write_yaml(tmp_path / "plan.yaml", data)
    warnings: list[UnknownKeyWarning] = []

    with pytest.raises(ConfigurationError, match=error):
        load_test_plan(plan, unknown_keys=warnings)

    assert [(w.key_path, w.suggestion) for w in warnings] == [(key_path, suggestion)]


@pytest.mark.parametrize(
    ("path", "key", "expected_path", "suggestion"),
    [
        ((), "device", "device", "devices"),
        (
            ("credentials", "default"),
            "pasword",
            "credentials.default.pasword",
            "password",
        ),
        (("devices", "spine-01"), "group", "devices.spine-01.group", "groups"),
        (
            ("devices", "spine-01", "credentials", "api"),
            "tokn",
            "devices.spine-01.credentials.api.tokn",
            "token",
        ),
    ],
    ids=["top-level", "credential", "device", "device-credential"],
)
def test_each_testbed_level_warns(
    tmp_path: Path,
    path: tuple[str, ...],
    key: str,
    expected_path: str,
    suggestion: str | None,
) -> None:
    """An unknown key at any testbed level warns with its path."""
    data = json.loads(json.dumps(_TESTBED))
    _set(data, path, key)
    testbed = _write_yaml(tmp_path / "testbed.yaml", data)

    (warning,) = _testbed_warnings(testbed)

    assert warning.source == testbed
    assert warning.key_path == expected_path
    assert warning.suggestion == suggestion


def test_testbed_name_defaults_to_none() -> None:
    """A testbed without a name loads with Testbed.name set to None."""
    assert load_testbed(FIXTURES / "loaders" / "testbed_valid.yaml").name is None


def test_testbed_name_is_stored(tmp_path: Path) -> None:
    """A string testbed name is loaded into Testbed.name."""
    testbed = load_testbed(_write_yaml(tmp_path / "testbed.yaml", _TESTBED))

    assert testbed.name == "lab"


def test_testbed_name_must_be_a_string(tmp_path: Path) -> None:
    """A non-string testbed name is a configuration error."""
    data = dict(_TESTBED, name=["lab"])

    with pytest.raises(ConfigurationError, match="Testbed 'name' must be a string"):
        load_testbed(_write_yaml(tmp_path / "testbed.yaml", data))


def test_loaders_do_not_collect_warnings_without_a_list(tmp_path: Path) -> None:
    """Existing callers that pass no collector keep working unchanged."""
    plan = _write_yaml(tmp_path / "plan.yaml", _plan(extra="x"))

    assert load_test_plan(plan).name == "Plan"


def test_directory_plan_warns_per_file(tmp_path: Path) -> None:
    """Directory mode names the file that holds each unknown key."""
    data = _plan()
    scenarios = {"scenarios": data.pop("scenarios")}
    scenarios["scenarios"]["scenario-1"]["phases"]["phase-1"]["depend_on"] = []
    data["test_case_groups"]["group-1"]["test"] = ["1.0.0"]
    main = _write_yaml(tmp_path / "plan" / "main.yaml", data)
    scenario_file = _write_yaml(tmp_path / "plan" / "scenarios.yaml", scenarios)

    warnings = _plan_warnings(tmp_path / "plan")

    by_source = {w.source: w for w in warnings}
    assert by_source[main].key_path == "test_case_groups.group-1.test"
    assert by_source[main].suggestion == "tests"
    assert by_source[scenario_file].suggestion == "depends_on"


def test_directory_plan_skips_underscore_data_model(tmp_path: Path) -> None:
    """Files under a `_` directory are not plan files, so they never warn."""
    _write_yaml(tmp_path / "plan" / "main.yaml", _plan())
    _write_yaml(tmp_path / "plan" / "_data" / "fabric.yaml", {"fabric": {"asn": 1}})

    assert _plan_warnings(tmp_path / "plan") == []


def test_removed_defaults_key_is_still_an_error(tmp_path: Path) -> None:
    """The defaults key keeps its explicit removal error, not a warning."""
    plan = _write_yaml(tmp_path / "plan.yaml", _plan(defaults={"tags": ["a"]}))
    warnings: list[UnknownKeyWarning] = []

    with pytest.raises(ConfigurationError, match="'defaults'.*was removed"):
        load_test_plan(plan, unknown_keys=warnings)
    assert warnings == []


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage the passing runner fixture with a typo in the plan and testbed."""
    monkeypatch.delenv("HUGINN_NO_UNKNOWN_KEY_WARNINGS", raising=False)
    monkeypatch.setattr("huginn.runner.RuntimeBroker", _FakeRuntimeBroker)
    source = FIXTURES / "runner" / "passed"
    shutil.copytree(source / "jobs", tmp_path / "jobs")
    plan = yaml.safe_load((source / "test_plan.yaml").read_text(encoding="utf-8"))
    plan["scenarios"]["scenario-1"]["phases"]["phase-1"]["depend_on"] = []
    _write_yaml(tmp_path / "test_plan.yaml", plan)
    testbed = yaml.safe_load((source / "testbed.yaml").read_text(encoding="utf-8"))
    testbed["devices"]["spine-01"]["group"] = ["spine"]
    _write_yaml(tmp_path / "testbed.yaml", testbed)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(args: list[str], env: dict[str, str] | None = None) -> Any:  # noqa: ANN401
    return CliRunner().invoke(
        app,
        [*args, "--plan", "test_plan.yaml", "--testbed", "testbed.yaml"],
        env=env,
        catch_exceptions=False,
    )


def _flat(output: str) -> str:
    """Collapse the console's line wrapping."""
    return " ".join(output.split())


def _validate_report(project: Path) -> dict[str, Any]:
    reports = sorted((project / "results").glob("*-validate/validate.json"))
    return json.loads(reports[-1].read_text(encoding="utf-8"))


def test_validate_reports_unknown_keys_as_warnings(project: Path) -> None:
    """Validate lists unknown keys as warning issues and still exits 0."""
    result = _invoke(["validate"])

    assert result.exit_code == 0, result.output
    report = _validate_report(project)
    assert report["valid"] is True
    assert report["errors"] == []
    codes = {w["code"] for w in report["warnings"]}
    assert codes == {"unknown_key"}
    messages = " ".join(w["message"] for w in report["warnings"])
    assert "did you mean 'depends_on'?" in messages
    assert "did you mean 'groups'?" in messages
    assert "did you mean 'depends_on'?" in _flat(result.output)


def test_validate_reports_warnings_when_the_plan_fails(project: Path) -> None:
    """Warnings found before a load error are still reported."""
    plan = yaml.safe_load((project / "test_plan.yaml").read_text(encoding="utf-8"))
    plan["test_case_groups"]["group-1"]["tests"] = ["missing"]
    _write_yaml(project / "test_plan.yaml", plan)

    result = _invoke(["validate"])

    assert result.exit_code == 3
    report = _validate_report(project)
    assert report["errors"][0]["code"] == "configuration_error"
    assert {w["code"] for w in report["warnings"]} == {"unknown_key"}


def test_run_prints_unknown_key_warnings(project: Path) -> None:
    """Run prints unknown-key warnings and still runs the plan."""
    result = _invoke(["run", "--mode", "testing"])

    assert result.exit_code == 0, result.output
    output = _flat(result.output)
    assert "WARNING [unknown_key]: Unknown key 'depend_on'" in output
    assert "did you mean 'depends_on'?" in output
    assert "did you mean 'groups'?" in output


def test_flag_silences_warnings(project: Path) -> None:
    """--no-unknown-key-warnings silences run and validate."""
    run = _invoke(["run", "--mode", "testing", "--no-unknown-key-warnings"])
    validate = _invoke(["validate", "--no-unknown-key-warnings"])

    assert "unknown_key" not in run.output
    assert "unknown_key" not in validate.output
    assert _validate_report(project)["warnings"] == []


def test_env_var_silences_warnings(project: Path) -> None:
    """HUGINN_NO_UNKNOWN_KEY_WARNINGS silences the warnings."""
    result = _invoke(
        ["run", "--mode", "testing"], env={"HUGINN_NO_UNKNOWN_KEY_WARNINGS": "1"}
    )

    assert result.exit_code == 0
    assert "unknown_key" not in result.output


def test_pyproject_key_silences_warnings(project: Path) -> None:
    """[tool.huginn] unknown_key_warnings = false silences the warnings."""
    (project / "pyproject.toml").write_text(
        "[tool.huginn]\nunknown_key_warnings = false\n", encoding="utf-8"
    )

    result = _invoke(["run", "--mode", "testing"])

    assert result.exit_code == 0
    assert "unknown_key" not in result.output


def test_env_var_overrides_pyproject_key(project: Path) -> None:
    """The environment variable takes precedence over [tool.huginn]."""
    (project / "pyproject.toml").write_text(
        "[tool.huginn]\nunknown_key_warnings = false\n", encoding="utf-8"
    )

    result = _invoke(["validate"], env={"HUGINN_NO_UNKNOWN_KEY_WARNINGS": "false"})

    assert result.exit_code == 0
    assert "unknown_key" in result.output


def test_pyproject_true_keeps_warnings(project: Path) -> None:
    """unknown_key_warnings = true leaves the warnings on."""
    (project / "pyproject.toml").write_text(
        "[tool.huginn]\nunknown_key_warnings = true\n", encoding="utf-8"
    )

    result = _invoke(["validate"])

    assert "unknown_key" in result.output


@pytest.mark.parametrize("value", ['"false"', "0", '"no"'])
def test_pyproject_key_must_be_a_boolean(tmp_path: Path, value: str) -> None:
    """unknown_key_warnings rejects values that are not TOML booleans."""
    (tmp_path / "pyproject.toml").write_text(
        f"[tool.huginn]\nunknown_key_warnings = {value}\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match="must be a boolean"):
        load_project_config(tmp_path)


def test_pyproject_bool_reaches_the_cli_as_a_default(tmp_path: Path) -> None:
    """The boolean key becomes the --no-unknown-key-warnings default."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.huginn]\nunknown_key_warnings = false\n", encoding="utf-8"
    )

    config = load_project_config(tmp_path)

    assert config.unknown_key_warnings is False
    assert config.cli_defaults() == {"no_unknown_key_warnings": True}


@pytest.mark.parametrize(
    "args",
    [
        ["reconcile", "--plan", "test_plan.yaml", "--phase", "phase-1"],
        ["prune", "--plan", "test_plan.yaml", "--remove-orphans"],
        ["execute", "--testbed", "testbed.yaml", "--device", "x", "-c", "show"],
    ],
    ids=["reconcile", "prune", "execute"],
)
def test_other_commands_warn_and_accept_the_flag(
    project: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """Every command that loads a plan or testbed warns, and the flag silences it."""
    run_json = project / "run.json"
    monkeypatch.setattr(cli, "find_latest_testing_results", lambda _d: run_json)
    monkeypatch.setattr(cli, "find_latest_learning_results", lambda _d: run_json)
    reconcile_input = ReconcileInput(
        failing_tests=[FailingTestCase("1.0.0", "group-1", "scenario-1")],
        passing_test_ids_by_group={},
        affected_group_ids={"group-1"},
        phase_name="phase-1",
        scenarios_with_phase=["scenario-1"],
    )
    monkeypatch.setattr(
        cli, "parse_failures_from_run", lambda *_a, **_k: reconcile_input
    )
    monkeypatch.setattr(
        cli,
        "parse_applicability_from_run",
        lambda _path: cli.PruneInput(partial_tests=[], full_tests=[]),
    )

    async def _no_commands(**_kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(cli, "execute_commands", _no_commands)
    runner = CliRunner()

    warned = runner.invoke(app, args)
    silenced = runner.invoke(app, [*args, "--no-unknown-key-warnings"])

    assert "unknown_key" in warned.output, warned.output
    assert "unknown_key" not in silenced.output, silenced.output


@pytest.mark.parametrize("subcommand", ["new", "into"])
def test_inject_warns_and_accepts_the_flag(project: Path, subcommand: str) -> None:
    """Both inject subcommands warn about unknown keys in the plan directory."""
    plan_dir = project / "plan_dir"
    plan_dir.mkdir()
    shutil.move(project / "test_plan.yaml", plan_dir / "plan.yaml")
    args = {
        "new": ["inject", "new", "jobs", "--phase", "phase-1", "--dry-run"],
        "into": ["inject", "into", "group-1", "jobs", "--dry-run"],
    }[subcommand]
    args += ["--plan", str(plan_dir)]
    runner = CliRunner()

    warned = runner.invoke(app, args)
    silenced = runner.invoke(app, [*args, "--no-unknown-key-warnings"])

    assert "unknown_key" in warned.output, warned.output
    assert "unknown_key" not in silenced.output, silenced.output
