# Paleo Workbench Core Convergence: Mapping Engine 2.0 & Styling System

**Author:** Mapping Engine & Cartography Team (Worker M2)  
**Status:** Converged Specification & Architecture Guide  
**Date:** 2026-08-25  

---

## 1. Overview & Architecture Vision

Mapping Engine 2.0 modernizes and decouples the spatial visualization and cartographic capabilities of Paleo Workbench. The architecture achieves four core design goals:

1. **Pure-Data Layer Decoupling**: Complete separation between pure, serializable domain data models (`MapDocument`, polymorphic `MapLayer` hierarchy) and UI widget or rendering backends. Layer models contain zero dependencies on `PySide6.QtWidgets` or raw `qgis.core` objects.
2. **Extensible Renderer Registry & Styling System**: Polymorphic style rendering supporting single symbol, categorized (nominal), graduated (numerical range bins), continuous scalar grids (color ramps), isoline contours, well symbols, and cartographic annotations.
3. **QGIS C++ Bridge Domain Isolation**: The native QGIS rendering engine interacts strictly across a plain data/POD boundary (`VectorLayerSpec`, `FeatureSpec`, `CategorySpec`, `RangeSpec`). QGIS objects (`QgsVectorLayer`, `QgsMapCanvas`, `QgsFeature`) remain completely encapsulated within native C++ memory without polluting Python domain state. If QGIS is unavailable, `FallbackMapRenderBackend` renders byte-identical outputs.
4. **Unified Canvas & Composer Export Parity**: Interactive viewport canvas (`UnifiedMapCanvas`) and print composer (`MapComposerRenderer` / `MapCompositionDocument`) share the exact same geometry parsing, letterbox aspect calculations, DPI scaling (`dpi / 96.0`), and vector styling for PNG, SVG, and PDF exports.

---

## 2. Pure-Data Layer Hierarchy (`paleo_workbench/mapping/layers.py`)

All layer and document data models reside in `paleo_workbench/mapping/layers.py`. They are standard Python dataclasses depending only on `numpy` and the standard library.

```
MapLayer (Base ABC)
├── VectorMapLayer (Generic Point, Line, Polygon GeoJSON features)
│   ├── ContourMapLayer (Isolines with levels and interval metadata)
│   ├── WellPointMapLayer (Oil & gas well markers with factor values)
│   ├── PolygonMapLayer (Facies / geological zones with categories)
│   └── AnnotationMapLayer (Text callouts, labels, coordinates, rotation)
├── GridMapLayer (Continuous 2D scalar array with FactorGridResult and color ramp)
└── RasterMapLayer (External georeferenced raster image source)
```

### 2.1 Polymorphic Layer Specifications

| Layer Class | `layer_type` | Special Attributes | Key Responsibilities |
|---|---|---|---|
| `MapLayer` | `vector` (base) | `id`, `name`, `extent`, `crs`, `visible`, `opacity`, `scale_range`, `style`, `metadata`, `data_revision`, `style_revision` | Base class for all cartographic layers; tracks revisions; produces immutable `MapLayerSnapshot`. |
| `VectorMapLayer` | `vector` | `features: tuple[Mapping[str, Any], ...]` | Stores GeoJSON features; automatically calculates bounding extent with epsilon padding. |
| `GridMapLayer` | `grid` / `scalar_grid` | `grid_result`, `grid_z`, `grid_x`, `grid_y`, `color_ramp_name`, `value_range`, `unit`, `nodata` | Encapsulates continuous float32 scalar grids; implements fast lookup-table `rasterize_rgba()`. |
| `ContourMapLayer` | `contour` | `levels: list[float]`, `contour_interval: float \| None`, `show_labels: bool` | Manages Marching Squares isocontour lines and level annotations. |
| `WellPointMapLayer` | `well_point` | `factor_name: str`, `unit: str` | Manages well coordinates, well identifiers, and factor measurements with standard well symbols. |
| `PolygonMapLayer` | `polygon` | `categories: list[dict[str, Any]]` | Manages facies classification and zoned geological polygons. |
| `AnnotationMapLayer` | `annotation` | `annotations: tuple[Mapping[str, Any], ...]` | Manages text callouts, coordinate labels, font sizes, colors, and rotation angles; provides `add_annotation()`, `set_annotations()`, and `clear_annotations()`. |
| `RasterMapLayer` | `raster_source` | `source_path: str` | References external georeferenced raster basemaps or imagery. |

### 2.2 Canonical `MapDocument` Container

