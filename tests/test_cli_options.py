"""Tests for CLI option definitions shared across commands."""

import re
from pathlib import Path

import pytest
import typer
from typer.core import TyperGroup, TyperOption
from typer.testing import CliRunner

from huginn.cli import app


def _option(command_path: list[str], name: str) -> TyperOption:
    """Return the option `name` of the command at `command_path`."""
    command = typer.main.get_command(app)
    for part in command_path:
        assert isinstance(command, TyperGroup)
        command = command.commands[part]
    for param in command.params:
        if isinstance(param, TyperOption) and param.name == name:
            return param
    raise AssertionError(f"{' '.join(command_path)} has no option {name!r}")


@pytest.mark.parametrize("subcommand", ["new", "into"])
def test_inject_id_style_offers_only_implemented_styles(subcommand: str) -> None:
    """`--id-style` offers only `prefix-counter` and keeps it as the default."""
    option = _option(["inject", subcommand], "id_style")

    assert list(getattr(option.type, "choices", [])) == ["prefix-counter"]
    assert option.default == "prefix-counter"


@pytest.mark.parametrize(
    "args",
    [
        ["inject", "new", "jobs", "--phase", "pre-change"],
        ["inject", "into", "some-group", "jobs"],
    ],
    ids=["new", "into"],
)
def test_inject_rejects_unsupported_id_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """An unimplemented `--id-style` value is a usage error."""
    (tmp_path / "jobs").mkdir()
    (tmp_path / "test_plan").mkdir()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, [*args, "--id-style", "uuid"])

    assert result.exit_code == 2
    normalized_output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "Invalid value for '--id-style'" in normalized_output


def test_data_model_help_is_consistent_and_describes_override() -> None:
    """`--data-model` has the same accurate help text on every command."""
    helps = {
        command: _option([command], "data_model").help
        for command in ("run", "validate", "relearn")
    }

    assert len(set(helps.values())) == 1, helps
    text = helps["run"] or ""
    assert "Overrides data_model.path" in text
    assert "current working directory" in text
