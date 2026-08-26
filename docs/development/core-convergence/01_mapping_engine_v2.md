# Mapping Engine 2.0 & Styling Architecture

**Document ID**: `CORE-CONV-01`  
**Version**: `1.0.0`  
**Status**: `Production / Complete`  
**Author**: Paleo Workbench Engineering Team  
**Scope**: Features F6, F7, F8, F9, F10 (Decoupled Layer Models, Style Renderers, QGIS Bridge Isolation, Canvas/Print Parity)

---

## 1. Overview & Architectural Principles

Mapping Engine 2.0 refactors the cartographic and spatial visualization stack of Paleo Workbench from widget-bound drawing routines into a pure data-model architecture. The engine separates concerns across four distinct tiers:
1. **Pure Data Layer Models & MapDocument**: Dataclass representations of spatial entities with zero PySide6/Qt widget dependencies, supporting JSON serialization, cloning, and snapshotting.
2. **Pluggable Renderer Hierarchy & Style System**: Flexible styling models (single symbol, categorized, graduated, isovalue contours, scalar grids) managed via an extensible `RendererRegistry`.
3. **Isolated C++ Backend Bridge (QGIS Bridge)**: High-performance C++ rendering via a Plain-Old-Data (POD) bridge (`QgisRenderBridge`) that guarantees zero QGIS internal types leak into domain logic.
4. **Unified Canvas & Print Export Parity**: Shared coordinate transformation, symbol sizing, and color ramp rendering ensuring exact visual parity between 96 DPI interactive canvas displays and 300+ DPI high-resolution Composer exports (SVG, PNG, PDF).

```
+-----------------------------------------------------------------------------------+
|                                 APPLICATION LAYER                                 |
|         MapCanvasPanel / UnifiedMapCanvas           MapComposerDialog             |
+------------------------------------+----------------------------------------------+
                                     |
                                     v
+-----------------------------------------------------------------------------------+
|                                 DOMAIN LAYER                                      |
|  +-----------------------------------------------------------------------------+  |
|  |             MapDocument (id, name, crs, extent, layers: list[MapLayer])      |  |
|  +-----------------------------------------------------------------------------+  |
|  |  MapLayer Subclasses:                                                       |  |
|  |  - VectorMapLayer (points, linestrings, polygons, FeatureCollection)        |  |
|  |  - GridMapLayer (FactorGridResult / 2D numpy scalar matrix, colormap)        |  |
|  |  - ContourMapLayer (levels, GeoJSON MultiLineString geometries)             |  |
|  |  - WellPointMapLayer (well heads, trajectories, symbols, labels)            |  |
|  |  - PolygonMapLayer (facies zones, fill patterns, boundaries)                |  |
|  |  - AnnotationMapLayer (text callouts, leader lines, rich typography)        |  |
|  |  - RasterMapLayer (georeferenced images, RGB/RGBA bands)                    |  |
|  +-----------------------------------------------------------------------------+  |
+------------------------------------+----------------------------------------------+
                                     |
                                     v
+-----------------------------------------------------------------------------------+
|                              RENDERER REGISTRY                                    |
|  +-----------------------------------------------------------------------------+  |
|  |  LayerRenderer Interface:                                                   |  |
|  |  - render(layer, painter: QPainter, ctx: RenderContext) -> None             |  |
|  |  - render_svg(layer, ctx: SvgRenderContext) -> list[str]                    |  |
|  +-----------------------------------------------------------------------------+  |
|  |  Concrete Renderers:                                                        |  |
|  |  - SingleSymbolRenderer (uniform vector strokes & fills)                    |  |
|  |  - CategorizedRenderer (discrete facies/lithology value mapping)           |  |
|  |  - GraduatedRenderer (quantile, equal interval, natural breaks)             |  |
|  |  - GridRenderer (linear, logarithmic, clipped scalar colormaps)             |  |
|  |  - ContourRenderer (indexed line weights, labels, major/minor styling)      |  |
|  |  - WellSymbolRenderer (standardized geological well symbols & collars)      |  |
|  +-----------------------------------------------------------------------------+  |
+------------------------------------+----------------------------------------------+
                                     |
                 +-------------------+-------------------+
                 |                                       |
                 v                                       v
+----------------------------------+   +------------------------------------+
|       INTERNAL RENDERER          |   |     QGIS C++ BRIDGE ADAPTER        |
|  - QPainter Vector Pipeline      |   |  - MapRenderSnapshot (Pure POD)    |
|  - Pure-Python / NumPy Grid Mesh |   |  - Native QgisRenderBridge C++     |
|  - SvgPath / Vector Generators   |   |  - High-throughput rasterization   |
+----------------------------------+   +------------------------------------+
```

