# Mapping Engine 2.0 & Geological Mapping Pipeline — Codebase Analysis

## 1. Executive Summary

This document audits the existing mapping, rendering, styling, and geological factor workflows in Paleo Workbench. It establishes the baseline for the **Mapping Engine 2.0** refactoring and the **Geological Mapping Pipeline** end-to-end integration.

---

## 2. Current Mapping Engine Architecture

```
Current Data Flow:
  Project Data / Well Table / Trend Surface
         │
         ▼
  PaleoMapDocument (Record DTOs / JSON dicts)
         │
  ┌──────┴───────────────────────────┐
  ▼                                  ▼
MapAuthoringDocument        document_render_snapshot()
  (VectorLayer & EditSession)        │
  │                                  ▼
  │ (manual record sync)     MapRenderSnapshot (Immutable DTO)
  │                                  │
  ▼                                  ▼
MapEditScene / Canvas     MapRenderBackend (God Object)
(Qt Graphics Items)      ┌───────────┴───────────┐
                         ▼                       ▼
               FallbackMapRenderBackend    QgisMapRenderBackend
               (Direct QPainter + Culling) (qgis_render_bridge C++)
                         │                       │
                         ▼                       ▼
                    RenderFrame             RenderFrame
                    (RGBA Bytes)            (RGBA Bytes)
                         │                       │
                         └───────────┬───────────┘
                                     ▼
                            UnifiedMapCanvas (Screen)

Divergent Composer Flow:
  MapCompositionDocument (models.py)
         │
         ▼
  MapComposerRenderer (renderer.py)
         │ (Ad-hoc manual SVG generation, duplicate coordinate transform, no style engine)
         ▼
  Raw SVG String (Export only, inconsistent with Canvas)
```

### Flow Breakdown
1. **Data Layer**: Project records live in `PaleoMapDocument` (`project/models.py`) with nested lists (`facies_polygons`, `well_overlays`, `line_features`, `label_features`, `reference_layers`).
2. **Authoring Layer**: `MapAuthoringDocument` (`mapping/map_authoring.py`) wraps `VectorLayer` and `VectorEditSession` (`mapping/vector_layer.py`), providing undo/redo edit buffers.
3. **Snapshot Adapter**: `map_document_snapshot.py` converts either `PaleoMapDocument` or `MapAuthoringDocument` into an immutable `MapRenderSnapshot` containing `MapLayerSnapshot` items.
4. **Render Backend**: `map_render_backend.py` receives the snapshot, manages viewport aspect-fitting (`fit_extent_to_aspect`), and routes to `FallbackMapRenderBackend` or `QgisMapRenderBackend`.
5. **Canvas**: `UnifiedMapCanvas` polls `take_completed_frame()` and paints the resulting RGBA buffer.
6. **Composer & Export**: `composer/renderer.py` operates on `MapCompositionDocument` and re-implements its own ad-hoc SVG polygon/line/circle drawing logic, completely bypassed from the main renderer/styling system.

---

## 3. Current Core Objects & Abstraction Inventory

| Domain Concept | Current Implementation Class / Location | Status / Evaluation |
|---|---|---|
| **Map Document** | `PaleoMapDocument` (`project/models.py`), `MapAuthoringDocument` (`mapping/map_authoring.py`), `MapCompositionDocument` (`mapping/composer/models.py`) | **Fragmented**: Three different document concepts exist for persistence, authoring, and layout composition. |
| **Layer** | `VectorLayer` (`mapping/vector_layer.py`), `MapLayerSnapshot` (`mapping/map_render_backend.py`), `MapReferenceLayer` (`project/models.py`) | **Split**: `VectorLayer` is editing-centric; `MapLayerSnapshot` is rendering-centric. No unified polymorphic `MapLayer` base hierarchy (`VectorLayer`, `GridLayer`, `ContourLayer`, `WellPointLayer`, `AnnotationLayer`). |
| **Geometry** | `VectorFeature` (`mapping/vector_layer.py`), `_PreparedFeature` / `_PreparedLayer` (`map_render_backend.py`), GeoJSON dicts | **Scattered**: GeoJSON mappings are used across python boundaries; geometry parsing/flattening is repeatedly executed. |
| **Style / Symbol** | `VectorStyle`, `TextStyle`, `LinePattern`, `MarkerSymbol` (`mapping/map_styles.py`), `qgis_style.py` | **Partial**: Pure-data style definitions exist, but style evaluation and symbol dispatch are hard-coded directly in renderer loops. |
| **Renderer** | Inlined inside `FallbackMapRenderBackend` and `MapComposerRenderer` | **`MISSING ABSTRACTION`**: No `LayerRenderer` protocol/ABC (`SingleSymbolRenderer`, `CategorizedRenderer`, `GraduatedRenderer`, `ContourRenderer`, `GridRenderer`, `WellSymbolRenderer`). |
| **Renderer Registry** | Not present (inlined `if/elif` branching on `layer_type`) | **`MISSING ABSTRACTION`**: No extensible registry for dynamically resolving layer types to appropriate renderers. |
| **Render Backend** | `MapRenderBackend`, `FallbackMapRenderBackend`, `QgisMapRenderBackend` (`mapping/map_render_backend.py`) | **Coupled**: `FallbackMapRenderBackend` is overloaded with geometry culling, LOD, style resolution, text deferral, and raster handling. |
| **Canvas** | `UnifiedMapCanvas` (`ui/map_canvas_panel.py`) | **Functional**: Displays `RenderFrame` RGBA output and hosts interaction tools. |
| **Composer** | `MapCompositionDocument`, `ComposerElement` (`mapping/composer/models.py`), `MapComposerRenderer` (`mapping/composer/renderer.py`) | **Isolated**: Composer reimplements drawing independently from the map engine. |
| **Exporter** | `export_map_body` (`map_render_backend.py`), `render_to_svg` (`composer/renderer.py`), `MapExportWorker` (`ui/map_export_worker.py`) | **Divergent**: Two separate export pathways with potential visual discrepancies. |

