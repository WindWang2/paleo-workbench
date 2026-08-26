# Paleo Workbench Core Convergence: System Architecture

**Author:** Runtime Stability & Native Safety Team (Worker M1)  
**Status:** Converged Baseline  
**Date:** 2026-08-25  

---

## 1. Executive Overview

**Paleo Workbench** is a high-performance scientific desktop workstation integrating paleogeographic mapping, 3D seismic volume visualization, well log analysis, and spatial geological modeling.

The **Core Convergence** initiative hardens the workstation into a unified, crash-resilient runtime with deterministic threading, strict thread-confined data caching, context-safe GPU resource reclamation, and hardware-accelerated C++20 extensions.

```
+-----------------------------------------------------------------------------------+
|                           Paleo Workbench Desktop UI                              |
|   +-------------------+  +-------------------+  +-------------------------------+ |
|   |   Mapping Canvas  |  |   Well Log View   |  |     3D Seismic / Horizons     | |
|   +---------+---------+  +---------+---------+  +---------------+---------------+ |
+-------------|----------------------|----------------------------|-----------------+
              |                      |                            |
              +----------------------+----------------------------+
                                     |
                         [SelectionContext Hub]
                    [CoordinateTransformHub (CRS/Z)]
                                     |
+------------------------------------+----------------------------------------------+
|                         Core Scientific Services                                 |
|  +-----------------------------+  +---------------------------------------------+ |
|  | GeologicalMappingService    |  | NativeEngineBackend                         | |
|  | - Factor extraction (well)  |  | - seismic_3d_core (Coherence, Marching Cubes) |
|  | - Kriging & IDW grids       |  | - well_log_core (LOD Downsampling, LAS)      | |
|  | - Marching Squares contour  |  | - map_edit_core (Hit Test, Snapping, Topo)  | |
|  | - Facies polygonization     |  | - grid_render_core (SIMD Color Mapping)     | |
|  +-----------------------------+  +---------------------------------------------+ |
+------------------------------------+----------------------------------------------+
                                     |
+------------------------------------+----------------------------------------------+
|                        Runtime Stability Foundation                               |
|  +----------------------+  +----------------------+  +--------------------------+ |
|  | OwnedWorkerJob       |  | CatalogIndex (SQLite)|  | Context-Scoped Deferred  | |
|  | - Cooperative worker |  | - Thread-isolated    |  |   OpenGL Deletion Queue  | |
|  | - Detached keeper    |  | - ThreadSafeSession  |  | - Context-safe flush     | |
|  | - Interruption check |  | - WAL concurrency    |  | - Zero VRAM leaks        | |
|  +----------------------+  +----------------------+  +--------------------------+ |
+-----------------------------------------------------------------------------------+
```

---

## 2. Six Converged Architecture Pillars

### 2.1 Pillar 1: Runtime Stability Foundation
- **Cooperative Thread Management**: All asynchronous background tasks execute via `OwnedWorkerJob`, encapsulating a parentless `QObject` worker relocated to an owned `QThread` (`moveToThread`). Results are delivered strictly across thread boundaries via `Qt.ConnectionType.QueuedConnection`. Heavy CPU loops poll `isInterruptionRequested()`. Dialogs and host widgets override `closeEvent` and `reject` to cleanly join or detach running threads into `DetachedJobKeeper`.
- **Thread-Confined SQLite Indexing**: `CatalogIndex` provides a high-throughput, rebuildable query cache over canonical `catalog.json`. Connections are strictly thread-local, protected by re-entrant mutexes, and operate in `PRAGMA journal_mode=WAL`. The `ThreadSafeCatalogSession` context manager guarantees that worker thread connections are disposed upon task exit, while `_prune_dead_threads()` monitors thread liveness and OS task states.
- **Context-Scoped Deferred OpenGL Resource Management**: GPU resources (textures, shader programs, VBOs) destroyed during GUI events or background teardowns are queued into context-bound deletion buckets (`_CONTEXT_PENDING_TEXTURE_DELETES`, `_CONTEXT_PENDING_PROGRAM_DELETES`). Deallocations are flushed during `paintGL` only when the matching `QOpenGLContext` is active.
- **C++ Native Extension Safety**: Pybind11 modules (`seismic_3d_core`, `well_log_core`, `map_edit_core`, `grid_render_core`, `layer_model_core`) enforce GIL release (`py::gil_scoped_release`) during computation, acquire GIL (`py::gil_scoped_acquire`) for callbacks, validate memory buffer dimensions, and export exact build metadata (`__version__`).

