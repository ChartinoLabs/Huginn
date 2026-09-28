"""Unit tests for data model loading and path resolution."""

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from huginn.loaders import (
    ConfigurationError,
    load_data_model,
    load_plan_data_model,
    load_test_plan,
)

_MINIMAL_PLAN = """\
test_cases:
  "1.0.0":
    title: T
    job: jobs/t.py
test_case_groups:
  g:
    tests: ["1.0.0"]
scenarios:
  s:
    phases:
      p:
        test_case_groups: [g]
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_load_data_model_deep_merges_files_recursively(tmp_path: Path) -> None:
    """Mappings from every file, including nested directories, are deep-merged."""
    _write(tmp_path / "a.yaml", "fabric:\n  name: dc1\n  bgp:\n    asn: 65000\n")
    _write(tmp_path / "sites" / "b.yml", "fabric:\n  bgp:\n    rr: [s1, s2]\n")
    _write(tmp_path / "c.yaml", "vrfs: [red]\n")

    data_model = load_data_model(tmp_path)

    assert data_model == {
        "fabric": {"name": "dc1", "bgp": {"asn": 65000, "rr": ["s1", "s2"]}},
        "vrfs": ["red"],
    }


def test_load_data_model_merges_in_discovery_order(tmp_path: Path) -> None:
    """Keys are merged in the sorted order the test plan loader uses."""
    _write(tmp_path / "b.yaml", "devices:\n  leaf: {}\n")
    _write(tmp_path / "a.yaml", "devices:\n  spine: {}\n")

    data_model = load_data_model(tmp_path)

    assert list(cast(dict[str, object], data_model["devices"])) == ["spine", "leaf"]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("fabric:\n  name: dc1\n", "fabric:\n  name: dc2\n"),
        ("fabric:\n  name: dc1\n", "fabric:\n  name: dc1\n"),
        ("vrfs: [red]\n", "vrfs: [blue]\n"),
        ("fabric:\n  name: dc1\n", "fabric: [dc1]\n"),
    ],
    ids=["scalar", "equal-scalar", "list", "mapping-vs-list"],
)
def test_load_data_model_rejects_conflicting_values(
    tmp_path: Path, first: str, second: str
) -> None:
    """A non-mapping value defined by two files names both files and the key."""
    first_path = _write(tmp_path / "a.yaml", first)
    second_path = _write(tmp_path / "b.yaml", second)

    with pytest.raises(ConfigurationError) as excinfo:
        load_data_model(tmp_path)

    message = str(excinfo.value)
    assert "Conflicting data model value at '" in message
    assert str(first_path) in message
    assert str(second_path) in message


def test_load_data_model_conflict_names_nested_key_path(tmp_path: Path) -> None:
    """The conflict error reports the full dotted key path."""
    _write(tmp_path / "a.yaml", "fabric:\n  bgp:\n    asn: 1\n")
    _write(tmp_path / "b.yaml", "fabric:\n  bgp:\n    asn: 2\n")

    with pytest.raises(ConfigurationError, match=r"at 'fabric\.bgp\.asn'"):
        load_data_model(tmp_path)


def test_load_data_model_skips_underscore_and_dot_paths(tmp_path: Path) -> None:
    """Files and directories starting with `_` or `.` are ignored."""
    _write(tmp_path / "a.yaml", "kept: true\n")
    _write(tmp_path / "_draft.yaml", "draft: true\n")
    _write(tmp_path / ".hidden.yaml", "hidden: true\n")
    _write(tmp_path / "_archive" / "old.yaml", "archived: true\n")
    _write(tmp_path / "notes.txt", "not: yaml\n")

    assert load_data_model(tmp_path) == {"kept": True}


def test_load_data_model_rejects_missing_directory(tmp_path: Path) -> None:
    """A path that does not exist raises a configuration error."""
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_data_model(tmp_path / "missing")


def test_load_data_model_rejects_empty_directory(tmp_path: Path) -> None:
    """A directory with no YAML files raises a configuration error."""
    with pytest.raises(ConfigurationError, match="contains no YAML files"):
        load_data_model(tmp_path)


def test_load_data_model_rejects_invalid_yaml(tmp_path: Path) -> None:
    """Invalid YAML raises a configuration error naming the file."""
    bad = _write(tmp_path / "bad.yaml", "fabric: [unclosed\n")

    with pytest.raises(ConfigurationError, match=str(bad)):
        load_data_model(tmp_path)


def test_load_data_model_rejects_non_mapping_root(tmp_path: Path) -> None:
    """A file whose root is not a mapping raises a configuration error."""
    _write(tmp_path / "a.yaml", "- item\n")

    with pytest.raises(ConfigurationError, match="Expected mapping"):
        load_data_model(tmp_path)


def test_load_data_model_result_is_read_only(tmp_path: Path) -> None:
    """Nested mappings and lists reject mutation."""
    _write(tmp_path / "a.yaml", "fabric:\n  leafs: [leaf-01]\n")
    data_model = load_data_model(tmp_path)
    fabric = cast(dict[str, Any], data_model["fabric"])

    with pytest.raises(TypeError, match="read-only"):
        fabric["name"] = "x"
    with pytest.raises(TypeError, match="read-only"):
        fabric["leafs"].append("leaf-02")
    assert data_model == {"fabric": {"leafs": ["leaf-01"]}}


def test_load_data_model_deepcopy_is_mutable_and_serializes(tmp_path: Path) -> None:
    """`copy.deepcopy` returns plain containers; JSON and YAML dumps work."""
    _write(tmp_path / "a.yaml", "fabric:\n  leafs: [leaf-01]\n")
    data_model = load_data_model(tmp_path)

    mutable = cast(dict[str, Any], copy.deepcopy(data_model))
    mutable["fabric"]["leafs"].append("leaf-02")

    assert type(mutable["fabric"]) is dict
    assert data_model == {"fabric": {"leafs": ["leaf-01"]}}
    assert json.loads(json.dumps(data_model)) == {"fabric": {"leafs": ["leaf-01"]}}
    assert yaml.safe_load(yaml.safe_dump(data_model)) == {
        "fabric": {"leafs": ["leaf-01"]}
    }


def test_load_plan_data_model_returns_none_when_not_configured(
    tmp_path: Path,
) -> None:
    """A plan without `data_model` and no override has no data model."""
    plan_path = _write(tmp_path / "plan.yaml", _MINIMAL_PLAN)

    assert (
        load_plan_data_model(plan_path=plan_path, test_plan=load_test_plan(plan_path))
        is None
    )


def test_load_plan_data_model_resolves_relative_to_plan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`data_model.path` is relative to the plan file's directory, not the cwd."""
    plan_path = _write(
        tmp_path / "plans" / "plan.yaml",
        "data_model:\n  path: dm\n" + _MINIMAL_PLAN,
    )
    _write(tmp_path / "plans" / "dm" / "a.yaml", "source: plan\n")
    _write(tmp_path / "dm" / "a.yaml", "source: cwd\n")
    monkeypatch.chdir(tmp_path)

    data_model = load_plan_data_model(
        plan_path=plan_path, test_plan=load_test_plan(plan_path)
    )

    assert data_model == {"source": "plan"}


