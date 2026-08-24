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

import time

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
from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw
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
    # The session grid differs from the committed v1 artifact, so persist must
    # actually rewrite this task (the old `or not changed` form asserted
    # nothing).
    assert task in changed
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


# --------------------------------------------------------------------- #921


def test_constrained_idw_r_squared_is_cross_validated_not_anchored():
    """#921: the shared r_squared key must not carry the ≈1 anchored fidelity.

    On a smooth plane sampled at 7 wells the old in-sample metric reported
    ≈0.9999 while honest held-out validation scores far lower (plain-IDW LOO
    on the same data was 0.31 in the audit). The two metrics must now differ
    and travel under distinct keys.
    """
    pts = [
        {"well": "w1", "x": 0.0, "y": 0.0, "value": 0.5},
        {"well": "w2", "x": 10.0, "y": 0.0, "value": 5.5},
        {"well": "w3", "x": 0.0, "y": 10.0, "value": 5.5},
        {"well": "w4", "x": 10.0, "y": 10.0, "value": 10.5},
        {"well": "w5", "x": 5.0, "y": 5.0, "value": 5.5},
        {"well": "w6", "x": 2.0, "y": 2.0, "value": 2.5},
        {"well": "w7", "x": 8.0, "y": 2.0, "value": 5.5},
    ]
    result = run_constrained_idw(pts, grid_n=50, power=2.0)
    assert result["r_squared_method"] == "spatial_4_fold"
    assert result["r_squared"] < 0.99, (
        "held-out R² must stay below the old fabricated in-sample value"
    )
    assert result["anchored_fidelity"] > 0.99
    assert result["r_squared"] != pytest.approx(result["anchored_fidelity"])


# --------------------------------------------------------------------- #925


def test_create_map_render_backend_degrades_on_broken_bridge(monkeypatch):
    """#925: a bridge that imports but fails initialize() must not crash the
    factory — the fallback engages with an actionable logged reason."""
    import importlib

    from paleo_workbench.mapping import map_render_backend as mrb

    class BrokenBridge:
        @staticmethod
        def initialize():
            raise RuntimeError("QGIS prefix broken")

    monkeypatch.setattr(mrb.QgisMapRenderBackend, "is_available", property(lambda self: True))
    # Replace the native module reference used inside initialize() so the
    # guarded probe hits the broken-bridge path.
    mrb_module = importlib.reload(mrb) if False else mrb
    monkeypatch.setattr(
        mrb_module.QgisMapRenderBackend,
        "initialize",
        lambda self: (_ for _ in ()).throw(RuntimeError("QGIS prefix broken")),
    )
    monkeypatch.setattr(mrb_module, "_QGIS_PROBE", {}, None)
    backend = mrb_module.create_map_render_backend(prefer_qgis=True)
    assert backend.backend_name != "qgis", "broken bridge must degrade to fallback"
    ok, reason = mrb_module.qgis_backend_probe()
    assert ok is False
    assert "初始化失败" in reason


def test_scalar_pipeline_probe_reports_gdal_gap(monkeypatch):
    """#925: availability covers what the scalar pipeline actually imports."""
    from paleo_workbench.mapping import qgis_style

    monkeypatch.setattr(qgis_style, "qgis_bridge_available", lambda: True)
    import builtins

    real_import = builtins.__import__

    def no_osgeo(name, *a, **k):
        if name.startswith("osgeo"):
            raise ImportError("No module named osgeo")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_osgeo)
    ok, reason = qgis_style.qgis_scalar_pipeline_ready()
    assert ok is False
    assert "GDAL" in reason


# ------------------------------------------------- #922 / #929 / #923 (QGIS)


def _qgis_env_ready() -> bool:
    try:
        import qgis_render_bridge  # noqa: F401

        from osgeo import gdal  # noqa: F401

        return True
    except Exception:
        return False


