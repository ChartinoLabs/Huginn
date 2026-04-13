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
from huginn.loaders import ConfigurationError, load_test_plan
from huginn.output import Output
from huginn.plan_filtering import PlanFilterOptions
from huginn.reconcile import (
    ReconcileError,
    apply_reconcile_plan,
    compute_reconcile_plan,
    copy_parameter_files,
    find_latest_testing_results,
    parse_failures_from_run,
    validate_after_reconcile,
)
from huginn.runner import RunExecutionError, run_test_plan
from huginn.validation import validate_inputs

app = typer.Typer(
    name="huginn",
    help="Async-first test automation framework for network infrastructure.",
    no_args_is_help=True,
)


@app.command()
def run(
    mode: Annotated[
        ExecutionMode,
        typer.Option(
            "--mode",
            "-m",
            help="Execution mode: 'learning' captures current state as baseline, "
            "'testing' compares against learned parameters.",
            envvar="HUGINN_MODE",
        ),
    ],
    plan: Annotated[
        Path | None,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files "
            "(default: ./test_plan).",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ] = None,
    testbed: Annotated[
        Path | None,
        typer.Option(
            "--testbed",
            "-t",
            help="Path to testbed YAML file defining device inventory "
            "(default: ./testbed.yaml).",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            envvar="HUGINN_TESTBED",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter test cases by tags. Only matching test cases will run.",
            envvar="HUGINN_TAGS",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude test cases with matching tags.",
            envvar="HUGINN_EXCLUDE_TAGS",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Run only specified scenarios.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Run only specified phases.",
            envvar="HUGINN_PHASE",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Run only specified test case groups.",
            envvar="HUGINN_TEST_CASE_GROUP",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Run only specified test case IDs.",
            envvar="HUGINN_TEST_ID",
        ),
    ] = None,
    test_id_pattern: Annotated[
        str | None,
        typer.Option(
            "--test-id-pattern",
            help="Regex pattern to filter test case IDs (e.g. '-post-shutdown$').",
            envvar="HUGINN_TEST_ID_PATTERN",
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
            envvar="HUGINN_DATA_MODEL",
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
            envvar="HUGINN_INVENTORY_PLUGIN",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Path to output directory for run artifacts "
            "(default: <run-dir>/artifacts/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_OUTPUT_DIR",
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
    plan = _resolve_plan_option(plan)
    resolved_results_dir = results_dir or Path.cwd() / "results"

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
        results_dir=resolved_results_dir,
        output_dir=output_dir,
    )

    try:
        filters = _build_plan_filters(
            tags=tags,
            exclude_tags=exclude_tags,
            scenarios=scenario,
            phases=phase,
            test_case_groups=test_case_group,
            test_ids=test_id,
            test_id_pattern=test_id_pattern,
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
                results_dir=resolved_results_dir,
                output_dir=output_dir,
                output=output,
            )
        )
    except ConfigurationError as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error
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
            help="Path to test plan YAML file or directory of YAML files to validate.",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
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
            envvar="HUGINN_TESTBED",
        ),
    ] = None,
    tags: Annotated[
        list[str] | None,
        typer.Option(
            "--tags",
            help="Filter validation set by tags.",
            envvar="HUGINN_TAGS",
        ),
    ] = None,
    exclude_tags: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tags",
            help="Exclude validation set by tags.",
            envvar="HUGINN_EXCLUDE_TAGS",
        ),
    ] = None,
    scenario: Annotated[
        list[str] | None,
        typer.Option(
            "--scenario",
            help="Validate only specified scenarios.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    phase: Annotated[
        list[str] | None,
        typer.Option(
            "--phase",
            help="Validate only specified phases.",
            envvar="HUGINN_PHASE",
        ),
    ] = None,
    test_case_group: Annotated[
        list[str] | None,
        typer.Option(
            "--test-case-group",
            help="Validate only specified test case groups.",
            envvar="HUGINN_TEST_CASE_GROUP",
        ),
    ] = None,
    test_id: Annotated[
        list[str] | None,
        typer.Option(
            "--test-id",
            help="Validate only specified test case IDs.",
            envvar="HUGINN_TEST_ID",
        ),
    ] = None,
    test_id_pattern: Annotated[
        str | None,
        typer.Option(
            "--test-id-pattern",
            help="Regex pattern to filter test case IDs (e.g. '-post-shutdown$').",
            envvar="HUGINN_TEST_ID_PATTERN",
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
            envvar="HUGINN_DATA_MODEL",
        ),
    ] = None,
    inventory_plugin: Annotated[
        str | None,
        typer.Option(
            "--inventory-plugin",
            "-i",
            help="Use an inventory plugin instead of a static testbed YAML file.",
            envvar="HUGINN_INVENTORY_PLUGIN",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
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
    try:
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
                    test_id_pattern=test_id_pattern,
                ),
                project_root=Path.cwd(),
                results_dir=Path.cwd() / "results",
                output=output,
            )
        )
    except ConfigurationError as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error
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


