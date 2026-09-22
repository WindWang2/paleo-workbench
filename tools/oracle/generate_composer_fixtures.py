#!/usr/bin/env python3
"""Freeze the V14 composer template/renderer/export oracle.

Runs the FROZEN Python reference
(``paleo_workbench/mapping/composer/{templates,renderer,export}.py``) over a
deterministic corpus of compositions and writes
``libs/mapping_document/mapping_document_tests/fixtures/composer_oracle.json``,
which the C++ test (``composer_oracle_test.cpp``) replays.

Determinism: element ids are produced by a counter (Python's uuid4 is
process-random) and the renderer's ``hash()``-derived SVG ids (cbar_/grad_/
lith_) are normalised to stable placeholders in the frozen text — the C++
side applies the same normalisation before comparing, and the test
additionally asserts the C++ ids are stable across two render calls.

The sandbox has no numpy and no PySide6; the frozen modules import both
transitively, so ``_np_stub`` installs inert stand-ins (the rendered code
paths never execute numeric or Qt code — Qt is imported lazily inside the
export functions this generator does not call).

Usage:
    python3 tools/oracle/generate_composer_fixtures.py [--out PATH] [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _np_stub  # noqa: E402

_np_stub.install()
_np_stub.install_pyside_stub()

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping.composer import (  # noqa: E402
    components as py_components,
    registry as py_registry,
    export as py_export,
    models as py_models,
    renderer as py_renderer,
    templates as py_templates,
)
from paleo_workbench.mapping.color_ramps import get_color_ramp  # noqa: E402

SCHEMA = "composer-oracle-v14-1"
DEFAULT_OUT = os.path.join(
    REPO_ROOT,
    "libs",
    "mapping_document",
    "mapping_document_tests",
    "fixtures",
    "composer_oracle.json",
)

# hash()-derived SVG ids are process-random in Python; normalise them so the
# frozen text is stable. The C++ test applies the identical patterns.
NORMALISATIONS = [
    (re.compile(r"cbar_\d+"), "cbar_H"),
    (re.compile(r"grad_(\d+)_\d+"), r"grad_\1_H"),
    (re.compile(r"lith_\d+"), "lith_H"),
]


def normalise(text: str) -> str:
    for pattern, replacement in NORMALISATIONS:
        text = pattern.sub(replacement, text)
    return text


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deterministic element ids (Python's _new_element_id uses uuid4).
# ---------------------------------------------------------------------------

_ID_COUNTER = {"n": 0}


def _deterministic_element_id() -> str:
    _ID_COUNTER["n"] += 1
    return "el_%010d" % _ID_COUNTER["n"]


py_models._new_element_id = _deterministic_element_id


class _DeterministicUuid:
    """uuid4() stand-in with a counter body (templates.py uses uuid4)."""

    def __init__(self, hex_body):
        self.hex = hex_body


class _DeterministicUuidModule:
    def uuid4(self):
        _ID_COUNTER["n"] += 1
        return _DeterministicUuid("%010x" % _ID_COUNTER["n"])


py_templates.uuid = _DeterministicUuidModule()
# CompositionFactory.create_document also mints a uuid document id.
py_components.uuid = _DeterministicUuidModule()


_DOC_COUNTER = {"n": 0}


def make_doc(elements, title="oracle", paper="A4", orientation="landscape",
             dpi=300.0, metadata=None):
    _DOC_COUNTER["n"] += 1
    doc = py_models.MapCompositionDocument(
        id="comp_%010d" % _DOC_COUNTER["n"], title=title)
    doc.dpi = dpi
    if metadata:
        doc.metadata.update(metadata)
    if paper != "A4" or orientation != "landscape":
        doc.set_paper(paper, orientation)
    for element in elements:
        doc.add_element(element)
    return doc


def el(element_type, x, y, w, h, z=0, visible=True, locked=False, **properties):
    return py_models.ComposerElement(
        id=_deterministic_element_id(),
        element_type=py_models.ElementType(element_type),
        x_mm=x,
        y_mm=y,
        width_mm=w,
        height_mm=h,
        z_index=z,
        visible=visible,
        locked=locked,
        properties=dict(properties),
    )


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def element_corpus():
    """One composition carrying every element type in the vocabulary."""
    return make_doc(
        [
            el("main_map", 10, 20, 100, 80, z=10),
            el("title", 10, 4, 100, 10, z=40, text="标题文本"),
            el("subtitle", 10, 15, 100, 6, z=39, text="副标题"),
            el("north_arrow", 120, 6, 12, 16, z=30),
            el("scale_bar", 12, 104, 46, 7, z=30, length_km=10),
            el("legend", 120, 24, 78, 56, z=30, items=[
                {"label": "面状", "color": "#ffe082"},
                {"label": "线状", "color": "#333333", "symbol_type": "line"},
                {"label": "点状", "color": "#e45756", "symbol_type": "point"},
                {"label": "渐变", "color": "#000000", "symbol_type": "gradient",
                 "gradient_stops": [[0.0, "#053061"], [1.0, "#67001f"]]},
            ]),
            el("facies_legend", 120, 84, 78, 40, z=30),
            el("well_legend", 120, 128, 78, 20, z=30, items=[
                {"label": "钻井", "color": "#22b8a7", "symbol_type": "point"},
            ]),
            el("colorbar", 204, 24, 12, 36, z=30, title="色标", min=0.0, max=1.0),
            el("grid", 10, 20, 100, 80, z=20, spacing_mm=30.0),
            el("annotation", 30, 40, 42, 8, z=35, text="注记 →"),
            el("annotation", 30, 52, 42, 8, z=35, text="无引线", leader=False),
            el("timescale", 10, 116, 100, 14, z=30, stages=[
                {"label": "Q", "start": 0.0, "end": 2.6, "color": "#f2f2f2"},
                {"label": "K", "start": 2.6, "end": 66.0, "color": "#d9e6c3"},
            ]),
            el("neatline", 8, 18, 102, 82, z=5, line_width_mm=0.8),
            el("datasource", 204, 128, 78, 26, z=30, title="数据来源",
               text="来源A：\n来源B："),
            el("time_credits", 204, 158, 78, 18, z=30, text="制图：\n审核："),
            el("fault_symbols", 204, 180, 78, 26, z=30, items=[
                {"label": "正断层", "pattern": "solid"},
                {"label": "逆断层", "pattern": "dash"},
                {"label": "点线", "pattern": "dot"},
                {"label": "点划", "pattern": "dashdot"},
                {"label": "断层", "pattern": "fault"},
                {"label": "未知", "pattern": "mystery"},
            ]),
            el("lithology_legend", 8, 140, 78, 30, z=30, items=[
                {"label": "砂岩", "color": "#ffe082", "pattern": "dots"},
                {"label": "泥岩", "color": "#b0bec5", "pattern": "lines"},
                {"label": "灰岩", "color": "#cfd8dc", "pattern": "crosshatch"},
            ]),
            el("strat_labels", 10, 158, 100, 12, z=30, text="层序标签"),
            el("text", 10, 174, 100, 12, z=30, text="多行\n文本\n块"),
            el("metadata", 10, 190, 160, 14, z=30, fields=[
                ["编制", ""], ["日期", ""], ["比例尺", ""], ["数据来源", ""],
                ["审核", ""], ["图号", ""], ["比例", ""], ["密级", ""],
            ]),
            el("image", 204, 6, 40, 20, z=30),
            el("inset_map", 120, 152, 60, 44, z=30, locator_rect=[0.2, 0.2, 0.4, 0.4]),
            el("profile", 8, 104, 60, 30, z=30),
            el("stat_chart", 204, 210, 78, 48, z=30),
        ],
        title="全要素",
    )


def chart_corpus():
    """Every chart type, valid and empty data, plus normalisation edges."""
    series = [
        {"label": "A", "value": 3.0},
        {"label": "B", "value": 7.0},
        {"label": "C", "value": 1.0},
    ]
    docs = []
    for chart_type in ("bar", "hbar", "line", "scatter", "pie", "donut",
                       "histogram", "rose"):
        docs.append((f"chart_{chart_type}", make_doc([
            el("stat_chart", 10, 10, 90, 70, z=30, chart_type=chart_type,
               title=f"{chart_type} 图", series=series, units="m"),
        ], title=chart_type)))
    # Series shapes: {x,y} arrays, point pairs, negative values, single point.
    docs.append(("chart_line_xy_arrays", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="line",
           series={"x": [0.0, 1.0, 2.0, 3.0], "y": [1.0, 4.0, 2.0, 8.0]},
           units="m"),
    ])))
    docs.append(("chart_scatter_pairs", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="scatter",
           series=[{"x": 1.0, "y": 2.0, "label": "p1"},
                   {"x": 2.0, "y": 5.0, "label": "p2"}]),
    ])))
    docs.append(("chart_bar_negative", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="bar",
           series=[{"label": "n", "value": -3.0}, {"label": "z", "value": 0.0}]),
    ])))
    docs.append(("chart_donut_hole", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="donut",
           hole_ratio=0.7, series=series),
    ])))
    docs.append(("chart_donut_bad_hole", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="donut",
           hole_ratio="x", series=series),
    ])))
    docs.append(("chart_pie_single", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="pie",
           series=[{"label": "only", "value": 5.0}]),
    ])))
    docs.append(("chart_histogram_bins", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="histogram",
           series={"values": [1.0, 2.0, 2.0, 3.0, 5.0, 8.0], "bins": 4}),
    ])))
    docs.append(("chart_histogram_bad_values", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="histogram",
           series={"values": ["a", None, 1.0], "bins": "x"}),
    ])))
    docs.append(("chart_rose_angles", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="rose", series=[
            {"label": "NE", "angle_deg": 45.0, "value": 8.0},
            {"label": "SE", "angle_deg": 135.0, "value": 5.0},
        ]),
    ])))
    docs.append(("chart_empty_series", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="bar"),
    ])))
    docs.append(("chart_bad_entries", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="bar", series=[
            "not-a-mapping", {"label": "x", "value": "bad"}, {"label": "y"},
        ]),
    ])))
    docs.append(("chart_custom_colors", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="bar",
           series=series, colors=["#111111", "#222222"]),
    ])))
    docs.append(("chart_unknown_type", make_doc([
        el("stat_chart", 10, 10, 90, 70, z=30, chart_type="spider",
           series=series),
    ])))
    return docs


def dict_layer_corpus():
    """Pure-JSON dict layers through the composer main-map branch 3."""
    extent = [0.0, 0.0, 100.0, 100.0]
    polygon_feature = {
        "type": "Feature",
        "geometry": {"type": "Polygon",
                     "coordinates": [[[10, 10], [40, 10], [40, 40], [10, 40], [10, 10]]]},
        "properties": {"name": "p1", "facies_name": "sand", "value": 12.0},
    }
    line_feature = {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[10, 60], [50, 80], [90, 60]]},
        "properties": {"name": "fault1", "value": 60.0},
    }
    point_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [30, 30]},
        "properties": {"name": "well-1", "value": 30.0},
    }
    multi_feature = {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon",
                     "coordinates": [[[[60, 60], [80, 60], [80, 80], [60, 80], [60, 60]]],
                                     [[[85, 10], [95, 10], [95, 20], [85, 20], [85, 10]]]]},
        "properties": {"facies_name": "mud"},
    }
    docs = []
    docs.append(("dict_layers_single", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v1", "name": "Vector", "layer_type": "vector",
             "features": [polygon_feature, line_feature, point_feature, multi_feature]},
        ]),
    ])))
    docs.append(("dict_layers_styled", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v2", "name": "Styled", "layer_type": "polygon",
             "style": {"fill": "#4fc3f7", "stroke": "#222222", "stroke_width": 1.5,
                       "line_pattern": "dash", "marker": "square", "marker_size": 8,
                       "labels": {"field": "name", "size": 9, "color": "#111111"}},
             "features": [polygon_feature, point_feature]},
        ]),
    ])))
    docs.append(("dict_layers_categorized", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v3", "name": "Facies", "layer_type": "facies",
             "style": {"renderer": "categorized", "field": "facies_name",
                       "categories": [["sand", "#ffe082", "砂"], ["mud", "#b0bec5", "泥"]]},
             "features": [polygon_feature, multi_feature]},
        ]),
    ])))
    docs.append(("dict_layers_graduated", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v4", "name": "Graduated", "layer_type": "vector",
             "style": {"renderer": "graduated", "field": "value",
                       "ranges": [[0.0, 25.0, "#f2f2f2", "低"], [25.0, 100.0, "#636363", "高"]]},
             "features": [polygon_feature, line_feature, point_feature]},
        ]),
    ])))
    docs.append(("dict_layers_default_color", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v5", "name": "Legacy", "layer_type": "vector",
             "color": "#123456", "features": [polygon_feature]},
        ]),
    ])))
    docs.append(("dict_layers_no_extent", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, layers=[
            {"id": "v6", "name": "NoExtent", "layer_type": "vector",
             "features": [polygon_feature]},
        ]),
    ])))
    docs.append(("dict_layers_empty_features", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v7", "name": "Empty", "layer_type": "vector", "features": []},
        ]),
    ])))
    # Well symbols, annotations and label layers: renderers.py's
    # WellSymbolRenderer / AnnotationRenderer take the same VectorMapLayer
    # feature shape, so the JSON route renders them (the registry resolves
    # them by layer_type AND by style.renderer keyword).
    well_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [30, 30]},
        "properties": {"name": "W-1", "value": 12.5},
    }
    plain_well_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [60, 60]},
        "properties": {"well": "W-2"},
    }
    docs.append(("dict_layers_well", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "w1", "name": "井位", "layer_type": "well",
             "style": {"fill": "#22b8a7", "stroke": "#182431", "marker_size": 7.0,
                       "labels": {"field": "name", "size": 9.0, "color": "#1f2937"}},
             "features": [well_feature, plain_well_feature]},
        ]),
    ])))
    docs.append(("dict_layers_well_renderer_keyword", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "w2", "name": "井位2", "layer_type": "vector",
             "style": {"renderer": "well", "fill": "#22b8a7", "stroke": "#182431"},
             "features": [well_feature]},
        ]),
    ])))
    annotation_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [40, 50]},
        "properties": {"text": "注记 A", "font_size": 8.0, "color": "#111111",
                       "rotation": 15.0, "show_marker": True},
    }
    annotation_line_feature = {
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [[10, 80], [50, 90], [90, 80]]},
        "properties": {"text": "线注记", "bold": True},
    }
    docs.append(("dict_layers_annotation", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "a1", "name": "注记", "layer_type": "annotation",
             "style": {"fill": "#eff3f8", "stroke": "#182431", "marker_size": 4.0},
             "features": [annotation_feature, annotation_line_feature]},
        ]),
    ])))
    docs.append(("dict_layers_label", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "a2", "name": "标签", "layer_type": "label",
             "style": {"fill": "#eff3f8", "stroke": "#182431"},
             "features": [{
                 "type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [70, 20]},
                 "properties": {"label": "标签 L", "size": 7.0},
             }]},
        ]),
    ])))
    # A falsy-but-present subtitle text renders (Python .get(key, default)).
    docs.append(("subtitle_falsy_text", make_doc([
        el("subtitle", 10, 15, 100, 6, z=39, text=0),
    ])))
    # Dict-layer labels strip surrounding whitespace (Python .strip()).
    docs.append(("dict_layers_label_whitespace", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, extent=extent, layers=[
            {"id": "v8", "name": "Padded", "layer_type": "vector",
             "style": {"fill": "#4fc3f7", "stroke": "#222222",
                       "labels": {"field": "name", "size": 9.0}},
             "features": [{
                 "type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [30, 30]},
                 "properties": {"name": "  W1  "},
             }]},
        ]),
    ])))
    return docs


def misc_corpus():
    docs = []
    # Unbound main map → honest placeholder.
    docs.append(("main_map_unbound", make_doc([
        el("main_map", 10, 20, 120, 100, z=10),
    ])))
    docs.append(("main_map_unbound_titled", make_doc([
        el("main_map", 10, 20, 120, 100, z=10, title="自定义画布"),
    ])))
    # Locked / invisible elements.
    docs.append(("locked_and_hidden", make_doc([
        el("title", 10, 4, 100, 10, z=40, text="锁定", locked=True),
        el("text", 10, 20, 100, 10, z=30, text="隐藏", visible=False),
        el("text", 10, 34, 100, 10, z=30, text="可见"),
    ])))
    # Unknown element type (forward-compat TEXT carrier, from_dict path).
    unknown_doc = py_models.MapCompositionDocument.from_dict({
        "id": "comp_unknown_type",
        "title": "unknown",
        "paper_size": "A4",
        "orientation": "landscape",
        "width_mm": 297.0,
        "height_mm": 210.0,
        "dpi": 300.0,
        "schema_version": 2,
        "elements": [
            {
                "id": "el_future_1",
                "element_type": "future_widget",
                "x_mm": 10.0, "y_mm": 10.0,
                "width_mm": 40.0, "height_mm": 20.0,
                "z_index": 30, "visible": True, "locked": False,
                "properties": {"text": "x"},
            }
        ],
        "metadata": {},
    })
    docs.append(("unknown_element_type", unknown_doc))
    # A marker stored on a genuine text element is popped as its type.
    docs.append(("raw_type_marker", py_models.MapCompositionDocument.from_dict({
        "id": "comp_raw_marker",
        "title": "raw",
        "elements": [
            {
                "id": "el_raw_1",
                "element_type": "text",
                "x_mm": 10.0, "y_mm": 10.0,
                "width_mm": 40.0, "height_mm": 20.0,
                "z_index": 30, "visible": True, "locked": False,
                "properties": {"_raw_element_type": "title", "text": "载体"},
            }
        ],
        "metadata": {},
    })))
    # Scale bar integer vs float length (Python // semantics).
    docs.append(("scale_bar_int", make_doc([
        el("scale_bar", 10, 10, 46, 7, z=30, length_km=50),
    ])))
    docs.append(("scale_bar_float", make_doc([
        el("scale_bar", 10, 10, 46, 7, z=30, length_km=25.5),
    ])))
    # Colorbar variants: discrete, explicit stops, named ramp, empty stops.
    docs.append(("colorbar_discrete", make_doc([
        el("colorbar", 10, 10, 12, 40, z=30, discrete=True,
           stops=[[0.0, "#111111"], [0.5, "#555555"], [1.0, "#999999"]]),
    ])))
    docs.append(("colorbar_named_ramp", make_doc([
        el("colorbar", 10, 10, 12, 40, z=30, color_ramp="viridis", min=0.0, max=100.0),
    ])))
    docs.append(("colorbar_alias_ramp", make_doc([
        el("colorbar", 10, 10, 12, 40, z=30, color_ramp="paleogeographic-v1"),
    ])))
    docs.append(("colorbar_default_stops", make_doc([
        el("colorbar", 10, 10, 12, 40, z=30),
    ])))
    # Text clipping (line overflow) + alignment variants.
    docs.append(("text_clipping", make_doc([
        el("text", 10, 10, 60, 8, z=30, text="L1\nL2\nL3\nL4\nL5\nL6", font_size=4.0),
        el("text", 80, 10, 60, 20, z=30, text="右对齐", align="right", font_size=3.0),
        el("text", 80, 40, 60, 20, z=30, text="居中", align="center", font_size=3.0),
        el("text", 80, 70, 60, 20, z=30, text="未知对齐", align="justify"),
    ])))
    docs.append(("text_empty", make_doc([
        el("text", 10, 10, 60, 10, z=30),
    ])))
    # Timescale without stages, metadata overflow, neatline double.
    docs.append(("timescale_empty", make_doc([
        el("timescale", 10, 10, 100, 14, z=30),
    ])))
    docs.append(("metadata_overflow", make_doc([
        el("metadata", 10, 10, 100, 8, z=30, fields=[["k%d" % i, "v"] for i in range(9)]),
    ])))
    docs.append(("metadata_bad_entries", make_doc([
        el("metadata", 10, 10, 100, 20, z=30, fields=[["ok", "v"], ["short"], "x", None]),
    ])))
    docs.append(("neatline_double", make_doc([
        el("neatline", 10, 10, 100, 60, z=30, double_line=True, inner_gap_mm=2.0),
    ])))
    # Image variants.
    docs.append(("image_b64", make_doc([
        el("image", 10, 10, 40, 20, z=30,
           image_data_png_b64="iVBORw0KGgo="),
    ])))
    docs.append(("image_path", make_doc([
        el("image", 10, 10, 40, 20, z=30, image_path="/tmp/x.png"),
    ])))
    # Well legend unbound → placeholder; profile bound → inset rendering.
    docs.append(("well_legend_unbound", make_doc([
        el("well_legend", 10, 10, 78, 20, z=30),
    ])))
    docs.append(("profile_bound", make_doc([
        el("profile", 10, 10, 80, 40, z=30, section_ref="sec-1",
           locator_rect=[0.1, 0.1, 0.5, 0.5]),
    ])))
    # Legend without items and no main map → documented defaults.
    docs.append(("legend_defaults", make_doc([
        el("legend", 10, 10, 78, 30, z=30),
    ])))
    docs.append(("legend_title_override", make_doc([
        el("legend", 10, 10, 78, 30, z=30, title="自定义图例", items=[
            {"label": "唯一", "color": "#abcdef"},
        ]),
    ])))
    docs.append(("legend_overflow", make_doc([
        el("legend", 10, 10, 78, 10, z=30, items=[
            {"label": "L%d" % i, "color": "#112233"} for i in range(8)
        ]),
    ])))
    # Fault symbols without items, lithology without patterns.
    docs.append(("fault_symbols_empty", make_doc([
        el("fault_symbols", 10, 10, 78, 26, z=30),
    ])))
    docs.append(("lithology_no_pattern", make_doc([
        el("lithology_legend", 10, 10, 78, 26, z=30, items=[
            {"label": "砂岩", "color": "#ffe082"},
        ]),
    ])))
    # Title/subtitle defaults and empty text.
    docs.append(("title_default", make_doc([
        el("title", 10, 4, 100, 10, z=40),
        el("subtitle", 10, 16, 100, 6, z=39),
    ])))
    # HTML escaping.
    docs.append(("escaping", make_doc([
        el("title", 10, 4, 100, 10, z=40, text='<b>&"\'</b>'),
        el("text", 10, 20, 100, 20, z=30, text="<script>alert(1)</script>\n第二行 & 转义"),
    ])))
    return docs


def template_docs():
    """Every built-in template, instantiated with the default title."""
    out = []
    for template_id in [t.template_id for t in py_templates.TEMPLATE_LIBRARY.values()]:
        doc = py_templates.instantiate_template(template_id)
        out.append((f"template_{template_id}", doc))
    # Explicit title/paper/orientation/dpi overrides + falsy fallbacks.
    out.append(("template_override", py_templates.instantiate_template(
        "contour", title="等值线定制", paper_size="A3", orientation="portrait", dpi=600.0)))
    out.append(("template_falsy_overrides", py_templates.instantiate_template(
        "heatmap", title="", paper_size="", orientation="", dpi=0.0)))
    return out


# ---------------------------------------------------------------------------
# Fixture assembly
# ---------------------------------------------------------------------------

def doc_payload(doc):
    """MapCompositionDocument.to_dict() (the C++ parse_composition input)."""
    return doc.to_dict()


def build_fixture():
    fixture = {
        "schema": SCHEMA,
        "generator": "tools/oracle/generate_composer_fixtures.py",
        "python_source": {
            "renderer": "paleo_workbench/mapping/composer/renderer.py",
            "templates": "paleo_workbench/mapping/composer/templates.py",
            "export": "paleo_workbench/mapping/composer/export.py",
        },
        "normalisation": {
            "cbar_\\d+": "cbar_H",
            "grad_(\\d+)_\\d+": "grad_\\1_H",
            "lith_\\d+": "lith_H",
        },
        "templates": [],
        "render_cases": [],
        "export_cases": [],
    }

    # Templates: the frozen library + the materialised document.
    for template in py_templates.TEMPLATE_LIBRARY.values():
        fixture["templates"].append({
            "template_id": template.template_id,
            "category": template.category,
            "label": template.label,
            "description": template.description,
            "paper_size": template.paper_size,
            "orientation": template.orientation,
            "style_bindings": dict(template.style_bindings),
            "data_bindings": dict(template.data_bindings),
            "element_definitions": [
                {
                    "element_type": d.element_type.value
                    if hasattr(d.element_type, "value") else str(d.element_type),
                    "x_mm": d.x_mm, "y_mm": d.y_mm,
                    "width_mm": d.width_mm, "height_mm": d.height_mm,
                    "z_index": d.z_index,
                    "properties": dict(d.properties),
                }
                for d in template.element_definitions
            ],
        })
    for name, doc in template_docs():
        fixture["templates"].append({
            "template_id": name,
            "doc": doc_payload(doc),
            "doc_title": doc.title,
            "paper_size": doc.paper_size,
            "orientation": doc.orientation,
            "width_mm": doc.width_mm,
            "height_mm": doc.height_mm,
            "dpi": doc.dpi,
            "metadata": dict(doc.metadata),
        })

    # Render cases. Every document is round-tripped through
    # to_dict → from_dict first: a persisted composition (the shape the C++
    # kernel parses) always carries float geometry (models.to_dict coerces
    # float(...)), so the frozen SVG reflects the wire form, not the
    # in-memory int literals the corpus was built with.
    cases = []
    cases.append(("all_elements", element_corpus()))
    cases.extend(chart_corpus())
    cases.extend(dict_layer_corpus())
    cases.extend(misc_corpus())
    for name, doc in cases:
        doc = py_models.MapCompositionDocument.from_dict(doc.to_dict())
        svg = normalise(py_renderer.composer_renderer.render_to_svg(doc))
        fixture["render_cases"].append({
            "name": name,
            "doc": doc_payload(doc),
            "svg": svg,
            "sha256": sha256(svg),
        })

    # Export cases: the physical-size re-anchored SVG (export.py
    # _composition_svg) for a template document and the all-elements corpus.
    for name, doc in [
        ("export_template", py_templates.instantiate_template("comprehensive")),
        ("export_all_elements", element_corpus()),
    ]:
        doc = py_models.MapCompositionDocument.from_dict(doc.to_dict())
        physical = normalise(py_export._composition_svg(doc))
        fixture["export_cases"].append({
            "name": name,
            "doc": doc_payload(doc),
            "physical_svg": physical,
            "sha256": sha256(physical),
            "page_pixels_96": list(py_export.composition_page_pixels(doc, 96.0)),
            "page_pixels_300": list(py_export.composition_page_pixels(doc, 300.0)),
        })

    # Palette stops the C++ test injects through the palette seam so the
    # named-ramp colorbar case renders identically to Python.
    fixture["palettes"] = {}
    for ramp_name in ("viridis", "paleogeographic-v1", "lithofacies-v1"):
        ramp = py_registry.resolve_palette(ramp_name)
        fixture["palettes"][ramp_name] = {
            "name": ramp.name,
            "stops": [[float(s.position), str(s.color)] for s in ramp.stops],
        }
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true",
                        help="fail when the fixture on disk differs")
    args = parser.parse_args()

    fixture = build_fixture()
    text = json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        with open(args.out, encoding="utf-8") as handle:
            existing = handle.read()
        if existing != text:
            print("composer oracle fixture is stale — regenerate with "
                  "tools/oracle/generate_composer_fixtures.py", file=sys.stderr)
            return 1
        print("composer oracle fixture up to date (%d render cases)" %
              len(fixture["render_cases"]))
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print("wrote %s (%d templates, %d render cases, %d export cases)" %
          (args.out, len(fixture["templates"]), len(fixture["render_cases"]),
           len(fixture["export_cases"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
