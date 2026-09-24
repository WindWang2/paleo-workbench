# 01 — libs/job_runtime audit

LOC: ~2.2k headers + ~2.4k src + ~3k tests. Targets: `pwb_job_runtime` (Qt-free, `Pwb::JobRuntime`), `pwb_job_qt` (`Pwb::JobQt`, links Qt6::Core).

## Components

| Component | File | Class of capability |
|---|---|---|
| `JobState` (7-state), `JobCancelled`, `JobSubmitError`, `CancellationToken`, `JobSnapshot`, `JobContext`, `JobSpec`, `JobHandle` | include/pwb/job_runtime/job_contract.hpp | GENERIC scheduling (QgsTask/QgsTaskManager equivalent) |
| `JobScheduler` (jthread pool, dual lane, max-heap, aging, task_key supersede/dedupe, admission hook, bounded history, work dirs) | job_scheduler.{hpp,cpp} | GENERIC scheduling — DELETE from GUI product |
| `JobOwner`, `DetachedJobKeeper`, `install_quit_drain`, `reissue_when_terminal`, DeliveryPump | qt/job_bridge.{hpp,cpp} | GENERIC GUI marshaling — replaced by QgsTask + finished()/queued signals (manager owns tasks ⇒ keeper free) |
| `ResourceGovernor`, `governance` | resource_governor.{hpp,cpp}, governance.{hpp,cpp} | PALEO-specific admission (VRAM/ONNX/IO/RAM/CPU pressure-shed) — KEEP as thin policy behind QgsTaskManager submission |
| `ResourceBudget`, `MemoryPressureMonitor` | resource_budget.*, memory_pressure.* | PALEO-specific (no QGIS equivalent; /proc sampling, evictable caches) — KEEP |
| `JobCategory`/`CategoryPolicy` (11 categories, kind→policy) | job_categories.* | PALEO-specific task tagging — KEEP (priority/tag map) |
| `ThreadJoinGuard` | thread_join_guard.hpp | RAII util — KEEP |

## Scheduler semantics being dropped (replaced by QGIS equivalents)

- Dual-lane jthread pool + max-heap priority queue + aging → `QgsTaskManager` (QThreadPool-based, priority int on addTask).
- 7-state machine → QgsTask::TaskStatus (Queued/OnHold/Running/Complete/Terminated). `degraded` (success-with-caveat) is preserved at the **owner/outcome** level, not the scheduler level.
- Cooperative `CancellationToken` → `QgsTask::isCanceled()` / `QgsFeedback::isCanceled()`.
- task_key dedupe/supersede (#1224) → thin `PwbTaskGate` pre-submission check (active-task key registry, keyed on QgsTaskManager tasks).
- Bounded history (200) → TaskCenter projection keeps its own bounded model over manager tasks (UI concern).
- shutdown bounded drain → cancel + bounded wait on active tasks at window close; app quit handled by QGIS task manager teardown + our quit hook.

## Consumers (before)

81 files reference JobScheduler/JobCenter/WorkerHost/JobOwner. Link edges: `pwb_ui_workstation`, `pwb_closure_workflow`, `pwb_ui_controllers(+qt)`, `pwb_ui_seqviz(+qt)`, `pwb_ui_workers`, `pwb_ui_review_qt`, `pwb_ui_canvas`, `pwb-platform` (PRIVATE Pwb::JobQt), plus test targets. Full file lists in 08.

Scheduler instances in product (fragmentation): JobCenter (1+1 lanes), `job::global_scheduler()` (ui_seqviz ×4 pages), private schedulers in ui_canvas ×2, ui_review dialogs ×4.
