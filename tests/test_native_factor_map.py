"""FactorGridResult/artifact/native scalar-layer vertical contract."""

from __future__ import annotations

import numpy as np

from paleo_workbench.catalog.grid_artifact import write_grid_artifact
from paleo_workbench.project.models import ContourDraft, ContourSegment, FactorMapTask
from paleo_workbench.viz.native_factor_map import NativeMapScene, scene_from_factor_task
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def _result() -> FactorGridResult:
    return FactorGridResult.from_engine_dict(
        {
            "grid_x": [10.0, 20.0],
            "grid_y": [30.0, 40.0],
            "grid_z": [[0.0, 0.5], [1.0, None]],
            "backend": "idw",
            "n_points": 4,
            "r_squared": 0.9,
        },
        factor_name="孔隙度",
        crs="EPSG:3857",
        run_ref="run-1",
    )


def test_managed_artifact_transfers_to_native_scalar_layer_without_interpolation(tmp_path):
    result = _result()
    artifact = write_grid_artifact(result, tmp_path, "porosity")
    scene = NativeMapScene()
    layer = scene.add_factor_grid_artifact(artifact, layer_id="porosity")

    assert layer.extent == result.extent
    assert layer.crs == "EPSG:3857"
    assert layer.source_ref == str(artifact)
    image = scene.raster_rgba("porosity")
    assert image.shape == (2, 2, 4)
    assert image[1, 1, 3] == 0


def test_style_visibility_opacity_and_view_operations_do_not_recompute_interpolation():
    calls = 0

    def interpolate_once() -> FactorGridResult:
        nonlocal calls
        calls += 1
        return _result()

    scene = NativeMapScene()
    scene.add_factor_grid(interpolate_once(), layer_id="porosity")
    scalar = scene.scalar_layer("porosity")
    assert calls == 1
    scene.raster_rgba("porosity")
    assert scalar.rasterize_count == 1

    assert scene.set_scalar_style("porosity", gamma=2.0)
    scene.raster_rgba("porosity")
    assert scalar.rasterize_count == 2
    assert scene.set_layer_opacity("porosity", 0.4)
    scene.raster_rgba("porosity")
    assert scalar.rasterize_count == 2  # opacity is Qt composition state
    scene.registry.get("porosity").visible = False
    scene.registry.move_layer("porosity", 0)
    assert calls == 1


def test_scene_composes_contours_and_sample_points_in_registry_order():
    scene = NativeMapScene()
    result = _result()
    scene.add_factor_grid(result, layer_id="surface")
    scene.add_contours(
        "contours",
        [[(10.0, 35.0), (20.0, 35.0)]],
        extent=result.extent,
        crs="EPSG:3857",
    )
    scene.add_sample_points(
        "samples", [(10.0, 30.0), (20.0, 40.0)], extent=result.extent, crs="EPSG:3857"
    )
    assert [layer.id for layer in scene.registry.layers()] == [
        "surface",
        "contours",
        "samples",
    ]
    assert scene.contour_geometry("contours").paths[0][0] == (10.0, 35.0)
    assert scene.point_geometry("samples").points[-1] == (20.0, 40.0)


def test_legacy_completed_task_adapts_to_native_scene_without_interpolation():
    result = _result()
    task = FactorMapTask(
        id="task-porosity",
        name="孔隙度",
        target_horizon="H1",
        factor_type="孔隙度",
        method="IDW",
        status="complete",
        parameters={
            **result.to_legacy_dict(),
            "sample_points": [{"x": 10.0, "y": 30.0, "value": 0.0}],
        },
    )
    draft = ContourDraft(
        id="draft-porosity",
        name="孔隙度等值线",
        linked_factor_task_id=task.id,
        segments=[
            ContourSegment(level=0.5, coordinates=[[10.0, 35.0], [20.0, 35.0]])
        ],
    )
    scene = scene_from_factor_task(task, crs="EPSG:3857", contour_drafts=[draft])
    assert scene.registry.get(task.id).extent == result.extent
    assert scene.scalar_layer(task.id) is not None
    assert scene.point_geometry(f"{task.id}:samples").points == ((10.0, 30.0),)
    assert [layer.id for layer in scene.registry.children_of(f"{task.id}:group")] == [
        task.id,
        f"{task.id}:samples",
        draft.id,
    ]
    assert scene.contour_geometry(draft.id).paths == (((10.0, 35.0), (20.0, 35.0)),)


def test_idw_task_to_native_canvas_style_changes_never_rerun_interpolation(monkeypatch, qtbot):
    import paleo_workbench.workflow.factor_interpolation as interpolation
    from paleo_workbench.ui.native_map_canvas import NativeMapCanvas

    calls = 0
    original = interpolation.interpolate_factor_grid

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(interpolation, "interpolate_factor_grid", counted)
    task = FactorMapTask(
        id="real-idw",
        name="H1 孔隙度",
        target_horizon="H1",
        factor_type="孔隙度",
        method="IDW",
        status="pending",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 0.0},
                {"x": 1.0, "y": 0.0, "value": 0.3},
                {"x": 0.0, "y": 1.0, "value": 0.7},
                {"x": 1.0, "y": 1.0, "value": 1.0},
            ]
        },
        source_kind="real",
    )

    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    assert calls == 1
    scene = scene_from_factor_task(task)
    canvas = NativeMapCanvas(scene)
    qtbot.addWidget(canvas)
    canvas.resize(240, 180)
    canvas.show()
    canvas.grab()

    scene.set_scalar_style(task.id, gamma=1.5)
    scene.set_layer_opacity(task.id, 0.5)
    scene.registry.get(task.id).visible = False
    scene.registry.get(task.id).visible = True
    scene.registry.move_layer(task.id, 1)
    canvas.zoom_by(0.8)
    canvas.pan_by_pixels(8, 5)
    canvas.grab()
    assert calls == 1
