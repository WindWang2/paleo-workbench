"""Legacy-document migration adapter around one authoritative MapScene registry."""

from __future__ import annotations

from paleo_workbench.mapping.map_scene_adapter import LegacyDocumentSceneAdapter
from paleo_workbench.project.models import PaleoMapDocument


def test_legacy_document_scene_adapter_preserves_scene_identity_and_updates_revisions() -> None:
    document = PaleoMapDocument(
        id="map-1",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "A", "coordinates": [[0, 0], [2, 0], [0, 2]]}
        ],
    )
    adapter = LegacyDocumentSceneAdapter()

    first = adapter.sync(document, project_crs="EPSG:3857")
    scene = adapter.scene
    layer = scene.registry.get("map-1:facies")
    assert layer is not None
    first_data_revision = layer.data_revision

    document.facies_style["fill"] = "#55b6ff"
    styled = adapter.sync(document, project_crs="EPSG:3857")
    assert adapter.scene is scene
    assert scene.registry.get("map-1:facies").data_revision == first_data_revision
    assert styled.layers[0].style_revision > first.layers[0].style_revision

    document.facies_polygons[0]["coordinates"][1] = [4, 0]
    edited = adapter.sync(document, project_crs="EPSG:3857")
    assert edited.layers[0].data_revision > styled.layers[0].data_revision


def test_legacy_document_scene_adapter_keeps_live_unsaved_records_out_of_document() -> None:
    document = PaleoMapDocument(
        id="map-1",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "f1", "name": "A", "coordinates": [[0, 0], [2, 0], [0, 2]]}
        ],
    )
    live_records = [
        {
            "id": "f1",
            "kind": "facies",
            "name": "A",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10, 0], [12, 0], [10, 2], [10, 0]]],
            },
        }
    ]
    adapter = LegacyDocumentSceneAdapter()

    snapshot = adapter.sync(document, project_crs="EPSG:3857", records=live_records)

    assert snapshot.layers[0].features[0]["geometry"]["coordinates"][0][0] == [10, 0]
    assert document.facies_polygons[0]["coordinates"][0] == [0, 0]
