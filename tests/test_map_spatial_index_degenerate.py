"""Regression tests for #887: degenerate-span layers must not hang the index.

A layer whose features are all (nearly) coincident previously shrank the
grid cell size to 1e-9, so a normal-tolerance identify/snap enumerated
billions of cells. Queries now cap the enumerated cells and fall back to a
linear scan, and a zero span falls back to cell size 1.0.
"""

from __future__ import annotations

import time

from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer


def _point_layer(*points: tuple[float, float]) -> VectorLayer:
    features = [
        VectorFeature(f"w{i}", {"type": "Point", "coordinates": list(point)})
        for i, point in enumerate(points)
    ]
    return VectorLayer(id="unified:wells", name="Wells", features=features)


def test_single_point_layer_identify_is_fast() -> None:
    index = FeatureSpatialIndex(_point_layer((5.0, 5.0)))
    start = time.monotonic()
    assert index.identify((5.0, 5.0), tolerance=1e-3) == "w0"
    assert index.identify((100.0, 100.0), tolerance=1e-3) is None
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"identify took {elapsed:.2f}s on a single-point layer"


def test_single_point_layer_vertex_snap_is_fast() -> None:
    index = FeatureSpatialIndex(_point_layer((5.0, 5.0)))
    start = time.monotonic()
    match = index.snap((5.0001, 5.0), tolerance=1e-2)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"snap took {elapsed:.2f}s on a single-point layer"
    assert match is not None and match.feature_id == "w0"


def test_degenerate_layer_candidates_match_bruteforce() -> None:
    points = [(5.0, 5.0), (5.0, 5.0), (5.0, 5.0001)]
    index = FeatureSpatialIndex(_point_layer(*points))
    index._ensure()
    bounds = (4.9, 4.9, 5.1, 5.1)
    candidates = index._feature_candidates(bounds)
    assert {feature.feature_id for feature in candidates} == {"w0", "w1", "w2"}


def test_huge_tolerance_falls_back_to_linear_scan() -> None:
    # Even with a healthy span, a tolerance far larger than the layer span
    # (e.g. extreme zoom-out) must not enumerate unbounded cells.
    index = FeatureSpatialIndex(_point_layer((0.0, 0.0), (100.0, 0.0)))
    start = time.monotonic()
    assert index.identify((50.0, 0.0), tolerance=1e6) == "w1"
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"identify with huge tolerance took {elapsed:.2f}s"


def test_mixed_polygon_layer_identify_unchanged() -> None:
    layer = VectorLayer(
        id="unified:facies",
        name="Facies",
        features=[
            VectorFeature("A", {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}),
            VectorFeature("B", {"type": "Polygon", "coordinates": [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]]}),
        ],
    )
    index = FeatureSpatialIndex(layer)
    assert index.identify((7.5, 5.0), tolerance=0.0) == "B"
    assert index.identify((2.5, 5.0), tolerance=0.0) == "A"
    assert index.identify((50.0, 50.0), tolerance=0.0) is None
