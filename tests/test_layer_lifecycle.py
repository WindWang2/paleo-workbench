"""Layer lifecycle and revision contracts across the composition seam."""

from __future__ import annotations

from paleo_workbench.mapping.map_scene_adapter import LegacyDocumentSceneAdapter


def _document(document_id: str = "map"):
    from paleo_workbench.project.models import PaleoMapDocument

    return PaleoMapDocument(id=document_id, name="Test Map", linked_target_horizon="H1")


def _records(count: int = 3) -> list[dict]:
    return [
        {
            "id": f"well-{index}",
            "kind": "well",
            "name": f"W{index}",
            "coordinates": [float(index), float(index)],
            "properties": {},
        }
        for index in range(count)
    ]


def test_full_layer_lifecycle_create_style_visibility_remove() -> None:
    layer_model_core = pytest.importorskip("layer_model_core")

    adapter = LegacyDocumentSceneAdapter()
    document = _document()

    # create/load
    snapshot = adapter.sync(document, project_crs="EPSG:3857", records=_records(3))
    scene = adapter.scene
    layer = scene.registry.get("map:well")
    assert layer is not None
    assert layer.type == layer_model_core.LayerType.Vector
    assert len(scene.vector_features("map:well")) == 3
    data_revision_after_load = layer.data_revision

    # style change bumps only the style revision
    assert scene.set_vector_style("map:well", {"fill": "#00ff00", "marker": "circle"})
    assert layer.data_revision == data_revision_after_load
    assert layer.style_revision > 1

    # visibility toggles are cheap attribute changes, not data changes
    layer.visible = False
    assert not layer.visible

    # remove
    assert scene.remove_layer("map:well")
    assert scene.registry.get("map:well") is None
    assert adapter.sync(document, project_crs="EPSG:3857", records=_records(0)).layers

    # z-order is registry order and is exported into the snapshot
    scene.add_vector_layer(
        "extra", (), name="Extra", extent=(0.0, 0.0, 1.0, 1.0), crs=""
    )
    scene.registry.move_layer("extra", 0)
    snapshot = scene.render_snapshot()
    assert snapshot.layers[0].id == "extra"


def test_adapter_reuses_features_when_revision_unchanged() -> None:
    adapter = LegacyDocumentSceneAdapter()
    document = _document()

    first = adapter.sync(document, project_crs="", records=_records(3), data_revisions={"well": 1})
    layer = adapter.scene.registry.get("map:well")
    revision_after_first = layer.data_revision
    features_after_first = adapter.scene.vector_features("map:well")

    second = adapter.sync(document, project_crs="", records=_records(3), data_revisions={"well": 1})
    # Same revision: no bump, identical feature payload object reused.
    assert adapter.scene.registry.get("map:well").data_revision == revision_after_first
    assert adapter.scene.vector_features("map:well") is features_after_first

    third = adapter.sync(document, project_crs="", records=_records(4), data_revisions={"well": 2})
    assert adapter.scene.registry.get("map:well").data_revision > revision_after_first
    assert len(adapter.scene.vector_features("map:well")) == 4
    assert first and second and third


def test_snapshot_carries_catalog_provenance_metadata_and_scale_range() -> None:
    layer_model_core = pytest.importorskip("layer_model_core")

    from paleo_workbench.viz.native_factor_map import MapScene

    scene = MapScene()
    layer = scene.add_vector_layer(
        "provenance", (), name="Provenanced", extent=(0.0, 0.0, 1.0, 1.0), crs=""
    )
    layer.set_provenance_ref("dv-abc-42")
    layer.set_metadata("algorithm_id", "idw_v2")
    layer.scale_range = layer_model_core.ScaleRange(10.0, 10000.0)

    snapshot_layer = scene.render_snapshot().layers[0]

    assert snapshot_layer.source_version_id == "dv-abc-42"
    assert snapshot_layer.metadata["algorithm_id"] == "idw_v2"
    assert snapshot_layer.scale_range == (10.0, 10000.0)


def test_default_scale_range_is_none_and_scale_hidden_layer_renders_nowhere() -> None:
    from paleo_workbench.viz.native_factor_map import MapScene

    scene = MapScene()
    scene.add_vector_layer(
        "plain", (), name="Plain", extent=(0.0, 0.0, 1.0, 1.0), crs=""
    )
    assert scene.render_snapshot().layers[0].scale_range is None


def test_contour_and_point_render_snapshots_are_cached_per_geometry() -> None:
    from paleo_workbench.viz.native_factor_map import MapScene

    scene = MapScene()
    scene.add_contours("c1", [[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]], extent=(0.0, 0.0, 2.0, 1.0))
    scene.add_sample_points("p1", [(0.5, 0.5), (1.5, 0.5)], extent=(0.0, 0.0, 2.0, 1.0))

    first = scene.render_snapshot()
    second = scene.render_snapshot()

    contour_first = next(layer for layer in first.layers if layer.id == "c1")
    contour_second = next(layer for layer in second.layers if layer.id == "c1")
    assert contour_first.features is contour_second.features

    point_first = next(layer for layer in first.layers if layer.id == "p1")
    point_second = next(layer for layer in second.layers if layer.id == "p1")
    assert point_first.features is point_second.features
