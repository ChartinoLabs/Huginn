"""Unit tests for learned parameter persistence helpers."""

import json
from pathlib import Path

import pytest

from huginn.parameters import ParameterManager, ParameterStoreError


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