### 2.2 Pillar 2: Mapping Engine 2.0
- **Decoupled MapLayer Models**: Dataclass layer models (`VectorMapLayer`, `GridMapLayer`, `ContourMapLayer`, `WellPointMapLayer`, `PolygonMapLayer`, `AnnotationMapLayer`, `RasterMapLayer`) and `MapDocument` maintain zero dependency on Qt widgets.
- **Extensible Renderer Registry**: Pluggable renderers (`SingleSymbolRenderer`, `CategorizedRenderer`, `GraduatedRenderer`, `GridRenderer`, `ContourRenderer`, `WellSymbolRenderer`) handle vector and raster rendering.
- **Backend Isolation & Export Parity**: Shared rendering rules drive interactive canvas painting and high-resolution Composer exports (PNG, SVG, PDF). An isolated QGIS C++ adapter (`QgisRenderBridge`) provides optional native cartography without domain model coupling.

### 2.3 Pillar 3: Geological Mapping Pipeline
- **End-to-End Analysis Workflow**: Extraction of well geological factors (porosity, sandstone thickness, TOC, formation tops) -> spatial interpolation via Ordinary Kriging and IDW -> structured `FactorGridResult` -> Marching Squares contour leveling -> facies zone polygonization -> editable multi-layer `MapDocument`.

### 2.4 Pillar 4: Unified Multi-View Coordination
- **Central SelectionContext**: Synchronizes active well selections, depth intervals, and seismic cursors across 2D Map Canvas, Well Log View, and 3D Seismic views with source widget tagging to prevent event recursion.
- **CoordinateTransformHub**: Bidirectional transformations between Map CRS coordinates, Well Trajectory (XY, MD, TVD, TVDSS), and Seismic volume grids (Inline, Crossline, TWT).

### 2.5 Pillar 5: Project Data Lifecycle & Provenance
- **Dataset Immutability**: Raw scientific assets are strictly read-only (`chmod 0o444`, `ImmutableVersionError`).
- **Asset Hierarchy & Lineage**: Strict stages (Raw, Derived, Intermediate, Output, Working, Trash) with full lineage DAG tracking (`build_lineage_chain`) linking outputs back to source parameters and input data versions.
- **Atomic Persistence**: Reliable project save/reopen (`*.paleo.json`) with rollback safety and automatic query cache recovery.

### 2.6 Pillar 6: Infrastructure & Build Control
- **CPython 3.12 Unification**: Strict interpreter alignment (`>=3.12,<3.13`) preventing ABI mismatch.
- **Bounded Parallel Compilation**: Enforced `CMAKE_BUILD_PARALLEL_LEVEL=2` during C++ builds to prevent system memory exhaustion.
- **Multi-Tier Testing**: Comprehensive automated testing from feature contracts (Tier 1) through boundary conditions (Tier 2), cross-subsystem interactions (Tier 3), real-world geological scenarios (Tier 4), and adversarial stress testing (Tier 5).

---

## 3. Subsystem Interface Contracts

| Interface | Provider | Consumer | Contract |
|---|---|---|---|
| `OwnedWorkerJob` | `paleo_workbench.ui.owned_worker_job` | UI Dialogs, Pages | Non-blocking execution, queued result slots, timeout shutdown, detached thread adoption |
| `CatalogIndex.session()` | `paleo_workbench.catalog.db` | Workers, Services | Thread-confined SQLite handle, WAL mode, deterministic cleanup on block exit |
| `queue_gl_texture_delete` | `geoviz_seismic.renderer_3d` | GL Items | Context-bound deferred texture deallocation flushed during active paintGL |
| `NativeEngineBackend.dispatch` | `paleo_workbench.native_backend` | Services, Pipelines | Dynamic dispatch to accelerated C++ extension or byte-identical pure-Python fallback |
