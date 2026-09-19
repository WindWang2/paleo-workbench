# CONV-27 Decisions — cartography style/template/symbol/ramp registry

## Scope ledger

**In scope (this branch owns)**
- `libs/cartography` (new, Qt-free): color ramp registry, VectorStyle/
  TextStyle value types + presets, ScalarStyleSpec + classification,
  geological symbol V2 registry, geological style library V1, QgisStylePayload
  model, componentized template library + the five map template factories,
  QGIS-bridge adapter payloads, and the product API facade (`cartography.hpp`).
- Root CMake `PWB_BUILD_CONV_27C` option block (implies Domain + CONV-02).
- `tools/oracle/generate_cartography_fixtures.py` + frozen fixtures under
  `libs/cartography/cartography_tests/fixtures/`.
- Tests: one per module + oracle-negative self-check + adapter schema tests.
- Python legacy annotations (module docstrings + `CPP_EXTENSION.md`).

**Out of scope (explicitly)**
- Layout/PDF export (branch mandate) and `renderers.py` SVG fallback path —
  the QGIS backend is the product render path; the Python fallback stays
  legacy (not deleted).
- `facies_taxonomy.py` (separate Q1 surface), `facies_renderer_xml.py`
  (hand-rolled XML — the bridge owns QGIS XML), `map_render_backend.py` UI.
- No changes to `native/qgis_render_bridge` (already C++; this branch emits
  its inputs).

**Shared/conflict files**
- `CMakeLists.txt` (root): only the appended `# BEGIN CONV-27` block —
  same append-only discipline as CONV-19/20/25.
- `paleo_workbench/mapping/CPP_EXTENSION.md`: appended section.
- Everything else is new files.

**Not duplicating other branches** — open PRs #1346-1349 cover data/workspace,
workflow runtime, prediction runtime and build packaging; none touch
cartography style/symbol/ramp/template surfaces.

## Decisions

- **D-1 New lib `libs/cartography`, namespace `pwb::cartography`.** A registry
  layer, not a kernel leaf of mapping_kernel (which is numeric cores). Links
  `Pwb::Domain` (JSON) and `Pwb::MappingDocument` (composition/document
  models). Gated by `PWB_BUILD_CONV_27C`; implies `PWB_BUILD_DATA` and
  `PWB_BUILD_CONV_02` (same pattern as CONV-18/23).
- **D-2 Bit-exact numpy replication for scalar classification.** `np.linspace`
  (`i*step+start`, forced endpoint), `np.quantile` linear `_lerp` with the
  `t>=0.5` branch, and Fisher-Jenks DP reproduce numpy's **pairwise
  summation** (blocksize 128, unroll 8, recursive split) so frozen oracle
  cases match bit-for-bit. Frozen DP cases stay small (≤1500 drawn samples,
  k≤4) so the O(k·n²)-per-class DP keeps the suite fast.
- **D-3 Deterministic sample draw = vendored PCG64 + numpy shuffle.**
  `natural_breaks` with >1000 finite values needs
  `default_rng(0).choice(..., replace=False)`. Implemented as numpy-compatible
  PCG64 (XSL-RR) + descending Fisher-Yates with Lemire bounded draws —
  verified against frozen sampled arrays from numpy 2.5.3 (stream-compatible
  by NEP 19). Failure mode is visible: the oracle freezes the sampled array
  for one oversized case.
- **D-4 Template library is componentized.** Shared page geometry
  (`TemplatePage`), component builders (`add_title`, `add_main_map`,
  `add_north_arrow`, `add_scale_bar`, `add_legend_rail`, `add_colorbar`,
  `add_subtitle`, `add_datasource`) over `pwb::mapping_document::Composition`,
  and five factories (factor/facies/prediction/constraint/comprehensive).
  The factor factory is Python-parity (oracle-frozen); the other four are
  C++-authored compositions from the same components (no Python counterpart —
  their tests assert geometry invariants + a parse/dump round-trip; the
  catalog lives only in the C++ library and the bind facade).
- **D-5 The QGIS adapter emits bridge payloads, not QGIS objects.**
  `qgis_adapter.hpp` produces (a) the scalar renderer payload JSON consumed by
  the existing C++ `build_scalar_renderer_xml`, (b) a `VectorLayerSpec`-shaped
  JSON matching `native/qgis_render_bridge/src/qgis_render_bridge.hpp` field
  names (fill/stroke/stroke_width/marker/line_pattern/renderer_kind/
  categories/ranges/labels…), and (c) the `_flatten_qgis_style` unit
  conversions (size px→pt ×72/96, buffer mm ×25.4/96, buffer_color fallback)
  frozen from the Python function. Building vendored QGIS on this box is out
  of resource budget (-j3); the payloads are schema-validated against the
  bridge header contract and unit-frozen against Python.
- **D-6 `style_dict_revision` deviation (documented).** Python hashes a frozen
  tuple with the process-salted `hash()` — not reproducible across processes
  and therefore not a portable contract. C++ provides a stable FNV-1a-64 over
  the canonical freeze serialization. Callers use it for change detection
  within a session; the value is never persisted semantically. Tests assert
  stability + content sensitivity, not numeric parity with Python.
- **D-7 Registry thread-safety.** The mutable color-ramp registry is a
  function-local static guarded by a mutex (matches Python's module-global
  registry with GIL-free C++ semantics). All other registries are immutable
  after first use.
- **D-8 Product API = module surface.** Ramps resolve through
  `color_ramps.hpp` (`get_color_ramp` / `list_color_ramps` /
  `register_color_ramp`), symbols through `geological_symbols.hpp`
  (`geological_symbols` / `symbol_by_id` / `symbols_for_role` /
  `validate_binding` / `binding_record`), templates through
  `templates.hpp` (`template_catalog` / `instantiate_template`);
  `cartography.hpp` adds `validate_style`, `apply_style` (preset or V1
  library entry; data-level apply: style payload + binding + effective
  opacity — no QgsMapLayer dependency) and `style_preset_catalog`.
  `apply_style_entry` mirrors Python `apply_style_to_layer` semantics
  (`min(layer_opacity, opacity_hint)`, binding under `style_binding`).
- **D-9 Python classification.** The ported modules get a docstring note
  "C++ port: libs/cartography (CONV-27); this module remains as oracle and
  legacy fallback" — product C++ code never imports them (the only Python
  left on the style chain is the oracle generator and the legacy fallback
  renderer surface, disclosed in the PR).

## Verification plan

- Oracle: one generator, six fixture groups (color_ramps, map_styles,
  scalar_style, geological_symbols, style_library, templates, qgis_style,
  flatten_qgis) + a `negative` group where the test perturbs the fixture and
  asserts `json_semantic_diff` reports it (self-check).
- Error parity: frozen ValueError/KeyError message cases (spec validation,
  symbol/style lookups, library schema mismatch, empty classification input).
- Local: configure + targeted build of `pwb_cartography` + its tests with
  `-j3` (resource gate), full ctest of the new suite ×2.
