"""Unit tests for scope providers used by ``huginn import``."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner, Result

from huginn.catalog_import import Catalog, Scope, ScopedDevice, Taxonomy
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
    ScopeRequest,
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


class _FailingEntryPoint:
    """Entry point whose module raises when imported, recording each attempt."""

    def __init__(self, name: str, error: Exception) -> None:
        self.name = name
        self.error = error
        self.load_calls = 0

    def load(self) -> type:
        self.load_calls += 1
        raise self.error


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


class _RequestProvider:
    """Provider that takes a ``ScopeRequest`` and records the last one."""

    last_request: ScopeRequest | None = None

    def __init__(self, config: str) -> None:
        self.config = config

    def resolve_scope(self, request: ScopeRequest) -> Scope:
        type(self).last_request = request
        return Scope(devices=(ScopedDevice("r1", "alpha", (self.config,)),))


class _AsyncRequestProvider:
    """Provider that takes a ``ScopeRequest`` in a coroutine."""

    def __init__(self, config: str) -> None:
        self.config = config

    async def resolve_scope(self, request: ScopeRequest) -> Scope:
        assert request.testbed is not None
        return Scope(
            devices=tuple(
                ScopedDevice(name, "alpha", (self.config,))
                for name in request.testbed.devices
            )
        )


_PROVIDERS = [
    _FakeEntryPoint("request", _RequestProvider),
    _FakeEntryPoint("async-request", _AsyncRequestProvider),
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
    plan_path: Path | None = None,
    catalog: Catalog | None = None,
) -> Scope:
    return await resolve_scope(
        scope_path=scope_path,
        scope_provider=scope_provider,
        project_root=project_root or Path.cwd(),
        testbed=testbed,
        registry=PluginRegistry(),
        plan_path=plan_path,
        catalog=catalog,
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
async def test_request_provider_receives_scope_request(
    providers: None, tmp_path: Path
) -> None:
    """A one-argument provider gets the plan path, catalog and taxonomy."""
    taxonomy = Taxonomy(os_aliases={"alpha-os": "alpha"})
    catalog = Catalog(entries=(), taxonomy=taxonomy, source="cat")
    testbed = _testbed()
    scope = await _resolve(
        scope_provider="request:peering",
        project_root=tmp_path,
        testbed=testbed,
        plan_path=tmp_path / "test_plan",
        catalog=catalog,
    )
    assert scope.devices[0].features == ("peering",)
    assert _RequestProvider.last_request == ScopeRequest(
        project_root=tmp_path,
        testbed=testbed,
        plan_path=tmp_path / "test_plan",
        catalog=catalog,
        taxonomy=taxonomy,
    )


@pytest.mark.asyncio
async def test_request_provider_without_context(providers: None) -> None:
    """Callers that pass no plan or catalog give the provider ``None``."""
    await _resolve(scope_provider="request:x")
    request = _RequestProvider.last_request
    assert request is not None
    assert (request.plan_path, request.catalog, request.taxonomy) == (None,) * 3


@pytest.mark.asyncio
async def test_request_provider_may_be_async(providers: None) -> None:
    """A one-argument provider can also be a coroutine."""
    scope = await _resolve(scope_provider="async-request:peering", testbed=_testbed())
    assert [d.name for d in scope.devices] == ["r1", "r2"]


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        (lambda request: None, True),
        (lambda request, *, extra=None: None, True),
        (lambda project_root, testbed: None, False),
        (lambda project_root, testbed=None: None, False),
        (lambda *args: None, False),
        (lambda: None, False),
    ],
)
def test_provider_signature_detection(
    method: Callable[..., object], expected: bool
) -> None:
    """Only a method taking exactly one positional argument gets a request."""
    from huginn.scope_providers import _takes_one_argument

    assert _takes_one_argument(method) is expected


def test_scope_request_taxonomy_defaults_to_catalog_taxonomy(tmp_path: Path) -> None:
    """A request built with only a catalog exposes the catalog's taxonomy."""
    taxonomy = Taxonomy(always_include=("base",))
    catalog = Catalog(entries=(), taxonomy=taxonomy)
    request = ScopeRequest(project_root=tmp_path, testbed=None, catalog=catalog)
    assert request.taxonomy is taxonomy


