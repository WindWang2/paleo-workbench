# 02 — workflow engine/runtime/graph audit

Targets: `pwb_workflow_engine`, `pwb_workflow_graph`, `pwb_workflow_runtime` (all Qt-free, oracle-frozen Python ports).

## Key facts

- No worker pool anywhere in the three libs. Both engines (`Engine`, `RunEngine`) drive nodes **serially on the calling thread** (`run_engine.cpp` ready_batch limit=1; `_drive_parallel` documented DEFERRED). The only concurrency primitive is `AdmissionGate` (bounded latch, default max_concurrency=1).
- Bridge to job_runtime is external: `closure_workflow::WorkflowScheduler` submits **one run as one job** on the host `JobScheduler`; nodes inside stay serial. UI side: `ui_controllers::qt::WorkflowController(jobs->scheduler(), …)`.
- DAG split today: execution DAG = engine specs + Kahn/ready_batch; provenance DAG = `workflow_graph::DependencyGraph` rebuilt from catalog listings (`version --input--> run --output--> version`); UI progress = `WorkflowPlanView` (no production consumers yet).
- Provenance recording: per-node `register_run` → `register_result_asset`/`register_version` + `attach_run_output` on `CatalogRepository` (RuntimeStore in-mem / FileCatalogRepository JSON / PersistentRuntimeCatalog / SQLite adapter). Cache identity = canonical_hash(action_id, version, params, sorted input vids).
- Node→kernel calls go through function tables (`NodeRegistry` / `RunFunctionMap` / `StepHandler`); only two mapping ops exist (`map.extract_factors`, `map.interpolate_idw`); production recompute path (`workflow_controller.cpp`) uses `PlanExecutor` + seam handlers bound in `workflow_install.cpp`.

## Convergence decision (Phase 5)

- QGIS model API is sufficient only for linear parameter pipelines; Paleo workflows carry checkpoint/resume/rerun/provenance semantics QGIS models don't have. Per prompt: Paleo workflow engine **keeps orchestrating**, but:
  - each node's body must invoke a `QgsProcessingAlgorithm` (by paleo algorithm id) — new `workflow_engine/src/ops.cpp` bodies route through the Processing entry seam instead of raw kernels;
  - run submission uses `QgsTask` (via the injected host submit seam replacing `JobScheduler&`);
  - provenance DAG stays as-is (record-keeping only, never a second scheduler).
- `WorkflowScheduler` constructor changes from `JobScheduler&` to a `RunSubmitter` std::function; the Qt host binds it to QgsTaskManager.

## Phase 5 outcome (as built)

- Run submission: `WorkflowScheduler` now takes a `RunSubmitter` (std::function); the product binds it to the QgsTaskManager bridge — one workflow run = one background execution on QGIS' pool. The engines never owned a worker pool and still don't.
- Production recompute/prepare: `WorkflowController(PwbTaskGate*, ...)` — bodies run as PaleoFunctionTask over QgsTaskManager (admission via the retained governance stack).
- Node bodies: the headless engine's in-memory JSON node contract (`map.extract_factors` / `map.interpolate_idw`, payload = FactorDataset/FactorGrid, frozen against Python oracle fixtures) is NOT restaged through the QGIS parameter contract (feature-source/file destinations): staging would change node semantics and break the frozen oracles, and constructing QGIS layers off the GUI thread is not supported. Per this direction's fallback clause the engine keeps orchestrating; the kernels behind both node ids are the SAME kernels the provider registers (`paleo:extract_factors`, `paleo:interpolation_idw`) — id bridge documented in 03. Execution (scheduling/threads/cancel/progress) is fully converged; algorithm identity is converged; parameter-schema staging is not (deliberate, documented).
- Provenance DAG unchanged (catalog rails; record-keeping only).