---

## 4. Deep Audit of `map_render_backend.py`

`map_render_backend.py` is 1,975 lines long and acts as a massive God Object handling at least 14 distinct responsibilities:

1. **Geometry Conversion & Validation**: `_prepare_geometry`, `_as_points`, `_geometry_to_wkt`.
2. **Coordinate & Viewport Transformation**: `fit_extent_to_aspect`, `_screen_point`, scale denominator calculations.
3. **Culling & Spatial Filtering**: `_cull_features`, per-part screen bbox culling.
4. **Level of Detail (LOD) & Simplification**: Pixel-grid quantisation, vertex budget enforcement (`DEFAULT_VERTEX_BUDGET`), line stride decimation, point marker grid deduplication.
5. **Renderer Dispatch**: Hardcoded `if layer.layer_type == "scalar_grid"` / `"raster_source"` / `"vector"`.
6. **Style Evaluation**: `_category_colors`, `_color`, dash pattern translation.
7. **Point Symbol Painting**: `_draw_point_symbol` (Circle, Square, Triangle, Diamond, Cross, Star, Well), `_draw_dots`.
8. **Path & Polygon Construction**: `_paint_layer_paths`, OddEvenFill polygon path assembly, categories color switches.
9. **Label Layout & Safe Deferral**: `_draw_label_text`, `_LabelSpec` collection, GUI-thread `_paint_label_specs` for PySide6 font-engine safety.
10. **Raster & Grid Blitting**: `_draw_scalar_grid`, `_draw_raster_source`.
11. **Concurrency & Execution Management**: `ThreadPoolExecutor`, `_render_future`, generation tracking, stale frame cancellation.
12. **Frame Caching**: `_frame_key`, `_cached_frame`, prepared layers cache LRU.
13. **QGIS Bridge Serialization**: `_qgis_snapshot`, delta tracking (`_feature_delta_ships`), style flattening (`_flatten_qgis_style`).
14. **Backend Probing & Factory**: `qgis_backend_probe`, `create_map_render_backend`.

### Architectural Risks & Recommendations
- **Do not blindly break `map_render_backend.py`**: It contains delicate PySide6 thread safety fixes (e.g. #822 text font rendering off-thread crashes, weakref backend tracking).
- **Introduce clean abstractions around it**:
  - Extract a polymorphic `LayerRenderer` system and `RendererRegistry`.
  - Extract unified `Symbol` and `ColorRamp` models.
  - Retain `FallbackMapRenderBackend` and `QgisMapRenderBackend` as implementations of `RenderBackendProtocol`.
  - Unify `Canvas` and `Composer` so both render via the same backend / renderer pipeline.

---

## 5. Geological Factor & Interpolation Pipeline Audit

### Existing Foundation
- **`FactorGridResult`** (`paleo_workbench/workflow/factor_grid_result.py`): Robust, canonical data structure holding `grid_z` (float32, NaN nodata), `grid_x`, `grid_y`, `extent`, `statistics`, `variance_grid`, `boundary`, `contours`.
- **Interpolation Engines**:
  - `geoviz_plots.factor.kriging` (Ordinary Kriging with variogram fitting).
  - `geoviz_plots.factor.interpolation` (IDW, Spline, Directional Trend).
  - `paleo_workbench/workflow/constrained_idw_adapter.py` (Haiyou constrained-IDW with fault barriers).
- **Contour & Polygonization Helpers**:
  - `paleo_workbench/mapping/single_factor_pipeline.py`: Has `extract_grid_contours` (Marching Squares via `skimage` or fallback) and `extract_facies_polygons` (raster thresholding + `rasterio.features.shapes` + topology repair).

### Missing Link for Epic 2
Currently, interpolation produces either:
1. `FactorGridResult` cached in memory / NPZ artifact.
2. Matplotlib / GeoViz plots for preview.
3. Isolated `single_factor_pipeline.py` calls.

There is **no unified pipeline** that transforms:
`Well Data → Factor Extraction → Interpolation → FactorGridResult → GridLayer + ContourLayer + WellPointLayer → MapDocument → Map Composer → Professional Cartographic Export`.

---

## 6. Conclusion & Refactoring Strategy

1. **Build Mapping Engine 2.0 Abstractions**:
   - Define `MapLayer` hierarchy (`VectorLayer`, `GridLayer`, `ContourLayer`, `WellPointLayer`).
   - Define `LayerRenderer` interface and `RendererRegistry`.
   - Build `RenderPlan` and unify `Composer` + `Canvas` rendering.
2. **Build Geological Mapping Pipeline**:
   - Implement `GeologicalFactor` extraction & normalization.
   - Implement `GeologicalMappingPipeline` orchestrating Kriging/IDW → `GridLayer` → `ContourLayer` → `WellPointLayer` → `MapDocument`.
   - Build standard Geological Factor Map templates (Title, Legend, Color Bar, North Arrow, Scale Bar).
   - Wire application service and UI for factor map creation.
