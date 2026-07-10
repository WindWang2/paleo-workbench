"""normalize_facies / normalize_well accept demo draft and GeoJSON shapes."""

from paleo_workbench.mapping.geometry_schema import normalize_facies, normalize_well


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
