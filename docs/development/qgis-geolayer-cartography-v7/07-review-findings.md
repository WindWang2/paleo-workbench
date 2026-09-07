# 07 — Review findings (§19 three rounds)

Status: PENDING — the three review rounds run after the bridge suite
verification completes (all implementation phases are committed; reviews
cover the final state).

## Round 2 — Architecture (2026-09-08, bridge-unbuilt source review by agent)

Q1–Q8 answered with file:line evidence. Verdict: no second GIS kernel;
layer/tree/MapDocument authorities intact; delegation narrow; ownership
clean (edit_tools.* untouched; ui/workstation only stage_actions call
sites; third_party + grid_render_core touches documented).

P1 fixes applied (commit a2cdf470):
- F1: host Chaikin smooth reported ENGINE_SHAPELY → ENGINE_HOST
  (geometry_operations.py) + test expectation corrected.
- F2: nearest-feature docstring claimed scipy cKDTree while the impl is
  host brute force → docstring corrected.
- F3: live mirror mapped Polygon→"Polygon" while the schema adapter
  mandates MultiPolygon → mirror now emits MultiPolygon (R2-F3).
- F4: fields_json wire was test-only → `_fields_json_for_metadata` resolves
  the layer's recorded role to spec schema and rides the mirror upsert
  (legacy-bridge TypeError fallback keeps old bridges working).
- F6: C++ fid-table clear on count mismatch now also drops
  mirror_data_revisions[doc_id] (map_stack_service.cpp) — otherwise later
  deltas would duplicate until a coincidental full ship.
- F5: new registry test asserts geometry_kind↔LayerType consistency.
- Bonus (found while verifying F4): ledger required layer.data_revision →
  revision-less duck-typed layers (SimpleNamespace) crashed the mirror;
  fixed (revision 0 = ledger disabled, delta off) + regression fixed
  (test_mirror_failures_collected_not_swallowed, pre-existing #1164 test).
P2 accepted as follow-ups (F7 raster ledger tokens, F8 ledger scoping,
F9 docstring capability sniff, F10 recompute discipline, F11 symbol
sidecar disclosure — see 08 §4 for the disclosed subset).

## Round 1 — Scientific / GIS correctness (2026-09-08, bridge-unbuilt fallback review by agent)

P0: R1-F1 MultiPolygon PIP flattening (geometry_planar) — fixed + regression.
P1 fixed: R1-F2/F3 areas+low_confidence keys, R1-F4 uncertainty statistics,
R1-F5 mask MultiPolygon harvest.
P2 accepted as follow-ups unless cheap: F6 quantile collapse, F7 Jenks
count change, F8 constant-grid span, F9 map_qa_rules literal.
Verified OK: scalar mirror orientation (north-up + NaN nodata consistent
across grid_array/mirror/geotransform/RGBA path), clip delegation
identical, fusion science unaltered, symbology domains exact, QA spot
checks sound, fingerprint order-sensitivity is the right fail-safe.

## Round 3 — Cartography / Performance / Adversarial (2026-09-08, by agent)

P0: R3-1 fields_json vs delta channel (binding+C++ signature + signature
probes; strict-signature fake test) — fixed.
P1 fixed: R3-2/R3-3 area/length multi-part, R3-4 n_classes cap (256),
R3-5 explicit-breaks strict increase, R3-7 empty raster_source recorded,
R3-8 RGBA reverse, R3-9 clip validation; R3-6 raster_renderer_info noted
(item_count fallback path — bridge-unbuilt, verified at build).
P2 accepted/documented: R3-10 revision-0 ledger path, R3-11/12 empty-input
discipline, R3-13 silent substitutions (inventoried), R3-14 vsimem reopen
(disclosed in 08), R3-15 perf wording.
Silent-path inventory recorded in the review; screen/export parity holds on
the native path (single renderer authority), divergences contained to the
disclosed RGBA/composer fallbacks.



## Round 2 — Architecture
Focus: no second GIS kernel, layer authority (spec registry ↔
memberships), QGIS tree authority, MapDocument authority, persistence,
mirror ledgers, layout (no second project authority), catalog/run graph.
<!-- R2_FINDINGS -->

## Round 3 — Cartography / Performance / Adversarial
Focus: 1000-layer trees, complex polygons/holes/Multi*, invalid geometries,
missing CRS, stale factors, bad renderers, project reopen, layout export,
fallback honesty, benchmark budgets.
<!-- R3_FINDINGS -->

## Fix log
<!-- FIX_LOG -->
