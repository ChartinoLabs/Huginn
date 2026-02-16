"""Unit tests for inventory plugin resolution."""

from pathlib import Path

import pytest

from huginn.inventory_plugins import (
    InventoryPluginError,
    resolve_inventory_testbed_path,
)


def test_resolve_inventory_from_file_plugin(tmp_path: Path) -> None:
    """Resolve testbed path from built-in file inventory plugin spec."""
    testbed = tmp_path / "testbed.yaml"
    testbed.write_text("devices: {}\n", encoding="utf-8")

    resolved = resolve_inventory_testbed_path(
        testbed_path=None,
        inventory_plugin="file:testbed.yaml",
        project_root=tmp_path,
    )

    assert resolved == testbed


def test_resolve_inventory_rejects_unsupported_plugin(tmp_path: Path) -> None:
    """Unsupported plugin names are rejected with clear errors."""
    with pytest.raises(InventoryPluginError, match="Unsupported inventory plugin"):
        resolve_inventory_testbed_path(
            testbed_path=None,
            inventory_plugin="netbox:prod",
            project_root=tmp_path,
        )


def test_resolve_inventory_rejects_missing_file(tmp_path: Path) -> None:
    """File plugin must resolve to an existing file."""
    with pytest.raises(InventoryPluginError, match="resolved missing testbed file"):
        resolve_inventory_testbed_path(
            testbed_path=None,
            inventory_plugin="file:missing.yaml",
            project_root=tmp_path,
        )
