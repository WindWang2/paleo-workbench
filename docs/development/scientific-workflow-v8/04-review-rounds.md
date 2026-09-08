# V8 Review Rounds Record

Three full review rounds over `feat/scientific-workflow-v8`, all findings
fixed in-commit before the PR.

## Round 1 — correctness / regression / scientific semantics
2×P0, 6×P1, 8×P2 found; all fixed (`fix(v8): review round 1` commit).

| # | Sev | Finding → Fix |
|---|---|---|
| 1 | P0 | streaming `w_sq += contribution*membership` poisoned confidence with `0*NaN` at partial-coverage cells → `np.where(mask, …)` + V6-equivalence regression test |
| 2 | P0 | kriging CV applied a 2.5:1 anisotropy frame for DEFAULT configs (production runs isotropic — `anisotropy_requested` gate now mirrored exactly) |
| 3 | P1 | multi-factor batch stamped the LAST task's samples+report on every task → per-task tuples |
| 4 | P1 | `duplicate_policy='error'` aborted the whole batch in classify → per-task fail-isolate |
| 5 | P1 | unit gate allowlist missed `mD`/`1` (factor-units authority values) |
| 6 | P1 | constraint-ref resolution failure fabricated CURRENT → UNKNOWN |
| 7 | P1 | `weight_provenance` unreachable via `run_integrated_fusion` → forwarded |
| 8 | P1 | fusion verifier checked nonexistent `version_id` key (false-failed every registered run) |
| 9 | P1 | `factor.interpolate` laundered cancellation into FAILED → explicit `(TaskCancelled, JobCancelled)` re-raise |
| 10 | P1 | `factor.polygonize` extent mis-ordered → `grid.extent` authority + public wrapper |
| P2 batch | | DAG index idempotent/updated_at-ordered/thread-locked; `_parse_started` reset on all paths; token protocol supports `is_cancelled`; metric-best among ELIGIBLE only; variance version ids in descriptor+registration; provenance qc drops private keys; `from_dict` restores weight_provenance; verifiers skip honest error payloads; validate_inputs resolves constraints refs; staleness detail text |

## Round 2 — architecture / duplication / authority boundaries
1×P0, 3×P1, 6×P2; all fixed (`fix(v8): review round 2` commit).

| # | Sev | Finding → Fix |
|---|---|---|
| 1 | P0 | constraint asset lookup scanned `catalog.document` (EMPTY pre-warm on lazy-opened services — the production GUI path) → second asset per group on re-commit; replaced with lazy-safe `list_assets`/`list_versions` + lazy-reopen regression test (REPRODUCED by reviewer, now pinned) |
| 2 | P1 | `resolve_constraint_ref` crashed on the injected `CoreCatalogAdapter` (no `.document`) → constraints:current permanently UNKNOWN in the mapping workspace UI; `_as_service` unwrap + port-adapter test |
| 3 | P1 | `fusion.run` used the process-global catalog singleton instead of the injected context port |
| 4 | P1 | two verbatim ~100-line recommendation adjudication copies (already drifted once) → shared `adjudicate_recommendation` |
| 5-10 | P2 | string verdicts kill the workflow→mapping_workspace import cycle; provenance fusion section hoisted (was O(products×runs)) + `list_runs` lazy-safety; public `polygonize_factor_grid`; exception-name heuristic → explicit tuple; stray scratch file removed |

Architecturally-confirmed sound (kept): the constraint commit write-path
(sanctioned atomic APIs only), sample-normalization as single duplicate
authority, the honest-cancellation contract (ADR-2), the fusion streaming
maths, ADR-4 (index is a lookup aid — full re-validation verified).

## Round 3 — UX / performance / adversarial / lifecycle
Run by the main agent (review subagent timed out on the loaded machine);
release-blocking checks verified directly:

- **Old-data reopen safety**: old `QualityReport` dicts (no `rule_status`)
  load with defaults; new reports round-trip; `WorkflowRun.parent_run_id`
  and `FusionModel.weight_provenance` are additive with stable fingerprints
  (verified R2 + re-verified); `FactorMapTask` V8 state lives in the
  free-form `parameters` dict.
- **Interchange/packaging**: no interchange code serializes `QualityReport`
  fields explicitly (project `model_dump` carries them generically); the
  telemetry `events.jsonl` is an append-only log under the artifacts tree —
  harmless to packaging, never read as truth.
- **Adversarial inputs**: NaN coordinates in constraint hashing (canonical,
  deterministic — and sync-back filters NaN vertices upstream); 1e308
  duplicate values overflowed the mean `sum()` → replaced with incremental
  mean (finite verified); unicode well-id joins stable; provenance node ids
  unique (kind collisions deduped).
- **Perf re-check**: constraint pin hashing at interpolation time is the
  500-line hash (~ms per group; 20-group budget test < 5s);
  `normalize_factor_samples` is called ≤3× per task per batch (classify /
  group-key / apply) — linear, covered by the 100k budget test; fusion
  conflict diagnostics add one O(N·H·W) elementwise pass (bounded by the
  500×500×50 < 30s budget test).
- **Docs accuracy**: `02-verification.md` test counts match the files;
  `01-architecture.md` updated by the round-1/2 fix commits themselves.
