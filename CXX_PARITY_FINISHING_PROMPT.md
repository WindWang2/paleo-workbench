# C++ 化收尾任务 — 交接 Prompt

> 目标：完成 Paleo Workbench 从 Python 到原生 C++ 的 100% 功能对等转换，产出**可编译、可运行**的原生产品。本文件是当前会话对全部剩余工作的精确盘点，可直接作为任务说明书交给开发 agent 执行。

---

## 0. 环境与基线

| 项 | 值 |
|---|---|
| 仓库 | `/home/kevin/project/paleo-workbench` |
| 构建目录 | `build/native-product` |
| 可执行文件 | `build/native-product/apps/paleo_workbench_platform/pwb-platform` |
| CMake | `/home/kevin/tools/cmake-4.1.2-linux-x86_64/bin/cmake` |
| Ninja | `/home/kevin/pwb-sdks/root/usr/bin/ninja` |
| Preset | `linux-native-product` |
| QGIS vendor SDK | `native/qgis_render_bridge/build/qgis-vendor/output`（lib/ 下有完整 .so 闭包；`data/` 是 GDAL_DATA） |
| Python oracle | `paleo_workbench/`（只读参照，678 个 .py） |
| 机器 | ~40 核 / ~40G RAM |

**构建与自检命令**：

```bash
cd /home/kevin/project/paleo-workbench
/home/kevin/tools/cmake-4.1.2-linux-x86_64/bin/cmake --preset linux-native-product   # 仅改 CMake 时需要
/home/kevin/pwb-sdks/root/usr/bin/ninja -C build/native-product -j16 pwb-platform
# 自检（需要 vendor 库路径 + GDAL_DATA，否则 libodbc/GDAL 警告）
cd build/native-product/apps/paleo_workbench_platform
LD_LIBRARY_PATH=$PWD/../../../native/qgis_render_bridge/build/qgis-vendor/output/lib \
GDAL_DATA=$PWD/../../../native/qgis_render_bridge/build/qgis-vendor/output/data \
QT_QPA_PLATFORM=offscreen ./pwb-platform --headless-self-check
```

基线：上一轮 `-j16` 全量构建 831 目标全绿，`--headless-self-check` **13/13 通过**。当前工作树有未编译的新代码（见 §2）。

---

## 1. 硬性约束（违反即返工）

