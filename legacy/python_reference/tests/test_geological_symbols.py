"""§6 — geological symbols V2.

Coverage: the §6 vocabulary (fault classes incl. inferred + confidence
semantics, facies 9-class palette, provenance, boundaries), role/geometry
compat validation (negative cases), serialization round-trip, spec
cross-check (every §6 RendererBinding.style_id resolves and validates),
fallback style well-formedness, and coexistence with the V1 style library.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping.geological_style_library import (
    GEOLOGICAL_STYLE_LIBRARY,
    StyleEntry,
)
from paleo_workbench.mapping.geological_symbols import (
    GEOLOGICAL_SYMBOLS,
    SYMBOL_ALIASES,
    SYMBOL_CATEGORIES,
    GeologicalSymbolDef,
    apply_symbol_to_layer,
    binding_record,
    canonical_symbol_id,
    legacy_style_for_symbol,
    library_from_dict,
    library_to_dict,
    library_version,
    load_symbol_library,
    register_symbols_into_style_library,
    save_symbol_library,
    symbol_by_id,
    symbols_for_role,
    unregister_symbols_from_style_library,
    validate_binding,
)
from paleo_workbench.mapping.layers import VectorMapLayer
from paleo_workbench.mapping.map_styles import STYLE_LIBRARY, VectorStyle
from paleo_workbench.mapping_workspace.geological_layer_spec import (
    GEOLOGICAL_LAYER_SPECS,
    spec_for_role,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole

#: §6 roles: every spec renderer_binding.style_id of these roles must
#: resolve to a symbol entry and be role/geometry compatible with its role.
SECTION6_ROLES = (
    LayerRole.FAULT_CONSTRAINT,
    LayerRole.PROVENANCE_LINE,
    LayerRole.PROVENANCE_DIRECTION,
    LayerRole.DISTRIBUTION_LINE,
    LayerRole.PALEO_SHORELINE,
    LayerRole.FACIES_BOUNDARY,
    LayerRole.INTERPOLATION_BOUNDARY,
    LayerRole.INTEGRATED_BOUNDARY,
    LayerRole.INITIAL_FACIES_SOURCE,
    LayerRole.INITIAL_FACIES_DRAFT,
    LayerRole.INTEGRATED_FACIES,
    LayerRole.FACTOR_CLASSIFICATION,
)

# Flat dict keys the fallback renderer understands (VectorStyle.to_dict is
# the contract; the STYLE_LIBRARY presets are its established shape).
_FALLBACK_KEYS = set().union(
    *(set(preset.to_dict()) for preset in STYLE_LIBRARY.values())
) | set(VectorStyle().to_dict()) | {"categories", "ranges", "labels", "fill_patterns"}


# -- vocabulary ------------------------------------------------------------


def test_library_covers_section6_categories_and_vocabulary():
    assert set(SYMBOL_CATEGORIES) == {"fault", "facies", "provenance", "boundary"}
    present = {s.category for s in GEOLOGICAL_SYMBOLS.values()}
    assert present == set(SYMBOL_CATEGORIES)

    # fault: categorized composite + typed singles + inferred (dashed)
    for symbol_id in ("fault_v2", "fault_normal_v2", "fault_reverse_v2",
                      "fault_thrust_v2", "fault_strike_slip_v2",
                      "fault_inferred_v2"):
        assert symbol_id in GEOLOGICAL_SYMBOLS
    # facies: fills + hatch variant
    assert {"facies_v2", "facies_hatch_v2"} <= set(GEOLOGICAL_SYMBOLS)
    # provenance
    assert {"provenance_line_v1", "provenance_direction_v1",
            "distribution_line_v1"} <= set(GEOLOGICAL_SYMBOLS)
    # boundaries with distinct strokes per §6
    boundaries = [GEOLOGICAL_SYMBOLS[sid] for sid in
                  ("shoreline_v2", "facies_boundary_v2",
                   "interpolation_boundary_v2", "map_extent")]
    strokes = {(b.legacy_fallback.stroke, b.legacy_fallback.stroke_width)
               for b in boundaries}
    assert len(strokes) == 4  # mutually distinct


def test_fault_v2_is_categorized_on_fault_type_with_spec_domain():
    fault = symbol_by_id("fault_v2")
    spec_field = next(
        f for f in spec_for_role(LayerRole.FAULT_CONSTRAINT).fields
        if f.name == "fault_type"
    )
    assert fault.renderer_hint["renderer_kind"] == "categorized"
    assert fault.renderer_hint["field"] == "fault_type"
    assert [r["value"] for r in fault.renderer_hint["rules"]] == list(
        spec_field.choices
    )
    # legacy fallback carries the same categorized binding
    legacy = legacy_style_for_symbol("fault_v2")
    assert legacy["renderer"] == "categorized"
    assert legacy["field"] == "fault_type"
    assert {c[0] for c in legacy["categories"]} == set(spec_field.choices)
    assert all(c[2] for c in legacy["categories"])  # legend-complete labels


def test_fault_confidence_semantics_documented_in_renderer_hint():
    fault = symbol_by_id("fault_v2")
    confidence = fault.renderer_hint["confidence"]
    assert confidence["field"] == "confidence"
    spec_confidence = next(
        f for f in spec_for_role(LayerRole.FAULT_CONSTRAINT).fields
        if f.name == "confidence"
    )
    levels = confidence["levels"]
    assert set(levels) == set(spec_confidence.choices)  # inferred/interpreted/verified
    # monotonic gradation: inferred < interpreted < verified
    widths = [levels[k]["stroke_width"] for k in
              ("inferred", "interpreted", "verified")]
    alphas = [levels[k]["stroke_alpha"] for k in
              ("inferred", "interpreted", "verified")]
    assert widths == sorted(widths) and len(set(widths)) == 3
    assert alphas == sorted(alphas) and len(set(alphas)) == 3
    # inferred reads as uncertain: plain dash (not the fault long-dash)
    assert levels["inferred"]["line_pattern"] == "dash"
    assert levels["interpreted"]["line_pattern"] == "fault"
    # and the metadata documents the semantics for legend/QA
    assert set(fault.metadata["confidence_semantics"]) == set(levels)


def test_inferred_fault_symbol_is_dashed():
    inferred = symbol_by_id("fault_inferred_v2")
    legacy = legacy_style_for_symbol("fault_inferred_v2")
    assert legacy["line_pattern"] == "dash"
    assert inferred.metadata["confidence_level"] == "inferred"
    # lighter than the verified/interpreted base weight
    assert legacy["stroke_width"] < legacy_style_for_symbol("fault_v2")["stroke_width"]


def test_facies_v2_palette_matches_spec_domain_with_legend_groups():
    facies = symbol_by_id("facies_v2")
    spec_field = next(
        f for f in spec_for_role(LayerRole.INITIAL_FACIES_SOURCE).fields
        if f.name == "facies_name"
    )
    values = [r["value"] for r in facies.renderer_hint["rules"]]
    assert values == list(spec_field.choices)  # the 9-class domain, in order
    assert all(r["fill"].startswith("#") and len(r["fill"]) == 7 for r in
               facies.renderer_hint["rules"])
    # hierarchy grouping hint partitions the domain exactly once
    grouped = [c for group in facies.metadata["legend_groups"]
               for c in group["classes"]]
    assert sorted(grouped) == sorted(values) and len(grouped) == len(set(grouped))


def test_facies_hatch_variant_is_declaration_only():
    hatch = symbol_by_id("facies_hatch_v2")
    params = hatch.metadata["hatch"]
    assert params["style"] == "line_pattern_fill"
    assert set(params["per_class_angle_deg"]) == {
        r["value"] for r in symbol_by_id("facies_v2").renderer_hint["rules"]
    }
    # data-only: the fallback stays a plain outline (no fill painted)
    legacy = legacy_style_for_symbol("facies_hatch_v2")
    assert legacy["fill"] == "transparent"
    assert "renderer_xml" not in legacy


def test_provenance_symbols_declare_arrow_decorations():
    line = symbol_by_id("provenance_line_v1")
    assert line.metadata["decorations"][0]["kind"] == "arrow"
    direction = symbol_by_id("provenance_direction_v1")
    deco = direction.metadata["decorations"][0]
    assert deco["kind"] == "direction_arrow"
    assert deco["placement"] == "line_midpoint"
    assert deco["rotation_field"] == "azimuth_deg"  # spec field
    assert direction.metadata["labels"]["field"] == "azimuth_deg"


# -- role/geometry compatibility ---------------------------------------------


def test_validate_binding_positive_cases():
    ok, reason = validate_binding("fault_v2", LayerRole.FAULT_CONSTRAINT, "line")
    assert ok and reason == "ok"
    assert validate_binding("shoreline_v2", "paleo_shoreline", "line")[0]
    assert validate_binding("facies_v2", "initial_facies_source", "polygon")[0]
    # runtime generic "vector" layers are acceptable carriers
    assert validate_binding("provenance_line_v1", LayerRole.PROVENANCE_LINE,
                            "vector")[0]
    assert validate_binding("map_extent", LayerRole.MAP_REFERENCE, "polygon")[0]


def test_validate_binding_negative_role_cases():
    # §6: a fault style cannot bind a shoreline layer (and vice versa)
    assert validate_binding("fault_v2", LayerRole.PALEO_SHORELINE, "line") == (
        False, "symbol 'fault_v2' (category 'fault') does not apply to role "
               "'paleo_shoreline'")
    assert not validate_binding("shoreline_v2", LayerRole.FAULT_CONSTRAINT,
                                "line")[0]
    assert not validate_binding("facies_v2", LayerRole.FAULT_CONSTRAINT,
                                "polygon")[0]
    assert not validate_binding("provenance_line_v1", LayerRole.DISTRIBUTION_LINE,
                                "line")[0]
    assert not validate_binding("fault_inferred_v2", LayerRole.INTEGRATED_BOUNDARY,
                                "line")[0]


def test_validate_binding_negative_geometry_and_unknown_ids():
    ok, reason = validate_binding("fault_v2", LayerRole.FAULT_CONSTRAINT, "polygon")
    assert not ok and "expects 'line' geometry" in reason
    assert not validate_binding("facies_v2", LayerRole.INITIAL_FACIES_SOURCE,
                                "line")[0]
    assert not validate_binding("fault_v2", "not_a_role", "line")[0]
    ok, reason = validate_binding("no_such_symbol", LayerRole.FAULT_CONSTRAINT,
                                  "line")
    assert not ok and "unknown symbol" in reason


def test_symbols_for_role_and_alias_resolution():
    fault_symbols = {s.symbol_id for s in symbols_for_role(LayerRole.FAULT_CONSTRAINT)}
    assert fault_symbols == {"fault_v2", "fault_normal_v2", "fault_reverse_v2",
                             "fault_thrust_v2", "fault_strike_slip_v2",
                             "fault_inferred_v2"}
    assert [s.symbol_id for s in symbols_for_role(LayerRole.PROVENANCE_DIRECTION)] \
        == ["provenance_direction_v1"]
    assert symbols_for_role(LayerRole.QC_WARNING) == []
    # spec compatibility aliases resolve to their V2 successor
    for alias, target in SYMBOL_ALIASES.items():
        assert canonical_symbol_id(alias) == target
        assert symbol_by_id(alias).symbol_id == target


def test_symbol_by_id_unknown_lists_available():
    with pytest.raises(KeyError, match="fault_v2"):
        symbol_by_id("不存在的符号")


def test_symbol_construction_validates_vocabulary():
    base = symbol_by_id("shoreline_v2").to_dict()

    data = dict(base, category="volcanic")
    with pytest.raises(ValueError, match="category"):
        GeologicalSymbolDef.from_dict(data)
    data = dict(
        base,
        renderer_hint={**base["renderer_hint"], "renderer_kind": "hallucinated"},
    )
    with pytest.raises(ValueError, match="renderer_kind"):
        GeologicalSymbolDef.from_dict(data)
    data = dict(base, geometry_kind="polyhedron")
    with pytest.raises(ValueError, match="geometry_kind"):
        GeologicalSymbolDef.from_dict(data)
    data = dict(base, version=0)
    with pytest.raises(ValueError, match="version"):
        GeologicalSymbolDef.from_dict(data)


# -- serialization -----------------------------------------------------------


def test_library_roundtrip_through_json():
    payload = library_to_dict()
    restored = library_from_dict(json.loads(json.dumps(payload)))
    assert set(restored) == set(GEOLOGICAL_SYMBOLS)
    for symbol_id, symbol in GEOLOGICAL_SYMBOLS.items():
        assert restored[symbol_id].to_dict() == symbol.to_dict()
        # frozenset roles survive the wire
        assert restored[symbol_id].applicable_roles == symbol.applicable_roles
    assert payload["schema_version"] == library_version() == 2


def test_save_load_symbol_library_roundtrip(tmp_path):
    path = save_symbol_library(tmp_path / "sym" / "symbols.json")
    loaded = load_symbol_library(path)
    assert set(loaded) == set(GEOLOGICAL_SYMBOLS)


def test_library_from_dict_rejects_unknown_schema():
    with pytest.raises(ValueError, match="schema"):
        library_from_dict({"schema_version": 99, "symbols": []})


# -- spec cross-check --------------------------------------------------------


def test_every_section6_spec_style_id_resolves_and_validates():
    resolved = set()
    for role in SECTION6_ROLES:
        spec = spec_for_role(role)
        binding = spec.renderer_binding
        assert binding is not None, f"{role.value} has no renderer binding"
        symbol = symbol_by_id(binding.style_id)
        resolved.add(symbol.symbol_id)
        ok, reason = validate_binding(
            binding.style_id, spec.role, spec.geometry_kind)
        assert ok, f"{binding.style_id} vs {spec.spec_id}: {reason}"
        # the fallback renderer kind matches the spec's declared kind
        assert symbol.renderer_hint["renderer_kind"] == binding.renderer_kind
    assert resolved == {"fault_v2", "facies_v2", "provenance_line_v1",
                        "provenance_direction_v1", "distribution_line_v1",
                        "shoreline_v2", "facies_boundary_v2",
                        "interpolation_boundary_v2"}


def test_spec_style_ids_never_resolve_to_a_foreign_role():
    # any spec style_id that resolves must be valid for its own spec
    for spec in GEOLOGICAL_LAYER_SPECS.values():
        binding = spec.renderer_binding
        if binding is None:
            continue
        try:
            symbol_by_id(binding.style_id)
        except KeyError:
            continue  # not part of the §6 symbol vocabulary (mask_v1, ...)
        ok, reason = validate_binding(
            binding.style_id, spec.role, spec.geometry_kind)
        assert ok, f"{binding.style_id} vs {spec.spec_id}: {reason}"


# -- fallback styles & bindings ------------------------------------------------


def test_legacy_fallback_styles_are_well_formed():
    for symbol_id, symbol in GEOLOGICAL_SYMBOLS.items():
        legacy = legacy_style_for_symbol(symbol_id)
        assert set(legacy) <= _FALLBACK_KEYS, symbol_id
        # every fallback parses back through the flat style authority
        assert VectorStyle.from_dict(legacy).to_dict() == legacy, symbol_id
        if symbol.renderer_hint["renderer_kind"] == "categorized":
            assert legacy["renderer"] == "categorized"
            assert legacy["field"] == symbol.renderer_hint["field"]
            assert {c[0] for c in legacy["categories"]} == {
                r["value"] for r in symbol.renderer_hint["rules"]}


def test_legacy_style_overrides():
    styled = legacy_style_for_symbol(
        "shoreline_v2", stroke="#000000", stroke_width=3.0,
        line_pattern="dash")
    assert styled["stroke"] == "#000000"
    assert styled["stroke_width"] == 3.0
    assert styled["line_pattern"] == "dash"
    with pytest.raises(TypeError):
        legacy_style_for_symbol("shoreline_v2", not_a_style_field=1)


def test_binding_record_shape_and_field_values():
    record = binding_record("fault_v2", {"fault_type": "normal"})
    assert record["symbol_id"] == "fault_v2"
    assert record["symbol_version"] == 2
    assert record["category"] == "fault"
    assert record["field"] == "fault_type"
    assert record["classes"] == ["normal", "reverse", "thrust", "strike_slip",
                                 "unclassified"]
    assert record["confidence_field"] == "confidence"
    assert record["field_values"] == {"fault_type": "normal"}
    assert record["source"].startswith("geological-symbols-v2/")
    # single-symbol entries produce a class-free record
    plain = binding_record("shoreline_v2")
    assert plain["classes"] == [] and "field_values" not in plain


def test_apply_symbol_to_layer_records_versioned_binding():
    layer = VectorMapLayer(id="f1", name="断层", layer_type="vector")
    apply_symbol_to_layer(layer, "fault_v2")
    binding = layer.style["style_binding"]
    assert binding["symbol_id"] == "fault_v2"
    assert binding["symbol_version"] == 2
    assert binding["field"] == "fault_type"
    assert layer.style["renderer"] == "categorized"

    direction = VectorMapLayer(id="p1", name="物源方向", layer_type="vector")
    apply_symbol_to_layer(direction, "provenance_direction_v1",
                          field_values={"azimuth_deg": 225.0})
    assert direction.style["style_binding"]["field_values"] == {"azimuth_deg": 225.0}
    assert direction.style["labels"]["field"] == "azimuth_deg"


# -- V1 library coexistence ----------------------------------------------------


def test_register_symbols_keeps_v1_entries_intact():
    copy = dict(GEOLOGICAL_STYLE_LIBRARY)
    original_keys = set(copy)
    added = register_symbols_into_style_library(copy)
    assert added and set(copy) >= original_keys  # nothing replaced/removed
    assert all(isinstance(copy[key], StyleEntry) for key in added)
    fault_entry = copy["fault.fault_v2"]
    assert fault_entry.binding["symbol_id"] == "fault_v2"
    assert fault_entry.style.renderer == "categorized"


def test_register_and_unregister_into_global_library():
    original_keys = set(GEOLOGICAL_STYLE_LIBRARY)
    try:
        added = register_symbols_into_style_library()
        assert set(GEOLOGICAL_STYLE_LIBRARY) == original_keys | set(added)
    finally:
        removed = unregister_symbols_from_style_library()
    assert set(removed) == set(added)
    assert set(GEOLOGICAL_STYLE_LIBRARY) == original_keys
    # idempotent in both directions
    assert unregister_symbols_from_style_library() == []
