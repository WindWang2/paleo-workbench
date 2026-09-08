# V8 Verification Evidence

All verification is LOCAL (no CI dependency, per goal constraints). Python
3.12.13 venv; worktree `feat/scientific-workflow-v8`.

## New test files (V8)
| File | Covers | Result |
|---|---|---|
| `tests/test_sample_normalization.py` | duplicate policy authority (11) | 11 pass |
| `tests/test_factor_v8_duplication_cv_parity.py` | production dup policy, fingerprint targeted invalidation, kriging CV variogram/anisotropy parity, constrained-IDW fold CRS, recommendation gates, per-method evaluation (15) | 15 pass |
| `tests/test_multi_well_unit_gate.py` | mixed m/ft section semantics (7) | 7 pass |
| `tests/test_constraint_versions.py` | M2 lifecycle: commit/no-op/chain, pins, stale propagation, version diff, `constraints:current` (16) | 16 pass |
| `tests/test_harness_scientific_pipeline_actions.py` | M6 actions + verifiers (12) | 12 pass |
| `tests/test_well_load_cancel_honesty.py` | M8 cancellation checkpoints + honest phases (6) | 6 pass |
| `tests/test_dag_cache_index_lineage.py` | M7 index + lineage (9) | 9 pass |
| `tests/test_factor_fusion_v8.py` | M5 streaming equivalence, conflicts, variance registration, weight provenance, sensitivity single-compute (9) | 9 pass |
| `tests/test_qc_rule_coverage.py` | M11 evaluated/skipped + publish visibility (5) | 5 pass |
| `tests/test_catalog_telemetry_v8.py` | M9 events + batch pre-warm (6) | 6 pass |
| `tests/test_provenance_graph.py` | M10 lifecycle graph (4) | 4 pass |
| `tests/perf/test_v8_goal_perf.py` | M12 perf matrix (slow-marked) (11) | 11 pass |

## Regression (existing suites re-run after each milestone)
- factor/interpolation/fingerprint/fusion/integrated-compilation/map-product/
  QC/map-qa/QGIS-multi-well/harness/action-library/catalog-lc/gc/lazy/scale/
  perf-v7 — all green at each commit point (see commit sequence).
- Full non-slow suite: see `02b-full-suite.log` excerpt below (filled after
  the final run).

## Key adversarial cases pinned by tests
- twin wells double-vote (plain IDW) — merged, surface equal to single-twin
  reference; `keep` policy preserves legacy exactly;
- kriging LOO with production variogram ≠ default fit (RMSE differs);
  residual x/y aligned to deduped unique locations (order-shuffled input);
- mixed-unit section: ft numbers become metres exactly (0.3048), external
  meter tops converted on foot sections, unknown-unit well refused on foot
  section, kept (V6 compromise) on meter section;
- unchanged constraint commit = no-op; edited constraint → exactly the
  consuming tasks stale, other-horizon tasks stay current;
- fusion: agreeing factors → 0 conflict; opposed factors → 0.5 mean
  conflict; all-NaN cell stays nodata; no (n,h,w) stacks (structural);
- DAG cache: 30-run history → exactly 1 run deserialized on hit; identity
  miss → 0 deserializations; running/from_cache nodes unindexed;
- cancellation: before-parse → no parse runs; mid-parse → `cancelling`
  signal + late result discarded; pre-cancelled adapter call raises the
  typed error (never a message payload);
- QC: no inputs → 3 rules skipped with reasons, no low_confidence issues,
  coverage counts visible; publish gate names the skipped rules;
- recommendation: unknown unit/invalid CRS/unknown constraint →
  `recommended_method=None` with reason on every entry, metrics kept.

## Perf budgets (structural-first; absolute ceilings generous for CI noise)
- kNN IDW: 10k<25s / 50k<90s / 100k<240s on 500×500 (measured well under).
- Streaming fusion 500×500×50 < 30s; ×5 < 5s; no 3-D temporaries (monkeypatch
  np.stack gate).
- Normalization 100k samples < 30s (linear).
- Constraint content hash 20 groups × 25 lines(10 pts) < 5s; unchanged
  re-commit < 1s.
- DAG identity digests 100 nodes < 2s.
