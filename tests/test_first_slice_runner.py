"""Integration tests for the first end-to-end runner slice."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from huginn.cli import app


def test_run_executes_single_test_case_and_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run executes one test and writes a JSON report."""
    _write_job(
        tmp_path,
        """
from huginn import ResultStatus, TestCase


class VerifySomething(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        context.results.add_result(ResultStatus.PASSED, "all good")

    async def cleanup(self, context) -> None:
        return None
""",
    )
    _write_testbed(tmp_path)
    _write_test_plan(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "passed"
    assert report_data["summary"]["passed"] == 1


def test_run_returns_non_zero_for_failed_test_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI run returns exit code 1 when a test fails."""
    _write_job(
        tmp_path,
        """
from huginn import ResultStatus, TestCase


class VerifySomething(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        context.results.add_result(ResultStatus.FAILED, "failed check")

    async def cleanup(self, context) -> None:
        return None
""",
    )
    _write_testbed(tmp_path)
    _write_test_plan(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "failed"
    assert report_data["summary"]["failed"] == 1


def test_cleanup_runs_when_test_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup is executed even when test raises an exception."""
    _write_job(
        tmp_path,
        """
from pathlib import Path
from huginn import TestCase


class VerifySomething(TestCase):
    async def setup(self, context) -> None:
        return None

    async def test(self, context) -> None:
        raise RuntimeError("boom")

    async def cleanup(self, context) -> None:
        Path("cleanup.marker").write_text("done", encoding="utf-8")
""",
    )
    _write_testbed(tmp_path)
    _write_test_plan(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--mode",
            "testing",
            "--testbed",
            str(tmp_path / "testbed.yaml"),
            "--plan",
            str(tmp_path / "test_plan.yaml"),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert (tmp_path / "cleanup.marker").exists()
    report_data = _load_report(tmp_path)
    assert report_data["summary"]["status"] == "errored"
    assert report_data["summary"]["errored"] == 1


def _write_job(tmp_path: Path, body: str) -> None:
    """Write a single job module used by tests."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "verify.py").write_text(body.strip() + "\n", encoding="utf-8")


def _write_testbed(tmp_path: Path) -> None:
    """Write a minimal testbed file for integration tests."""
    (tmp_path / "testbed.yaml").write_text(
        """
devices:
  spine-01:
    os: nxos
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_test_plan(tmp_path: Path) -> None:
    """Write a minimal test plan file for integration tests."""
    (tmp_path / "test_plan.yaml").write_text(
        """
test_cases:
  "1.0.0":
    title: Verify Something
    job: jobs/verify.py

test_case_groups:
  group-1:
    tests:
      - "1.0.0"

phases:
  phase-1:
    test_case_groups:
      - group-1
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _load_report(tmp_path: Path) -> dict[str, Any]:
    """Load the generated run report from the default reports directory."""
    report_path = tmp_path / "reports" / "run.json"
    return json.loads(report_path.read_text(encoding="utf-8"))
