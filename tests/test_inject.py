"""Unit tests for the inject module."""

from pathlib import Path

import yaml

from huginn.inject import InjectPlan, apply_inject_plan
from huginn.loaders import load_test_plan

_NEW_TEST_CASES: dict[str, dict[str, object]] = {
    "CDP-1": {"title": "Verify CDP", "job": "jobs/cdp/verify_cdp.py"},
}


def _write_plan_dir(plan_path: Path, group: dict[str, object]) -> None:
    """Write a directory plan with one group named ``existing``."""
    (plan_path / "groups").mkdir(parents=True)
    (plan_path / "test_cases.yaml").write_text(
        yaml.safe_dump(
            {"test_cases": {"1.0.0": {"title": "Ping", "job": "jobs/ping.py"}}}
        )
    )
    (plan_path / "groups" / "existing.yaml").write_text(
        yaml.safe_dump({"test_case_groups": {"existing": group}})
    )
    (plan_path / "scenarios.yaml").write_text(
        yaml.safe_dump(
            {
                "scenarios": {
                    "scenario-1": {
                        "phases": {"pre": {"test_case_groups": ["existing"]}}
                    }
                }
            }
        )
    )


def test_inject_new_group_writes_no_description(tmp_path: Path) -> None:
    """A group created by inject has no description key and loads as None."""
    plan_path = tmp_path / "plan"
    _write_plan_dir(plan_path, {"tests": ["1.0.0"]})

    apply_inject_plan(
        plan_path=plan_path,
        inject_plan=InjectPlan(
            new_test_cases=_NEW_TEST_CASES,
            group_id="cdp",
            group_name="CDP",
            is_new_group=True,
            phase_updates=["pre"],
        ),
    )

    raw = yaml.safe_load((plan_path / "groups" / "cdp.yaml").read_text())
    assert "description" not in raw["test_case_groups"]["cdp"]
    assert load_test_plan(plan_path).test_case_groups["cdp"].description is None


def test_inject_into_existing_group_keeps_description(tmp_path: Path) -> None:
    """Appending tests to an existing group keeps its description."""
    plan_path = tmp_path / "plan"
    _write_plan_dir(plan_path, {"description": "Baseline", "tests": ["1.0.0"]})

    apply_inject_plan(
        plan_path=plan_path,
        inject_plan=InjectPlan(
            new_test_cases=_NEW_TEST_CASES,
            group_id="existing",
            group_name=None,
            is_new_group=False,
        ),
    )

    group = load_test_plan(plan_path).test_case_groups["existing"]
    assert group.description == "Baseline"
    assert group.tests == ["1.0.0", "CDP-1"]
