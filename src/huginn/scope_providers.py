"""Scope provider contract and built-in provider resolution.

A scope provider returns the features found on each device, for
``huginn import``. The built-in ``file`` provider reads a scope file. Other
providers are classes registered in the ``huginn.scope_providers`` entry
point group of an installed package, so a package can derive scope however
it likes, for example from device configuration.

A provider's ``resolve_scope`` takes one ``ScopeRequest``, which carries the
project root, testbed, test plan path, catalog and taxonomy. Providers that
take the original two arguments, ``(project_root, testbed)``, are still
supported: Huginn reads the method's signature to decide how to call it.
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from huginn.catalog_import import (
    Catalog,
    CatalogImportError,
    Scope,
    Taxonomy,
    load_scope,
)
from huginn.models import Testbed
from huginn.plugin_registry import PluginRegistry, PluginResolutionError


class ScopeProviderError(ValueError):
    """Raised when a scope provider cannot be resolved or fails."""


@dataclass(frozen=True)
class ScopeRequest:
    """What Huginn knows when it asks a scope provider for the scope.

    Attributes:
        project_root: The directory the command runs from.
        testbed: The testbed from ``--testbed`` or ``./testbed.yaml``, or
            None when there is none.
        plan_path: The test plan directory the import writes to, or None
            when the caller has no plan.
        catalog: The loaded catalog the scope will be matched against, or
            None when the caller has not loaded one.
        taxonomy: The catalog's taxonomy, for its feature names and
            operating system aliases. Defaults to ``catalog.taxonomy``, and
            is None when there is no catalog.
    """

    project_root: Path
    testbed: Testbed | None
    plan_path: Path | None = None
    catalog: Catalog | None = None
    taxonomy: Taxonomy | None = None

    def __post_init__(self) -> None:
        """Default the taxonomy to the catalog's."""
        if self.taxonomy is None and self.catalog is not None:
            object.__setattr__(self, "taxonomy", self.catalog.taxonomy)


class ScopeProvider(Protocol):
    """Protocol for plugins that return the features found on each device.

    Huginn constructs a provider with ``config``, the text after the colon in
    ``--scope-provider <name>:<config>`` (an empty string when there is none).
    """

    def resolve_scope(self, request: ScopeRequest) -> Scope | Awaitable[Scope]:
        """Return the scope for the request's testbed.

        Args:
            request: The project root, testbed, plan path, catalog and
                taxonomy of the command asking for the scope.
        """
        raise NotImplementedError


class LegacyScopeProvider(Protocol):
    """The original provider form, which takes two arguments.

    Still supported. New providers should implement ``ScopeProvider``.
    """

    def resolve_scope(
        self, project_root: Path, testbed: Testbed | None
    ) -> Scope | Awaitable[Scope]:
        """Return the scope for the testbed."""
        raise NotImplementedError


@dataclass(frozen=True)
class FileScopeProvider:
    """Built-in provider that reads a scope file."""

    config: str = ""

    def resolve_scope(self, project_root: Path, testbed: Testbed | None) -> Scope:
        """Load the scope file named by ``config``, relative to the project."""
        if not self.config:
            raise ScopeProviderError(
                "Scope provider 'file' requires a scope file path, "
                "for example 'file:scope.yaml'."
            )
        path = Path(self.config)
        if not path.is_absolute():
            path = project_root / path
        try:
            return load_scope(path)
        except CatalogImportError as error:
            raise ScopeProviderError(str(error)) from error


async def resolve_scope(
    *,
    scope_path: Path | None,
    scope_provider: str | None,
    project_root: Path,
    testbed: Testbed | None,
    registry: PluginRegistry | None = None,
    plan_path: Path | None = None,
    catalog: Catalog | None = None,
) -> Scope:
    """Return the scope from a scope file or a scope provider spec.

    Exactly one of ``scope_path`` and ``scope_provider`` must be given.
    ``scope_provider`` is ``<name>`` or ``<name>:<config>``. ``file`` is
    built in; other names are looked up in the ``huginn.scope_providers``
    entry point group through ``registry``. The provider receives a
    ``ScopeRequest`` built from ``project_root``, ``testbed``,
    ``plan_path`` and ``catalog``.

    Raises:
        ScopeProviderError: If both or neither source is given, the provider
            cannot be found, or it fails or returns something other than a
            ``Scope``.
    """
    if (scope_path is None) == (scope_provider is None):
        raise ScopeProviderError("Pass exactly one of --scope or --scope-provider.")
    if scope_path is not None:
        return FileScopeProvider(config=str(scope_path)).resolve_scope(
            project_root, testbed
        )

    provider = _provider_from_spec(str(scope_provider), registry=registry)
    request = ScopeRequest(
        project_root=project_root,
        testbed=testbed,
        plan_path=plan_path,
        catalog=catalog,
    )
    try:
        resolved = _call_provider(provider, request)
        if inspect.isawaitable(resolved):
            resolved = await resolved
    except (ScopeProviderError, CatalogImportError):
        raise
    except Exception as error:
        raise ScopeProviderError(
            f"Scope provider '{scope_provider}' failed: {error}"
        ) from error
    if not isinstance(resolved, Scope):
        raise ScopeProviderError("Scope provider must return a Scope object")
    return resolved


def _call_provider(
    provider: ScopeProvider | LegacyScopeProvider, request: ScopeRequest
) -> Scope | Awaitable[Scope]:
    """Call ``resolve_scope`` with a request, or with the two legacy arguments.

    A method that accepts exactly one positional argument gets the request.
    Anything else, including a signature that cannot be read, is called the
    original way, with the project root and the testbed.
    """
    method = cast("Callable[..., Scope | Awaitable[Scope]]", provider.resolve_scope)
    if _takes_one_argument(method):
        return method(request)
    return method(request.project_root, request.testbed)


def _takes_one_argument(method: Callable[..., object]) -> bool:
    """Return whether a callable accepts one positional argument but not two."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    try:
        signature.bind(None)
    except TypeError:
        return False
    try:
        signature.bind(None, None)
    except TypeError:
        return True
    return False


def _provider_from_spec(
    spec: str, *, registry: PluginRegistry | None
) -> ScopeProvider | LegacyScopeProvider:
    """Build the provider named by a ``<name>[:<config>]`` spec."""
    name, _, config = spec.partition(":")
    if not name:
        raise ScopeProviderError(
            "Scope provider must be '<name>' or '<name>:<config>', "
            "for example 'file:scope.yaml'."
        )
    if name == "file":
        return FileScopeProvider(config=config)
    try:
        provider_cls = (registry or PluginRegistry()).resolve_scope_provider_class(name)
        return provider_cls(config=config)
    except PluginResolutionError as error:
        raise ScopeProviderError(str(error)) from error
    except Exception as error:
        raise ScopeProviderError(
            f"Scope provider '{name}' could not be created: {error}"
        ) from error
