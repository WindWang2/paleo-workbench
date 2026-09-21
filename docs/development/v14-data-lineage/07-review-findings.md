# 07 — Review findings & disposition

Two independent review rounds were run (architecture/correctness after P1–P3; adversarial/performance/lifecycle after P4). Every finding is dispositioned below.

## Round 1 — architecture/correctness (domain layer)

| # | Sev | Finding | Disposition |
|---|---|---|---|
| R1-1 | **P0** | `remove_links_for_asset` computed its count AFTER the nlohmann move (moved-from array is empty → always returned the full count) | FIXED (53c2d26a) — capture before the move |
| R1-2 | **P0** | `remove_asset_links_and_prune_reference_wells` built its surviving-link scan from the moved-from array → empty scan → pruned still-linked reference wells (data loss) | FIXED (53c2d26a) — scan before the move |
| R1-3 | P2 | slot `display` used the entity-scoped role lookup where the oracle uses the bare (well-first) lookup | FIXED — bare lookup in `_slots_for_entity` |
| R1-4 | P2 | `AssetSummary.format` lost the asset-metadata fallback for assets with no current version | FIXED — metadata fallback restored |
| R1-5 | P3 | `member_before` is not a total order on ties (std::sort unstable) | FIXED — tie-break on asset_id (total order) |
| R1-6 | P3 | `EntityDataView` member named `slots` collides with Qt's `slots` keyword macro in any TU that included a Qt header first (MSVC C2208) | FIXED — renamed to `role_slots` |

## Round 2 — adversarial / performance / lifecycle (P4 + full build)

| # | Sev | Finding | Disposition |
|---|---|---|---|
| R2-1 | **P1** | `apply_plan_rows` ignored `include=false` for already-accepted rows → a deselected file was still imported | FIXED (ac230bc9) — exclusion always maps to skip |
| R2-2 | **P1** | `apply_plan_rows` never wrote `row.primary` back → the single-primary preview was discarded at execute time | FIXED (ac230bc9) |
| R2-3 | **P1** | The 计划导入 toolbar was never placed in a layout (QVBoxLayout cast on a QHBoxLayout parent) → the two-phase ingest was unreachable in production | FIXED (ac230bc9) — splitter/center-column walk |
| R2-4 | **P1** | `WellDetailHost::update()` filled a panel on a hidden stack page (nothing called `show_well_detail(true)`) | FIXED (ac230bc9) |
| R2-5 | **P1** | `dirty_hint` resolved the working-copy path against the process CWD (registry stores it project-relative) → every edit flagged dirty | FIXED (ac230bc9) |
| R2-6 | **P1** | `run_ids_touching_assets` treated the flat `versions.run_id` column as an all-or-nothing fallback → port-less runs and Python-written stores under-reported | FIXED (ac230bc9) — union |
| R2-7 | P2 | Stale attribution charged ancestor-less items to their own asset; the oracle skips them (and `ImpactService` never emits them) | FIXED + test corrected (the test had pinned the impossible state) |
| R2-8 | P2 | Python `EntityAssetLink` has no `ordinal` → pydantic `extra='ignore'` silently reverted C++-written ordinals on a Python open→save | FIXED — field added to the Python model (round-trip safe both ways) |
| R2-9 | P2 | Lifecycle stamping wrote `artifact_kind_present` (bool) instead of the kind string, and the retention class only in the nested record where no reader looks | FIXED — kind string + top-level `retention_class` mirror |
| R2-10 | P2 | `publish_run_result` let the policy stage override the version row but placed the payload under the caller's stage directory | FIXED — stage resolved once, used by both |
| R2-11 | P2 | `json_string` threw on a present-but-null field (nlohmann `value()` only defaults on absence) | FIXED — null/type-safe read |
| R2-12 | P2 | Duplicate source entry for `closure_data_workspace.cpp` in the platform test target | FIXED |
| R2-13 | P2 | Tautological assertions (`int >= 0`) in the platform impact test | FIXED — real linked-entity / advice-line assertions |
| R2-14 | P3 | The bus refresh lambda captured `&workspace` by reference (adopted/reparented workspaces can dangle) | FIXED — QPointer guard |
| R2-15 | P3 | `IngestPlanModel` slot key omitted `entity_type` | ACCEPTED (documented): ids are type-prefixed by construction; recorded in 08-known-limitations |
| R2-16 | P3 | `posix_shim::temp_file_path` constructs `std::random_device` per call | ACCEPTED (documented): atomic-write frequency is low; noted in 08 |
| R2-17 | P3 | The Windows `strptime` replacement (sscanf) is looser than POSIX | ACCEPTED (documented): only the fixed ISO prefix format is parsed by the one caller; noted in 08 |
| R2-18 | P3 | `build_manual_edit_run` validates source ids where the Python oracle permits unknown ones ("versions may legitimately not exist yet") | DELIBERATE DIVERGENCE — the C++ commit path always has the versions durable; fail-closed keeps provenance honest. Recorded in 08 with rationale |
| R2-19 | P2 | The production runtime-bag path registers context-free manual-edit runs (empty entity/business_role) | ORACLE-FAITHFUL (the Python production caller does the same); the full `ManualEditRequest` surface exists for the entity-context caller. Recorded in 08 |
| R2-20 | P2 | `complete_manual_edit_run` does not validate committed ids or refuse terminal runs | FIXED — ids validated against the document, terminal runs refused, MAX_RUN_PORTS budget enforced |
| R2-21 | P2 | `entity_workspace.cpp` re-scans the whole link array per expansion (O(L) per well_view) | ACCEPTED (measured): 50 expansions over 100k links cost ~5M link scans ≈ ms; the catalog-read bound is the contract that matters. Recorded in 08 with the measurement |

## Post-fix verification

- Full `windows-msvc` closure build: 0 errors (also links `pwb-platform.exe`).
- V14 suites: `data.entity_domain_ops`, `data.entity_workspace`, `data.manual_edit`, `data.data_fabric_e2e`, `data.entity_workspace_scale`, `platform.closure_data` — 6/6 green (×2 runs).
- Cross-line regression: `platform.closure_mapping`, `platform.closure_review_install`, `ui_pages_data.*` — green (no sibling-line breakage).
- P0/P1: zero open.