def _render_layer_pixels(backend, style, scale_range=None):
    """Render one legacy-styled line layer through the real QGIS backend."""
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    if not hasattr(_render_layer_pixels, "_rev"):
        _render_layer_pixels._rev = [0]
    _render_layer_pixels._rev[0] += 1
    rev = _render_layer_pixels._rev
    layer = MapLayerSnapshot(
        id=f"audit{rev[0]}",
        name="L",
        layer_type="vector",
        data_revision=1,
        style_revision=rev[0],
        visible=True,
        opacity=1.0,
        extent=(0.0, 0.0, 1000.0, 1000.0),
        crs="EPSG:3857",
        features=(
            {
                "id": "f1",
                "geometry": {"type": "LineString", "coordinates": [[100.0, 500.0], [900.0, 500.0]]},
                "properties": {},
            },
        ),
        style=style,
        scale_range=scale_range,
    )
    backend.set_layer_snapshot(MapRenderSnapshot(layers=[layer], project_crs="EPSG:3857"))
    backend.set_extent((0.0, 0.0, 1000.0, 1000.0))
    backend.set_output_size(800, 800)
    backend.set_dpi(96.0)
    frame = backend.render_sync()
    height = frame.height
    width = frame.width
    arr = np.frombuffer(bytes(frame.rgba), dtype=np.uint8)[: height * width * 4].reshape(
        height, width, 4
    )
    return arr


@pytest.mark.qgis
@pytest.mark.skipif(not _qgis_env_ready(), reason="requires built bridge + osgeo.gdal")
def test_legacy_px_sizes_dash_and_scale_range_on_qgis_path(qtbot):
    """#922/#929: legacy sizes stay pixels (96dpi), dash stays dashed, scale gates."""
    from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend

    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("bridge not built")
    backend.initialize()
    try:
        # stroke_width=4 px must render ~4 px thick (pre-fix: ~15 px as mm).
        arr = _render_layer_pixels(
            backend,
            {"fill": "transparent", "stroke": "#0000ff", "stroke_width": 4.0,
             "line_pattern": "solid"},
        )
        blue = (arr[..., 2] > 200) & (arr[..., 0] < 100) & (arr[..., 3] > 200)
        col = int(np.argmax(blue.any(axis=0)))
        thickness = int(blue[:, col].sum())
        assert 3 <= thickness <= 6, f"stroke 4px rendered {thickness}px"

        # dash must produce real gaps along the line (pre-fix: solid).
        arr = _render_layer_pixels(
            backend,
            {"fill": "transparent", "stroke": "#00ff00", "stroke_width": 4.0,
             "line_pattern": "dash"},
        )
        green = (arr[..., 1] > 150) & (arr[..., 3] > 200)
        colmask = green.any(axis=0)
        idx = np.where(colmask)[0]
        segment = colmask[idx[0]: idx[-1] + 1]
        gaps = np.split(np.where(~segment)[0], np.where(~segment)[0])
        gap_runs = [len(g) for g in gaps if len(g) > 0]
        assert gap_runs and max(gap_runs) >= 3, "dash pattern produced no gaps"

        # "fault" (the default fault-trace pattern) must dash too — it has no
        # QGIS built-in equivalent and previously fell through to solid.
        arr = _render_layer_pixels(
            backend,
            {"fill": "transparent", "stroke": "#00a0a0", "stroke_width": 4.0,
             "line_pattern": "fault"},
        )
        cyan = (arr[..., 1] > 120) & (arr[..., 2] > 120) & (arr[..., 3] > 200)
        colmask = cyan.any(axis=0)
        idx = np.where(colmask)[0]
        assert idx.size > 0, "fault pattern produced no line at all"
        segment = colmask[idx[0]: idx[-1] + 1]
        gaps = np.split(np.where(~segment)[0], np.where(~segment)[0])
        gap_runs = [len(g) for g in gaps if len(g) > 0]
        assert gap_runs and max(gap_runs) >= 3, "fault pattern rendered solid"

        # scale_range max 1:500 must hide the layer at 1:1000 (pre-fix: drawn).
        arr = _render_layer_pixels(
            backend,
            {"fill": "transparent", "stroke": "#ff0000", "stroke_width": 4.0,
             "line_pattern": "solid"},
            scale_range=(1.0, 500.0),
        )
        red = (arr[..., 0] > 200) & (arr[..., 3] > 200)
        assert int(red.sum()) == 0, "scale-gated layer rendered"
    finally:
        backend.shutdown()


