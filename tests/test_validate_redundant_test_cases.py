"""Tests for the validate warning about test cases that are copies."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from huginn.cli import app

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "runner" / "target_selectors"
_JOB = "jobs/test_verify_targets.py"


def _stage_plan(
    tmp_path: Path,
    *,
    pre: dict[str, Any] | None = None,
    post: dict[str, Any] | None = None,
    post_group_target: dict[str, Any] | None = None,
) -> None:
    """Stage a two-phase plan whose PRE and POST test cases differ as given."""
    shutil.copytree(_FIXTURE, tmp_path, dirs_exist_ok=True)
    post_group: dict[str, Any] = {"tests": ["POST"]}
    if post_group_target is not None:
        post_group["target"] = post_group_target
    plan = {
        "test_cases": {
            "PRE": {"title": "Pre-change check", "job": _JOB, **(pre or {})},
            "POST": {"title": "Post-change check", "job": _JOB, **(post or {})},
        },
        "test_case_groups": {
            "pre-group": {"tests": ["PRE"], "target": {"devices": ["leaf-01"]}},
            "post-group": {"target": {"devices": ["leaf-01"]}, **post_group},
        },
        "scenarios": {
            "change": {
                "phases": {
                    "pre-change": {"test_case_groups": ["pre-group"]},
                    "post-change": {
                        "test_case_groups": ["post-group"],
                        "depends_on": ["pre-change"],
                    },
                }
            }
        },
    }
    (tmp_path / "test_plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")


def _write_parameters(parameters_dir: Path, test_id: str, payload: object) -> None:
    parameters_dir.mkdir(parents=True, exist_ok=True)
    (parameters_dir / f"{test_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _redundant_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *extra_args: str,
) -> list[str]:
    """Run validate and return the messages of redundant test case warnings."""
    monkeypatch.chdir(tmp_path)
    # Two runs in the same second get different results directory names, so
    # clear earlier results to read only this run's report.
    shutil.rmtree(tmp_path / "results", ignore_errors=True)
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
            *extra_args,
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    reports = sorted((tmp_path / "results").glob("*-validate/validate.json"))
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert report["valid"] is True
    return [
        warning["message"]
        for warning in report["warnings"]
        if warning["code"] == "redundant_test_case"
    ]


def test_warns_about_copies_without_learned_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two test cases differing only in title and tags are reported once."""
    _stage_plan(tmp_path, post={"tags": ["post"]})

    warnings = _redundant_warnings(tmp_path, monkeypatch)

    assert len(warnings) == 1
    assert warnings[0].startswith("Test cases POST, PRE are copies")
    assert _JOB in warnings[0]


def test_warns_about_copies_with_identical_learned_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copies that learned the same parameters are still copies."""
    _stage_plan(tmp_path)
    for test_id in ("PRE", "POST"):
        _write_parameters(tmp_path / "parameters", test_id, {"leaf-01": {"up": 4}})

    assert len(_redundant_warnings(tmp_path, monkeypatch)) == 1


def test_reconciled_variant_with_different_parameters_is_not_a_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-change variant that expects a different state is not reported."""
    _stage_plan(tmp_path)
    _write_parameters(tmp_path / "parameters", "PRE", {"leaf-01": {"up": 4}})
    _write_parameters(tmp_path / "parameters", "POST", {"leaf-01": {"up": 3}})

    assert _redundant_warnings(tmp_path, monkeypatch) == []


def test_only_one_test_case_with_learned_parameters_is_not_a_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learned parameters on one test case and none on the other differ."""
    _stage_plan(tmp_path)
    _write_parameters(tmp_path / "parameters", "PRE", {"leaf-01": {"up": 4}})

    assert _redundant_warnings(tmp_path, monkeypatch) == []


@pytest.mark.parametrize(
    ("post", "post_group_target"),
    [
        pytest.param({"metadata": {"interface": "Ethernet1"}}, None, id="metadata"),
        pytest.param({"target": {"os": ["eos"]}}, None, id="test-target"),
        pytest.param({"is_automated": False}, None, id="is-automated"),
        pytest.param({}, {"devices": ["leaf-02"]}, id="resolved-devices"),
    ],
)
def test_test_cases_that_differ_in_an_input_are_not_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post: dict[str, Any],
    post_group_target: dict[str, Any] | None,
) -> None:
    """A difference in anything that affects the result rules out a copy."""
    _stage_plan(tmp_path, post=post, post_group_target=post_group_target)

    assert _redundant_warnings(tmp_path, monkeypatch) == []


def test_reads_learned_parameters_from_parameters_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--parameters-dir selects where learned parameters are compared from."""
    _stage_plan(tmp_path)
    _write_parameters(tmp_path / "learned", "PRE", {"leaf-01": {"up": 4}})
    _write_parameters(tmp_path / "learned", "POST", {"leaf-01": {"up": 3}})

    assert _redundant_warnings(tmp_path, monkeypatch) != []
    assert (
        _redundant_warnings(
            tmp_path, monkeypatch, "--parameters-dir", str(tmp_path / "learned")
        )
        == []
    )


def test_unreadable_learned_parameters_are_not_compared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken parameter file skips the check instead of failing validation."""
    _stage_plan(tmp_path)
    for test_id in ("PRE", "POST"):
        (tmp_path / "parameters").mkdir(exist_ok=True)
        (tmp_path / "parameters" / f"{test_id}.json").write_text("{", encoding="utf-8")

    assert _redundant_warnings(tmp_path, monkeypatch) == []
