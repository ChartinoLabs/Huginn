"""Plugin discovery and resolution for Huginn.

Provides a central registry that discovers plugins via Python entry
points (importlib.metadata) and resolves them based on user configuration.

Resolution order for all plugin types:
    1. Explicit configuration in PluginConfig (from [tool.huginn.plugins])
    2. Entry point discovery via importlib.metadata.entry_points(group=...)
"""

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from huginn.brokers.protocol import ConnectionBrokerProtocolV1
from huginn.hooks import HookPlugin
from huginn.reporting.protocol import ReporterPlugin

logger = logging.getLogger(__name__)

BROKER_GROUP = "huginn.brokers"
INVENTORY_GROUP = "huginn.inventory"
REPORTER_GROUP = "huginn.reporters"
HOOK_GROUP = "huginn.hooks"


class PluginResolutionError(ValueError):
    """Raised when a requested plugin cannot be found or loaded."""


@dataclass(frozen=True)
class PluginConfig:
    """Configuration for plugin resolution.

    Attributes:
        brokers: List of broker entry point names to activate. None means
            all discovered brokers are available.
        reporters: List of reporter entry point names to activate. None
            means all discovered reporters are active. Empty list disables
            all reporting.
        hooks: List of hook entry point names to activate. None means all
            discovered hooks are active. Empty list disables all hooks.
        plugin_options: Per-plugin configuration dicts, keyed by plugin
            name. Passed to plugins that accept a config parameter.
    """

    brokers: list[str] | None = None
    reporters: list[str] | None = None
    hooks: list[str] | None = None
    plugin_options: dict[str, dict[str, Any]] = field(default_factory=dict)


class PluginRegistry:
    """Central registry for discovering and instantiating plugins."""

    def __init__(self, config: PluginConfig | None = None) -> None:
        """Initialize the registry with optional plugin configuration."""
        self._config = config or PluginConfig()

    def discover_broker_classes(self) -> dict[str, type]:
        """Discover all available broker plugin classes.

        Returns:
            Mapping of entry point name to broker class.
        """
        discovered = _load_entry_point_classes(BROKER_GROUP)
        if self._config.brokers is not None:
            return {
                name: cls
                for name, cls in discovered.items()
                if name in self._config.brokers
            }
        return discovered

    def resolve_broker(self, broker_type: str) -> ConnectionBrokerProtocolV1:
        """Instantiate a single broker by its entry point name.

        Args:
            broker_type: The broker name (e.g., 'ssh', 'http', 'netconf').

        Returns:
            An instantiated broker conforming to ConnectionBrokerProtocolV1.

        Raises:
            PluginResolutionError: If the broker cannot be found.
        """
        classes = self.discover_broker_classes()
        broker_cls = classes.get(broker_type)
        if broker_cls is None:
            all_discovered = _load_entry_point_classes(BROKER_GROUP)
            if broker_type in all_discovered:
                raise PluginResolutionError(
                    f"Broker '{broker_type}' is installed but not enabled "
                    f"in plugin configuration. Enabled brokers: "
                    f"{self._config.brokers}"
                )
            available = sorted(all_discovered.keys())
            raise PluginResolutionError(
                f"No broker plugin found for '{broker_type}'. Available: {available}"
            )
        return broker_cls()

    def resolve_brokers(
        self, required: set[str]
    ) -> dict[str, ConnectionBrokerProtocolV1]:
        """Instantiate all required brokers.

        Args:
            required: Set of broker names needed for the run.

        Returns:
            Mapping of broker name to instantiated broker.
        """
        return {name: self.resolve_broker(name) for name in required}

    def resolve_inventory_plugin_class(self, plugin_name: str) -> type:
        """Resolve an inventory plugin class by entry point name.

        Args:
            plugin_name: The inventory plugin name (e.g., 'file').

        Returns:
            The inventory plugin class.

        Raises:
            PluginResolutionError: If the plugin cannot be found.
        """
        classes = _load_entry_point_classes(INVENTORY_GROUP)
        plugin_cls = classes.get(plugin_name)
        if plugin_cls is None:
            available = sorted(classes.keys())
            raise PluginResolutionError(
                f"No inventory plugin found for '{plugin_name}'. Available: {available}"
            )
        return plugin_cls

    def resolve_reporters(self) -> list[ReporterPlugin]:
        """Instantiate all active reporter plugins.

        Returns:
            List of instantiated reporters. May be empty if reporting is
            disabled via configuration.
        """
        if self._config.reporters is not None and len(self._config.reporters) == 0:
            return []

        classes = _load_entry_point_classes(REPORTER_GROUP)

        if self._config.reporters is not None:
            filtered = {
                name: cls
                for name, cls in classes.items()
                if name in self._config.reporters
            }
        else:
            filtered = classes

        reporters: list[ReporterPlugin] = []
        for name, cls in filtered.items():
            try:
                reporters.append(cls())
            except Exception:
                logger.warning(
                    "Failed to instantiate reporter plugin '%s'",
                    name,
                    exc_info=True,
                )
        return reporters

    def resolve_hooks(self) -> list[HookPlugin]:
        """Instantiate all active hook plugins.

        Returns:
            List of instantiated hooks. May be empty if hooks are disabled
            or none are installed.
        """
        if self._config.hooks is not None and len(self._config.hooks) == 0:
            return []

        classes = _load_entry_point_classes(HOOK_GROUP)

        if self._config.hooks is not None:
            filtered = {
                name: cls for name, cls in classes.items() if name in self._config.hooks
            }
        else:
            filtered = classes

        hooks: list[HookPlugin] = []
        for name, cls in filtered.items():
            config = self._config.plugin_options.get(name, {})
            try:
                if config:
                    hooks.append(cls(config=config))
                else:
                    hooks.append(cls())
            except Exception:
                logger.warning(
                    "Failed to instantiate hook plugin '%s'",
                    name,
                    exc_info=True,
                )
        return hooks

    def get_plugin_config(self, plugin_name: str) -> dict[str, Any]:
        """Retrieve plugin-specific configuration.

        Args:
            plugin_name: The plugin name to look up.

        Returns:
            The configuration dict, or empty dict if not configured.
        """
        return self._config.plugin_options.get(plugin_name, {})


def _load_entry_point_classes(group: str) -> dict[str, type]:
    """Load all entry point classes for a given group.

    Args:
        group: The entry point group name (e.g., 'huginn.brokers').

    Returns:
        Mapping of entry point name to loaded class.
    """
    discovered: dict[str, type] = {}
    eps = entry_points(group=group)
    for ep in eps:
        try:
            discovered[ep.name] = ep.load()
        except Exception:
            logger.warning(
                "Failed to load entry point '%s' from group '%s'",
                ep.name,
                group,
                exc_info=True,
            )
    return discovered
