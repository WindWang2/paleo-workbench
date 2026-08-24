# Project: Paleogeography Workbench Remediation (51 Audit Issues #962–#1012)

## Architecture
- **Desktop UI Layer (`paleo_workbench/ui`)**: PySide6 widgets, pages (`DataPage`, `StratigraphyCorrelationPage`, `MappingPage`, `GeologicalModeling3DPage`), project controller, worker lifecycle managers.
- **Domain & Model Layer (`paleo_workbench/model`)**: Project metadata, domain configs, data contracts, business adapters.
- **Storage & Catalog Layer (`paleo_workbench/catalog`)**: SQLite indexing, SHA-256 deduplication, garbage collection, atomic file swaps.
- **Mapping & GIS Engine (`paleo_workbench/mapping`)**: Vector/raster map scenes, Marching Squares isoline extraction, shapely polygonization, Map Composer SVG export.
- **Visualization Subsystems (`geo-viz-engine`, `well-log-engine`)**:
  - `geoviz_seismic`: 2D profile view, 3D OpenGL volume/slice renderer, instanced wiggle trace renderer.
  - `geoviz_well_log`: Multi-track well curve rendering, zoom/pan interaction.
  - `geoviz_well_seismic_3d`: Joint 3D scene, seismic fence curtains, two-sided lighting.
  - `geoviz_plots`: Factor LOO analysis, Kriging spatial interpolation, CRS transforms.
- **Native Acceleration Layer (`native/`)**: C++ pybind11 modules (`seismic_3d_core`, `layer_model_core`, `grid_render_core`, `well_log_core`, `qgis_render_bridge`).

## Feature Inventory
Every issue from the master audit is inventoried below with its assigned milestone. No feature is unassigned.

