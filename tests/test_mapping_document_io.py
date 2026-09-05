from paleo_workbench.project.domain import CoordinateStatus
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


# ------------------------------------------------------- audit #1162 tests


def test_apply_features_short_label_coordinates_skipped_not_crash(caplog):
    """Single-element label coordinates must be skipped with a diagnostic."""
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    features = [
        {"id": "lb_bad", "kind": "label", "name": "坏", "coordinates": [1]},
        {"id": "lb_ok", "kind": "label", "name": "好", "coordinates": [1, 2]},
    ]
    with caplog.at_level("WARNING", logger="paleo_workbench.mapping.document_io"):
        apply_features_to_document(doc, features)
    assert [lb["id"] for lb in doc.label_features] == ["lb_ok"]
    assert doc.label_features[0]["anchor"] == [1.0, 2.0]
    assert any("lb_bad" in r.message for r in caplog.records)


def test_apply_features_empty_label_coordinates_skipped():
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    apply_features_to_document(
        doc, [{"id": "lb0", "kind": "label", "name": "t", "coordinates": []}]
    )
    assert doc.label_features == []


def test_apply_features_short_well_coordinates_flagged_invalid():
    """A well with one coordinate keeps the partial x but is flagged invalid."""
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    apply_features_to_document(
        doc,
        [{"id": "w1", "kind": "well", "name": "A1", "coordinates": [3.0]}],
    )
    assert len(doc.well_overlays) == 1
    rec = doc.well_overlays[0]
    assert rec["x"] == 3.0
    assert rec["y"] == 0.0
    assert rec["coordinate_status"] == CoordinateStatus.INVALID


def test_apply_features_missing_well_coordinates_flagged_missing():
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    apply_features_to_document(
        doc,
        [{"id": "w1", "kind": "well", "name": "A1", "coordinates": []}],
    )
    assert doc.well_overlays[0]["coordinate_status"] == CoordinateStatus.MISSING


def test_apply_features_valid_well_has_no_status_marker():
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    apply_features_to_document(
        doc,
        [{"id": "w1", "kind": "well", "name": "A1", "coordinates": [1.0, 2.0]}],
    )
    assert "coordinate_status" not in doc.well_overlays[0]
    assert doc.well_overlays[0]["x"] == 1.0
    assert doc.well_overlays[0]["y"] == 2.0
