"""Unit tests for inventory plugin resolution."""

from pathlib import Path

import pytest

import huginn.inventory_plugins as inventory_plugins
from huginn.inventory_plugins import (
    InventoryPluginError,
    resolve_inventory_testbed,
)
from huginn.models import Device as DeviceModel, Testbed as HuginnTestbed


@pytest.mark.asyncio
async def test_resolve_inventory_from_file_plugin(tmp_path: Path) -> None:
    """Resolve testbed object from built-in file inventory plugin spec."""
    testbed = tmp_path / "testbed.yaml"
    testbed.write_text(
        "devices:\n  leaf-01:\n    os: nxos\n",
        encoding="utf-8",
    )

    resolved = await resolve_inventory_testbed(
        testbed_path=None,
        inventory_plugin="file:testbed.yaml",
        project_root=tmp_path,
    )

    assert set(resolved.devices.keys()) == {"leaf-01"}


@pytest.mark.asyncio
async def test_resolve_inventory_rejects_unsupported_plugin(tmp_path: Path) -> None:
    """Unsupported plugin names are rejected with clear errors."""
    with pytest.raises(InventoryPluginError, match="Unsupported inventory plugin"):
        await resolve_inventory_testbed(
            testbed_path=None,
            inventory_plugin="netbox:prod",
            project_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_resolve_inventory_rejects_missing_file(tmp_path: Path) -> None:
    """File plugin must resolve to an existing file."""
    with pytest.raises(InventoryPluginError, match="resolved missing testbed file"):
        await resolve_inventory_testbed(
            testbed_path=None,
            inventory_plugin="file:missing.yaml",
            project_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_resolve_inventory_from_explicit_testbed_path(tmp_path: Path) -> None:
    """Explicit --testbed path loads and returns a Testbed object."""
    testbed = tmp_path / "testbed.yaml"
    testbed.write_text(
        "devices:\n  spine-01:\n    os: eos\n",
        encoding="utf-8",
    )

    resolved = await resolve_inventory_testbed(
        testbed_path=testbed,
        inventory_plugin=None,
        project_root=tmp_path,
    )

    assert set(resolved.devices.keys()) == {"spine-01"}


@pytest.mark.asyncio
async def test_resolve_inventory_supports_sync_plugin_implementations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Async resolver accepts plugins that return Testbed synchronously."""

    class _SyncPlugin:
        def resolve_testbed(self, project_root: Path) -> HuginnTestbed:
            return HuginnTestbed(
                devices={"leaf-01": DeviceModel(name="leaf-01", os="nxos")}
            )

    monkeypatch.setattr(
        inventory_plugins,
        "_parse_inventory_plugin_spec",
        lambda _spec: _SyncPlugin(),
    )

    resolved = await resolve_inventory_testbed(
        testbed_path=None,
        inventory_plugin="sync:anything",
        project_root=tmp_path,
    )

    assert set(resolved.devices.keys()) == {"leaf-01"}
