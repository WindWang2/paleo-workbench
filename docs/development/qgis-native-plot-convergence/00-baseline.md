# 00 — Baseline

> Prompt 6: QGIS Native Plot / Scientific 2D Visualization Framework Convergence
> Worktree: `/home/kevin/projects/paleo-qgis-plot` · Branch: `feat/qgis-native-plot-scientific-visualization`

## Baseline SHA

| Item | Value |
|------|-------|
| Baseline commit | `192422c60c4eb99ee78a6a410676293ca09053cc` (`origin/main` @ 2026-09-23, "Merge pull request #1480") |
| Worktree root | `/home/kevin/projects/paleo-qgis-plot` |
| Branch | `feat/qgis-native-plot-scientific-visualization` (tracks `origin/main`) |
| QGIS | vendored **4.2.0** source snapshot `third_party/qgis` (UPSTREAM.md: `final-4_2_0`, commit `ca5812c8`) |
| Qt | system Qt6 (`/usr`, Qt6_DIR=/usr/lib/cmake/Qt6), Widgets/Xml/Svg/PrintSupport |
| QGIS SDK | **prebuilt, read-only reuse**: `/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor/output` (`libqgis_{core,gui,analysis}.so.4.2.0`) |
| QGIS build dir (generated headers) | `/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor` |
| Deps prefix (qwt/geos/gdal headers) | `/home/kevin/projects/paleo_project/main/build/qgis-deps-prefix` |
| Build dir (this worktree) | `build/native-product`, Ninja, Release, `CMAKE_BUILD_PARALLEL_LEVEL=4` (hard cap ≤6) |

## Concurrent work ledger (startup audit)

| Stream | State @ baseline | Relevance |
|--------|------------------|-----------|
| PR #1483 `feat/qgis-native-layer-control` (Prompt 2) | OPEN, head `8dcf86408` | owns QgsMapCanvas/layer tree — we do NOT touch |
| PR #1482 `feat/qgis-native-data-management` (Prompt 3) | OPEN, head `555d6d4c6` | owns project/data providers — we consume only |
| `paleo-qgis-shell` (Prompt 1) | worktree exists, 0 commits | owns main_window/dock assembly — we provide plot panel entry points only |
| `paleo-qgis-processing` (Prompt 4) | worktree exists, 0 commits | owns QgsProcessing/QgsTaskManager — we consume via gatherer seam |
| `paleo-qgis-layout` (Prompt 5) | worktree exists, 0 commits | owns QgsLayout — we provide plot→layout bridge points only |
| main worktree dirty tree | ~94 modified/untracked files in-flight (uncommitted) | overlaps `libs/visualization/*canvas*`, `apps/*factor_stats_dock*`, `viz_c_time_map`, `main_window.*`, `ui_workstation` — **all excluded from this branch's diff; we branch from clean origin/main** |
| Open issues | #1472 (CI red legs), #1429 (Windows AV family) | pre-existing, unrelated |

## Submodules

`well-log-engine`, `geo-viz-engine`, `third_party/gdal`, `third_party/proj` are **not initialized in this worktree** — not needed: neither submodule is required by the default `pwb-platform` build (`PWB_SCIENCE_BUILD_VIEWER=OFF` default; geo-viz-engine is an oracle-fixture source only, never CMake-linked).

## Resource discipline

- All builds: `cmake --build ... -j4` (hard cap 6 per mandate; machine has 16 cores but sibling worktrees build concurrently).
- QGIS/vendor SDK: reused read-only; never rebuilt from this worktree.
