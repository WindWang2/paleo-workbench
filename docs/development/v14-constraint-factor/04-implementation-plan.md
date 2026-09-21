# V14-CONSTRAINT-FACTOR — 04 实现计划

## 里程碑

### M1 — 内核模块（libs/closure_workflow/factor_prepare_production）
1. `LiveFactorGridStore`（LRU + 密封条目 + fingerprint 条件逐出）。
2. `build_prepare_slice`：root JSON → PrepareProjectSlice（含 source_json 保留、sample_points any 装载、grid_metadata/parameters 装载）。
3. `fingerprints_for_task` 胶水：约束解析（break/direction/boundary）+ `factor_host::build_factor_fingerprints` + memo（键=Python 契约）。
4. `classify_fn`：胶水 + `classify_factor_recompute`（has_live_factor_grid 接 store）。
5. `batch_fn`（`apply_interpolation_isolated` 移植）：
   - 读取/归一化 sample_points → `mapping::normalize_factor_samples`；
   - 方法路由：idw/kriging → `interpolate_factor`（boundary 进入 options.boundary）；constrained_idw → wells/boundaries/barriers/directions 构造 + `generate_constrained_idw`（Config 推导 = Python adapter 语义：value/search/decluster 从样本推导、分辨率 clamp 20–200、direction 活跃时 decluster 强制 0）；cubic/directional → per-task 诚实失败；
   - 约束消费：break 折 fault_polylines（仅 idw/constrained）、direction 参数（anisotropy 进指纹与 kriging anisotropy 不启用——按 Python：kriging 仅在显式 anisotropy_requested 时启用；本线保持 kriging 各向同性 + 方向线进指纹/diagnostics）、boundary 环（constrained 域）；
   - `_attach_result_to_task`：任务 JSON 补丁（03 契约字段全表）+ `LiveFactorGridStore::store`；
   - 每任务 try/catch 隔离（非 JobCancelled → status=failed + last_error，批次继续）。
6. `group_key_fn`：纯 IDW（IDW/idw/mock）→ plan 摘要（xy 归一 + grid_n + power + breaks），其余 nullopt。
7. `grid_peek_fn/governor_clamp_fn/synthetic_points_fn/stratigraphy_with_horizon_fn`。

### M2 — commit 与 catalog
1. `commit_prepare_batch_result`：代数门 → cancelled 处置 → created-defaults bootstrap（首次/迟到合成默认 #1159）→ per-item（reused 跳过；error/task None 丢弃；未知 id 规则；指纹复验；定点替换；grid store/clear）。
2. `register_factor_map_run` C++（03 契约；catalog 可空降级）。
3. `commit_contour_drafts_full`：upsert 保 id + paleomap_documents 推送。

### M3 — app 接线（closure_mapping_install.cpp）
- `BEGIN V14-FACTOR PREPARE` 命名块替换 675-724 假 worker：
  - `ClosureContext` 增 `LiveFactorGridStore`、`FileCatalogRepository`（随项目 reopen）；
  - `set_prepare_worker_fn`：GUI 线程 snapshot → WorkerHost 线程 `run_factor_prepare_schedule`（真 seams）→ marshal 回调（progress/completed/failed/cancelled）；
  - `set_commit_prepare_fn` → `commit_prepare_batch_result`（+catalog）；
  - `set_snapshot_task_count_fn`/`set_factor_map_tasks_fn` 复用既有。
- `set_commit_contour_fn` → `commit_contour_drafts_full`。
- 切项目：reopen catalog、保留 store（进程级，跨项目条目按 task id 命名空间隔离——Python 进程级同行为）。

### M4 — cross-well 因子上下文
- `FactorContextProvider` 小接头：给定井链 + 当前 project root → 每井采样点/因子值/约束 pins（供剖面轨迹着色/标注），复用 well identity 既有注册表。接线到 viz_b dock 的数据侧（不改渲染）。

### M5 — 测试与证据
- 见 05-test-plan。
- 性能基线脚本化（bench 二进制或测试内计时断言）。

## 提交切分（logical commits）
1. `feat(closure_workflow): factor prepare production kernel — seams, live grid store, slice builder`
2. `feat(closure_workflow): prepare commit + factor_map catalog registration + contour upsert/map-apply`
3. `feat(platform): bind real factor prepare kernel into PreparationPage install`
4. `feat(crosswell): factor context provider wiring`
5. `test(closure_workflow): factor prepare production oracle/degenerate/commit/staleness suite`
6. `test(platform): preparation page real-kernel E2E`
7. `docs(v14): constraint-factor line ledger`

## 风险与回退
- 风险：#1436 合入后 closure_workflow CMakeLists 冲突 → 两行加法，trivial。
- 风险：FileCatalogRepository 双开（他线同文件）→ 本线文件名 `workflow_provenance.json` 为 cpp-close-02 既定名，若他线已开则复用同一实例（读 lease 后协调；当前无他线使用）。
- 回退：app 接线块整体位于命名标记内，可单独 revert 恢复"诚实失败"面。
