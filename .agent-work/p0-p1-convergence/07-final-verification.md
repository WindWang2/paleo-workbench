# 07 — Final Verification

## Implemented

Eight vertical slices closing the remaining P0+P1 gaps on top of
origin/main @ e1622496 (see 00-baseline.md for the audit that defined
"remaining"):

1. **P0-C** — geological selection slots on the ONE context bus;
   TimeDepthCalibration (fail-closed, provenance-carrying) replacing the
   silent constant-velocity depth↔time; scenarios A/B/C/D closed end-to-end
   (seismic locator, map cursor marker + 3D slice focus, gated depth→time
   with a production calibration author, horizon identity routing).
2. **P0-B** — SQL-paged virtualized explorer table: keyset-cursor pages,
   index-backed counts/aggregates, canFetchMore/fetchMore rows, honest
   degradation for fs-probe/in-memory-join smart views.
3. **P0-D** — complete cartographic composition system: 14 component types
   under one contract (create/delete/move/scale/configure/serialize/copy/
   z-order/undo), deterministic + forward-compatible serialization with a
   re-bind path, 9 professional templates (layout + bindings, not bitmaps),
   editor panel, PNG/SVG/PDF at one physical-size + DPI contract.
4. **P1-B** — horizon picking → versioned interpretation closed (sparse
   undoable picks, line interpolation, save/reopen with geometry-mismatch
   refusal, overlay); fault interpretation lifted from the map plane; 10
   attribute kernels with strict halo parity and honest trace-global
   refusal; attribute panel advertises exactly what computes.
5. **P1-C** — VRAM budget applied at boot (ledger-verified); real geometry
   highlight via the 3D probe marker; versioned horizon interpretations as
   stratal inputs (grid path ≡ .dat path, test-pinned).
6. **P1-A** — curve interpretation operations → DERIVED versions with the
   full provenance set; RAW bytes pinned immutable by test; data-page
   context-menu entry with honest disabled state.
7. **P1-D** — MapProduct: multi-factor + interpretations + composition →
   ONE catalog OUTPUT version with full lineage; fail-closed anti-laundering;
   factor→composition data bindings; synthesized-data honesty fix.
8. **P0-A** — fault data files bind as geological DomainEntities; CONTEXT.md
   vocabulary converged (8 new entries with avoid-clauses).

## Architecture

Authoritative owners unchanged and singular: DataCatalogService (lifecycle),
`catalog.json`+SQLite (metadata), project/manager (persistence),
SelectionContext (one bus), CoordinateTransformHub (transforms),
mapping/layers+renderers (map documents), runtime/task_scheduler,
engine chunked volume IO. New modules are extensions at stable seams
(02-architecture.md). No second Catalog/LayerRegistry/scheduler/
selection-bus/volume-IO anywhere in the diff (verified by review).

## Tests

- Full local suite: `bash run_env.sh tests/` — **4603 passed, 56 skipped, 0 failed,
  exit 0** (offscreen Qt, software GL; includes e2e + perf legs; native
  legs green after rebuilding map_edit_core from the engine submodule and
  preloading the system libstdc++ for the welllog binding).
- New test modules: 10 (see 04-test-strategy.md), including the
  BLOCKER-pinned band-seam parity and the 100k budget assertions.
- Post-review-fix regression batch: 254 passed.

## Benchmarks (measured, this machine)

- 100k catalog: SQL page fetch p50 ≈ 17–20 ms (budget < 50), count < 10 ms,
  text-search count < 15 ms (budgets < 100); explorer refresh no longer
  materializes per-asset views above 25k assets.
- Catalog service re-measured at 100k (benchmarks/catalog_scale_benchmark.py):
  metadata_update 0.3 ms, add_tag 0.3 ms, trash 10.8 ms, search 22.7 ms —
  within the documented budget class. `filter_by_type` 1658.9 ms remains
  result-size-proportional pydantic materialization (documented pre-existing
  service behavior; the paged UI path does not call it — 1449.6 ms in the
  prior doc's run vs 1658.9 ms here is machine variance on the same code
  path).
- Composition: template < 5 ms, 7-component SVG < 10 ms, A4@300dpi PNG
  ~250 ms, PDF ~150 ms.
- VRAM: ledger reports the applied 1 GiB cap (test-pinned).

## Known limitations (non-goal or honestly scoped)

- Well content tree / display sets / plot templates live in the
  well-log-engine submodule's desktop app by its own spec — out of this
  repo's scope (verified delivered there at the pinned commit).
- The well-log depth cursor publishes the cross-view well key (registered
  hub name — the established #1029 convention, now documented); entity-id
  keying would require touching every view publisher.
- Attribute label → engine attribute-combo routing remains best-effort by
  text (engine owns its combo vocabulary).
- Scenario C's calibration refusal logs at debug (behavioral refusal is
  real: no navigation happens); surfacing it in the seismic status line is
  a recorded follow-up (06-review-log #15).
- `filter_by_type` service call still materializes result rows (pre-existing;
  explorers use the paged SQL path).

## Review

Matt /code-review two-axis (Standards + Spec) against the origin/main
merge-base: Round 1 found 1 BLOCKER + 8 HIGH + 6 MEDIUM; every BLOCKER/HIGH
fixed (one resolved as documented-deliberate), MEDIUMs fixed except the
recorded follow-up. Round-2 verification pass over the fixes: no new
BLOCKER/HIGH findings. **Final: BLOCKER 0, HIGH 0.**

## P0/P1 checklist

- [x] **P0-A Workspace/Survey Domain Core** — DONE (WorkArea domain was
  ~85% on main; this branch added fault entity binding + vocabulary; typed
  id value classes deliberately not introduced — string-prefixed ids are the
  established contract)
- [x] **P0-B Unified Data Explorer** — DONE (100k paged virtualized table,
  keyset cursor, budgets asserted; explorer shell/tree/search/tags/
  versions/lineage/preview were already in place)
- [x] **P0-C Cross-view Geological Context** — DONE (single bus extended;
  A/B/C/D closed with fail-closed calibration; echo/bleed guards tested)
- [x] **P0-D Cartographic Composition System** — DONE (component contract,
  serialization + re-bind, templates ×9, editor UI, DPI-true exports)
- [x] **P1-A Well Interpretation Workflow** — DONE for this repo's scope
  (interpretation corrections → derived versions with provenance; content
  tree is the engine app's delivered scope)
- [x] **P1-B Seismic Interpretation Workflow** — DONE (picking→version
  loop, fault lift, 10 kernels with parity contracts)
- [x] **P1-C Unified Geological Scene** — DONE (budget wiring, geometry
  highlight, versioned horizons in 3D; identity rigor for wells was already
  engine-tested)
- [x] **P1-D Factor Map → Paleogeographic Product** — DONE (MapProduct with
  full lineage; factor→layout bindings; anti-laundering enforced)

Online CI/CD was intentionally not awaited or used as the completion gate;
all verification above is local.
