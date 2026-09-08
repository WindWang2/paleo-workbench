# 08 — Known limitations

Honest boundaries at PR time.

1. **Legend filtering**: the bridge's QgsLayoutItemLegend parses only
   type/position/map_item/title/resize/background — no layer filter key.
   COLOR_BAR/GEOLOGICAL_LEGEND therefore list every layer of the linked map
   (QGIS-native behaviour); a narrow `filter_layers` bridge extension is the
   follow-up. No drift is introduced: screen and export share the renderer.
2. **Hybrid layout elements**: TIMESCALE, INSET_MAP, STAT_CHART, PROFILE,
   FAULT_SYMBOLS, LITHOLOGY_LEGEND remain composer-rendered; the export
   report itemizes them (`hybrid_items`) and keeps the all-or-nothing engine
   policy — no mixed-engine single-page exports (goal §13 allows documented
   mixing; we chose strictness).
3. **Scalar QGIS path availability**: requires bridge + osgeo.gdal in the
   runtime env; without them factor grids render via the RGBA mirror
   (disclosed degraded mode). Main CI remains fallback-only by design
   (packaging #437); the qgis CI leg + this machine run the scalar path.
4. **fields_json (QgsFields/constraints/domains on mirrors)**: the wire
   adapter exists (mapping/qgis_layer_schema.py) and the spec validates
   host-side, but the C++ mirror upsert does not yet apply field schemas to
   memory providers — GeoJSON properties remain the attribute path. The
   goal's "one field authority" holds (spec → properties), the QGIS-side
   constraint enforcement is the remaining bridge work (recorded as
   follow-up; not silently skipped).
5. **Constraint versioning**: constraint lines gained content fingerprints
   (constraints_sync.py) so staleness can compare content, but they are
   still not catalog DataVersions — `constraints:current` freshness stays
   UNKNOWN-labeled where no fingerprint consumers run yet.
6. **Snapping host authority**: host SnappingService remains the editing
   authority pushed into QGIS (deliberate; documented in audit). Topology
   checks run shapely host-side via the facade (bridge exposes no topology
   API).
7. **Pre-existing environment issues** (NOT introduced by this goal,
   verified standalone/pristine): test_ui_adversarial_v5 theme-switch hangs
   in the FULL offscreen suite on this machine (passes standalone — suite
   pollution/timeout interaction); test_lod_render_path hard-crashes on
   Windows (documented since V6); native factor-map tests need the native
   builds (now built in this worktree).
8. **Perf coverage**: mirror publish, fusion entry, and factor products are
   benchmarked; the full §15 matrix (100k features, 10k wells metadata,
   500×500×50 fusion, layout export at scale) runs in the final verification
   pass (05-verification) — budgets recorded in 06-performance.
9. **osgeo import**: the workbench venv does not vendor GDAL Python
   bindings; osgeo resolves via the conda deps env (cp312 ABI match) when
   its site-packages/DLLs are on the runtime path. CI's qgis leg uses its
   conda prefix equivalently (documented in the workflow file).
