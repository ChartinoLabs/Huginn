"""Tests for LOST_APPLICABILITY across a learning run and a testing run."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from huginn.cli import app
from huginn.prune import parse_applicability_from_run
from huginn.relearn import parse_failed_test_ids

from .conftest import first_test_case, load_report, stage_runner_fixture


def _run(tmp_path: Path, mode: str, unsupported: list[str]) -> Result:
    """Run the fixture plan with the given devices unsupported."""
    (tmp_path / "unsupported.txt").write_text("\n".join(unsupported), encoding="utf-8")
    return CliRunner().invoke(
        app,
        [
            "run",
            "--mode",
            mode,
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )


def _latest_run_json(tmp_path: Path) -> dict[str, Any]:
    """Return the raw run.json of the latest run."""
    path = sorted((tmp_path / "results").glob("*/run.json"))[-1]
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stage the fixture and run from the temp directory."""
    stage_runner_fixture(tmp_path, "lost_applicability")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_learned_device_that_loses_support_fails_the_run(staged: Path) -> None:
    """A device learned as supported but unsupported in testing fails the run."""
    assert _run(staged, "learning", []).exit_code == 0

    result = _run(staged, "testing", ["leaf-02"])

    assert result.exit_code == 1
    assert "Run status: lost_applicability" in result.stdout
    assert "not_applicable=0 lost_applicability=1 " in result.stdout
    run_json = _latest_run_json(staged)
    assert run_json["summary"]["status"] == "lost_applicability"
    assert run_json["summary"]["lost_applicability"] == 1
    test_case = first_test_case(load_report(staged))
    assert test_case["status"] == "lost_applicability"
    assert test_case["not_applicable_devices"] == {}
    assert [check["status"] for check in test_case["checks"]] == [
        "lost_applicability",
        "passed",
    ]
    assert test_case["checks"][0]["message"] == (
        "leaf-02: Device does not support 'show feature', but it was supported "
        "when parameters were learned"
    )


def test_prune_never_excludes_a_lost_device(staged: Path) -> None:
    """Prune sees only never-supported devices, not ones that lost support."""
    _run(staged, "learning", ["leaf-01"])
    _run(staged, "testing", ["leaf-01", "leaf-02"])
    run_json = sorted((staged / "results").glob("*-testing/run.json"))[-1]

    prune_input = parse_applicability_from_run(run_json)

    excluded = {
        device
        for entry in prune_input.partial_tests + prune_input.full_tests
        for device in entry.not_applicable_devices
    }
    assert excluded == {"leaf-01"}


def test_relearn_picks_up_lost_applicability(staged: Path) -> None:
    """Relearn treats a LOST_APPLICABILITY test case as a failed context."""
    _run(staged, "learning", [])
    _run(staged, "testing", ["leaf-02"])
    run_json = sorted((staged / "results").glob("*-testing/run.json"))[-1]

    relearn_input = parse_failed_test_ids(run_json)

    assert relearn_input.contexts == [("scenario-1", "phase-1", "1.0.0")]


def test_html_report_shows_lost_applicability(staged: Path) -> None:
    """The HTML dashboard counts and badges LOST_APPLICABILITY distinctly."""
    _run(staged, "learning", [])
    _run(staged, "testing", ["leaf-02"])

    report_dir = staged / "reports" / "latest"
    dashboard = (report_dir / "index.html").read_text(encoding="utf-8")
    assert 'class="metric-card metric-lost-applicability"' in dashboard
    assert "Lost Applicability" in dashboard
    assert "status-pill-lost_applicability" in dashboard
    detail = next((report_dir / "test-cases").glob("*.html")).read_text(
        encoding="utf-8"
    )
    assert "result-item-lost_applicability" in detail


def test_device_never_supported_stays_not_applicable(staged: Path) -> None:
    """A device unsupported when learned and when tested is only N/A."""
    assert _run(staged, "learning", ["leaf-02"]).exit_code == 0

    result = _run(staged, "testing", ["leaf-02"])

    assert result.exit_code == 0
    test_case = first_test_case(load_report(staged))
    assert test_case["status"] == "passed"
    assert test_case["not_applicable_devices"] == {
        "leaf-02": "Device does not support 'show feature'"
    }
    assert _latest_run_json(staged)["summary"]["lost_applicability"] == 0


def test_learning_mode_never_reports_lost_applicability(staged: Path) -> None:
    """Relearning after a device loses support records N/A, not a failure."""
    assert _run(staged, "learning", []).exit_code == 0

    result = _run(staged, "learning", ["leaf-02"])

    assert result.exit_code == 0
    test_case = first_test_case(load_report(staged))
    assert test_case["status"] == "not_applicable"
    assert "leaf-02" in test_case["not_applicable_devices"]
    assert _latest_run_json(staged)["summary"]["lost_applicability"] == 0
