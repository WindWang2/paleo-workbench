"""M9 — geological style library.

Coverage of every geological category, categorized/graduated styles bound to
their scientific fields, JSON round-trip, and layer application with
style↔science traceability.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.geological_style_library import (
    CATEGORIES,
    GEOLOGICAL_STYLE_LIBRARY,
    StyleEntry,
    apply_style_to_layer,
    load_style_library,
    save_style_library,
    style_entry,
)
from paleo_workbench.mapping.layers import VectorMapLayer
from paleo_workbench.mapping.map_styles import LinePattern, MarkerSymbol


def test_library_covers_all_geological_categories():
    present = {entry.category for entry in GEOLOGICAL_STYLE_LIBRARY.values()}
    assert present == set(CATEGORIES)


def test_facies_style_binds_all_classes_to_field():
    entry = style_entry("facies_fills", "facies_v1")
    assert entry.binding["field"] == "facies_name"
    classes = entry.binding["classes"]
    assert len(classes) >= 6
    categories = entry.style.categories
    assert {c[0] for c in categories} == set(classes)
    # every category has a label (legend completeness by construction)
    assert all(c[2] for c in categories)


def test_well_symbols_use_standard_markers():
    standard = style_entry("well_symbols", "well_standard")
    assert standard.style.marker is MarkerSymbol.WELL
    fault = style_entry("fault", "fault_major")
    assert fault.style.line_pattern is LinePattern.DASH


def test_uncertainty_style_is_graduated_with_confidence_binding():
    entry = style_entry("uncertainty", "uncertainty_band")
    assert entry.style.renderer == "graduated"
    assert entry.binding["field"] == "confidence"
    # ranges must partition [0, 1] without gaps
    ranges = sorted(entry.style.ranges)
    assert ranges[0][0] == 0.0
    assert ranges[-1][1] >= 1.0
    for (lo_a, hi_a, *_), (lo_b, hi_b, *_) in zip(ranges, ranges[1:]):
        assert lo_b <= hi_a  # contiguous


def test_entry_roundtrip_through_json(tmp_path):
    payload = {
        "schema_version": 1,
        "styles": [entry.to_dict() for entry in GEOLOGICAL_STYLE_LIBRARY.values()],
    }
    path = tmp_path / "styles.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded = load_style_library(path)
    for key, entry in GEOLOGICAL_STYLE_LIBRARY.items():
        assert loaded[key].to_dict() == entry.to_dict()


def test_save_load_roundtrip(tmp_path):
    path = save_style_library(tmp_path / "lib" / "styles.json")
    loaded = load_style_library(path)
    assert set(loaded) == set(GEOLOGICAL_STYLE_LIBRARY)


def test_load_rejects_unknown_schema(tmp_path):
    path = tmp_path / "styles.json"
    path.write_text(json.dumps({"schema_version": 99, "styles": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        load_style_library(path)


def test_unknown_style_key_lists_available():
    with pytest.raises(KeyError, match="facies_fills"):
        style_entry("facies_fills", "不存在")


def test_apply_style_records_binding_and_opacity_hint():
    layer = VectorMapLayer(id="l", name="相带", layer_type="vector")
    entry = GEOLOGICAL_STYLE_LIBRARY["reference.reference_basemap"]
    apply_style_to_layer(layer, entry)
    assert layer.style["style_binding"]["class"] == "reference"
    assert layer.opacity == pytest.approx(0.4)

    facies = VectorMapLayer(id="l2", name="相带", layer_type="vector", opacity=1.0)
    apply_style_to_layer(facies, style_entry("facies_fills", "facies_v1"))
    assert facies.style["style_binding"]["field"] == "facies_name"
    assert facies.style["style_binding"]["classes"]
    assert "opacity_hint" not in facies.style  # style payload stays clean


def test_style_payload_parses_back_through_vector_style():
    from paleo_workbench.mapping.map_styles import VectorStyle

    for entry in GEOLOGICAL_STYLE_LIBRARY.values():
        restored = VectorStyle.from_dict(entry.style.to_dict())
        assert restored.renderer == entry.style.renderer
        assert len(restored.categories) == len(entry.style.categories)
        assert len(restored.ranges) == len(entry.style.ranges)
