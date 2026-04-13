"""CLI interface for Huginn test automation framework.

This module provides the command-line interface for executing test plans
against infrastructure testbeds.
"""

import asyncio
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Annotated

import typer

from huginn.enums import ErrorCode, ExecutionMode
from huginn.output import Output
from huginn.plan_filtering import PlanFilterOptions
from huginn.runner import RunExecutionError, run_test_plan
from huginn.validation import validate_inputs

app = typer.Typer(
    name="huginn",
    help="Async-first test automation framework for network infrastructure.",
    no_args_is_help=True,
)


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
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude test cases with matching tags.",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Run only specified scenarios.",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Run only specified phases.",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Run only specified test case groups.",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Run only specified test case IDs.",
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
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable DEBUG-level logging."),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option("--log-file", help="Path to log file (default: ./huginn.log)."),
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
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status(f"Starting run in {mode.value} mode")
    output.log_debug_fields(
        "CLI run options",
        plan=plan,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
        tags=tags,
        exclude_tags=exclude_tags,
        scenario=scenario,
        phase=phase,
        test_case_group=test_case_group,
        test_id=test_id,
        log_level="DEBUG" if debug else log_level,
        show_logs=show_logs,
        log_file=log_file,
    )

    try:
        filters = _build_plan_filters(
            tags=tags,
            exclude_tags=exclude_tags,
            scenarios=scenario,
            phases=phase,
            test_case_groups=test_case_group,
            test_ids=test_id,
        )
        result = asyncio.run(
            run_test_plan(
                mode=mode,
                testbed_path=testbed_path,
                inventory_plugin=inventory_plugin,
                plan_path=plan,
                filters=filters,
                project_root=Path.cwd(),
                parameters_dir=Path.cwd() / "parameters",
                results_dir=Path.cwd() / "results",
                output=output,
            )
        )
    except RunExecutionError as error:
        output.error(f"ERROR [{error.code.value}]: {error}")
        if error.traceback_text:
            output.error(error.traceback_text)
        raise typer.Exit(code=_exit_code_for_run_error(error.code)) from error

    output.status(f"Run status: {result.summary.status}")
    output.status(
        "Summary: "
        f"total={result.summary.total} "
        f"passed={result.summary.passed} "
        f"failed={result.summary.failed} "
        f"errored={result.summary.errored} "
        f"not_applicable={result.summary.not_applicable} "
        f"skipped={result.summary.skipped} "
        f"blocked={result.summary.blocked}"
    )
    if result.summary.total == 0:
        output.warning("No test cases were selected for execution")
    output.status("Run artifacts written to results/")
    output.status("Run report written to reports/latest/")
    if result.summary.status != "passed":
        raise typer.Exit(code=1)


@app.command()
def validate(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file to validate.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
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
            help="Filter validation set by tags.",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude validation set by tags.",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Validate only specified scenarios.",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Validate only specified phases.",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Validate only specified test case groups.",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Validate only specified test case IDs.",
        ),
    ] = None,
    data_model: Annotated[
        Path | None,
        typer.Option(
            "--data-model",
            "-d",
            help="Reserved for future data model support.",
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
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable DEBUG-level logging."),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option("--log-file", help="Path to log file (default: ./huginn.log)."),
    ] = None,
) -> None:
    """Validate testbed/plan inputs without executing tests."""
    testbed_path = _resolve_testbed_option(
        testbed=testbed,
        inventory_plugin=inventory_plugin,
        data_model=data_model,
    )

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status("Starting validation")
    output.log_debug_fields(
        "CLI validate options",
        plan=plan,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
        tags=tags,
        exclude_tags=exclude_tags,
        scenario=scenario,
        phase=phase,
        test_case_group=test_case_group,
        test_id=test_id,
        log_level="DEBUG" if debug else log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    result = asyncio.run(
        validate_inputs(
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            plan_path=plan,
            filters=_build_plan_filters(
                tags=tags,
                exclude_tags=exclude_tags,
                scenarios=scenario,
                phases=phase,
                test_case_groups=test_case_group,
                test_ids=test_id,
            ),
            project_root=Path.cwd(),
            results_dir=Path.cwd() / "results",
            output=output,
        )
    )
    output.status(f"Validation status: {'passed' if result.valid else 'failed'}")
    output.status(
        "Summary: "
        f"test_cases={len(result.test_cases)} "
        f"warnings={len(result.warnings)} "
        f"errors={len(result.errors)}"
    )
    output.status("Validation artifacts written to results/")

    if not result.valid:
        for error in result.errors:
            output.error(f"ERROR [{error.code}]: {error.message}")
        raise typer.Exit(code=3)

    for warning in result.warnings:
        output.warning(f"WARNING [{warning.code}]: {warning.message}")


def _exit_code_for_run_error(code: ErrorCode) -> int:
    """Map structured run errors to deterministic CLI exit codes."""
    if code in {
        ErrorCode.CONFIGURATION_ERROR,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.PLANNING_ERROR,
    }:
        return 2
    return 1


def _resolve_testbed_option(
    *,
    testbed: Path | None,
    inventory_plugin: str | None,
    data_model: Path | None,
) -> Path | None:
    """Validate first-slice options and return required testbed path."""
    if testbed is not None and inventory_plugin is not None:
        raise typer.BadParameter(
            "--testbed and --inventory-plugin are mutually exclusive."
        )

    if testbed is None and inventory_plugin is None:
        raise typer.BadParameter(
            "Either --testbed or --inventory-plugin must be specified."
        )

    if data_model is not None:
        raise typer.BadParameter("--data-model is not implemented yet.")
    return testbed


def _build_plan_filters(
    *,
    tags: list[str] | None,
    exclude_tags: list[str] | None,
    scenarios: list[str] | None,
    phases: list[str] | None,
    test_case_groups: list[str] | None,
    test_ids: list[str] | None,
) -> PlanFilterOptions:
    """Normalize CLI filter values into a single plan-filter object."""
    normalized_scenarios = _split_csv_option_values(scenarios)
    normalized_phases = _split_csv_option_values(phases)
    if normalized_phases and not normalized_scenarios:
        raise typer.BadParameter("--phase requires --scenario to be specified.")

    return PlanFilterOptions(
        tags=_split_csv_option_values(tags),
        exclude_tags=_split_csv_option_values(exclude_tags),
        scenarios=normalized_scenarios,
        phases=normalized_phases,
        test_case_groups=_split_csv_option_values(test_case_groups),
        test_ids=_split_csv_option_values(test_ids),
    )


def _split_csv_option_values(values: list[str] | None) -> list[str] | None:
    """Split comma-separated CLI option values while preserving order."""
    if not values:
        return None

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        for raw_item in value.split(","):
            item = raw_item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
    return normalized or None


def _build_output(
    *,
    debug: bool,
    log_level: str,
    show_logs: bool,
    log_file: Path | None,
) -> Output:
    """Build output coordinator for console and logging streams."""
    resolved_log_level = "DEBUG" if debug else log_level
    return Output(
        show_logs=show_logs,
        log_level=resolved_log_level,
        log_file=log_file,
    )


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()
