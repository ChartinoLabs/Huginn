"""Validation checks for testbed and test plan inputs."""

from dataclasses import dataclass
from pathlib import Path

from huginn.enums import BrokerType, ErrorCode
from huginn.inventory_plugins import (
    InventoryPluginError,
    resolve_inventory_testbed,
)
from huginn.jobs import JobLoadError, load_test_case_class
from huginn.loaders import ConfigurationError, load_test_plan
from huginn.logging_helpers import log_debug, log_info, log_warning
from huginn.models import Phase, Testbed, TestCaseDefinition, TestCaseGroup, TestPlan
from huginn.output import Output
from huginn.plan_filtering import PlanFilterOptions, filter_test_plan
from huginn.result_store import write_validation_result
from huginn.runner import _resolve_targets
from huginn.runtime_broker import RuntimeBrokerError, normalize_broker_key
from huginn.testcase import TestCase


@dataclass
class ValidationCase:
    """Validation details for one phase/group/test-case execution node."""

    phase: str
    group: str
    test_id: str
    title: str
    required_brokers: list[str]
    targets: list[str]


@dataclass
class ValidationIssue:
    """Structured validation issue with category code and message."""

    code: str
    message: str


@dataclass
class ValidationResult:
    """Top-level validation result."""

    valid: bool
    phase_order: list[str]
    required_brokers: list[str]
    test_cases: list[ValidationCase]
    warnings: list[ValidationIssue]
    errors: list[ValidationIssue]


async def validate_inputs(
    *,
    testbed_path: Path | None,
    inventory_plugin: str | None,
    plan_path: Path,
    filters: PlanFilterOptions,
    project_root: Path,
    results_dir: Path,
    output: Output | None = None,
) -> ValidationResult:
    """Validate configuration and emit a validation result."""
    log_info(
        output,
        "Validation starting",
        plan=plan_path,
        testbed=testbed_path,
        inventory_plugin=inventory_plugin,
    )
    try:
        testbed = await resolve_inventory_testbed(
            testbed_path=testbed_path,
            inventory_plugin=inventory_plugin,
            project_root=project_root,
        )
        test_plan = filter_test_plan(load_test_plan(plan_path), filters)
        log_debug(
            output,
            "Validation inputs loaded",
            devices=len(testbed.devices),
            phases=len(test_plan.phases),
            groups=len(test_plan.test_case_groups),
            test_cases=len(test_plan.test_cases),
        )
    except (ConfigurationError, InventoryPluginError) as error:
        log_warning(output, "Validation configuration load failed", error=error)
        result = _build_configuration_error_result(str(error))
        _write_result(result=result, results_dir=results_dir)
        return result

    errors: list[ValidationIssue] = []
    phase_order, order_errors = _resolve_phase_order(test_plan)
    log_debug(
        output,
        "Phase order resolved",
        phase_order=phase_order,
        dependency_errors=len(order_errors),
    )
    errors.extend(order_errors)

    required_by_case = _collect_required_brokers(
        test_plan=test_plan,
        project_root=project_root,
        errors=errors,
        output=output,
    )

    test_cases, target_warnings, target_errors = _collect_target_validations(
        test_plan=test_plan,
        testbed=testbed,
        phase_order=phase_order,
        required_by_case=required_by_case,
        output=output,
    )
    errors.extend(target_errors)

    all_required = _collect_all_required_brokers(required_by_case)
    result = ValidationResult(
        valid=not errors,
        phase_order=phase_order,
        required_brokers=all_required,
        test_cases=test_cases,
        warnings=target_warnings,
        errors=errors,
    )
    _write_result(result=result, results_dir=results_dir)
    log_info(
        output,
        "Validation completed",
        valid=result.valid,
        warnings=len(result.warnings),
        errors=len(result.errors),
        test_cases=len(result.test_cases),
        required_brokers=result.required_brokers,
    )
    return result


def _build_configuration_error_result(error: str) -> ValidationResult:
    """Build a result for fatal configuration parse/load errors."""
    return ValidationResult(
        valid=False,
        phase_order=[],
        required_brokers=[],
        test_cases=[],
        warnings=[],
        errors=[
            ValidationIssue(
                code=ErrorCode.CONFIGURATION_ERROR.value,
                message=error,
            )
        ],
    )


