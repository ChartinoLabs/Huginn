"""CLI interface for Huginn test automation framework.

This module provides the command-line interface for executing test plans
against infrastructure testbeds.
"""

from enum import Enum
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="huginn",
    help="Async-first test automation framework for network infrastructure.",
    no_args_is_help=True,
)


class ExecutionMode(str, Enum):
    """Execution mode for test runs."""

    LEARNING = "learning"
    TESTING = "testing"


@app.command()
def run(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file defining test organization.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ],
    mode: Annotated[
        ExecutionMode,
        typer.Option(
            "--mode",
            "-m",
            help="Execution mode: 'learning' captures current state as baseline, "
            "'testing' compares against learned parameters.",
        ),
    ],
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter test cases by tags. Only matching test cases will run.",
        ),
    ] = None,
    data_model: Annotated[
        Path | None,
        typer.Option(
            "--data-model",
            "-d",
            help="Path to data model directory containing YAML files representing "
            "intended infrastructure state.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
        ),
    ] = None,
) -> None:
    """Execute a test plan against infrastructure.

    Run test cases defined in a test plan against devices specified in a testbed.
    In learning mode, current device state is captured as baseline parameters.
    In testing mode, current state is compared against learned parameters.

    Examples:
        huginn run -m testing -t testbed.yaml -p test_plan.yaml
        huginn run -m learning -t testbed.yaml -p test_plan.yaml --tags ospf
        huginn run -m testing -p test_plan.yaml -i huginn-netbox
    """
    if testbed is None and inventory_plugin is None:
        raise typer.BadParameter(
            "Either --testbed or --inventory-plugin must be specified."
        )

    if testbed is not None and inventory_plugin is not None:
        raise typer.BadParameter(
            "--testbed and --inventory-plugin are mutually exclusive."
        )

    typer.echo(f"Executing test plan: {plan}")
    typer.echo(f"Mode: {mode.value}")

    if testbed:
        typer.echo(f"Testbed: {testbed}")
    else:
        typer.echo(f"Inventory plugin: {inventory_plugin}")

    if tags:
        typer.echo(f"Tags filter: {', '.join(tags)}")

    if data_model:
        typer.echo(f"Data model: {data_model}")


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()
