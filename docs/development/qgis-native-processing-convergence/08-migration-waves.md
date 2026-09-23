# 08 — Migration waves

## Wave A — provider + representative algorithms + task bridge (new code only)

1. `libs/qgis_processing/**` skeleton: provider, feedback bridge, grid_io, task bridge (PaleoFunctionTask, PwbTaskGate, PwbTaskOwner), task source, runner.
2. Algorithms: interpolation (idw/kriging/constrained/scipy/directional), grid_contours, contour_layer_product, grid_statistics, extract_factors, factor_fusion, facies_class_grid, representative_facies, seismic ×11, well_curve_operation, well_log_match, scalar_classification, clip_to_ring/repair_ring, project_validate_sources, project_relink, batch_convert, well_head_scatter.
3. `processing_install.{hpp,cpp}` in the platform app: register provider + governance + gate at startup (after QgisRuntime::acquire).
4. Tests (libs/qgis_processing/qgis_processing_tests/): discovery/uniqueness/schema/invalid-input/CRS+extent/progress+cancel/result publishing/100+ tasks/cancel storm/admission/shutdown bounds/thread affinity/tri-entrance id parity.

## Wave B — UI default paths through Processing / JobCenter projection

1. Rewrite `job_center.*` (provider registration moves here from processing_install or vice versa — one owner: JobCenter), `make_owner → PwbTaskOwner`, remove scheduler.
2. `stage_flow_install.cpp` TaskCenter wiring → `task_source()` projection over QgsTaskManager (+ OperationRegistry merge kept).
3. `AlgorithmRunner` → delegates to `paleo:` ids via registry; `app_context.registerProductKernels` replaced by provider registration; `main_window` attribute dialog lists from provider.
4. TU-static direct-call sites (`closure_seismic_install.cpp`, `seismic_viewer/crossplot_core.cpp`) → registry by id (resolver seam for the Qt-free lib).
5. `run_map_pipeline` path → `paleo:factor_map_pipeline`-equivalent composition or direct per-step ids (extract→interpolate→contour) via runner.

## Wave C — delete JobOwner/WorkerHost consumers

Migrate all 20 JobOwner sites (list in 04) to `PwbTaskOwner`; ui_seqviz pages off `global_scheduler()`; ui_canvas/ui_review private schedulers removed; `closure_mapping_install` WorkerHost → `PaleoFunctionTask` owners (WorkerJobApi shape preserved for PreparationPage); `reissue_when_terminal` consumer (viz_c_joint_host) onto new owner; `JobOwnerRunner` → `PwbTaskOwnerRunner` (same UiJobRunner interface); WorkflowScheduler `JobScheduler&` → `RunSubmitter`.

## Wave D — JobScheduler exits the GUI product

1. CMake: `pwb-platform` and all UI libs drop `Pwb::JobQt`/`Pwb::JobRuntime`; job_runtime splits into `pwb_job_contracts` + `pwb_job_governance` (product-linked) vs `pwb_job_runtime`/`pwb_job_qt` (option `PWB_BUILD_JOB_SCHEDULER`, default ON only so the frozen oracle tests keep validating governance/scheduler semantics headlessly; GUI binary never links).
2. ui_workers include rewrite (job_contract → job_contracts).
3. Files retired outright: `qt/job_bridge.*` from product (kept headless-only for tests), `WorkerHost` class, `global_scheduler()` uses in product (API stays for headless tests).
4. Statistics captured for PR (before/after): JobScheduler consumer count, runtime LOC in product link graph, registry count, execution path count.

## Rollback / risk notes

- Frozen oracle tests (job policy/governor/bridge) keep passing — they test headless scheduler semantics that remain compilable; they are decoupled from the product.
- #1471 reissue semantics and #1224 supersede semantics must survive on the new owner/gate (tests ported).
- GUI post-process thread affinity: all result delivery via `finished()`/queued connections — asserted in tests.
