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

    out = sample_points_from_well_table(table, include_flagged=True, value_key="z")
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
    # 砂地比-typed table: the export value key is the R_s column (#1151), so
    # the fixture carries an explicit ratio (sand_ratio alias) rather than a
    # generic value that silently lands in z.
    table = well_table_from_sample_points(
        [{"well": "W1", "x": 1, "y": 2, "sand_ratio": 0.4}],
        name="wells",
    )
    attach_well_table_to_factor_task(project, table, task)
    assert task.well_table_id == table.id
    assert project.well_tables[0].id == table.id
    assert task.parameters["sample_points"][0]["well"] == "W1"
    assert task.parameters["sample_points"][0]["value"] == 0.4
    assert task.parameters["well_table_id"] == table.id


def test_attach_task_factor_type_wins_over_table(caplog):
    """attach/sync value-key consistency: a table typed A attached to a task
    typed B exports with B's value key (task owns the factor semantics),
    warns about the conflict, and sync afterwards exports identically."""
    import logging as _logging

    from paleo_workbench.workflow.well_table import sync_well_table_to_linked_tasks

    project = ProjectDocument.new("P")
    task = FactorMapTask(
        name="砂地比",
        target_horizon="C6",
        factor_type="砂地比",  # B → R_s value key
        method="IDW",
    )
    project.factor_map_tasks.append(task)
    # Table typed A (砂岩厚度 → H_s value key) carrying BOTH quantities.
    table = well_table_from_sample_points(
        [{"well": "W1", "x": 1, "y": 2, "H_s": 3.0, "sand_ratio": 0.4}],
        name="wells",
        factor_type="砂岩厚度",  # A
    )
    with caplog.at_level(_logging.WARNING, logger="paleo_workbench.workflow.well_table"):
        attach_well_table_to_factor_task(project, table, task)
    # Task's factor type (B=砂地比) picked the export value key: R_s, not H_s.
    assert task.parameters["sample_points"][0]["value"] == 0.4
    assert any("不一致" in r.message for r in caplog.records)

    # sync (same table, same task) must export the same value key — no flip.
    sync_well_table_to_linked_tasks(project, table)
    assert task.parameters["sample_points"][0]["value"] == 0.4


def test_attach_table_factor_type_used_when_task_has_none():
    """No task factor type → the table's own type picks the value key."""
    project = ProjectDocument.new("P")
    task = FactorMapTask(
        name="厚度",
        target_horizon="C6",
        factor_type="",
        method="IDW",
    )
    project.factor_map_tasks.append(task)
    table = well_table_from_sample_points(
        [{"well": "W1", "x": 1, "y": 2, "H_s": 3.0, "sand_ratio": 0.4}],
        name="wells",
        factor_type="砂岩厚度",  # H_s value key
    )
    attach_well_table_to_factor_task(project, table, task)
    assert task.parameters["sample_points"][0]["value"] == 3.0


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
    clean = sample_points_from_well_table(table, value_key="z")
    assert len(clean) == 1
    assert clean[0]["well"] == "A"
    all_pts = sample_points_from_well_table(table, include_flagged=True, value_key="z")
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
    # Sand-ratio table: MAD must score R_s, not the (absent) metre-valued z.
    run_well_table_qc(table, value_key="R_s")
    by_name = {r.name: r for r in table.rows}
    assert by_name["A"].R_s == 0.3
    # #1151 residual fix: R_s is NEVER written into the z column — rows that
    # arrived without a measured z keep z=None instead of a dimensionless mix.
    assert by_name["A"].z is None
    assert by_name["BAD"].qc_flag == "invalid_ratio"
    summary = qc_summary(table)
    assert summary["invalid_ratio"] == 1
    assert summary["total"] == 4


def test_sand_ratio_qc_never_backfills_z():
    """Rows with z=None but valid H_s/H_t get R_s + QC verdicts, z stays None."""
    table = well_table_from_sample_points(
        [
            {"well": "A", "x": 0, "y": 0, "H_s": 3, "H_t": 10},
            {"well": "B", "x": 1, "y": 0, "H_s": 4, "H_t": 10},
        ]
    )
    assert all(r.z is None for r in table.rows)
    run_well_table_qc(table, value_key="R_s")
    assert all(r.z is None for r in table.rows)  # dimension untouched
    assert [r.R_s for r in table.rows] == [0.3, 0.4]
    assert all(r.qc_flag == "ok" for r in table.rows)


def test_run_well_table_qc_default_value_key_is_z():
    """Back-compat: no value_key → MAD scores z; a z-less table flags missing."""
    table = well_table_from_sample_points(
        [
            {"well": "A", "x": 0, "y": 0, "value": 10.0},
            {"well": "B", "x": 1, "y": 0, "value": 10.1},
            {"well": "C", "x": 2, "y": 0, "H_s": 3, "H_t": 10},  # z absent
        ]
    )
    run_well_table_qc(table)
    by_name = {r.name: r for r in table.rows}
    assert by_name["A"].qc_flag == "ok"
    assert by_name["B"].qc_flag == "ok"
    # Row C has no z; the old code backfilled it with R_s=0.3 and scored that
    # against metre values. Now it is honestly "missing" and z stays None.
    assert by_name["C"].qc_flag == "missing"
    assert by_name["C"].z is None
    assert by_name["C"].R_s == 0.3


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


