# 05 — Adversarial Review Findings (Round 1)

Date: 2026-08-29
Scope: `main..feat/production-workflow-convergence` (catalog, runtime, seismic pipeline, mapping, well-log, multiview)

## Method

Manual deep-read of every new file and diffed hunk plus targeted test re-runs. Each finding below carries file:line evidence.

## BLOCKER — None remaining after fixes in this round

## HIGH — Fixed in this round

### H-1: Attribute band halo blocks on the last inline band were mis-aligned
**File:** `paleo_workbench/seismic_attributes.py:42-95` — `compute_block`
**Symptom:** `test_band_output_matches_full_reference_everywhere` failed on final band `[35:36)` (1.0 frac mismatched, max diff 0.04) — the band's clamped halo block `[30:36)` (6 inlines) is shorter than the C3 kernel window (11 = 2*5+1). The old path let the kernel shrink `wil` ( `min(2*5+1, 6) = 6` ), so the cropped windows never match the full-volume reflect semantics.
**Fix:** Reflect-pad the *interior-cut* side (never a real survey edge) to restore `2*half+1` length, tracking `pad_low` offsets so the interior crop lands at the right place in the padded block. Verified: all 8 attribute tests pass, bitwise parity restored for every band.

### H-2: Tiled ONNX edge tiles used reflect padding instead of zero padding
**File:** `paleo_workbench/prediction/tiled_onnx.py:_run_tile_group` (pads before model)
**Symptom:** `_conv_model` (receptive field 3, same-padding conv) tiled vs whole-volume mismatch 0.6% of voxels — edge tiles invented structure via reflect where the whole-volume conv saw zeros.
**Fix:** Edge-tile pads now `constant=0.0` (replicates the model's own volume-boundary padding). Both models pass tiled==whole-volume.

### H-3: Engine CRS `coerce_to_project_crs` referenced stale global
**File:** `geo-viz-engine/packages/geoviz_plots/geoviz_plots/crs/__init__.py:94` — `target = _project_crs` (NameError; the variable was renamed to `_project_crs_var` contextvar). Present since the pinned submodule commit f6fbd3c4 — not introduced by this branch but surfaced by the new mapping dispatch contract tests.
**Fix:** `target = get_project_crs()` (reads the contextvar).

## MEDIUM — Fixed

### M-1: LOD `build_lod` level-store names collided across decimation strategies
**File:** `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/chunked.py:ChunkedVolumeReader.build_lod`
**Risk:** `_l1`, `_l1_mean` etc would reuse each other's level stores — different data, same path.
**Fix:** `+tile_...` suffix naming; sibling stores namespaced by strategy.

### M-2: Directional prefetcher fired on the very first slider position
**File:** `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/lod.py:DirectionalPrefetcher.update`
**Risk:** No direction known yet → wasted opposite-side reads during idle.
**Fix:** First position only baselines; batches start on the second move.

### M-3: Scheduler `cancel` on a QUEUED task skipped the `on_cancel` callback
**File:** `paleo_workbench/runtime/task_scheduler.py:cancel`
**Symptom:** `test_cancel_then_resume_completes` + `test_resume_pending...` saw `run.status == "running"` after cancel — the lifecycle's `on_cancel` (which marks the run `cancelled`) was never called for queued-but-not-yet-running tasks.
**Fix:** Queued-cancel path captures and fires `on_cancel` outside the lock. `shutdown` similarly fires queued `on_cancel`s.

### M-4: `TaskScheduler._run_task` callback ordering race
**File:** `paleo_workbench/runtime/task_scheduler.py:_run_task`
**Symptom:** `test_retranscode_marks_old_derived_stale` flaked — `_wait_done(handle)` observed DONE before `on_done` (which registers the DERIVED version) had run.
**Fix:** `on_done`/`on_cancel` now run *before* the terminal state is published; callers that see DONE can rely on the side effects having completed.

### M-5: `register_derived_store` did a full `rglob` scan before the catalog lock
**File:** `paleo_workbench/catalog/service.py:register_derived_store`
**Risk:** Large 100G stores — best to scan outside the lock (intentional). The `rglob` is intentionally outside (the comment says so) — not a bug. Left as-is after confirmation.

### M-6: Single-well composite panel contract test pinned the old deliberately-Legacy behavior
**File:** `tests/test_composite_visualization_panel.py:test_composite_well_host_prefers_retained_engine_when_available`
**Fix:** Flipped to assert the #1053 engine-preferred behavior (engine view owns the screen when importable).

## LOW — Deferred (tracked, not blocking)

- `test_map_line_label.py::test_mapping_page_wires_layer_visibility_and_property` — batch pre-existing.
- C++ QGIS bridge: `-fsyntax-only` verified only (no vendored QGIS build env locally); needs real QGIS build validation in CI.
- Well-log `import welllog` raises `ImportError: GLIBCXX_3.4.35` on this conda libstdc++ — covered by the ImportError probe contract; native rendering untestable locally.
- Full acceptance benchmark (`benchmarks/acceptance_100g.py`) runs on a 2.4 GB quick2g volume; full100g (106 GB) is extrapolated (see 04-benchmarks).

## Confirmation

Re-ran the full new-suite batch after fixes:

```
tests/test_mapping_crs_idw.py            ...s + tests/test_qgis_label_wire.py ...    [pass]
tests/test_seismic_attributes.py         8/8    (bitwise parity)
tests/test_tiled_onnx.py                 5/5    (tiled == whole-volume, real ORT)
tests/test_lod_render_path.py            9/9
tests/test_task_scheduler.py            11/11
tests/test_seismic_lifecycle.py          6/6
tests/test_chunked_volume_reader.py     14/14
tests/test_catalog_sqlite_canonical.py  15/15 + perf/test_catalog_scale 4/4
tests/test_view_coordination_seismic_producer.py 25/25 (incl. e2e engine signal)
tests/test_issue1053/1054                14/14 + test_composite... fixed
```

Environment note: `test_native_backend.py::test_map_edit_core_version...` (`map_edit_core` missing) and `test_welllog_engine_native_integration.py::test_binding_contract_not_silently_skipped` — pre-existing, unrelated to this branch.
