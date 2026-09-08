# V8 Scientific Workflow — Phase 0 Overlap Audit (2026-09-09)

Baseline: `origin/main @ d5181cb3` (local worktree `feat/scientific-workflow-v8`).
Open PRs at audit time: **0**. Open issues: **#1224** (fake cancellation in
WellLogLoadWorker/MapExportWorker), **#1230** (CI gate coverage; out of scope —
this goal verifies locally, no CI dependency).

## A. Delivered baseline — DO NOT REBUILD

| Merged PR / commit | Delivered capability | V8 stance |
|---|---|---|
| #1232 (ea56f9a3 + 79e89ec0 + 2c2719f6) | lazy catalog, transaction CAS, payload leases + GC coordination, working-copy lifecycle/recovery, session guards, 100k–500k metadata baselines; `sha256_file(cancel=)`; **MapExportWorker real cancel checkpoints**; QUEUED-task supersede | extend only |
| #1234 (db21f6cf) | typed depth/unit contracts, well identity hardening, SEG-Y scalar semantics, **constraint capability matrix + honest unsupported/partial routing**, Kriging V2 (variogram controls, anisotropy, LOWO CV), constrained IDW, evaluation workbench, factor map contract, fusion/QC, variance propagation kriging→fusion | extend only |
| #1198 | Workflow DAG, Recipe, ActionSpec V2, six-state ActionResult, verifier hooks, provider contract V2, checkpoint/resume/rerun/cache, 56 actions / 11 domains | extend only |
| #1231 | staged mapping workspace, grouped layer tree, constraints geometry sync-back + content fingerprint (`mapping_workspace/constraints_sync.py`) | build upon |
| #1237 (ff721e03) | QGIS geolayer/cartography platform V7 | Direction B — untouched |
| #1235/#1236 + follow-ups (10647f09, c5a1d322, 7fcf0bb1) | workstation UX V7, authoring kernel V7, tool_surface/toolbar/inspector fixes | Direction A/B — untouched |
| d5181cb3 | MultiPolygon polygonization area fix, seismic grid reconfig reset | Direction B — untouched |

Parallel V8 directions (both worktrees at `d5181cb3`, no commits yet):
`feat/qgis-context-control-plane-v8` and `feat/qgis-spatial-authoring-v8`
(QGIS/rendering/UI side). Conflict surface with this direction: **low** — we own
`workflow/**`, `harness/**`, targeted `catalog/**` follow-ups, factor/fusion/QA
domain code. We only touch `ui/**` in the two workers named by #1224
(`ui/pages/well_log_load_worker.py`, already partially fixed for export worker)
and add no workstation UI.

## B. Verified current state (audit 2026-09-09, evidence-based)

Scientific chain (files: `workflow/factor_interpolation.py`,
`interpolation_evaluation.py`, `constraint_capabilities.py`,
`constrained_idw_adapter.py`, `factor_fusion.py`, `map_product.py`,
`map_qa_rules.py`, `qc.py`, `freshness.py`):