# ------------------------------------------- audit #1151: explicit value keys


def test_value_key_for_factor_type_families():
    from paleo_workbench.workflow.well_table import value_key_for_factor_type

    assert value_key_for_factor_type("砂地比") == "R_s"
    assert value_key_for_factor_type("sand_ratio") == "R_s"
    assert value_key_for_factor_type("R_s") == "R_s"
    assert value_key_for_factor_type("rs") == "R_s"
    assert value_key_for_factor_type("地层厚度") == "H_t"
    assert value_key_for_factor_type("formation_thickness") == "H_t"
    assert value_key_for_factor_type("砂岩厚度") == "H_s"
    assert value_key_for_factor_type("sand_thickness") == "H_s"
    # Unknown / untyped factors export the raw measured value.
    assert value_key_for_factor_type("孔隙度") == "z"
    assert value_key_for_factor_type("") == "z"
    assert value_key_for_factor_type("anything") == "z"


def test_sample_points_value_key_no_cross_dimension_fallback():
    """Mixed rows export ONLY the explicitly selected physical quantity.

    Old behaviour fell back per row z→R_s→H_t, mixing a dimensionless ratio
    with metre thicknesses in one interpolation field.
    """
    table = well_table_from_sample_points(
        [
            {"well": "Z1", "x": 0, "y": 0, "value": 0.3},
            {"well": "Z2", "x": 1, "y": 0, "value": 0.4},
            {"well": "R1", "x": 2, "y": 0, "sand_ratio": 0.5},
            {"well": "H1", "x": 3, "y": 0, "total_thickness": 42.0},
        ]
    )
    # Export the ratio column: only R1 has it.
    stats: dict[str, int] = {}
    pts = sample_points_from_well_table(table, value_key="R_s", stats=stats)
    assert [p["well"] for p in pts] == ["R1"]
    assert pts[0]["value"] == 0.5
    assert stats["exported"] == 1
    assert stats["skipped_missing_value"] == 3

    # Export the raw z column: only Z1/Z2 have it — H_t metres never leak in.
    pts_z = sample_points_from_well_table(table, value_key="z")
    assert [p["well"] for p in pts_z] == ["Z1", "Z2"]
    assert [p["value"] for p in pts_z] == [0.3, 0.4]

    # Export the thickness column: only H1 has it; ratios never leak in.
    pts_t = sample_points_from_well_table(table, value_key="H_t")
    assert [p["well"] for p in pts_t] == ["H1"]
    assert pts_t[0]["value"] == 42.0


def test_sample_points_rejects_unknown_value_key():
    import pytest

    table = well_table_from_sample_points([{"well": "A", "x": 0, "y": 0, "value": 1}])
    with pytest.raises(ValueError, match="value_key"):
        sample_points_from_well_table(table, value_key="bogus")


def test_well_table_to_arrays_value_key_skips_and_counts():
    from paleo_workbench.workflow.well_table import well_table_to_arrays

    table = well_table_from_sample_points(
        [
            {"well": "Z1", "x": 0, "y": 0, "value": 0.3},
            {"well": "R1", "x": 2, "y": 0, "sand_ratio": 0.5},
        ]
    )
    arrs = well_table_to_arrays(table, value_key="R_s", include_flagged=True)
    assert list(arrs["names"]) == ["R1"]
    import numpy as np

    np.testing.assert_allclose(arrs["z"], [0.5])
    assert arrs["skipped_missing"] == 1


def test_mad_outlier_qc_no_cross_dimension_fallback():
    """MAD scores only the selected column; z-missing rows flag 'missing'.

    Old behaviour scored such rows with H_t metres (or R_s) against a z
    population — mixing physical dimensions in one MAD field.
    """
    table = well_table_from_sample_points(
        [
            *[{"well": f"N{i}", "x": float(i), "y": 0.0, "value": 10.0 + i * 0.1} for i in range(9)],
            # No z: has metres of thickness only — must NOT enter the z MAD set.
            {"well": "THICK", "x": 50.0, "y": 0.0, "total_thickness": 500.0},
        ]
    )
    apply_mad_outlier_qc(table, threshold=3.5)
    by_name = {r.name: r for r in table.rows}
    assert by_name["THICK"].qc_flag == "missing"
    assert by_name["THICK"].qc_z_star is None
    assert by_name["N0"].qc_flag == "ok"

    # Explicit ratio column scoring works standalone.
    ratio_table = well_table_from_sample_points(
        [
            *[{"well": f"R{i}", "x": float(i), "y": 0.0, "sand_ratio": 0.3 + 0.01 * i} for i in range(9)],
            {"well": "ROUT", "x": 99.0, "y": 0.0, "sand_ratio": 9.9},
        ]
    )
    apply_mad_outlier_qc(ratio_table, threshold=3.5, value_attr="R_s")
    by_name = {r.name: r for r in ratio_table.rows}
    assert by_name["ROUT"].qc_flag == "outlier"
    assert by_name["R0"].qc_flag == "ok"
