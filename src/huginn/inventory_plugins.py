"""Inventory plugin contract and built-in plugin resolution."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class InventoryPluginError(ValueError):
    """Raised when an inventory plugin cannot be resolved or executed."""


class InventoryPlugin(Protocol):
    """Protocol for inventory plugins that resolve testbed file paths."""

    def resolve_testbed_path(self, project_root: Path) -> Path:
        """Resolve and return a testbed file path for execution."""


@dataclass(frozen=True)
class FileInventoryPlugin:
    """Built-in plugin that resolves a testbed file path from spec input."""

    file_path: Path

    def resolve_testbed_path(self, project_root: Path) -> Path:
        """Resolve plugin file path against project root when relative."""
        if self.file_path.is_absolute():
            return self.file_path
        return (project_root / self.file_path).resolve()


def resolve_inventory_testbed_path(
    *,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    project_root: Path,
) -> Path:
    """Resolve testbed path from explicit file or inventory plugin spec."""
    if testbed_path is not None and inventory_plugin is not None:
        raise InventoryPluginError(
            "--testbed and --inventory-plugin are mutually exclusive."
        )

    if testbed_path is not None:
        return testbed_path

    if inventory_plugin is None:
        raise InventoryPluginError(
            "Either --testbed or --inventory-plugin must be specified."
        )

    plugin = _parse_inventory_plugin_spec(inventory_plugin)
    resolved_testbed = plugin.resolve_testbed_path(project_root)
    if not resolved_testbed.exists() or not resolved_testbed.is_file():
        raise InventoryPluginError(
            f"Inventory plugin resolved missing testbed file: {resolved_testbed}"
        )
    return resolved_testbed


def _parse_inventory_plugin_spec(spec: str) -> InventoryPlugin:
    """Parse inventory plugin specification string into plugin object."""
    if ":" not in spec:
        raise InventoryPluginError(
            "Inventory plugin must use '<plugin>:<config>' format, "
            "for example 'file:testbed.yaml'."
        )

    plugin_name, config = spec.split(":", maxsplit=1)
    if plugin_name != "file":
        raise InventoryPluginError(
            f"Unsupported inventory plugin '{plugin_name}'. Supported: file"
        )
    if not config:
        raise InventoryPluginError(
            "Inventory plugin 'file' requires a testbed file path, "
            "for example 'file:testbed.yaml'."
        )

    return FileInventoryPlugin(file_path=Path(config))
