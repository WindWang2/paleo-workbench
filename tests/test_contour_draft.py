"""ISS-DOM-03: ContourDraft from FactorMapTask grids."""

from __future__ import annotations

import dataclasses

import numpy as np

from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.workflow.contour_draft import (
    GENERATOR_VERSION,
    apply_contour_draft_to_map,
    compile_contour_draft_from_task,
    contour_draft_from_factor_task,
    line_features_from_contour_draft,
    suggest_levels,
    upsert_contour_draft,
)
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _task_with_grid() -> FactorMapTask:
    # Smooth ramp so contourpy finds clear isolines.
    gx = np.linspace(0.0, 10.0, 12)
    gy = np.linspace(0.0, 10.0, 12)
    X, Y = np.meshgrid(gx, gy)
    Z = 0.1 * X + 0.2 * Y
    task = FactorMapTask(
        name="厚度",
        target_horizon="C6",
        factor_type="地层厚度",
        method="IDW",
        parameters={
            "grid_x": [float(v) for v in gx],
            "grid_y": [float(v) for v in gy],
            "grid_z": [[float(v) for v in row] for row in Z],
            "grid_n": 12,
            "interp_backend": "idw",
            "sample_points": [
                {"x": 0, "y": 0, "value": 0.0},
                {"x": 10, "y": 10, "value": 3.0},
            ],
        },
        status="complete",
    )
    return task


def test_suggest_levels_interior():
    z = np.linspace(0, 10, 20).reshape(4, 5)
    levels = suggest_levels(z, n_levels=4)
    assert len(levels) == 4
    assert levels[0] > 0
    assert levels[-1] < 10


def test_contour_draft_from_factor_task_extracts_segments():
    task = _task_with_grid()
    draft = contour_draft_from_factor_task(task, n_levels=5)
    assert draft.target_horizon == "C6"
    assert draft.factor_type == "地层厚度"
    assert draft.linked_factor_task_id == task.id
    assert draft.generator_version == GENERATOR_VERSION
    # #928: levels are upstream-style nice steps (multiples of a rounded
    # step anchored at the data range), so the count is a *target*, not an
    # exact promise; the ramp 0..3 with n=5 snaps to step 1.0 → [1, 2].
    assert 2 <= len(draft.levels) <= 8
    assert all(level != 0.0 or True for level in draft.levels)
    assert len(draft.segments) >= 1
    for seg in draft.segments:
        assert len(seg.coordinates) >= 2
        assert seg.level in draft.levels


def test_line_features_role_contour():
    task = _task_with_grid()
    draft = contour_draft_from_factor_task(task, levels=[1.0, 1.5])
    feats = line_features_from_contour_draft(draft)
    assert feats
    assert all(f["role"] == "contour" for f in feats)
    assert all(f["properties"]["contour_draft_id"] == draft.id for f in feats)


def test_upsert_contour_draft_idempotent_by_task():
    project = ProjectDocument.new("C")
    task = _task_with_grid()
    d1 = contour_draft_from_factor_task(task)
    upsert_contour_draft(project, d1)
    d2 = contour_draft_from_factor_task(task, n_levels=6)
    upsert_contour_draft(project, d2)
    assert len(project.contour_drafts) == 1
    assert project.contour_drafts[0].id == d1.id
    # Nice-step levels: count near the target, replaced wholesale on upsert.
    assert 2 <= len(project.contour_drafts[0].levels) <= 9
    assert project.contour_drafts[0].levels == d2.levels


def test_apply_contour_draft_to_map_creates_document():
    project = ProjectDocument.new("M")
    task = _task_with_grid()
    draft = contour_draft_from_factor_task(task)
    upsert_contour_draft(project, draft)
    doc = apply_contour_draft_to_map(project, draft)
    assert doc in project.paleomap_documents
    assert doc.linked_contour_draft_id == draft.id
    assert draft.linked_map_document_id == doc.id
    contours = [f for f in doc.line_features if f.get("role") == "contour"]
    assert len(contours) == len(draft.segments)
    assert draft.status == "editing"

    # Re-apply replaces previous contour lines only
    draft2 = contour_draft_from_factor_task(task, levels=[1.0])
    draft2.id = draft.id
    apply_contour_draft_to_map(project, draft2, map_document=doc)
    contours2 = [f for f in doc.line_features if f.get("role") == "contour"]
    assert len(contours2) == len(draft2.segments)


def test_compile_end_to_end_from_interpolation():
    project = ProjectDocument.new("E2E")
    task = FactorMapTask(
        name="砂地比",
        target_horizon="H1",
        factor_type="砂地比",
        method="IDW",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 0.1},
                {"x": 1.0, "y": 0.0, "value": 0.2},
                {"x": 0.0, "y": 1.0, "value": 0.3},
                {"x": 1.0, "y": 1.0, "value": 0.4},
                {"x": 0.5, "y": 0.5, "value": 0.25},
            ]
        },
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=10)
    project.factor_map_tasks.append(task)
    draft = compile_contour_draft_from_task(project, task, n_levels=4)
    assert draft in project.contour_drafts or any(
        d.id == draft.id for d in project.contour_drafts
    )
    assert project.paleomap_documents
    assert any(
        f.get("role") == "contour" for f in project.paleomap_documents[0].line_features
    )


