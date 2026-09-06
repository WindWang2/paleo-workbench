# Progress — Data & Runtime Foundation V6

## Session 2026-09-07
- Created worktree .worktrees/data-runtime-foundation-v6, branch
  feat/data-runtime-foundation-v6 off main @ 295fabc3
- Verified test env: main .venv Python 3.12.13 / pytest 9.1.1 / pydantic 2.13.4
- Planning files reset for this task
- Next: baseline test run, then parallel subsystem audit (A–L)

## PHASE 3 complete — lazy catalog (commit 2)
- db.py: shared row→model builders; lazy getters get_asset_model/get_version_model/
  get_run_model/list_asset_models/list_run_models/list_version_models_for_asset/
  list_all_version_models/child_version_models/list_tag_models/tags_for_version/
  tag_ids_for_asset
- service.py: open(lazy=True); warm_document/require_warm/_warm_locked;
  _ensure_maps inline-warms; hot getters SQL fast path w/ _lazy_read_cache;
  resolve_asset_models; get_lineage lazy path; close() zero-mutation manifest skip;
  _WARM_REQUIRED_METHODS decorator loop (68 methods); ensure_index dead param removed
- queries.py search_assets lazy resolver (was: index rows filtered to empty pre-warm)
- adapter.py: list_versions/list_runs lazy-safe; _tag_by_id/_tag_names/_asset_for
  lazy branches; FIXED pre-existing main bug: _scan_external_by_path dangling
  reference in _find_external_by_path (3 adapter_e2e tests failed on main)
- project_controller: lazy open + warm first in maintenance thread
- Tests: tests/test_catalog_lazy_open.py (11 tests incl. open budget + warm race +
  eager/lazy equivalence). Regression: 282 catalog tests + controller/capacity green.

## PHASE 4 complete — transaction CAS (#1220, commit 3)
- db.py: CatalogStaleWriteError moved here (service re-exports); apply_changes
  opens BEGIN IMMEDIATE + in-txn revision CAS (expected_revision kwarg);
  reconcile gains expected_revision incl. empty-dirty stamp branch
- service.py: _flush_canonical_locked/_ensure_index_fresh pass baseline;
  rebuild_index under lock + stale guard + re-baseline; removed dead
  _sync_index_best_effort (guard bypass)
- adapter.py: restored _scan_managed_raw/_scan_external_by_path named
  fallbacks (2nd pre-existing main breakage from e01cc3cb; 2 batch_dedup
  tests red on main) + lazy pre-warm early-out
- Tests: tests/test_catalog_transaction_cas.py (TOCTOU window sim, unscoped
  reconcile refusal, rebuild guard, REAL subprocess commit, batch atomicity)
- Regression: 134 catalog tests green.

## PHASE 5 complete — payload staging leases + GC coordination (#1222, #1218)
- db.py: staging_leases table (connect-time idempotent + _SCHEMA_DDL +
  _DELETE_ORDER); acquire/release/heartbeat/active_staging_targets(ttl=1h)/
  prune_stale methods
- gc.py: plan skips leased prefixes (stage/temp/blob/empty-dir, auto+explicit);
  sweep_gc(report=None) re-validates referenced+leased under service lock in
  64-item chunks (closes plan→sweep TOCTOU AND place→commit window);
  stale leases pruned at explicit plan
