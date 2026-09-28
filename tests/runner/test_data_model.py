"""Integration tests for passing the data model to jobs through the CLI."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from huginn.cli import app

from .conftest import load_report, stage_runner_fixture


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage the data model fixture and chdir into it."""
    stage_runner_fixture(tmp_path, "data_model")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(command: str, tmp_path: Path, *extra_args: str) -> Result:
    """Run a Huginn command against the staged fixture."""
    mode_args = ["--mode", "learning"] if command == "run" else []
    return CliRunner().invoke(
        app,
        [
            command,
            *mode_args,
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            *extra_args,
        ],
        catch_exceptions=False,
    )


def _reported_checks(tmp_path: Path) -> dict[str, list[str]]:
    """Return each test case's check messages from the run report."""
    report = load_report(tmp_path)
    return {
        test_case["test_id"]: [check["message"] for check in test_case["checks"]]
        for scenario in report["scenarios"]
        for phase in scenario["phases"]
        for group in phase["test_case_groups"]
        for test_case in group["test_cases"]
    }


def _data_model_message(value: object) -> str:
    return f"data_model={json.dumps(value, sort_keys=True)}"


_SAVED = "Learned parameters saved successfully"


def test_run_passes_merged_data_model_to_every_job(staged: Path) -> None:
    """Every job receives the merged model from `data_model.path`, read-only."""
    result = _invoke("run", staged)

    assert result.exit_code == 0, result.output
    expected = _data_model_message(
        {"fabric": {"leafs": ["leaf-01", "leaf-02"], "name": "dc1"}}
    )
    # The second job sees the original value: the first job could not mutate it.
    assert _reported_checks(staged) == {
        "1.0.0": [expected, "read-only", _SAVED],
        "1.1.0": [expected, "read-only", _SAVED],
    }


def test_run_data_model_option_overrides_plan_path(staged: Path) -> None:
    """`--data-model` replaces `data_model.path` and resolves against the cwd."""
    result = _invoke("run", staged, "--data-model", "alt_data_model")

    assert result.exit_code == 0, result.output
    checks = _reported_checks(staged)
    assert checks["1.0.0"][0] == _data_model_message({"fabric": {"name": "alt"}})


def test_run_data_model_env_var_overrides_plan_path(
    staged: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`HUGINN_DATA_MODEL` replaces `data_model.path` like `--data-model`."""
    monkeypatch.setenv("HUGINN_DATA_MODEL", "alt_data_model")

    result = _invoke("run", staged)

    assert result.exit_code == 0, result.output
    checks = _reported_checks(staged)
    assert checks["1.0.0"][0] == _data_model_message({"fabric": {"name": "alt"}})


def test_run_without_data_model_passes_none(staged: Path) -> None:
    """Jobs receive `None` when neither the plan nor the CLI sets a data model."""
    plan = staged / "test_plan.yaml"
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "data_model:\n  path: data_model\n", ""
        ),
        encoding="utf-8",
    )

    result = _invoke("run", staged)

    assert result.exit_code == 0, result.output
    assert _reported_checks(staged)["1.0.0"] == [_data_model_message(None), _SAVED]


def test_run_fails_on_conflicting_data_model(staged: Path) -> None:
    """A data model conflict stops the run with a configuration error."""
    (staged / "data_model" / "zz.yaml").write_text(
        "fabric:\n  name: other\n", encoding="utf-8"
    )

    result = _invoke("run", staged)

    assert result.exit_code == 1
    assert "Conflicting data model value at 'fabric.name'" in result.output


def test_validate_passes_with_valid_data_model(staged: Path) -> None:
    """`validate` loads the data model and passes when it is valid."""
    result = _invoke("validate", staged)

    assert result.exit_code == 0, result.output


def test_validate_reports_conflicting_data_model(staged: Path) -> None:
    """`validate` fails and reports a data model that does not load."""
    (staged / "data_model" / "zz.yaml").write_text(
        "fabric:\n  name: other\n", encoding="utf-8"
    )

    result = _invoke("validate", staged)

    assert result.exit_code == 3
    report_path = next((staged / "results").glob("*-validate/validate.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "configuration_error"
    assert "fabric.name" in report["errors"][0]["message"]


def test_validate_reports_missing_data_model_override(staged: Path) -> None:
    """`validate` fails when `--data-model` points at a missing directory."""
    result = _invoke("validate", staged, "--data-model", "missing")

    assert result.exit_code == 3
    assert "does not exist" in result.output


def test_relearn_passes_data_model_override_to_jobs(staged: Path) -> None:
    """`relearn` loads the data model from `--data-model` for re-run jobs."""
    run_dir = staged / "results" / "2020-Jan-01-00-00-00-testing"
    run_dir.mkdir(parents=True)
    failed_case = {
        "test_id": "1.0.0",
        "title": "Report Data Model",
        "status": "failed",
        "result_path": "test-cases/1.0.0/result.json",
    }
    phase = {
        "id": "phase-1",
        "status": "failed",
        "test_case_groups": [
            {"id": "group-1", "status": "failed", "test_cases": [failed_case]}
        ],
    }
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "mode": "testing",
                "scenarios": [
                    {"id": "scenario-1", "status": "failed", "phases": [phase]}
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _invoke("relearn", staged, "--data-model", "alt_data_model")

    assert result.exit_code == 0, result.output
    assert _reported_checks(staged) == {
        "1.0.0": [
            _data_model_message({"fabric": {"name": "alt"}}),
            "read-only",
            _SAVED,
        ]
    }