| Suspected gap | Verdict |
|---|---|
| kriging barriers unsupported | honest-unsupported already; **no fake penalty** (keep; document as known limitation) |
| plain IDW duplicate double-vote | **STILL EXISTS** (engine keeps identical-XY; no dedup policy) |
| numpy fallback kriging fitter ≠ engine WLS | **STILL EXISTS** (`mapping/geological_pipeline/interpolator.py:410-456` unweighted OLS vs engine scipy WLS) |
| mixed m/ft multi-well section | **STILL EXISTS** (`viz/welllog_multi_well_adapter.py` no unit gate; single-well paths fixed) |
| kriging LOO CV uses default variogram | **STILL EXISTS** (`factor_interpolation.py:1039-1047`, `interpolation_evaluation.py:534-586`; no anisotropy passthrough) |
| constraint honesty per method | FIXED (#1234) — structured requested/applied/partial/ignored/unsupported |
| uncertainty propagation | FIXED for kriging→fusion (variance grids); IDW honestly has none |
| duplicate policy configurable | **ABSENT** (three inconsistent fixed policies: constrained-IDW first-wins, kriging mean, plain IDW none) |
| CV config = production config | **PARTIAL** (kriging variogram ignored in CV; constrained-IDW fold drops `crs=`; harness `factor.evaluate_methods` uses one IDW-proxy fold engine for ALL methods) |
| recommendation fail-closed units/CRS | **ABSENT** (units/CRS not inputs to recommendation; unknown constraint names only warn) |
| QA skipped == pass | **STILL EXISTS** in basic/extended report (`qc.py:310-316`, rules not marked evaluated/skipped; cartographic module already honest) |

Harness/DAG/runtime/catalog (files: `harness/**`, `workflow/dag/**`,
`runtime/**`, `catalog/**`):

- 56 actions / 11 domains; **only 1 verifier** (`project.health`); **only 1
  cacheable action** (`seismic.compute_attribute`); **zero actions declare
  `input_refs`**; `supports_cancel=True` declared on 2 actions whose handlers
  never read `context.cancel` (`map.create_factor_map`, `seismic.compute_attribute`).
- Unwrapped production capabilities (all live behind real services):
  `factor.interpolate`, `factor.polygonize`, `factor.compare_versions`,
  `constraint.validate`, `constraint.commit` (lifecycle doesn't exist yet),
  `fusion.run`, `compilation.validate_inputs`, `map_product.assemble`,
  `map_product.qa`, `map_product.freeze`. (`map.contour`, `map.publish`,
  `factor.evaluate_methods`, `map.describe_product` are wrapped.)
- DAG cache lookup: O(all runs × all nodes) full-JSON rescan per cacheable node
  (`dag/store.py:72-133`); run files never pruned; checkpoint rewrites entire
  run file per node transition; **no run lineage** (`rerun` creates unlinked run).
- #1224 current truth: MapExportWorker **fixed** (cancel checkpoints);
  `VizAdapter.resolve` still has **no cancel token** — WellLogLoadWorker
  boundary-only checks; slot held for whole parse.
- Catalog: `stage=DERIVED` first-class; **constraints have NO catalog entities**
  (document models + fingerprints only); lazy pre-warm N+1 residual
  (`service.py:1426-1432`); `list_all_versions` full materialization; tag
  fallback scans empty doc pre-warm; **no lease telemetry**; **no recovery
  event persistence** (in-memory reports only); GC per-item recheck done (#1222).

## C. Proposed V8 items → disposition

| Item | Disposition |
|---|---|
| Constraint catalog lifecycle (commit→DERIVED DataVersion+DataRun, version refs into FactorMapTask, stale propagation, `constraints:current` resolution) | **NEW** (extends sync-back fingerprints, no second DB) |
| Unified duplicate-sample policy for interpolation (IDW/kriging/constrained-IDW + configurable) | **NEW** (host-side, engine untouched) |
| CV/production config consistency (kriging variogram+anisotropy passthrough, constrained-IDW crs in fold, real per-method fold engines in evaluation) | **EXTEND** `factor_interpolation.py` / `interpolation_evaluation.py` |
| Recommendation fail-closed on unknown unit/CRS; unknown constraint names disqualify | **EXTEND** `interpolation_evaluation.py` |
| numpy-fallback kriging fitter parity or honest degraded | **EXTEND** `mapping/geological_pipeline/interpolator.py` |
| Mixed m/ft multi-well section gate/convert | **EXTEND** `viz/welllog_multi_well_adapter.py` |
| QA evaluated/skipped semantics | **EXTEND** `qc.py`/`map_qa_rules.py` (mirror cartographic module's honest accounting) |
| Scientific action coverage + verifiers for WRITE actions | **NEW wrappers over existing services** (no wrapper-of-wrapper) |
| DAG bounded cache index + run lineage (`parent_run_id`) + receipt pruning policy | **EXTEND** `dag/store.py`/`engine.py`/`model.py` |
| Cancellation contract: `VizAdapter.resolve(cancel=)`, WellLogLoadWorker honest phases, wire declared `supports_cancel` | **EXTEND** (#1224 remainder) |
| Catalog: batch pre-warm, `list_versions` iteration, lease/recovery telemetry events | **EXTEND** |
| Provenance graph incl. constraint versions → product | **EXTEND** `freshness.py`/`catalog/lineage_graph.py` |
| Benchmarks/adversarial matrix (samples/grids/fusion/catalog/DAG/cancel) | **NEW** local, structural gates |
| kriging barrier support | **DROP** (no scientifically defensible implementation available; documented limitation) |
| new spline/RBF methods | **DROP** (no requirement) |
| 100GB seismic anything | **DROP** (out of scope) |
| CI gate changes (#1230) | **DROP** (no CI dependency; local verification only) |

## D. Changed-file ownership / conflict risk

- This direction: `paleo_workbench/workflow/**` (majority),
  `paleo_workbench/harness/**`, `paleo_workbench/catalog/{service,queries,db,gc,telemetry*}.py` (targeted),
  `paleo_workbench/mapping/geological_pipeline/interpolator.py` (fallback parity),
  `paleo_workbench/viz/welllog_multi_well_adapter.py` (unit gate),
  `paleo_workbench/ui/pages/well_log_load_worker.py` + `paleo_workbench/viz/adapter.py` (cancel token, #1224),
  `paleo_workbench/ui/map_export_worker.py` (only if lease semantics need it).
- Direction A/B own: `native/qgis_render_bridge/**`, `ui/workstation/**`,
  mapping QGIS layers/renderers. We output pure data/descriptors only.
- Watch-outs: `workflow/map_product.py` is also read by Direction B for
  descriptors — additive changes only; `project/models.py` gets new fields
  (constraint version refs) — additive, pydantic-defaulted, no migration needed.

Overlap audit complete — implementation may proceed.
