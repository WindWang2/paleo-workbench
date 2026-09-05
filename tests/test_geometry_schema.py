"""normalize_facies / normalize_well accept demo draft and GeoJSON shapes."""

from __future__ import annotations

import pytest

from paleo_workbench.project.domain import CoordinateStatus
from paleo_workbench.mapping.geometry_schema import (
    normalize_facies,
    normalize_label,
    normalize_well,
)


def test_normalize_well_accepts_lng_lat():
    w = normalize_well({"name": "A1", "lng": 114.1, "lat": 22.7})
    assert w["coordinates"] == [114.1, 22.7]
    assert w["name"] == "A1"


def test_normalize_facies_reads_properties_name():
    f = normalize_facies(
        {
            "type": "Feature",
            "properties": {"name": "三角洲", "facies": "三角洲"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]],
            },
        }
    )
    assert f["name"] == "三角洲"
    assert len(f["coordinates"]) == 4


# ------------------------------------------------------- audit #1162 tests


def test_normalize_well_rejects_short_coordinates_without_crashing():
    """A single-element coordinates payload must not IndexError (#1162)."""
    w = normalize_well({"name": "A1", "coordinates": [114.1], "x": 1.5, "y": 2.5})
    # Scalar keys are the fallback when the coordinates payload is unusable.
    assert w["coordinates"] == [1.5, 2.5]
    assert w["coordinate_status"] == "ok"


def test_normalize_well_short_coordinates_without_scalar_keys_flagged_invalid():
    w = normalize_well({"name": "A1", "coordinates": [114.1]})
    assert w["coordinate_status"] == CoordinateStatus.INVALID
    assert w["coordinates"] == [114.1, 0.0]


def test_normalize_well_two_element_coordinates_still_ok():
    w = normalize_well({"name": "A1", "coordinates": [10.0, 20.0]})
    assert w["coordinates"] == [10.0, 20.0]
    assert w["coordinate_status"] == CoordinateStatus.OK


# ---------------------------------------------- scalar key-family semantics


def test_normalize_well_cross_family_scalar_pair_is_invalid():
    """`{x, lat}` mixes a projected x with a geographic latitude: scalar
    fallback selects whole CRS families only, so the pair must NOT be
    cross-paired into an "ok" feature (pipeline #1150 semantics)."""
    w = normalize_well({"name": "A1", "x": 1.0, "lat": 2.0})
    assert w["coordinate_status"] == CoordinateStatus.INVALID
    # No mixed pair produced: the placeholder keeps the partial-evidence
    # behaviour (leading scalar absent here → [0.0, 0.0]).
    assert w["coordinates"] == [0.0, 0.0]


def test_normalize_well_scalar_families_selected_whole():
    """Complete families are honoured in priority order: (x,y) → (lng,lat)
    → (lon,lat)."""
    assert normalize_well({"name": "A", "x": 1.0, "y": 2.0})["coordinates"] == [1.0, 2.0]
    assert normalize_well({"name": "B", "lng": 114.0, "lat": 22.0})["coordinates"] == [
        114.0,
        22.0,
    ]
    assert normalize_well({"name": "C", "lon": 115.0, "lat": 23.0})["coordinates"] == [
        115.0,
        23.0,
    ]
    # xy wins over lng/lat when both families are complete
    w = normalize_well({"name": "D", "x": 1.0, "y": 2.0, "lng": 3.0, "lat": 4.0})
    assert w["coordinates"] == [1.0, 2.0]
    # incomplete fallback family (lon without lat) never crosses into x/lat
    w = normalize_well({"name": "E", "x": 1.0, "lon": 115.0, "lat": 23.0})
    assert w["coordinates"] == [115.0, 23.0]
    assert w["coordinate_status"] == CoordinateStatus.OK


def test_normalize_label_short_anchor_raises_descriptive_error():
    """Short anchor raises ValueError (caught+skipped by import), not IndexError."""
    with pytest.raises(ValueError, match="label anchor"):
        normalize_label({"id": "lb1", "text": "t", "anchor": [1.0]})


def test_normalize_label_valid_anchor_unchanged():
    lb = normalize_label({"id": "lb1", "text": "t", "anchor": [1.0, 2.0]})
    assert lb["coordinates"] == [1.0, 2.0]