@pytest.mark.asyncio
async def test_exactly_one_scope_source(tmp_path: Path) -> None:
    """Both or neither of a scope file and a provider is an error."""
    with pytest.raises(ScopeProviderError, match="exactly one"):
        await _resolve()
    with pytest.raises(ScopeProviderError, match="exactly one"):
        await _resolve(scope_path=tmp_path / "s.yaml", scope_provider="file:s.yaml")


def test_registry_lists_available_providers(providers: None) -> None:
    """An unknown provider name lists what is available, including ``file``."""
    with pytest.raises(
        PluginResolutionError, match="'async', 'async-request', 'broken'"
    ):
        PluginRegistry().resolve_scope_provider_class("missing")
    assert PluginRegistry().resolve_scope_provider_class("devices") is (
        _DeviceListProvider
    )


@pytest.fixture
def failing_provider() -> Iterator[_FailingEntryPoint]:
    """Register the fake providers plus one whose module fails to import."""
    failing = _FailingEntryPoint("bad-import", ModuleNotFoundError("no 'lab_sdk'"))

    def _entry_points(*, group: str) -> list[object]:
        return [*_PROVIDERS, failing] if group == SCOPE_PROVIDER_GROUP else []

    with patch("huginn.plugin_registry.entry_points", side_effect=_entry_points):
        yield failing


def test_registry_imports_only_the_requested_provider(
    failing_provider: _FailingEntryPoint,
) -> None:
    """Selecting one provider never imports the other registered providers."""
    assert PluginRegistry().resolve_scope_provider_class("devices") is (
        _DeviceListProvider
    )
    with pytest.raises(PluginResolutionError, match="No scope provider found"):
        PluginRegistry().resolve_scope_provider_class("missing")
    assert failing_provider.load_calls == 0


def test_registry_lists_providers_that_fail_to_import(
    failing_provider: _FailingEntryPoint,
) -> None:
    """An unknown name lists every registered name, without importing any."""
    with pytest.raises(PluginResolutionError, match="'bad-import'"):
        PluginRegistry().resolve_scope_provider_class("missing")
    assert failing_provider.load_calls == 0


def test_requested_provider_import_failure_is_an_error(
    failing_provider: _FailingEntryPoint,
) -> None:
    """The requested provider failing to import raises, naming the cause."""
    with pytest.raises(
        PluginResolutionError,
        match=r"Scope provider 'bad-import' could not be imported: "
        r"ModuleNotFoundError: no 'lab_sdk'",
    ) as excinfo:
        PluginRegistry().resolve_scope_provider_class("bad-import")
    assert excinfo.value.__cause__ is failing_provider.error
    assert failing_provider.load_calls == 1


def test_cli_reports_provider_import_failure(
    project: Path, failing_provider: _FailingEntryPoint
) -> None:
    """The CLI exits 1 with the import error of the requested provider."""
    result = _invoke("--scope-provider", "bad-import")
    assert result.exit_code == 1
    assert "could not be imported" in result.output
    assert "ModuleNotFoundError: no 'lab_sdk'" in result.output


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


def test_cli_passes_plan_and_catalog_to_provider(
    project: Path, providers: None
) -> None:
    """``huginn import`` gives the provider the plan path and loaded catalog."""
    _RequestProvider.last_request = None
    result = _invoke("--scope-provider", "request:peer sessions", "--dry-run")
    assert result.exit_code == 0, result.output
    request = _RequestProvider.last_request
    assert request is not None
    assert request.project_root == project
    assert request.plan_path == project / "test_plan"
    assert request.testbed is not None
    assert set(request.testbed.devices) == {"r1", "r2"}
    assert request.catalog is not None
    assert request.catalog.entries
    assert request.taxonomy is request.catalog.taxonomy


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