@pytest.mark.qgis
@pytest.mark.skipif(not _qgis_env_ready(), reason="requires built bridge + osgeo.gdal")
def test_failed_snapshot_does_not_leak_style_into_reused_mirror(qtbot):
    """#929 (#519 residual): a rejected snapshot leaves mirror styles intact."""
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot,
        MapRenderSnapshot,
        QgisMapRenderBackend,
    )

    def layer(lid, srev, stroke, renderer_xml=None):
        style = {"fill": "transparent", "stroke": stroke, "stroke_width": 4.0,
                 "line_pattern": "solid"}
        if renderer_xml is not None:
            style["renderer_xml"] = renderer_xml
        return MapLayerSnapshot(
            id=lid, name=lid, layer_type="vector",
            data_revision=1, style_revision=srev, visible=True, opacity=1.0,
            extent=(0.0, 0.0, 1000.0, 1000.0), crs="EPSG:3857",
            features=({"id": "f", "geometry": {"type": "LineString",
                       "coordinates": [[100.0, 500.0], [900.0, 500.0]]}, "properties": {}},),
            style=style,
        )

    def push_and_count(snap, target_channel):
        backend.set_layer_snapshot(snap)
        backend.set_extent((0.0, 0.0, 1000.0, 1000.0))
        backend.set_output_size(800, 800)
        backend.set_dpi(96.0)
        frame = backend.render_sync()
        height, width = frame.height, frame.width
        arr = np.frombuffer(bytes(frame.rgba), dtype=np.uint8)[
            : height * width * 4
        ].reshape(height, width, 4)
        return int(target_channel(arr).sum())

    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip("bridge not built")
    backend.initialize()
    try:
        blue = lambda a: (a[..., 2] > 200) & (a[..., 0] < 100) & (a[..., 3] > 200)  # noqa: E731
        red = lambda a: (a[..., 0] > 200) & (a[..., 3] > 200)  # noqa: E731
        base = MapRenderSnapshot(layers=[layer("L", 1, "#0000ff")], project_crs="EPSG:3857")
        assert push_and_count(base, blue) > 500

        # Rejected update: L flips to red AND a second layer carries an invalid
        # renderer payload — the whole snapshot must throw BEFORE any style is
        # applied to L (pre-fix: L leaked red).
        bad = MapRenderSnapshot(
            layers=[
                layer("L", 2, "#ff0000"),
                layer("X", 1, "#00ff00", renderer_xml="</not-xml>"),
            ],
            project_crs="EPSG:3857",
        )
        with pytest.raises(RuntimeError):
            backend.set_layer_snapshot(bad)

        retry = MapRenderSnapshot(layers=[layer("L", 1, "#0000ff")], project_crs="EPSG:3857")
        assert push_and_count(retry, red) == 0, "leaked red style into reused mirror"
        assert push_and_count(retry, blue) > 500
    finally:
        backend.shutdown()


def test_layer_properties_payload_preserves_labels_on_qgis_path(qtbot, monkeypatch):
    """#929-3: Apply on the native symbology path must not wipe label config."""
    layer_model_core = pytest.importorskip("layer_model_core")

    from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog

    from paleo_workbench.mapping import qgis_style

    monkeypatch.setattr(qgis_style, "qgis_bridge_available", lambda: True)
    registry = layer_model_core.LayerRegistry()
    layer = registry.add_layer("facies", "Facies", layer_model_core.LayerType.Vector)
    dialog = MapLayerPropertiesDialog(
        layer,
        style={"fill": "#123456", "labels": {"field": "name", "visible": True}},
    )
    qtbot.addWidget(dialog)
    dialog._qgis_symbology = True  # force the native path even without a bridge
    dialog._pending_qgis_style = {"renderer_xml": "<renderer-v2/>", "revision": 3}
    dialog.apply()
    payload = dialog.payload()
    assert payload["labels"] == {"field": "name", "visible": True}


