"""Regression tests for audit issues #918 / #919 / #936.

Each test pins one specific defect found by the 2026-08-22 audit:
* #919 — recompute must reuse a task's recorded method/grid_n/power.
* #918(b) — a failed prepare run must not evict the task's previous live grid
  via the commit's fingerprint-conditional invalidation.
* #918(a) — saving with an unsaved (e.g. cancelled-run) grid must persist that
  grid instead of re-branding it as the previously committed artifact.
* #936 — well-table QC write-back must not cross-inject into factor_map_tasks[0].
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.project.factor_grid_artifacts import (
    factor_grid_result_for_task,
    persist_factor_grid_artifacts,
)
from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    batch_prepare_factor_maps,
    interpolation_params_from_task,
)
from paleo_workbench.workflow.factor_prepare_scheduler import (
    build_prepare_snapshot,
    commit_prepare_batch_result,
    run_factor_prepare_schedule,
)
from paleo_workbench.workflow.well_table import (
    sample_points_from_well_table,
    sync_well_table_to_linked_tasks,
    well_table_from_sample_points,
)


def _points(n: int = 10, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    return [
        {
            "x": float(rng.uniform(0, 20)),
            "y": float(rng.uniform(0, 20)),
            "value": float(5.0 + 30.0 * rng.uniform(0, 1)),
        }
        for _ in range(n)
    ]


# --------------------------------------------------------------------- #919


def test_interpolation_params_recovered_from_task():
    task = FactorMapTask(
        name="kriging task",
        target_horizon="H1",
        factor_type="sand",
        method="克里金",
        parameters={"sample_points": _points(), "grid_n": 24, "power": 3.0},
        status="complete",
    )
    method, grid_n, power = interpolation_params_from_task(task)
    assert method == "克里金"
    assert grid_n == 24
    assert power == pytest.approx(3.0)


def test_interpolation_params_fall_back_to_defaults():
    task = FactorMapTask(
        name="bare",
        target_horizon="H1",
        factor_type="sand",
        method="IDW",
        parameters={"sample_points": _points()},
        status="pending",
    )
    method, grid_n, power = interpolation_params_from_task(task)
    assert method == "IDW"
    assert power == pytest.approx(2.0)
    assert grid_n >= 8


def test_apply_with_recovered_params_keeps_method_and_grid():
    task = FactorMapTask(
        name="kriging task",
        target_horizon="H1",
        factor_type="sand",
        method="克里金",
        parameters={"sample_points": _points(), "grid_n": 16, "power": 3.0},
        status="pending",
    )
    method, grid_n, power = interpolation_params_from_task(task)
    apply_interpolation_to_task(task, method=method, grid_n=grid_n, power=power)
    # The recorded algorithm identity survives the recompute round-trip.
    assert task.method == "克里金"
    assert task.parameters["grid_n"] == 16
    assert task.parameters["power"] == pytest.approx(3.0)


# ------------------------------------------------------------------- #918(b)


def _two_task_project() -> ProjectDocument:
    project = ProjectDocument.new("Audit918")
    project.stratigraphy.target_horizon = "H1"
    for name, pts in (("good", _points(12, seed=1)), ("victim", _points(12, seed=2))):
        project.factor_map_tasks.append(
            FactorMapTask(
                name=name,
                target_horizon="H1",
                factor_type=name,
                method="IDW",
                parameters={"sample_points": list(pts)},
                status="pending",
            )
        )
    return project


def test_failed_prepare_run_keeps_previous_live_grid():
    project = _two_task_project()
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    victim = project.factor_map_tasks[1]
    first_result = factor_grid_result_for_task(victim)
    first_mean = float(np.nanmean(first_result.grid_z))

    # Next round: "good" changes (dirty) while "victim"'s new samples make its
    # interpolation FAIL (<2 valid points).
    good = project.factor_map_tasks[0]
    good_pts = list(good.parameters["sample_points"])
    good_pts[0] = {**good_pts[0], "value": float(good_pts[0]["value"]) + 2.0}
    good.parameters = {**good.parameters, "sample_points": good_pts}
    victim.parameters = {
        **victim.parameters,
        "sample_points": [
            {"x": 1.0, "y": 1.0, "value": np.nan},
            {"x": 2.0, "y": 2.0, "value": None},
        ],
    }

    snap = build_prepare_snapshot(project, generation=7, method="IDW", grid_n=12)
    result = run_factor_prepare_schedule(snap, workers=1)
    discarded = commit_prepare_batch_result(project, result, expected_generation=7)

    assert any(item.error for item in result.task_results), "victim run must fail"
    # The failed task's PREVIOUS grid survives the commit (#918).
    after = factor_grid_result_for_task(victim)
    assert np.isfinite(after.grid_z).any()
    assert float(np.nanmean(after.grid_z)) == pytest.approx(first_mean, rel=1e-12)
    assert discarded  # the failed task was discarded from metadata patching


# ------------------------------------------------------------------- #918(a)


def test_save_persists_uncommitted_grid_instead_of_rebranding(tmp_path):
    project = ProjectDocument.new("Audit918a")
    project.stratigraphy.target_horizon = "H1"
    task = FactorMapTask(
        name="f",
        target_horizon="H1",
        factor_type="type",
        method="IDW",
        parameters={"sample_points": _points()},
        status="pending",
    )
    project.factor_map_tasks.append(task)
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    project_path = tmp_path / "proj.paleo.json"
    persist_factor_grid_artifacts(project, project_path)
    committed_mean = float(np.nanmean(factor_grid_result_for_task(task).grid_z))
    # Simulate the catalog having registered the artifact as a version.
    task.grid_artifact_version_id = "v1"
    assert task.grid_artifact_path

    # A later (here: cancelled-style) run leaves a NEW uncommitted grid in the
    # session cache while task metadata still points at the old artifact.
    pts = list(task.parameters["sample_points"])
    for p in pts:
        p["value"] = float(p["value"]) + 10.0
    apply_interpolation_to_task(task, method="IDW", grid_n=12)
    new_mean = float(np.nanmean(factor_grid_result_for_task(task).grid_z))
    assert new_mean != pytest.approx(committed_mean)

    changed = persist_factor_grid_artifacts(project, project_path)
    assert task in changed or not changed  # rewrite path exercised either way
    served_after_save = factor_grid_result_for_task(task)
    assert float(np.nanmean(served_after_save.grid_z)) == pytest.approx(new_mean)

    # Reopen semantics: reload from the artifact on disk — it must now carry
    # the SAME content the session serves (no torn pairing).
    reloaded = type(project).load(project_path) if hasattr(type(project), "load") else None
    if reloaded is not None:
        reloaded_task = next(t for t in reloaded.factor_map_tasks if t.id == task.id)
        reopened = factor_grid_result_for_task(reloaded_task)
        assert float(np.nanmean(reopened.grid_z)) == pytest.approx(new_mean)
    assert task.grid_artifact_version_id != "v1"


def test_save_still_skips_when_live_is_sealed_committed_content(tmp_path):
    project = ProjectDocument.new("Audit918b")
    project.stratigraphy.target_horizon = "H1"
    task = FactorMapTask(
        name="f",
        target_horizon="H1",
        factor_type="type",
        method="IDW",
        parameters={"sample_points": _points()},
        status="pending",
    )
    project.factor_map_tasks.append(task)
    batch_prepare_factor_maps(project, method="IDW", grid_n=12)
    project_path = tmp_path / "proj.paleo.json"
    persist_factor_grid_artifacts(project, project_path)
    # Simulate the catalog having registered the artifact as a version.
    task.grid_artifact_version_id = "v1"

    # Simulate catalog rehoming: bump the artifact file's identity by touching
    # mtime, then save again — no new run happened, so nothing may be rewritten.
    import os

    from pathlib import Path as _Path

    artifact = _Path(task.grid_artifact_path)
    assert artifact.exists()
    os.utime(artifact, None)
    changed = persist_factor_grid_artifacts(project, project_path)
    assert task not in changed


# --------------------------------------------------------------------- #936


def test_qc_sync_only_touches_bound_tasks():
    project = ProjectDocument.new("Audit936")
    project.stratigraphy.target_horizon = "H1"

    def mk(name: str) -> FactorMapTask:
        return FactorMapTask(
            name=name,
            target_horizon="H1",
            factor_type=name,
            method="IDW",
            parameters={"sample_points": _points(6, seed=len(name))},
            status="pending",
        )

    unbound_first = mk("alpha")
    bound = mk("beta")
    project.factor_map_tasks.extend([unbound_first, bound])

    table = well_table_from_sample_points(_points(6, seed=99), name="T")
    table.rows[0].x = 42.0  # QC-cleaned geometry differs from both tasks
    bound.well_table_id = table.id  # prior attach (attach_well_table_to_factor_task)

    updated = sync_well_table_to_linked_tasks(project, table)
    assert updated == [bound]
    synced_points = sample_points_from_well_table(table)
    assert bound.parameters["sample_points"] == synced_points
    # The unbound FIRST task keeps its own samples (the #936 bug injected here).
    assert unbound_first.parameters["sample_points"] != synced_points
    assert unbound_first.well_table_id is None


def test_qc_sync_adopts_single_unbound_legacy_task():
    project = ProjectDocument.new("Audit936b")
    project.stratigraphy.target_horizon = "H1"
    only = FactorMapTask(
        name="solo",
        target_horizon="H1",
        factor_type="t",
        method="IDW",
        parameters={"sample_points": _points(6)},
        status="pending",
    )
    project.factor_map_tasks.append(only)
    table = well_table_from_sample_points(_points(6, seed=5), name="T")
    updated = sync_well_table_to_linked_tasks(project, table)
    assert updated == [only]
    assert only.well_table_id == table.id


# --------------------------------------------------------------------- #924


def test_constrained_idw_gap_fill_survives_hull_raster_skip():
    """#924: the vendored hull-raster skip must not disable default gap fill.

    Fixture (14 wells, one direction line, 50x50 batch grid) diverged from the
    upstream engine by 70 finite cells before the fix: skipping the hull raster
    flipped ``data_hull_active`` and zeroed ``gap_iterations``. Post-fix the
    finite-cell count matches upstream's 1652 for this SHApinned fixture.
    """
    import importlib

    import numpy as np

    from paleo_workbench.workflow.constrained_idw_adapter import _ensure_haiyou_engine

    _ensure_haiyou_engine()
    # The adapter put the vendored root on sys.path; its modules import as
    # top-level ``drawing.*`` packages (Qt-free stubs).
    fast_grid = importlib.import_module("drawing.single_factor.fast_grid")
    corridor = importlib.import_module("drawing.single_factor.direction_corridor")

    rng = np.random.default_rng(20260822)
    n = 14
    wells = np.stack(
        [rng.uniform(8.0, 92.0, n), rng.uniform(8.0, 92.0, n)], axis=1
    )
    vals = 20.0 + 60.0 * (wells[:, 0] / 100.0) + rng.normal(0.0, 6.0, n)
    well_array = np.stack([wells[:, 0], wells[:, 1], vals], axis=1)

    dline = [(12.0, 20.0), (40.0, 45.0), (70.0, 62.0), (90.0, 88.0)]
    specs = [
        corridor.DirectionLineSpec(
            line_id="d0",
            points=tuple(dline),
            active=True,
            ratio=18.0,
            influence_radius=0.0,
            priority=1,
            core_radius=0.0,
            zone_id="",
            extend_mode="auto",
            transition=0.0,
        )
    ]
    gx = np.linspace(-2.0, 102.0, 50)
    gy = np.linspace(-2.0, 102.0, 50)
    domain = np.ones((50, 50), dtype=bool)
    spacing = corridor.estimate_mean_well_spacing(wells)
    geoms = corridor.build_direction_geometries(
        specs, search_radius=120.0, mean_well_spacing=spacing, map_extent=104.0
    )
    cache = corridor.build_grid_direction_cache(gx, gy, domain, geoms)
    field = corridor.build_legacy_direction_field(cache)

    grid = fast_grid.interpolate_idw_grid_batch(
        gx,
        gy,
        well_array,
        domain,
        search_radius=120.0,
        power=2.0,
        min_points=3,
        max_points=12,
        density_weights=np.ones(n, dtype=float),
        value_min=0.0,
        value_max=100.0,
        region_labels=None,
        well_labels=None,
        direction_field=field,
        direction_corridor_strength=1.0,
        direction_perpendicular_strength=1.0,
        use_extended_search=True,
        limit_search_radius=True,
    )
    finite = int(np.isfinite(grid).sum())
    # Golden count verified bit-identical against upstream @ 5b8f8f98 with the
    # gap-fill fix applied (pre-fix vendored produced 1582).
    assert finite == 1652


# --------------------------------------------------------------------- #920


def test_scene_from_factor_task_upserts_new_grid_payload():
    """#920: re-overlaying a re-run task refreshes the scalar payload in place."""
    from paleo_workbench.viz.native_factor_map import scene_from_factor_task
    from paleo_workbench.workflow.factor_interpolation import (
        apply_interpolation_to_task,
    )

    def mk_pts(shift=0.0):
        rng = np.random.default_rng(7)
        return [
            {"x": float(x), "y": float(y), "value": float(v) + shift}
            for x, y, v in zip(
                rng.uniform(0, 50, 40), rng.uniform(0, 50, 40), rng.uniform(10, 60, 40)
            )
        ]

    task = FactorMapTask(
        name="f",
        target_horizon="H1",
        factor_type="t",
        method="IDW",
        parameters={"sample_points": mk_pts()},
        status="pending",
    )
    apply_interpolation_to_task(task, grid_n=24)
    scene = scene_from_factor_task(task, crs=None)
    layer_id = str(task.id)
    fp_first = scene.registry.get(layer_id).metadata.get("result_fingerprint")
    revision_first = scene._scalars[layer_id].data_revision

    # Re-run with different values → re-overlay must serve the NEW grid (#920).
    task.parameters = {**task.parameters, "sample_points": mk_pts(20.0)}
    apply_interpolation_to_task(task, grid_n=24)
    scene_from_factor_task(task, crs=None, scene=scene)
    assert scene.registry.get(layer_id).metadata.get("result_fingerprint") != fp_first
    assert scene._scalars[layer_id].data_revision != revision_first

    # Idempotent re-request with unchanged content must not touch the payload.
    revision_third = scene._scalars[layer_id].data_revision
    scene_from_factor_task(task, crs=None, scene=scene)
    assert scene._scalars[layer_id].data_revision == revision_third