def test_load_plan_data_model_resolves_relative_to_plan_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In directory mode, `data_model.path` is relative to the plan directory."""
    plan_dir = tmp_path / "plan"
    _write(plan_dir / "meta.yaml", "data_model:\n  path: _dm\n")
    _write(plan_dir / "plan.yaml", _MINIMAL_PLAN)
    _write(plan_dir / "_dm" / "a.yaml", "source: plan-dir\n")
    _write(tmp_path / "_dm" / "a.yaml", "source: cwd\n")
    monkeypatch.chdir(tmp_path)

    data_model = load_plan_data_model(
        plan_path=plan_dir, test_plan=load_test_plan(plan_dir)
    )

    assert data_model == {"source": "plan-dir"}


def test_load_plan_data_model_override_wins_and_is_cwd_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An override replaces `data_model.path` and resolves against the cwd."""
    plan_path = _write(
        tmp_path / "plans" / "plan.yaml",
        "data_model:\n  path: dm\n" + _MINIMAL_PLAN,
    )
    _write(tmp_path / "plans" / "dm" / "a.yaml", "source: plan\n")
    _write(tmp_path / "dm" / "a.yaml", "source: override\n")
    monkeypatch.chdir(tmp_path)

    data_model = load_plan_data_model(
        plan_path=plan_path,
        test_plan=load_test_plan(plan_path),
        override=Path("dm"),
    )

    assert data_model == {"source": "override"}


def test_load_plan_data_model_rejects_missing_plan_path(tmp_path: Path) -> None:
    """A `data_model.path` that does not exist raises a configuration error."""
    plan_path = _write(
        tmp_path / "plan.yaml", "data_model:\n  path: missing\n" + _MINIMAL_PLAN
    )

    with pytest.raises(ConfigurationError, match="does not exist"):
        load_plan_data_model(plan_path=plan_path, test_plan=load_test_plan(plan_path))


@pytest.mark.parametrize(
    "data_model",
    ["{}", "{path: 5}", "{path: ''}", "{path: [a]}"],
    ids=["missing", "int", "empty", "list"],
)
def test_load_test_plan_requires_string_data_model_path(
    tmp_path: Path, data_model: str
) -> None:
    """A `data_model` section must set `path` to a non-empty string."""
    plan_path = _write(
        tmp_path / "plan.yaml", f"data_model: {data_model}\n" + _MINIMAL_PLAN
    )

    with pytest.raises(ConfigurationError, match=r"'data_model\.path' must be"):
        load_test_plan(plan_path)


def test_load_test_plan_directory_requires_string_data_model_path(
    tmp_path: Path,
) -> None:
    """Directory-mode plans validate `data_model.path` too."""
    _write(tmp_path / "meta.yaml", "data_model:\n  path: 5\n")
    _write(tmp_path / "plan.yaml", _MINIMAL_PLAN)

    with pytest.raises(ConfigurationError, match=r"'data_model\.path' must be"):
        load_test_plan(tmp_path)
