# Findings — Data & Runtime Foundation V6

## Environment facts
- Worktree: .worktrees/data-runtime-foundation-v6 @ feat/data-runtime-foundation-v6 (from main 295fabc3)
- Test venv (shared from main checkout): C:/Users/wangj.KEVIN/projects/paleo-workbench/.venv
  Python 3.12.13, pytest 9.1.1, pydantic 2.13.4, PySide6 present. QT_QPA_PLATFORM=offscreen.
  paleo-workbench NOT pip-installed → pytest `pythonpath=["."]` resolves code from CWD;
  always run pytest from worktree root with explicit tests/... args.
- Baseline: tests/test_catalog_service.py + test_catalog_db.py → 64 passed.
- Sibling worktree .worktrees/workstation-ux-v6 — parallel task, do not touch.

## Open issues mapped to this program (from gh, 2026-09-07)
IN SCOPE (fix in this program):
- #1211 P1 create_working_copy 无条件覆盖未提交工作副本 → PHASE 6 working-copy state machine
- #1212 P1 工程打开 GUI 线程全量物化 catalog document → PHASE 3 lazy catalog
- #1218 P2 commit_working_copy 持锁跨 payload IO → PHASE 5 (verify then fix)
- #1219 P2 成果装配先落 completed run（ghost provenance）→ PHASE 10
- #1220 P2 stale 守卫 TOCTOU + rebuild_index 绕过 → PHASE 4 CAS/BEGIN IMMEDIATE
- #1221 P2 resolve_path 无 sha/size 时无条件信任 basename → PHASE 10 fail-closed
- #1222 P2 sweep_gc 与并发注册竞态删 payload → PHASE 5 GC leases
- #1223 P2 heavy-task on_done 在 catalog close 后写旧工程 → PHASE 8 session generation
- #1224 P2 WellLogLoadWorker/MapExportWorker 假取消 → PHASE 8 real cancellation
- #1225 P2 vendored IDW 改写 BLAS env + 绕开 governor → PHASE 9
- #1228 P2 打开后 GUI 全量物化旁路家族 → PHASE 3 (UI-side lazy follow-ups)
- #1229 P2 .bak 回退把暂时不可读当损坏 → PHASE 7 project recovery
OUT OF SCOPE (well-domain/algorithms/seismic-footprint/CI): #1213(O(N×W) WellRegistry —
maybe PHASE 11 if cheap), #1214–#1217, #1226, #1227, #1230.

## Key architecture facts (from 6-way parallel audit, file:line under paleo_workbench/)
### Catalog core
- Canonical store = metadata/catalog.sqlite (WAL, busy_timeout=5000, DEFERRED txns only);
  catalog.json = export/checkpoint manifest with .bak + corrupt-isolation (catalog/store.py).
