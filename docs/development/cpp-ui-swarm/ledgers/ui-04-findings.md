# UI-04 findings — page workers ported onto job_runtime (7 files)

Branch: `feat/cpp-ui-core-workers` (base origin/main @ 5a6373bd). Worktree:
`../worktrees/cpp-ui-core-workers`. Slice UI-04 of the M10 UI→C++ migration.
Precedent infra read in full: `libs/job_runtime` (CONTRACT/CATEGORIES/SCHEDULER,
CONV-30), `apps/paleo_workbench_platform/job_center.*`, and the LEGACY Python
base (`ui/owned_worker_job.py` + `ui/thread_keeper.py`).

## Scope ledger

### 本分支负责（7 Python files → C++）

| # | Python source | Worker semantics (frozen) | C++ landing |
|---|---|---|---|
| 1 | `ui/pages/contour_draft_worker.py` (91) | `ContourDraftWorker(QObject)`: narrow snapshot (`factor_map_tasks` shared + `contour_drafts` copied, NOTHING else — #850-6); `run()`: token check → `compile_contour_drafts_for_project(apply_to_map=False)` → token check → `completed(ContourDraftResult)` / `cancelled` / `failed("Class: msg")`; `finally: terminal()`. Draft id stability via snapshot-ledger upsert. Per-task `ValueError`/`ImportError` → skip. | `pwb::ui_workers::run_contour_drafts` + `make_contour_draft_job_spec` (kind `compute.contour_draft`). Slice `FactorTaskSlice` carries the resolved grid + stored engine contours (artifact store = host collect). contourpy `extract_contour_lines` = injected seam `extract_lines_fn` (different algorithm from `pwb::mapping::marching_squares` — NOT bound, see decisions D3). `upsert_contour_draft` + `line_features_from_contour_draft` ported (pure). Map-document apply = host-side commit (gap G4). |
| 2 | `ui/pages/correlation_load_worker.py` (73) | `CorrelationLoadWorker`: `cancel()`→Event; `run()`: pre-cancel → `finished` skipped; `loader(project, resource_ids, max_wells)` (injectable, default `load_correlation_wells`); exception→`failed` unless cancelled; post-cancel → `cancelled`; else `finished((logs,names,loaded_ids,warnings))`. `load_correlation_wells`: sorted `well_log` resources (name,id), id filter, `max(1,max_wells)` cap, `ref_from_resource` (type/format tables) → `adapter.resolve` → optional `merge_prediction_onto_well_log`; warnings per skipped well. | `run_correlation_load` + spec (kind `load.correlation`). `ResourceSlice` + `VizRef` ported; `_resource_path` + `is_within_directory` + `ref_from_resource` ported verbatim. `resolve_fn` + `merge_prediction_fn` = seams (engine LAS/VizAdapter not ported — G1/G2). Payload = `std::any`. |
| 3 | `ui/pages/dtw_propagation_worker.py` (136) | `bounded_dtw_band` (cell cap 4M); `DtwPropagationWorker`: `recommend_fn` FIRST (exception→None) → `recommendation_ready`; pre-cancel → `cancelled`; `compute_dtw_propagation(ref,depth,band,progress_cb)`; progress cb raises `JobCancelled` on flag → `cancelled`; `finished(pairs)`; `failed("Class: msg")`. | `bounded_dtw_band` verbatim + `run_dtw_propagation` + spec (kind `compute.dtw_propagation`). `compute_fn`/`recommend_fn` seams (engine `DTWEngine.correlate` not ported — G3; `pwb::well_science::match_curves` is a DIFFERENT algorithm, deliberately not bound — D4). Progress → `ctx.report_progress(done,total)` + typed hook. |
| 4 | `ui/pages/factor_prepare_worker.py` (88) | `FactorPrepareWorker`: snapshot preferred (host-built); `run()`: token check → `run_factor_prepare_schedule(snapshot, token, progress)` → `progress(FactorPrepareProgress)` per emit → `completed(result)` + `finished(count)` / `cancelled` (JobCancelled OR `result.cancelled`) / `failed`. Scheduler internals: `prepare_worker_count` (env 1..4 + governor clamp), clean/dirty classify (fingerprints), serial vs geometry-group parallel (ThreadPoolExecutor, per-group JobCancelled→"cancelled" tasks, other-exception→`"group failed: ..."` tasks), cancelled bookkeeping + phase emits, `FactorPrepareBatchResult` (all fields incl. timings/grid_n/power). | `FactorPrepareSnapshot` slim struct + `FactorPrepareProgress`/`FactorPrepareTaskResult`/`FactorPrepareBatchResult` field-exact ports + `run_factor_prepare_schedule` (orchestration 1:1, parallel path via `std::async` with mutex-guarded memo) + `build_prepare_snapshot` (collect helper). Seams: `classify_fn` (interpolation_fingerprint — G5), `batch_fn` (batch_prepare_factor_maps — G5), `group_key_fn` (`_task_plan_group_key`), `synthetic_points_fn` (geoviz), `grid_peek_fn` (live cache), `governor_clamp_fn`, `clock`. `commit_prepare_batch_result` = host-side apply (G6). |
| 5 | `ui/pages/geological_modeling_workers.py` (405) | FOUR workers, all `terminal()` in `finally`, NO cancel support (fire-and-forget): `GeologicalModelingWorker` — demo volume `kk+8sin(ii/8)cos(jj/8)`→uint8%256, hardcoded 4-borehole/2-tunnel/2-fault records, geoviz cylinder/tube/fault primitives, progress emits 10/30/60/80/95/100 with `time.sleep` pacing, `completed(dict)`; `StratalWorker` — demo (`make_demo_stratal_grids`+`build_proportional_surfaces`) or real (`build_stratal_grids(.dat)`/`_grids_from_interpretations(NPZ)` → `build_stratal_surfaces`); `ExportWorker` — legacy GridSpec (`export_to_flac3d/abaqus`) or V2 (`export_volume_*`/`export_mesh_*` with point_data); `AdvisorWorker` — `check_boreholes`+`check_coplanar_faults` → `completed(bh,faults)`. | `geomodel_primitives.*` (cylinder/tube/fault, float32+colors, oracle-frozen — geo3d_viz tube deliberately not reused, D5) + `stratal.*` (validate_horizon_pair, build_proportional_surfaces, demo volume+grids, ms→sample-index, scipy `map_coordinates` order=1/mode=nearest/cval=NaN port, `_ms_grids_to_preview_sample_indices` on a `StratalSceneSlice`) + `geological_modeling_workers.*` (4 `run_*` + specs). Export/advisor seams default-bind `Pwb::GeoModel` when `TARGET` exists (`legacy_export_*`, `export_volume_*`, `export_mesh_*`, `check_boreholes`, `check_coplanar_faults`); horizon `.dat`/`NPZ` loaders = `ms_grid_loader_fn` seam (G7). |
| 6 | `ui/pages/integrity_worker.py` (195) | `compute_sha256(path, max_bytes, is_cancelled)`: 65536 chunks, yield, None on cancel/missing/OSError. `IntegrityWorker`: `progress(idx+1,total,name)` BEFORE hashing each asset; cancel checks before+after progress emit + inside hash; catalog-bridged → `service.verify_integrity(version_id)` status map (verified/modified/missing/unknown), NEVER updates checksums; legacy path: missing→MISSING, unmanaged→UNMANAGED, checksum compare→VERIFIED/MODIFIED, no checksum→compute+`checksum_updates[id]`+VERIFIED (None→UNKNOWN); details strings verbatim (Chinese); break on cancel → `finished(report)` (partial report ALWAYS emitted; no `cancelled` signal); exception→`failed(str)`. | `IntegrityState` enum + `IntegrityCheckReport` (fields + `summary_text` verbatim) + `compute_sha256` (domain::Sha256, same chunk size/yield/max_bytes/cancel→None) + `run_integrity_check` + spec (kind `verify.integrity`). `IntegrityAssetSlice` (id/name/path/managed/checksum) = the collect-side of `asset_view_from_object` (G8); `verify_fn` = catalog service seam (G9). Cancelled run lands `cancelled` WITH the partial report as recorded result (scheduler partial-result contract — parity of "finished(report) with 已取消 detail", see decisions D6). |
| 7 | `ui/pages/well_log_load_worker.py` (92) | `#1224` honest cancel: `cancel()` sets event + emits `cancelling()` ONCE iff parse in flight; `run()`: pre-cancel → `cancelled` (no parse, no `cancelling`); `_parse_started=True` → `adapter.resolve(ref,project,cancel)` → `WellLogLoadCancelled`/event→`cancelled`; other exc→`failed`; `finally: _parse_started=False`; late result DISCARDED → `cancelled` (never `finished`). Adapter `_resolve_well_log`: `_find_resource`→`_absolute_path`→`is_file`→`load_well_log_from_path`→payload assembly (soft-fail message payloads, never raise). | `run_well_log_load` + spec (kind `load.well_log`) + `WellLogLoadPhase` (`requested`/`parse_active` atomics) + `request_well_log_cancel` (the `cancel()` contract: once-only `cancelling` when mid-parse; post-run cancel cannot emit — `parse_active` cleared in finally-equivalent). `resolve` seam: `_find_resource`/`_absolute_path` ported; `load_fn` = engine LAS/XML parse seam (G1). Late-result discard = scheduler cancelled-with-partial contract (D6). |

### 本分支不负责

- GUI-thread collect (ProjectDocument/AssetView materialization, `bridged_version_map`,
  `build_prepare_snapshot` on live project) — stays host-side; inputs are already-resolved slices.
- GUI-thread apply (`commit_contour_drafts` map mutation, `commit_prepare_batch_result`,
  `picks_model.add_pick`, renderer surface application) — job outcomes carry the DTOs.
- Kernel internals not yet ported (gaps below) — recorded, never faked.
- `pwb_ui_workers_qt`: rejected — JobCenter/JobOwner (CONV-30) already provides the GUI hop;
  nothing Qt-specific remains in the worker cores (decisions D1).
- No MainWindow/AppContext wiring, no Python deletion, no new `option()`s.

### Kernel gaps (seams, recorded — never faked)

| # | Missing kernel | Where it sits |
|---|---|---|
| G1 | Engine LAS/XML parse (`load_las_preview`/`load_xml_preview` + preview LRU + depth-unit wrap) — WLE exists only via `PWB_SCIENCE_BUILD_VIEWER` (heavy Qt adapter, OFF) | `load_fn` seam in well_log_load + `resolve_fn` in correlation_load |
| G2 | `merge_prediction_onto_well_log` (prediction facies merge) | `merge_prediction_fn` seam |
| G3 | `geoviz_cross_well::DTWEngine.correlate` (compact-band DTW + confidence) | `compute_fn`/`correlate_fn` seam in dtw_propagation |
| G4 | `factor_grid_result_for_task` artifact store + `apply_contour_draft_to_map`/`PaleoMapDocument` | input slices carry resolved grids/contours; map apply is host-side |
| G5 | `interpolation_fingerprint` + `batch_prepare_factor_maps` + `_task_plan_group_key` + `synthetic_sample_points` + live grid cache | `classify_fn`/`batch_fn`/`group_key_fn`/`synthetic_points_fn`/`grid_peek_fn` seams |
| G6 | `commit_prepare_batch_result` (live-project apply) | host-side apply step |
| G7 | `HorizonParser` (.dat→ms grid) + interpretation NPZ read | `ms_grid_loader_fn` seam |
| G8 | `asset_view_from_object` full AssetView | `IntegrityAssetSlice` (id/name/path/managed/checksum — exactly the fields the loop reads) |
| G9 | `DataCatalogService.verify_integrity` | `verify_fn` seam returning the status string |
| G10 | `contourpy.contour_generator` (serial) | `extract_lines_fn` seam |

## Oracle 计划

`tools/oracle/generate_ui_workers_fixtures.py`（conv12 venv: numpy/scipy/pydantic/PySide6 + geoviz
via `import paleo_workbench` bootstrap）freezes real executions: `bounded_dtw_band`,
`suggest_nice_levels(_from_range)`, `compile_contour_drafts_for_project`（真 contourpy 提取 +
stored-contour 短路）, geoviz cylinder/tube/fault primitives, stratal demo/validate/proportional/
ms-index/map_coordinates path, advisor checks, legacy exporters bytes, `compute_sha256`,
`IntegrityWorker.run` on real files, `run_factor_prepare_schedule`（clean 全真 + dirty 走
确定性 stub batch — orchestration freeze，与 C++ seam 对应）, `DtwPropagationWorker.run` /
`CorrelationLoadWorker.run` / `WellLogLoadWorker.run`（fake canvas/loader/adapter — 与 Python
测试同构）, `GeologicalModelingWorker.run`/`StratalWorker.run`/`ExportWorker.run`/
`AdvisorWorker.run`（真 geoviz + 真 exporters）。`{ROOT}` 占位、固定时间戳、`id_fn` 注入确定性 id。
C++ replay + negative self-check。

## 测试计划（ctest `ui_workers.*`）

behavior: start handshake（queued→running）、cancel-before-start、cancel-mid-run（各 worker 的
cancel 窗口/语义逐一对应 Python 测试）、progress ordering（typed hook 序列 + scheduler ratio
单调）、cancelling honest hint（well_log once-only + post-run 抑制）、partial report on cancel
（integrity）、per-task skip（contour ValueError/ImportError）、grouped parallel prepare
（cancel/error 分桶）、teardown（shutdown 时 keeper-adoptable：job 不强杀、返回后落 cancelled）、
oracle replay + negative self-check。

## Oracle parity 修复轮（31→0）

首轮 replay 31 处失配，其中 23 处为 harness 假阳性（fixture `faces` 存嵌套数组，比较器按扁平数组索引）。
真实修复 3 处 + 1 处测试边界修正：

- **`py_round`** — `value*10^n→nearbyint` 在 `2.675` 类陷阱上发散（乘积恰为 267.5 tie，真值 2.6749…）。
  改为 `snprintf %.*f`（glibc 正确十进制舍入、ties-to-even，逐位对齐 CPython `round`）；负数 digits 走
  `%.*e` 两遍格式化提取十进制指数。
- **`lerp_sample`（stratal）** — scipy `map_coordinates(order=1, mode="constant")` 的 stencil 语义：
  整数坐标恒含邻居（内部 `{k,k+1}`，顶界左移 `{n-2,n-1}`），IEEE `nan*0=nan` 使 stencil 内**任何**
  NaN 角点污染样本（零权重 i/x 邻居不豁免）。C++ 原实现漏掉 i/x 邻居污染路径。
- **`well_log_resources` replay 边界** — oracle 冻结的是 `list_well_log_resources` + wanted/cap 纯排序
  语义；测试原走全 `load_correlation_wells`（多一道 `ref_from_resource` format 门，fixture 资源无
  `format` 字段 → 全被跳过）。改为直接回放被冻结的纯函数。
- **`parallel_groups` 进度序** — Python `as_completed` 完成序是时序敏感的，fixture 冻结了特定序
  （grpB→grpA→None）。测试侧加 GroupGate：order[0] 组到达即放行，后续组仅在前一组发射后由
  progress 回调推进释放，余者 drain —— 确定性复现冻结 multiset（`executed` 计数依赖完成序）。

结果：`ui_workers.oracle` 456 checks / 0 failures（1 negative self-check verified），
`ui_workers.lifecycle` 通过。
