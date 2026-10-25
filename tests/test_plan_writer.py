"""Unit tests for the shared test plan writer."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from huginn.plan_writer import (
    PlanWriteError,
    add_group_to_phases,
    cases_file_path,
    extend_group,
    extend_test_case_target,
    find_group_file,
    find_scenarios_file,
    groups_file_path,
    load_raw_yaml,
    write_group,
    write_test_cases,
)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data))


def _read(path: Path) -> Any:  # noqa: ANN401
    return yaml.safe_load(path.read_text())


def test_write_test_cases_adds_and_replaces(tmp_path: Path) -> None:
    """New IDs are added, existing IDs replaced, others kept."""
    path = cases_file_path(tmp_path, "g")
    _write(path, {"test_cases": {"A": {"title": "old"}, "B": {"title": "keep"}}})
    write_test_cases(path, {"A": {"title": "new"}, "C": {"title": "added"}})
    assert _read(path)["test_cases"] == {
        "A": {"title": "new"},
        "B": {"title": "keep"},
        "C": {"title": "added"},
    }


def test_write_group_creates_file(tmp_path: Path) -> None:
    """A group is written to a new file under ``groups/``."""
    path = groups_file_path(tmp_path, "g")
    write_group(path, "g", {"tests": ["A"]})
    assert _read(path) == {"test_case_groups": {"g": {"tests": ["A"]}}}


def test_extend_group_appends_missing_ids_only(tmp_path: Path) -> None:
    """Tests and child groups already listed are not added again."""
    path = tmp_path / "groups" / "x.yml"
    _write(path, {"test_case_groups": {"g": {"tests": ["A"]}}})
    assert extend_group(tmp_path, "g", tests=["A", "B"], groups=["child"])
    assert _read(path)["test_case_groups"] == {
        "g": {"tests": ["A", "B"], "groups": ["child"]}
    }


def test_extend_group_without_changes_leaves_file(tmp_path: Path) -> None:
    """Nothing is rewritten when every ID is already listed."""
    path = tmp_path / "groups" / "x.yaml"
    path.parent.mkdir()
    path.write_text("test_case_groups:\n  g: {tests: [A]}  # keep me\n")
    assert extend_group(tmp_path, "g", tests=["A"])
    assert "# keep me" in path.read_text()


def test_extend_group_reports_missing_group(tmp_path: Path) -> None:
    """A group defined nowhere under ``groups/`` is reported, not created."""
    assert not extend_group(tmp_path, "g", tests=["A"])
    assert find_group_file(tmp_path, "g") is None


def test_add_group_to_phases_in_every_scenario(tmp_path: Path) -> None:
    """The group is added to each named phase of each scenario, once."""
    path = tmp_path / "scenarios.yaml"
    _write(
        path,
        {
            "scenarios": {
                "one": {"phases": {"pre": {"test_case_groups": ["base"]}}},
                "two": {"phases": {"pre": {}, "post": {}}},
            }
        },
    )
    add_group_to_phases(tmp_path, "new", ["pre", "missing"])
    add_group_to_phases(tmp_path, "new", ["pre"])
    scenarios = _read(path)["scenarios"]
    assert scenarios["one"]["phases"]["pre"]["test_case_groups"] == ["base", "new"]
    assert scenarios["two"]["phases"]["pre"]["test_case_groups"] == ["new"]
    assert scenarios["two"]["phases"]["post"] == {}


def test_scenarios_file_errors(tmp_path: Path) -> None:
    """A missing scenarios file or mapping is a write error."""
    with pytest.raises(PlanWriteError, match="No scenarios.yaml"):
        find_scenarios_file(tmp_path)
    _write(tmp_path / "scenarios-main.yaml", {"other": 1})
    assert find_scenarios_file(tmp_path).name == "scenarios-main.yaml"
    with pytest.raises(PlanWriteError, match="No scenarios mapping"):
        add_group_to_phases(tmp_path, "g", ["pre"])


def test_extend_test_case_target(tmp_path: Path) -> None:
    """Target values are appended to the file that defines the test case."""
    path = tmp_path / "nested" / "cases.yaml"
    _write(path, {"test_cases": {"A": {"target": {"os": ["x"]}}, "B": {}}})
    assert extend_test_case_target(tmp_path, "A", "os", ["x", "y"])
    assert _read(path)["test_cases"]["A"] == {"target": {"os": ["x", "y"]}}
    assert not extend_test_case_target(tmp_path, "B", "os", ["y"])
    assert not extend_test_case_target(tmp_path, "missing", "os", ["y"])


def test_load_raw_yaml_requires_mapping(tmp_path: Path) -> None:
    """A YAML file whose root is not a mapping is rejected."""
    path = tmp_path / "x.yaml"
    path.write_text("- a\n")
    with pytest.raises(PlanWriteError, match="Expected mapping"):
        load_raw_yaml(path)
