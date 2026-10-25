"""Unit tests for scope providers used by ``huginn import``."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.catalog_import import Scope, ScopedDevice
from huginn.cli import app
from huginn.models import Device, Testbed
from huginn.plugin_registry import (
    SCOPE_PROVIDER_GROUP,
    PluginRegistry,
    PluginResolutionError,
)
from huginn.scope_providers import (
    FileScopeProvider,
    ScopeProviderError,
    resolve_scope,
)

CATALOGS = Path(__file__).resolve().parent / "fixtures" / "catalogs"
CATALOG_DIR = CATALOGS / "fake_catalog"


class _FakeEntryPoint:
    """Simulates an importlib.metadata entry point."""

    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


class _DeviceListProvider:
    """Provider that scopes every testbed device with the features in config."""

    def __init__(self, config: str) -> None:
        self.features = tuple(name for name in config.split(",") if name)

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        assert testbed is not None
        return Scope(
            devices=tuple(
                ScopedDevice(name=d.name, os=d.os, features=self.features)
                for d in testbed.devices.values()
            )
        )


class _AsyncProvider:
    """Provider whose ``resolve_scope`` is a coroutine."""

    def __init__(self, config: str) -> None:
        self.config = config

    async def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        return Scope(devices=(ScopedDevice("r1", "alpha", (self.config,)),))


class _BrokenProvider:
    """Provider that fails while resolving."""

    def __init__(self, config: str) -> None:
        pass

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        raise RuntimeError("lab unreachable")


class _WrongTypeProvider:
    """Provider that returns something other than a Scope."""

    def __init__(self, config: str) -> None:
        pass

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> object:
        return {"devices": []}


class _NoConfigProvider:
    """Provider whose constructor does not accept ``config``."""

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        return Scope(devices=())


_PROVIDERS = [
    _FakeEntryPoint("devices", _DeviceListProvider),
    _FakeEntryPoint("async", _AsyncProvider),
    _FakeEntryPoint("broken", _BrokenProvider),
    _FakeEntryPoint("wrong", _WrongTypeProvider),
    _FakeEntryPoint("noconfig", _NoConfigProvider),
]


@pytest.fixture
def providers() -> Iterator[None]:
    """Register the fake providers in the scope provider entry point group."""

    def _entry_points(*, group: str) -> list[_FakeEntryPoint]:
        return _PROVIDERS if group == SCOPE_PROVIDER_GROUP else []

    with patch("huginn.plugin_registry.entry_points", side_effect=_entry_points):
        yield


def _testbed() -> Testbed:
    return Testbed(
        devices={
            "r1": Device(name="r1", os="alpha-os"),
            "r2": Device(name="r2", os="alpha-os"),
        }
    )


def _write_scope(path: Path) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "platform_metadata": [
                    {"device_name": "r1", "os_type": "alpha", "features": ["peering"]}
                ]
            }
        )
    )
    return path


async def _resolve(
    *,
    scope_path: Path | None = None,
    scope_provider: str | None = None,
    project_root: Path | None = None,
    testbed: Testbed | None = None,
) -> Scope:
    return await resolve_scope(
        scope_path=scope_path,
        scope_provider=scope_provider,
        project_root=project_root or Path.cwd(),
        testbed=testbed,
        registry=PluginRegistry(),
    )


# ---------------------------------------------------------------------------
# Built-in file provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_path_uses_file_provider(tmp_path: Path) -> None:
    """``--scope`` reads the scope file directly."""
    scope = await _resolve(scope_path=_write_scope(tmp_path / "scope.yaml"))
    assert scope.devices == (ScopedDevice("r1", "alpha", ("peering",)),)


@pytest.mark.asyncio
async def test_file_provider_spec_is_relative_to_project(tmp_path: Path) -> None:
    """``file:<path>`` resolves a relative path against the project root."""
    _write_scope(tmp_path / "scope.yaml")
    scope = await _resolve(scope_provider="file:scope.yaml", project_root=tmp_path)
    assert scope.devices[0].name == "r1"


@pytest.mark.asyncio
async def test_file_provider_errors(tmp_path: Path) -> None:
    """A missing path or file is a provider error."""
    with pytest.raises(ScopeProviderError, match="requires a scope file path"):
        await _resolve(scope_provider="file", project_root=tmp_path)
    with pytest.raises(ScopeProviderError, match="not found"):
        await _resolve(scope_provider="file:missing.yaml", project_root=tmp_path)


def test_file_provider_is_registered_as_entry_point() -> None:
    """The installed package registers the built-in ``file`` provider."""
    from importlib.metadata import entry_points

    names = {ep.name: ep.value for ep in entry_points(group=SCOPE_PROVIDER_GROUP)}
    assert names.get("file") == "huginn.scope_providers:FileScopeProvider"
    assert FileScopeProvider(config="x").config == "x"


# ---------------------------------------------------------------------------
# Plugin providers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_provider_receives_config_and_testbed(providers: None) -> None:
    """A registered provider is built with its config and given the testbed."""
    scope = await _resolve(
        scope_provider="devices:peering,bundling", testbed=_testbed()
    )
    assert [d.name for d in scope.devices] == ["r1", "r2"]
    assert scope.devices[0].features == ("peering", "bundling")


@pytest.mark.asyncio
async def test_plugin_provider_may_be_async(providers: None) -> None:
    """A provider can return its scope from a coroutine."""
    scope = await _resolve(scope_provider="async:peering")
    assert scope.devices[0].features == ("peering",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("missing", "No scope provider found for 'missing'"),
        ("broken", "Scope provider 'broken' failed: lab unreachable"),
        ("wrong", "must return a Scope object"),
        ("noconfig", "could not be created"),
        (":x", "must be '<name>' or '<name>:<config>'"),
    ],
)
async def test_plugin_provider_errors(providers: None, spec: str, message: str) -> None:
    """Provider lookup, creation and failures become provider errors."""
    with pytest.raises(ScopeProviderError, match=message):
        await _resolve(scope_provider=spec, testbed=_testbed())


@pytest.mark.asyncio
async def test_exactly_one_scope_source(tmp_path: Path) -> None:
    """Both or neither of a scope file and a provider is an error."""
    with pytest.raises(ScopeProviderError, match="exactly one"):
        await _resolve()
    with pytest.raises(ScopeProviderError, match="exactly one"):
        await _resolve(scope_path=tmp_path / "s.yaml", scope_provider="file:s.yaml")


def test_registry_lists_available_providers(providers: None) -> None:
    """An unknown provider name lists what is available, including ``file``."""
    with pytest.raises(PluginResolutionError, match="'async', 'broken'"):
        PluginRegistry().resolve_scope_provider_class("missing")
    assert PluginRegistry().resolve_scope_provider_class("devices") is (
        _DeviceListProvider
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a plan and testbed, with the fake catalog importable."""
    monkeypatch.syspath_prepend(str(CATALOGS))
    for module in list(sys.modules):
        if module == "fake_catalog" or module.startswith("fake_catalog."):
            monkeypatch.delitem(sys.modules, module, raising=False)
    plan = tmp_path / "test_plan"
    (plan / "groups").mkdir(parents=True)
    (plan / "test_cases.yaml").write_text(
        yaml.safe_dump({"test_cases": {"1": {"title": "P", "job": "jobs/p.py"}}})
    )
    (plan / "groups" / "base.yaml").write_text(
        yaml.safe_dump({"test_case_groups": {"base": {"tests": ["1"]}}})
    )
    (plan / "scenarios.yaml").write_text(
        yaml.safe_dump(
            {"scenarios": {"s": {"phases": {"pre": {"test_case_groups": ["base"]}}}}}
        )
    )
    (tmp_path / "testbed.yaml").write_text(
        yaml.safe_dump(
            {
                "devices": {
                    name: {
                        "os": "alpha-os",
                        "connections": {
                            "cli": {"protocol": "ssh", "host": "192.0.2.1"}
                        },
                    }
                    for name in ("r1", "r2")
                }
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _invoke(*args: str) -> Result:
    return CliRunner().invoke(
        app, ["import", "--catalog", str(CATALOG_DIR), "--plan", "test_plan", *args]
    )


def test_cli_imports_from_plugin_provider(project: Path, providers: None) -> None:
    """``--scope-provider`` imports with a scope from a registered provider."""
    result = _invoke("--scope-provider", "devices:peer sessions", "--target", "devices")
    assert result.exit_code == 0, result.output
    cases = yaml.safe_load(
        (project / "test_plan" / "test_cases" / "catalog-import.yaml").read_text()
    )["test_cases"]
    assert {tuple(tc["target"]["devices"]) for tc in cases.values()} == {("r1", "r2")}


def test_cli_needs_exactly_one_scope_source(project: Path) -> None:
    """Giving both or neither scope source is a usage error."""
    neither = _invoke("--dry-run")
    assert neither.exit_code == 2
    assert "exactly one" in neither.output
    _write_scope(project / "scope.yaml")
    both = _invoke("--scope", "scope.yaml", "--scope-provider", "file:scope.yaml")
    assert both.exit_code == 2


def test_cli_reports_provider_failure(project: Path, providers: None) -> None:
    """A failing provider exits 1 with its error and writes nothing."""
    result = _invoke("--scope-provider", "broken")
    assert result.exit_code == 1
    assert "lab unreachable" in result.output
    assert not (project / "test_plan" / "test_cases").exists()
