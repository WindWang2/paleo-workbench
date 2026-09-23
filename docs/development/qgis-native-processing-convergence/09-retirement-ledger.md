# 09 — Retirement ledger (QGIS replacement matrix)

## Replacement matrix (self-built → QGIS)

| Self-built | QGIS replacement | Disposition |
|---|---|---|
| `JobScheduler` (pool/queue/aging/lane) | `QgsTaskManager` (priority addTask, QThreadPool) | RETIRED from GUI product; headless build option keeps oracle tests |
| `CancellationToken`/`JobContext` | `QgsTask::isCanceled` / `QgsFeedback` + `job_contracts` vocabulary | contracts MOVED to `pwb_job_contracts` |
| 7-state machine | `QgsTask::TaskStatus` + owner-level outcome (degraded kept as outcome flag) | dropped at scheduler level |
| `JobOwner`/`DetachedJobKeeper`/DeliveryPump | `PwbTaskOwner` + QgsTaskManager ownership + `finished()` main-thread delivery | REPLACED |
| `install_quit_drain` | JobCenter quit hook over taskManager cancel + bounded wait | REPLACED |
| `reissue_when_terminal` (#1471) | ported onto `PwbTaskOwner` (same contract) | PORTED |
| task_key dedupe/supersede (#1224) | `PwbTaskGate` key registry over live tasks | PORTED (thin) |
| admission hook + lease | `PwbTaskGate` over retained governor (`try_admit`) | PORTED (thin) |
| `WorkerHost` + per-run std::thread | `PaleoFunctionTask` | DELETED |
| `global_scheduler()` product uses | owners + taskManager | REMOVED from product |
| `AlgorithmRegistry` as discovery authority | `QgsProcessingRegistry` + PaleoProcessingProvider | registry stays as kernel SDK container only |
| `AlgorithmRunner::kernels_` map | provider registration + `createAlgorithmById` | DELETED |
| TU-static registries (×2) | registry by id (resolver seam for Qt-free lib) | DELETED |
| `workflow_interpretation` AlgorithmSpec table | provider metadata (display labels/groups) | RETIRED (zero consumers) |
| job history (200) | TaskCenter bounded projection over manager tasks | UI concern |
| progress marshaling (queued hops) | QgsTask signals (queued) / finished() | dropped |

## Retained (thin, QGIS-absent)

- Governance stack: `resource_budget`, `memory_pressure`, `resource_governor`, `governance`, `job_categories` (policy/tag table) → `pwb_job_governance`.
- Paleo provenance: catalog rails, ExecutionReceipt, DependencyGraph — record-keeping only.
- `ThreadJoinGuard`, kernel-level progress/cancel contracts (`pwb_job_contracts`).
- Workflow engine orchestration (checkpoint/resume/rerun) with Processing-based node bodies.

## Before/after statistics (as built, 2026-09-23)

| Metric | Before (192422c60) | After |
|---|---|---|
| Files referencing JobScheduler/JobCenter/WorkerHost/JobOwner | 81 | 5 code-touching sites: task_bridge.hpp comment; ui_workers lifecycle TEST (headless scheduler harness, gated); closure_mapping_install.cpp comments — plus 2 stale comment-only mentions (tests/cpp/platform/test_closure_mapping.cpp, tests/cpp/viz_c/store_concurrency_test.cpp) |
| `JobScheduler` instances in the GUI product | 8 (JobCenter + global_scheduler ×4 consumers + ui_canvas ×2 + ui_review ×1 default) | **0** (one QgsTaskManager) |
| `WorkerHost` (per-run std::thread) | 1 class, 2 live lanes + 1 dead pipe | 0 (WorkerLane over PwbTaskOwner/PaleoFunctionTask) |
| GUI background execution authority | self-built dual-lane jthread pool | `QgsApplication::taskManager()` |
| Algorithm discovery authorities | 3 (AlgorithmRegistry containers ×3 instances + AlgorithmRunner map + interpretation table) | 1 (`QgsProcessingRegistry`, provider `paleo`, 31 algorithms) |
| Independent execution tracks to kernels | 4 | 2 (registry path; in-memory plane/crossplot executor table mirroring registry ids; unit tests aside) |
| job_runtime targets | 2 (runtime + qt) | 4 split: `pwb_job_contracts` / `pwb_job_governance` (product-linked) + `pwb_job_runtime` / `pwb_job_qt` (headless-only, `PWB_BUILD_JOB_SCHEDULER`, default ON for oracle tests; GUI product links neither) |
| Product link of scheduler | `pwb-platform` PRIVATE Pwb::JobQt (fail-closed) | `Pwb::QgisProcessing`; PwbNativeProduct hard closure updated |
| `paleo:` algorithm count | 0 | 31 |
| QGIS Processing provider | none | `paleo` (11 groups) |
| Retained Paleo policy (thin, QGIS-absent) | — | PwbTaskGate: governor admission + task_key supersede (#1224) + kind tags; JobCancelled → cancelled terminal mapping; #1471 reissue ported to PwbTaskOwner |
