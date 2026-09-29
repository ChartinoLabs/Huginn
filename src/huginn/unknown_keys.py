"""Warnings for keys that the test plan and testbed loaders do not read.

Unknown keys are warnings, not errors, because some projects keep data for
other tools in these files. Each recognized-key set below lists what the
loaders read for one schema object, plus keys that are reserved for it.
Connection mappings are not checked: their extra keys are broker options.
"""

import difflib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from huginn.output import Output

UNKNOWN_KEY_WARNING_CODE = "unknown_key"

PLAN_KEYS = frozenset(
    {"name", "description", "data_model", "test_cases", "test_case_groups", "scenarios"}
)
TEST_CASE_KEYS = frozenset(
    {
        "title",
        "job",
        "description",
        "tags",
        "target",
        "priority",
        "category",
        "is_automated",
        "metadata",
    }
)
GROUP_KEYS = frozenset(
    {
        "name",
        "description",
        "tests",
        "groups",
        "exclude_tests",
        "tags",
        "target",
        "strategy",
    }
)
SCENARIO_KEYS = frozenset({"name", "description", "phases"})
PHASE_KEYS = frozenset(
    {
        "name",
        "description",
        "test_case_groups",
        "depends_on",
        "target",
        "strategy",
        "preserve_cache",
    }
)
TARGET_KEYS = frozenset({"devices", "groups", "os", "exclude_devices"})
STRATEGY_KEYS = frozenset({"serial", "parallel"})
SERIAL_STRATEGY_KEYS: frozenset[str] = frozenset()
PARALLEL_STRATEGY_KEYS = frozenset({"maximum"})

TESTBED_KEYS = frozenset({"name", "credentials", "devices"})
CREDENTIAL_KEYS = frozenset(
    {"username", "password", "private_key", "token", "token_type"}
)
DEVICE_KEYS = frozenset({"os", "groups", "credentials", "connections", "metadata"})


@dataclass(frozen=True)
class UnknownKeyWarning:
    """A key that the loader does not read, found in a test plan or testbed.

    Attributes:
        source: The YAML file that contains the key.
        key: The unknown key.
        key_path: Dotted path to the key, for example
            ``scenarios.migration.phases.post.depend_on``. A path segment
            that contains a dot is written as ``["1.0.0"]``.
        suggestion: The closest recognized key at the same level, if any.
    """

    source: Path
    key: str
    key_path: str
    suggestion: str | None = None

    def __str__(self) -> str:
        """Return the warning as a one-line message."""
        message = f"Unknown key '{self.key}' at '{self.key_path}' in {self.source}"
        if self.suggestion is not None:
            message += f"; did you mean '{self.suggestion}'?"
        return message


def check_plan_keys(
    data: dict[str, object],
    source: Path,
    unknown_keys: list[UnknownKeyWarning] | None,
) -> None:
    """Append a warning to ``unknown_keys`` for each unknown key in a plan file."""
    if unknown_keys is not None:
        _KeyChecker(source, unknown_keys).plan(data)


def check_testbed_keys(
    data: dict[str, object],
    source: Path,
    unknown_keys: list[UnknownKeyWarning] | None,
) -> None:
    """Append a warning to ``unknown_keys`` for each unknown key in a testbed."""
    if unknown_keys is not None:
        _KeyChecker(source, unknown_keys).testbed(data)


def emit_unknown_key_warnings(
    output: Output | None,
    unknown_keys: list[UnknownKeyWarning] | None,
) -> None:
    """Print each unknown-key warning through ``output``."""
    if output is None or not unknown_keys:
        return
    for warning in unknown_keys:
        output.warning(f"WARNING [{UNKNOWN_KEY_WARNING_CODE}]: {warning}")


class _KeyChecker:
    """Walk one YAML file and record the keys each schema level does not read.

    Values of the wrong type are skipped, because the loader reports them.
    """

    def __init__(self, source: Path, unknown_keys: list[UnknownKeyWarning]) -> None:
        self.source = source
        self.unknown_keys = unknown_keys

    def plan(self, data: dict[str, object]) -> None:
        self._check(data, PLAN_KEYS, ())
        for test_id, test_case in _entries(data.get("test_cases")):
            path = ("test_cases", test_id)
            mapping = self._check(test_case, TEST_CASE_KEYS, path)
            if mapping is not None:
                self._target(mapping, path)
        for group_id, group in _entries(data.get("test_case_groups")):
            self._scoped(group, GROUP_KEYS, ("test_case_groups", group_id))
        for scenario_id, scenario in _entries(data.get("scenarios")):
            self._scenario(scenario, ("scenarios", scenario_id))

    def testbed(self, data: dict[str, object]) -> None:
        self._check(data, TESTBED_KEYS, ())
        self._credentials(data, ())
        for device_name, device in _entries(data.get("devices")):
            path = ("devices", device_name)
            mapping = self._check(device, DEVICE_KEYS, path)
            if mapping is not None:
                self._credentials(mapping, path)

    def _scenario(self, scenario: object, path: tuple[str, ...]) -> None:
        mapping = self._check(scenario, SCENARIO_KEYS, path)
        if mapping is None:
            return
        for phase_id, phase in _entries(mapping.get("phases")):
            self._scoped(phase, PHASE_KEYS, (*path, "phases", phase_id))

    def _scoped(
        self, value: object, recognized: frozenset[str], path: tuple[str, ...]
    ) -> None:
        """Check a group or phase, which both take ``target`` and ``strategy``."""
        mapping = self._check(value, recognized, path)
        if mapping is None:
            return
        self._target(mapping, path)
        strategy_path = (*path, "strategy")
        strategy = self._check(mapping.get("strategy"), STRATEGY_KEYS, strategy_path)
        if strategy is None:
            return
        self._check(
            strategy.get("serial"), SERIAL_STRATEGY_KEYS, (*strategy_path, "serial")
        )
        self._check(
            strategy.get("parallel"),
            PARALLEL_STRATEGY_KEYS,
            (*strategy_path, "parallel"),
        )

    def _target(self, mapping: dict[str, object], path: tuple[str, ...]) -> None:
        self._check(mapping.get("target"), TARGET_KEYS, (*path, "target"))

    def _credentials(self, mapping: dict[str, object], path: tuple[str, ...]) -> None:
        for name, credential in _entries(mapping.get("credentials")):
            self._check(credential, CREDENTIAL_KEYS, (*path, "credentials", name))

    def _check(
        self, value: object, recognized: frozenset[str], path: tuple[str, ...]
    ) -> dict[str, object] | None:
        """Record the unknown keys of ``value`` and return it if it is a mapping."""
        if not isinstance(value, dict):
            return None
        mapping = cast(dict[str, object], value)
        for key in mapping:
            name = str(key)
            if name in recognized:
                continue
            matches = difflib.get_close_matches(name, sorted(recognized), n=1)
            self.unknown_keys.append(
                UnknownKeyWarning(
                    source=self.source,
                    key=name,
                    key_path=_format_key_path((*path, name)),
                    suggestion=matches[0] if matches else None,
                )
            )
        return mapping


def _entries(value: object) -> Iterator[tuple[str, object]]:
    """Yield the items of a mapping section, or nothing for any other value."""
    if isinstance(value, dict):
        for key, item in cast(dict[object, object], value).items():
            yield str(key), item


def _format_key_path(parts: tuple[str, ...]) -> str:
    """Join key path segments with dots, bracketing segments that contain one."""
    path = ""
    for part in parts:
        if "." in part:
            path += f'["{part}"]'
        else:
            path += f".{part}" if path else part
    return path
