"""Unit tests for learned parameter persistence helpers."""

import json
from pathlib import Path

import pytest

from huginn.parameters import (
    ParameterManager,
    ParameterStoreError,
    list_available_parameters,
    load_test_case_parameters,
)


@pytest.mark.asyncio
async def test_parameter_manager_saves_and_loads_payload(tmp_path: Path) -> None:
    """Saved parameters are loaded back from per-test JSON file."""
    manager = ParameterManager(parameters_dir=tmp_path / "parameters", test_id="1.0.0")
    payload = {"neighbors": ["10.0.0.1"], "count": 1}

    await manager.save(payload)
    loaded = await manager.load()

    assert loaded == payload


@pytest.mark.asyncio
async def test_parameter_manager_load_raises_for_missing_file(tmp_path: Path) -> None:
    """Loading missing learned parameters raises a descriptive error."""
    manager = ParameterManager(parameters_dir=tmp_path / "parameters", test_id="1.0.0")

    with pytest.raises(ParameterStoreError, match="No learned parameters found"):
        await manager.load()


@pytest.mark.asyncio
async def test_parameter_manager_save_rejects_non_serializable_payload(
    tmp_path: Path,
) -> None:
    """Non-JSON-serializable payloads are rejected with ParameterStoreError."""
    manager = ParameterManager(parameters_dir=tmp_path / "parameters", test_id="1.0.0")

    with pytest.raises(ParameterStoreError, match="Unable to serialize"):
        await manager.save({"bad": {1, 2, 3}})


@pytest.mark.asyncio
async def test_parameter_manager_writes_expected_json_file(tmp_path: Path) -> None:
    """Save writes to <parameters_dir>/<test_id>.json."""
    parameters_dir = tmp_path / "parameters"
    manager = ParameterManager(parameters_dir=parameters_dir, test_id="2.1.0")

    await manager.save({"ok": True})

    parameter_file = parameters_dir / "2.1.0.json"
    assert parameter_file.exists()
    assert json.loads(parameter_file.read_text(encoding="utf-8")) == {"ok": True}


# --- Synchronous SDK helpers ---


def test_load_test_case_parameters_returns_learned_data(tmp_path: Path) -> None:
    """load_test_case_parameters reads a previously saved parameter file."""
    params_dir = tmp_path / "parameters"
    params_dir.mkdir()
    (params_dir / "1.0.0.json").write_text('{"bgp_as": 65000}', encoding="utf-8")

    result = load_test_case_parameters(params_dir, "1.0.0")

    assert result == {"bgp_as": 65000}


def test_load_test_case_parameters_returns_none_when_absent(tmp_path: Path) -> None:
    """load_test_case_parameters returns None for a test with no learned params."""
    assert load_test_case_parameters(tmp_path, "missing") is None


def test_load_test_case_parameters_raises_on_invalid_json(tmp_path: Path) -> None:
    """load_test_case_parameters raises ParameterStoreError for malformed JSON."""
    params_dir = tmp_path / "parameters"
    params_dir.mkdir()
    (params_dir / "bad.json").write_text("{not valid", encoding="utf-8")

    with pytest.raises(ParameterStoreError, match="Unable to read"):
        load_test_case_parameters(params_dir, "bad")


def test_load_test_case_parameters_raises_on_non_mapping(tmp_path: Path) -> None:
    """load_test_case_parameters rejects a JSON file whose root is not a dict."""
    params_dir = tmp_path / "parameters"
    params_dir.mkdir()
    (params_dir / "list.json").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ParameterStoreError, match="must be a mapping"):
        load_test_case_parameters(params_dir, "list")


def test_list_available_parameters_finds_json_files(tmp_path: Path) -> None:
    """list_available_parameters discovers all learned parameter files."""
    params_dir = tmp_path / "parameters"
    params_dir.mkdir()
    (params_dir / "1.0.0.json").write_text("{}", encoding="utf-8")
    (params_dir / "2.0.0.json").write_text("{}", encoding="utf-8")
    (params_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    result = list_available_parameters(params_dir)

    assert set(result.keys()) == {"1.0.0", "2.0.0"}
    assert result["1.0.0"] == params_dir / "1.0.0.json"


def test_list_available_parameters_returns_empty_for_missing_dir(
    tmp_path: Path,
) -> None:
    """list_available_parameters returns empty dict when the directory is absent."""
    assert list_available_parameters(tmp_path / "nonexistent") == {}
