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


def test_normalize_label_short_anchor_raises_descriptive_error():
    """Short anchor raises ValueError (caught+skipped by import), not IndexError."""
    with pytest.raises(ValueError, match="label anchor"):
        normalize_label({"id": "lb1", "text": "t", "anchor": [1.0]})


def test_normalize_label_valid_anchor_unchanged():
    lb = normalize_label({"id": "lb1", "text": "t", "anchor": [1.0, 2.0]})
    assert lb["coordinates"] == [1.0, 2.0]