- service.py: _payload_staging_lease ctx + _staging_target/_blob_staging_target;
  wired register_version (incl. blob-root target), register_result_asset,
  create_derived, promote_version; commit_working_copy(asset_id=None)
  restructured — payload IO no longer under the lock (#1218)
- adapter _register_produced leased; seismic attribute job: lease acquired at
  start, per-band heartbeat (VolumeAttributeJob.on_band), released in
  on_done/on_fail/on_cancel; harness mapping npz lease around write+register
- register_derived_store needs no lease (move+commit already fully in-lock,
  protected by chunked recheck)
- Tests: tests/test_catalog_gc_registration_race.py (adversarial register||
  sweep, stale-report sweep, lease TTL expiry, blob survival, #1218 lock
  release during IO). 118-test regression green.

## PHASE 6 complete — working-copy state machine (#1211)
- db.py: working_copies registry table (connect-time + _SCHEMA_DDL + delete
  order); register/get_by_path/get_live_for_source/list/update_state/remove
- service.py: create_working_copy(version_id, allow_replace=False) — live
  copy REUSED (no silent overwrite; explicit allow_replace discards+recreates);
  identity = working_id + source version (never display name); concurrent
  checkouts converge (placement retry + idempotent temp+replace);
  list_working_copies/working_copy_state (conservative mtime/size dirty hint)/
  discard_working_copy (explicit; committing copies protected)/
  recover_working_copies (committing→evidence-based heal; missing-file rows
  dropped); commit_working_copy transitions committing→(commit)→row removed,
  failure → back to dirty
- project_controller maintenance: recover_working_copies after warm
- Tests: tests/test_catalog_working_copy_lifecycle.py (7: reuse+edits kept,
  name-collision identity, crash-after-copy reopen, crash-during-commit both
  evidence branches, discard terminal, concurrent convergence, save-as orphan)

## PHASE 7 complete — project recovery decision table (#1229)
- manager.py _load_data: PermissionError/OSerror → typed ProjectUnreadableError
  (NEVER .bak fallback — main+backup untouched); FileNotFoundError → interrupted-
  save restore; JSON/validation → corruption quarantine (*.corrupt-<ts>, catalog
  precedent) + .bak restore; unusable .bak → original error re-raised
- Persistent record: ProjectMeta.last_recovery {source, recovered_at, error,
  quarantined} set on the model at load (snapshot keeps disk truth → next save
  persists it even when otherwise clean)
- Stale guard v2: snapshot gains disk_sha256; mtime drift + identical hash =
  benign external touch (re-baseline + proceed); content change → refuse
- controller: ProjectUnreadableError mapping with retry message
- Fixed 4th pre-existing main failure: unknown-section warning dead since
  extra=allow (#1170) — detection now diffs declared model_fields
- Tests: tests/test_project_recovery_v6.py (6) + regression 54 green

## PHASE 8 complete — session generation + real cancellation (#1223, #1224)
- catalog_is_current(service) in catalog/runtime (+__init__ re-export):
  backend identity IS the session token (set/reset swap at every open/close);
  unwraps adapter .service. Seismic lifecycle on_done/on_fail/on_cancel embed
  the guard; mapping_page export slot checks captured project vs page project
- resume_pending wired into project-open maintenance (interrupted transcodes
  no longer sit 'running' until unrelated lifecycle activity)
- Real cancellation: sha256_file(cancel=) chunk-granular (ChecksumCancelled,
  never a partial digest) wired through service.verify_integrity(cancel=);
  map export render_and_save(cancel=) checkpoints between native→fallback,
  pre-decoration, pre-save; scheduler QUEUED-duplicate supersede (cancelled
  request never hangs the next; RUNNING refusal message honest)
- Tests: tests/test_runtime_session_and_cancel.py (6) + regressions green

## PHASE 9 complete — governor convergence (#1225)
- fast_grid (vendored IDW): REMOVED all runtime OMP/OPENBLAS/MKL/NUMEXPR/
  VECLIB env mutation; threadpoolctl now used as a SCOPED context per batch
  (restored after; was called without with — global forever); single-thread
  path keeps full-core BLAS but scoped; pool width stays budget-derived
  (ComputeSettings.cpu_workers ← governance set_cpu_percent at bootstrap)
- workflow DAG _drive_parallel: pool width = min(spec max_concurrency,
  clamp_workers('background.compute')) — spec value is upper bound only
- interchange batch: constructor clamp consults clamp_workers('background.io')
- Tests: tests/test_resource_governance_convergence.py (env-untouched,
  scoped-limit restore, DAG clamp contract, batch governed, import-time clean)
- Pre-existing main failure #5 confirmed out-of-scope (kriging dispatch #1227)

## PHASE 10 complete — provenance atomicity + identity fail-closed (#1219, #1221)
- map_product.assemble_map_product: run booked RUNNING → register_result_asset
  → complete; registration failure compensates to failed (no permanent ghost)
- audit orphan_completed_run now covers map_product_assembly + interchange.import
- service.repair_ghost_runs(): completed producing runs w/o outputs → failed
  (+ghost_repair note); wired into project maintenance
- resolve_path._fallback_identity_ok: no sha AND no size → False (fail closed,
  #1221) — identity-less versions surface missing instead of binding a
  same-named stranger
- migration: legacy externals without checksum/size gain a SAFE stat
  backfill (size + mtime_ns in external_stat metadata; no guessed digests)
- Tests: tests/test_provenance_and_identity_v6.py + 71-test regression green

## PHASE 11 complete — scale fixtures + benchmarks (§13)
- benchmarks/catalog_scale_v6.py: production-API seeding (real import_raw
  batch) + --direct-seed metadata-stress tier (500k, direct rows, honest
  labeling); measures §13 list incl. concurrent conflict flag
- Measured @20k production on this (slow, Defender-fsync) Windows box:
  open_lazy 13.2ms | first_page 7.2ms | deep_page 6.5ms | get_by_id 0.3ms |
  tag 8.6ms | wc checkout+commit 33.8ms | manifest export 358ms |
  REOPEN EAGER 33,072ms (!) | conflict detected=1
  → lazy open is ~2500× the eager reopen on this box; scale-independent
- BONUS FIX: ensure_catalog_layout root now RESOLVED — Windows 8.3 short-path
  project dirs crashed place_managed_file relative_to (found by bench)
- tests/test_catalog_scale_v6.py: CI-size gates (lazy<500ms, page<150/200ms,
  get<10ms, warmup-during-query correctness, conflict at scale)
- #1213 WellRegistry O(N×W): documented as known limitation (well-domain,
  out of v6 data/runtime core)

## PHASE 12 complete — 3 review rounds + fixes (commit 11)
R1(data correctness)/R2(concurrency)/R3(perf/adversarial/recovery) ran as
independent agents over 295fabc3..5078bfec.
P1 FIXED:
- R3#1 _staging_target used stage.value ("output") not STAGE_DIRS ("outputs")
  — OUTPUT leases never matched; now on-disk names. Race test proven
  load-bearing (red with bug / green with fix).
- R3#2 import_raw (primary bulk funnel) + register_derived_store paths
  lacked leases — import_raw now leases RAW dir + blob root.
- R3#3/#1211 fail-open: registry degradation clobbered uncommitted copies —
  create_working_copy now fail-CLOSED on disk evidence (existing file w/o
  row reused unless allow_replace).
- R3#4 vacuous race test rewritten (gate on EVERY placement pre-commit).
- R2#1 mapping_page guard read nonexistent self.project (registration dead
  code, wrong message on every export) → self._project.
P2 FIXED:
- R1#1/R2#3 pre-warm foreign-revision drift served empty fallbacks —
  _query_index_if_current/queries.search_assets trust the store pre-warm.
- R1#4/R3#7 recovery quarantined main BEFORE validating backup — validate
  first; R1#5 stale recovery attrs reset per load.
- R1#10 assets load ORDER BY rowid (lazy/eager parity).
- R2#4 transcode _register_derived session guard (mirror of attr path).
- R2#6 supersede fires on_cancel (side effects unwind).
- R2#5 _pending_commit_assets placeholder set guards purge/maintenance
  zombie classifiers during the #1218 lock-free window.
- R3#11 removed committed debug artifacts (.scratch/cas_smoke, wc_dbg).
- catalog_is_current semantics refined: absent backend ≠ stale (the hazard
  is a REPLACED backend); updated tests accordingly.
DOCUMENTED (not code-fixed): rebuild/write_all CAS bypass (explicit
maintenance op, narrow), lease TTL vs >1h single placements, pre-warm N+1
resolvers (bounded by warm window), recover spoof via source_uri, legacy
fact-less externals permanently fail-closed (intended #1221).
