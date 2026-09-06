"""V6 §10 — constraint routing honesty end-to-end (audit P0-6/P0-7).

Faults + kriging used to produce a fault-oblivious surface reporting
``n_break_lines: 0`` while the UI still showed the faults. The capability
matrix evaluation must put requested/applied/ignored on the task and grid.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("scipy")

from geoviz_plots.factor.interpolation import synthetic_sample_points
from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _task() -> FactorMapTask:
    return FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="克里金",
        parameters={
            "sample_points": synthetic_sample_points(seed=2, factor_type="厚度")
        },
        status="pending",
        source_kind="mixed",
    )


FAULTS = [[(0.0, 0.0), (0.5, 0.5), (1.0, 0.6)]]


class TestConstraintRouting:
    def test_kriging_with_faults_records_unsupported_barrier(self):
        task = _task()
        apply_interpolation_to_task(task, method="克里金", grid_n=12, fault_polylines=FAULTS)
        assert task.status == "complete"
        record = task.parameters["constraint_diagnostics"]
        assert record["requested_constraints"] == ["barrier"]
        assert record["unsupported_constraints"] == ["barrier"]
        assert record["applied_constraints"] == []
        assert any("barrier" in d for d in record["constraint_diagnostics"])

    def test_kriging_grid_carries_the_same_record(self):
        from paleo_workbench.project.factor_grid_artifacts import (
            factor_grid_result_for_task,
        )

        task = _task()
        apply_interpolation_to_task(task, method="克里金", grid_n=12, fault_polylines=FAULTS)
        grid = factor_grid_result_for_task(task)
        assert grid.algorithm_parameters["constraint_diagnostics"][
            "unsupported_constraints"
        ] == ["barrier"]

    def test_idw_with_faults_applies_barrier(self):
        task = _task()
        task.method = "IDW"
        apply_interpolation_to_task(task, method="IDW", grid_n=12, fault_polylines=FAULTS)
        record = task.parameters["constraint_diagnostics"]
        assert record["applied_constraints"] == ["barrier"]
        assert record["unsupported_constraints"] == []
        assert task.parameters["n_break_lines"] == 1

    def test_engine_reports_ignored_constraints_in_status(self):
        from geoviz_plots.factor.interpolation import interpolate_factor_grid

        points = synthetic_sample_points(seed=3, factor_type="厚度")
        result = interpolate_factor_grid(
            points, method="克里金", grid_n=10, fault_polylines=FAULTS
        )
        assert result["ignored_constraints"], "kriging + faults must never be silent"
        assert any("barrier" in entry for entry in result["ignored_constraints"])
        assert result["constraint_warnings"]

    def test_no_constraints_clean_record(self):
        task = _task()
        apply_interpolation_to_task(task, method="克里金", grid_n=12)
        record = task.parameters["constraint_diagnostics"]
        assert record["requested_constraints"] == []
        assert record["unsupported_constraints"] == []