| # | Issue | Feature / Defect Description | Milestone | Source |
|---|-------|------------------------------|-----------|--------|
| 1 | #962 | `DataPage._shutdown_workers()` complete worker list | M1 | Audit R1-04 |
| 2 | #963 | Move `PreviewSettings` to domain layer to eliminate UI inverted imports | M4 | Audit R1-01 |
| 3 | #964 | Enforce native acceleration checks through `NativeBackendService` | M4 | Audit R1-02 |
| 4 | #965 | Disconnect signals in `OwnedWorkerJob.shutdown()` before join | M1 | Audit R1-03 |
| 5 | #966 | `StratigraphyCorrelationPage` and `MappingPage` aggregated worker shutdown | M1 | Audit R1-05 |
| 6 | #967 | Remove blocking thread joins from `__del__` finalizers | M1 | Audit R1-06 |
| 7 | #968 | Bounded LRU cache for seismic slice loader | M4 | Audit R1-08 |
| 8 | #969 | Dynamic memory management for preview rendering | M4 | Audit R1-08b |
| 9 | #970 | Cancellation event in `ProjectController` catalog maintenance thread | M1 | Audit R1-09 |
| 10 | #971 | Catch `sqlite3.Error` during cross-thread session teardown in `CatalogIndex.close()` | M1 | Audit R1-10 |
| 11 | #972 | Atomic file swap replacement for project saves | M1 | Audit R1-11 |
| 12 | #973 | Replace silent exception passes with structured logging | M4 | Audit R1-12 |
| 13 | #974 | OpenGL texture delete queueing when context is inactive in `DualGLVolumeItem.clean()` | M1 | Audit R2-BUG-01 |
| 14 | #975 | 3D normal map gradient axis mapping `[-d_inline, -d_crossline, -d_time]` & memory optimization | M2 | Audit R2-BUG-02 |
| 15 | #976 | Polyline click coordinate transformation with zoom/pan matrix in `ProfileVD` | M2 | Audit R2-BUG-03 |
| 16 | #977 | Replace synthetic striping with Marching Squares isolines and shapely facies polygons | M2 | Audit R2-BUG-04 |
| 17 | #978 | Dynamic SVG layer rendering and legend generation in Map Composer | M2 | Audit R2-BUG-05 |
| 18 | #979 | Connect GPU instanced `WiggleTraceRenderer` in `ProfileWidget` | M2 | Audit R2-BUG-06 |
| 19 | #980 | Descending inline binary search direction handling | M2 | Audit R2-BUG-07 |
| 20 | #981 | Reset active texture to `GL_TEXTURE0` in `GLImageLutItem.paint()` | M2 | Audit R2-BUG-08 |
| 21 | #982 | Subtract track header height from well-log zoom depth anchor | M2 | Audit R2-BUG-09 |
| 22 | #983 | Two-sided lighting on 3D fence curtains | M2 | Audit R2-BUG-10 |
| 23 | #984 | Dynamic volume downsampling based on GPU VRAM | M2 | Audit R2-BUG-11 |
| 24 | #985 | Filter horizon pick projections by distance tolerance to current slice | M2 | Audit R2-BUG-12 |
| 25 | #986 | Implement `safe_unlink` for read-only files on Windows NTFS | M3 | Audit R3-01 |
| 26 | #987 | Fix MinGW GCC vs MSVC compiler detection in `native_compile_flags.py` | M3 | Audit R3-03 |
| 27 | #988 | Add `os.add_dll_directory` for Python 3.8+ Windows companion DLLs | M3 | Audit R3-02 |
| 28 | #989 | Support 32-bit `long` buffer format (`format == "l"`) on Windows LLP64 in `numpy_bridge.cpp` | M3 | Audit R3-04 |
| 29 | #990 | `shutil.rmtree(..., onexc=handle_remove_readonly)` for directory cleanup | M3 | Audit R3-05 |
| 30 | #991 | Normalize case-insensitive paths on Windows (`os.path.normcase`) | M3 | Audit R3-06 |
| 31 | #992 | Enforce explicit `encoding="utf-8"` on all text/CSV exports | M3 | Audit R3-07 |
| 32 | #993 | Fix QGIS native bridge Windows build configuration & macro escaping | M3 | Audit R3-08 |
| 33 | #994 | Long path truncation protection with `\\?\` prefix | M3 | Audit R3-09 |
| 34 | #995 | Normalize POSIX `/` vs Windows `\` in native layer model | M3 | Audit R3-10 |
| 35 | #996 | `py::gil_scoped_acquire` in C++ progress callbacks | M3 | Audit R3-11 |
| 36 | #997 | Dynamic drive letter assignment for virtual subst drives | M3 | Audit R3-12 |
| 37 | #998 | CRLF vs LF normalization in stored project text hash calculation | M3 | Audit R3-13 |
| 38 | #999 | Zero-dimension validation guard in `SeismicVolumeSource` against C++ crash | M1 | Audit R4-05 |
| 39 | #1000 | Connect `geo-viz-engine` test paths in `pyproject.toml` | M1 | Audit R4-01 |
| 40 | #1001 | Guard native C++ test imports with `pytest.importorskip` | M1 | Audit R4-02 |
| 41 | #1002 | Cross-platform process termination in crash test helpers (`signal.SIGKILL` replacement) | M1 | Audit R4-09 |
| 42 | #1003 | Flatten `GeometryCollection` into constituent shapes in vector map renderer | M2 | Audit R4-06 |
| 43 | #1004 | Automatic character encoding detection with `gb18030` fallback for Chinese well logs/tables | M4 | Audit R4-07 |
| 44 | #1005 | Sanitize `NaN`/`Inf` in Factor LOO $R^2$ before JSON serialization | M4 | Audit R4-08/12 |
| 45 | #1006 | Add nugget regularization / fallback for singular matrices in Kriging | M4 | Audit R4-13 |
| 46 | #1007 | Configure Mesa software OpenGL in CI workflows | M4 | Audit R4-03 |
| 47 | #1008 | Replace process-global mutable CRS state with ContextVar/explicit passing | M4 | Audit R4-04 |
| 48 | #1009 | Thread-exit hooks to clean SQLite connections | M1 | Audit R4-10 |
| 49 | #1010 | Auto-normalize inverted/zero depth ranges in well-log curve track | M4 | Audit R4-08 |
| 50 | #1011 | Eliminate hardcoded `/tmp/` paths in tests using `tmp_path` fixture | M4 | Audit R4-11 |
| 51 | #1012 | Clip non-positive values before log10 in curve track renderer | M4 | Audit R4-14 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Requirement-driven test suite infra & test cases (Tiers 1-4) | None | IN_PROGRESS |
| M1 | Concurrency & Storage Safety | #962, #965, #966, #967, #970, #971, #972, #974, #999, #1000, #1001, #1002, #1009 | None | IN_PROGRESS |
| M2 | 2D/3D Viz & GIS Mapping | #975, #976, #977, #978, #979, #980, #981, #982, #983, #984, #985, #1003 | None | PLANNED |
| M3 | Windows Platform & Native Bridges | #986, #987, #988, #989, #990, #991, #992, #993, #994, #995, #996, #997, #998 | None | PLANNED |
| M4 | Architecture Decoupling & CI/Math | #963, #964, #968, #969, #973, #1004, #1005, #1006, #1007, #1008, #1010, #1011, #1012 | M1 | PLANNED |
| M5 | Full E2E Verification & Hardening | 100% test pass on Windows + Tier 5 adversarial testing | M1, M2, M3, M4, E2E | PLANNED |

## Interface Contracts
- **Thread Shutdown Contract**: All UI pages (`DataPage`, `StratigraphyCorrelationPage`, `MappingPage`) implement `shutdown_workers(wait_ms: int = 1500) -> bool` returning `True` only when all managed child jobs have terminated cleanly.
- **Worker Signal Contract**: `OwnedWorkerJob.shutdown()` disconnects all outbound Qt signal connections before blocking on `wait()`.
- **GL Cleanup Contract**: When `QOpenGLContext.currentContext()` is `None`, OpenGL texture deletions are queued in `queue_gl_texture_delete(tex_id)` rather than dropped.
- **File System Unlink Contract**: `safe_unlink(path: Path)` safely handles read-only files on Windows NTFS by clearing `stat.S_IWRITE` before unlinking.
- **Encoding Contract**: All text-based file operations explicitly declare `encoding="utf-8"`, while input parsers employ `gb18030` fallback for non-UTF-8 Chinese datasets.

## Code Layout
- `paleo_workbench/`: Main application code (UI, catalog, model, resources, mapping, viz).
- `geo-viz-engine/`: Visualization engine subsystem (`packages/geoviz_seismic`, `packages/geoviz_well_log`, `packages/geoviz_well_seismic_3d`, `packages/geoviz_plots`).
- `well-log-engine/`: Native well log processing engine (`src/`, `python/`).
- `native/`: Native C++ acceleration modules (`seismic_3d_core`, `layer_model_core`, `grid_render_core`, `qgis_render_bridge`).
- `tests/`: Monorepo test suites.
- `.agents/`: Agent metadata only.
