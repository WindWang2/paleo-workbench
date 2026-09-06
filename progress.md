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
