"""Generic LayerRegistry-backed map composition contracts."""

from __future__ import annotations

import layer_model_core
import numpy as np

from paleo_workbench.viz.native_factor_map import MapScene, NativeMapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def test_map_scene_is_the_generic_registry_backed_composition_surface() -> None:
    scene = MapScene()
    scene.add_vector_layer(
        "facies",
        [
            {
                "id": "f1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 0]]],
                },
                "properties": {"facies": "delta"},
            }
        ],
        name="Facies",
        extent=(0.0, 0.0, 4.0, 4.0),
        crs="EPSG:3857",
    )
    scene.add_contours(
        "contours",
        [[(0, 2), (4, 2)]],
        extent=(0.0, 0.0, 4.0, 4.0),
        crs="EPSG:3857",
    )
    scene.add_sample_points(
        "samples",
        [(1, 1), (3, 3)],
        extent=(0.0, 0.0, 4.0, 4.0),
        crs="EPSG:3857",
    )

    snapshot = scene.render_snapshot(project_crs="EPSG:3857")

    assert NativeMapScene is MapScene
    assert [layer.id for layer in scene.registry.layers()] == ["facies", "contours", "samples"]
    assert scene.registry.get("facies").type == layer_model_core.LayerType.Vector
    assert [layer.id for layer in snapshot.layers] == ["facies", "contours", "samples"]
    assert snapshot.layers[0].features[0]["geometry"]["type"] == "Polygon"
    assert snapshot.layers[1].features[0]["geometry"]["type"] == "LineString"
    assert snapshot.layers[2].features[0]["geometry"]["type"] == "Point"


def test_map_scene_keeps_vector_data_and_style_revisions_independent() -> None:
    scene = MapScene()
    layer = scene.add_vector_layer(
        "facies",
        [{"id": "f1", "geometry": {"type": "Point", "coordinates": [0, 0]}}],
        name="Facies",
        extent=(0.0, 0.0, 1.0, 1.0),
    )
    before_data, before_style = layer.data_revision, layer.style_revision

    assert scene.set_vector_style("facies", {"fill": "#55b6ff"})
    assert layer.data_revision == before_data
    assert layer.style_revision > before_style
    assert scene.set_vector_features(
        "facies",
        [{"id": "f1", "geometry": {"type": "Point", "coordinates": [1, 1]}}],
        extent=(0.0, 0.0, 1.0, 1.0),
    )
    assert layer.data_revision > before_data


def test_map_scene_snapshot_references_the_existing_native_scalar_payload() -> None:
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [0.0, 1.0],
            "grid_y": [0.0, 1.0],
            "grid_z": np.array([[0.0, 1.0], [0.5, 0.25]], dtype=np.float32),
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="porosity")

    snapshot = scene.render_snapshot(project_crs="EPSG:3857")

    assert snapshot.layers[0].layer_type == "scalar_grid"
    assert snapshot.layers[0].renderer_payload is scene.scalar_layer("porosity")


def test_map_scene_can_describe_an_immutable_external_raster_without_copying_samples() -> None:
    scene = MapScene()
    layer = scene.add_raster_source(
        "reference-raster",
        "/tmp/reference.tif",
        name="Reference raster",
        extent=(1.0, 2.0, 3.0, 4.0),
        crs="EPSG:3857",
        source_ref="reference:ref-1",
        source_revision="revision-1",
    )
    before = layer.data_revision

    snapshot = scene.render_snapshot(project_crs="EPSG:3857")

    assert layer.type == layer_model_core.LayerType.Raster
    assert snapshot.layers[0].layer_type == "raster_source"
    assert snapshot.layers[0].renderer_payload == "/tmp/reference.tif"
    assert scene.set_raster_source("reference-raster", "/tmp/reference.tif", source_revision="revision-2")
    assert layer.data_revision > before
