# Paleo Workbench: Core Convergence Architecture Overview

**Document ID**: `CORE-CONV-00`  
**Version**: `1.0.0`  
**Status**: `Production / Complete`  
**Author**: Paleo Workbench Engineering Team  
**Scope**: Unified Core Architecture Convergence (Milestones 1–6, Features F1–F25)

---

## 1. Executive Summary

Paleo Workbench is a desktop scientific workstation designed for deep subsurface exploration, integrating paleogeographic map compilation, well log interpretation, 3D seismic volume visualization, and spatial data science into a cohesive desktop environment.

Prior to the Core Convergence initiative, capabilities across geological mapping, well analytics, and seismic visualization existed in loosely coupled modules with heterogeneous lifecycle patterns, separate rendering paradigms, and non-atomic project persistence. The **Core Convergence** milestone establishes five foundational pillars that unify the platform into an enterprise-grade scientific workstation:

1. **Runtime Stability Foundation**: Robust threading lifecycle (`OwnedWorkerJob`), thread-confined SQLite database connections in Write-Ahead Logging (WAL) mode, context-scoped deferred OpenGL resource deallocation, and memory-safe C++ pybind11 native extension bindings.
2. **Mapping Engine 2.0**: Pure-data decoupled `MapLayer` models, extensible `RendererRegistry` (single symbol, categorized, graduated, grid, contour, well point), isolated C++ QGIS bridge adapter (`QgisRenderBridge`), and unified 96 DPI Canvas and 300+ DPI print Composer export pipelines.
3. **End-to-End Geological Mapping Pipeline**: Complete automated analytical pipeline spanning well geological factor extraction, spatial interpolation (Ordinary Kriging, Inverse Distance Weighting), continuous `FactorGridResult` modeling, Marching Squares isovalue contouring, facies polygonization, and compilation into editable `MapDocument` instances.
4. **Unified Multi-View Coordination**: Shared event-driven `SelectionContext` with source tagging and echo-loop suppression, coupled with `CoordinateTransformHub` bridging 2D/3D Map CRS, Well Trajectory (XY, MD, TVD, TVDSS), and Seismic Grid (Inline, Crossline, TWT) coordinates.
5. **Project Data Lifecycle & Provenance**: Dual-tier storage (canonical `catalog.json` + SQLite query cache `catalog.sqlite`), strict raw dataset immutability (`0o444`, `ImmutableVersionError`), structured asset taxonomy (`RAW`, `DERIVED`, `INTERMEDIATE`, `OUTPUT`, `WORKING`, `TRASH`), cycle-safe lineage graph traversal (`build_lineage_chain`), and atomic crash-safe project persistence (`*.paleo.json`).

