# Project: Paleo Workbench Core Convergence

## Architecture
Paleo Workbench is a unified desktop scientific workstation integrating geological mapping, well log analysis, 3D seismic visualization, and spatial data science. The core convergence architecture consists of:
1. **Runtime Stability Layer**: `OwnedWorkerJob` thread lifecycle management, thread-confined SQLite database sessions in WAL mode, context-scoped deferred OpenGL resource deallocation, and GIL-safe pybind11 C++ bindings.
2. **Mapping Engine 2.0**: Pure-data decoupled `MapLayer` models (`VectorMapLayer`, `GridMapLayer`, `ContourMapLayer`, `WellPointMapLayer`, `PolygonMapLayer`, `AnnotationMapLayer`, `RasterMapLayer`) and `MapDocument`, extensible `RendererRegistry` (`SingleSymbolRenderer`, `CategorizedRenderer`, `GraduatedRenderer`, `GridRenderer`, `ContourRenderer`, `WellSymbolRenderer`), isolated QGIS C++ backend adapter (`QgisRenderBridge`), and unified Canvas/Composer rendering pipelines.
3. **Geological Mapping Pipeline**: End-to-end scientific workflow: well factor extraction (`GeologicalMappingService`), spatial interpolation (Ordinary Kriging, IDW) producing structured `FactorGridResult` objects, Marching Squares contouring (auto/fixed intervals), facies zone polygonization, and editable `MapDocument` compilation.
4. **Unified Multi-View Coordination**: Central `SelectionContext` managing cross-view selections (active well, depth intervals, seismic cursors) with source tagging to prevent echo loops, coupled with `CoordinateTransformHub` bridging Map CRS, Well Trajectory (XY, MD, TVD, TVDSS), and Seismic Grid (Inline, Crossline, TWT) coordinates.
5. **Project Data Lifecycle & Provenance**: Dual-tier storage (canonical `catalog.json` + SQLite query cache `catalog.sqlite`), strict raw dataset immutability (`chmod 0o444`, `ImmutableVersionError`), asset hierarchy (RAW, DERIVED, INTERMEDIATE, OUTPUT, WORKING, TRASH), cycle-safe lineage graph traversal (`build_lineage_chain`), and atomic project save/reopen persistence.
6. **Infrastructure & Delivery**: Worktree `feat/core-convergence`, bounded compilation (`CMAKE_BUILD_PARALLEL_LEVEL=2`), unified Python 3.12 environment, docs in `docs/development/core-convergence/`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Worker Lifecycle & Cancellation | `OwnedWorkerJob` lifecycle, interruptible worker threads in dialogs, safe teardown | M1 | Survey R1 |
| F2 | SQLite Thread Confinement | Thread-confined connections with robust cleanup for exited Qt worker threads | M1 | Survey R1 |
| F3 | Deferred OpenGL Cleanup | Context-scoped deferred GPU resource deletion queue | M1 | Survey R1 |
| F4 | Native C++ pybind11 Safety | GIL safety, memory buffers, and version metadata in `map_edit_core` | M1 | Survey R1 |
| F5 | Infrastructure & Build Control | Bounded parallel build (`CMAKE_BUILD_PARALLEL_LEVEL=2`), worktree setup, docs | M1 | Survey R6 |
| F6 | Decoupled MapLayer Models | Pure dataclass Layer models & `MapDocument` with zero UI widget dependencies | M2 | Survey R2 |
| F7 | Graduated & Style Renderers | `GraduatedRenderer` implementation and full style system support | M2 | Survey R2 |
| F8 | Annotation Layer Support | Explicit `AnnotationMapLayer` model and renderer support | M2 | Survey R2 |
| F9 | QGIS Bridge Backend Isolation | POD-based C++ bridge with zero domain model type leakage | M2 | Survey R2 |
| F10 | Canvas & Export Parity | Shared rendering logic between Map Canvas and Composer/Exporters (SVG/PNG/PDF) | M2 | Survey R2 |
| F11 | Well Factor Extraction | Automated extraction of geological factors (porosity, thickness, tops) | M3 | Survey R3 |
| F12 | Spatial Interpolation & Grid Result | Kriging & IDW algorithms outputting structured `FactorGridResult` | M3 | Survey R3 |
| F13 | Marching Squares Contouring | Contouring with automatic and fixed-interval leveling | M3 | Survey R3 |
| F14 | Facies Polygonization | Reclassification and polygon generation for geological zones | M3 | Survey R3 |
| F15 | Factor MapDocument Generation | Integration of Grid, Contour, Well, and Polygon layers into editable MapDocument | M3 | Survey R3 |
| F16 | SelectionContext Engine | Shared selection context (wells, depth ranges, seismic cursors) with source tagging | M4 | Survey R4 |
| F17 | CoordinateTransformHub | Bidirectional coordinate transforms (Map CRS <-> Well XY/MD/TVD <-> Seismic IL/XL/TWT) | M4 | Survey R4 |
| F18 | Incremental Multi-View Sync | Map <-> Well Log <-> Seismic synchronization without full volume/map reloads | M4 | Survey R4 |
| F19 | Raw Dataset Immutability | Enforce read-only permissions (`0o444`) and `ImmutableVersionError` on RAW assets | M5 | Survey R5 |
| F20 | Asset Hierarchy & Storage | Structured storage layout (Raw, Derived, Intermediate, Output, Working, Trash) | M5 | Survey R5 |
| F21 | Lineage Graph & Provenance | Lineage chain tracking from raw data through factors to grids and MapDocuments | M5 | Survey R5 |
| F22 | Project Persistence & Reopen | Atomic project save (`*.paleo.json`), clean session teardown, and asset recovery | M5 | Survey R5 |
| F23 | E2E 4-Tier Test Suite Pass | 100% pass across Tier 1, Tier 2, Tier 3, and Tier 4 acceptance tests | M6 | Survey R6 |
| F24 | Adversarial Coverage Hardening | Tier 5 Challenger stress tests and edge case coverage | M6 | Survey R6 |
| F25 | Convergence Documentation & PR | Complete documentation in `docs/development/core-convergence/` & clean PR | M6 | Survey R6 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Runtime Stability & Native Safety Foundation | F1, F2, F3, F4, F5 | none | DONE |
| M2 | Mapping Engine 2.0 & Styling System | F6, F7, F8, F9, F10 | none | DONE |
| M3 | Geological Mapping Pipeline | F11, F12, F13, F14, F15 | M2 | DONE |
| M4 | Unified Multi-View Coordination | F16, F17, F18 | M2 | DONE |
| M5 | Project Data Lifecycle & Provenance | F19, F20, F21, F22 | M3 | DONE |
| M6 | Final Convergence, E2E Verification & Delivery | F23, F24, F25 | M1, M2, M3, M4, M5 | DONE |

