# V14-CONSTRAINT-FACTOR — 00 基线

- 日期：2026-09-20
- Base SHA：`412d8baf22a6a928c860e2e3d6c1108a9c035c78`（执行时 `origin/main`）
- 分支：`feat/v14-constraint-single-factor-native`
- Worktree：`/home/kevin/project/paleo-workbench-v14-constraint-factor`

## 执行时仓库状态（实测，非 Prompt 快照）

- `git fetch` 后 `origin/main == 412d8baf`，与 Prompt 快照一致。
- Open PR（实测 3 个，Prompt 只预告了 #1434）：
  - **#1434** `fix/open-issues-batch` — 批量修 #1339-1345/#1357/#1358/#1385/#1388/#1392/#1427-1431（workflow_graph 语义、curve_expr、polygonization r[0] 闭合、QGIS mirror/export 性能、表格性能、卫生）。
  - **#1435** `devin/1789909230-cpp-final-closure` — native product 迁移矩阵/构建接线（根 CMakeLists、cmake/*、app_context.cpp、tools/migration）。
  - **#1436** `feat/cpp-residual-conversion` — 基于 #1434 基线：job_runtime ResourceGovernor/Budget、ui_data_core resources 服务、closure_workflow/map_compile、workflow_runtime/run_orchestration 骨架、ui_canvas fallback 渲染器。**触及 `libs/mapping_kernel/src/{representative_facies,layer_products,extract,polygonization}.cpp`、`libs/factor_host/src/semantics.cpp`、`libs/job_runtime/**`**。
- 五路并行租约区 `.git/paleo-v14-parallel/leases/`：`v14-qgis-control.json`（Prompt3，libs/workspace、mapping_document、ui_widgets/qgis、native/qgis_render_bridge、qgis_layer_control）已存在；本线新增 `v14-constraint-factor.json`。
- 其他 worktree：`paleo-issue-fixes`（#1434）、`paleo-conversion-push`（#1436）、`paleo-workbench-v14-qgis-layer-control`（Prompt3）、`/tmp/pwb-main-ab`（A/B 基线）。

## #1433 披露的核心缺口（执行时验证仍然存在）

`apps/paleo_workbench_platform/closure_mapping_install.cpp:675-724`：

1. `set_prepare_worker_fn` 绑定的是一个 **staging 假 worker**：`start.message = "网格计算内核未接入"`，task result `error = "网格计算内核未接入（等待科学计算内核绑定）"`。
2. `set_commit_prepare_fn` 是空 stub（`return 0`），任务补丁/状态/代数守卫全部未落地。
3. 等值线 leg 是**真核**（`viz_charts::extract_contour_lines` marching squares + `ui_workers::compile_contour_drafts_for_project`），但 commit 只做 `root["contour_drafts"] = *payload` 的整段替换——Python 的 upsert（保 id）+ `apply_contour_draft_to_map`（推送 paleomap_documents line features）未移植。

## 执行时 C++ 科学核现状（能力地图，审计结论）

| Capability | C++ kernel | 生产接线 | provenance | UI | parity | gap |
|---|---|---|---|---|---|---|
| factor input collect | `mapping::extract_factors`（extract.hpp） | workflow_engine ops / map_pipeline_runner | — | WellTablePanel 展示 | oracle | well_table→sample_points 桥 C++ 缺（Python well_table.py） |
| sample normalize | `mapping::normalize_factor_samples` | science_service | — | — | oracle | 无 |
| IDW | `mapping::interpolate_factor`（interpolator.hpp，power/kNN/radius/全邻、精确命中后写） | map_pipeline_runner/science_service | — | — | interpolator_oracle（19 用例） | 无 |
| kriging | `interpolate_factor`（numpy-OLS 经验变差球状/指数/高斯 + ridge 回退 + 方差格） | 同上 | — | — | oracle | geoviz WLS 估计器为不同估计器（决策：用本核，见 02） |
| constrained_idw | `constrained_idw::generate_constrained_idw`（3779 行，EDT/LOS/走廊/锚定） | science_service（Engine B） | — | — | constrained_idw oracle（12 用例） | 无 |
| 样条/方向趋势 | **无 C++ 核**（geoviz scipy/directional 未移植） | — | — | — | — | 诚实禁用+原因（不伪成功） |
| nearest | `nearest_neighbor_class_grid`（分类用，非标量） | mapping_bind | — | — | oracle | 标量 nearest 非 UI 方法（Python 也无） |
| contour 提取 | `viz_charts::extract_contour_lines` + `mapping::marching_squares_contours` | closure_mapping_install（生产） | — | — | oracle | 无 |
| 等值线分级 | `ui_workers::suggest_nice_levels` | 生产 | — | — | oracle | 无 |
| 指纹/分类 | `factor_host::build_factor_fingerprints/classify_factor_recompute` | workflow_runtime freshness（部分） | — | — | oracle | `fingerprints_for_task` 项目级胶水留宿主（本线补） |
| 调度器 | `ui_workers::run_factor_prepare_schedule`（classify→reuse→串/并行） | **无生产绑定**（KernelUnavailable） | — | PreparationPage 生命周期完备 | ui_workers oracle（脚本 seams） | **本线核心** |
| live grid 缓存 | **无**（Python factor_grid_artifacts.py） | — | — | — | — | 本线补 |
| commit 补丁 | **无**（空 stub） | — | — | — | — | 本线补 |
| catalog 登记 | `workflow_runtime::CatalogRepository` seam + `FileCatalogRepository`（持久） | map_product/runtime_service 有范例 | ✔ | — | — | `register_factor_map_run`（factor_map run + INTERMEDIATE 版本 + domain_task_id）C++ 缺，本线补 |
| constraint 消费 | constraint_layers JSON + `workflow_interpretation/constraint_capabilities` + constrained_idw 核 | science_service 请求级 | `constraint_versions` C++ 存在 | 约束编辑属 Prompt3/QGIS 会话 | — | prepare 路径的 break/direction/boundary 解析胶水本线补 |
| staleness/recompute | freshness/recompute_plan/`kStepOrder(factor_map)` | workflow_controller（seams 未绑） | ✔ | — | — | 任务级 DIRTY_* 分类已有；run 级经 grid_artifact_version_id（本线 stamp 后即通） |
| cross-well | `WellIdentityRegistry`/tops/picks/DTW/section planner（#1419） | viz_b dock | sidecar | dock | — | map↔profile linkage provider 表面缺（本线补科学上下文接线） |

## 结论

main 上的缺口是**生产接线缺口**，不是算法缺口：内核（IDW/kriging/constrained_idw/等值线/指纹）全部存在且有 oracle；调度器移植完备但 seams 未绑。本线使命 = 把 `FactorPrepareSeams`（classify_fn/batch_fn/group_key_fn/grid_peek_fn）绑到真核、补 live grid 缓存与 commit 补丁、登记 catalog 版本、闭合 contour→map 推送，并给 cross-well 提供因子上下文。
