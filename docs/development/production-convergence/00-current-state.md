# 00 — Current State (baseline audit, 2026-08-29)

Baseline: `origin/main` = `af92f59e` (Merge PR #1104, VramTextureCache L2).
Worktree: `../paleo-production-convergence`, branch `feat/production-workflow-convergence`.
Submodules initialized at pinned commits (`geo-viz-engine` f6fbd3c4, `well-log-engine` fd3bc5a).

## 1. "Merged but not in main" audit (PR truth verification)

| PR | Claim | Reality on main | Evidence |
|---|---|---|---|
| #1098 SQLite thread ownership | MERGED | **IN main** (`c0a1dc31`) | `git merge-base --is-ancestor` ✓ |
| #1099 SQLite **canonical** store (#1027) | MERGED 21:26:28+08 | **NOT in main** — merge commit `420bb6e7` exists only on `origin/fix/p0-sqlite-thread-ownership` & head branch `fix/p0-catalog-sqlite-canonical` | `git branch -a --contains 420bb6e7` lacks main; `catalog/db.py` docstring still says "rebuildable index, catalog.json is canonical" |
| #1100 render units (#1025) | MERGED | IN main (`8901a128`) ✓ | |
| #1104 VramTextureCache (#1078) | MERGED | IN main (`af92f59e`) ✓ | |
| #1105 RenderContext DPI (#1103) | MERGED 00:23:17+08 | **NOT in main** — content lives on open PR **#1106** (`fix/p0-cartography-units`, commits 1402cc06 f1633330 7a669f92 2f8cd403) | `renderers.py:81` dpi field has zero readers on main |
| #1087–#1092 (P1 batch) | MERGED | IN main ✓ | log shows all merge commits |

Root cause pattern (also documented by audit): 3 merges raced within 44 s on 2026-08-28 21:25–21:26 (#1098/#1099/#1100); main was subsequently rebuilt **without** #1099. #1105 merged 18 s after #1104 but onto a stale base and was dropped; work continued as open PR #1106.

Historical regression source: commit `a4953678` ("resolve all 35 issues") fixed many audit issues, then PR #1089's file rewrites (based on an older baseline) clobbered: IDW tiling, CRS lookup, QGIS dataDefinedProperties rotation, well_log_host engine branch, DTW min-max downsample, lineage deque. Those fixes are recoverable via `git show a4953678:<path>` but must be re-integrated against current main.

## 2. Catalog (P0)

- `catalog/db.py` = **rebuildable SQLite query index** (ADR 0056): `catalog.json` canonical, full delete-and-rewrite rebuild, INDEX_SCHEMA_VERSION 5.
- Every mutation deep-copies `CatalogDocument` and re-serializes whole JSON (O(N), the #1027/#1099 problem).
- `#1099` content (3 commits `9466ecc6` `1cdd767f` `3be90314`) = SQLite promoted to transactional canonical store (WAL, row-level txns, DirtySet, apply_changes, load_document, write_all, reconcile, schema migration; catalog.json kept as checkpoint/export). Needs **re-land on top of latest main** (main's service.py gained legacy_projection + perf changes from #1088 since the branch base `4f3a47a7`).
- #1059 still present: `catalog/lineage_graph.py:139-141` `queue.pop(0)` (list), `:67-78` rebuilds tag dict per node.

## 3. Seismic (baseline vs 100G goal)

From `docs/specs/100g-seismic-volume-architecture.md` and code audit:

- **Transcoder done but orphaned**: `paleo_workbench/seismic_transcode.py` (parallel workers, shard-aligned writes, resume-by-shard-probe, cancel, `_validate_existing`). Only caller = its test. Not wired into import; no DataRun/DERIVED registration.
- **ChunkedVolumeReader only a prototype**: `prototypes/chunked_access/reader.py` (zarr v3, lazy cascade LOD `_l{n}` arrays, DirectionalPrefetcher, cache-key compatible with production `SliceCacheKey`). No production `geoviz_seismic/chunked.py`, no `open_volume()`.
- **Production reads are segyio-direct**: `viz/seismic_volume_source.py` (LOD = post-read 2D decimation / strided re-read ladder), `viz/source_backed_volume_access.py` (3D adapter). `read_voxel_window`/`read_arbitrary_line` do not exist in production.
- **No global scheduler**: zero QThreadPool; each module spawns its own QThread (workers.py, inference_worker, joint_host workers, geological_modeling_workers, scanner ThreadPoolExecutor, transcoder ThreadPoolExecutor). Shared infra is only liveness helpers (`OwnedWorkerJob`, `thread_keeper`).
- **Rendering**: 2D profile = QImage indexed8 software path; 3D = pyqtgraph.opengl. L1 RAM slice cache (global 1 GiB) + L2 VramTextureCache (1 GiB budget, all-type ledger) merged (#1078). Prefetch fixed ±1/±2 offsets, not direction-aware. No frame budget, no viewport-driven LOD selection.
- **Attributes**: 16 attrs incl. C3 coherence (CuPy optional) in `geoviz_seismic/attributes.py` + C++ 3D coherence via native dispatch. All whole-slice/whole-volume; **no ROI, no out-of-core banding**.
- **AI inference**: framework (DataRun lifecycle, providers) exists; providers = demo/heuristic/online. **No ONNX runtime, no tiled inference.**
- **Synthetic data + benchmarks**: `benchmarks/generate_synthetic_segy.py` (tiny/quick2g/full100g presets, deterministic per-inline seeds), format benchmark, VRAM L2 benchmark. Ready to reuse for acceptance.

## 4. Mapping

- #1049 kriging: **already fixed** (variogram OK via `geoviz.factor.kriging`); stale comment + unreachable legacy alias `"克里金(MVP·线性)"→linear` remain in engine `factor/interpolation.py:32-39`.
- #1050 CRS: still 1 wrong read — `services/geological_mapping_service.py:148` `project.crs...` (hasattr always False → hardcoded EPSG:4326). Real schema: `project.coordinate.project_crs` (`project/models.py:35-39,487`).
- #1048 IDW: `mapping/geological_pipeline/interpolator.py:130-163` still builds full (M,N) dist/valid/weights matrices. (Engine-side `geoviz_plots` IDW is chunked.)
- #1051 fallback CRS: `FallbackMapRenderBackend._paint_composition` maps all layers through one world extent; `layer.crs` never used for reprojection.
- #1052: QGIS bridge wire protocol has layer-level label fields only; no rotation / per-feature size/color / dataDefinedProperties (C++ `qgis_render_bridge.cpp:185-203`, `bindings.cpp:108-122`).
- #1102: `qgis_render_bridge.cpp:198` hardcodes buffer color white; Python already sends `buffer_color` (forward-compat).
- #1103: RenderContext.dpi dead in SVG path; fix exists in PR #1106 branch (needs re-land).

## 5. Well Log

- #1053: `viz/hosts/well_log_host.py:363-371` unconditionally releases engine doc and renders Legacy QPainter; `_show_engine` is dead code in this host. Native binding module = `welllog` (`WellLogView`) probed via `try_import_welllog()`. Engine path only used by `well_log_canvas_panel.py` (prediction page) behind `PALEO_USE_WELLLOG_ENGINE` (default True).
- #1054: `viz/dtw_log_matcher.py:56-64` uniform `[::stride]` decimation when n_ref×n_target > 1e6 cost cells. C++ well_log_core has no DTW (mapping is dead → always Python impl).

## 6. Multi-view coordination

- SelectionContext / CoordinateTransformHub / ViewCoordinationController wired for Map/3D/WellLog-prediction (source-tagged, diff-routed, echo-guarded).
- **Seismic cursor producer missing**: `publish_seismic_cursor()` has zero callers; `_route_seismic_cursor` ready.
- **Well registry never populated in production**: `register_well`/`set_seismic_geometry` only called by tests; no project open/close hooks → `seismic_to_well` would KeyError (swallowed at `view_coordination.py:210-211`).

## 7. Test infrastructure

- `run_env.sh <worktree> [pytest args]`: miniconda py3.13, offscreen Qt, LIBGL software, PYTHONPATH shared from main worktree's submodule packages.
- Optional C++ extensions (layer_model_core / grid_render_core / qgis_render_bridge / well_log_core) NOT built locally — related tests fail on clean main equally (environment limitation, not regression).
- #1101: `test_nested_and_multithreaded_disabled_acceleration` fails on clean main (pre-existing). #1107: razor-thin timing budgets (FilterIndex 1.0s, catalog_scale linearity) flaky.

## 8. Resources

- 62 GB RAM (52 free), 270 GB disk free. Builds must use `-j2`/`-j4`; benchmark datasets capped (quick2g ≈ 2.4 GB; full100g = extrapolated, not materialized).