## Interface Contracts

### 1. Runtime & Worker Thread Contract
- `OwnedWorkerJob`: Accepts `worker: QObject`, manages `QThread` lifecycle, forces `worker.moveToThread(thread)`, emits typed PyQt/PySide signals, handles `closeEvent` and cancel gracefully.
- `CatalogIndex`: Thread-local connection pool guarded by re-entrant mutex. Worker threads release connection on termination or use scoped session context manager.

### 2. MapLayer & Renderer Contract
- `MapLayer`: Pure dataclass `id: str`, `name: str`, `layer_type: str`, `extent: tuple[float, float, float, float]`, `crs: str`, `visible: bool`, `opacity: float`, `style: dict | VectorStyle`, `metadata: dict`.
- `LayerRenderer`: `render(layer: MapLayer, painter: QPainter, ctx: RenderContext)` and `render_svg(layer: MapLayer, ctx: SvgRenderContext) -> list[str]`.
- `RendererRegistry`: `register(renderer_type: str, renderer: LayerRenderer)` and `resolve(layer: MapLayer) -> LayerRenderer`.

### 3. SelectionContext & Coordinate Hub Contract
- `SelectionContext`: `active_well_id: str | None`, `selected_well_ids: list[str]`, `depth_range: tuple[float, float] | None`, `seismic_cursor: tuple[int, int, float] | None`, `source_widget_id: str | None`. Emits `selection_changed(SelectionContext)`.
- `CoordinateTransformHub`:
  - `map_to_well(x: float, y: float) -> str | None` (nearest well)
  - `well_depth_to_map(well_id: str, md: float) -> tuple[float, float, float]` (x, y, tvd)
  - `seismic_to_map(il: int, xl: int, twt: float) -> tuple[float, float, float]` (x, y, z)
  - `map_to_seismic(x: float, y: float, z: float) -> tuple[int, int, float]` (il, xl, twt)

### 4. Data Catalog & Lineage Contract
- `DataCatalogService.register_run(run: DataRun) -> str` (run_id)
- `DataCatalogService.create_version(asset_id: str, stage: DataStage, source_path: Path, run_id: str | None, tags: dict) -> DataVersion`
- Lineage: Every `FactorGridResult` and `MapDocument` stores `input_version_ids: list[str]` and `run_id: str`.

## Code Layout
- `paleo_workbench/ui/owned_worker_job.py`: Thread management & worker lifecycle
- `paleo_workbench/catalog/`: Data catalog, SQLite DB, storage, lineage graph
- `paleo_workbench/mapping/`: Layers, renderers, map styles, render backends, composer
- `paleo_workbench/mapping/geological_pipeline/`: Factor extraction, Kriging/IDW interpolator, Marching Squares contouring, polygonization
- `paleo_workbench/viz/`: SelectionContext, coordinate hub, multi-view hosts
- `native/`: Native C++ pybind11 extensions
- `geo-viz-engine/`: Core GIS & 3D seismic rendering engine
- `well-log-engine/`: Native well log rendering & session engine
- `tests/`: Unit, integration, and E2E regression test suites
- `docs/development/core-convergence/`: Architecture documentation and verification reports
