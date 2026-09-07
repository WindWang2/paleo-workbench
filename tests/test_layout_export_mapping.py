"""V7 §13 — layout native mapping extension + explicit hybrid boundary.

Covers the legend-backed element mapping (COLORBAR / FACIES_LEGEND /
WELL_LEGEND onto the native ``legend`` item gated on the mirrored layer
set), the wire-key honesty (only keys the C++ legend branch parses), and
the itemized ``hybrid_items`` reporting of the all-or-nothing engine
policy. Runs bridge-free: the stack is faked, the mirror is a plain layer
description.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.composer.models import (
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.layout_export import (
    _HYBRID_TYPES,
    _LEGEND_BACKED_GATES,
    _LEGEND_ITEM_KEYS,
    _NATIVE_TYPES,
    build_layout_spec,
    export_composition_reported,
    hybrid_element_types,
)

# Single source of truth for the wire contract: the keys the C++ legend
# branch actually parses (see _LEGEND_ITEM_KEYS in layout_export).
CPP_LEGEND_KEYS = _LEGEND_ITEM_KEYS

EXTENT = (0.0, 0.0, 10.0, 9.0)


def _composition(*elements: ComposerElement) -> MapCompositionDocument:
    doc = MapCompositionDocument(id="comp_v7", title="t")
    doc.add_element(
        ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180.0, 150.0)
    )
    for element in elements:
        doc.add_element(element)
    return doc


def _colorbar() -> ComposerElement:
    return ComposerElement(
        "el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0,
        properties={"title": "砂地比", "units": "%", "min": 0.0, "max": 1.0},
    )


class _FakeLayer:
    def __init__(self, layer_id: str, layer_type: str, style=None):
        self.id = layer_id
        self.name = layer_id
        self.layer_type = layer_type
        self.style = style or {}


class _FakeSnapshot:
    def __init__(self, *layers: _FakeLayer):
        self.project_crs = "EPSG:4326"
        self.layers = tuple(layers)


class _FakeStack:
    """Duck-typed QgisMapStack: records the spec, reports success."""

    def __init__(self):
        self.spec: dict | None = None

    def layout_export(self, spec_json: str, path: str, fmt: str, dpi: float):
        self.spec = json.loads(spec_json)
        return json.dumps({"ok": True, "items": len(self.spec["items"])})


# ---------------------------------------------------------------------------
# Completeness of the mapping table (§13: every element accounted for)
# ---------------------------------------------------------------------------


def test_every_element_type_is_native_hybrid_or_legend_backed():
    accounted = set(_NATIVE_TYPES) | set(_HYBRID_TYPES) | set(_LEGEND_BACKED_GATES)
    assert accounted == set(ElementType)
    # the three buckets are disjoint
    assert not set(_NATIVE_TYPES) & set(_HYBRID_TYPES)
    assert not set(_NATIVE_TYPES) & set(_LEGEND_BACKED_GATES)
    assert not set(_HYBRID_TYPES) & set(_LEGEND_BACKED_GATES)


def test_documented_hybrid_boundary_is_exactly_these_types():
    assert {t.value for t in _HYBRID_TYPES} == {
        "timescale", "inset_map", "stat_chart", "profile",
        "fault_symbols", "lithology_legend",
    }


# ---------------------------------------------------------------------------
# COLORBAR → native legend bound to the scalar raster path
# ---------------------------------------------------------------------------


def test_colorbar_maps_to_native_legend_with_scalar_in_mirror():
    mirror = _FakeSnapshot(_FakeLayer("grid1", "scalar_grid"))
    warnings: list[str] = []
    spec = build_layout_spec(
        _composition(_colorbar()), map_extent=EXTENT, crs="EPSG:4326",
        warnings=warnings, mirror_layers=mirror,
    )
    legends = [i for i in spec["items"] if i["type"] == "legend"]
    assert len(legends) == 1
    legend = legends[0]
    assert legend["map_item"] == "map"  # bound to the main map item
    assert legend["title"] == "砂地比 (%)"
    assert set(legend) <= CPP_LEGEND_KEYS
    # the no-filter limitation is disclosed, not silent
    assert any("cannot filter layers" in w for w in warnings)


def test_colorbar_without_scalar_layer_stays_composer():
    mirror = _FakeSnapshot(_FakeLayer("v1", "vector"))
    composition = _composition(_colorbar())
    assert hybrid_element_types(composition, mirror_layers=mirror) == ["colorbar"]
    with pytest.raises(ValueError, match="colorbar"):
        build_layout_spec(
            composition, map_extent=EXTENT, crs="EPSG:4326",
            mirror_layers=mirror,
        )
    # and without ANY mirror description the gate cannot be proven either
    assert hybrid_element_types(composition) == ["colorbar"]


def test_colorbar_accepts_snapshot_or_plain_sequence_mirror():
    # a bare sequence of layer dicts works the same as a snapshot object
    mirror = [{"id": "g", "layer_type": "scalar_grid"}]
    spec = build_layout_spec(
        _composition(_colorbar()), map_extent=EXTENT, crs=None,
        mirror_layers=mirror,
    )
    assert any(i["type"] == "legend" for i in spec["items"])


# ---------------------------------------------------------------------------
# Geological legend (FACIES_LEGEND) and well legend (WELL_LEGEND)
# ---------------------------------------------------------------------------


def test_facies_legend_native_with_polygon_or_categorized_vector():
    facies = ComposerElement(
        "el_fl", ElementType.FACIES_LEGEND, 205.0, 95.0, 78.0, 60.0,
        properties={"title": "沉积相图例"},
    )
    for mirror in (
        _FakeSnapshot(_FakeLayer("poly1", "polygon")),
        _FakeSnapshot(_FakeLayer(
            "v1", "vector", style={"renderer": "categorized", "field": "facies"}),
        ),
    ):
        spec = build_layout_spec(
            _composition(facies), map_extent=EXTENT, crs="EPSG:4326",
            mirror_layers=mirror,
        )
        legend = next(i for i in spec["items"] if i["type"] == "legend")
        assert legend["title"] == "沉积相图例"
        assert set(legend) <= CPP_LEGEND_KEYS


def test_well_legend_native_only_with_well_layer_in_mirror():
    well_legend = ComposerElement(
        "el_wl", ElementType.WELL_LEGEND, 205.0, 160.0, 70.0, 40.0,
        properties={"title": "测井图例", "items": ()},
    )
    composition = _composition(well_legend)
    assert hybrid_element_types(composition) == ["well_legend"]
    mirror = _FakeSnapshot(_FakeLayer("w1", "well_point"))
    spec = build_layout_spec(
        composition, map_extent=EXTENT, crs="EPSG:4326", mirror_layers=mirror,
    )
    legend = next(i for i in spec["items"] if i["type"] == "legend")
    assert legend["map_item"] == "map"
    assert set(legend) <= CPP_LEGEND_KEYS


# ---------------------------------------------------------------------------
# Hybrid boundary itemization in the export report
# ---------------------------------------------------------------------------


def test_hybrid_items_itemized_in_composer_fallback_report(tmp_path):
    composition = _composition(
        ComposerElement("el_chart", ElementType.STAT_CHART, 205.0, 30.0,
                        75.0, 55.0),
        ComposerElement("el_ts", ElementType.TIMESCALE, 15.0, 175.0,
                        180.0, 12.0),
        ComposerElement("el_ts2", ElementType.TIMESCALE, 15.0, 188.0,
                        180.0, 10.0),
    )
    report = export_composition_reported(
        composition, tmp_path / "page.svg", fmt="svg",
    )
    assert report.engine == "composer_fallback"
    assert report.hybrid_items == ["stat_chart", "timescale"]
    assert set(report.unmapped_elements) == {"el_chart", "el_ts", "el_ts2"}
    forced = [w for w in report.warnings if "forced by unmapped" in w]
    assert forced and "stat_chart×1" in forced[0] and "timescale×2" in forced[0]
    payload = report.to_dict()
    assert payload["hybrid_items"] == ["stat_chart", "timescale"]


def test_fully_native_composition_reports_empty_hybrid(tmp_path):
    mirror = _FakeSnapshot(
        _FakeLayer("grid1", "scalar_grid"),
        _FakeLayer("w1", "well_point"),
    )
    composition = _composition(_colorbar())
    stack = _FakeStack()
    report = export_composition_reported(
        composition, tmp_path / "page.pdf", fmt="pdf",
        map_extent=EXTENT, crs="EPSG:4326", stack=stack,
        mirror_layers=mirror,
    )
    assert report.engine == "qgis_layout"
    assert report.hybrid_items == []
    assert report.items == len(stack.spec["items"])
    # every legend on the wire binds to the main map item
    for item in stack.spec["items"]:
        if item["type"] == "legend":
            assert item["map_item"] == "map"


def test_legend_backed_hybrid_without_mirror_reported_itemized(tmp_path):
    # mirror omitted → the gate cannot be proven → composer, itemized
    composition = _composition(_colorbar())
    report = export_composition_reported(
        composition, tmp_path / "page.svg", fmt="svg",
        map_extent=EXTENT, crs="EPSG:4326", stack=_FakeStack(),
    )
    assert report.engine == "composer_fallback"
    assert report.hybrid_items == ["colorbar"]
    assert any("no matching layer in the mirror" in w for w in report.warnings)


def test_runtime_layout_failure_keeps_mapping_boundary_report(tmp_path):
    class _FailingStack:
        def layout_export(self, spec_json, path, fmt, dpi):
            raise RuntimeError("boom")

    composition = _composition(
        ComposerElement("el_sub", ElementType.SUBTITLE, 60.0, 8.0, 120.0, 6.0,
                        properties={"text": "T1"}),
    )
    report = export_composition_reported(
        composition, tmp_path / "page.svg", fmt="svg",
        map_extent=EXTENT, crs=None, stack=_FailingStack(),
    )
    assert report.engine == "composer_fallback"
    # a runtime failure is not a mapping gap: nothing is hybrid
    assert report.hybrid_items == []
    assert any("qgis layout export failed" in w for w in report.warnings)
