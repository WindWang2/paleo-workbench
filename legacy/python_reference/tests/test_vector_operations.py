"""GEOS-backed merge/split remain edit-buffer commands, not graphics operations."""

import pytest

from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.mapping.vector_operations import merge_selected_polygons, split_polygon_by_line


def _polygon_layer() -> tuple[VectorLayer, object]:
    layer = VectorLayer(
        id="facies", name="Facies", features=[
            VectorFeature("left", {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}),
            VectorFeature("right", {"type": "Polygon", "coordinates": [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]]}),
        ],
    )
    return layer, layer.start_editing()


def test_merge_and_split_are_reversible_session_operations() -> None:
    pytest.importorskip("shapely")
    layer, session = _polygon_layer()
    merged_id = merge_selected_polygons(session, ["left", "right"])

    assert session.feature(merged_id).geometry["type"] in {"Polygon", "MultiPolygon"}
    assert session.undo()
    assert {feature.feature_id for feature in session.features()} == {"left", "right"}

    cutter = VectorFeature("cutter", {"type": "LineString", "coordinates": [[1, -1], [1, 3]]})
    split_ids = split_polygon_by_line(session, "left", cutter)
    assert len(split_ids) == 2
    assert session.undo()
    assert session.feature("left").feature_id == "left"


def test_merge_accepts_one_shot_iterable() -> None:
    """R2-10: a generator input must not be exhausted by validation and
    then re-raise 'select at least two polygons' — forward the deduped ids."""
    layer, session = _polygon_layer()
    merged_id = merge_selected_polygons(
        session, (k for k in ["left", "right"])  # one-shot generator
    )
    assert merged_id