def _resolve_plan_option(plan: Path | None) -> Path:
    """Apply default plan path when the user omits --plan."""
    if plan is not None:
        return plan
    default = Path.cwd() / "test_plan"
    if default.exists():
        return default.resolve()
    raise typer.BadParameter("No --plan specified and default ./test_plan not found.")


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
        default = Path.cwd() / "testbed.yaml"
        if default.exists():
            testbed = default.resolve()
        else:
            raise typer.BadParameter(
                "Either --testbed or --inventory-plugin must be specified "
                "(no default ./testbed.yaml found)."
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
    test_id_pattern: str | None = None,
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
        test_id_pattern=test_id_pattern,
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
def reconcile(
    plan: Annotated[
        Path,
        typer.Option(
            "--plan",
            "-p",
            help="Path to test plan YAML file or directory of YAML files.",
            exists=True,
            file_okay=True,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PLAN",
        ),
    ],
    phase: Annotated[
        str,
        typer.Option(
            "--phase",
            help="Phase whose failures to reconcile. Also used as suffix for "
            "new test case IDs and group names.",
            envvar="HUGINN_PHASE",
        ),
    ],
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            help="Reconcile only the specified scenario. "
            "If omitted, all scenarios with the target phase are processed.",
            envvar="HUGINN_SCENARIO",
        ),
    ] = None,
    results_dir: Annotated[
        Path | None,
        typer.Option(
            "--results-dir",
            help="Path to results directory (default: ./results/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_RESULTS_DIR",
        ),
    ] = None,
    parameters_dir: Annotated[
        Path | None,
        typer.Option(
            "--parameters-dir",
            help="Path to parameters directory (default: ./parameters/).",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            envvar="HUGINN_PARAMETERS_DIR",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Enable DEBUG-level logging.",
            envvar="HUGINN_DEBUG",
        ),
    ] = False,
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Logging level (DEBUG, INFO, WARNING, ERROR).",
            envvar="HUGINN_LOG_LEVEL",
        ),
    ] = "INFO",
    show_logs: Annotated[
        bool,
        typer.Option(
            "--show-logs",
            help="Stream logs to console in addition to file.",
            envvar="HUGINN_SHOW_LOGS",
        ),
    ] = False,
    log_file: Annotated[
        Path | None,
        typer.Option(
            "--log-file",
            help="Path to log file (default: ./huginn.log).",
            envvar="HUGINN_LOG_FILE",
        ),
    ] = None,
) -> None:
    """Reconcile failing test cases into new test case groups.

    After running a post-change phase in testing mode, some tests may fail
    because the golden parameters reflect pre-change state. This command
    creates new test case definitions and groups for the failing tests so
    they can be re-learned with post-change parameters.

    Examples:
        huginn reconcile -p test_plan.yaml --phase post-change
        huginn reconcile -p plans/ --phase post-change --scenario migration
    """
    resolved_results_dir = results_dir or Path.cwd() / "results"
    resolved_parameters_dir = parameters_dir or Path.cwd() / "parameters"

    output = _build_output(
        debug=debug,
        log_level=log_level,
        show_logs=show_logs,
        log_file=log_file,
    )
    output.status(f"Reconciling failures for phase '{phase}'")
    output.log_debug_fields(
        "CLI reconcile options",
        plan=plan,
        phase=phase,
        scenario=scenario,
        results_dir=resolved_results_dir,
        parameters_dir=resolved_parameters_dir,
        log_level="DEBUG" if debug else log_level,
    )

    try:
        run_json_path = find_latest_testing_results(resolved_results_dir)
        output.status(f"Using results from {run_json_path.parent.name}")

        reconcile_input = parse_failures_from_run(
            run_json_path, phase, scenario_filter=scenario
        )

        if not reconcile_input.failing_tests:
            output.success(
                f"No failures found in phase '{phase}' -- nothing to reconcile"
            )
            return

        output.status(
            f"Found {len(reconcile_input.failing_tests)} failing test case(s) "
            f"across {len(reconcile_input.affected_group_ids)} group(s)"
        )

        test_plan = load_test_plan(plan)
        plan_result = compute_reconcile_plan(reconcile_input, test_plan, phase)

        if not plan_result.new_test_cases and not plan_result.new_groups:
            output.success("Reconciliation already applied -- no changes needed")
            if plan_result.skipped_existing:
                output.warning(
                    f"Skipped {len(plan_result.skipped_existing)} existing "
                    "ID(s) (already reconciled)"
                )
            return

        apply_reconcile_plan(
            plan_path=plan,
            reconcile_plan=plan_result,
            phase_name=phase,
            output=output,
        )

        copied = copy_parameter_files(
            parameters_dir=resolved_parameters_dir,
            copies=plan_result.parameter_copies,
            output=output,
        )

        validate_after_reconcile(plan)

        output.success(
            f"Reconciliation complete: "
            f"{len(plan_result.new_test_cases)} new test case(s), "
            f"{len(plan_result.new_groups)} new group(s), "
            f"{copied} parameter file(s) copied"
        )
        if plan_result.skipped_existing:
            output.warning(
                f"Skipped {len(plan_result.skipped_existing)} existing "
                "ID(s) (already reconciled)"
            )

    except (ReconcileError, ConfigurationError) as error:
        output.error(f"ERROR: {error}")
        raise typer.Exit(code=1) from error


@app.command()
def version() -> None:
    """Display the Huginn version."""
    typer.echo(f"huginn v{get_version('huginn')}")


def main() -> None:
    """Entry point for the Huginn CLI."""
    app()
