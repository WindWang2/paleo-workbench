"""Generic LayerRegistry-backed map composition contracts."""

from __future__ import annotations

import layer_model_core

from paleo_workbench.viz.native_factor_map import MapScene, NativeMapScene


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