```
+----------------------------------------------------------------------------------------------------+
|                                    PALEO WORKBENCH MAIN SHELL                                      |
+----------------------------------------------------------------------------------------------------+
|  [Mapping Canvas 2.0]     |      [Well Log Engine]         |      [3D Seismic / Well-Tie]          |
|  - MapLayers & Styles     |      - Multi-track Composite   |      - Volume Slicing & Probes         |
|  - QGIS / Fallback Engine |      - Tops & Lithology Tracks |      - Dev Well Trajectories          |
|  - Canvas / Composer      |      - Curve Predictors        |      - Synthetic Seismograms          |
+---------------------------+--------------------------------+---------------------------------------+
|                                    CROSS-VIEW COORDINATION                                         |
|  * SelectionContext (Source-tagged active well, depth interval, seismic cursor, zero-echo sync)    |
|  * CoordinateTransformHub (Map CRS <---> Well XY/MD/TVD <---> Seismic Inline/Crossline/TWT)       |
+----------------------------------------------------------------------------------------------------+
|                                   GEOLOGICAL MAPPING PIPELINE                                      |
|  * Well Factor Extraction -> Kriging / IDW Interpolation -> Marching Squares Contouring            |
|  * Facies Polygonization -> Multi-Layer MapDocument -> SVG / PNG / PDF Export                      |
+----------------------------------------------------------------------------------------------------+
|                               PROJECT DATA LIFECYCLE & PROVENANCE                                  |
|  * Strict Raw Immutability (0o444, ImmutableVersionError)                                         |
|  * Dual-Tier Storage: Canonical JSON (catalog.json) + WAL SQLite Index (catalog.sqlite)            |
|  * Directed Lineage Graph (Input Version Tracking, Run IDs, Cycle-Safe BFS/DFS Traversal)         |
|  * Atomic Persistence & Backup Recovery (*.paleo.json <-> *.paleo.json.bak)                       |
+----------------------------------------------------------------------------------------------------+
|                                    RUNTIME STABILITY FOUNDATION                                    |
|  * OwnedWorkerJob (Interruptible QThread worker lifecycle, clean signals, safe closeEvent)        |
|  * Thread-Confined SQLite Connections (Dead-thread pruning, mutex re-entrancy)                    |
|  * Deferred GPU Deallocation (Context-bound OpenGL resource release queues)                        |
|  * GIL-Safe Native pybind11 C++ Extensions (Buffer protocol, RAII lifetime guards)                 |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Core Pillars Summary

### 2.1 Runtime Stability Foundation
The desktop runtime manages complex asynchronous operations including spatial grid interpolation, 3D volume slicing, and background catalog maintenance. The runtime architecture enforces four critical guarantees:
- **Thread Lifetime & Cancellation**: All asynchronous tasks execute inside `OwnedWorkerJob`, which encapsulates `QThread` and worker `QObject` instances, enforces explicit cross-thread moves (`worker.moveToThread`), emits typed signals, and guarantees thread termination and join prior to widget destruction.
- **SQLite Concurrency & WAL Confinement**: Database connections to `catalog.sqlite` and session databases are strictly thread-confined through a thread-local dictionary (`_conns: dict[int, sqlite3.Connection]`). Periodic pruning (`_prune_dead_threads`) reaps connections belonging to terminated worker threads, while WAL journal mode permits concurrent non-blocking reads during background maintenance writes.
- **Context-Bound OpenGL Destruction**: Native GPU textures, vertex buffers, and shaders are never released in non-rendering worker threads. Deallocations are queued to a context-bound deferred cleanup queue (`OpenGLCleanupQueue`), drained exclusively on the active render thread when a valid OpenGL context is current.
- **Memory-Safe C++ Native Extensions**: C++ extensions (`map_edit_core`, `qgis_render_bridge`) leverage pybind11 with explicit GIL release during heavy compute (`py::gil_scoped_release`) and GIL re-acquisition (`py::gil_scoped_acquire`) during Python callback dispatch, avoiding deadlocks and memory corruption.

### 2.2 Mapping Engine 2.0
The mapping system transitions from UI-coupled widgets to a pure data-model architecture:
- **Decoupled Layer Models**: Dataclasses (`VectorMapLayer`, `GridMapLayer`, `ContourMapLayer`, `WellPointMapLayer`, `PolygonMapLayer`, `AnnotationMapLayer`, `RasterMapLayer`) and `MapDocument` encapsulate pure spatial geometries and styling metadata with zero GUI dependencies.
- **Hierarchical Style & Renderer Registry**: `RendererRegistry` resolves layer rendering through pluggable renderers: `SingleSymbolRenderer`, `CategorizedRenderer`, `GraduatedRenderer` (quantile, equal interval, natural breaks), `GridRenderer` (linear, logarithmic colormaps), and `ContourRenderer`.
- **Isolated C++ QGIS Bridge**: High-performance cartographic rendering utilizes `QgisRenderBridge` via plain-old-data (POD) snapshot structures (`MapRenderSnapshot`), preventing QGIS internal C++ types from leaking into application models.
- **Canvas & Print Composer Parity**: A unified rendering backend guarantees identical visual outputs between interactive screen rendering (96 DPI) and publication-quality vector/raster exports (SVG, PNG, PDF at 300+ DPI).

### 2.3 End-to-End Geological Pipeline
The scientific workflow translates raw borehole measurements into spatial geological surfaces:
- **Factor Extraction**: Automated extraction and unit normalization of geological parameters (porosity, sandstone thickness, sand-to-gross ratio, total organic carbon) from well databases.
- **Spatial Interpolation**: High-performance 2D spatial estimation algorithms (Ordinary Kriging with spherical/exponential variogram fitting, and optimized Inverse Distance Weighting) producing validated `FactorGridResult` grid models with explicit CRS bounding boxes and nodata masks.
- **Marching Squares Contouring**: Continuous isovalue curve extraction supporting automatic interval binning and explicit user-specified levels, producing valid topological GeoJSON LineString geometries.
- **Facies Polygonization**: Automated threshold segmentation and vector polygon generation for geological zone boundaries.
- **MapDocument Assembly**: Multi-layer document compilation merging base raster grids, isovalue contours, facies polygons, well locations, and cartographic annotations.

### 2.4 Unified Multi-View Coordination
Synchronized scientific interpretation across geological domains without redundant recomputation:
- **Source-Tagged SelectionContext**: A centralized singleton broadcasts selection updates (active well ID, multiple well selections, depth intervals, 3D seismic inline/crossline/TWT cursor coordinates). Every event carries a `source_widget_id` that prevents infinite echo loops across views.
- **CoordinateTransformHub**: Bidirectional mathematical conversion between disparate coordinate spaces:
  - 2D/3D Geographic Map CRS (e.g. `EPSG:3857`, `EPSG:4326`, Projected UTM)
  - Well Trajectory Space (Surface X/Y, Measured Depth MD, True Vertical Depth TVD, Subsea TVDSS)
  - 3D Seismic Survey Space (Inline, Crossline, Two-Way Travel Time TWT)
- **Incremental Synchronization**: View updates mutate only viewport transformations and selection highlights without triggering full seismic volume or GIS raster reloads.

### 2.5 Project Data Lifecycle & Provenance
Scientific repeatability and data integrity across project lifecycles:
- **Strict Raw Immutability**: All imported source files placed in `<project>.artifacts/raw/` are protected with read-only filesystem bits (`0o444` / `0o400`). Modification attempts trigger `ImmutableVersionError`. Derived analyses operate strictly on copy-on-write working buffers.
- **Structured Asset Hierarchy**: Clear taxonomic separation across `RAW`, `DERIVED`, `INTERMEDIATE`, `OUTPUT`, `WORKING`, and `TRASH` stages.
- **Directed Lineage Graph**: Every generated artifact (`FactorGridResult`, `MapDocument`, contour export) tracks upstream inputs (`input_version_ids`) and execution provenance (`run_id`). Traversal algorithms (`build_lineage_chain`, `compute_summaries`) employ cycle-safe BFS/DFS to trace data origin back to raw source files.
- **Crash-Safe Atomic Persistence**: Project manifests (`*.paleo.json`) and catalog stores (`catalog.json`) utilize atomic temporary file writes, `fsync` barriers, and automatic fallback to `.bak` backups on abnormal termination recovery.

---

## 3. System Architecture Diagram

```
+----------------------------------------------------------------------------------------------------+
|                                    DESKTOP USER INTERFACE                                          |
|  +--------------------------+  +--------------------------+  +----------------------------------+  |
|  |     Mapping Canvas       |  |     Well Log View        |  |     3D Seismic / Tie View        |  |
|  |  (UnifiedMapCanvas)      |  |  (WellLogCanvas)         |  |  (Seismic3DCanvas)               |  |
|  +------------+-------------+  +------------+-------------+  +----------------+-----------------+  |
|               |                             |                                 |                    |
|               +-----------------------------+---------------------------------+                    |
|                                             |                                                      |
|                                             v                                                      |
|                          +-------------------------------------+                                   |
|                          |     SelectionContext & Event Hub    |                                   |
|                          +------------------+------------------+                                   |
|                                             |                                                      |
|                                             v                                                      |
|                          +-------------------------------------+                                   |
|                          |       CoordinateTransformHub        |                                   |
|                          |   Map CRS <-> Well <-> Seismic      |                                   |
|                          +-------------------------------------+                                   |
+---------------------------------------------+------------------------------------------------------+
                                              |
                                              v
