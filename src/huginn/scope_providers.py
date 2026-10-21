"""Scope provider contract and built-in provider resolution.

A scope provider returns the features found on each device, for
``huginn import``. The built-in ``file`` provider reads a scope file. Other
providers are classes registered in the ``huginn.scope_providers`` entry
point group of an installed package, so a package can derive scope however
it likes, for example from device configuration.
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Protocol

from huginn.catalog_import import CatalogImportError, Scope, load_scope
from huginn.models import Testbed
from huginn.plugin_registry import PluginRegistry, PluginResolutionError


class ScopeProviderError(ValueError):
    """Raised when a scope provider cannot be resolved or fails."""


class ScopeProvider(Protocol):
    """Protocol for plugins that return the features found on each device.

    Huginn constructs a provider with ``config``, the text after the colon in
    ``--scope-provider <name>:<config>`` (an empty string when there is none).
    """

    def resolve_scope(
        self, project_root: Path, testbed: Testbed | None
    ) -> Scope | Awaitable[Scope]:
        """Return the scope for the testbed.

        Args:
            project_root: The directory the command runs from.
            testbed: The testbed from ``--testbed`` or ``./testbed.yaml``,
                or None when there is none.
        """
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
) -> Scope:
    """Return the scope from a scope file or a scope provider spec.

    Exactly one of ``scope_path`` and ``scope_provider`` must be given.
    ``scope_provider`` is ``<name>`` or ``<name>:<config>``. ``file`` is
    built in; other names are looked up in the ``huginn.scope_providers``
    entry point group through ``registry``.

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
    try:
        resolved = provider.resolve_scope(project_root, testbed)
        if isawaitable(resolved):
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


def _provider_from_spec(spec: str, *, registry: PluginRegistry | None) -> ScopeProvider:
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