def test_export_spec_prefers_native_renderer_for_qgis_canvas():
    """#923: the export worker must know the live backend is the QGIS renderer."""
    from types import SimpleNamespace

    from paleo_workbench.ui.map_export_worker import snapshot_map_export

    canvas = SimpleNamespace(
        view_extent=(0.0, 0.0, 100.0, 100.0),
        _overlay_provider=None,
        backend=SimpleNamespace(backend_name="qgis", _snapshot=SimpleNamespace()),
    )
    spec = snapshot_map_export(canvas, "/tmp/x.png", width=100, height=100)
    assert spec.prefer_native_renderer is True
    canvas.backend.backend_name = "fallback"
    spec = snapshot_map_export(canvas, "/tmp/x.png", width=100, height=100)
    assert spec.prefer_native_renderer is False


def test_export_degrades_to_fallback_when_native_unavailable(tmp_path, monkeypatch):
    """#923: a failing QGIS render must still produce the PNG via fallback."""
    from paleo_workbench.ui import map_export_worker as mew
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    class ExplodingBackend:
        backend_name = "qgis"

        def initialize(self):
            raise RuntimeError("no QGIS here")

    monkeypatch.setattr(
        "paleo_workbench.mapping.map_render_backend.QgisMapRenderBackend",
        ExplodingBackend,
    )
    snap = MapRenderSnapshot(
        layers=[
            MapLayerSnapshot(
                id="v", name="v", layer_type="vector",
                data_revision=1, style_revision=1, visible=True, opacity=1.0,
                extent=(0.0, 0.0, 100.0, 100.0), crs="EPSG:3857",
                features=({"id": "f", "geometry": {"type": "LineString",
                           "coordinates": [[10.0, 50.0], [90.0, 50.0]]}, "properties": {}},),
                style={"fill": "transparent", "stroke": "#ff0000", "stroke_width": 2.0,
                       "line_pattern": "solid"},
            )
        ],
        project_crs="EPSG:3857",
    )
    out = tmp_path / "export.png"
    mew.render_and_save_map_export(
        mew.MapExportSpec(
            snapshot=snap, extent=(0.0, 0.0, 100.0, 100.0), width=100, height=100,
            dpi=96.0, decorations={}, path=str(out), prefer_native_renderer=True,
        )
    )
    assert out.exists() and out.stat().st_size > 0


# ------------------------------------------------------------- #927 / #934


def test_direction_defaults_use_haiyou_ratio_not_placeholder():
    """#927: unset semi axes must not collapse anisotropy to 2:1."""
    from paleo_workbench.workflow.constrained_idw_adapter import _build_directions
    from types import SimpleNamespace

    line = SimpleNamespace(
        id="d1", name="dir", role="direction", target_horizon="H1",
        coordinates=[(0.0, 0.0), (10.0, 10.0)],
        azimuth_deg=None, semi_major=None, semi_minor=None, active=True,
    )
    layer = SimpleNamespace(lines=[line], target_horizon="H1")
    dirs = _build_directions([layer], target_horizon="H1")
    assert len(dirs) == 1
    assert dirs[0].ratio >= 16.0  # haiyou default 18 with fb513c2 floor 16


def test_single_factor_plan_kernel_matches_multi_path():
    """#934: the single-factor fast path produces the multi-path numbers."""
    from paleo_workbench.workflow.interpolation_plan import (
        apply_idw_plan,
        apply_idw_plan_multi,
        build_idw_plan,
        extract_values_aligned,
    )

    rng = np.random.default_rng(11)
    n = 30
    xs = rng.uniform(0, 1000, n)
    ys = rng.uniform(0, 1000, n)
    vals = rng.uniform(10, 60, n)
    samples = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, vals)
    ]
    plan = build_idw_plan(samples, grid_n=96, power=2.0)
    values = extract_values_aligned(samples, plan)
    single = apply_idw_plan(plan, values)["grid_z"]
    multi = apply_idw_plan_multi(plan, np.stack([values, values], axis=0))[0]["grid_z"]
    assert np.array_equal(np.isnan(single), np.isnan(multi))
    finite = np.isfinite(single)
    assert np.allclose(single[finite], multi[finite], rtol=0, atol=1e-10)