`MapDocument` (`layers.py:390-524`) is the root container for multi-layer maps:
- `layers: list[MapLayer]`: Ordered stack of layers (bottom to top).
- `crs: str`: Project coordinate reference system (e.g. `EPSG:4326`, `EPSG:3857`).
- `extent: tuple[float, float, float, float]`: Aggregated bounding box `(xmin, ymin, xmax, ymax)` dynamically recomputed from visible layers via `recompute_extent()`.
- `add_layer()`, `remove_layer()`, `get_layer()`, `reorder_layers()`: Layer stack management.
- `to_snapshot() -> MapRenderSnapshot`: Produces an immutable, thread-safe snapshot consumed by render backends.
- `from_snapshot(snapshot: MapRenderSnapshot) -> MapDocument`: Reconstructs the complete polymorphic layer tree from a render snapshot.

---

## 3. Extensible Renderer Registry (`paleo_workbench/mapping/renderers.py`)

Layer renderers translate abstract layer data models and styles into visual primitives (QPainter commands or SVG vector markup).

### 3.1 `LayerRenderer` Protocol & Registry

Every renderer inherits from `LayerRenderer`:
- `legend_items(layer: MapLayer) -> list[LegendItem]`: Emits legend entries (label, fill, stroke, symbol type, marker symbol, gradient stops).
- `render_svg(layer: MapLayer, ctx: RenderContext) -> str`: Emits clean, standalone SVG group markup with world-to-screen coordinate transformation.

`RendererRegistry` provides global resolution (`DEFAULT_RENDERER_REGISTRY.resolve(layer)`) with precedence:
1. Specialized layer types (`annotation`, `grid`, `contour`, `well_point`, `well`).
2. Explicit style renderer keywords (`categorized`, `graduated`, `single`).
3. Style structure detection (`style.ranges` -> `GraduatedRenderer`, `style.categories` -> `CategorizedRenderer`).
4. General layer types (`polygon`, `vector`, `facies`).
5. Fallback to `SingleSymbolRenderer`.

### 3.2 Built-in Renderers

| Renderer | `renderer_type` | Target Layers | Description |
|---|---|---|---|
| `SingleSymbolRenderer` | `single` | Generic vector, boundary lines, faults | Unified stroke and fill across all features. |
| `CategorizedRenderer` | `categorized` | Facies polygons, zone classifications | Value-based lookup matching attribute keys to fill colors. |
| `GraduatedRenderer` | `graduated` | Numerical factors, thickness/porosity ranges | Numeric interval binning (`ranges: list[tuple[float, float, str, str]]`). |
| `AnnotationRenderer` | `annotation` | Text labels, coordinate annotations, callouts | Renders styled text with font family, size, color, and arbitrary rotation angle. |
| `GridRenderer` | `grid` | Scalar grids, interpolated heatmaps | Smooth color ramp rasterization with embedded Base64 PNG and gradient legend stops. |
| `ContourRenderer` | `contour` | Isoline contours | Polyline stroke rendering with mid-point numeric elevation/factor text labels. |
| `WellSymbolRenderer` | `well_symbol` | Well locations | Standard oil & gas dual-circle well symbol with well name and value text. |

---

## 4. Cartographic Style Schema (`paleo_workbench/mapping/map_styles.py`)

Styles are defined as pure dataclasses without Qt imports to allow safe serialization, file storage (`save_style_library` / `load_style_library`), and cross-thread sharing.

### 4.1 Schema Components

- **`LinePattern`**: `SOLID`, `DASH` (4, 2), `DOT` (1, 2), `DASH_DOT` (4, 2, 1, 2), `FAULT` (6, 2), `BOUNDARY`.
- **`MarkerSymbol`**: `CIRCLE`, `SQUARE`, `TRIANGLE`, `DIAMOND`, `CROSS`, `STAR`, `WELL` (standard dual-ring well point).
- **`TextStyle`**: `field`, `size`, `color`, `font_family`, `bold`, `halo_color`, `halo_width`, `visible`.
- **`VectorStyle`**: Flat serializable dataclass with `fill`, `stroke`, `stroke_width`, `line_pattern`, `marker`, `marker_size`, `renderer`, `field`, `categories`, `ranges`, `labels`.
- **`STYLE_LIBRARY`**: Named presets for geological features (`facies`, `well`, `contour`, `formation_boundary`, `fault`, `line`, `annotation`, `label`).

---

## 5. QGIS Bridge Isolation & Render Backends (`map_render_backend.py`)

```
+--------------------------------------------------------------------+
|                    Domain Model (Pure Data)                        |
|        MapDocument -> MapLayer -> VectorFeature / Grid             |
+--------------------------------------------------------------------+
                                   │
                           to_snapshot()
                                   ▼
+--------------------------------------------------------------------+
|                Immutable Render Snapshot Boundary                  |
|          MapRenderSnapshot / MapLayerSnapshot (dataclasses)        |
+--------------------------------------------------------------------+
                  │                                  │
                  ▼                                  ▼
+------------------------------------+  +----------------------------+
| FallbackMapRenderBackend (Python)  |  | QgisMapRenderBackend (C++) |
| - Off-thread geometry rasterization|  | - Flat POD C++ specs       |
| - On-thread QPainter finalisation  |  | - Encapsulated QGIS objects|
| - Pure numpy & PySide6 painter     |  | - Zero domain type leakage |
+------------------------------------+  +----------------------------+
                  │                                  │
                  └─────────────────┬────────────────┘
                                    ▼
                         RenderFrame (RGBA bytes)
```