1. **单一编目轨**：所有因子制备/编图/产品装配/预测写入同一个 `workflow_runtime::CatalogRepository`（`closure_mapping::factor_catalog(window)` 暴露的共享实例；SQLite 优先，JSON 回退）。**禁止**建第二个目录权威。
2. **诚实失败**：缺输入/缺目录/缺服务必须显式报错，禁止伪造网格、置信度层、预测结果或证据。失败 run 必须以 failed 状态留在目录里，不得静默丢弃。
3. **Qt-free 域逻辑在 libs/**，宿主/UI 编排在 `apps/`。stale/missing/unknown 状态必须可见保留，不得偷偷换成 current 数据。
4. **资源纪律**：主构建 `-j10`~`-j20`（当前 `-j16`）；如派子代理，**子代理只改隔离文件、禁止跑构建/测试**；禁止并行 Ninja/CMake。
5. `workspace_install.cpp` 之类的组合根接线模式沿用现有风格（window property 暴露权威指针、`status()` 进 statusBar、异常经 `dispatch_stage_action` 的 try/catch 转成状态消息）。
6. 仓库规范见 `CLAUDE.md`：Karpathy 准则——先想后写、最小实现、外科手术式修改、可验证成功标准。

---

## 2. 已完成（不要重做，但要编译验证）

以下文件**已写入工作树且已注册进各自 CMakeLists**，多数已单独编译通过（.o 存在）：

| 文件 | 状态 | 内容 |
|---|---|---|
| `libs/cartography/src/cartographic_qa.cpp` + `include/.../cartographic_qa.hpp` | **已编译** | §14 制图 QA 15 规则移植；`collect_cartographic_qa_issues` 签名直接兼容 `workflow_runtime::CartographicQaDelegate` |
| `libs/workflow_interpretation/src/dependencies.cpp` + `.hpp` | **已编译** | `MappingDependencyService.evaluate` 移植：`evaluate_workspace_freshness`/`stale_summary_json`/`stale_entries`/`stale_headline`；artifact key 词表 `phase1_draft:`/`factor:`/`integrated:`/`mapproduct:` |
| `libs/mapping_kernel/src/{directional_trend,scipy_grid}.cpp` | **已编译** | cubic/linear/nearest/rbf 插值核 + 方向趋势 |
| `libs/closure_workflow/src/catalog_closure_adapter.cpp` + `.hpp` | **已编译** | 深层 `CatalogServiceCore` ↔ `workflow_runtime::CatalogRepository` 桥（含 `mutable_core()` 访问器） |
| `libs/closure_science/src/mock_facies.cpp` + `providers.hpp`/`model_seed.{hpp,cpp}` 声明 | **已注册，未编译** | `make_mock_well_facies_provider`/`make_mock_seismic_facies_provider` + `ensure_mock_facies_models`（`mock-well-facies-v1`/`mock-seismic-facies-v1`，demo 标记，幂等） |
| `libs/ui_composite/src/{constraints_sync,factor_group_layers}.cpp` + 头文件 | **已注册，未编译** | `sync_constraint_geometry`（§11 约束几何回填）+ `factor_group_layers`/`classify_prediction_task`/`confidence_overlay_layers`/`boundary_features_from_polygons`/`integrated_boundary_action_helpers` |
| `apps/paleo_workbench_platform/workflow_install.cpp` | **部分** | 组合根骨架已编译（WorkflowController 全 seam、页面扇出、SQLite 优先目录轨）；**本轮刚补了 28 个 includes（未编译）；stage-action handler 主体未写** |
| `CMakeLists.txt` 修正 | 已生效 | `PWB_WITH_CATALOG_CLOSURE` 顺序 bug 已修（apps/ 在 libs/ui_controllers 之前处理导致守卫永假）；`PWB_WITH_CLOSURE_WORKFLOW`/`PWB_WITH_CLOSURE_SCIENCE`/`PWB_WITH_FACTOR_KERNEL`/`PWB_WITH_CARTOGRAPHY` 均已在产品编译行生效 |

---

## 3. 剩余工作（按依赖序）

### 3.1 stage-action 编排层（核心缺口，`workflow_install.cpp`）

Python oracle：`paleo_workbench/ui/workstation/stage_actions.py` L240–2080（19 个 handler 全语义已核读）。dispatch 表在 `libs/ui_workstation/src/stage_actions.cpp` L9-38，22 个 action id → 19 个 key，horizon 门槛表 L53-75。

现有 `dispatch_stage_action_`（workflow_install.cpp ~L1132）只接了 4 个 handler（`stage_save`/`open_factor_workbench`/`run_qa`/`assemble_map_product`）。**需补齐以下 handler 并注册进 handlers map**：

| dispatch key | Python 锚点 | C++ 落点（签名已核实） |
|---|---|---|
| `load_initial_facies` | L366 | paleomap_documents → RAW 叠加；`_default_blank_facies_features`（workarea.boundary ring ≥3）；`edit_controller->create_layer(name,"polygon",template,role)` + `import_layer_features` + `set_layer_style`；无候选时淡色空白相 `#1a64748b` |
| `run_well_facies_mock`/`run_seismic_facies_mock` | L430-549 | `_run_mock_prediction(kind)`：`ensure_mock_facies_models` → `_mock_run_parameters`（well=wells 表/seismic=`_mock_areal_extent` 三级回退：工区边界→井位 bbox+10%→地震工区角点）→ `resolve_model_inputs`（C++ 等价，注意 Python `resolve_prediction_inputs` 未移植——用 `resolve_model_inputs(document, resources, model_version_id)`）→ `start_inference` → `execute_run`（ProviderRegistry 注册两个 mock provider）→ `_register_mock_intermediates`（well=`well_detail` JSON 中间文件 / seismic=`mock_grid` npz，`DataStage::INTERMEDIATE`，`register_result_asset`）→ `materialize_prediction_task` → `link_run_to_domain_task` → `prediction_tasks.append` → 自动叠加（well：先 `_drop_stale_well_points_layer` 删 `POINTS_LAYER_TASK_ID` 旧层再 `add_well_prediction_overlay`；seismic：`add_seismic_prediction_overlay`）→ 状态消息含 mock/层位明示。**catalog 空 = 直接报「数据编目不可用」** |
| `add_well_prediction_overlay` | L735 | `_overlay_polygon_predictions(prefer="well")` + `_overlay_well_prediction_points`：`mapping::spatial_point_features`/`point_features`，role=`layer_role::kWellFaciesPrediction`，`factor_task_id=POINTS_LAYER_TASK_ID`；幂等（已有则跳过计数） |
| `add_seismic_prediction_overlay` | L761 | `_overlay_polygon_predictions(prefer="seismic")`：`classify_prediction_task`（已在 factor_group_layers）+ `extract_polygon_features`；role=`kSeismicFaciesPrediction` |
| `well_prediction_point_to_surface` | L765 | `point_to_surface_features(points, extent, grid_n=80, clip_ring, crs)`；extent=`extent_from_workarea_boundary` 优先否则 `extent_from_points`；role=`kWellFaciesPrediction` + `SURFACE_LAYER_TASK_ID`；先删旧同 task 层 |
| `toggle_prediction_confidence` | L960 | 幂等开关：有 `kWellFaciesConfidence`/`kSeismicFaciesConfidence` 层→移除；否则 `confidence_overlay_layers(project, task)` descriptor 建层 |
| `create_facies_draft` | L1006 | RAW→DERIVED：INITIAL_FACIES_SOURCE 层要素拷贝（或 paleomap_documents 首个含 facies_polygons 文档，或空白相）→ INITIAL_FACIES_DRAFT 层 + `state.set_maturity("phase1_draft:<lid>","draft")` + `set_active_layer` + `layer_manager->select_layer` + 分类样式 |
| `overlay_factor_results` | L1077 | `factor_group_layers(document, task, grid)`（已移植）：六子层 descriptor；raster 子层走 `group_controller->register_layer`（descriptor-only 登记）；vector 子层 `_create_role_layer`；`peek_live_factor_grid` 等价物 = `factor_production::LiveFactorGridStore`（`closure_mapping::factor_grid_store(window)` 或同类访问器——查 `closure_mapping_install.hpp`）；空 vector 子层不建（QC 子层报原因）；幂等按 role+task 判 |
| `commit_constraints` | L1233 | `workflow_runtime::commit_all_constraints(*catalog, root, "workstation")` → reports 分类计数（committed/unchanged/no_content）→ 状态消息；catalog 空 = 「目录服务不可用」 |
| `select_evidence` | L1316 | `workflow_graph::available_evidence(document, &workspace_view, constraint_resolver)` → `QInputDialog::getItem`（status_tag 后缀：resolved/floating 当前内容/unpinned/stale/missing/unknown）→ 双写：legacy `state.compilation_input_set[label]=selector` + 结构化 `active_input_set`/`create_input_set` shell + `persist_input_set`；末项「〔移除证据〕…」→ `_remove_evidence`（legacy 按值删 + 结构化按 selector 删 + persist）→ `write_mapping_workspace(root, state)` + `save` |
| `freeze_evidence_set` | L1280 | `active_input_set` 空→提示；`freeze_input_set(input_set, root, ctx)`（ctx.catalog=`CatalogResolver` 包装 `catalog->resolve_version`；ctx.workspace=WorkspaceView{membership,layers_with_role}；constraint_resolver=`resolve_constraint_ref` 等价物——查 `workflow_runtime/provenance.hpp` 或 constraint_versions）→ `persist_input_set(root, frozen, true)` → 持久化 |
| `create_integrated_draft` | L1391 | INTEGRATED_FACIES 已存在→提示；`compilation_input_set` 空→提示；INITIAL_FACIES_DRAFT 要素拷贝为底稿→建层 + `set_maturity("integrated:<lid>","draft")` + `_register_integrated_interpretation`（`create_integrated_interpretation(document,name,layer_id,input_set_id,fusion_version_id="",class_schema=[],created_by="workstation")`；`find_by_layer` 幂等） |
| `create_integrated_boundary` | L1487 | INTEGRATED_BOUNDARY 已存在→提示；源=INTEGRATED_FACIES 层否则 INITIAL_FACIES_DRAFT 层否则工程侧 `integrated_boundary_action_helpers` descriptor；`boundary_features_from_polygons(features, source_layer_id)`→建 line 层 + set_maturity + select |
| `run_fusion` | L1549 | `active_input_set` 未冻结→「请先冻结」；`evidence_view(root, &workspace_json)` 无 `factor:` 条目→提示；`run_integrated_fusion(root, evidence, catalog, seams, ..., register_output=catalog!=nullptr)`；descriptor-only 登记 likelihood/confidence/variance（`descriptor["layer_id"]` 幂等，`register_layer(layer_id, role, source_version_id=artifact_version_id or fusion_version_id)`）；classification_features 且无 INTEGRATED_FACIES→建融合初稿 + `set_maturity` + `_register_integrated_interpretation(base_kind="fusion")` + `record_interpretation_revision(base_kind="fusion")`；`_track_latest_fusion_version`（`interpretations_for_document` + `upsert_interpretation` 写 latest_fusion_version_id）；状态消息含 registered/class_counts/confidence_coverage/draft_note |
| `run_qa` | L1700 | **重写现有 `run_map_qa_`**：Python 语义 = ① INTEGRATED_FACIES+INTEGRATED_BOUNDARY 层 `topology().validate`（或 `gate_topology_issues`/`run_topology_checks`——查 composite_controller.hpp L383-386），异常→error issue 不跳过 ② `evaluate_workspace_freshness` 的 stale_entries→issue ③ `cartographic_issues(project, inputs{stale_summary=stale_summary_json(...)}, &cartography::collect_cartographic_qa_issues)` delegate 调用 ④ 全部 issue → `project::QualityReport` append（rules=["topology","staleness",*carto_rules]，status=issues/passed）；现有 `run_map_qc` 调用保留还是替换需对照 Python 确认（Python stage action 不调 run_map_qc） |
| `commit_interpretation` | L1772 | INTEGRATED_FACIES 首层→`find_by_layer`→layer Json（live 层序列化或 user_vector_layers 回退，`layer_payload` 读 `{features:[{feature_id|id,geometry,attributes|properties}]}` 形状）→`commit_integrated_interpretation(root, interpretation, layer_json, catalog, "workstation","",evidence_refs)`；catalog 空→「目录服务不可用」；ValueError→「提交被拒绝」 |
| `stage_save` | L1909 | **扩展现有 handler**：`flush_edit_sessions` 等价物（查 CompositeDocument/EditController 公共面）+ `_sync_constraint_geometry`（对每个 constraint group line 的 `properties["layer_id"]` 调 `ui_composite::sync_constraint_geometry(document, layer_id)`，lines_synced 计数）+ `_record_interpretation_revisions`（INITIAL_FACIES_DRAFT→phase1_draft、INTEGRATED_FACIES→integrated_facies、INTEGRATED_BOUNDARY→integrated_boundary 各调 `record_interpretation_revision`，evidence_refs=`evidence_view` 值集）+ `save_documents(window)` + workspace state 写回 |

**通用辅助（Python `_create_role_layer` L244-295 等价物）**：`edit_controller->create_layer(name,kind,template,role)` → `group_controller->register_layer(layer.id, role, factor_task_id, constraint_kind, source_version_id)` → `apply_capture_spec` 等价物（若无则跳过）→ `import_layer_features`（`VectorFeature{feature_id:"f"+hex10, geometry, attributes}`）→ 组合同步（`rebuild_composition` callback 或 `sync_to_project` 路径——查 CompositeDocument 公共面 L94-98）。`_stage_role_layer(role)` = `state.layers_with_role(role)` 首个 `edit_controller->layer(lid)!=nullptr` 者。`_apply_categorized_facies_style` = `ui_workstation::facies_category_color`（stage_actions.hpp L55，known_fills 可空）+ `set_layer_style`，失败仅记日志不阻断。

**workspace/catalog 访问器**（已确认存在）：
- `runtime_catalog()` → `workflow_runtime::CatalogRepository*`（binding 私有方法，L485）
- workspace 权威：`window->property("pwb.layer_workspace")`（`MappingWorkspaceState*`，main_window.cpp:3621 已 setProperty）+ `pwb.layer_groups`（`LayerGroupController*`）；工程切换时 notify 已更新、关闭时已清空
- `closure_mapping::document_bank(window)`/`save_documents(window,&err)`（closure_mapping_install.hpp L93-99）
- `shell_->composite()->edit_controller`（CompositeDocument 公共成员，composite_document.hpp L85）
- `shell_->composite()->layer_manager`（L70，`select_layer`）
- 持久化统一走 `workspace::write_mapping_workspace(root, state)` + `store()->save_document()`

### 3.2 shelf 三处占位替换（`install_factor_shelf_`，~L1254-1272）

- `factor_overlay_requested(overlay_id)` → 调 `overlay_factor_results` handler（或按 overlay_id 路由到对应子层构建）
- `create_factor_map_requested` → **需要 §3.3 的 FactorMapService**
- `fault_interpretation_requested` → **需要 §3.4 的 fault lifecycle**

### 3.3 FactorMapServiceFn 生产实现（create_factor_map）

Python oracle：`paleo_workbench/mapping/geological_mapping.py` `create_factor_map` + `paleo_workbench/mapping/factor_extract.py` + `factor_task.py` + `task_build.py`。语义链：井因子提取 → 插值（`apply_interpolation`，constrained_idw/scipy 核已在）→ FactorMapTask 记录 → live grid 注册（LiveFactorGridStore）→ catalog provenance → `build_factor_map_document` → 约束诊断 + staleness anchors。C++ 侧 `factor_prepare_production.cpp` 已有 records 组装路径可复用；seam 定义查 `closure_workflow/host_bindings.hpp` 的 `FactorMapServiceFn`。

### 3.4 断层解释生命周期（fault_lifecycle）

Python oracle：`paleo_workbench/workflow/fault_lifecycle.py`（262 行）+ `correlation_artifact.py`。语义链：map-plane polylines（break/fault 约束线）→ `FaultTrace` → 草稿保存 = 不可变派生 artifact（科学 payload + canonical JSON SHA-256 指纹，`factor_host/canonical_json.hpp` 的 `canonical_encode`+`stable_sha256` 已字节级等价）→ catalog 注册 `fault_interpretation` run + DERIVED 版本 → 失败补偿（删本地 artifact + run 标 failed）→ 工程存 `FaultInterpretationRef` → 重开解析 artifact 恢复干净草稿。C++ 件：`project/artifacts.hpp` 路径助手、`workflow_runtime` 的 run/version seam、`resolve_context` 已知 fault 输入。落点建议 `libs/workflow_interpretation/src/fault_lifecycle.cpp`（Qt-free），shelf handler 只做编排。

### 3.5 QA delegate + stale_summary 接线

- `run_qa` handler 内：`workflow_runtime::CartographicQaInputs{snapshot=?, capability=?, stale_summary=stale_summary_json(evaluate_workspace_freshness(root, catalog, workspace_view)), catalog=catalog}` + delegate `&cartography::collect_cartographic_qa_issues` → `cartographic_issues(project, inputs, delegate)`。snapshot/capability 的具体构造查 `map_qa_rules.cpp` 的 CartographicQaInputs 消费点与 Python `cartographic_issues` 调用形状。
- `evaluate_workspace_freshness` 需要 `WorkspaceView`（membership→source_version_id）——用 `pwb.layer_workspace` 的 `MappingWorkspaceState` 构造。

---

## 4. 验收标准（全部满足才算完）

1. `ninja -C build/native-product -j16 pwb-platform` **全绿**（含 mock_facies/constraints_sync/factor_group_layers 三个未编译 TU + 新编排代码）
2. `--headless-self-check` **13/13**（环境变量按 §0）
3. `dispatch_stage_action` 对 19 个 key 全部返回非「未接入」状态（可写最小冒烟：无工程时各 handler 应报「请先打开工程」类诚实错误而非崩溃）
4. mock 预测：无工程/无 catalog/无井 → 显式报错；有输入 → DataRun(failed→completed 可见) + PredictionTask + overlay 层
5. `stage_save` 后工程 JSON 含 constraint 几何回填 + interpretation_revisions + workspace state
6. `run_qa` 产出含 cartographic 规则的 QualityReport（rules 列出实际跑过的规则 id）
7. `commit_constraints`/`commit_interpretation`/`assemble_map_product`/`run_fusion` 写同一 catalog 轨，版本链可查
8. shelf 三个入口不再显示「接入中」占位文案
9. 冻结证据集 → 证据 pin 写回 selector；融合 → descriptor 登记 + 初稿创建 + interpretation 登记 + 修订链
10. 无 child-agent 构建竞争；最终 `git status` 改动清单干净可审

---

## 5. 已知非阻塞项（如实记录，不算缺口）

- vendor GDAL 未编 `gdal_PNG.so` 插件：render_frame/layout_export 走 Qt 自带 PNG 不受影响；GDAL 栅格导出是 vendor SDK 的诚实缺口
- 标量（raster）子层为 descriptor-only 登记——画布标量发布路径不在本动作内，与 Python 语义一致
- `Agent 产品入口`/`executor 绑定验证`、`约束等值线后处理尾部`、`样条核` 属于上一轮盘点遗留项——若时间允许核对；release 验收（同 SHA 双平台 + 安装包 + 真实 GL）超出本收尾范围
