#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-27 cartography slice.

Imports the REAL implementations (paleo_workbench.mapping.color_ramps /
map_styles / scalar_style / geological_symbols / geological_style_library /
qgis_style, composer templates via geological_pipeline.templates and the
map_render_backend flatten helper) and freezes their JSON contracts so the
C++ port in libs/cartography can be verified sample-exactly:

  * color_ramps    — 11 builtin ramp documents + evaluate grids (normal,
                     boundary, non-finite, degenerate span) + sample tables
                     + tolerant from_dict;
  * map_styles     — 8 preset documents, tolerant from_dict cases,
                     default_style_for kinds, dash_pattern table;
  * scalar_style   — spec documents + validation errors + equal_interval /
                     quantile / natural_breaks (incl. the numpy RNG sample
                     draw) + ramp items (continuous/classified/reverse);
  * geological_symbols — the whole-library document, binding records,
                     validate_binding matrix, legacy style overrides, alias
                     resolution, library schema errors;
  * style_library  — the 12-entry V1 document, lookups, apply semantics;
  * templates      — the factor-map composition dumps (landscape/portrait,
                     title fallbacks, degenerate extents);
  * qgis_style     — payload round-trips + invalid payloads;
  * flatten_qgis   — _flatten_qgis_style promotion + unit conversions.

Regenerate with:

    python3 tools/oracle/generate_cartography_fixtures.py

Requires numpy (scalar_style) and PySide6 (templates -> layers ->
map_render_backend import chain) but NOT the qgis_render_bridge (no QGIS
XML path is frozen here — that half is already C++ in the bridge).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.mapping import color_ramps as cr  # noqa: E402
from paleo_workbench.mapping import geological_style_library as gsl  # noqa: E402
from paleo_workbench.mapping import geological_symbols as gs  # noqa: E402
from paleo_workbench.mapping import map_styles as ms  # noqa: E402
from paleo_workbench.mapping import qgis_style as qs  # noqa: E402
from paleo_workbench.mapping import scalar_style as ss  # noqa: E402
from paleo_workbench.mapping.geological_pipeline import templates as tp  # noqa: E402
from paleo_workbench.mapping.layers import MapDocument  # noqa: E402
from paleo_workbench.mapping.map_render_backend import _flatten_qgis_style  # noqa: E402

OUT_DIR = (
    REPO_ROOT / "libs" / "cartography" / "cartography_tests" / "fixtures"
)


