"""Tests for `${VAR}` environment variable expansion in testbed files."""

import re
from pathlib import Path

import pytest

from huginn.loaders import (
    ConfigurationError,
    _expand_env_vars,
    load_test_plan,
    load_testbed,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "docs" / "getting-started" / "quickstart.md"


def _expand(text: str, **environ: str) -> object:
    """Expand one string against an explicit environment."""
    return _expand_env_vars(text, source="testbed.yaml", environ=environ)


@pytest.mark.parametrize(
    ("text", "environ", "expected"),
    [
        ("${USER_NAME}", {"USER_NAME": "admin"}, "admin"),
        ("${A}-${B}", {"A": "x", "B": "y"}, "x-y"),
        ("pre-${A}-post", {"A": "x"}, "pre-x-post"),
        ("${_private9}", {"_private9": "ok"}, "ok"),
        ("${A:-fallback}", {}, "fallback"),
        ("${A:-fallback}", {"A": ""}, "fallback"),
        ("${A:-fallback}", {"A": "set"}, "set"),
        ("${A:-}", {}, ""),
        ("${A:-a b:-c $d}", {}, "a b:-c $d"),
        ("${A}", {"A": ""}, ""),
        ("$${A}", {}, "${A}"),
        ("$${A}", {"A": "set"}, "${A}"),
        ("$${", {}, "${"),
        ("$$${A}", {"A": "set"}, "$${A}"),
        ("$A", {"A": "set"}, "$A"),
        ("$$A", {"A": "set"}, "$$A"),
        ("cost $5", {}, "cost $5"),
        ("{A}", {"A": "set"}, "{A}"),
        ("${A:-x}}", {}, "x}"),
        ("", {}, ""),
    ],
)
def test_expand_env_vars_syntax(
    text: str, environ: dict[str, str], expected: str
) -> None:
    """Each supported form expands to the documented value."""
    assert _expand(text, **environ) == expected


def test_expand_env_vars_expands_once() -> None:
    """A resolved value containing `${` is not expanded again."""
    assert _expand("${A}", A="${B}", B="nested") == "${B}"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("${", "Unterminated"),
        ("abc ${A", "Unterminated"),
        ("${}", "Invalid environment variable reference"),
        ("${1X}", "Invalid environment variable reference"),
        ("${A-B}", "Invalid environment variable reference"),
        ("${A B}", "Invalid environment variable reference"),
        ("${A-default}", "Invalid environment variable reference"),
        ("${A:=default}", "Invalid environment variable reference"),
        ("${A:-${B}}", "a default cannot contain"),
    ],
)
def test_expand_env_vars_rejects_malformed_references(text: str, message: str) -> None:
    """Malformed references raise instead of passing through silently."""
    with pytest.raises(ConfigurationError, match=re.escape(message)):
        _expand(text, A="set", B="set")


def test_expand_env_vars_unset_variable_names_variable_and_path() -> None:
    """An unset variable without a default names the variable and key path."""
    data = {"devices": {"rtr-01": {"credentials": {"default": {"password": "${PW}"}}}}}

    with pytest.raises(ConfigurationError) as excinfo:
        _expand_env_vars(data, source="testbed.yaml", environ={})

    assert str(excinfo.value) == (
        "Environment variable 'PW' referenced at "
        "'devices.rtr-01.credentials.default.password' in testbed.yaml is not set "
        "and has no default"
    )


def test_expand_env_vars_error_does_not_leak_values() -> None:
    """The unset-variable error omits resolved values and the surrounding text."""
    data = {"password": "literal-part-${SECRET}-${MISSING}"}

    with pytest.raises(ConfigurationError) as excinfo:
        _expand_env_vars(data, source="testbed.yaml", environ={"SECRET": "hunter2"})

    message = str(excinfo.value)
    assert "MISSING" in message
    assert "hunter2" not in message
    assert "literal-part" not in message


def test_expand_env_vars_walks_lists_and_leaves_keys_and_scalars() -> None:
    """Strings in nested lists expand; keys and non-string scalars do not."""
    data = {
        "${KEY}": ["${A}", {"inner": "${A}"}],
        "port": 22,
        "verify": False,
        "missing": None,
    }

    result = _expand_env_vars(data, source="testbed.yaml", environ={"A": "x"})

    assert result == {
        "${KEY}": ["x", {"inner": "x"}],
        "port": 22,
        "verify": False,
        "missing": None,
    }


def test_expand_env_vars_list_error_path_uses_index() -> None:
    """Errors inside lists report the list index in the key path."""
    with pytest.raises(ConfigurationError, match=r"'devices\.r1\.groups\[1\]'"):
        _expand_env_vars(
            {"devices": {"r1": {"groups": ["core", "${GROUP}"]}}},
            source="testbed.yaml",
            environ={},
        )