---

## 2. Decoupled MapLayer & MapDocument Models (Feature F6)

All spatial entities inherit from the pure dataclass `MapLayer`, located in `paleo_workbench/mapping/layers.py`.

### 2.1 Layer Model Hierarchy
- **`MapLayer`**: Base dataclass defining `id: str`, `name: str`, `layer_type: str`, `extent: tuple[float, float, float, float]`, `crs: str`, `visible: bool`, `opacity: float`, `style: dict`, `metadata: dict`, `source_version_id: str | None`.
- **`VectorMapLayer`**: Encapsulates vector features formatted as standard GeoJSON feature dictionaries. Supports spatial filtering and bounding box recalculation.
- **`GridMapLayer`**: Encapsulates continuous spatial scalar fields (`FactorGridResult`), storing `grid_x: np.ndarray`, `grid_y: np.ndarray`, `grid_z: np.ndarray`, `colormap: str`, and `z_range: tuple[float, float]`.
- **`ContourMapLayer`**: Encapsulates isovalue contour curves, storing extracted line segments, level classifications (major/minor), elevation values, and label placements.
- **`WellPointMapLayer`**: Encapsulates well locations, storing surface X/Y coordinates, well IDs, operator names, well types (exploration, appraisal, production), and trajectory point geometries.
- **`PolygonMapLayer`**: Encapsulates geological facies and reservoir zone polygons with topological border sharing and fill hatching rules.
- **`AnnotationMapLayer`**: Encapsulates textual annotations, scale bars, north arrows, and callout arrows with multi-line CJK text and angle rotation support.
- **`RasterMapLayer`**: Encapsulates external georeferenced raster datasets (GeoTIFF, PNG with world files).

### 2.2 MapDocument Model
`MapDocument` serves as the container for multi-layer cartographic compositions:
```python
@dataclass
class MapDocument:
    id: str
    name: str
    crs: str = "EPSG:3857"
    extent: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    layers: list[MapLayer] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    
    @property
    def input_version_ids(self) -> list[str]:
        """Aggregate input data version IDs across metadata and child layers."""
        ...
```
`MapDocument` provides methods for adding, removing, reordering layers, recomputing collective spatial extents (`recompute_extent()`), serializing to JSON descriptors (`to_dict()`), and reconstructing from JSON (`from_dict()`).

---

## 3. Style System & Renderer Registry (Features F7, F8)

The styling subsystem (`paleo_workbench/mapping/renderers/`) decouples layer data from cartographic presentation.

### 3.1 Renderer Hierarchy
- **`LayerRenderer`**: Abstract base class defining:
  - `render(layer: MapLayer, painter: QPainter, ctx: RenderContext) -> None`
  - `render_svg(layer: MapLayer, ctx: SvgRenderContext) -> list[str]`
- **`SingleSymbolRenderer`**: Applies uniform stroke color, width, dash patterns, and fill brush across all features in a vector layer.
- **`CategorizedRenderer`**: Maps categorical attributes (e.g. `facies_type = "delta_front"`, `"turbidite_channel"`) to discrete symbol and color assignments.
- **`GraduatedRenderer`**: Classifies numerical attributes (e.g. `thickness`, `permeability`) into range bins using standard statistical classification methods:
  - **Quantile**: Equal count distribution per bin.
  - **Equal Interval**: Uniform numeric range subdivision ($\frac{\max - \min}{N}$).
  - **Natural Breaks (Jenks)**: Minimizes intra-class variance and maximizes inter-class variance.
- **`GridRenderer`**: Renders 2D scalar grids using continuous and discretized color ramps (`viridis`, `plasma`, `terrain`, `seismic`), with support for logarithmic scaling, alpha masks, and bilinear/bicubic resampling.
- **`ContourRenderer`**: Renders isovalue contour curves, distinguishing major (index) contours with heavier line weights and annotations from minor contours.
- **`WellSymbolRenderer`**: Standardizes geological well symbols (e.g. dry hole, oil producer, gas show, abandoned) according to industry cartographic symbology standards.