def test_single_factor_plan_kernel_with_faults_keeps_nan_parity():
    """Fault-blocked cells must stay NaN on the single-factor fast path.

    The pre-fix fast path wrote ``(0 @ z) / 1.0 == 0.0`` into cells whose
    weight row the fault mask had fully zeroed, shifting plan min/max and
    contour levels with a bogus 0 surface; the multi path left NaN.
    """
    from paleo_workbench.workflow.interpolation_plan import (
        apply_idw_plan,
        apply_idw_plan_multi,
        build_idw_plan,
        extract_values_aligned,
    )

    rng = np.random.default_rng(7)
    n = 30
    xs = rng.uniform(0, 600, n)
    ys = rng.uniform(0, 1000, n)
    vals = rng.uniform(10, 60, n)
    samples = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, vals)
    ]
    # Vertical wall at x=610, just right of the sample bbox (max 600): the
    # 5% grid padding reaches ~630, so the last columns sit beyond the wall
    # with EVERY well on the far side — their weight rows are fully zeroed.
    fault = [(610.0, -100.0), (610.0, 1100.0)]
    plan = build_idw_plan(samples, grid_n=64, power=2.0, fault_polylines=[fault])
    values = extract_values_aligned(samples, plan)
    single = apply_idw_plan(plan, values)["grid_z"]
    multi = apply_idw_plan_multi(plan, np.stack([values, values], axis=0))[0][
        "grid_z"
    ]
    assert np.array_equal(np.isnan(single), np.isnan(multi))
    assert np.isnan(single).any(), "test setup must produce blocked cells"
    finite = np.isfinite(single)
    assert np.allclose(single[finite], multi[finite], rtol=0, atol=1e-10)
    # The regression signature: bogus 0.0 among the blocked cells.
    assert np.nanmin(single) > 1.0


# --------------------------------------------------------------------- #926


def test_plan_fault_mask_grid_aligned_fault_matches_single_task():
    """#926: a grid-aligned vertical fault must not blank a whole column.

    The plan's old cells_on/wells_on whole-row/column blocking severed every
    node sitting on the fault line from every well (23/23 NaN column) while
    the single-task geoviz kernel rendered 0 NaN (#118 semantics).
    """
    from paleo_workbench.project.factor_grid_artifacts import (
        factor_grid_result_for_task,
    )
    from paleo_workbench.workflow.factor_interpolation import (
        apply_interpolation_to_task,
    )
    from paleo_workbench.workflow.interpolation_plan import (
        apply_idw_plan,
        build_idw_plan,
        extract_values_aligned,
    )

    rng = np.random.default_rng(5)
    xs = rng.uniform(0, 100, 24)
    ys = rng.uniform(0, 100, 24)
    vals = rng.uniform(10, 60, 24)
    samples = [
        {"x": float(x), "y": float(y), "value": float(v)}
        for x, y, v in zip(xs, ys, vals)
    ]
    fault = [[(50.0, -5.0), (50.0, 105.0)]]

    plan = build_idw_plan(samples, grid_n=40, power=2.0, fault_polylines=fault)
    plan_grid = apply_idw_plan(plan, extract_values_aligned(samples, plan))["grid_z"]
    assert int(np.isnan(plan_grid).sum()) == 0

    task = FactorMapTask(
        name="t", target_horizon="H1", factor_type="t", method="IDW",
        parameters={"sample_points": samples}, status="pending",
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=40, fault_polylines=fault)
    single_grid = factor_grid_result_for_task(task).grid_z
    assert int(np.isnan(single_grid).sum()) == 0
    # Same inputs, same production semantics: both paths agree on nodata.
    assert np.array_equal(np.isnan(plan_grid), np.isnan(single_grid))


