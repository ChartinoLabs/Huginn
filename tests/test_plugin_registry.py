"""Unit tests for huginn.plugin_registry module."""

from unittest.mock import patch

import pytest

from huginn.plugin_registry import (
    BROKER_GROUP,
    HOOK_GROUP,
    INVENTORY_GROUP,
    REPORTER_GROUP,
    PluginConfig,
    PluginRegistry,
    PluginResolutionError,
)


class _FakeEntryPoint:
    """Simulates an importlib.metadata entry point."""

    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


class _FakeBroker:
    """Minimal broker for registry tests."""

    @property
    def name(self) -> str:
        return "fake"

    @property
    def connection_type(self) -> str:
        return "fake"


class _FakeReporter:
    """Minimal reporter for registry tests."""

    @property
    def name(self) -> str:
        return "fake-reporter"

    async def generate_report(self, **kwargs: object) -> None:
        pass


class _FakeHook:
    """Minimal hook for registry tests."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @property
    def name(self) -> str:
        return "fake-hook"

    def subscriptions(self) -> set:
        return set()

    async def on_event(self, event: object, context: dict) -> None:
        pass


def _mock_entry_points(
    mapping: dict[str, list[_FakeEntryPoint]],
) -> object:
    """Create a side_effect for entry_points(group=...) calls."""

    def _side_effect(*, group: str) -> list[_FakeEntryPoint]:
        return mapping.get(group, [])

    return _side_effect


class TestBrokerDiscovery:
    """Tests for broker plugin discovery."""

    def test_discover_all_brokers(self) -> None:
        """Registry discovers all broker entry points."""
        eps = [
            _FakeEntryPoint("ssh", _FakeBroker),
            _FakeEntryPoint("gnmi", _FakeBroker),
        ]
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({BROKER_GROUP: eps}),
        ):
            registry = PluginRegistry()
            classes = registry.discover_broker_classes()

        assert set(classes.keys()) == {"ssh", "gnmi"}

    def test_config_filters_brokers(self) -> None:
        """PluginConfig.brokers filters discovered brokers."""
        eps = [
            _FakeEntryPoint("ssh", _FakeBroker),
            _FakeEntryPoint("gnmi", _FakeBroker),
        ]
        config = PluginConfig(brokers=["ssh"])
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({BROKER_GROUP: eps}),
        ):
            registry = PluginRegistry(config=config)
            classes = registry.discover_broker_classes()

        assert set(classes.keys()) == {"ssh"}

    def test_resolve_broker_instantiates(self) -> None:
        """resolve_broker returns an instance of the broker class."""
        eps = [_FakeEntryPoint("ssh", _FakeBroker)]
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({BROKER_GROUP: eps}),
        ):
            registry = PluginRegistry()
            broker = registry.resolve_broker("ssh")

        assert isinstance(broker, _FakeBroker)

    def test_resolve_broker_raises_for_unknown(self) -> None:
        """resolve_broker raises PluginResolutionError for unknown type."""
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({BROKER_GROUP: []}),
        ):
            registry = PluginRegistry()
            with pytest.raises(PluginResolutionError, match="No broker plugin"):
                registry.resolve_broker("gnmi")

    def test_resolve_broker_raises_when_disabled(self) -> None:
        """resolve_broker raises if broker is installed but not enabled."""
        eps = [_FakeEntryPoint("gnmi", _FakeBroker)]
        config = PluginConfig(brokers=["ssh"])
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({BROKER_GROUP: eps}),
        ):
            registry = PluginRegistry(config=config)
            with pytest.raises(PluginResolutionError, match="not enabled"):
                registry.resolve_broker("gnmi")


class TestInventoryDiscovery:
    """Tests for inventory plugin discovery."""

    def test_resolve_inventory_plugin_class(self) -> None:
        """Registry finds inventory plugin by name."""

        class _FakeInventory:
            pass

        eps = [_FakeEntryPoint("netbox", _FakeInventory)]
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({INVENTORY_GROUP: eps}),
        ):
            registry = PluginRegistry()
            cls = registry.resolve_inventory_plugin_class("netbox")

        assert cls is _FakeInventory

    def test_resolve_inventory_plugin_raises_for_unknown(self) -> None:
        """Unknown inventory plugin name raises PluginResolutionError."""
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({INVENTORY_GROUP: []}),
        ):
            registry = PluginRegistry()
            with pytest.raises(PluginResolutionError, match="No inventory plugin"):
                registry.resolve_inventory_plugin_class("unknown")


class TestReporterDiscovery:
    """Tests for reporter plugin discovery."""

    def test_resolve_reporters_instantiates_all(self) -> None:
        """Registry instantiates all discovered reporters."""
        eps = [_FakeEntryPoint("fake", _FakeReporter)]
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({REPORTER_GROUP: eps}),
        ):
            registry = PluginRegistry()
            reporters = registry.resolve_reporters()

        assert len(reporters) == 1
        assert reporters[0].name == "fake-reporter"

    def test_empty_reporters_config_disables_all(self) -> None:
        """Empty reporters list in config disables reporting."""
        config = PluginConfig(reporters=[])
        registry = PluginRegistry(config=config)
        reporters = registry.resolve_reporters()

        assert reporters == []

    def test_config_filters_reporters(self) -> None:
        """PluginConfig.reporters filters to specified names."""
        eps = [
            _FakeEntryPoint("html", _FakeReporter),
            _FakeEntryPoint("junit", _FakeReporter),
        ]
        config = PluginConfig(reporters=["html"])
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({REPORTER_GROUP: eps}),
        ):
            registry = PluginRegistry(config=config)
            reporters = registry.resolve_reporters()

        assert len(reporters) == 1


class TestHookDiscovery:
    """Tests for hook plugin discovery."""

    def test_resolve_hooks_instantiates_all(self) -> None:
        """Registry instantiates all discovered hooks."""
        eps = [_FakeEntryPoint("fake", _FakeHook)]
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({HOOK_GROUP: eps}),
        ):
            registry = PluginRegistry()
            hooks = registry.resolve_hooks()

        assert len(hooks) == 1

    def test_empty_hooks_config_disables_all(self) -> None:
        """Empty hooks list in config disables all hooks."""
        config = PluginConfig(hooks=[])
        registry = PluginRegistry(config=config)
        hooks = registry.resolve_hooks()

        assert hooks == []

    def test_hooks_receive_plugin_config(self) -> None:
        """Hook plugins receive their config from plugin_options."""
        eps = [_FakeEntryPoint("fake", _FakeHook)]
        config = PluginConfig(
            plugin_options={"fake": {"webhook_url": "https://example.com"}}
        )
        with patch(
            "huginn.plugin_registry.entry_points",
            side_effect=_mock_entry_points({HOOK_GROUP: eps}),
        ):
            registry = PluginRegistry(config=config)
            hooks = registry.resolve_hooks()

        assert len(hooks) == 1
        hook = hooks[0]
        assert isinstance(hook, _FakeHook)
        assert hook.config == {"webhook_url": "https://example.com"}


class TestPluginConfig:
    """Tests for PluginConfig defaults."""

    def test_default_config_has_no_filtering(self) -> None:
        """Default PluginConfig applies no filtering."""
        config = PluginConfig()

        assert config.brokers is None
        assert config.reporters is None
        assert config.hooks is None
        assert config.plugin_options == {}

    def test_get_plugin_config_returns_empty_for_unknown(self) -> None:
        """get_plugin_config returns empty dict for unconfigured plugins."""
        registry = PluginRegistry()

        assert registry.get_plugin_config("nonexistent") == {}

    def test_get_plugin_config_returns_configured_values(self) -> None:
        """get_plugin_config returns the matching config dict."""
        config = PluginConfig(plugin_options={"html": {"theme": "dark"}})
        registry = PluginRegistry(config=config)

        assert registry.get_plugin_config("html") == {"theme": "dark"}
