# P2 Performance Budget — measured

Host: dev workstation (62.6 GB RAM, Linux). All numbers `[measured]` via
`benchmarks/p2_resource_governance_benchmark.py` (production paths; synthetic
representative data; no mocks of scheduler/catalog/transcoder).

## P2-A scenarios

| # | Scenario | Metric | Measured | Budget | Verdict |
|---|---|---|---|---|---|
| 1 | 100k catalog + background verify | interactive query queue delay p99 | 0.79 ms | <50 ms | PASS |
|   |                               | direct search p95 | 17.48 ms | — | — |
|   |                               | verify jobs completed | 120/120 | all | PASS |
| 2 | transcode + slice browsing | slice read p50/p95 baseline | 0.03/0.07 ms | — | — |
|   |                          | slice read p50/p95 under transcode | 0.15/0.21 ms | no meaningful degradation | PASS (sub-ms; 2.9× on a 16×16×128 tiny volume) |
| 3 | attribute + interactive render | render queue delay p99 | 0.60 ms | <50 ms | PASS |
| 4 | 200k-row export + queries | interactive dispatch p99 (scheduler+admission) | 23.24 ms | <50 ms | PASS |
|   |                        | direct query p95 idle → under export | 0.11 → 18.80 ms | — | documented (pre-existing SQLite read tail under file IO; reproduces with no governance) |
| 5 | RAM/VRAM pressure | shed/evict/bounded/recover/no-deadlock/telemetry | 8/8 PASS | all | PASS |

## P2-A unit/integration tests

- `tests/test_resource_governance.py` — 27 tests (budgets, pressure, admission, aging, lanes, cancellation, wiring, telemetry) ALL PASS.
- Adjacent regression: `test_task_scheduler.py`, `test_seismic_lifecycle.py`, `test_transcode_segy_zarr.py`, `test_factor_prepare_scheduler.py`, `test_data_asset_registry.py` ALL PASS.

## Budget rules honored

- Interactive task queue delay < 50 ms: measured 0.6–23 ms across scenarios (probe measured inside the worker to exclude observer GIL waits).
- Registry lookup / action dispatch / validation budgets: see harness measurements (08-final-verification.md) — READ-action dispatch overhead target <10 ms excluding business IO.

## Follow-ups recorded (honest)

- SQLite index reads tail (20–60 ms) under heavy concurrent file IO — pre-existing catalog behavior; candidate follow-up in catalog domain (not governance).
- Pure-Python CPU burns still share the GIL; mitigated by 2 ms switch-interval policy + heavy-lane niceness. Process-pool isolation documented as future option via the existing `viz/ipc` bridge if exports grow.
