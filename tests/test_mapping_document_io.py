from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.mapping.document_io import (
    features_from_document,
    apply_features_to_document,
)


def test_features_from_document_normalizes_facies_and_wells():
    doc = PaleoMapDocument(
        name="Map A",
        linked_target_horizon="D5",
        facies_polygons=[
            {"id": "f1", "name": "三角洲", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]},
        ],
        well_overlays=[{"id": "w1", "name": "A1", "x": 10.0, "y": 20.0}],
    )
    features = features_from_document(doc)
    kinds = {f["kind"] for f in features}
    assert kinds == {"facies", "well"}
    well = next(f for f in features if f["kind"] == "well")
    assert well["coordinates"] == [10.0, 20.0]


def test_apply_features_round_trip_lines_and_labels():
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    features = [
        {
            "id": "f1",
            "kind": "facies",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
            "style": {},
        },
        {"id": "ln1", "kind": "line", "name": "F1", "coordinates": [[0, 0], [3, 3]]},
        {"id": "lb1", "kind": "label", "name": "注记", "text": "注记", "coordinates": [1, 1]},
    ]
    apply_features_to_document(doc, features)
    assert len(doc.facies_polygons) == 1
    assert len(doc.line_features) == 1
    assert len(doc.label_features) == 1
    back = features_from_document(doc)
    assert {f["id"] for f in back} == {"f1", "ln1", "lb1"}


def test_malformed_coordinates_skipped_not_crashed_or_faked():
    """#1162: short coordinates skip + warn — no IndexError (label), no
    silent y=0.0 persistence (well)."""
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    apply_features_to_document(doc, [
        {"id": "w-bad", "kind": "well", "name": "坏井", "coordinates": [116.0]},
        {"id": "lb-bad", "kind": "label", "name": "坏注记", "text": "x", "coordinates": [1.0]},
        {"id": "w-ok", "kind": "well", "name": "好井", "coordinates": [116.0, 22.0]},
    ])
    assert [w["id"] for w in doc.well_overlays] == ["w-ok"]
    assert doc.well_overlays[0]["x"] == 116.0
    assert doc.well_overlays[0]["y"] == 22.0
    assert doc.label_features == []


def test_facies_polygon_holes_round_trip_without_flattening():
    coordinates = [
        [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]],
        [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]],
    ]
    doc = PaleoMapDocument(
        name="holes",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "type": "Feature",
                "properties": {"id": "f-hole", "facies": "delta"},
                "geometry": {"type": "Polygon", "coordinates": coordinates},
            }
        ],
    )

    feature = features_from_document(doc)[0]
    assert feature["geometry_type"] == "Polygon"
    assert feature["coordinates"] == coordinates

    target = PaleoMapDocument(name="target", linked_target_horizon="H")
    apply_features_to_document(target, [feature])
    saved = target.facies_polygons[0]
    assert saved["geometry"] == {"type": "Polygon", "coordinates": coordinates}
    assert features_from_document(target)[0]["coordinates"] == coordinates


def test_facies_multipolygon_round_trip_preserves_every_part():
    coordinates = [
        [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
    ]
    doc = PaleoMapDocument(
        name="multi",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "multi",
                "geometry": {"type": "MultiPolygon", "coordinates": coordinates},
            }
        ],
    )

    feature = features_from_document(doc)[0]
    assert feature["geometry_type"] == "MultiPolygon"
    assert feature["coordinates"] == coordinates

    apply_features_to_document(doc, [feature])
    assert doc.facies_polygons[0]["geometry"]["type"] == "MultiPolygon"
    assert doc.facies_polygons[0]["geometry"]["coordinates"] == coordinates