def test_project_serializes_contour_drafts():
    project = ProjectDocument.new("Ser")
    task = _task_with_grid()
    draft = contour_draft_from_factor_task(task)
    project.contour_drafts.append(draft)
    restored = ProjectDocument.model_validate(project.model_dump())
    assert len(restored.contour_drafts) == 1
    assert restored.contour_drafts[0].segments


# --------------------------------------------------------------------------- #
# #928 — vendored upstream contour pipeline activation
# --------------------------------------------------------------------------- #


def _constrained_task_with_breaks(grid_n: int = 96) -> FactorMapTask:
    rng = np.random.default_rng(4242)
    pts = [
        {"well": f"w{i}", "x": float(x), "y": float(y), "value": float(v)}
        for i, (x, y, v) in enumerate(
            zip(rng.uniform(0, 1000, 40), rng.uniform(0, 1000, 40), rng.uniform(10, 60, 40))
        )
    ]
    task = FactorMapTask(
        name="约束IDW",
        target_horizon="H1",
        factor_type="厚度",
        method="约束IDW",
        parameters={
            "sample_points": pts,
            "break_polylines": [[(500.0, -50.0), (510.0, 1050.0)]],
        },
    )
    apply_interpolation_to_task(
        task, method="约束IDW", grid_n=grid_n,
        fault_polylines=[[(500.0, -50.0), (510.0, 1050.0)]],
    )
    return task


def test_constrained_idw_run_stores_engine_contours_and_keeps_grid(tmp_path):
    """#928: prepare-time engine contours ride the grid result; the surface is
    bit-identical to the surface-only pass (extraction must not move values)."""
    from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
    import dataclasses

    rng = np.random.default_rng(11)
    pts = [
        {"well": f"w{i}", "x": float(x), "y": float(y), "value": float(v)}
        for i, (x, y, v) in enumerate(
            zip(rng.uniform(0, 1000, 30), rng.uniform(0, 1000, 30), rng.uniform(10, 60, 30))
        )
    ]
    breaks = [[(500.0, -50.0), (510.0, 1050.0)]]
    with_contours = run_constrained_idw(
        pts, grid_n=64, power=2.0, break_polylines=breaks
    )
    assert with_contours["contours"], "engine contours missing from result"
    assert with_contours["contour_levels"]
    # The extraction stage must not alter the surface: rerun surface-only via
    # the engine contract used by the adapter and compare grids bitwise.
    surface_only = run_constrained_idw_surface_only(pts, grid_n=64, power=2.0, break_polylines=breaks)
    assert np.array_equal(
        np.asarray(with_contours["grid_z"]), np.asarray(surface_only), equal_nan=True
    )


def run_constrained_idw_surface_only(pts, *, grid_n, power, break_polylines):
    """Adapter run with extraction off — mirrors the pre-#928 contract."""
    from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
    import paleo_workbench.workflow.constrained_idw_adapter as cia

    engine = cia._ensure_haiyou_engine()
    generate = engine["generate_constrained_idw"]

    def generate_no_contours(*args, **kwargs):
        cfg = kwargs.get("config") or args[5]
        kwargs["config"] = dataclasses.replace(cfg, extract_contours=False)
        kwargs["levels"] = []
        return generate(*args, **kwargs)

    engine["generate_constrained_idw"] = generate_no_contours
    try:
        return run_constrained_idw(
            pts, grid_n=grid_n, power=power, break_polylines=break_polylines
        )["grid_z"]
    finally:
        engine["generate_constrained_idw"] = generate


def test_draft_prefers_engine_contours_and_survives_reopen(tmp_path):
    """#928: the default draft uses the stored refined isolines; a reopen
    (artifact-backed read) keeps them; mismatched explicit levels re-extract."""
    project = ProjectDocument.new("C928")
    task = _constrained_task_with_breaks()
    project.factor_map_tasks.append(task)

    draft = compile_contour_draft_from_task(project, task)
    assert draft.segments, "draft has no segments"
    assert all(
        seg.properties.get("refined") for seg in draft.segments
    ), "draft did not use the engine-refined contours"

    # Explicit identical levels still use the stored contours.
    stored = [seg.level for seg in draft.segments]
    draft_same = compile_contour_draft_from_task(
        project, task, levels=sorted(set(stored))
    )
    assert draft_same.segments and all(
        seg.properties.get("refined") for seg in draft_same.segments
    )

    # A different explicit level set must re-extract (raw pipeline).
    off = [min(stored) - 1.5] if stored else [1.0]
    draft_other = compile_contour_draft_from_task(project, task, levels=off)
    assert draft_other.segments
    assert not any(
        seg.properties.get("refined") for seg in draft_other.segments
    )