### 3.2 RendererRegistry
`RendererRegistry` manages the binding between layer types, style configurations, and concrete renderers:
```python
registry = RendererRegistry()
registry.register("single_symbol", SingleSymbolRenderer())
registry.register("categorized", CategorizedRenderer())
registry.register("graduated", GraduatedRenderer())
registry.register("grid", GridRenderer())
registry.register("contour", ContourRenderer())
registry.register("well_symbol", WellSymbolRenderer())

renderer = registry.resolve(layer)
renderer.render(layer, painter, render_context)
```

---

## 4. QGIS Bridge Backend Isolation (Feature F9)

To achieve native-speed rendering while avoiding heavy framework lock-in, Paleo Workbench isolates the QGIS C++ rendering backend behind a strict POD boundary (`native/qgis_render_bridge`).

### 4.1 Plain-Old-Data (POD) Contract
The interface between Python and the native QGIS bridge is defined exclusively via `MapRenderSnapshot`:
```python
@dataclass
class LayerSnapshot:
    layer_id: str
    layer_type: str  # "vector", "raster", "grid", "contour"
    source_uri: str
    crs: str
    opacity: float
    style_json: str  # Serialized QML or standard style dictionary

@dataclass
class MapRenderSnapshot:
    width_px: int
    height_px: int
    dpi: float
    extent: tuple[float, float, float, float]
    crs: str
    background_color: str
    layers: list[LayerSnapshot]
```
### 4.2 C++ Bridge Implementation
The C++ bridge (`native/qgis_render_bridge/src/qgis_bridge.cpp`) receives `MapRenderSnapshot`, instantiates a headless `QgsMapSettings`, configures layers, and renders directly into a shared memory image buffer (`QImage` or raw RGBA byte buffer) returned to Python via pybind11 buffer protocol without copying.
- **Zero Type Leakage**: No `QgsVectorLayer`, `QgsMapLayer`, or `QgsCoordinateReferenceSystem` pointers cross into Python domain code.
- **Graceful Fallback**: If `qgis_render_bridge` is not compiled or fails initialization, `RenderBackendFactory` automatically falls back to `InternalQtRenderer` without interrupting user workflows.

---

## 5. Canvas & Print Export Parity (Feature F10)

Cartographic workflows require that what the geoscientist sees on the interactive canvas precisely matches the final high-resolution print publication.

### 5.1 Coordinate Transformation & DPI Normalization
Both `UnifiedMapCanvas` (interactive viewport) and `MapComposer` (print exporter) share the unified `RenderContext`:
```python
@dataclass
class RenderContext:
    target_rect: QRectF
    extent: tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    dpi: float = 96.0
    scale_factor: float = 1.0  # (dpi / 96.0)
    device_pixel_ratio: float = 1.0
```
- **World-to-Screen Mapping**:
  $$X_{\text{screen}} = (X_{\text{world}} - \min X) \cdot \frac{W_{\text{target}}}{\max X - \min X}$$
  $$Y_{\text{screen}} = (\max Y - Y_{\text{world}}) \cdot \frac{H_{\text{target}}}{\max Y - \min Y}$$
- **Scale-Independent Line & Font Sizing**: Stroke widths, dash spacings, and font sizes are scaled by `scale_factor = dpi / 96.0`, ensuring crisp vector text and line styling on 300+ DPI exports.

### 5.2 Multi-Format Exporters
- **SVG Export (`render_svg`)**: Generates standards-compliant SVG documents with semantic grouping (`<g id="layer_id">`), CSS styling, and embedded vector glyphs.
- **PNG Export (`export_png`)**: High-resolution rasterization supporting antialiasing, transparency, and DPI metadata tagging.
- **PDF Export (`export_pdf`)**: Multi-page vector PDF generation embedding vector geometry, true font glyphs, and cartographic chrome (scale bar, north arrow, legend).

---

## 6. Verification Summary

The Mapping Engine 2.0 implementation is verified through dedicated test suites:
- `tests/test_mapping_engine_v2.py`: Layer model serialization, extent recomputation, and registry resolution.
- `tests/test_map_styles.py` & `tests/test_map_renderers.py`: Graduated classification math (Jenks, Quantile), Categorized styling, and SVG emission.
- `tests/e2e/test_tier1_features.py` (F6–F10): Isolated feature unit tests.
- `tests/e2e/test_tier2_boundaries.py`: Singular extents, empty feature collections, collinear geometries, nodata grids.
- `tests/e2e/test_tier3_interactions.py`: Multi-layer composition, QGIS bridge fallback, dynamic style updates.
- `tests/e2e/test_tier4_scenarios.py`: Full cartographic export scenarios to SVG/PNG/PDF.
