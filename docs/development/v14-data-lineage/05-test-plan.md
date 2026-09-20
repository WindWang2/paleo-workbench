# 05 — Test plan

| Suite (file) | Kind | Covers |
|---|---|---|
| `tests/cpp/data/entity_domain_ops_test.cpp` | domain/unit + persistence | role registry table parity; ordinal upsert/normalize/round-trip; links_for_*/entity_ids_for_asset; remove_well_entity; prune reference wells (touched/shared/manual matrices); old-project compat (no ordinal → 0) |
| `tests/cpp/data/entity_workspace_test.cpp` | domain/unit + negative | index O(W+L) with THROWING catalog source (structural zero-read proof); slot assembly parity cases; sorting (primary, ordinal, name); unknown role synthetic slot; unknown asset `<未注册资产>`; unresolved split; WC filtering; stale opt-in; rollups; related runs |
| `tests/cpp/data/manual_edit_provenance_test.cpp` | domain + integration | build_manual_edit_run validation (unknown/uncommitted source → error); register → commit → complete chain; run visible in lineage; no fabricated author (unknown); idempotent complete |
| `tests/cpp/data/lifecycle_enforcement_test.cpp` | negative/fail-closed | ephemeral kinds refused by managed funnel; intermediate/derived/output defaults applied; metadata stamping idempotent; existing metadata wins |
| `tests/cpp/data/entity_workspace_scale_test.cpp` | scale structural | 10k wells/100k links/100k assets seeded store; root index no catalog reads; expand-one-well bounded statement count (counter hook); no 100k materialization (memory/time ceiling); project switch clears state |
| `tests/cpp/data/data_fabric_e2e_test.cpp` | cross-module E2E | 18-step loop (contracts §F) + appendix (duplicate/missing member/corrupted hash/crash recovery/CAS) |
| `tests/cpp/platform/test_closure_data_workspace.cpp` | Qt offscreen | nav tree populated from real store; selection → filter query; well detail panel fed; lineage action opens dialog with real rows; impact preview text; ingest plan dialog decision flips + execute; project close clears |
| existing suites regression | — | `data.*` suite rerun (frozen oracle replay must stay green — proves no frozen-core drift) |

Parity/oracle: role registry + entity ops + workspace slot semantics frozen against
`paleo_workbench/project/roles.py`, `project/domain.py`, `catalog/entity_views.py` @ base SHA
(read-only reference; Python executed only as fixture GENERATOR for the registry table where
useful, never as a production dependency).

Acceptance gates: P0/P1 findings zero before PR; frozen `data.*` ctest slice green ×2;
new tests green ×2 (flake check); offscreen platform test green.