+----------------------------------------------------------------------------------------------------+
|                                    DOMAIN CORE & ENGINES                                           |
|  +------------------------------------------------------+  +------------------------------------+  |
|  |                Mapping Engine 2.0                    |  |    Geological Mapping Pipeline     |  |
|  |  - MapDocument (Pure dataclass layer models)         |  |  - Factor Extraction Service       |  |
|  |  - LayerRenderer & RendererRegistry                  |  |  - Kriging & IDW Interpolators     |  |
|  |  - Canvas / Composer Exporters (SVG/PNG/PDF)         |  |  - Marching Squares Contouring     |  |
|  |  - QgisRenderBridge (Isolated C++ backend adapter)   |  |  - Facies Polygonization           |  |
|  +------------------------------------------------------+  +------------------------------------+  |
+---------------------------------------------+------------------------------------------------------+
                                              |
                                              v
+----------------------------------------------------------------------------------------------------+
|                                DATA LIFECYCLE & PROVENANCE                                         |
|  +-----------------------------------+  +-------------------------------------------------------+  |
|  |      DataCatalogService           |  |                  Lineage Graph Engine                 |  |
|  |  - Canonical Store (catalog.json) |  |  - Directed Provenance DAG (BFS / DFS Traversal)      |  |
|  |  - WAL Query Index (catalog.db)   |  |  - input_version_ids & run_id provenance tracking     |  |
|  |  - Raw Immutability (0o444 mode)  |  |  - Hops-to-raw summary & depth limit capping          |  |
|  +-----------------------------------+  +-------------------------------------------------------+  |
+---------------------------------------------+------------------------------------------------------+
                                              |
                                              v
