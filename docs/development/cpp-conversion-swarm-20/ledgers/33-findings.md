# CONV-33 findings — workflow 顶层编排面（orchestrator/recipe/versioning/service + QC 面）

Branch `feat/cpp-workflow-orchestration`（worktree `../worktrees/cpp-workflow-orchestration`，base origin/main dff8087a = PR #1378（CONV-32）+ PR #1398（CONV-31b）合并后）。
轮0 侦察 = 5 路并行只读：R1 orchestrator/service/current_context 深读 / R2 recipe+versioning+constraint_versions+freshness 深读 / R3 recompute/dependency/provenance/qc + 其余 17 文件一行判定 / R4 C++ 可消费面审计 / R5 消费者+测试+oracle 资产。
cmake 本机不可用（沿 31/31b/32 披露）：验证边界 = g++ -std=c++20 直连 + 真实 Python oracle 冻结 replay。CMakeLists 仍按仓库惯例更新供 CI。

## A. 终态三列（Python source → 语义要点 → C++ 目标）

### A1. 本切片移植（新增 C++，oracle 冻结 + replay）

| Python | 语义要点 | C++ 目标（初判，契约冻结轮裁决） |
|---|---|---|
| orchestrator.py (115) | legacy headless 步骤游标（docstring 自认非权威；权威 = service.home_workflow_steps，audit #847-2）。STEP_NAMES 6 步中文 (L42)、WorkflowStepContext 7 字段 (L17)、next_step 推进/拒绝 message 逐字 (L69/92/98/107/113)、is_valid 陷阱（warning/running 也算 valid，L65）、step_payload 形参接受但忽略 (L81) | libs/workflow_engine 新 TU `orchestrator.{hpp,cpp}`（随 service 一起，纯内存零持久化，边际成本近零） |
| service.py (355) | 首页步骤状态推断权威：STEP_ORDER/REQUIRED_RESOURCE_TYPES (L19-20)、create_compilation_run (L32)、infer_workflow_step_status = evidence→freshness overlay 两层 (L92/L149)、home_workflow_steps 就地回写 active_run.workflow_steps + persisted failed/warning 弱覆盖保留 (L232-242)、build_affected_products_plan (L247)、downstream_impact_for_version (L263)、dashboard_state (L312)；两处 broad except 降级回退 evidence-only (L136-146/L197-206，audit #847-3)；状态字符串（pending/running/complete/warning/failed/stale）是跨模块隐式契约无 enum | workflow_engine 新 TU（freshness 依赖已在 workflow_runtime 可直连接线；qc/recompute_plan 为函数级 lazy 依赖需本切片保证可用） |
| recipe.py (326) | 可移植配方 `*.paleo-workflow.json`：save/load 双端安全门（禁键表 L31/SQL/代码/绝对路径正则含 Windows 盘符+UNC+`$` 前缀豁免 L36/L98）、fail-closed migrate (L114)、原子写 `.tmp-recipe-`+os.replace (L168)、`json.dump(ensure_ascii=False, indent=1)` 字节级、后缀强改 `.json`→`.paleo-workflow.json` (L160)、clone/diff/inspect、recipe_from_spec (L196)/recipe_from_run (L213)；`time.time()` 直灌 created_at 无 seam (L208/247/257) | workflow_engine 新 TU `recipe.{hpp,cpp}`（唯二仓内依赖 workflow_spec model+validation 已字节级对齐；Clock seam 替 time.time，store.hpp 先例） |
| versioning.py (237) | 图件专家定稿（ISS-DOM-04）：build_snapshot（`json.dumps(sort_keys=True, ensure_ascii=False, default=str)` sha256 截 16 hex 指纹，L31-32）、finalize_map_version 六道门（中文消息逐字 L134-148）、同层位旧 final 置 superseded、ContourDraft→final / 编译 run→export_ready 联动、active_final_snapshot (L208)、version_set_summary (L229)；catalog register_finalize_run best-effort 吞异常 (L190-201) | **前置 = libs/project 补 VersionSet/VersionSnapshot/ContourDraft/compilation_runs 模型**（document.hpp 现无）；catalog 锚点 = version_promote.hpp 冻结形状 + repository 事务族 + service_core.save(dirty) |
| qc.py (556) | QC 检查面：BASIC_QC_RULES 6 规则 (L17)、make_issue (L27)/spatial_issues (L278)/issue_layer_geojson (L289)、run_basic_qc (L338)（报告按 linked_map_document_id 稳定 id upsert + 活动 run 绑定 + catalog register_qc_run 临时文件 OUTPUT 溯源 H3/H14）、run_map_qc (L475)（BASIC+EXTENDED 合并）、centroid 三级兜底链 (L60-103) | workflow_runtime 新 TU `qc.{hpp,cpp}`（spatial_issues 谓词已在 ui_review 手工对应，收编归一；register_qc_run 的 C++ 等价面需补） |
| map_qa_rules.py (478) | M12 可定位扩展 QA：EXTENDED_QC_RULES（CRS 纪律 D5、渲染/分类一致、范围越界、融合置信度） | 与 qc.py 同面同 TU |

### A2. 已移植（此前切片；本切片 oracle 对拍核对即可）

| Python | 证据 |
|---|---|
| freshness.py (880) | workflow_runtime/freshness.hpp（全评估 API + FRESHNESS_UI_LABELS 中文标签 + WORKFLOW_STATUS_FOR_FRESHNESS；模块级 `_GRAPH_CACHE` id() LRU 为宿主侧策略不移植，头 L18 已声明） |
| constraint_versions.py (682) | workflow_runtime/constraint_versions.hpp 全 API（pins/staleness/compare/resolve）；对拍重点 = 紧凑 JSON sha256（separators=(",",":")+sort_keys，L141-144）、坐标 round(float,9)（L101）、detail 含 `…` 省略号逐字 |
| dependency_graph.py (391) | workflow_graph/graph.hpp（CONV-25）+ workflow_runtime/catalog_seam.hpp |
| recompute_plan.py (489) | workflow_runtime/recompute_plan.hpp（project 走 Json seam；对 freshness 私有 `_selection_mismatch` 的越界调用已在 C++ 转正） |
| provenance_graph.py (182) | workflow_runtime/provenance_graph.hpp |
| dag/ 子包 5 文件 | workflow_engine store/reproduction/receipt/plan_view/run_engine（CONV-32，PR #1378） |
| constraint_capabilities + interpretation/ 7 文件 | workflow_interpretation（CONV-32） |

### A3. 部分移植 / 留待消费方切片

| Python | 现状 | 剩余 |
|---|---|---|
| current_context.py (431) | CurrentProjectVersionContext 数据面已移植（workflow_runtime/current_context.hpp） | resolve_current_project_version_context 五段 project 注入 (L122) + _deselect_superseded_domain_tips (L383) 重度 getattr 反射 + catalog.runtime 全局单例；留待 project/catalog 强类型消费方切片（头文件已标注） |
| map_product.py (1078) | catalog OUTPUT 编排面（P1-D，fail-closed 拒绝合成输入）；provenance_graph.hpp 已引用其记录形状 | 主体归 catalog 消费方切片，本切片不收（契约冻结轮可再裁） |
| integrated_compilation.py (683) | 证据集→FusionModel→融合→角色摘要（§12 Stage-3） | 依赖 factor_fusion/science_service 接线成熟度，归科学服务消费方切片 |

### A4. 归属其他里程碑（点名不收）

factor_interpolation (1488) / interpolation_evaluation (825) / factor_fusion (790) / constrained_idw_adapter (721) / interpolation_plan (676) / factor_grid_result (673) / interpolation_fingerprint (667) / contour_draft (473) → mapping_kernel / factor_host / factor_fusion 计算内核；factor_prepare_scheduler (769) → factor_host+job_runtime 调度切片；td_calibration_lifecycle (437) → well_science。其余（curve/correlation/fault/stratigraphy/well_table/well_science/crs_policy/sample_normalization/factor_map/factor_units 等）此前切片已点名归宿，不重复。

## B. C++ 依赖就绪面（31b-decisions D7 声明兑现核验）

- **workflow_engine**（CONV-32）：RunEngine create/run/resume/rerun/cancel + WorkflowRunStore 原子 checkpoint + find_reusable_node + build_receipt 26 字段 + plan_view 七态。
- **workflow_spec**（CONV-06）：WorkflowSpec/NodeRun/WorkflowRun DTO + canonical_hash + validation（slot/参数门）。
- **workflow_graph / workflow_runtime**（CONV-25/26B）：DependencyGraph（topological/find_reuse_run）+ freshness/recompute_plan/current_context/constraint_versions/provenance_graph + catalog_seam + runtime_service。
- **catalog**（CONV-31/31b）：service_core（open 五健康矩阵 / save 全量+DirtySet / #411+#1220 双层 CAS / batch）+ repository 事务族（promote/working-copy/bundle/model）+ working_copy 状态机 + v11_bundle 两阶段 + model_registry + version_promote 冻结形状。
- **project**：document.hpp ProjectDocument 已移植；**缺口 = VersionSet/VersionSnapshot/ContourDraft/compilation_runs 模型**（versioning.py 前置）。

## C. oracle / 测试资产

- **需新写生成器**（tools/oracle/）：orchestrator（test_workflow_orchestrator 3 例 + test_issue847 拒绝矩阵 10 例）、service（test_workflow_service 8 例 + issue847 overlay）、recipe（test_workflow_recipe 12 例，含密钥/绝对路径/SQL/损坏 JSON 安全门）、versioning（test_versioning 5 例，需冻结 QualityReport 输入）、qc+map_qa_rules（最大新面，无既有生成器）。
- **已有可直接对拍**：workflow_graph_oracle.json 131 例；workflow_runtime_oracle.json 126 例（freshness 44 / constraint 39 / staleness 21 / recompute 14 / provenance 5 / current_context 3）；engine 族（CONV-32）598 checks。
- **不冻结**：test_workflow_controller_api.py（qtbot GUI 线程语义）、test_workflow_integrity.py（CI YAML 元守卫，与 workflow 包无关，同名误导）。

## D. CMake 接线（契约冻结轮事项）

- 现无 `PWB_BUILD_CONV_33` 门；`PWB_BUILD_CONV_26B` / `PWB_BUILD_CONV_32` 未进任何 preset 与 cmake/PwbFeatures.cmake（grep 0）——本切片自带门，并考虑补 preset 挂载。
- 测试注册照抄 workflow_interpretation 的 argv[1] fixture 模式（`set(<LIB>_FIXTURE_DIR ...)` + `add_test(NAME <lib>.<case> COMMAND <exe> ${FIXTURE_DIR}/<oracle>.json)`）。
- 库落点初判：orchestrator/recipe/service → libs/workflow_engine 增量 TU；qc/map_qa_rules → libs/workflow_runtime；versioning 落点随 project 模型前置一并裁决。

## E. 风险清单（实现轮盯防）

1. service.py home_workflow_steps 就地 mutation 副作用（持久化进度回写）+ broad except 降级语义 → C++ 显式所有权与异常模型抉择。
2. 中文消息逐字：versioning 六道门（L134-148，全角标点）、orchestrator 推进/拒绝 message、service/dashboard 中文标签（OPERATION_LABELS_ZH/FRESHNESS_UI_LABELS 渗入）。
3. JSON 字节格式：recipe indent=1 ensure_ascii=False；versioning 指纹 sort_keys + default=str 的 Python float repr；constraint_versions 紧凑分隔符 + round(9)（已移植，对拍确认）。
4. recipe `time.time()` 无 seam → Clock 注入（store.hpp 先例）；versioning 走 project.models `_now_iso()`。
5. catalog.runtime 全局单例（current_context resolve 面）→ 组合根注入，AppContext 先例；本切片 A3 不触。
