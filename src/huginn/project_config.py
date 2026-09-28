"""Project defaults loaded from ``[tool.huginn]`` in ``pyproject.toml``.

The CLI reads ``pyproject.toml`` from the current working directory once per
invocation. Path and logging keys become defaults for the matching CLI
options, below explicit flags and ``HUGINN_*`` environment variables. The
``[tool.huginn.plugins]`` sub-table configures the plugin registry.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]  # noqa: F811

from huginn.loaders import ConfigurationError
from huginn.plugin_registry import PluginConfig

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

_PATH_KEYS = (
    "test_plan",
    "testbed",
    "parameters_dir",
    "results_dir",
    "output_dir",
    "log_file",
)
_STRING_KEYS = ("inventory_plugin", "log_level")
_RESERVED_TABLES = ("plugins",)
_ALLOWED_KEYS = frozenset(_PATH_KEYS + _STRING_KEYS + _RESERVED_TABLES)
_PLUGIN_KEYS = frozenset(("brokers", "reporters", "hooks", "config"))

# Keys whose CLI parameter name differs from the pyproject key.
_CLI_PARAMETER_NAMES = {"test_plan": "plan"}


@dataclass(frozen=True)
class ProjectConfig:
    """Validated contents of ``[tool.huginn]``.

    Attributes:
        test_plan: Default for ``--plan``.
        testbed: Default for ``--testbed``.
        inventory_plugin: Default for ``--inventory-plugin``.
        parameters_dir: Default for ``--parameters-dir``.
        results_dir: Default for ``--results-dir``.
        output_dir: Default for ``--output-dir``.
        log_file: Default for ``--log-file``.
        log_level: Default for ``--log-level``.
        plugins: Plugin configuration from ``[tool.huginn.plugins]``.
    """

    test_plan: Path | None = None
    testbed: Path | None = None
    inventory_plugin: str | None = None
    parameters_dir: Path | None = None
    results_dir: Path | None = None
    output_dir: Path | None = None
    log_file: Path | None = None
    log_level: str | None = None
    plugins: PluginConfig = field(default_factory=PluginConfig)

    def cli_defaults(self) -> dict[str, Path | str]:
        """Return the set defaults keyed by CLI parameter name."""
        defaults: dict[str, Path | str] = {}
        for key in _PATH_KEYS + _STRING_KEYS:
            value = getattr(self, key)
            if value is not None:
                defaults[_CLI_PARAMETER_NAMES.get(key, key)] = value
        return defaults


def load_project_config(project_root: Path) -> ProjectConfig:
    """Load and validate ``[tool.huginn]`` from ``project_root/pyproject.toml``.

    Relative paths are resolved against ``project_root``. A missing file or
    missing ``[tool.huginn]`` table yields an empty configuration.

    Raises:
        ConfigurationError: If the file is not valid TOML, the table holds an
            unknown key or a value of the wrong type, ``log_level`` is not a
            supported level, both ``testbed`` and ``inventory_plugin`` are set,
            or ``[tool.huginn.plugins]`` holds an unknown key or a bad value.
    """
    table = _read_huginn_table(project_root / "pyproject.toml")
    unknown = sorted(set(table) - _ALLOWED_KEYS)
    if unknown:
        raise ConfigurationError(
            f"Unknown key(s) in [tool.huginn]: {', '.join(unknown)}"
        )
    if "testbed" in table and "inventory_plugin" in table:
        raise ConfigurationError(
            "[tool.huginn] keys 'testbed' and 'inventory_plugin' are mutually "
            "exclusive."
        )

    values: dict[str, Any] = {
        key: project_root / _string_value(table, key)
        for key in _PATH_KEYS
        if key in table
    }
    values.update(
        {key: _string_value(table, key) for key in _STRING_KEYS if key in table}
    )
    if "log_level" in values:
        values["log_level"] = _log_level(values["log_level"])
    return ProjectConfig(**values, plugins=_plugin_config(table.get("plugins", {})))


def _read_huginn_table(pyproject_path: Path) -> dict[str, Any]:
    """Return the ``[tool.huginn]`` table, or an empty dict if absent."""
    if not pyproject_path.exists():
        return {}
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid {pyproject_path}: {error}") from error

    table = data.get("tool", {}).get("huginn", {})
    if not isinstance(table, dict):
        raise ConfigurationError("[tool.huginn] must be a table.")
    return table


def _string_value(table: dict[str, Any], key: str) -> str:
    """Return a non-empty string value from ``table`` or raise."""
    value = table[key]
    if not isinstance(value, str) or not value:
        raise ConfigurationError(
            f"[tool.huginn] key '{key}' must be a non-empty string, got {value!r}."
        )
    return value


def _log_level(value: str) -> str:
    """Normalize a log level, rejecting values the CLI does not accept."""
    level = value.upper()
    if level not in LOG_LEVELS:
        raise ConfigurationError(
            f"[tool.huginn] key 'log_level' must be one of "
            f"{', '.join(LOG_LEVELS)}, got {value!r}."
        )
    return level


def _plugin_config(plugins_section: object) -> PluginConfig:
    """Build plugin configuration from ``[tool.huginn.plugins]``."""
    if not isinstance(plugins_section, dict):
        raise ConfigurationError("[tool.huginn.plugins] must be a table.")
    unknown = sorted(set(plugins_section) - _PLUGIN_KEYS)
    if unknown:
        hint = (
            ". Use 'brokers', 'reporters' or 'hooks' instead of 'enabled'."
            if "enabled" in unknown
            else ""
        )
        raise ConfigurationError(
            f"Unknown key(s) in [tool.huginn.plugins]: {', '.join(unknown)}{hint}"
        )
    return PluginConfig(
        brokers=_plugin_names(plugins_section, "brokers"),
        reporters=_plugin_names(plugins_section, "reporters"),
        hooks=_plugin_names(plugins_section, "hooks"),
        plugin_options=_plugin_options(plugins_section.get("config", {})),
    )


def _plugin_names(plugins_section: dict[str, Any], key: str) -> list[str] | None:
    """Return a list of plugin names from ``plugins_section`` or raise."""
    value = plugins_section.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name for name in value
    ):
        raise ConfigurationError(
            f"[tool.huginn.plugins] key '{key}' must be a list of non-empty "
            f"strings, got {value!r}."
        )
    return value


def _plugin_options(config: object) -> dict[str, dict[str, Any]]:
    """Return per-plugin options from ``[tool.huginn.plugins.config]`` or raise."""
    if not isinstance(config, dict):
        raise ConfigurationError(
            f"[tool.huginn.plugins] key 'config' must be a table, got {config!r}."
        )
    for name, options in config.items():
        if not isinstance(options, dict):
            raise ConfigurationError(
                f"[tool.huginn.plugins.config] key '{name}' must be a table, "
                f"got {options!r}."
            )
    return config