def sanitize(value):
    """Deep-convert non-finite floats to JSON-safe string tags."""
    if isinstance(value, float):
        return encode_float(value)
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def dump(name: str, payload) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(
        json.dumps(sanitize(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def error_of(fn, *args, **kwargs):
    """Run fn and freeze the failure as {error: type, message: str}."""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - oracle freeze
        # KeyError.__str__ wraps the message in repr quotes; freeze the raw
        # message so the C++ side compares against the same content.
        message = exc.args[0] if isinstance(exc, KeyError) else str(exc)
        return {"error": type(exc).__name__, "message": message}
    return {"error": None}


def encode_float(value: float):
    """JSON-safe float: standard JSON has no NaN/Infinity tokens."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def decode_float(value):
    """The C++ counterpart of encode_float (test-side helper mirror)."""
    return value


# ---------------------------------------------------------------------------
# 1. color_ramps
# ---------------------------------------------------------------------------


def case_color_ramps() -> dict:
    cases = {}
    # Ramp documents in registry order.
    cases["builtin_documents"] = {
        name: cr.get_color_ramp(name).to_dict()
        for name in cr.list_color_ramps()
    }
    cases["list_ramps"] = cr.list_color_ramps()

    # evaluate grids: 21 points + boundaries + non-finite for every ramp.
    evaluate = {}
    ts = [i / 20 for i in range(21)]
    ts += [0.0, 1.0, -0.25, 1.5, float("nan"), float("inf"), float("-inf")]
    ts_encoded = [encode_float(t) for t in ts]
    for name in cr.list_color_ramps():
        ramp = cr.get_color_ramp(name)
        evaluate[name] = [ramp.evaluate(t) for t in ts]
    cases["evaluate_grid"] = {"ts": ts_encoded, "values": evaluate}

    # evaluate_value: normal, degenerate span, non-finite inputs.
    ramp = cr.get_color_ramp("viridis")
    cases["evaluate_value"] = {
        "normal": ramp.evaluate_value(0.25, 0.0, 100.0),
        "normal_2": ramp.evaluate_value(75.0, 0.0, 100.0),
        "degenerate": ramp.evaluate_value(5.0, 5.0, 5.0),
        "degenerate_close": ramp.evaluate_value(5.0, 5.0, 5.0000000001),
        "nan_value": ramp.evaluate_value(float("nan"), 0.0, 1.0),
        "inf_bounds": ramp.evaluate_value(0.5, float("-inf"), float("inf")),
        "below": ramp.evaluate_value(-10.0, 0.0, 1.0),
        "above": ramp.evaluate_value(2.0, 0.0, 1.0),
    }

    # sample_table sizes (2, 3, 5, 256) on viridis + toc.
    tables = {}
    for name in ("viridis", "toc"):
        tables[name] = {
            str(count): cr.get_color_ramp(name).sample_table(count)
            for count in (2, 3, 5, 256)
        }
    cases["sample_tables"] = tables

    # from_dict tolerance.
    cases["from_dict"] = {
        "valid": cr.ColorRamp.from_dict(
            {
                "name": "Custom",
                "stops": [
                    {"position": 0, "color": "#ff0000"},
                    {"position": 1, "color": "#00ff00"},
                ],
                "nodata_color": "#11223344",
            }
        ).to_dict(),
        "empty_stops": cr.ColorRamp.from_dict({"name": "flat"}).to_dict(),
        "none": cr.ColorRamp.from_dict(None).to_dict(),
        "scalar": cr.ColorRamp.from_dict(42).to_dict(),
        "missing_color": cr.ColorRamp.from_dict(
            {"name": "x", "stops": [{"position": 0.5}]}
        ).to_dict(),
        "falsy_name": cr.ColorRamp.from_dict({"name": "", "stops": []}).to_dict(),
        "unknown_lookup": cr.get_color_ramp("NOPE").to_dict(),
        "uppercase_lookup": cr.get_color_ramp("VIRIDIS").to_dict(),
    }

    # hex parsing edges (via a dedicated probe ramp).
    hexes = [
        "#440154", "440154", "#440154ff", "#abc", "abc", "#ab", "abcdefgh",
        "", "#", "#GGGGGG", "  #3b528b  ", "#21918C", "#5EC96280",
    ]
    probe = cr.ColorRamp(name="probe", stops=tuple(
        cr.ColorStop(0.0, h) for h in hexes
    ) + (cr.ColorStop(1.0, "#440154"),))
    cases["hex_parse"] = [
        {"input": h, "sampled": probe.evaluate(i / (len(hexes)))}
        for i, h in enumerate(hexes)
    ]

    # register + list ordering semantics.
    custom = cr.ColorRamp(
        name="CustomRamp",
        stops=(cr.ColorStop(0.0, "#000000"), cr.ColorStop(1.0, "#ffffff")),
    )
    cr.register_color_ramp(custom)
    cases["register"] = {
        "list_after": cr.list_color_ramps(),
        "lookup_by_lower": cr.get_color_ramp("customramp").to_dict(),
    }
    return cases


# ---------------------------------------------------------------------------
# 2. map_styles
# ---------------------------------------------------------------------------


def case_map_styles() -> dict:
    cases = {}
    cases["presets"] = {
        name: style.to_dict() for name, style in ms.STYLE_LIBRARY.items()
    }
    cases["default_style_for"] = {
        kind: ms.default_style_for(kind).to_dict()
        for kind in (
            "facies", "well", "line", "label", "annotation",
            "grid", "contour", "unknown_kind",
        )
    }
    cases["dash_pattern"] = {
        pattern.value: list(pattern.dash_pattern(1.5))
        for pattern in ms.LinePattern
    }
    cases["vector_style_from_dict"] = {
        "flat": ms.VectorStyle.from_dict(
            {
                "fill": "#101010",
                "stroke": "#eeeeee",
                "stroke_width": "2.5",
                "line_pattern": "fault",
                "marker": "square",
                "marker_size": 9,
                "renderer": "categorized",
                "field": "facies_name",
                "categories": [
                    ["sand", "#f2d38a", "砂岩"],
                    ["mud", "#9aa7b5"],
                ],
                "ranges": [
                    [0, 0.5, "#c9b8d8", "低"],
                    {"min": 0.5, "max": 1.0, "color": "#7fbf9e", "label": "高"},
                    ["bad", "range", "#ffffff"],
                ],
                "fill_patterns": {"sand": "sandstone", "mud": "mudstone"},
                "labels": {"field": "name", "size": "11", "bold": True},
                "unknown_key": {"kept": False},
            }
        ).to_dict(),
        "qgis_map_categories": ms.VectorStyle.from_dict(
            {"categories": {"sand": "#f2d38a", "mud": "#9aa7b5"}}
        ).to_dict(),
        "invalid_numbers": ms.VectorStyle.from_dict(
            {"stroke_width": "abc", "marker_size": None, "fill": ""}
        ).to_dict(),
        "unknown_patterns": ms.VectorStyle.from_dict(
            {"line_pattern": "dotted", "marker": "hexagon"}
        ).to_dict(),
        "not_mapping": ms.VectorStyle.from_dict(None).to_dict(),
        "empty": ms.VectorStyle.from_dict({}).to_dict(),
        "labels_partial": ms.VectorStyle.from_dict(
            {"labels": {"color": None, "size": "bad", "halo_width": 2}}
        ).to_dict(),
    }
    cases["text_style_from_dict"] = ms.TextStyle.from_dict(
        {"field": "well_name", "size": 12, "color": "#000000",
         "bold": 1, "visible": True, "rotation_field": "deg"}
    ).to_dict()
    cases["text_style_default"] = ms.TextStyle().to_dict()
    # style_dict_revision is Python-hash based (process-salted) and thus NOT
    # frozen — the C++ side documents its own stable token (D-6).
    return cases


# ---------------------------------------------------------------------------
# 3. scalar_style
# ---------------------------------------------------------------------------


def _spec_cases() -> dict:
    return {
        "defaults": ss.ScalarStyleSpec().to_dict(),
        "classified_quantile": ss.ScalarStyleSpec(
            ramp_name="porosity",
            mode="classified",
            classification="quantile",
            n_classes=4,
            reverse=True,
            opacity=0.8,
            unit_label="%",
            colorbar_title="孔隙度",
            colorbar_decimals=1,
        ).to_dict(),
        "explicit": ss.ScalarStyleSpec(
            mode="classified",
            classification="explicit",
            explicit_breaks=(0.0, 1.5, 3.0),
            manual_range=(0.0, 3.0),
        ).to_dict(),
    }


def case_scalar_style() -> dict:
    cases = {}
    cases["specs"] = _spec_cases()
    cases["spec_from_dict"] = {
        "roundtrip": ss.ScalarStyleSpec.from_dict(
            ss.ScalarStyleSpec(
                mode="classified",
                classification="natural_breaks",
                n_classes=6,
                reverse=True,
                manual_range=(1.0, 9.0),
            ).to_dict()
        ).to_dict(),
        "minimal": ss.ScalarStyleSpec.from_dict({}).to_dict(),
    }

    validation = {}
    for name, fn in {
        "bad_mode": lambda: ss.ScalarStyleSpec(mode="steps"),
        "bad_classification": lambda: ss.ScalarStyleSpec(classification="jenks"),
        "n_classes_low": lambda: ss.ScalarStyleSpec(n_classes=1),
        "n_classes_high": lambda: ss.ScalarStyleSpec(n_classes=257),
        "opacity": lambda: ss.ScalarStyleSpec(opacity=1.5),
        "manual_range": lambda: ss.ScalarStyleSpec(manual_range=(2.0, 1.0)),
        "explicit_missing": lambda: ss.ScalarStyleSpec(classification="explicit"),
        "explicit_unsorted": lambda: ss.ScalarStyleSpec(
            classification="explicit", explicit_breaks=(1.0, 1.0, 0.5)
        ),
    }.items():
        validation[name] = error_of(fn)
    cases["validation_errors"] = validation

    values = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0,
              3.3, 6.6, 9.9, 1.1, 13.7, float("nan"), float("inf"), -4.2]
    finite_only = [v for v in values if math.isfinite(v)]

    cases["equal_interval"] = {
        "basic": {
            "breaks": ss.equal_interval_breaks(0.0, 100.0, n=5, decimals=2)[0],
            "labels": ss.equal_interval_breaks(0.0, 100.0, n=5, decimals=2)[1],
        },
        "negative": {
            "breaks": ss.equal_interval_breaks(-40.0, -10.0, n=3, decimals=3)[0],
            "labels": ss.equal_interval_breaks(-40.0, -10.0, n=3, decimals=3)[1],
        },
        "n2": ss.equal_interval_breaks(5.0, 7.0, n=2, decimals=2),
        "nan_span": ss.equal_interval_breaks(float("nan"), 1.0, n=2, decimals=2),
    }
    cases["quantile"] = {
        "basic": ss.quantile_breaks(np.asarray(finite_only), n=4, decimals=2),
        "flat": ss.quantile_breaks(np.asarray([2.0, 2.0, 2.0, 2.0]), n=3,
                                   decimals=2),
        "two_values": ss.quantile_breaks(np.asarray([1.0, 2.0]), n=5,
                                         decimals=2),
        "with_nan": ss.quantile_breaks(np.asarray(values), n=3, decimals=2),
        "empty": error_of(ss.quantile_breaks, np.asarray([]), n=3),
    }
    cases["natural_breaks"] = {
        "small_data": ss.natural_breaks(np.asarray(finite_only), n=3,
                                        decimals=2),
        "n_ge_size": ss.natural_breaks(np.asarray([1.0, 5.0, 9.0]), n=5,
                                       decimals=2),
        "sampled": ss.natural_breaks(
            np.asarray([float(i % 97) + (i * 0.37) % 3.1
                        for i in range(1500)]),
            n=4, sample=200, seed=0, decimals=2,
        ),
        "sampled_default_seed": ss.natural_breaks(
            np.asarray([float((i * 7919) % 2003) for i in range(1200)]),
            n=4, decimals=2,
        ),
        "empty": error_of(ss.natural_breaks, np.asarray([]), n=3),
    }
    # Freeze the sampled finite arrays for the two oversized cases so the
    # C++ PCG64 re-implementation is verified draw-for-draw (D-3).
    rng = np.random.default_rng(0)
    sampled_a = rng.choice(
        np.asarray([float(i % 97) + (i * 0.37) % 3.1 for i in range(1500)]),
        size=200, replace=False)
    rng_b = np.random.default_rng(0)
    sampled_b = rng_b.choice(
        np.asarray([float((i * 7919) % 2003) for i in range(1200)]),
        size=1000, replace=False)
    cases["frozen_samples"] = {
        "a": {"size": 200, "values": sampled_a.tolist()},
        "b": {"size": 1000, "values": sampled_b.tolist()},
    }

    spec_c = ss.ScalarStyleSpec()
    cases["classify_breaks"] = {
        "equal": ss.classify_breaks(
            spec_c, values=np.asarray(finite_only), vmin=0.0, vmax=20.0
        ),
        "manual_override": ss.classify_breaks(
            ss.ScalarStyleSpec(manual_range=(-10.0, 10.0)),
            values=np.asarray(finite_only), vmin=0.0, vmax=20.0,
        ),
        "explicit": ss.classify_breaks(
            ss.ScalarStyleSpec(
                classification="explicit", explicit_breaks=(0.0, 4.0, 8.0)
            ),
            values=np.asarray(finite_only), vmin=0.0, vmax=20.0,
        ),
    }

    ramp = cr.get_color_ramp("porosity")
    cases["ramp_items"] = {
        "continuous": ss.ramp_items_for_spec(
            spec_c, ramp, (0.0, 100.0), mode="continuous"
        ),
        "continuous_reverse": ss.ramp_items_for_spec(
            ss.ScalarStyleSpec(reverse=True), ramp, (0.0, 100.0),
            mode="continuous",
        ),
        "classified": ss.ramp_items_for_spec(
            spec_c, ramp, (0.0, 100.0), mode="classified",
            breaks=ss.equal_interval_breaks(0.0, 100.0, n=4, decimals=2)[0],
        ),
        "classified_reverse": ss.ramp_items_for_spec(
            ss.ScalarStyleSpec(reverse=True), ramp, (0.0, 100.0),
            mode="classified",
            breaks=ss.equal_interval_breaks(0.0, 100.0, n=4, decimals=2)[0],
        ),
        "degenerate_span": error_of(
            ss.ramp_items_for_spec, spec_c, ramp, (5.0, 5.0), mode="continuous"
        ),
        "missing_breaks": error_of(
            ss.ramp_items_for_spec, spec_c, ramp, (0.0, 100.0),
            mode="classified", breaks=[1.0],
        ),
    }
    return cases


# ---------------------------------------------------------------------------
# 4. geological_symbols
# ---------------------------------------------------------------------------


def case_geological_symbols() -> dict:
    cases = {}
    cases["schema_version"] = gs.SYMBOL_LIBRARY_SCHEMA_VERSION
    cases["library"] = gs.library_to_dict()
    cases["aliases"] = {
        alias: gs.canonical_symbol_id(alias)
        for alias in (
            "facies_v1", "shoreline_v1", "facies_boundary_v1",
            "interpolation_boundary_v1", "fault_v2", "nope",
        )
    }
    cases["validate_binding"] = {
        "ok_fault": gs.validate_binding("fault_v2", "fault_constraint", "line"),
        "ok_polygon_carry": gs.validate_binding(
            "map_extent", "interpolation_boundary", "vector"
        ),
        "wrong_role": gs.validate_binding("fault_v2", "paleo_shoreline", "line"),
        "wrong_geometry": gs.validate_binding("fault_v2", "fault_constraint",
                                              "polygon"),
        "unknown_symbol": gs.validate_binding("ghost", "fault_constraint",
                                              "line"),
        "unknown_role": gs.validate_binding("fault_v2", "not_a_role", "line"),
        "alias_ok": gs.validate_binding("shoreline_v1", "paleo_shoreline",
                                        "line"),
    }
    cases["binding_records"] = {
        symbol_id: gs.binding_record(symbol_id)
        for symbol_id in ("fault_v2", "facies_v2", "shoreline_v2", "map_extent")
    }
    cases["binding_record_field_values"] = gs.binding_record(
        "fault_v2", {"fault_type": ["normal", "reverse"]}
    )
    cases["legacy_styles"] = {
        "plain": gs.legacy_style_for_symbol("shoreline_v2"),
        "overrides": gs.legacy_style_for_symbol(
            "shoreline_v2", stroke="#ff0000", stroke_width=3.0,
            line_pattern="dash",
        ),
        "bad_override": error_of(
            gs.legacy_style_for_symbol, "shoreline_v2", **{"not_a_field": 1}
        ),
        "bad_pattern": error_of(
            gs.legacy_style_for_symbol, "shoreline_v2", line_pattern="zzz"
        ),
    }
    cases["style_entries"] = {
        symbol_id: gs.style_entry_for_symbol(symbol_id).to_dict()
        for symbol_id in ("fault_v2", "facies_v2", "provenance_line_v1")
    }
    cases["symbols_for_role"] = {
        role.value: [s.symbol_id for s in gs.symbols_for_role(role)]
        for role in gs.GEOLOGICAL_SYMBOLS["fault_v2"].applicable_roles
        | gs.GEOLOGICAL_SYMBOLS["facies_v2"].applicable_roles
    }
    cases["unknown_symbol_error"] = error_of(gs.symbol_by_id, "ghost")
    cases["library_from_dict"] = {
        "ok": len(gs.library_from_dict(gs.library_to_dict())),
        "bad_version": error_of(
            gs.library_from_dict, {"schema_version": 99, "symbols": []}
        ),
    }
    # V1 registration seam (on a copy — the 12 built-ins stay).
    scratch: dict = {}
    added = gs.register_symbols_into_style_library(scratch)
    removed = gs.unregister_symbols_from_style_library(scratch)
    cases["v1_registration"] = {
        "added": added,
        "removed": removed,
        "residual": sorted(scratch.keys()),
        "entry_sample": scratch and None,
    }
    return cases


# ---------------------------------------------------------------------------
# 5. style_library (V1)
# ---------------------------------------------------------------------------


def case_style_library() -> dict:
    cases = {}
    cases["schema_version"] = gsl.STYLE_LIBRARY_SCHEMA_VERSION
    cases["categories"] = list(gsl.CATEGORIES)
    cases["document"] = {
        "schema_version": gsl.STYLE_LIBRARY_SCHEMA_VERSION,
        "styles": [
            entry.to_dict() for entry in gsl.GEOLOGICAL_STYLE_LIBRARY.values()
        ],
    }
    cases["lookups"] = {
        "hit": gsl.style_entry("fault", "fault_major").to_dict(),
        "miss": error_of(gsl.style_entry, "fault", "nope"),
        "miss_category": error_of(gsl.style_entry, "nope", "x"),
    }
    # apply semantics on a stand-in layer object (style + opacity only).
    class _Layer:
        def __init__(self, opacity):
            self.style = {}
            self.opacity = opacity

    layer = _Layer(1.0)
    gsl.apply_style_to_layer(layer, gsl.style_entry("fault", "fault_major"))
    cases["apply_plain"] = {"style": layer.style, "opacity": layer.opacity}
    layer = _Layer(0.7)
    gsl.apply_style_to_layer(
        layer, gsl.style_entry("reference", "reference_basemap")
    )
    cases["apply_opacity_hint"] = {"style": layer.style, "opacity": layer.opacity}
    layer = _Layer(0.2)
    gsl.apply_style_to_layer(
        layer, gsl.style_entry("reference", "reference_basemap")
    )
    cases["apply_opacity_min"] = {"style": layer.style, "opacity": layer.opacity}
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump({"schema_version": 7, "styles": []}, handle)
        bad_path = handle.name
    try:
        bad_version = error_of(gsl.load_style_library, bad_path)
    finally:
        Path(bad_path).unlink(missing_ok=True)
    cases["load_errors"] = {"bad_version": bad_version}
    return cases


# ---------------------------------------------------------------------------
# 6. templates
# ---------------------------------------------------------------------------


def case_templates() -> dict:
    cases = {}
    map_doc = MapDocument(id="map_alpha", title="Prior Title")
    map_doc.extent = (110.0, 35.0, 125.0, 45.0)
    composition = tp.create_geological_factor_map_template(
        map_doc, factor_name="porosity", unit="%"
    )
    cases["factor_default"] = composition.to_dict()

    titled = tp.create_geological_factor_map_template(
        map_doc, title="Custom Title", factor_name="permeability", unit="mD"
    )
    cases["factor_titled"] = titled.to_dict()

    map_doc_no_title = MapDocument(id="map_beta")
    portrait = tp.create_geological_factor_map_template(
        map_doc_no_title, factor_name="thickness", orientation="portrait"
    )
    cases["factor_portrait"] = portrait.to_dict()

    degenerate = MapDocument(id="map_zero")
    degenerate.extent = (7.0, 0.0, 7.0, 4.0)
    cases["factor_degenerate_extent"] = tp.create_geological_factor_map_template(
        degenerate, factor_name="span0"
    ).to_dict()

    tiny = MapDocument(id="map_tiny")
    tiny.extent = (0.0, 0.0, 5.0, 5.0)
    cases["factor_tiny_extent"] = tp.create_geological_factor_map_template(
        tiny, factor_name="tiny"
    ).to_dict()

    huge = MapDocument(id="map_huge")
    huge.extent = (-1000.0, -500.0, 2500.0, 750.0)
    cases["factor_huge_extent"] = tp.create_geological_factor_map_template(
        huge, factor_name="huge"
    ).to_dict()
    return cases


# ---------------------------------------------------------------------------
# 7. qgis_style payload
# ---------------------------------------------------------------------------


def case_qgis_style() -> dict:
    cases = {}
    payload = qs.QgisStylePayload(
        renderer_xml="<renderer-v2 type=\"singleSymbol\"/>",
        labeling_xml="", name="fault style", tags=("fault", "v2"),
    )
    cases["valid"] = payload.to_dict()
    cases["bumped"] = payload.bumped().to_dict()
    cases["roundtrip"] = qs.QgisStylePayload.from_dict(payload.to_dict()).to_dict()
    cases["from_missing"] = qs.QgisStylePayload.from_dict(None)
    cases["from_empty_dict"] = qs.QgisStylePayload.from_dict({})
    cases["blank_renderer"] = error_of(
        qs.QgisStylePayload, renderer_xml="   "
    )
    cases["minimal"] = qs.QgisStylePayload.from_dict(
        {"renderer_xml": "<renderer-v2/>"}
    ).to_dict()
    return cases


# ---------------------------------------------------------------------------
# 8. _flatten_qgis_style
# ---------------------------------------------------------------------------


def case_flatten_qgis() -> dict:
    base_labels = ms.TextStyle(field="name", size=9.0,
                               halo_color="#f8f9fa", halo_width=1.0)
    flat_style = ms.VectorStyle(fill="#6c8ebf", stroke="#26364d",
                                labels=base_labels)
    cases = {}
    cases["legacy_only"] = _flatten_qgis_style(flat_style.to_dict())
    payload = {
        "fill": "#6c8ebf",
        "stroke": "#26364d",
        "labels": base_labels.to_dict(),
        "qgis_style": {
            "schema_version": 1,
            "renderer_xml": "<renderer-v2 type=\"categorizedSymbol\"/>",
            "labeling_xml": "  ",
            "name": "n",
            "tags": [],
            "revision": 3,
        },
    }
    cases["promoted"] = _flatten_qgis_style(payload)
    payload_label_units = {
        "labels": {"size": 12.0, "halo_width": 2.0, "halo_color": "#101010"},
        "qgis_style": {"renderer_xml": "<renderer-v2/>"},
    }
    cases["label_units"] = _flatten_qgis_style(payload_label_units)
    cases["explicit_buffer_kept"] = _flatten_qgis_style(
        {"labels": {"size": 10.0, "buffer": 0.5, "buffer_color": "#ffffff",
                    "halo_width": 3.0}}
    )
    cases["no_labels"] = _flatten_qgis_style({"fill": "#000000"})
    # Non-Mapping input: dict(str) raises (the function expects a Mapping).
    cases["non_mapping"] = error_of(_flatten_qgis_style, "not-a-dict")
    return cases


def main() -> None:
    dump("color_ramps_oracle.json", case_color_ramps())
    dump("map_styles_oracle.json", case_map_styles())
    dump("scalar_style_oracle.json", case_scalar_style())
    dump("geological_symbols_oracle.json", case_geological_symbols())
    dump("style_library_oracle.json", case_style_library())
    dump("templates_oracle.json", case_templates())
    dump("qgis_style_oracle.json", case_qgis_style())
    dump("flatten_qgis_oracle.json", case_flatten_qgis())


if __name__ == "__main__":
    main()
