"""Inventory plugin contract and built-in plugin resolution."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Protocol

from huginn.loaders import load_testbed
from huginn.models import Testbed
from huginn.plugin_registry import PluginRegistry, PluginResolutionError


class InventoryPluginError(ValueError):
    """Raised when an inventory plugin cannot be resolved or executed."""


class InventoryPlugin(Protocol):
    """Protocol for inventory plugins that resolve Testbed objects."""

    def resolve_testbed(self, project_root: Path) -> Testbed | Awaitable[Testbed]:
        """Resolve and return a testbed object for execution."""
        raise NotImplementedError


@dataclass(frozen=True)
class FileInventoryPlugin:
    """Built-in plugin that loads a testbed from a file path."""

    file_path: Path

    async def resolve_testbed(self, project_root: Path) -> Testbed:
        """Resolve plugin file path and load the resulting testbed."""
        if self.file_path.is_absolute():
            resolved_path = self.file_path
        else:
            resolved_path = (project_root / self.file_path).resolve()

        if not resolved_path.exists() or not resolved_path.is_file():
            raise InventoryPluginError(
                f"Inventory plugin resolved missing testbed file: {resolved_path}"
            )

        return load_testbed(resolved_path)


async def resolve_inventory_testbed(
    *,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    project_root: Path,
    registry: PluginRegistry | None = None,
) -> Testbed:
    """Resolve testbed object from explicit file or inventory plugin spec."""
    if testbed_path is not None and inventory_plugin is not None:
        raise InventoryPluginError(
            "--testbed and --inventory-plugin are mutually exclusive."
        )

    if testbed_path is not None:
        return load_testbed(testbed_path)

    if inventory_plugin is None:
        raise InventoryPluginError(
            "Either --testbed or --inventory-plugin must be specified."
        )

    plugin = _parse_inventory_plugin_spec(inventory_plugin, registry=registry)
    return await _resolve_plugin_testbed(plugin=plugin, project_root=project_root)


async def _resolve_plugin_testbed(
    *,
    plugin: InventoryPlugin,
    project_root: Path,
) -> Testbed:
    """Resolve a testbed from plugin, supporting sync and async plugin methods."""
    resolved = plugin.resolve_testbed(project_root)
    if isawaitable(resolved):
        awaited = await resolved
        return _ensure_testbed(awaited)
    return _ensure_testbed(resolved)


def _ensure_testbed(value: object) -> Testbed:
    """Validate plugin output is a Testbed instance."""
    if not isinstance(value, Testbed):
        raise InventoryPluginError("Inventory plugin must resolve a Testbed object")
    return value


def _parse_inventory_plugin_spec(
    spec: str,
    *,
    registry: PluginRegistry | None = None,
) -> InventoryPlugin:
    """Parse inventory plugin specification string into plugin object.

    When a registry is provided, plugin names are resolved via entry point
    discovery. Otherwise, only the built-in 'file' plugin is supported.
    """
    if ":" not in spec:
        raise InventoryPluginError(
            "Inventory plugin must use '<plugin>:<config>' format, "
            "for example 'file:testbed.yaml'."
        )

    plugin_name, config = spec.split(":", maxsplit=1)

    if plugin_name == "file":
        if not config:
            raise InventoryPluginError(
                "Inventory plugin 'file' requires a testbed file path, "
                "for example 'file:testbed.yaml'."
            )
        return FileInventoryPlugin(file_path=Path(config))

    if registry is not None:
        try:
            plugin_cls = registry.resolve_inventory_plugin_class(plugin_name)
        except PluginResolutionError as error:
            raise InventoryPluginError(str(error)) from error
        return plugin_cls(config=config)

    raise InventoryPluginError(
        f"Unsupported inventory plugin '{plugin_name}'. "
        "Provide a plugin registry to discover third-party inventory plugins. "
        "Built-in plugins: file"
    )
