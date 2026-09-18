# CONV-27 Findings — cartography style/template/symbol/ramp registry

Branch: `feat/cpp-cartography-style-template-registry` (base `ff67dcf3` = origin/main).
Scope: the early-excluded cartography style surfaces — style value types,
color ramps, geological symbols, style libraries, scalar classification,
map templates, and the C++ adapter toward the QGIS render bridge.

## Python surfaces inventoried (read-only pass + verification)

| Python module | Lines | Public surface | Tests | C++ status before this branch | Class |
|---|---|---|---|---|---|
| `paleo_workbench/mapping/color_ramps.py` | 251 | `ColorStop`, `ColorRamp` (evaluate/evaluate_value/sample_table/to_dict/from_dict), 11 builtin ramps, `get_color_ramp`/`register_color_ramp`/`list_color_ramps` | `tests/test_mapping_engine_v2.py::test_color_ramps_evaluation` (partial) | none | Python-only |
| `paleo_workbench/mapping/map_styles.py` | 383 | `LinePattern`(+dash_pattern), `MarkerSymbol`, `TextStyle`, `VectorStyle` (tolerant from_dict), 8-entry `STYLE_LIBRARY`, `default_style_for`, `style_dict_revision` | `tests/test_map_styles.py` (8) | bridge `VectorLayerSpec` only (native/qgis_render_bridge), no Qt-free value type | partial |
| `paleo_workbench/mapping/geological_symbols.py` | 783 | V2 registry (15 symbols), `GeologicalSymbolDef`, `validate_binding`, `binding_record`, `legacy_style_for_symbol`, `library_to_dict/from_dict`, save/load, V1 registration seam | `tests/test_geological_symbols.py` (24) | none | Python-only |
| `paleo_workbench/mapping/geological_style_library.py` | 299 | V1 library (12 entries), `StyleEntry`, `style_entry`, save/load, `apply_style_to_layer` | `tests/test_geological_style_library.py` (10) | none | Python-only |
| `paleo_workbench/mapping/scalar_style.py` | 363 | `ScalarStyleSpec`, `equal_interval_breaks`, `quantile_breaks`, `natural_breaks` (Fisher-Jenks DP), `classify_breaks`, `ramp_items_for_spec`, `encode_scalar_renderer_xml` | `tests/test_qgis_scalar_raster_v7.py` + 9 more | renderer XML encode already C++ (`build_scalar_renderer_xml`); classification host-side Python-only | partial |
| `paleo_workbench/mapping/qgis_style.py` | 231 | `QgisStylePayload` model/revision, `payload_from_legacy_style` | `tests/test_qgis_style_payload.py` (10) | XML generation already C++ (bridge) | core-only-unwired |
| `paleo_workbench/mapping/geological_pipeline/templates.py` | 132 | `create_geological_factor_map_template` | indirect (`test_geological_mapping_pipeline`) | composition document model ported (CONV-02); builder missing | partial |
| `paleo_workbench/mapping/renderers.py` | 802 | SVG fallback renderers + `RendererRegistry` | fallback-path suites | intentionally NOT ported (QGIS backend is the C++ path) | Python-only (kept legacy) |
| `paleo_workbench/mapping/facies_patterns.py` | 111 | pattern-id table | `tests/test_facies_patterns.py` | table frozen into symbol registry metadata | Python-only (kept legacy) |
| `paleo_workbench/mapping/facies_renderer_xml.py` | 179 | hand-rolled categorized SVGFill XML | bridge-verified tests | out of scope here (bridge owns QGIS XML authoring) | Python-only (kept legacy) |
| `paleo_workbench/mapping/facies_taxonomy.py` | 215 | 3-level taxonomy tree | `tests/test_facies_taxonomy.py` (15) | separate Q1 surface, not this branch | Python-only (kept legacy) |

## Key semantics pinned for the port

1. **color_ramps**: `_hex_to_rgb` gray `(128,128,128,255)` fallback; 3/6/8-digit
   hex; `evaluate` clamps + linear interpolation with **Python banker's
   rounding** (`int(round(x))` = half-to-even → `std::nearbyint` under the
   default FP environment); single-stop ramp short-circuits; `evaluate_value`
   degenerate span via `math.isclose` (rel_tol=1e-9, abs_tol=0.0); registry is
   insertion-ordered with lowercased keys; `from_dict` falls back to the
   viridis registry entry for non-mapping payloads.
