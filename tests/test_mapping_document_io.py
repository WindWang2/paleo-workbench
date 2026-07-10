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