def _write_testbed(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "testbed.yaml"
    path.write_text(content, encoding="utf-8")
    return path


TESTBED_WITH_REFERENCES = """\
credentials:
  default:
    username: ${HUGINN_USERNAME:-admin}
    password: ${HUGINN_PASSWORD}
devices:
  rtr-01:
    os: ${RTR_OS:-iosxe}
    groups: [core, "${SITE}"]
    connections:
      netconf:
        protocol: netconf
        host: ${RTR_HOST}
        port: ${RTR_PORT}
        credential: default
        hostkey_file: "$${HOME}/.ssh/known_hosts"
"""


def test_load_testbed_expands_references_in_all_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credentials, hosts, ports, groups and options are all expanded."""
    monkeypatch.delenv("HUGINN_USERNAME", raising=False)
    monkeypatch.delenv("RTR_OS", raising=False)
    monkeypatch.setenv("HUGINN_PASSWORD", "s3cret")
    monkeypatch.setenv("SITE", "dc1")
    monkeypatch.setenv("RTR_HOST", "10.0.0.1")
    monkeypatch.setenv("RTR_PORT", "830")

    testbed = load_testbed(_write_testbed(tmp_path, TESTBED_WITH_REFERENCES))

    device = testbed.devices["rtr-01"]
    assert testbed.credentials["default"] == {
        "username": "admin",
        "password": "s3cret",
    }
    assert device.credentials["default"]["password"] == "s3cret"
    assert device.os == "iosxe"
    assert device.groups == ["core", "dc1"]
    connection = device.connections["netconf"]
    assert connection.host == "10.0.0.1"
    assert connection.port == 830
    assert connection.options["hostkey_file"] == "${HOME}/.ssh/known_hosts"


def test_load_testbed_rejects_non_numeric_port_after_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A port that expands to a non-digit string still fails the type check."""
    monkeypatch.setenv("RTR_PORT", "ssh")
    path = _write_testbed(
        tmp_path,
        "devices:\n  r1:\n    os: iosxe\n    connections:\n      ssh:\n"
        "        protocol: ssh\n        host: 10.0.0.1\n        port: ${RTR_PORT}\n",
    )

    with pytest.raises(ConfigurationError, match="port must be int"):
        load_testbed(path)


def test_load_testbed_unset_variable_names_device_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loader error names the file, key path and variable."""
    monkeypatch.setenv("HUGINN_PASSWORD", "s3cret")
    monkeypatch.setenv("SITE", "dc1")
    monkeypatch.setenv("RTR_PORT", "830")
    monkeypatch.delenv("RTR_HOST", raising=False)
    path = _write_testbed(tmp_path, TESTBED_WITH_REFERENCES)

    with pytest.raises(ConfigurationError) as excinfo:
        load_testbed(path)

    message = str(excinfo.value)
    assert "'RTR_HOST'" in message
    assert "'devices.rtr-01.connections.netconf.host'" in message
    assert str(path) in message
    assert "s3cret" not in message


def _quickstart_testbed() -> str:
    """Return the testbed YAML block from the quick start guide."""
    text = QUICKSTART.read_text(encoding="utf-8")
    section = text.split("## Define your testbed", 1)[1]
    match = re.search(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_quickstart_testbed_loads_with_password_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The quick start testbed loads once DEVICE_PASSWORD is exported."""
    monkeypatch.setenv("DEVICE_PASSWORD", "quickstart-pw")

    testbed = load_testbed(_write_testbed(tmp_path, _quickstart_testbed()))

    assert testbed.devices["rtr-01"].credentials["default"] == {
        "username": "admin",
        "password": "quickstart-pw",
    }


def test_quickstart_testbed_fails_clearly_without_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without DEVICE_PASSWORD the quick start testbed fails naming it."""
    monkeypatch.delenv("DEVICE_PASSWORD", raising=False)
    path = _write_testbed(tmp_path, _quickstart_testbed())

    with pytest.raises(
        ConfigurationError,
        match=r"'DEVICE_PASSWORD' referenced at "
        r"'devices\.rtr-01\.credentials\.default\.password'",
    ):
        load_testbed(path)


def test_load_test_plan_does_not_expand_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expansion is scoped to testbed files; test plans keep `${...}` as-is."""
    monkeypatch.setenv("PLAN_TITLE", "expanded")
    path = tmp_path / "plan.yaml"
    path.write_text(
        "test_cases:\n  1.0.0:\n    title: ${PLAN_TITLE}\n    job: jobs/verify.py\n"
        "test_case_groups:\n  routing:\n    tests: [1.0.0]\n"
        "scenarios:\n  s1:\n    phases:\n      p1:\n"
        "        test_case_groups: [routing]\n",
        encoding="utf-8",
    )

    plan = load_test_plan(path)

    assert plan.test_cases["1.0.0"].title == "${PLAN_TITLE}"