2. **map_styles**: flat dict wire format with conditional keys
   (`categories`/`ranges`/`fill_patterns`/`labels` only when non-empty);
   tolerant `from_dict` (QGIS `{"value": color}` map form, dict-form ranges
   with `min/lo`/`max/hi`/`fill/color`/`label`, invalid numerics skipped,
   unknown patterns ignored); `style_dict_revision` uses Python's salted
   `hash()` → **not** cross-process stable (decision D-6).
3. **scalar_style** (numpy-exact): `np.linspace` = `i*step + start` with
   `step=(stop-start)/div`, endpoint forced; `np.quantile` 'linear' with the
   two-branch `_lerp` (`t >= 0.5` ⇒ `b - (b-a)*(1-t)`); Fisher-Jenks DP with
   numpy **pairwise summation** (blocksize 128, unroll 8) for `seg.sum()` and
   `(seg*seg).sum()`; deterministic sample draw
   `default_rng(seed).choice(finite, size, replace=False)`; strict-monotonic
   quantile enforcement; `f"{v:.{d}f}"` labels (NaN → `"nan"`).
4. **geological_symbols**: 15 symbols in registry insertion order; aliases
   resolve 4 legacy ids; `validate_binding` reason strings; `binding_record`
   key order (`symbol_id, symbol_version, category, field, classes, source`
   [+`confidence_field`, +`field_values`]); `_plain` JSON-safe deep copy;
   whole-library document `{"schema_version": 2, "symbols": [...]}`.
5. **templates**: `create_geological_factor_map_template` geometry
   (A4 297×210 landscape / 210×297 portrait, margins 12/10, title_h 14,
   map_w = w−24−50, legend 45×min(map_h,80) right rail, scale-bar
   `length_km = max(5, int(span/4)) if span > 10 else 10`, dpi 300,
   `comp_{map_doc.id}`, title fallback `f"{factor_name} 平面分布图"`);
   `MapDocument` inside element properties serializes as the stub
   `{"__ref__": "map_document", "id", "layer_count"}` (composer
   `_serialize_property_value`), NOT a nested document.
6. **qgis_style payload**: `{"schema_version": 1, "renderer_xml",
   "labeling_xml", "name", "tags", "revision"}`; `bumped()` = revision+1;
   `from_dict` returns None on absent/invalid (blank `renderer_xml` rejected).
7. **`_flatten_qgis_style`** (map_render_backend): promotes
   `qgis_style.renderer_xml/labeling_xml` to top level when non-blank, drops
   the `qgis_style` key, converts label `size` px→pt (×72/96), adds
   `buffer` mm (×25.4/96) from non-zero `halo_width`, falls back
   `buffer_color` ← `halo_color`.

## Existing C++ to reuse (no duplication)

- `Pwb::Domain` (`pwb::domain::Json` = ordered_json, `json_semantic_diff`,
  Python-compatible dump) — the oracle comparison backbone.
- `Pwb::MappingDocument` (CONV-02): `MapDocument`/`Composition`/
  `ComposerElement` parse/dump, `add_element` stable z-sort — the template
  library builds on it, no parallel document model.
- `native/qgis_render_bridge` (C++/pybind, links vendored QGIS): already owns
  ALL QgsSymbol/QgsRenderer/QgsTextFormat/QgsColorRampShader realization
  (`build_renderer_from_spec`, `apply_renderer_style`, `apply_label_style`,
  `build_scalar_renderer_xml`, `renderer_to_xml/from_xml`). This branch adds
  the Qt-free adapter that produces its input payloads — it does NOT wrap
  QGIS a second time.
- Oracle/test conventions from `libs/mapping_kernel` (fixture macro +
  `json_semantic_diff` + hand-rolled `check()` harness) and
  `tools/oracle/generate_*_fixtures.py` (generators import REAL Python).

## Oracle interpreter

This Linux box has no repo venv; a dedicated interpreter was created at
`/tmp/pwb-oracle-env` (Python 3.14 + numpy 2.5.3 + pydantic + PySide6) —
network install, used only to run `tools/oracle/generate_cartography_fixtures.py`
against the real modules. The committed fixtures are the oracle; the
generator is reproducible from any environment that can import the modules.
