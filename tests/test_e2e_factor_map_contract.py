"""ISS-E2E-01: single-factor map pipeline contract.

WellTable → MAD/sand-ratio QC → constraints → directional trend / IDW
→ ContourDraft → map line_features → basic QC → VersionSet finalize.
"""

from __future__ import annotations

from paleo_workbench.project.models import (
    CompilationRun,
    ConstraintLayers,
    ConstraintLine,
    ProjectDocument,
)
from paleo_workbench.workflow.constraints import upsert_constraint_layers
from paleo_workbench.workflow.contour_draft import compile_contour_drafts_for_project
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
)
from paleo_workbench.workflow.qc import active_quality_reports, run_basic_qc
from paleo_workbench.workflow.versioning import (
    active_final_snapshot,
    finalize_map_version,
    version_set_summary,
)
from paleo_workbench.workflow.well_qc import qc_summary, run_well_table_qc
from paleo_workbench.workflow.well_table import (
    attach_well_table_to_factor_task,
    sample_points_from_well_table,
    well_table_from_sample_points,
)


def test_e2e_factor_map_welltable_to_version_set():
    project = ProjectDocument.new("E2E-Factor")
    project.stratigraphy.target_horizon = "C6"
    project.compilation_runs.append(
        CompilationRun(name="run-e2e", target_horizon="C6", status="draft")
    )

    # 1) WellTable from sample wells (incl. one invalid sand ratio + one outlier)
    raw_points = [
        {"well": "A1", "x": 0.0, "y": 0.0, "H_s": 3.0, "H_t": 10.0, "value": 0.30},
        {"well": "A2", "x": 1.0, "y": 0.0, "H_s": 4.0, "H_t": 10.0, "value": 0.40},
        {"well": "A3", "x": 0.0, "y": 1.0, "H_s": 5.0, "H_t": 10.0, "value": 0.50},
        {"well": "A4", "x": 1.0, "y": 1.0, "H_s": 3.5, "H_t": 10.0, "value": 0.35},
        {"well": "BAD", "x": 0.5, "y": 0.5, "H_s": 20.0, "H_t": 10.0, "value": 2.0},
        {"well": "OUT", "x": 2.0, "y": 2.0, "H_s": 4.0, "H_t": 10.0, "value": 9.9},
    ]
    table = well_table_from_sample_points(
        raw_points,
        name="C6 井点",
        target_horizon="C6",
        factor_type="砂地比",
    )
    run_well_table_qc(table)
    summary = qc_summary(table)
    assert summary["invalid_ratio"] >= 1
    assert summary["outlier"] >= 1
    clean = sample_points_from_well_table(table, include_flagged=False)
    assert len(clean) >= 4
    assert all(p.get("qc_flag", "ok") == "ok" for p in clean)

    # 2) Constraints: break + direction for C6
    layers = ConstraintLayers(
        name="C6 约束",
        target_horizon="C6",
        lines=[
            ConstraintLine(
                name="F1",
                role="break",
                coordinates=[[0.5, -0.5], [0.5, 1.5]],
                target_horizon="C6",
            ),
            ConstraintLine(
                name="D1",
                role="direction",
                coordinates=[[0, 0], [0, 1]],
                azimuth_deg=0.0,
                semi_major=2.0,
                semi_minor=0.4,
                target_horizon="C6",
            ),
        ],
    )
    upsert_constraint_layers(project, layers)

    # 3) Factor task linked to WellTable → directional trend surface
    from paleo_workbench.project.models import FactorMapTask

    task = FactorMapTask(
        name="C6 砂地比",
        target_horizon="C6",
        factor_type="砂地比",
        method="方向趋势",
        parameters={"sample_points": clean},
        status="pending",
        source_kind="real",
    )
    project.factor_map_tasks.append(task)
    attach_well_table_to_factor_task(project, table, task)
    # Re-sync cleaned points after attach (attach uses current table QC flags)
    task.parameters["sample_points"] = sample_points_from_well_table(table)

    apply_interpolation_to_task(
        task, method="方向趋势", grid_n=10, project=project
    )
    assert task.status == "complete"
    assert task.parameters.get("interp_backend") == "directional"
    assert task.parameters.get("azimuth_deg") == 0.0
    assert task.parameters.get("grid_z")
    assert len(task.parameters["grid_z"]) == 10

    # 4) ContourDraft from grids → map line_features
    drafts = compile_contour_drafts_for_project(project, n_levels=4, apply_to_map=True)
    assert drafts
    draft = drafts[0]
    assert draft.linked_factor_task_id == task.id
    assert draft.segments
    assert project.paleomap_documents
    map_doc = project.paleomap_documents[-1]
    assert map_doc.linked_contour_draft_id == draft.id
    contours = [
        f for f in map_doc.line_features if isinstance(f, dict) and f.get("role") == "contour"
    ]
    assert contours
    assert draft.status == "editing"

    # 5) Basic map QC upsert
    qc1 = run_basic_qc(project, map_doc.id)
    qc2 = run_basic_qc(project, map_doc.id)
    assert qc1.id == qc2.id
    assert len(active_quality_reports(project)) == 1

    # 6) Expert finalize → VersionSet
    vset = finalize_map_version(
        project,
        map_doc.id,
        note="e2e contract",
        operator="e2e",
        require_qc_pass=False,
    )
    assert vset.status == "final"
    assert vset.finalized_by == "e2e"
    snap = active_final_snapshot(project, target_horizon="C6")
    assert snap is not None
    assert snap.map_document_id == map_doc.id
    assert snap.contour_draft_id == draft.id
    assert snap.quality_report_id == qc2.id
    assert snap.content_fingerprint
    draft_live = next(d for d in project.contour_drafts if d.id == draft.id)
    assert draft_live.status == "final"
    assert project.compilation_runs[-1].status == "export_ready"
    assert project.compilation_runs[-1].active_paleomap_document_id == map_doc.id

    summary = version_set_summary(project)
    assert summary["final_count"] == 1
    assert summary["latest_final_horizon"] == "C6"

    # 7) Round-trip persistence of new domain objects
    restored = ProjectDocument.model_validate(project.model_dump())
    assert restored.well_tables
    assert restored.constraint_layers
    assert restored.contour_drafts
    assert restored.version_sets
    assert restored.version_sets[0].status == "final"
    assert restored.factor_map_tasks[0].parameters.get("grid_z")


def test_e2e_idw_with_break_lines_and_batch_prepare():
    """Alternate path: batch IDW + break barriers still reaches contour + finalize."""
    project = ProjectDocument.new("E2E-IDW")
    project.stratigraphy.target_horizon = "H1"
    project.constraint_layers.append(
        ConstraintLayers(
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    role="break",
                    coordinates=[[0.4, -1], [0.4, 2]],
                    target_horizon="H1",
                )
            ],
        )
    )
    prepared = batch_prepare_factor_maps(
        project, method="IDW", grid_n=8, seed=1, factor_types=["地层厚度"]
    )
    assert prepared
    assert prepared[0].parameters.get("n_break_lines", 0) >= 1 or prepared[0].parameters.get(
        "grid_z"
    )

    drafts = compile_contour_drafts_for_project(project, n_levels=3)
    assert drafts
    map_doc = project.paleomap_documents[-1]
    run_basic_qc(project, map_doc.id)
    vset = finalize_map_version(project, map_doc.id, operator="batch")
    assert vset.status == "final"
    assert active_final_snapshot(project) is not None
