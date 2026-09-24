# 00 — Overview / Baseline

- Baseline: `origin/main` = `192422c60` (merge of PR #1480, 2026-09-23). Reviewed PRs #1478–#1481 (already in baseline): persistence/numerics/UI-lifecycle hardening, incl. #1471 terminal-aware JobOwner reissue.
- Branch: `feat/qgis-native-processing-task-framework` (worktree `/home/kevin/projects/paleo-qgis-processing`).
- Goal: converge Paleo's self-built algorithm registration / background execution / task UI onto QGIS Processing (`QgsProcessingRegistry`) + `QgsTaskManager`. Paleo keeps only geology kernels, provenance, and QGIS-absent resource policy as thin adapters.
- QGIS SDK: vendored tree `main/third_party/qgis` @ `cpp-migration-plan-v1-568-g192422c60`, linked via `PwbQgis::Sdk`; runtime init in `libs/qgis/src/qgis_runtime_entry.cpp` (`QgsApplication::init()+initQgis()`), so `QgsApplication::processingRegistry()` / `taskManager()` exist for the whole product process.
- Method: per-round audit → design → implement → delete old layer → build/test → review → fix → re-audit. Parallelism ≤ j6 (normally j4).
- Companion worktrees (boundaries): shell/action (Prompt 1), layer tree (Prompt 2), data/provider (Prompt 3), layout/export (Prompt 5). This direction owns `libs/qgis_processing/**`, `libs/job_runtime/**`, `libs/workflow_runtime/**` (scheduler seams), algorithm adapters, `processing_install.*`, `job_center.*`.

## Ledger index

- 01 — job_runtime audit (scheduler/contracts/governance/Qt bridge)
- 02 — workflow engine/runtime/graph audit (DAG split, provenance, node execution)
- 03 — registry inventory (7 registries, 4 execution tracks, id chaos)
- 04 — JobCenter / WorkerHost / UI execution audit
- 05 — science kernel inventory (migration candidates)
- 06 — QGIS SDK API verification (headers, 4.0-generation API)
- 07 — target architecture
- 08 — migration waves (A–D) with consumer lists
- 09 — retirement ledger + before/after statistics
- 10 — test evidence
