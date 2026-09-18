#!/usr/bin/env python3
"""Oracle fixture generator for the layout-export behavior kernel (CONV-27).

Imports the REAL Python product code (paleo_workbench.mapping.layout_export,
paleo_workbench.mapping.composer.models) and freezes:

* layout specs produced by the real ``build_layout_spec`` (item wire dicts,
  warnings, fail-closed ValueError messages) — ``expectation_source:
  "python-product"``;
* ``hybrid_element_types`` classifications under mirror descriptions;
* ``export_composition_reported`` reports driven by a fake stack (the same
  duck type tests/test_layout_export_mapping.py uses). Cases where the C++
  chain deliberately deviates (no composer SVG fallback, D-03) freeze the
  Python report PLUS an explicit ``cpp_policy`` block; every other report
  field is parity-frozen;
* ``check_pixel_budget`` messages (exact %g / str(float) formatting);
* screen/export parity expectations — the parity comparer is new C++
  surface Python does not define, so expectations come from an independent
  (deliberately naive) reimplementation of the documented contract here —
  ``expectation_source: "cpp-contract"``;
* a negative self-check payload (a corrupted expectation the C++ replay
  must NOT accept).

North-arrow ``svg_path`` values are machine-specific temp paths; both the
generator and the C++ replay neutralise them to ``<NORTH_ARROW_SVG>``.

Regenerate with the oracle venv:
    /home/kevin/project/oracle-venvs/conv12/bin/python \
        tools/oracle/generate_layout_export_fixtures.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.mapping.composer.models import (  # noqa: E402
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.layout_export import (  # noqa: E402
    _check_pixel_budget,
    build_layout_spec,
    export_composition_reported,
    hybrid_element_types,
)

OUT = REPO_ROOT / "libs/layout_export/layout_export_tests/fixtures/layout_export_oracle.json"

SVG_MARKER = "<NORTH_ARROW_SVG>"
REPORT_PATH_MARKER = "<REPORT_PATH>"


class _FakeLayer:
    def __init__(self, layer_id, layer_type, style=None):
        self.id = layer_id
        self.name = layer_id
        self.layer_type = layer_type
        self.style = style or {}


class _FakeSnapshot:
    """Duck-typed render snapshot (the shape Python's gate code expects)."""

    def __init__(self, layers):
        self.project_crs = "EPSG:4326"
        self.layers = tuple(layers)


class _FakeStack:
    """Duck-typed QgisMapStack: records the spec, reports success."""

    def __init__(self, fail=False):
        self.spec = None
        self._fail = fail

    def layout_export(self, spec_json, path, fmt, dpi):
        if self._fail:
            raise RuntimeError("boom")
        self.spec = json.loads(spec_json)
        return json.dumps({"ok": True, "items": len(self.spec["items"])})


def _el(elem_id, elem_type, x, y, w, h, z=0, visible=True, props=None):
    return ComposerElement(
        elem_id, elem_type, x, y, w, h,
        z_index=z, visible=visible, properties=dict(props or {}),
    )


def _base_composition(*elements):
    doc = MapCompositionDocument(id="comp_oracle", title="oracle")
    doc.add_element(_el("el_map", ElementType.MAIN_MAP, 8.0, 12.0, 180.0, 150.0))
    for element in elements:
        doc.add_element(element)
    return doc


def _neutralize(payload):
    """Replace machine-specific north-arrow temp paths with a marker."""
    if isinstance(payload, dict):
        return {
            key: (SVG_MARKER if key == "svg_path" and isinstance(value, str)
                  else _neutralize(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_neutralize(item) for item in payload]
    return payload


def _dump_composition(doc):
    return doc.to_dict()


EXTENT = (0.0, 0.0, 10.0, 9.0)


def _mirror_json(layers):
    """Canonical JSON wire shape for a mirror description."""
    return list(layers)


def _snapshot(layers):
    return _FakeSnapshot([
        _FakeLayer(entry["id"], entry["layer_type"], entry.get("style"))
        for entry in layers
    ])


def _wire_composition(doc):
    """Freeze the JSON-wire form: from_dict(to_dict(doc)) applies Python's
    falsy coercions (e.g. width_mm=0.0 → 1.0), which is exactly the input
    the C++ kernel consumes through parse_composition."""
    return MapCompositionDocument.from_dict(doc.to_dict())


def run_spec_case(case_id, composition, *, map_extent=EXTENT, crs="EPSG:4326",
                  mirror_layers=None):
    composition = _wire_composition(composition)
    warnings_out = []
    entry = {
        "id": case_id,
        "expectation_source": "python-product",
        "input": {
            "composition": _dump_composition(composition),
            "map_extent": [float(v) for v in map_extent],
            "crs": crs,
            "mirror_layers": _mirror_json(mirror_layers) if mirror_layers is not None else None,
        },
    }
    try:
        spec = build_layout_spec(
            composition,
            map_extent=map_extent,
            crs=crs,
            warnings=warnings_out,
            mirror_layers=_snapshot(mirror_layers) if mirror_layers is not None else None,
        )
        # Determinism probe on the Python side: the frozen expectation must
        # be stable across repeated builds.
        again = build_layout_spec(
            composition,
            map_extent=map_extent,
            crs=crs,
            warnings=list(warnings_out),
            mirror_layers=_snapshot(mirror_layers) if mirror_layers is not None else None,
        )
        assert spec == again, f"{case_id}: python build_layout_spec not deterministic"
        entry["cpp_expected"] = {
            "error": None,
            "spec": _neutralize(json.loads(json.dumps(spec, ensure_ascii=False))),
            "warnings": warnings_out,
        }
    except ValueError as exc:
        entry["cpp_expected"] = {"error": str(exc), "spec": None, "warnings": warnings_out}
    return entry


def spec_cases():
    cases = []

    # 1 — kitchen sink: every native element type on one page.
    doc = _base_composition(
        _el("el_title", ElementType.TITLE, 60.0, 3.0, 180.0, 8.0,
            props={"text": "古地理图", "font_size": 14, "align": "center"}),
        _el("el_subtitle", ElementType.SUBTITLE, 60.0, 11.0, 180.0, 6.0,
            props={"text": "早三叠世", "font_size": 10}),
        _el("el_legend", ElementType.LEGEND, 195.0, 12.0, 90.0, 60.0,
            props={"items": []}),
        _el("el_scale", ElementType.SCALE_BAR, 30.0, 168.0, 40.0, 8.0,
            props={"units": "km", "length_km": 50}),
        _el("el_arrow", ElementType.NORTH_ARROW, 250.0, 168.0, 12.0, 18.0,
            props={"label": "N"}),
        _el("el_neat", ElementType.NEATLINE, 2.0, 2.0, 293.0, 206.0,
            props={"line_width_mm": 0.6}),
        _el("el_note", ElementType.TEXT, 100.0, 180.0, 120.0, 10.0,
            props={"text": "备注: 合成用例", "color": "#333333"}),
        _el("el_ann", ElementType.ANNOTATION, 150.0, 100.0, 40.0, 8.0,
            props={"text": "①", "leader": True}),
        _el("el_src", ElementType.DATASOURCE, 8.0, 190.0, 150.0, 8.0,
            props={"title": "数据来源", "text": "1:20万地质图"}),
        _el("el_cred", ElementType.TIME_CREDITS, 8.0, 196.0, 150.0, 6.0,
            props={"text": "2026-09"}),
        _el("el_strat", ElementType.STRAT_LABELS, 160.0, 190.0, 60.0, 8.0,
            props={"text": "T1y"}),
        _el("el_meta", ElementType.METADATA, 160.0, 196.0, 80.0, 10.0,
            props={"fields": {"作者": "李白", "scale": 2, "ratio": 1.5,
                              "verified": True, "note": None},
                   "font_size": 6}),
        _el("el_img", ElementType.IMAGE, 200.0, 80.0, 40.0, 30.0,
            props={"image_path": "/assets/logo.svg", "fit": "contain"}),
    )
    cases.append(run_spec_case("native_full", doc))

    # 2 — empty composition: page with zero items, no error.
    cases.append(run_spec_case(
        "empty_composition", MapCompositionDocument(id="comp_empty", title="e")))

    # 3 — invisible elements are skipped entirely.
    doc = _base_composition(
        _el("el_hidden_title", ElementType.TITLE, 10.0, 2.0, 60.0, 8.0,
            visible=False, props={"text": "hidden"}),
        _el("el_seen", ElementType.TEXT, 10.0, 170.0, 60.0, 8.0,
            props={"text": "seen"}),
    )
    cases.append(run_spec_case("invisible_skipped", doc))

    # 4 — stable z-order: equal z_index keeps insertion order; negative and
    # large z values interleave.
    doc = MapCompositionDocument(id="comp_z", title="z")
    doc.add_element(_el("el_map", ElementType.MAIN_MAP, 8.0, 12.0, 180.0, 150.0))
    doc.add_element(_el("el_b", ElementType.TITLE, 0.0, 0.0, 50.0, 6.0, z=5,
                        props={"text": "B"}))
    doc.add_element(_el("el_a", ElementType.TITLE, 0.0, 0.0, 50.0, 6.0, z=5,
                        props={"text": "A"}))
    doc.add_element(_el("el_c", ElementType.TITLE, 0.0, 0.0, 50.0, 6.0, z=-3,
                        props={"text": "C"}))
    doc.add_element(_el("el_d", ElementType.TITLE, 0.0, 0.0, 50.0, 6.0, z=10 ** 9,
                        props={"text": "D"}))
    cases.append(run_spec_case("zorder_stable_ties", doc))

    # 5 — Unicode titles/colors end to end.
    doc = _base_composition(
        _el("el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0,
            props={"title": "砂地比", "units": "％", "min": 0.0, "max": 1.0}),
    )
    cases.append(run_spec_case(
        "unicode_colorbar", doc,
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))

    # 6-8 — colorbar gates and title/units rendering.
    def _colorbar(units=None, title="砂地比"):
        props = {"title": title, "min": 0.0, "max": 1.0}
        if units is not None:
            props["units"] = units
        return _el("el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0,
                   props=props)

    cases.append(run_spec_case(
        "colorbar_scalar_mirror", _base_composition(_colorbar("%")),
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))
    cases.append(run_spec_case(
        "colorbar_units_empty", _base_composition(_colorbar("")),
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))
    cases.append(run_spec_case(
        "colorbar_units_spaces", _base_composition(_colorbar("   ")),
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))
    cases.append(run_spec_case(
        "colorbar_units_missing", _base_composition(_colorbar()),
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))
    cases.append(run_spec_case(
        "colorbar_default_title", _base_composition(
            _el("el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0)),
        mirror_layers=[{"id": "grid1", "layer_type": "scalar_grid"}]))
    cases.append(run_spec_case(
        "colorbar_unproven", _base_composition(_colorbar("%")),
        mirror_layers=[{"id": "v1", "layer_type": "vector"}]))
    cases.append(run_spec_case(
        "colorbar_no_mirror", _base_composition(_colorbar("%"))))

    # plain-array mirror (no snapshot wrapper) proves the same.
    cases.append({
        "id": "colorbar_plain_array_mirror",
        "expectation_source": "python-product",
        "input": {
            "composition": _dump_composition(_base_composition(_colorbar("%"))),
            "map_extent": [float(v) for v in EXTENT],
            "crs": "EPSG:4326",
            "mirror_layers": [{"id": "g", "layer_type": "scalar_grid"}],
        },
    })
    cases[-1]["cpp_expected"] = _plain_array_expectation(cases[-1])

    # 9-11 — facies legend gates.
    facies = _el("el_fl", ElementType.FACIES_LEGEND, 205.0, 95.0, 78.0, 60.0,
                 props={"title": "沉积相图例"})
    cases.append(run_spec_case(
        "facies_polygon_mirror", _base_composition(facies),
        mirror_layers=[{"id": "fac1", "layer_type": "polygon"}]))
    cases.append(run_spec_case(
        "facies_categorized_vector_mirror", _base_composition(facies),
        mirror_layers=[{"id": "v1", "layer_type": "vector",
                        "style": {"renderer": "categorized",
                                  "field": "facies"}}]))
    cases.append(run_spec_case(
        "facies_uncategorized_vector_unproven", _base_composition(facies),
        mirror_layers=[{"id": "v1", "layer_type": "vector",
                        "style": {"renderer": "single"}}]))
    cases.append(run_spec_case(
        "facies_facies_kind_mirror", _base_composition(facies),
        mirror_layers=[{"id": "f2", "layer_type": "facies"}]))

    # 12-13 — well legend gates.
    well = _el("el_wl", ElementType.WELL_LEGEND, 205.0, 160.0, 70.0, 40.0,
               props={"title": "测井图例", "items": []})
    cases.append(run_spec_case(
        "well_point_mirror", _base_composition(well),
        mirror_layers=[{"id": "w1", "layer_type": "well_point"}]))
    cases.append(run_spec_case(
        "well_kind_mirror", _base_composition(well),
        mirror_layers=[{"id": "w2", "layer_type": "well"}]))
    cases.append(run_spec_case(
        "well_unproven", _base_composition(well)))

    # 14 — plain legend keeps w/h and auto-size.
    cases.append(run_spec_case(
        "plain_legend_keeps_box", _base_composition(
            _el("el_legend", ElementType.LEGEND, 195.0, 12.0, 90.0, 60.0))))

    # 15-17 — hybrid fail-closed messages.
    cases.append(run_spec_case(
        "hybrid_single", _base_composition(
            _el("el_chart", ElementType.STAT_CHART, 205.0, 30.0, 75.0, 55.0))))
    cases.append(run_spec_case(
        "hybrid_multi_sorted", _base_composition(
            _el("el_ts", ElementType.TIMESCALE, 15.0, 175.0, 180.0, 12.0),
            _el("el_chart", ElementType.STAT_CHART, 205.0, 30.0, 75.0, 55.0),
            _el("el_inset", ElementType.INSET_MAP, 200.0, 150.0, 80.0, 40.0),
            _el("el_prof", ElementType.PROFILE, 10.0, 160.0, 120.0, 30.0),
            _el("el_fault", ElementType.FAULT_SYMBOLS, 10.0, 20.0, 40.0, 30.0),
            _el("el_lith", ElementType.LITHOLOGY_LEGEND, 240.0, 20.0, 40.0, 60.0))))

    # 18 — forward-compat TEXT carrier renders as a label (marker ignored).
    doc = _base_composition(
        _el("el_future", ElementType.TEXT, 10.0, 160.0, 60.0, 10.0,
            props={"_raw_element_type": "future_widget", "text": "carried"}))
    cases.append(run_spec_case("carried_text_label", doc))

    # 19-21 — metadata text rendering (ordered fields, type-shaped str()).
    cases.append(run_spec_case(
        "metadata_fields", _base_composition(
            _el("el_meta", ElementType.METADATA, 160.0, 196.0, 80.0, 10.0,
                props={"fields": {"作者": "李白", "scale": 2, "ratio": 1.5,
                                  "verified": True, "note": None}}))))
    cases.append(run_spec_case(
        "metadata_no_fields", _base_composition(
            _el("el_meta", ElementType.METADATA, 160.0, 196.0, 80.0, 10.0,
                props={"text": "fallback text", "fields": "not-a-mapping"}))))
    cases.append(run_spec_case(
        "metadata_empty_fields", _base_composition(
            _el("el_meta", ElementType.METADATA, 160.0, 196.0, 80.0, 10.0,
                props={"fields": {}}))))

    # 22-26 — grid folding.
    cases.append(run_spec_case(
        "grid_converts_to_map_units", _base_composition(
            _el("el_grid", ElementType.GRID, 8.0, 12.0, 180.0, 150.0,
                props={"spacing_mm": 12}))))
    cases.append(run_spec_case(
        "grid_default_spacing", _base_composition(
            _el("el_grid", ElementType.GRID, 8.0, 12.0, 180.0, 150.0))))
    cases.append(run_spec_case(
        "grid_zero_spacing_uses_default", _base_composition(
            _el("el_grid", ElementType.GRID, 8.0, 12.0, 180.0, 150.0,
                props={"spacing_mm": 0}))))
    cases.append(run_spec_case(
        "grid_without_main_map_warns", MapCompositionDocument(
            id="comp_nomap", title="n",
            elements=[_el("el_grid", ElementType.GRID, 0.0, 0.0, 10.0, 10.0)])))
    cases.append(run_spec_case(
        "grid_last_wins", _base_composition(
            _el("el_g1", ElementType.GRID, 8.0, 12.0, 180.0, 150.0,
                props={"spacing_mm": 5}),
            _el("el_g2", ElementType.GRID, 8.0, 12.0, 180.0, 150.0,
                props={"spacing_mm": 20}))))
    cases.append(run_spec_case(
        "grid_float_spacing", _base_composition(
            _el("el_grid", ElementType.GRID, 8.0, 12.0, 180.0, 150.0,
                props={"spacing_mm": 2.5})),
        map_extent=(100.0, 0.0, 110.0, 9.0)))

    # 27-28 — fail-closed geometry and image validation.
    # Zero width is truthy-coerced to the 1.0 default by the document
    # parser on BOTH runtimes, so it never reaches the builder; a negative
    # extent survives parsing and is rejected fail-closed.
    cases.append(run_spec_case(
        "zero_width_coerced_by_parse", _base_composition(
            _el("el_bad", ElementType.TITLE, 10.0, 10.0, 0.0, 8.0,
                props={"text": "x"}))))
    cases.append(run_spec_case(
        "negative_height_element", _base_composition(
            _el("el_bad", ElementType.TEXT, 10.0, 10.0, 50.0, -1.0))))
    cases.append(run_spec_case(
        "image_missing_path", _base_composition(
            _el("el_img", ElementType.IMAGE, 10.0, 10.0, 40.0, 30.0))))
    cases.append(run_spec_case(
        "image_embedded_data", _base_composition(
            _el("el_img", ElementType.IMAGE, 10.0, 10.0, 40.0, 30.0,
                props={"image_data_png_b64": "aGk="}))))

    # 29 — crs None → "".
    cases.append(run_spec_case(
        "crs_null", _base_composition(), crs=None))

    # 30 — boundary coordinates.
    cases.append(run_spec_case(
        "boundary_coords", _base_composition(
            _el("el_t", ElementType.TEXT, 0.0, 0.0, 0.5, 0.5,
                props={"text": "corner"}),
            _el("el_t2", ElementType.TEXT, -12.5, -3.25, 10.0, 10.0,
                props={"text": "outside"})),
        map_extent=(-15.0, -5.0, 15.0, 12.0)))

    # 31 — scalebar variants.
    cases.append(run_spec_case(
        "scalebar_units_missing", _base_composition(
            _el("el_scale", ElementType.SCALE_BAR, 30.0, 168.0, 40.0, 8.0))))
    cases.append(run_spec_case(
        "scalebar_unicode_units", _base_composition(
            _el("el_scale", ElementType.SCALE_BAR, 30.0, 168.0, 40.0, 8.0,
                props={"units": "米"}))))

    return cases


def _plain_array_expectation(entry):
    """Run the plain-array-mirror case through the real builder."""
    composition = MapCompositionDocument.from_dict(entry["input"]["composition"])
    warnings_out = []
    try:
        spec = build_layout_spec(
            composition,
            map_extent=tuple(entry["input"]["map_extent"]),
            crs=entry["input"]["crs"],
            warnings=warnings_out,
            mirror_layers=entry["input"]["mirror_layers"],  # bare list
        )
        return {"error": None,
                "spec": _neutralize(json.loads(json.dumps(spec, ensure_ascii=False))),
                "warnings": warnings_out}
    except ValueError as exc:
        return {"error": str(exc), "spec": None, "warnings": warnings_out}


def hybrid_cases():
    cases = []
    doc = _base_composition(
        _el("el_ts", ElementType.TIMESCALE, 15.0, 175.0, 180.0, 12.0),
        _el("el_ts2", ElementType.TIMESCALE, 15.0, 188.0, 180.0, 10.0),
        _el("el_chart", ElementType.STAT_CHART, 205.0, 30.0, 75.0, 55.0))
    for case_id, mirror in (
        ("hybrid_types_no_mirror", None),
        ("hybrid_types_all_proven", [{"id": "grid1", "layer_type": "scalar_grid"},
                                     {"id": "w1", "layer_type": "well_point"},
                                     {"id": "f1", "layer_type": "polygon"}]),
    ):
        cases.append({
            "id": case_id,
            "expectation_source": "python-product",
            "input": {
                "composition": _dump_composition(doc),
                "mirror_layers": _mirror_json(mirror) if mirror is not None else None,
            },
            "cpp_expected": hybrid_element_types(
                doc, mirror_layers=_snapshot(mirror) if mirror is not None else None),
        })
    empty = MapCompositionDocument(id="comp_none", title="none")
    cases.append({
        "id": "hybrid_types_empty",
        "expectation_source": "python-product",
        "input": {"composition": _dump_composition(empty), "mirror_layers": None},
        "cpp_expected": hybrid_element_types(empty),
    })
    return cases


def report_cases():
    cases = []

    def _run(case_id, composition, *, fmt="pdf", dpi=300.0, map_extent=EXTENT,
             crs="EPSG:4326", stack=True, fail_stack=False, geo_pdf=False,
             mirror_layers=None):
        composition = _wire_composition(composition)
        stack_obj = _FakeStack(fail=fail_stack) if stack else None
        report = export_composition_reported(
            composition, Path(tempfile.mkdtemp()) / "page.out",
            fmt=fmt, dpi=dpi, map_extent=map_extent if map_extent is not None else None,
            crs=crs, stack=stack_obj, geo_pdf=geo_pdf,
            mirror_layers=_snapshot(mirror_layers) if mirror_layers is not None else None,
        )
        payload = report.to_dict()
        # The report path is machine-specific; freeze a marker instead.
        payload["path"] = REPORT_PATH_MARKER
        entry = {
            "id": case_id,
            "expectation_source": "python-product",
            "input": {
                "composition": _dump_composition(composition),
                "fmt": fmt,
                "dpi": dpi,
                "map_extent": ([float(v) for v in map_extent]
                               if map_extent is not None else None),
                "crs": crs,
                "geo_pdf": geo_pdf,
                "executor": ("fail" if fail_stack else "ok") if stack else "none",
                "mirror_layers": (_mirror_json(mirror_layers)
                                  if mirror_layers is not None else None),
            },
            "python_report": payload,
        }
        if stack and stack_obj is not None and stack_obj.spec is not None:
            entry["recorded_geo_pdf"] = stack_obj.spec.get("geo_pdf") is True
        return entry

    native = _base_composition(
        _el("el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0,
            props={"title": "砂地比", "units": "%"}),
        _el("el_title", ElementType.TITLE, 60.0, 3.0, 180.0, 8.0,
            props={"text": "t"}))
    scalar_mirror = [{"id": "grid1", "layer_type": "scalar_grid"}]

    cases.append(_run("report_native_ok", native,
                      mirror_layers=scalar_mirror))
    cases.append(_run("report_geo_pdf_flag", native,
                      mirror_layers=scalar_mirror, geo_pdf=True))
    cases.append(_run("report_svg_format", native, fmt="svg", dpi=96.0,
                      mirror_layers=scalar_mirror))

    hybrid_doc = _base_composition(
        _el("el_ts", ElementType.TIMESCALE, 15.0, 175.0, 180.0, 12.0),
        _el("el_ts2", ElementType.TIMESCALE, 15.0, 188.0, 180.0, 10.0),
        _el("el_chart", ElementType.STAT_CHART, 205.0, 30.0, 75.0, 55.0))
    entry = _run("report_hybrid_no_stack", hybrid_doc, stack=False)
    entry["cpp_policy"] = {
        "engine": "none",
        "ok": False,
        "failure_contains": "fail-closed",
        "note": "D-03: no composer SVG fallback in the native chain",
    }
    cases.append(entry)

    unproven = _base_composition(
        _el("el_cb", ElementType.COLORBAR, 205.0, 30.0, 12.0, 60.0,
            props={"title": "cb", "units": "%"}))
    entry = _run("report_unproven_colorbar_with_stack", unproven,
                 mirror_layers=[])
    entry["cpp_policy"] = {
        "engine": "none",
        "ok": False,
        "failure_contains": "no native layout counterpart",
        "note": "D-03: fail-closed instead of the composer fallback page",
    }
    cases.append(entry)

    subtitle = _base_composition(
        _el("el_sub", ElementType.SUBTITLE, 60.0, 8.0, 120.0, 6.0,
            props={"text": "T1"}))
    entry = _run("report_runtime_failure", subtitle, fail_stack=True)
    entry["cpp_policy"] = {
        "engine": "qgis_layout",
        "ok": False,
        "failure_contains": "boom",
        "note": "D-03: executor failure is the report, no fallback engine",
    }
    cases.append(entry)

    entry = _run("report_no_extent", subtitle, map_extent=None)
    entry["cpp_policy"] = {
        "engine": "none",
        "ok": False,
        "failure_contains": "no map extent provided",
        "note": "D-03: fail-closed instead of the composer fallback page",
    }
    cases.append(entry)

    entry = _run("report_no_stack", subtitle, stack=False)
    entry["cpp_policy"] = {
        "engine": "none",
        "ok": False,
        "failure_contains": "no native layout executor available",
        "note": "D-03: fail-closed instead of the composer fallback page",
    }
    cases.append(entry)

    return cases


def budget_cases():
    def _try(case_id, width_mm, height_mm, dpi):
        doc = MapCompositionDocument(id="comp_b", title="b", width_mm=width_mm,
                                     height_mm=height_mm)
        entry = {
            "id": case_id,
            "expectation_source": "python-product",
            "input": {"width_mm": width_mm, "height_mm": height_mm, "dpi": dpi},
        }
        try:
            # Real product path: export_composition_reported raises before
            # anything else, via its module-level budget check.
            _check_pixel_budget(doc, dpi)
            entry["cpp_expected"] = {"error": None}
        except ValueError as exc:
            entry["cpp_expected"] = {"error": str(exc)}
        return entry

    return [
        _try("budget_a0_600_over", 841.0, 1189.0, 600.0),
        _try("budget_a4_300_ok", 297.0, 210.0, 300.0),
        _try("budget_a1_300_over", 594.0, 841.0, 300.0),
        _try("budget_fractional_dpi", 841.0, 1189.0, 599.5),
    ]


# ---------------------------------------------------------------------------
# Parity contract (new C++ surface; independent naive reimplementation)
# ---------------------------------------------------------------------------

def _close(a, b):
    return abs(a - b) <= 1e-9 + 1e-9 * max(abs(a), abs(b))


def _parity_expected(canvas, export):
    aspects = {}
    diffs = []
    ce = canvas.get("extent")
    ee = export.get("extent")
    extent_ok = (isinstance(ce, list) and isinstance(ee, list)
                 and len(ce) == 4 and len(ee) == 4
                 and all(_close(float(a), float(b)) for a, b in zip(ce, ee)))
    aspects["extent"] = extent_ok
    if not extent_ok:
        diffs.append("extent")
    aspects["crs"] = canvas.get("crs") == export.get("crs")
    if not aspects["crs"]:
        diffs.append("crs")

    def _visible(state):
        return [entry["id"] for entry in state.get("layers", [])
                if entry.get("visible", True)]

    def _hidden(state):
        return {entry["id"] for entry in state.get("layers", [])
                if not entry.get("visible", True)}

    aspects["layer_order"] = _visible(canvas) == _visible(export)
    if not aspects["layer_order"]:
        diffs.append("layer_order")
    aspects["visibility"] = _hidden(canvas) == _hidden(export)
    if not aspects["visibility"]:
        diffs.append("visibility")
    cg = canvas.get("grid") or {}
    eg = export.get("grid") or {}
    aspects["grid"] = (
        bool(cg.get("enabled")) == bool(eg.get("enabled"))
        and _close(float(cg.get("interval_x", 0.0)), float(eg.get("interval_x", 0.0)))
        and _close(float(cg.get("interval_y", 0.0)), float(eg.get("interval_y", 0.0)))
        if (cg or eg) else True)
    if (cg or eg) and not aspects["grid"]:
        diffs.append("grid")
    aspects["legend"] = bool(canvas.get("legend")) == bool(export.get("legend"))
    if not aspects["legend"]:
        diffs.append("legend")
    return {
        "equal": all(aspects.values()),
        "aspects": {key: {"equal": value} for key, value in aspects.items()},
        "diff_count": len(diffs),
        "style_source": "shared_qgis_project_layers",
        "by_construction": ["style", "annotations"],
    }


def parity_cases():
    base_layers = [{"id": "a", "visible": True}, {"id": "b", "visible": True}]
    canvas = {"extent": [0.0, 0.0, 10.0, 9.0], "crs": "EPSG:4326",
              "layers": base_layers,
              "grid": {"enabled": True, "interval_x": 0.5, "interval_y": 0.5},
              "legend": True}
    export_equal = {"extent": [0.0, 0.0, 10.0, 9.0], "crs": "EPSG:4326",
                    "layers": [{"id": "a", "visible": True},
                               {"id": "b", "visible": True}],
                    "grid": {"enabled": True, "interval_x": 0.5,
                             "interval_y": 0.5},
                    "legend": True}
    cases = [("parity_equal", canvas, export_equal)]

    extent_shift = copy.deepcopy(export_equal)
    extent_shift["extent"] = [0.0, 0.0, 10.5, 9.0]
    cases.append(("parity_extent_diff", canvas, extent_shift))

    order_diff = copy.deepcopy(export_equal)
    order_diff["layers"] = [{"id": "b", "visible": True},
                            {"id": "a", "visible": True}]
    cases.append(("parity_order_diff", canvas, order_diff))

    visibility_diff = copy.deepcopy(export_equal)
    visibility_diff["layers"] = [{"id": "a", "visible": True},
                                 {"id": "b", "visible": False}]
    cases.append(("parity_visibility_diff", canvas, visibility_diff))

    crs_diff = copy.deepcopy(export_equal)
    crs_diff["crs"] = "EPSG:4490"
    cases.append(("parity_crs_diff", canvas, crs_diff))

    grid_diff = copy.deepcopy(export_equal)
    grid_diff["grid"] = {"enabled": True, "interval_x": 1.0, "interval_y": 1.0}
    cases.append(("parity_grid_diff", canvas, grid_diff))

    legend_diff = copy.deepcopy(export_equal)
    legend_diff["legend"] = False
    cases.append(("parity_legend_diff", canvas, legend_diff))

    tolerance = copy.deepcopy(export_equal)
    tolerance["extent"] = [0.0 + 1e-12, 0.0, 10.0, 9.0]
    cases.append(("parity_tolerance_equal", canvas, tolerance))

    malformed = {"crs": "EPSG:4326", "layers": [], "legend": False}
    cases.append(("parity_malformed_extent", malformed, export_equal))

    return [
        {
            "id": case_id,
            "expectation_source": "cpp-contract",
            "input": {"canvas_state": canvas_state, "export_state": export_state},
            "cpp_expected": _parity_expected(canvas_state, export_state),
        }
        for case_id, canvas_state, export_state in cases
    ]


def _ensure_qt_app():
    """The composer-fallback path renders real PNG/PDF pages (Qt fonts), so
    the generator needs an offscreen QGuiApplication like the pytest
    conftest provides."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return None
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(["generate_layout_export_fixtures"])
    return app


def main():
    _ensure_qt_app()
    fixture = {
        "generator": "tools/oracle/generate_layout_export_fixtures.py",
        "note": "Frozen from the real Python product code; regenerate only "
                "with the oracle venv. svg_path values are neutralised to "
                "<NORTH_ARROW_SVG> on both sides.",
        "spec_cases": spec_cases(),
        "hybrid_cases": hybrid_cases(),
        "report_cases": report_cases(),
        "budget_cases": budget_cases(),
        "parity_cases": parity_cases(),
        "self_check": {
            "note": "The replay must REJECT this corrupted expectation "
                    "(comparator negative self-check).",
            "spec_case_id": "native_full",
            "corrupt": {"path": ["items", 0, "x"], "value": 999.0},
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} "
          f"({len(fixture['spec_cases'])} spec, "
          f"{len(fixture['hybrid_cases'])} hybrid, "
          f"{len(fixture['report_cases'])} report, "
          f"{len(fixture['budget_cases'])} budget, "
          f"{len(fixture['parity_cases'])} parity cases)")


if __name__ == "__main__":
    main()
