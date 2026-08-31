# 00 — Baseline (2026-08-31)

Base: `origin/main` @ `e1622496` (merge PR #1115). Worktree `/home/kevin/projects/paleo-p0-p1`,
branch `feat/p0-p1-workflow-convergence`.

## How this baseline was established

Read-only sweep of the current tree (code > tests > ADR > recent commits > docs), four parallel
deep-dive surveys (P0-A/B, P0-C/D, P1-A/B, P1-C/D), plus direct reading of the load-bearing
modules. Historical convergence PRs already merged into main: #1087–#1092 (P1 runtime/mapping/
catalog/multiview/e2e), #1098–#1106 (P0 catalog SQLite, cartography units, DPI contract),
#1108 (feat/core production-workflow-convergence), #1110–#1115 (CI/test hardening).
The only open PR is #1116 (P2 work, out of scope here).

## Verified state per goal

### P0-A Workspace/Survey Domain Core — ~85% DONE
Shipped as the WorkArea domain (ADR 0059): `paleo_workbench/project/domain.py`
(WorkArea/WellEntity/SeismicSurveyEntity/DomainEntity/EntityAssetLink + registries +
identity chain), `domain_migration.py` (deterministic idempotent v1→v2), `manager.py`
(atomic save, stale-write guard), `catalog/domain_binding.py`. Catalog remains sole
lifecycle authority; entities reference asset ids only.
**Gaps**: faults not auto-bound as DomainEntities; typed-id value classes absent
(string-prefixed ids are the established contract — deliberately not "fixed": fewer new
abstractions).

### P0-B Unified Data Explorer — ~85% DONE
DataPage (IA 3.0): NavigationTree with paged population (500/page), QAbstractTableModel
with incremental view recycling, debounced search (180ms), tag filters AND/OR, versions +
lineage panels, background preview with generation-based cancellation, 100k benchmarks
(`benchmarks/catalog_scale_benchmark.py`, `docs/development/production-convergence/04-benchmarks.md`).
**Gaps**: table model materializes every row (no canFetchMore/fetchMore); SQLite
`search_assets` not wired as the table's data source; `filter_by_type` @100k = 1.45s
materializing rows.

### P0-C Unified Geological Context — ~50% DONE
`viz/selection_context.py` (thread-safe, partial update, echo-guarded) +
`ui/view_coordination.py` (#1029, 4-layer echo prevention, differential routing) +
`viz/coordinate_hub.py` (map↔well↔seismic).
**Gaps**: scenario A seismic sink missing; scenario B map/3D cursor sinks missing;
scenario C depth→time missing entirely AND hub uses constant 2000 m/s for
seismic_to_well (violates no-calibration-no-assumption rule); scenario D
ActiveHorizon/Fault/Interpretation/layer/extent slots absent.

### P0-D Composition System — ~30% DONE
`mapping/composer/models.py` (8 element types, to_dict only) + `renderer.py`
(MAIN_MAP/TITLE/NORTH_ARROW/SCALE_BAR/LEGEND in SVG; GRID/ANNOTATION/TIMESCALE are
placeholder rects). QGIS bridge (`map_render_backend.py`, ADR 0057/0059) handles canvas
rendering + vector export; RenderContext DPI contract landed (#1103/#1106).
**Gaps**: no loader, no undo/redo, no template model, no component CRUD/move/scale
contract, no composition UI, no ColorBar/InsetMap/StatChart/Image/MetadataBlock/Text,
exports are view-exports not composition pages.

### P1-A Well Interpretation — ~70% DONE
Correlation tops workflow complete (pick/DTW/undo/redo → save_interpretation_version →
DERIVED + DataRun). Engine side (well-log-engine submodule @fd3bc5a8): curve_edit,
display_set, nav_tree, templates, true TimeDepthRelationship — Epics A–D closed.
**Gaps**: no workbench-side curve interpretation op → derived curve version loop
(editing half); annotations minor.

### P1-B Seismic Interpretation — infra ~90%, interpretation UI 0%
Out-of-core stack complete (transcode → Zarr v3, lifecycle w/ cancel/resume, TaskScheduler,
VRAM cache L2, LOD). Interpretation lifecycle complete and tested
(draft/artifact/lifecycle/fault_lifecycle) — **zero UI callers**. Engine SeismicView has
horizon picking (`horizon_picked` (il,xl,t)). Host wires only c3 coherence; engine has
envelope/phase/frequency/rms/sweetness/rel-impedance/dip/azimuth/curvature/rgb-fuse.
**Gaps**: picking → draft → version → reload → overlay loop; fault UI; attribute kernels
wiring + panel honesty; attribute consumers.

### P1-C Unified Geological Scene — ~60% DONE
Joint 3D scene with rigorous well identity (joint_well_identity), visibility persistence,
LOD ladder, fail-closed vertical domain. VRAM budget model exists
(`runtime/resource_budget.py`) — `apply_vram_budget` never called in production.
**Gaps**: non-well scene objects lack stable identity; horizons enter via .dat files not
versioned artifacts; highlight_well no geometry highlight; no budget wiring.

### P1-D Factor Map → Paleogeographic Product — ~80% DONE
Real Kriging (engine + genuine numpy fallback), FactorGridResult with full provenance
contract, catalog lineage registration, compile_map_production (fail-closed, anti-laundering),
review/export/finalize chain, ContourDraft lifecycle.
**Gaps**: no MapProduct concept (multi-factor + interpretation + adjustments + layout →
OUTPUT); GeologicalMappingService path drops source_refs/run_ref AND stamps
source_kind="real" on synthesized sample points (honesty bug); composition template
binding absent (depends on P0-D).

## Environment

- Python: `/opt/miniconda3/bin/python3.13` (PySide6, numpy 2.4.6, pydantic 2.13.4)
- Test wrapper: `run_env.sh` (offscreen Qt, software GL, libxmlshim preload, engine
  submodules on PYTHONPATH; mirrors the established sibling-worktree contract)
- Submodules checked out at main pins: geo-viz-engine 26777722, well-log-engine fd3bc5a8
- Baseline smoke: tests/test_workarea_domain.py 53/53 green