- DataCatalogService (catalog/service.py, ~3750 lines): holds full in-memory Pydantic
  CatalogDocument + _CatalogMaps (immutable-swap snapshot #619), single RLock :288.
- OPEN IS EAGER: DataCatalogService.open (service.py:667-789) → index.load_document →
  _load_document_once (db.py:1054-1199) materializes EVERY row to Pydantic + _ensure_maps
  second O(N) pass (service.py:417-456) — all on GUI thread via project_controller.py:296-299.
  `ensure_index` param is DEAD (accepted :671, never used). ensure_index_ready/sweep/migrate
  deferred to background thread (project_controller.py:312-355) but that's after the eager load.
- Stale guard #411 = check-then-act NOT CAS: revision read at service.py:887 BEFORE
  apply_changes txn; apply_changes writes catalog_revision unconditionally (db.py:1378-1385).
  rebuild_index (service.py:1005-1012) has NO stale guard + no lock; resets DB from stale
  in-memory doc. Unscoped _save(dirty=None) → reconcile() full-diff can DELETE other
  process's rows (service.py:3727 rebase_artifact_paths).
- Paged facade already SQL-backed when index current: search_assets_page/count/aggregates
  (service.py:3231-3410, _query_index_if_current :3478). UI paged mode ≥25k assets.
  Numbers @100k: page0 4.31ms, deep 7.45ms, count 3.01ms, aggregates 389ms cold.
- Payload IO outside lock for register_version (copy+hash :1357-1365), register_result_asset
  (:1471-1480), create_derived (:1944-1946). place_managed_file: temp+fsync+os.replace+
  readonly bit + known_sha verified against actual bytes (storage.py:371-465). dir fsync
  no-op on win32.
- register_derived_store (service.py:1505-1609): NO hash, NO fsync, structural fingerprint only.
- Seismic attr compute writes into derived/{asset}/{ver}/.attr-* INSIDE stage tree unreferenced
  (seismic_lifecycle.py:562); harness mapping npz direct-write into intermediate/
  (harness/actions/mapping.py:366-387) — both GC-race exposed.

### GC
- plan_gc/sweep_gc/cleanup_working_copies (catalog/gc.py) run with NO lock (documented
  catalog/audit.py:625). Classification: STAGE_ORPHAN = stage file not referenced by
  current document (gc.py:142-155); sweep = snapshot-then-delete, no recheck at unlink
  (gc.py:265-294). RACE: payload placed on disk outside lock → explicit sweep between
  place and metadata commit deletes live payload (#1222). No leases/epochs anywhere.
- Trash safe by ordering (tombstone→move). Blob GC conservative w/ content-proof adoption.

### Working copies today
- create_working_copy = full copy to working/{version_id}/ (storage.py:468-494), directory
  existence IS the state; repeat checkout REPLACES uncommitted edits (pinned as intended,
  tests/test_storage_m1.py:30-55). No registry/dirty flag/crash recovery (#1211).

### Project persistence
- Save 3-phase (project/manager.py:425-552): prepare (mtime stale guard :474-483) →
  execute worker (mkstemp+fsync+replace main→bak then tmp→main :392-423) → commit.
- Recovery _load_data (manager.py:554-576): catches (OSError, ValueError, TypeError,
  ValidationError) ALL → .bak os.replace destructive; PermissionError on main (transient
  AV/sync lock) silently replaces newer main with older .bak (#1229). No quarantine, no
  persistent recovery record (last_recovery_message on throwaway manager, UI never reads).
- No persisted project revision counter — mtime-only stale guard (false positives on sync
  tools; prepare→execute TOCTOU). Unknown fields round-trip OK (extra="allow").
- Session generation exists in ProjectController (_session_generation, guards async save
  + catalog maintenance) but heavy-task on_done in data_page etc. relies on
  `job.target is not self.project` identity checks; mapping_page._on_map_export_finished
  uses project object captured at export start, slot itself has NO check (#1223 family).

### Runtime
- TaskScheduler singleton: max 2 daemon threads (heavy lane concurrency=1 + interactive
  lane=1). Cancel cooperative (Event). Governor lease held until callable RETURNS
  (task_scheduler.py:495-499) → cancelled-but-nonchecking task blocks heavy lane + task_key
  (ValueError on same-key resubmit until old lands).
- OwnedWorkerJob: QThread per job, cancel cooperative, shutdown(3000ms) → DetachedJobKeeper.
- Cancellation: REAL for transcode/attributes/DAG-node-boundaries/factor-prepare/ONNX-tiles/
  packaging/relink/audit; COSMETIC for LAS well-log parse (well_log_load_worker.py:36-56
  check before/after only), map export render (map_export_worker.py:195-221), native render
  (by design); hashing has NO cancel (catalog/checksum.py:20-26); fast_grid.interpolate_
  idw_grid_batch has ZERO cancel checks.
- Governor bypasses: vendored fast_grid _shared_executor process-lifetime pool sized by
  os.cpu_count (fast_grid.py:19-36); _pin_blas_threads mutates OMP/OPENBLAS/MKL/NUMEXPR/
  VECLIB env vars at runtime per call + threadpoolctl used WITHOUT context manager
  (fast_grid.py:441-456) (#1225). DAG engine pool width = spec max_concurrency ungoverned
  (workflow/dag/engine.py:465-471). batch.py clamps 1..4 without governor.
- resume_pending NOT wired to project open (only on first lifecycle service use);
  docstring aspirational (seismic_lifecycle.py:460).

### Provenance/identity
- map_product.assemble_map_product (workflow/map_product.py:124-169): register_run default
  status="completed" NO outputs, THEN register_result_asset — crash between = permanent
  ghost; audit orphan_completed_run only checks {materialize, working_copy_commit}
  (catalog/audit.py:296-316) → map_product ghosts undetectable (#1219).
  Same pre-book pattern: data_lifecycle_controller materialize :860 / new_version :924
  (those ARE audit-covered + _fail_booked_run compensation).
- interchange ImportExecutor._record_run swallows exceptions (fail-open provenance,
  executor.py:114-115); caught only by unprovenanced_version audit.
- resolve_path basename fallback fail-open when version has NO sha AND NO size
  (service.py:1180-1202 _fallback_identity_ok returns True on missing facts) (#1221).
  relink_external_source itself fail-closed (sources.py:223-241 requires sha or
  size+mtime_ns). Legacy migration produces externals with NO identity facts
  (migration.py:195-208) → unrelinkable + fail-open resolve.
- Interchange packaging: catalog.json travels; provenance truncated to 1000 runs, no edges;
  vendored externals NOT rebound to in-package path.

### Concurrency/scale/tests
- NO file locks anywhere (no msvcrt/portalocker/fcntl); two instances cooperate only via
  #411 revision fence + mtime guard. SQLite: WAL, busy_timeout 5000, implicit DEFERRED
  BEGIN — no BEGIN IMMEDIATE anywhere. No two-PROCESS tests (all "cross-process" are two
  services in one process); cross-flush TOCTOU untested.
- Open memory floor = full Pydantic graph (_load_document_once). Capacity guard pins UI
  single-residency identity, not open RSS. 500k tier not implemented (heavy tier 50k/100k).
- Crash tests strong: real SIGKILL/TerminateProcess helpers (crash_kill_helper.py).
  GC-race tests MISSING. Working-copy state tests MISSING. PermissionError-on-main
  recovery test MISSING.
- CI fast gate: -m "not slow and not welllog_binding" --ignore=tests/perf --timeout=45.
  capacity marker runs in fast gate. Perf tests nightly.

## Design directions (locked into baseline doc)
1. Lazy catalog: open() reads revision+health+counts only; LazyEntityRepository (SQLite
   row→Pydantic by id + SQL list/page/aggregate/lineage); document becomes background-
   warmed cache; mutations journal entity ids during warmup, overlay after build; get-by-id
   served from SQL + identity LRU. Target open <500ms @100k.
2. Transactions: apply_changes(expected_revision) → BEGIN IMMEDIATE + in-txn revision
   compare + conditional bump (CAS); rebuild_index guarded+locked; reconcile refuses on
   foreign revision advance (typed CatalogStaleWriteError).
3. Payload protocol: staging dir + lease table (heartbeat) outside lock; move-into-place +
   metadata commit inside one immediate txn; GC consults leases + rechecks references under
   lock at unlink; register_derived_store gains fsync+staging; hash loops get cancel tokens.
4. Working copies: SQLite working_copies table state machine NONE/CHECKED_OUT/DIRTY/
   COMMITTING/COMMITTED/ABANDONED; no silent overwrite; recovery on open.
5. Project recovery: distinguish corruption (validate-fail → quarantine + .bak restore,
   recorded) from transient OSError (surface, never fallback); persistent recovery record.
6. Session generation: ProjectSessionToken (generation uuid) checked in heavy on_done
   callbacks via small guard helper; wire seismic resume_pending into project open
   maintenance; real cancel for LAS/map-export/hashing.
7. Governor: remove runtime env mutation in fast_grid; scoped threadpoolctl; executor
   width from clamp_workers; DAG pool clamped; batch.py consults governor.
8. Provenance: map_product begin→register→complete; audit covers map_product_assembly +
   interchange.import + repair for ghosts; resolve_path fail-closed without identity
   facts; migration backfills size+mtime (hash small files budget-bounded).
