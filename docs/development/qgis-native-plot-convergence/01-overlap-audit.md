# 01 — Overlap / Lease Ledger

Which files/responsibilities this stream owns vs. the five parallel worktrees.
Baseline: `192422c60`. Updated as conflicts surface.

## Ownership claims (this stream)

| Path / responsibility | Action | Boundary note |
|----------------------|--------|---------------|
| `libs/qgis_plot/**` (new) | create | this stream's infra lib — `Pwb::QgisPlot` |
| `libs/viz_charts/qt/**` | **done**: `plot_widget.{hpp,cpp}` (960 LOC), `cross_plot_widget.{hpp,cpp}` (481), `qt/series.hpp` (91) deleted — zero production consumers left; `colorbar`/`surface` kept (domain renderers) | Qt-free kernels (`series`, `axes`, `colormaps`, `convex_hull`, `marching_squares`, `fence`, `well_qc`) **stay** — domain math |
| `libs/ui_pages_preview/src/qt/well_log_preview_presenter.*` | migrate paint → `PwbPlotCanvas` | same public contract (`set_data`/`summary_line`) |
| `libs/ui_pages_preview/src/qt/time_depth_preview_presenter.*` | migrate paint → `PwbPlotCanvas` | same public contract (+`set_probe`) |
| `apps/.../viz_e_hosts.{hpp,cpp}` | `XyScatterHost` internals → `PwbPlotPanel`+`PwbPlotCanvas` | header API kept (`show_well_head`/`show_unavailable`/`export_*_to`/`export_requested`); `plot()` accessor → `canvas()` |
| `apps/.../comparison_view.*` | `CompareCanvas` paint → `PwbPlotCanvas` band items | Wave A stretch; QC/diagnostic representative |
| `apps/.../viz_e_install.cpp` | consumer wiring updates only | minimal touch |
| `apps/.../well_presenter_install.cpp` | consumer wiring updates only | minimal touch |
| `tests/cpp/viz_e/*`, `tests/cpp/well_crosswell/*`, `libs/viz_charts/viz_charts_tests/*`, `libs/ui_pages_preview/*_tests/*` | update to new canvas API | tests move with the code |
| `docs/development/qgis-native-plot-convergence/**` | create | this stream's ledger |
| root `CMakeLists.txt` | add `add_subdirectory(libs/qgis_plot)` in `PWB_BUILD_PLATFORM` | adjacent lines only; flagged seam |

## Explicitly NOT touched (other streams' leases)

| Path | Owner stream |
|------|--------------|
| `main_window.*`, `app_shell.*`, dock/ribbon assembly | Prompt 1 (shell) — no commits yet @baseline |
| `libs/ui_canvas`, `libs/ui_map`, `libs/ui_widgets/src/qgis/*`, `libs/qgis/src/map_session*`, layer tree | Prompt 2 (layers) — PR #1483 open |
| `libs/project`, `libs/data_suite`, `libs/providers`, `libs/application` data mgmt | Prompt 3 (data) — PR #1482 open |
| `libs/job_runtime`, processing/task infra | Prompt 4 (processing) — no commits yet |
| `libs/layout_export`, `libs/qgis/src/layout_service*`, `composition_*` | Prompt 5 (layout) — no commits yet |
| `libs/visualization/src/cross_well/*`, `well_tie/*` | **contended**: dirty in main worktree (in-flight uncommitted work) AND domain-heavy → deferred to Wave C regardless |
| `libs/seismic_viewer/*`, `viz_c_time_map.cpp` | domain raster viewers — Phase 9 boundary: keep specialized (documented) |
| `well-log-engine`, `geo-viz-engine` submodules | not initialized here; WLE = specialized engine (see 09) |

## Conflict matrix vs. dirty main worktree (uncommitted in-flight work)

| Dirty file | This stream touches? | Risk |
|-----------|----------------------|------|
| `libs/visualization/src/cross_well/qt/section_canvas.cpp`, `tie_canvas.cpp`, `formation_tops_preview.cpp` | NO (deferred Wave C) | none now; merge-time revisit |
| `apps/.../factor_stats_dock.cpp`, `viz_c_time_map.cpp`, `workflow_install.cpp`, `main_window.*`, `app_shell.*`, `bootstrap.cpp`, `self_check.cpp` | NO | none |
| `libs/ui_workstation/*`, `libs/ui_widgets/src/qgis/mirror_snapshot.cpp`, `libs/application/src/project_session.cpp`, `libs/qgis/src/map_session.*`, `libs/ui/*edit_tool*` | NO | none |
| `libs/ui_wellseis/src/qt/well_log_prediction_page.cpp` | NO | none |

**Zero overlapping files** between this branch's planned diff and the dirty main tree. ✓

## Seam register (cross-boundary touch points)

| Seam | Where | Contract |
|------|-------|----------|
| plot→map selection | `PwbPlotCanvas` signals (`pointClicked`/`lassoFinished` carry `series_id`+`point index`+domain ids) → consumer pages forward to map selection | one-directional signals only; plot never owns map truth |
| plot→processing | `QgsVectorLayerXyPlotDataGatherer` (QgsTask) usable for layer-derived series | consume `QgsApplication::taskManager()`, no new task framework |
| plot→layout | `QgsLayoutItemChart` accepts any `Qgs2DPlot` (upstream) | Paleo plot configs serialize via `writeXml` — layout stream can embed |
| shell integration | `PwbPlotPanel` is a plain `QWidget` — dock/page assembly stays with shell stream | no `main_window` edits |