+----------------------------------------------------------------------------------------------------+
|                                 RUNTIME & INFRASTRUCTURE                                           |
|  +-----------------------------------+  +-------------------------------------------------------+  |
|  |         OwnedWorkerJob            |  |              Native C++ Bindings (pybind11)           |  |
|  |  - Interruptible QThread Manager  |  |  - GIL-safe memory buffers & callbacks               |  |
|  |  - Safe closeEvent teardown       |  |  - Context-bound deferred OpenGL cleanup queues       |  |
|  +-----------------------------------+  +-------------------------------------------------------+  |
+----------------------------------------------------------------------------------------------------+
```

---

## 4. Milestone Matrix & Traceability

| Milestone | Scope & Title | Key Modules | Features Delivered | Status |
|---|---|---|---|---|
| **M1** | Runtime Stability Foundation | `paleo_workbench/ui/owned_worker_job.py`, `paleo_workbench/catalog/db.py`, `native/` | F1, F2, F3, F4, F5 | **COMPLETE** |
| **M2** | Mapping Engine 2.0 & Style System | `paleo_workbench/mapping/`, `paleo_workbench/ui/unified_map_canvas.py` | F6, F7, F8, F9, F10 | **COMPLETE** |
| **M3** | Geological Mapping Pipeline | `paleo_workbench/mapping/geological_pipeline/`, `paleo_workbench/workflow/` | F11, F12, F13, F14, F15 | **COMPLETE** |
| **M4** | Unified Multi-View Coordination | `paleo_workbench/viz/`, `paleo_workbench/ui/` | F16, F17, F18 | **COMPLETE** |
| **M5** | Project Data Lifecycle & Provenance | `paleo_workbench/catalog/`, `paleo_workbench/project/` | F19, F20, F21, F22 | **COMPLETE** |
| **M6** | Final Convergence, Verification & Delivery | `docs/development/core-convergence/`, `tests/`, `tests/e2e/` | F23, F24, F25 | **COMPLETE** |

---

## 5. Document Navigation

Detailed architectural specifications for each subsystem are provided in dedicated modules:
- [01_mapping_engine_v2.md](./01_mapping_engine_v2.md): Layer models, renderer hierarchy, style system, QGIS bridge isolation, canvas & print parity.
- [02_geological_pipeline.md](./02_geological_pipeline.md): Factor extraction, Kriging/IDW spatial interpolation, Marching Squares contouring, facies polygonization, MapDocument generation.
- [03_multiview_coordination.md](./03_multiview_coordination.md): SelectionContext with source tagging, CoordinateTransformHub, multi-view incremental sync.
- [04_data_lifecycle_provenance.md](./04_data_lifecycle_provenance.md): Raw dataset immutability (`0o444`, `ImmutableVersionError`), asset classification hierarchy, cycle-safe lineage graph traversal, atomic save & disaster recovery.
- [05_verification_report.md](./05_verification_report.md): Full regression results, 4-tier E2E matrix, adversarial hardening benchmarks, and release sign-off.
