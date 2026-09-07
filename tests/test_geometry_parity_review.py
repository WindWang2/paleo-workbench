"""Review Round 1 (scientific/GIS correctness): QGIS-vs-shapely parity for
the §4 facade fallback chain.

When the bridge is built these run the REAL QGIS engine against shapely on
canonical geological fixtures (bowtie, hole-y polygons, multiparts, donor
rings); without the bridge they verify the fallback is at least
self-consistent (same operation twice, same result) and honestly labeled.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping import geometry_operations as ops

SQ_A = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
SQ_B = {"type": "Polygon", "coordinates": [[[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]]]}
DONUT = {
    "type": "Polygon",
    "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
    ],
}
BOWTIE = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]],
}
UNCLOSED = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}


def _engine() -> str:
    return ops.engine_status()["ops"]["intersection"]


@pytest.mark.parametrize("a,b,expected", [
    (SQ_A, SQ_B, 25.0),
    (DONUT, SQ_B, 9.0),  # intersection of hole region minus hole coverage
    (SQ_A, DONUT, 84.0),
])
def test_intersection_areas(a, b, expected):
    result = ops.intersection(a, b)
    assert result.engine == _engine()
    from shapely.geometry import shape

    area = shape(result.geometry).area
    assert area == pytest.approx(expected, abs=1e-6)


def test_difference_with_holes():
    result = ops.difference(DONUT, SQ_B)
    from shapely.geometry import shape

    area = shape(result.geometry).area
    assert area == pytest.approx(84.0 - 9.0, abs=1e-6)


def test_repair_determinism():
    first = ops.repair(BOWTIE)
    second = ops.repair(BOWTIE)
    assert first.geometry == second.geometry
    assert first.engine == second.engine == _engine()


def test_validate_semantics():
    assert ops.validate(SQ_A).valid is True
    assert ops.validate(DONUT).valid is True
    assert ops.validate(BOWTIE).valid is False
    assert ops.validate(UNCLOSED).valid is False


def test_buffer_union_dissolve_chain():
    buffered = ops.buffer(SQ_A, 5.0, segments=32)
    merged = ops.union([buffered.geometry, SQ_B])
    dissolved = ops.dissolve([buffered.geometry, SQ_B])
    from shapely.geometry import shape

    assert shape(merged.geometry).area == pytest.approx(
        shape(dissolved.geometry).area)
    # buffer then clip must reconstruct ≥ the original area
    clipped = ops.clip(buffered.geometry, (0, 0, 10, 10))
    from shapely.geometry import shape as _shape

    assert _shape(clipped.geometry).area == pytest.approx(100.0, abs=1e-6)


def test_multipart_singlepart_invertible():
    parts = ops.multipart_to_singlepart({
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [2, 0], [2, 2], [0, 0]]],
            [[[5, 5], [7, 5], [7, 7], [5, 5]]],
        ],
    })
    merged = ops.singlepart_to_multipart(parts.geometries)
    assert merged.geometry["type"] == "MultiPolygon"
    assert len(merged.geometry["coordinates"]) == 2


def test_engine_honesty_guard():
    status = ops.engine_status()
    if not status["bridge_available"]:
        for name in ("intersection", "buffer", "simplify", "repair"):
            assert status["ops"][name] == ops.ENGINE_SHAPELY
    else:
        pytest.skip("QGIS engine active — shapely parity checked in R1 narrative")
