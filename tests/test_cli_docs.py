"""Documentation drift check: every CLI command and option is in the CLI reference.

The CLI reference page at `docs/reference/cli.md` documents every `huginn`
command, option, short form and environment variable. This test walks the
Typer app and fails when any of them is missing from the page, so that new
or renamed options cannot land without a matching documentation update.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.core import TyperCommand, TyperGroup

from huginn.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DOC = REPO_ROOT / "docs" / "reference" / "cli.md"


def _iter_commands() -> list[tuple[str, TyperCommand | TyperGroup]]:
    """Return (command path, command) pairs for the app and every subcommand."""
    commands: list[tuple[str, TyperCommand | TyperGroup]] = []

    def walk(command: TyperCommand | TyperGroup, path: str) -> None:
        commands.append((path, command))
        if isinstance(command, TyperGroup):
            for name, sub in sorted(command.commands.items()):
                if isinstance(sub, (TyperCommand, TyperGroup)):
                    walk(sub, f"{path} {name}".strip())

    root = typer.main.get_command(app)
    assert isinstance(root, TyperGroup)
    walk(root, "")
    return commands


def _expected_tokens() -> set[str]:
    """Return the leaf command headings, option strings and env vars cli.md needs."""
    tokens: set[str] = set()
    for path, command in _iter_commands():
        if path and not isinstance(command, TyperGroup):
            tokens.add(f"## {path}")
        for param in command.params:
            if param.param_type_name != "option":
                continue
            tokens.update(f"`{opt}`" for opt in param.opts)
            if isinstance(param.envvar, str):
                tokens.add(f"`{param.envvar}`")
    return tokens


def test_cli_reference_walker_sees_nested_and_root_options() -> None:
    """Guard the walker itself so an empty token set cannot pass silently."""
    tokens = _expected_tokens()
    assert "## inject new" in tokens
    assert "`--install-completion`" in tokens
    assert "`HUGINN_TEST_ID_PATTERN`" in tokens


def test_cli_reference_documents_every_option() -> None:
    """Fail if a CLI command, option, short form or env var is missing from cli.md."""
    content = CLI_DOC.read_text(encoding="utf-8")
    doc_lines = set(content.splitlines())
    missing = sorted(
        token
        for token in _expected_tokens()
        if (token not in doc_lines if token.startswith("## ") else token not in content)
    )
    if missing:
        lines = [f"Missing from {CLI_DOC.relative_to(REPO_ROOT)}:"]
        lines.extend(f"  {token}" for token in missing)
        pytest.fail("\n".join(lines))
