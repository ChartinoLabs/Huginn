"""Unit tests for the relearn module."""

import json
from pathlib import Path

from huginn.relearn import parse_failed_test_ids


def _write_json(path: Path, payload: object) -> Path:
    """Write a JSON file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _build_run_json(
    *,
    scenarios: list[dict] | None = None,
) -> dict:
    """Build a minimal run.json payload."""
    if scenarios is None:
        scenarios = [
            {
                "id": "scenario-1",
                "name": "Test Scenario",
                "status": "failed",
                "phases": [
                    {
                        "id": "pre-change",
                        "name": "Pre-Change",
                        "status": "failed",
                        "test_case_groups": [
                            {
                                "id": "group-a",
                                "name": "Group A",
                                "status": "failed",
                                "test_cases": [
                                    {
                                        "test_id": "TEST-1",
                                        "title": "Test one",
                                        "status": "passed",
                                        "result_path": "test-cases/TEST-1/result.json",
                                    },
                                    {
                                        "test_id": "TEST-2",
                                        "title": "Test two",
                                        "status": "failed",
                                        "result_path": "test-cases/TEST-2/result.json",
                                    },
                                    {
                                        "test_id": "TEST-3",
                                        "title": "Test three",
                                        "status": "errored",
                                        "result_path": "test-cases/TEST-3/result.json",
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "id": "post-change",
                        "name": "Post-Change",
                        "status": "failed",
                        "test_case_groups": [
                            {
                                "id": "group-b",
                                "name": "Group B",
                                "status": "failed",
                                "test_cases": [
                                    {
                                        "test_id": "TEST-4",
                                        "title": "Test four",
                                        "status": "failed",
                                        "result_path": "test-cases/TEST-4/result.json",
                                    },
                                    {
                                        "test_id": "TEST-5",
                                        "title": "Test five",
                                        "status": "passed",
                                        "result_path": "test-cases/TEST-5/result.json",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            {
                "id": "scenario-2",
                "name": "Other Scenario",
                "status": "failed",
                "phases": [
                    {
                        "id": "pre-change",
                        "name": "Pre-Change",
                        "status": "failed",
                        "test_case_groups": [
                            {
                                "id": "group-c",
                                "name": "Group C",
                                "status": "failed",
                                "test_cases": [
                                    {
                                        "test_id": "TEST-6",
                                        "title": "Test six",
                                        "status": "failed",
                                        "result_path": "test-cases/TEST-6/result.json",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ]
    return {
        "summary": {"status": "failed", "total": 6, "passed": 2, "failed": 4},
        "mode": "testing",
        "scenarios": scenarios,
    }


class TestParseFailedTestIds:
    """Tests for parse_failed_test_ids."""

    def test_extracts_all_failures(self, tmp_path: Path) -> None:
        """Collect all failed and errored test IDs across scenarios."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json)
        assert result.test_ids == ["TEST-2", "TEST-3", "TEST-4", "TEST-6"]

    def test_returns_affected_scenarios(self, tmp_path: Path) -> None:
        """Return scenario IDs that contain at least one failure."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json)
        assert result.scenario_ids == ["scenario-1", "scenario-2"]

    def test_returns_affected_phases(self, tmp_path: Path) -> None:
        """Return phase IDs that contain at least one failure."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json)
        assert result.phase_ids == ["pre-change", "post-change"]

    def test_deduplicates_across_scenarios(self, tmp_path: Path) -> None:
        """Same test ID failing in multiple scenarios appears only once."""
        payload = _build_run_json(
            scenarios=[
                {
                    "id": "s1",
                    "name": "S1",
                    "status": "failed",
                    "phases": [
                        {
                            "id": "p1",
                            "name": "P1",
                            "status": "failed",
                            "test_case_groups": [
                                {
                                    "id": "g1",
                                    "name": "G1",
                                    "status": "failed",
                                    "test_cases": [
                                        {
                                            "test_id": "DUPE-1",
                                            "title": "Dupe",
                                            "status": "failed",
                                            "result_path": "x",
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "id": "s2",
                    "name": "S2",
                    "status": "failed",
                    "phases": [
                        {
                            "id": "p1",
                            "name": "P1",
                            "status": "failed",
                            "test_case_groups": [
                                {
                                    "id": "g2",
                                    "name": "G2",
                                    "status": "failed",
                                    "test_cases": [
                                        {
                                            "test_id": "DUPE-1",
                                            "title": "Same",
                                            "status": "failed",
                                            "result_path": "y",
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ]
        )
        run_json = _write_json(tmp_path / "run.json", payload)
        result = parse_failed_test_ids(run_json)
        assert result.test_ids == ["DUPE-1"]
        assert result.scenario_ids == ["s1", "s2"]
        assert result.phase_ids == ["p1"]

    def test_scenario_filter(self, tmp_path: Path) -> None:
        """Only include failures from the filtered scenario."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json, scenario_filter="scenario-2")
        assert result.test_ids == ["TEST-6"]
        assert result.scenario_ids == ["scenario-2"]

    def test_phase_filter(self, tmp_path: Path) -> None:
        """Only include failures from the filtered phase."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json, phase_filter="post-change")
        assert result.test_ids == ["TEST-4"]
        assert result.phase_ids == ["post-change"]

    def test_scenario_and_phase_filter(self, tmp_path: Path) -> None:
        """Both filters narrow results to the intersection."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(
            run_json, scenario_filter="scenario-1", phase_filter="pre-change"
        )
        assert result.test_ids == ["TEST-2", "TEST-3"]
        assert result.scenario_ids == ["scenario-1"]
        assert result.phase_ids == ["pre-change"]

    def test_no_failures_returns_empty(self, tmp_path: Path) -> None:
        """Return empty lists when all tests passed."""
        payload = _build_run_json(
            scenarios=[
                {
                    "id": "s1",
                    "name": "S1",
                    "status": "passed",
                    "phases": [
                        {
                            "id": "p1",
                            "name": "P1",
                            "status": "passed",
                            "test_case_groups": [
                                {
                                    "id": "g1",
                                    "name": "G1",
                                    "status": "passed",
                                    "test_cases": [
                                        {
                                            "test_id": "OK-1",
                                            "title": "All good",
                                            "status": "passed",
                                            "result_path": "x",
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ]
        )
        run_json = _write_json(tmp_path / "run.json", payload)
        result = parse_failed_test_ids(run_json)
        assert result.test_ids == []
        assert result.scenario_ids == []
        assert result.phase_ids == []

    def test_nonexistent_scenario_filter_returns_empty(self, tmp_path: Path) -> None:
        """Return empty when scenario filter matches nothing."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json, scenario_filter="nonexistent")
        assert result.test_ids == []

    def test_nonexistent_phase_filter_returns_empty(self, tmp_path: Path) -> None:
        """Return empty when phase filter matches nothing."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(run_json, phase_filter="nonexistent")
        assert result.test_ids == []

    def test_includes_errored_status(self, tmp_path: Path) -> None:
        """Errored tests are included alongside failed ones."""
        run_json = _write_json(tmp_path / "run.json", _build_run_json())
        result = parse_failed_test_ids(
            run_json, scenario_filter="scenario-1", phase_filter="pre-change"
        )
        assert "TEST-3" in result.test_ids