def _collect_target_validations(
    *,
    test_plan: TestPlan,
    testbed: Testbed,
    phase_order: list[str],
    required_by_case: dict[str, set[str]],
    output: Output | None,
) -> tuple[list[ValidationCase], list[ValidationIssue], list[ValidationIssue]]:
    """Resolve targets per execution node and collect warnings/errors."""
    test_cases: list[ValidationCase] = []
    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []

    for phase_name in phase_order:
        phase = test_plan.phases[phase_name]
        for group_name in phase.test_case_groups:
            group = test_plan.test_case_groups[group_name]
            for test_id in group.tests:
                case = test_plan.test_cases[test_id]
                target_names, warning, error = _validate_case_targets(
                    testbed=testbed,
                    phase=phase,
                    group=group,
                    case=case,
                )
                if warning is not None:
                    log_warning(
                        output,
                        "Validation target warning",
                        phase=phase.name,
                        group=group.name,
                        test_id=case.test_id,
                        warning=warning,
                    )
                    warnings.append(
                        ValidationIssue(code="validation_warning", message=warning)
                    )
                if error is not None:
                    log_warning(
                        output,
                        "Validation target error",
                        phase=phase.name,
                        group=group.name,
                        test_id=case.test_id,
                        error=error,
                    )
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.VALIDATION_ERROR.value,
                            message=error,
                        )
                    )

                test_cases.append(
                    _build_validation_case(
                        phase_name=phase.name,
                        group_name=group.name,
                        case=case,
                        target_names=target_names,
                        required_by_case=required_by_case,
                    )
                )

    return test_cases, warnings, errors


def _validate_case_targets(
    *,
    testbed: Testbed,
    phase: Phase,
    group: TestCaseGroup,
    case: TestCaseDefinition,
) -> tuple[list[str], str | None, str | None]:
    """Resolve one case target set and return normalized diagnostics."""
    targets, target_error = _resolve_targets(
        testbed=testbed,
        phase=phase,
        group=group,
        test_case=case,
    )
    if target_error is not None:
        return [], None, target_error

    target_names = [device.name for device in targets]
    if target_names:
        return target_names, None, None

    warning = f"{phase.name}/{group.name}/{case.test_id} has no matched targets"
    return [], warning, None


def _build_validation_case(
    *,
    phase_name: str,
    group_name: str,
    case: TestCaseDefinition,
    target_names: list[str],
    required_by_case: dict[str, set[str]],
) -> ValidationCase:
    """Build one validation-case entry for the final result."""
    return ValidationCase(
        phase=phase_name,
        group=group_name,
        test_id=case.test_id,
        title=case.title,
        required_brokers=sorted(required_by_case.get(case.test_id, set())),
        targets=target_names,
    )


def _collect_all_required_brokers(required_by_case: dict[str, set[str]]) -> list[str]:
    """Collect sorted unique required brokers across all test cases."""
    return sorted({broker for req in required_by_case.values() for broker in req})


def _resolve_phase_order(
    test_plan: TestPlan,
) -> tuple[list[str], list[ValidationIssue]]:
    """Topologically sort phases by dependency order."""
    resolved: list[str] = []
    errors: list[ValidationIssue] = []
    pending = set(test_plan.phases.keys())

    while pending:
        progressed = False
        for phase_name in test_plan.phases:
            if phase_name not in pending:
                continue
            phase = test_plan.phases[phase_name]
            if all(dep in resolved for dep in phase.depends_on):
                resolved.append(phase_name)
                pending.remove(phase_name)
                progressed = True
        if not progressed:
            errors.append(
                ValidationIssue(
                    code=ErrorCode.VALIDATION_ERROR.value,
                    message=(
                        f"Unable to resolve phase dependencies for: {sorted(pending)}"
                    ),
                )
            )
            break

    return resolved, errors


def _collect_required_brokers(
    *,
    test_plan: TestPlan,
    project_root: Path,
    errors: list[ValidationIssue],
    output: Output | None,
) -> dict[str, set[str]]:
    """Load each job class and collect declared broker requirements."""
    required: dict[str, set[str]] = {}
    for test_case in test_plan.test_cases.values():
        try:
            test_case_class = load_test_case_class(
                job=test_case.job,
                project_root=project_root,
            )
            required[test_case.test_id] = _normalize_required_brokers(
                test_case_class,
            )
        except (JobLoadError, RuntimeBrokerError) as error:
            log_warning(
                output,
                "Validation planning failed",
                test_id=test_case.test_id,
                error=error,
            )
            errors.append(
                ValidationIssue(
                    code=ErrorCode.PLANNING_ERROR.value,
                    message=f"{test_case.test_id}: {error}",
                )
            )
            required[test_case.test_id] = {BrokerType.SSH.value}
    return required


def _normalize_required_brokers(test_case_class: type[TestCase]) -> set[str]:
    """Normalize a test class required_brokers declaration."""
    raw_required = getattr(test_case_class, "required_brokers", {BrokerType.SSH})
    if not isinstance(raw_required, set) or not raw_required:
        raise RuntimeBrokerError(
            f"{test_case_class.__name__}.required_brokers must be a non-empty set"
        )

    normalized: set[str] = set()
    for broker in raw_required:
        if not isinstance(broker, str):
            raise RuntimeBrokerError(
                f"{test_case_class.__name__}.required_brokers values must be strings"
            )
        normalized.add(normalize_broker_key(broker).value)
    return normalized


def _write_result(
    *,
    result: ValidationResult,
    results_dir: Path,
) -> None:
    """Persist validation result through Huginn's canonical JSON writer."""
    write_validation_result(result=result, results_dir=results_dir)
