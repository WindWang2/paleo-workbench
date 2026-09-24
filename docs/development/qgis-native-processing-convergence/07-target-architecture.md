# 07 — Target architecture

```
QAction / Agent / batch / E2E
        ↓ (paleo algorithm id + QVariantMap params)
QgsProcessingRegistry  →  PaleoProcessingProvider (id "paleo")
        ↓ createAlgorithmById → prepare/runPrepared/postProcess
QgsTaskManager (QgsProcessingAlgRunnerTask | PaleoFunctionTask)
        ↓ QgsProcessingContext + QgsProcessingFeedback(+MultiStep)
Paleo science kernel (Qt-free, unchanged)  +  Paleo provenance (catalog rail, post-hoc)
        ↓
QGIS result layers (raster file / feature sink / layersToLoadOnCompletion)
```

## New library `libs/qgis_processing` (target `pwb_qgis_processing`, alias `Pwb::QgisProcessing`)

Links `PwbQgis::Sdk` (QGIS core), `Pwb::JobRuntime-governance` (budget/governor/pressure — see split below), `Pwb::MappingKernel`, `Pwb::FactorFusion`, `Pwb::WellScience`, `Pwb::SeismicAttributes`, `Pwb::Algorithms`, `Pwb::Cartography`, `Pwb::Catalog`, `Pwb::Interchange`… as needed per algorithm TU (PRIVATE where possible).

Components:

1. `provider.hpp/cpp` — `PaleoProcessingProvider : QgsProcessingProvider`, id `"paleo"`, `loadAlgorithms()` registers all algorithm instances. Group ids: `well`, `seismic`, `mapping`, `constraint`, `factor`, `interpolation`, `cartography`, `project`, `quality`, `conversion`, `analysis`.
2. `algorithms/*.cpp` — one file per group; each algorithm subclasses `QgsProcessingAlgorithm`, declares QGIS parameter schema, `processAlgorithm` adapts params → kernel types, runs kernel with a feedback bridge (`QgsProcessingFeedback` → kernel progress/cancel; implemented inline in the adapters — there is no separate `feedback_bridge.hpp`), publishes results as raster (QgsRasterFileWriter) / vector sink / files / numbers.
3. `grid_io.hpp/cpp` — FactorGrid ↔ QGIS: write GeoTIFF via `QgsRasterFileWriter` (float32, geotransform + CRS from context/extent param), read points layer → SamplePoint vector (fields x/y/value), read QgsVectorLayer constraints → BarrierLine/BoundaryPolygon/DirectionLine, read raster layer → `mapping::Grid` (ascending axes).
4. `task_bridge.hpp/cpp` (Qt) —
   - `PaleoFunctionTask : QgsTask` — generic body runner (`std::function<bool(PaleoTaskBodyContext&)>`), progress via `setProgress`, cancel via `isCanceled()`, `finished()` delivers outcome on main thread. Replaces JobSpec.run bodies + WorkerHost threads.
   - `PwbTaskGate` — admission + dedupe: wraps the retained governance stack (`try_admit` → bounded deferral or reject with `PaleoTaskRejected`), task_key supersede registry keyed on live QgsTaskManager tasks, priority translation from `job_categories` policy table.
   - `PwbTaskOwner` (QObject) — UI ownership slot replacing `JobOwner`: `start(kind, title, body, on_done, on_progress)`, single-flight, `cancel()`, `shutdown(wait_ms)` (cancel + bounded waitForFinished; manager keeps ownership so no adoption keeper needed), released-flag delivery suppression, `reissue_when_terminal` preserved (needs the same "delivery after terminal" loop on GUI round).
5. `task_source.hpp/cpp` (Qt) — stateless `QgsTaskManager → TaskRow` projection for the Workstation TaskCenter (`tasks/progress/status/cancel`), reading `QgsTask::property("pwb.kind"/"pwb.run_id"/"pwb.task_key")` tags set by the gate/owner. Provenance run id is an extra column only.
6. `runner.hpp/cpp` — unified entry: `run_paleo_algorithm(id, params, project, feedback)` sync (main-thread `run()`) plus `PaleoAlgorithmTask` (a `QgsTask` wrapping prepare/runPrepared/postProcess) for the async path. There is no `submit_paleo_algorithm` helper. Used by AlgorithmRunner, batch, E2E.
7. `job_compat.hpp/cpp` — JobSpec/JobOwner vocabulary shims over the task bridge (`start_job_spec`), so existing GUI supervision code keeps its `JobSpec` bodies and outcome mapping.

Agent tool inventory/ActionSpec generation (the originally sketched `agent_tools.hpp/cpp`) was not implemented — agent integration reads the registry through `paleo_algorithm_ids()` where needed.

## job_runtime split

- **Stay in `libs/job_runtime`, still built (tests + governance consumers)**: contracts vocabulary shrinks to what kernels need; scheduler+qt bridge **removed from the product link graph** (Wave D). Concretely:
  - new target `pwb_job_contracts` (Qt-free): `KernelProgress`/cancel vocabulary + `ThreadJoinGuard` — included by ui_workers and algorithm wrappers;
  - `pwb_job_governance` (Qt-free): resource_budget/memory_pressure/resource_governor/governance/job_categories (policy table only);
  - `pwb_job_runtime` (scheduler) + `pwb_job_qt` (JobOwner bridge): headless-only — built only when `PWB_BUILD_JOB_SCHEDULER` (ON for its oracle tests; the GUI product never links them).
- ui_workers switches from `pwb/job_runtime/job_contract.hpp` to `pwb/job_contracts/kernel_context.hpp` (same shape: report_progress/check_cancelled/sleep_interruptible — moved, not reinvented).

## JobCenter (rewritten)

`JobCenter` now: registers `PaleoProcessingProvider` into `QgsApplication::processingRegistry()` (idempotent), owns `PwbTaskGate` (+governance install), `make_owner()` returns `PwbTaskOwner`, `task_source()` feeds TaskCenter, `shutdown_workers()` cancels owners bounded + relies on manager ownership. `scheduler()` API removed. `alive_` flag kept (bodies still poll it at safe points).

## Execution path convergence

- GUI factor map / seismic attribute supervision / SEG-Y import / previews: bodies wrapped in `PaleoFunctionTask` via owners (identical outcome contracts, `UiJobOutcome` mapping preserved).
- Algorithm executions (seismic attrs, interpolation, contours, stats, fusion, well ops, validation, batch): via `paleo:` ids through the registry — UI dropdowns read `PaleoProcessingProvider::algorithms()`.
- workflow: `RunSubmitter` seam (std::function) replaces `JobScheduler&`; node bodies route via `runner.hpp`; provenance unchanged.
- Agent: inventory + execution from registry (Phase 6).

## Provenance / execution split

Provenance remains: catalog `register_run` rails called by the product paths after algorithm completion (post-processor or caller), never inside `processAlgorithm` (which must stay re-runnable/pure). Execution DAG = QgsTaskManager dependencies + workflow engine; provenance DAG = workflow_graph/catalog (unchanged); UI progress DAG = TaskCenter projection + WorkflowPlanView.