### 5.1 Snapshot Boundary Guarantee
Neither render backend acts as an authority for map data. `MapLayerSnapshot` and `MapRenderSnapshot` are immutable frozen dataclasses. Data edits in the workspace produce an incremented revision; backends rebuild cached geometries only when revisions change.

### 5.2 Threading & Safe Finalization
Geometry preprocessing runs safely on background worker threads (`_rasterize_frame_offthread`). Because Qt font engines must only be accessed on the GUI thread, text label placements are collected as lightweight `_LabelSpec` structs and finalized on the GUI thread during `_finalize_frame`, preventing font engine segfaults.

---

## 6. Canvas vs Composer Export Rendering Parity

Both screen interaction and print exports share identical geometry transformations:

1. **Letterbox Aspect Fitting (`fit_extent_to_aspect`)**:
   Units-per-pixel is kept strictly uniform in X and Y (`units_per_pixel = max(world_w / w, world_h / h)`). Circles remain true circles and scale bars remain accurate regardless of viewport aspect ratio.
2. **DPI Normalization**:
   Stroke widths, marker sizes, and label fonts are defined in logical pixels at 96 DPI and scaled proportionally by `dpi / 96.0` during high-resolution export.
3. **Map Composer Unification (`paleo_workbench/mapping/composer/renderer.py`)**:
   `MapComposerRenderer` renders `MapCompositionDocument` (containing `MAIN_MAP`, `LEGEND`, `NORTH_ARROW`, `SCALE_BAR`, `TITLE`, `ANNOTATION`) into crisp SVG documents using the exact same `DEFAULT_RENDERER_REGISTRY.resolve(layer).render_svg(layer, ctx)` pipeline.

---

## 7. Verification & Automated Test Matrix

The Mapping Engine 2.0 implementation is verified across 4 automated test suites:

| Test Module | Coverage Areas | Verification Assertions |
|---|---|---|
| `tests/test_mapping_engine_v2.py` | Layer hierarchy, Snapshotting, ColorRamps, RendererRegistry, GraduatedRenderer, AnnotationMapLayer, MapComposerRenderer | Verifies layer extent calculations, snapshot reconstruction, graduated SVG range binning, annotation text & rotation, pure data decoupling, and Composer multi-layer SVG export. |
| `tests/test_map_render_backend.py` | `FallbackMapRenderBackend`, `QgisMapRenderBackend`, Tile/generation culling, DPI scaling, Graduated & Annotation rasterization | Verifies frame caching, generation discard upon view change, raster basemap drawing, graduated color rendering in QPainter, and annotation text rendering. |
| `tests/test_map_export_consistency.py` | `UnifiedMapCanvas` screen-to-export consistency | Verifies exact RGB byte parity between screen frames and PNG exports, geometry aspect preservation during letterboxed exports, vector SVG/PDF generation, and provenance tracking. |
| `tests/test_geological_mapping_pipeline.py` | End-to-end geological pipeline | Verifies well factor extraction, Kriging/IDW interpolation, Marching Squares contouring, facies polygonization, and MapDocument assembly. |

---

## 8. Summary of Milestone 2 Deliverables

- [x] **GraduatedRenderer**: Implemented in `paleo_workbench/mapping/renderers.py` supporting value ranges, fill colors, stroke styling, legend items, and SVG rendering. Registered in `DEFAULT_RENDERER_REGISTRY`.
- [x] **AnnotationMapLayer & AnnotationRenderer**: Implemented in `paleo_workbench/mapping/layers.py` and `renderers.py` supporting text, coordinates, font size, color, rotation, and snapshot serialization.
- [x] **Pure-Data Layer Decoupling**: Verified zero UI widget or QGIS dependencies in domain models.
- [x] **QGIS Bridge Isolation**: Verified flat POD boundary and fallback rasterizer parity.
- [x] **Canvas & Composer Rendering Parity**: Verified shared letterboxing, DPI scaling, and vector SVG/PDF exports.
- [x] **Comprehensive Test Suite**: 100% test pass rate across `test_mapping_engine_v2.py`, `test_map_render_backend.py`, and `test_map_export_consistency.py`.
- [x] **Architecture Documentation**: Documented in `docs/development/core-convergence/mapping_engine.md`.