# ------------------------------------------------------------- #928 / #930


def test_user_boundary_ring_constrains_constrained_idw_domain():
    """#928: an explicit boundary ring wins over the synthesized sample hull."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.constrained_idw_adapter import run_constrained_idw

    rng = np.random.default_rng(9)
    xs = rng.uniform(0, 100, 20)
    ys = rng.uniform(0, 100, 20)
    vs = rng.uniform(10, 60, 20)
    pts = [
        {"well": f"w{i}", "x": float(x), "y": float(y), "value": float(v)}
        for i, (x, y, v) in enumerate(zip(xs, ys, vs))
    ]
    ring = [(25.0, 25.0), (75.0, 25.0), (75.0, 75.0), (25.0, 75.0), (25.0, 25.0)]
    line = SimpleNamespace(
        id="b1", name="user-boundary", role="boundary", target_horizon="H1",
        coordinates=ring, azimuth_deg=None, semi_major=None, semi_minor=None,
        active=True,
    )
    layer = SimpleNamespace(lines=[line], target_horizon="H1")
    result = run_constrained_idw(
        pts, grid_n=60, power=2.0, layers=[layer], target_horizon="H1"
    )
    gx, gy = result["grid_x"], result["grid_y"]
    finite = np.isfinite(result["grid_z"])
    outside = 0
    for j, y in enumerate(gy):
        for i, x in enumerate(gx):
            if finite[j, i] and not (25.0 - 1e-6 <= x <= 75.0 + 1e-6 and 25.0 - 1e-6 <= y <= 75.0 + 1e-6):
                outside += 1
    assert outside == 0, f"{outside} finite cells outside the user boundary ring"
    assert int(finite.sum()) > 0
    # The reported boundary must be the ring actually used, not the
    # synthesized sample hull (extent displays read this key).
    reported = result["boundary"]
    rx = [p[0] for p in reported]
    ry = [p[1] for p in reported]
    assert max(rx) <= 75.0 + 1e-6 and min(rx) >= 25.0 - 1e-6
    assert max(ry) <= 75.0 + 1e-6 and min(ry) >= 25.0 - 1e-6


def test_contour_levels_are_nice_steps():
    """#928: default draft levels snap to 1/2/2.5/5x10^k multiples."""
    from paleo_workbench.workflow.contour_draft import suggest_nice_levels

    grid = np.array([[3.7, 11.2], [17.9, 28.4]])
    levels = suggest_nice_levels(grid, n_levels=8)
    assert levels == [5.0, 10.0, 15.0, 20.0, 25.0]


def test_register_produced_keeps_lock_free_during_payload_copy(tmp_path):
    """#930: concurrent catalog calls must not block for the copy window."""
    import threading

    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.service import DataCatalogService

    project_dir = tmp_path / "p"
    project_dir.mkdir()
    svc = DataCatalogService.open(project_dir)
    run = svc.register_run("r", input_version_ids=(), parameters={})
    adapter = CoreCatalogAdapter(svc)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x" * (48 * 1024 * 1024))

    latencies = []
    stop = threading.Event()

    def probe() -> None:
        while not stop.is_set():
            t0 = time.perf_counter()
            svc.list_assets()
            latencies.append(time.perf_counter() - t0)

    thread = threading.Thread(target=probe)
    thread.start()
    try:
        adapter.register_intermediate(
            run_id=run.id,
            name="big",
            path=str(payload),
        )
    finally:
        stop.set()
        thread.join()
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    # Pre-fix the whole copy+SHA window held the lock (audit: 84.8 ms @120MiB).
    # Allow generous headroom for CI noise; the copy itself takes ~100+ ms.
    assert p95 < 0.050, f"concurrent catalog call p95 {p95*1000:.1f} ms — lock held during copy"
