# 10 — Test evidence (as built, 2026-09-23)

## New (libs/qgis_processing/qgis_processing_tests) — 3/3 green (3 consecutive rounds)

- `qgis_processing.provider` (0.3s): provider idempotent install; ids unique, `paleo:`-prefixed; per-id displayName/groupId; idw schema INPUT/XFIELD/YFIELD/VALUEFIELD/CRS/OUTPUT; unknown id → nullptr; seismic group ≥ 11; `to_paleo_algorithm_id` mapping.
- `qgis_processing.run` (0.7s): real IDW run over an in-memory point layer → float32 GTiff (16×16), VALID_COUNT/GRID_MIN/MAX outputs; output reloads as QgsRasterLayer; `paleo:grid_statistics` on the result (TOTAL_COUNT=256); `paleo:grid_contours` LEVELS="0.5,1.5" → 2 levels + loadable sink; invalid XFIELD → error; determinism (two identical runs, equal stats); `paleo:scalar_classification`; `paleo:extract_factors` JSON records.
- `qgis_processing.task_bridge` (7.8s): owner complete/progress/cancel/single-flight/degraded/fail(double path)/JobCancelled→cancelled; 120-task storm through the shared gate (countActiveTasks==0); 50-task cancel storm; task_key duplicate rejection + QUEUED supersede; bounded shutdown(200ms) with late-delivery suppression; paleo_task_rows/cancel projection; `reissue_when_terminal` exactly-once on GUI thread; global gate cleanup.

Defects these tests caught and fixed: 7 × parameterAsSink leaks (file sinks never finalized), governor-less gate cancelled every task (nullptr lease semantics), VALID_COUNT label, `sizeof(const char*)` prefix-strip bug in algorithm_exec (broke section attributes).

## Full suite (build/native-product, ctest -j4)

- 256/259 tests pass (98.4%). Remaining 4 failures are pre-existing/environmental, verified against the baseline `main` checkout at the same commit:
  - `prediction.runtime` — missing `libonnxruntime.so` on this host (ONNX runtime not installed); fails identically without these changes.
  - `ui_data_core.import_oracle`, `closure_science.core` — fail on baseline main as well (fixture/environment).
  - (`viz_d.closure` was a real regression from this branch — `sizeof` prefix bug — and is FIXED; suite now green there.)
- Platform suites central to this convergence: `platform.*` 33/33, `job_runtime.*`/`job_qt.bridge` 8/8 (headless scheduler oracles still validating governance), `viz_*` 22/22, `ui_controllers/closure_workflow/ui_seqviz/ui_canvas/ui_review/seismic_viewer` 19/19, `qgis_processing.*` 3/3.
- Lifecycle/stress specifics: 100+ queued tasks (120) pass through the gate; preview-cancel storm (50) drains to zero; shutdown bounded (200 ms budget honored); app-quit drain (5 s cap, cancelAll) in JobCenter; GUI post-process thread affinity asserted (deliveries on owner thread; finished() main-thread contract).

## Build

- Full tree (incl. `pwb-platform`): 0 errors at -j4 (GCC 16.2.1; sporadic ICE in stl_algo/qbrush/qvariant retried per known procedure — identical commands pass on retry).
- Configure gate: `PwbNativeProduct.cmake` hard closure now requires `Pwb::QgisProcessing` for `pwb-platform`; `PWB_BUILD_JOB_SCHEDULER=OFF` configures and builds contracts+governance with the GUI product absent scheduler targets (verified in a throwaway build dir).
