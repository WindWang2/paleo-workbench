"""ISS-DOM-01 / ISS-ALG-01: WellTable model, adapters, MAD + sand-ratio QC."""

from __future__ import annotations

import math

import numpy as np

from paleo_workbench.project.models import FactorMapTask, ProjectDocument, WellTableRow
from paleo_workbench.workflow.well_qc import (
    apply_mad_outlier_qc,
    apply_sand_ratio_qc,
    compute_sand_ratio,
    median_absolute_deviation,
    modified_z_scores,
    qc_summary,
    run_well_table_qc,
)
from paleo_workbench.workflow.well_table import (
    attach_well_table_to_factor_task,
    sample_points_from_well_table,
    well_table_from_factor_task,
    well_table_from_sample_points,
)


def test_well_table_from_sample_points_roundtrip():
    points = [
        {"well": "A1", "x": 114.0, "y": 22.5, "value": 0.3, "H_s": 3, "H_t": 10},
        {"well": "A2", "lng": 114.1, "lat": 22.6, "z": 0.5},
    ]
    table = well_table_from_sample_points(
        points, name="T1", target_horizon="C6", factor_type="砂地比"
    )
    assert len(table.rows) == 2
    assert table.rows[0].name == "A1"
    assert table.rows[0].H_s == 3.0
    assert table.rows[1].x == 114.1

    out = sample_points_from_well_table(table, include_flagged=True)
    assert len(out) == 2
    assert out[0]["value"] == 0.3
    assert out[0]["H_s"] == 3.0


def test_attach_well_table_syncs_factor_task():
    project = ProjectDocument.new("P")
    task = FactorMapTask(
        name="砂地比",
        target_horizon="C6",
        factor_type="砂地比",
        method="IDW",
    )
    project.factor_map_tasks.append(task)
    table = well_table_from_sample_points(
        [{"well": "W1", "x": 1, "y": 2, "value": 0.4}],
        name="wells",
    )
    attach_well_table_to_factor_task(project, table, task)
    assert task.well_table_id == table.id
    assert project.well_tables[0].id == table.id
    assert task.parameters["sample_points"][0]["well"] == "W1"
    assert task.parameters["well_table_id"] == table.id


def test_well_table_from_factor_task():
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="IDW",
        parameters={"sample_points": [{"well": "B1", "x": 0, "y": 0, "value": 12}]},
    )
    table = well_table_from_factor_task(task)
    assert table.factor_type == "地层厚度"
    assert table.rows[0].z == 12.0


def test_compute_sand_ratio_constraints():
    assert compute_sand_ratio(3, 10) == (0.3, "ok")
    assert compute_sand_ratio(0, 5) == (0.0, "ok")
    assert compute_sand_ratio(5, 5) == (1.0, "ok")
    r, flag = compute_sand_ratio(6, 5)
    assert r is None and flag == "invalid_ratio"
    r, flag = compute_sand_ratio(1, 0)
    assert r is None and flag == "invalid_ratio"
    r, flag = compute_sand_ratio(-1, 5)
    assert r is None and flag == "invalid_ratio"


def test_mad_flags_clear_outlier():
    # Nine normal values around 10, one extreme 100.
    table = well_table_from_sample_points(
        [
            *[{"well": f"N{i}", "x": float(i), "y": 0.0, "value": 10.0 + (i % 3) * 0.1} for i in range(9)],
            {"well": "OUT", "x": 99.0, "y": 0.0, "value": 100.0},
        ]
    )
    apply_mad_outlier_qc(table, threshold=3.5)
    by_name = {r.name: r for r in table.rows}
    assert by_name["OUT"].qc_flag == "outlier"
    assert by_name["OUT"].qc_z_star is not None
    assert abs(by_name["OUT"].qc_z_star) > 3.5
    assert by_name["N0"].qc_flag == "ok"


def test_sample_points_skip_flagged_by_default():
    table = well_table_from_sample_points(
        [
            {"well": "A", "x": 0, "y": 0, "value": 1},
            {"well": "B", "x": 1, "y": 0, "value": 100},
        ]
    )
    table.rows[1].qc_flag = "outlier"
    clean = sample_points_from_well_table(table)
    assert len(clean) == 1
    assert clean[0]["well"] == "A"
    all_pts = sample_points_from_well_table(table, include_flagged=True)
    assert len(all_pts) == 2


def test_run_well_table_qc_sand_ratio_then_mad():
    table = well_table_from_sample_points(
        [
            {"well": "A", "x": 0, "y": 0, "H_s": 3, "H_t": 10},
            {"well": "B", "x": 1, "y": 0, "H_s": 4, "H_t": 10},
            {"well": "C", "x": 2, "y": 0, "H_s": 5, "H_t": 10},
            {"well": "BAD", "x": 3, "y": 0, "H_s": 20, "H_t": 10},
        ]
    )
    run_well_table_qc(table)
    by_name = {r.name: r for r in table.rows}
    assert by_name["A"].R_s == 0.3
    assert by_name["A"].z == 0.3
    assert by_name["BAD"].qc_flag == "invalid_ratio"
    summary = qc_summary(table)
    assert summary["invalid_ratio"] == 1
    assert summary["total"] == 4


def test_modified_z_score_formula():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
    mad = median_absolute_deviation(vals)
    med = float(np.median(vals))
    z = modified_z_scores(vals)
    expected = 0.6745 * (100.0 - med) / mad
    assert math.isclose(float(z[-1]), expected, rel_tol=1e-9)


def test_project_document_serializes_well_tables():
    project = ProjectDocument.new("Ser")
    table = well_table_from_sample_points([{"well": "A", "x": 1, "y": 2, "value": 3}])
    project.well_tables.append(table)
    data = project.model_dump()
    restored = ProjectDocument.model_validate(data)
    assert len(restored.well_tables) == 1
    assert restored.well_tables[0].rows[0].name == "A"


def test_missing_z_rows_skipped_never_coerced_from_rs_ht():
    """#1151: R_s (ratio) / H_t (meters) must not stand in for z."""
    from paleo_workbench.project.models import WellTable, WellTableRow
    from paleo_workbench.workflow.well_table import well_table_to_arrays

    table = WellTable(
        id="t", name="T", rows=[
            WellTableRow(well_id="w1", name="A", x=0.0, y=0.0, z=5.0, qc_flag="ok"),
            WellTableRow(well_id="w2", name="B", x=1.0, y=0.0, z=None, R_s=0.5, H_t=10.0, qc_flag="ok"),
        ],
    )
    points = sample_points_from_well_table(table)
    assert [p["well"] for p in points] == ["A"]
    assert points[0]["value"] == 5.0
    arrays = well_table_to_arrays(table)
    assert arrays["z"][0] == 5.0
    assert math.isnan(arrays["z"][1])
