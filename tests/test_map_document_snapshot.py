"""Compatibility adapter from legacy map documents to renderer-neutral layers."""

from __future__ import annotations

from paleo_workbench.mapping.map_document_snapshot import (
    document_render_snapshot,
    extent_for_snapshot,
)
from paleo_workbench.project.models import PaleoMapDocument


def test_document_snapshot_groups_legacy_records_without_mutating_the_document() -> None:
    document = PaleoMapDocument(
        id="map-1",
        name="H1 facies",
        linked_target_horizon="H1",
        facies_polygons=[
            {
                "id": "facies-1",
                "name": "delta",
                "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
            }
        ],
        well_overlays=[{"id": "well-1", "name": "A", "x": 4, "y": 3}],
        line_features=[{"id": "fault-1", "name": "F", "coordinates": [[-2, 5], [12, 5]]}],
        label_features=[{"id": "label-1", "text": "H1", "anchor": [5, 8]}],
        facies_style={"fill": "#d9a441"},
    )

    snapshot = document_render_snapshot(
        document,
        project_crs="EPSG:3857",
        visibility={"well": False},
    )

    assert [layer.id for layer in snapshot.layers] == [
        "map-1:facies",
        "map-1:well",
        "map-1:line",
        "map-1:label",
    ]
    assert snapshot.layers[0].features[0]["geometry"]["type"] == "Polygon"
    assert snapshot.layers[1].visible is False
    assert snapshot.layers[2].features[0]["geometry"] == {
        "type": "LineString", "coordinates": [[-2.0, 5.0], [12.0, 5.0]]
    }
    assert snapshot.layers[3].features[0]["properties"]["text"] == "H1"
    assert extent_for_snapshot(snapshot) == (-2.0, 0.0, 12.0, 10.0)
    assert document.facies_polygons[0]["coordinates"][0] == [0, 0]


def test_document_snapshot_separates_data_and_style_revisions() -> None:
    document = PaleoMapDocument(
        id="map-1",
        name="H1 facies",
        linked_target_horizon="H1",
        facies_polygons=[
            {"id": "facies-1", "name": "delta", "coordinates": [[0, 0], [1, 0], [0, 1]]}
        ],
    )
    before = document_render_snapshot(document, project_crs="EPSG:3857")
    document.facies_style["fill"] = "#55b6ff"
    styled = document_render_snapshot(document, project_crs="EPSG:3857")
    document.facies_polygons[0]["coordinates"][1] = [2, 0]
    edited = document_render_snapshot(document, project_crs="EPSG:3857")

    assert styled.layers[0].data_revision == before.layers[0].data_revision
    assert styled.layers[0].style_revision != before.layers[0].style_revision
    assert edited.layers[0].data_revision != styled.layers[0].data_revision
    assert edited.layers[0].style_revision == styled.layers[0].style_revision
