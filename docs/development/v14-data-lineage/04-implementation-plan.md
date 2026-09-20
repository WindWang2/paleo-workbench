# 04 — Implementation plan

Phases map to commits; each lands compile-clean + tested before the next starts.

## P1 — Domain foundation (data_suite + project schema)
1. `libs/data_suite/include/pwb/data/role_registry.hpp` + `src/role_registry.cpp`
   (roles.py parity table + lookups + vocabulary spans).
2. `libs/project/src/schema.cpp`: add `ordinal` Int field (default 0) to `kEntityAssetLink`.
3. `entity_identity.{hpp,cpp}`: ordinal on upsert; `EntityLinkView`; `links_for_entity` /
   `links_for_asset` / `entity_ids_for_asset`; `remove_links_for_asset` /
   `remove_well_entity` / `remove_asset_links_and_prune_reference_wells` /
   `is_reference_well`.
4. Tests: `tests/cpp/data/entity_domain_ops_test.cpp` (registry table snapshot, ordinal
   round-trip incl. old-doc normalize, prune rules incl. shared/touched/reference matrices).

## P2 — Entity workspace read model
5. `libs/data_suite/include/pwb/data/entity_workspace.hpp` + `src/entity_workspace.cpp`:
   `AssetSummary/RoleSlot/WorkingCopyLite/StaleLite/EntityIndexEntry/EntityDataView`,
   `WorkspaceCatalogSource`, `EntityWorkspaceService` (index + views + sorting + unknown
   handling + bounded probes), `RepositoryWorkspaceSource` (lazy SQL: `get_asset_models`
   500-chunks, current-version lookups, `list_working_copies`, runs by asset; document
   snapshot only inside `entity_staleness`).
6. Tests: `tests/cpp/data/entity_workspace_test.cpp` — fake source (incl. throwing source
   proving zero-catalog index), Python-parity slot assembly cases, ordinal/primary sorting,
   unresolved/unknown surfacing, WC filtering, stale opt-in, rollup counts.

## P3 — Provenance + lifecycle closure
7. `libs/catalog/include/pwb/catalog/manual_edit.hpp` + `src/manual_edit.cpp`
   (`build_manual_edit_run` pure assembly + validation).
8. Closure adapter: `register_manual_edit_run` / `complete_manual_edit_run` bound into the
   runtime bag (seams currently UNSET in `closure_catalog_install.cpp`).
9. Lifecycle enrichment in data_suite import path + closure import funnel
   (`lifecycle_for_artifact`, must_register refusal, metadata stamping).
10. Tests: `tests/cpp/data/manual_edit_provenance_test.cpp` (+ closure-level run through
    CommitCoordinator commit with manual_edit run id → provenance chain intact).

## P4 — Product wiring (apps + ui_pages_data new files)
11. `apps/paleo_workbench_platform/closure_data_workspace.{hpp,cpp}`:
    nav-tree population from the live project document; well-detail producer
    (`EntityDataView` → `WellDataViewSlice` → existing panel); lineage explorer action
    over ui_review dialog; impact preview over `DataDetailPanel`; selection-driven refresh
    with generation guard (reuse refresh path patterns).
12. `libs/ui_pages_data/include/pwb/ui_pages_data/ingest_plan_model.{hpp}` +
    `src/ingest_plan_model.cpp` (Qt-free review state machine over the domain plan) and
    `qt/ingest_plan_dialog.{hpp,cpp}` (review UI: entity/role/primary/ordinal/include/
    duplicate decision; execute with progress; cancel).
13. Wire `plan_import_requested` + nav tree into the data workspace host (viz_e/
    closure_preview install — additive named block; NO edits to #1434-leased files).
14. Tests: `tests/cpp/platform/test_closure_data_workspace.cpp` (offscreen: nav tree
    populated from a real store; selection → well detail; plan dialog happy/negative).

## P5 — Scale + E2E
15. `tests/cpp/data/entity_workspace_scale_test.cpp`: 10k wells / 100k link rows /
    100k-asset sqlite store (direct-row seeded) — root index without catalog reads
    (throwing source), expand-one-well batched lookups bounded (statement counter),
    keyset behavior, late-generation no-pollution.
16. `tests/cpp/data/data_fabric_e2e_test.cpp`: the 18-step cross-module loop
    (project → well → imports → roles/primary/ordinal → working copy → commit →
    INTERMEDIATE run → DERIVED run → manual edit run → upstream bump → stale → explain →
    impact → save → reopen → identity/version/member/lineage preserved) + duplicate /
    missing member / corrupted hash / crash recovery / CAS conflict appendix.

## P6 — Verification + review + PR
17. Full local build (windows-msvc preset, DATA=ON, -j4) + targeted ctest slices ×2.
18. Two independent reviews (architecture/correctness; adversarial/performance/lifecycle)
    → fix P0/P1 → rerun.
19. Docs 07-09, lease update, rebase check vs origin/main, push, PR (no auto-merge).

## Invariants held throughout
- No edits to #1434-leased files; no frozen-oracle core changes; new C++ only.
- Shared files (root CMakeLists, app install cpp): additive named blocks only.
- All new domain code Qt-free; UI adapters in separate TUs.
