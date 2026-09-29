"""Tests for testbed device `metadata` loading and read-only behavior."""

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from huginn.inventory_plugins import resolve_inventory_testbed
from huginn.loaders import ConfigurationError, load_testbed
from huginn.models import Device, Testbed as HuginnTestbed


def _write_testbed(tmp_path: Path, device_body: str) -> Path:
    """Write a one-device testbed whose `spine-01` body is `device_body`."""
    path = tmp_path / "testbed.yaml"
    path.write_text(
        "devices:\n  spine-01:\n    os: nxos\n" + device_body, encoding="utf-8"
    )
    return path


def _load_device(tmp_path: Path, device_body: str) -> Device:
    """Load the `spine-01` device from a one-device testbed."""
    return load_testbed(_write_testbed(tmp_path, device_body)).devices["spine-01"]


_METADATA = (
    "    metadata:\n"
    "      role: spine\n"
    "      rack: 12\n"
    "      managed: true\n"
    "      owner: null\n"
    "      uplinks: [leaf-01, leaf-02]\n"
    "      oob:\n"
    "        ip: 192.0.2.1\n"
)


def test_load_testbed_parses_device_metadata_of_any_yaml_type(tmp_path: Path) -> None:
    """Metadata values keep their YAML types, including nested containers."""
    device = _load_device(tmp_path, _METADATA)

    assert device.metadata == {
        "role": "spine",
        "rack": 12,
        "managed": True,
        "owner": None,
        "uplinks": ["leaf-01", "leaf-02"],
        "oob": {"ip": "192.0.2.1"},
    }


@pytest.mark.parametrize("body", ["", "    metadata:\n", "    metadata: {}\n"])
def test_load_testbed_device_metadata_defaults_to_empty(
    tmp_path: Path, body: str
) -> None:
    """A missing, null or empty `metadata` loads as an empty mapping."""
    assert _load_device(tmp_path, body).metadata == {}


@pytest.mark.parametrize("value", ["[a, b]", "spine", "12"])
def test_load_testbed_rejects_non_mapping_device_metadata(
    tmp_path: Path, value: str
) -> None:
    """`metadata` must be a mapping, and the error names the device."""
    path = _write_testbed(tmp_path, f"    metadata: {value}\n")

    with pytest.raises(
        ConfigurationError, match="Device 'spine-01' metadata must be a mapping"
    ):
        load_testbed(path)


def test_load_testbed_expands_env_vars_in_device_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`${VAR}` references expand in nested metadata strings, not in keys."""
    monkeypatch.setenv("SITE", "dc2")
    monkeypatch.delenv("RACK", raising=False)
    device = _load_device(
        tmp_path,
        "    metadata:\n"
        "      site: ${SITE}\n"
        "      ${SITE}: key\n"
        "      location:\n"
        "        rack: ${RACK:-r5}\n"
        "      tags: ['${SITE}-core']\n",
    )

    assert device.metadata == {
        "site": "dc2",
        "${SITE}": "key",
        "location": {"rack": "r5"},
        "tags": ["dc2-core"],
    }


def test_device_metadata_is_read_only_including_nested_values(
    tmp_path: Path,
) -> None:
    """The metadata mapping and its nested mappings and lists reject changes."""
    metadata = cast(dict[str, Any], _load_device(tmp_path, _METADATA).metadata)

    with pytest.raises(TypeError, match="read-only"):
        metadata["role"] = "leaf"
    with pytest.raises(TypeError, match="read-only"):
        metadata.pop("role")
    with pytest.raises(TypeError, match="read-only"):
        metadata["oob"]["ip"] = "192.0.2.2"
    with pytest.raises(TypeError, match="read-only"):
        metadata["uplinks"].append("leaf-03")
    assert metadata["uplinks"] == ["leaf-01", "leaf-02"]
    assert metadata["oob"] == {"ip": "192.0.2.1"}


def test_device_metadata_deepcopy_is_mutable_and_serializes(tmp_path: Path) -> None:
    """`copy.deepcopy` returns plain containers; JSON and YAML dumps work."""
    device = _load_device(tmp_path, _METADATA)

    mutable = cast(dict[str, Any], copy.deepcopy(device.metadata))
    mutable["uplinks"].append("leaf-03")
    mutable["oob"]["ip"] = "192.0.2.2"

    assert type(mutable) is dict
    assert type(mutable["oob"]) is dict
    assert type(mutable["uplinks"]) is list
    assert device.metadata["uplinks"] == ["leaf-01", "leaf-02"]
    assert device.metadata["oob"] == {"ip": "192.0.2.1"}
    assert json.loads(json.dumps(device.metadata)) == device.metadata
    assert yaml.safe_load(yaml.safe_dump(device.metadata)) == device.metadata


def test_device_constructed_directly_freezes_metadata() -> None:
    """Devices built in code, as inventory plugins do, get read-only metadata."""
    source: dict[str, object] = {"site": "dc1", "uplinks": ["leaf-01"]}
    device = Device(name="spine-01", os="nxos", metadata=source)
    source["site"] = "changed"

    assert device.metadata == {"site": "dc1", "uplinks": ["leaf-01"]}
    with pytest.raises(TypeError, match="read-only"):
        cast(list[str], device.metadata["uplinks"]).append("leaf-02")
    assert Device(name="leaf-01", os="nxos").metadata == {}


@pytest.mark.asyncio
async def test_inventory_plugin_devices_default_and_freeze_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Plugin-built devices default to empty metadata or keep it read-only."""

    class _Plugin:
        def resolve_testbed(self, project_root: Path) -> HuginnTestbed:
            return HuginnTestbed(
                devices={
                    "leaf-01": Device(name="leaf-01", os="nxos"),
                    "spine-01": Device(
                        name="spine-01", os="nxos", metadata={"role": "spine"}
                    ),
                }
            )

    monkeypatch.setattr(
        "huginn.inventory_plugins._parse_inventory_plugin_spec",
        lambda _spec, **_kwargs: _Plugin(),
    )

    testbed = await resolve_inventory_testbed(
        testbed_path=None, inventory_plugin="custom:any", project_root=tmp_path
    )

    assert testbed.devices["leaf-01"].metadata == {}
    spine_metadata = cast(dict[str, object], testbed.devices["spine-01"].metadata)
    assert spine_metadata == {"role": "spine"}
    with pytest.raises(TypeError, match="read-only"):
        spine_metadata["role"] = "leaf"


def test_device_equality_includes_metadata_and_device_is_unhashable() -> None:
    """Devices compare by value including metadata; they are not hashable."""
    device = Device(name="spine-01", os="nxos", metadata={"role": "spine"})

    assert device == Device(name="spine-01", os="nxos", metadata={"role": "spine"})
    assert device != Device(name="spine-01", os="nxos", metadata={"role": "leaf"})
    assert device in [Device(name="spine-01", os="nxos", metadata={"role": "spine"})]
    with pytest.raises(TypeError, match="unhashable"):
        hash(device)
