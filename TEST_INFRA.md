# E2E Test Infrastructure Specification: Paleogeography Workbench
**Remediation Audit Test Architecture (#962–#1012)**
**Document Version:** 1.0.0  
**Status:** ACTIVE / BASELINE  
**Workspace Root:** `C:\Users\wangj.KEVIN\projects\paleo-workbench`

---

## 1. Test Philosophy & Architectural Principles

The Paleogeography Workbench test architecture is engineered to provide rigorous, opaque-box end-to-end verification across the desktop application, visualization subsystems (`geo-viz-engine`), native acceleration layers (`native/`), and Windows platform integration.

### Core Testing Pillars
1. **Opaque-Box Verification (Contract-Driven)**: Tests evaluate observable behaviors, data contracts, and public APIs rather than internal implementation state.
2. **Progressive Testability & Headless Execution**: All test cases are fully executable in headless CI environments (e.g. `QT_QPA_PLATFORM=offscreen`, Mesa software OpenGL) and handle optional native C++ compilation gracefully with fail-closed or skipped contracts (`pytest.importorskip`).
3. **Cross-Platform & Windows Resilience**: Explicit verification of Windows filesystem semantics (NTFS read-only ACLs, extended-length `\\?\` paths, case-insensitivity, CRLF line endings, DLL search paths) alongside POSIX compatibility.
4. **Adversarial & Boundary Robustness**: Systematic stress testing of numerical edge conditions (singular matrices, division by zero, non-positive logarithms, non-finite float serialization), corrupted/GB18030 encoded files, and concurrent thread teardown.
5. **Deterministic Isolation**: Every test is self-contained, sets up dedicated temporary resources (`tmp_path`), executes without reliance on prior state, and cleans up background threads and QObjects safely.

---

## 2. 4-Tier Test Methodology & Coverage Taxonomy

The test suite is structured into four distinct hierarchical tiers:

```
                  ┌──────────────────────────────────────────────────┐
                  │    Tier 4: Real-World Application Scenarios       │
                  │    - 5 Complex Multi-Subsystem Workflows         │
                  └─────────────────────────┬────────────────────────┘
                                            │
                  ┌─────────────────────────┴────────────────────────┐
                  │    Tier 3: Cross-Feature Interactions (Pairwise)  │
                  │    - Multi-Module Integration & Concurrency      │
                  └─────────────────────────┬────────────────────────┘
                                            │
                  ┌─────────────────────────┴────────────────────────┐
                  │    Tier 2: Boundary & Corner Cases (>=5 / feat)  │
                  │    - Extreme inputs, zero dims, NaN, encodings   │
                  └─────────────────────────┬────────────────────────┘
                                            │
                  ┌─────────────────────────┴────────────────────────┐
                  │    Tier 1: Core Feature Coverage (>=5 / feat)    │
                  │    - 51 Audit Features (#962 to #1012)           │
                  └──────────────────────────────────────────────────┘
```

- **Tier 1: Feature Coverage (`tests/e2e/test_tier1_features.py`)**:
  - Direct behavioral verification of each individual audit item (#962 to #1012).
  - Target: $\ge 5$ concrete assertions / test cases per feature ($51 \times 5 = \ge 255$ verification points).
- **Tier 2: Boundary & Corner Cases (`tests/e2e/test_tier2_boundaries.py`)**:
  - Edge conditions: zero dimensions, null/empty collections, extreme numerical ranges, invalid encodings, NTFS read-only locks, long paths, concurrent teardown race conditions.
  - Target: $\ge 5$ boundary assertions / test cases per feature ($51 \times 5 = \ge 255$ verification points).
- **Tier 3: Cross-Feature Interactions (`tests/e2e/test_tier3_interactions.py`)**:
  - Pairwise and multi-feature combinations validating module interplay (e.g. worker shutdown + atomic save + NTFS unlink; GB18030 decoding + depth normalization + log10 clipping; Kriging fallback + NaN sanitization + ContextVar CRS).
- **Tier 4: Real-World Application Scenarios (`tests/e2e/test_tier4_scenarios.py`)**:
  - 5 comprehensive, multi-step real-world workflows:
    1. Seismic Exploration & 3D Interpretation Pipeline
    2. Multi-Well Chinese Stratigraphy & Well-Log QC Workflow
    3. Quantitative Paleogeographic Facies Mapping & SVG Map Publishing
    4. Windows Enterprise Storage Lifecycle & Disaster Recovery
    5. Multi-Factor Environmental Prediction & Provenance Export

---

## 3. Feature Inventory Matrix (#962–#1012)

| # | Issue | Feature / Defect Description | Subsystem / Area | Milestone | Primary Interface / Contract |
|---|---|---|---|---|---|
| 1 | #962 | `DataPage._shutdown_workers()` complete worker list | UI / Workers | M1 | `DataPage.shutdown_workers(wait_ms) -> bool` |
| 2 | #963 | Move `PreviewSettings` to domain layer to eliminate inverted imports | Domain Model | M4 | `paleo_workbench.model.preview_settings.PreviewSettings` |
| 3 | #964 | Enforce native acceleration checks through `NativeBackendService` | Domain / Native | M4 | `NativeBackendService.is_acceleration_available() -> bool` |
| 4 | #965 | Disconnect signals in `OwnedWorkerJob.shutdown()` before join | UI / Workers | M1 | `OwnedWorkerJob.shutdown(wait_ms)` disconnects result signals |
| 5 | #966 | `StratigraphyCorrelationPage` & `MappingPage` aggregated worker shutdown | UI / Workers | M1 | `shutdown_workers(wait_ms) -> bool` on all page controllers |
| 6 | #967 | Remove blocking thread joins from `__del__` finalizers | Concurrency | M1 | Destructors avoid blocking `thread.join()` or `wait()` |
| 7 | #968 | Bounded LRU cache for seismic slice loader | Seismic Viz | M4 | `SeismicSliceLRUCache(max_size=N)` evicts oldest entries |
| 8 | #969 | Dynamic memory management for preview rendering | Viz / Graphics | M4 | `PreviewMemoryBudgetManager.allocate(bytes) -> bool` |
| 9 | #970 | Cancellation event in `ProjectController` catalog maintenance thread | Catalog / UI | M1 | `threading.Event` checked during database maintenance |
| 10 | #971 | Catch `sqlite3.Error` during cross-thread session teardown in `CatalogIndex.close()` | Storage / DB | M1 | `CatalogIndex.close()` handles concurrent SQLite errors |
| 11 | #972 | Atomic file swap replacement for project saves | Storage / IO | M1 | Temp file write + `os.replace` atomic commit |
| 12 | #973 | Replace silent exception passes with structured logging | Infrastructure | M4 | Structured `logging.getLogger()` calls on caught exceptions |
| 13 | #974 | OpenGL texture delete queueing when context is inactive in `DualGLVolumeItem.clean()` | 3D Graphics | M1 | `queue_gl_texture_delete(tex_id)` on inactive context |
| 14 | #975 | 3D normal map gradient axis mapping `[-d_inline, -d_crossline, -d_time]` | 3D Graphics | M2 | Normal gradient formula & axis orientation |
| 15 | #976 | Polyline click coordinate transformation with zoom/pan matrix in `ProfileVD` | Seismic Viz | M2 | Viewport transform matrix applied to mouse click events |
| 16 | #977 | Marching Squares isolines and shapely facies polygons | Mapping / GIS | M2 | Isoline extraction & polygonization via Shapely |
| 17 | #978 | Dynamic SVG layer rendering and legend generation in Map Composer | Mapping / GIS | M2 | `MapComposerSvgExporter.export_svg()` dynamic tags & legend |
| 18 | #979 | Connect GPU instanced `WiggleTraceRenderer` in `ProfileWidget` | Seismic Viz | M2 | GPU instanced wiggle trace vertex buffer rendering |
| 19 | #980 | Descending inline binary search direction handling | Seismic Viz | M2 | Monotonically decreasing coordinate binary search |
| 20 | #981 | Reset active texture to `GL_TEXTURE0` in `GLImageLutItem.paint()` | 3D Graphics | M2 | `glActiveTexture(GL_TEXTURE0)` restored after custom LUT |
| 21 | #982 | Subtract track header height from well-log zoom depth anchor | Well-Log Viz | M2 | Depth anchor calculation: `(y - header_height) / scale` |
| 22 | #983 | Two-sided lighting on 3D fence curtains | 3D Graphics | M2 | Two-sided lighting calculation in fence curtain shaders |
| 23 | #984 | Dynamic volume downsampling based on GPU VRAM | 3D Graphics | M2 | Downsampling step calculation from available VRAM budget |
| 24 | #985 | Filter horizon pick projections by distance tolerance to current slice | Seismic Viz | M2 | Filter picks where `abs(pick_coord - slice_coord) <= tol` |
| 25 | #986 | Implement `safe_unlink` for read-only files on Windows NTFS | Windows Platform| M3 | Clear `stat.S_IWRITE` before `os.unlink` |
| 26 | #987 | Fix MinGW GCC vs MSVC compiler detection in `native_compile_flags.py` | Native Build | M3 | Compiler detection `/O2` vs `-O3` |
| 27 | #988 | Add `os.add_dll_directory` for Python 3.8+ Windows companion DLLs | Windows Platform| M3 | Register companion DLL directory on Python 3.8+ Windows |
| 28 | #989 | Support 32-bit `long` buffer format (`format == "l"`) on Windows LLP64 | Native Bridge | M3 | Buffer protocol parsing for `'l'` (32-bit int on LLP64) |
| 29 | #990 | `shutil.rmtree(..., onexc=handle_remove_readonly)` for directory cleanup | Windows Platform| M3 | Recursive removal clearing read-only attributes on error |
| 30 | #991 | Normalize case-insensitive paths on Windows (`os.path.normcase`) | Windows Platform| M3 | Path comparisons use `os.path.normcase` on Windows |
| 31 | #992 | Enforce explicit `encoding="utf-8"` on all text/CSV exports | Storage / IO | M3 | Text file exports explicitly specify `encoding="utf-8"` |
| 32 | #993 | Fix QGIS native bridge Windows build configuration & macro escaping | Native Build | M3 | CMake / compiler macro escaping on Windows |
| 33 | #994 | Long path truncation protection with `\\?\` prefix | Windows Platform| M3 | Prefix extended paths (>260 chars) with `\\?\` |
| 34 | #995 | Normalize POSIX `/` vs Windows `\` in native layer model | Native Bridge | M3 | Path normalization in native layer model serialization |
| 35 | #996 | `py::gil_scoped_acquire` in C++ progress callbacks | Native Bridge | M3 | Native threads acquire GIL before invoking Python callbacks |
| 36 | #997 | Dynamic drive letter assignment for virtual subst drives | Windows Platform| M3 | Dynamic free drive letter detection for subst drives |
| 37 | #998 | CRLF vs LF normalization in stored project text hash calculation | Storage / Integrity| M3 | Line-ending normalization (`\r\n` -> `\n`) before hashing |
| 38 | #999 | Zero-dimension validation guard in `SeismicVolumeSource` against C++ crash | Seismic Viz | M1 | Validate `inline > 0, crossline > 0, samples > 0` |
| 39 | #1000 | Connect `geo-viz-engine` test paths in `pyproject.toml` | CI / Build | M1 | `pythonpath` and testpaths include `geo-viz-engine` |
| 40 | #1001 | Guard native C++ test imports with `pytest.importorskip` | CI / Testing | M1 | Tests requiring C++ modules skip gracefully when unbuilt |
| 41 | #1002 | Cross-platform process termination in crash test helpers | Concurrency | M1 | Cross-platform process termination (`process.kill()`) |
| 42 | #1003 | Flatten `GeometryCollection` into constituent shapes in vector map renderer | Mapping / GIS | M2 | Flatten GeometryCollection into Points, Lines, Polygons |
| 43 | #1004 | Automatic character encoding detection with `gb18030` fallback for Chinese | Storage / IO | M4 | Fallback from UTF-8 to GB18030 on UnicodeDecodeError |
| 44 | #1005 | Sanitize `NaN`/`Inf` in Factor LOO $R^2$ before JSON serialization | Domain / Math | M4 | Replace non-finite floats with `None` or `0.0` for JSON |
| 45 | #1006 | Add nugget regularization / fallback for singular matrices in Kriging | Domain / Math | M4 | Nugget jitter diagonal regularization or IDW fallback |
| 46 | #1007 | Configure Mesa software OpenGL in CI workflows | CI / Graphics | M4 | Mesa llvmpipe / software rasterization configuration |
| 47 | #1008 | Replace process-global mutable CRS state with ContextVar/explicit passing | Mapping / GIS | M4 | `ContextVar` or explicit argument passing for CRS |
| 48 | #1009 | Thread-exit hooks to clean SQLite connections | Storage / DB | M1 | Thread-local SQLite connection automatic cleanup |
| 49 | #1010 | Auto-normalize inverted/zero depth ranges in well-log curve track | Well-Log Viz | M4 | Normalize depth intervals when `top >= bottom` |
| 50 | #1011 | Eliminate hardcoded `/tmp/` paths in tests using `tmp_path` fixture | CI / Testing | M4 | Cross-platform `tmp_path` fixture usage in all tests |
| 51 | #1012 | Clip non-positive values before log10 in curve track renderer | Well-Log Viz | M4 | Clip $x \le 0$ to positive $\epsilon$ or mask before log10 |

---

## 4. Test Suite Architecture & Directory Layout

```
tests/
├── e2e/
│   ├── __init__.py
│   ├── conftest.py                   # Reusable mock fixtures, synthetic data generators, headless Qt setup
│   ├── test_tier1_features.py        # Tier 1: 51 Feature unit-contract test suites (>=5 assertions/feat)
│   ├── test_tier2_boundaries.py      # Tier 2: 51 Feature boundary & corner cases (>=5 assertions/feat)
│   ├── test_tier3_interactions.py    # Tier 3: Cross-feature pairwise & multi-module integration suites
│   └── test_tier4_scenarios.py       # Tier 4: Real-world complex end-to-end application workflows
├── conftest.py                       # Root Qt session policy & deferred deletion cleanup
└── ... (existing unit and integration suites)
```

---

## 5. Execution Commands & Coverage Thresholds

### Running the E2E Test Suite
To execute the complete E2E test suite across all 4 tiers:
```bash
pytest tests/e2e -v
```

To execute individual tiers:
```bash
# Tier 1: Feature Coverage
pytest tests/e2e/test_tier1_features.py -v

# Tier 2: Boundary & Corner Cases
pytest tests/e2e/test_tier2_boundaries.py -v

# Tier 3: Cross-Feature Interactions
pytest tests/e2e/test_tier3_interactions.py -v

# Tier 4: Real-World Application Scenarios
pytest tests/e2e/test_tier4_scenarios.py -v
```

### Coverage & Quality Thresholds
- **Feature Coverage**: 100% of all 51 features (#962–#1012) must have explicit Tier 1 and Tier 2 test coverage.
- **Pass Rate**: 100% pass rate (0 failures, 0 errors, 0 unhandled warnings/crashes) in standard CI headless environment.
- **Independence**: 0 test ordering dependencies; all tests execute in arbitrary order.
- **Resource Hygiene**: 0 leaked threads, 0 unhandled SQLite locks, 0 dangling file handles on Windows NTFS.
