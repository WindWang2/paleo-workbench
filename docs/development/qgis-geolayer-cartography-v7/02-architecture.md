# 02 — Architecture (V7 implementation)

Extends the audited baseline (00-baseline §1). Nothing below replaces an
existing authority; every piece names the authority it extends.

## 1. Layer stack after V7

```
Paleo scientific semantics (unchanged authorities)
  FactorMapTask / FactorGridResult / catalog artifacts / fusion / QA
        ↓  (pure data — no Qt/QGIS)
mapping_workspace (domain, extended)
  geological_layer_spec.py   GeologicalLayerSpec registry (T2)
  presentation.py            LayerPresentationState builder (T5)
  layer_roles/groups/stages  unchanged vocabularies, now bound to specs
  constraints_sync.py        vector-layer ⇄ ConstraintLine sync + fingerprint
        ↓
mapping/ (adapters to QGIS, extended)
  scalar_data_mirror.py      single-band float GeoTIFF mirrors (T3)
  scalar_style.py            ScalarStyleSpec → raster renderer XML (T3)
  geometry_operations.py     bridge-first generic-ops facade (T1)
  qgis_mirror.py             + raster mirrors + delta channel (T3/T6)
  qgis_layer_schema.py       GeologicalLayerSpec → fields_json (T2)
  geological_symbols.py      symbology V2 library entries (T4)
  layout_export.py           extended native mapping (T8)
  cartographic_qa.py         §14 rules (T8)
        ↓
native/qgis_render_bridge (narrow extensions; NOT edit_tools.*)
  map_stack_service: raster mirror upsert (+raster renderer XML),
    vector mirror feature-delta apply, optional fields_json
  style_codec: raster renderer XML codec (QgsSingleBandPseudoColorRenderer
    + QgsColorRampShader)
        ↓
vendored QGIS core/gui/analysis (built once, reused via PALEO_QGIS_REUSE_VENDOR)
```

## 2. Scalar factor pipeline (T3) — data flow

```
FactorGridResult (grid_z float32, NaN nodata, crs, unit, stats)
  → ScalarDataMirrorCache.ensure(layer_id, grid, extent, crs, data_revision)
      writes /vsimem/paleo-scalar-data-<...>/<layer>-<data_rev>.tif
      (GTiff float32 single band, NaN nodata, geotransform, CRS WKT)
      keyed by data_revision ONLY (styles never rewrite data)
  → publish via qgis_mirror (canvas) + _qgis_snapshot (offscreen):
      kind "raster", source_path=mirror path,
      raster_renderer_xml = encode_scalar_renderer_xml(ScalarStyleSpec,
                                                        grid stats)
  → bridge: QgsRasterLayer(path, "gdal") + setRenderer(from XML)
  → legend/colorbar in layout uses the SAME renderer (QgsLayoutItemLegend)
```

Classification host-side (numpy): equal_interval, quantile, explicit,
natural-breaks (Jenks on sampled valid values, deterministic seed). The C++
surface stays minimal: apply/serialize renderer XML string.

Fallback chain (honest): scalar path requires bridge + osgeo.gdal
(`qgis_scalar_pipeline_ready` probe, extended). Unavailable ⇒ RGBA mirror
(today's behavior) explicitly reported as degraded, not hidden.

## 3. Delta publish (T6) — ledger

`MirrorPublishLedger` (host-side, per canvas): for each doc_id records
last-applied {content_revision, style_sig, placement, visibility}. Publish:
1. content changed & bridge holds base revision → ship delta
   ({base_revision, changed_features, removed_ids}) — new bridge arg;
2. style-only → set_layer_style (existing);
3. placement-only → order/groups via existing batched placements;
4. visibility-only → set_mirror_layer_visibility/opacity.
Full reship only on: geometry-kind drift, stale-delta rejection, first
publish. Same semantics as the proven offscreen #932 channel.

## 4. Field schema path (T2)

GeologicalLayerSpec.fields → `fields_json` (name/type/length/precision/
constraints{unique,not_null,expression}/domain{code:value}/default/
editor_widget) → bridge builds QgsFields + QgsFieldConstraints on the
memory provider at mirror creation (narrow addition to
upsert_mirror_layer; absent bridge ⇒ fields still flow via GeoJSON
properties and the spec validates host-side — disclosed degradation).

## 5. Ownership and cross-branch contract (D9)

This branch owns: mapping/**, mapping_workspace/**, workflow/factor_*,
workflow/map_*, composer/**, bridge extensions outside edit_tools.*,
related tests/docs.
Minimal surgical edits elsewhere: ui/workstation/stage_actions.py call
sites (P0 fixes + new producers wired to mapping/-side builders),
project/models.py only if a contract field is unavoidable.
Parallel branch workstation-ux-v7: ui/workstation tool surface, no C++.
We deliver to them: LayerPresentationState (domain model in
mapping_workspace/presentation.py), GeologicalLayerSpec, capability
snapshots. They render decorations; we do not touch ui/workstation
internals beyond call sites.

## 6. Test architecture

Layered per goal §18: spec/schema (pure, always run); bridge-dependent
(QGIS marker, skip without bridge, fail-closed under PALEO_REQUIRE_QGIS);
fallback-path (always run); performance (bounded, explicit budgets,
separate marker); adversarial geometry/CRS/unit. The vendor build on this
machine enables the QGIS leg locally for the first time on Windows.
