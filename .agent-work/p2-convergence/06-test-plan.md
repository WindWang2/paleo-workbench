# P2 Test Plan & Coverage

## New test files (this branch)

| file | scope | tests |
|---|---|---|
| `tests/test_resource_governance.py` | budgets (CPU/IO columns, degrade, pressure scale), monitor (transitions, relief, rate limit), admission (ceilings, IO slots, RAM soft limit, pressure shedding, allowances), scheduler (aging, admission leases, strict interactive lane, deferred-not-dropped), categories (mapping + ladder), cancellation adapters, governance wiring, telemetry snapshot | 29 |
| `tests/test_provider_sdk.py` | descriptor validation matrix, registry (duplicates/version/quarantine/naked/family sort/built-ins/entry-points-off), schema subset semantics, executor (happy path provenance, invalid params, undeclared inputs, exception wrap + run fail, governor lease release, CRITICAL shedding), built-ins (kriging real engine + diagnostics, empty dataset rejection, determinism bit-equal, bad volume rejection, backend probe honesty) | 31 |
| `tests/test_harness_core.py` | spec validation, tool-schema derivation, registry (duplicates/invalid/DESTRUCTIVE refused, default inventory 20 actions, tool schemas 1:1), executor (unknown action, params, permission, context, metrics, isolation, lease release), dispatch overhead budget (<10 ms), O(1) lookup, validators (all-NaN/thin/good/inverted-axis maps, empty map, missing composition) | 23 |
| `tests/e2e/test_harness_scenarios.py` | scenarios A–E on production paths (synthetic LAS wells + synthetic SEG-Y → transcode → zarr; real catalog service + adapter): well location map + labels + components + validation; W23 open + GR/RT/AC display + template; coherence via provider with catalog DERIVED + lineage; kriging factor map + legend/colorbar/scale/north + validation PASS; export → catalog OUTPUT + fail-closed gates + workspace-confinement + no-overwrite boundaries; context awareness; tool schema JSON | 7 |

All green: **90 new tests** (plus geoviz submodule: no new tests needed — the setter is
covered indirectly via governance wiring tests and the L1 evictable).

## TDD process

Each module landed red→green: tests written with the module, failures fixed in
place (several design bugs caught: inverted coverage-thin condition, endpoint-only
axis monotonicity check, lease protocol dropping deferred tasks, IO slots blocking
interactive work, bool-as-number schema hole, FakeCatalog run-id semantics).

## Regression strategy

- Adjacent existing suites rerun after every wiring change: `test_task_scheduler`,
  `test_seismic_lifecycle`, `test_transcode_segy_zarr`, `test_factor_prepare_scheduler`,
  `test_data_asset_registry`, `test_catalog_adapter_e2e` — all green.
- Full local corpus: `run_env_p2.sh tests/` (offscreen Qt, py3.13) — final result in
  08-final-verification.md; known environment-limited files (missing optional C++
  extensions) fail identically on clean main (P1 baseline comparison).
- Benchmarks: `benchmarks/p2_resource_governance_benchmark.py` five scenarios (§05).

## What is deliberately NOT mocked

scheduler, governor, catalog (real DataCatalogService + CoreCatalogAdapter),
transcoder, interpolation engines, attribute kernels, export renderer
(offscreen production backend), LAS loader.
