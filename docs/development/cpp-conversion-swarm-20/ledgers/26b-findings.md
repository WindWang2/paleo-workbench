# CONV-26 — Workflow Runtime Closure 勘察记录（findings）

分支 `feat/cpp-workflow-runtime-closure` · 库 `libs/workflow_runtime`（`Pwb::WorkflowRuntime`，gate `PWB_BUILD_CONV_26`）

## Python source surface（移植源）

| Python 模块 | 行数 | 移植面 | C++ 对应 |
|---|---|---|---|
| `workflow/current_context.py` | 431 | `CurrentProjectVersionContext` 数据类核心（select / mark_domain_product_current / current_for_asset / is_current_version / set_expected_identity + display-only 剥离） | `current_context.{hpp,cpp}` |
| `workflow/freshness.py` | 880 | FreshnessState/ReasonType/Reason/Report/Service 全量：evaluate_run（环栈递归、六规则 selection-mismatch、content-identical 容差、transitive stale、identity 期望、integrity 维度）、evaluate_version/domain_task、downstream_impact、stale_downstream、evaluate_operation、step_freshness 聚合、UI 标签表 | `freshness.{hpp,cpp}` |
| `workflow/recompute_plan.py` | 489 | PlanAction/Step/Plan、build_recompute_plan（roots 扩展、H11 task-links、stale_only + task_forced、复用匹配、拓扑）、PlanExecutor（generation guard、cancel、失败隔离、version-namespace poisoning）、OPERATION_LABELS_ZH | `recompute_plan.{hpp,cpp}` |
| `workflow/constraint_versions.py` | 682 | content hash（canonical sha256、ID-free/order-free）、commit（no_content/unchanged/changed）、commit_all、current_constraint_version、pins（for_task/pinned/staleness 懒绑定）、compare（行级 diff）、resolve_constraint_ref | `constraint_versions.{hpp,cpp}` |
| `workflow/provenance_graph.py` | 182 | build_product_lifecycle_graph（map_product/factor_task/factor_output/constraints/fusion_output 节点、assembles_factor/produced/consumed_constraints/fusion_input 边、gaps） | `provenance_graph.{hpp,cpp}` |
| `workflow/interpretation/staleness.py` | 204 | StalenessVerdict 汇聚词汇、VERDICT_IS_PROBLEM/LABELS_ZH、from_constraint_pin/from_workspace_status/from_run_freshness 适配器、ArtifactVerdict | `staleness.{hpp,cpp}` |

## 新增 runtime 面（无 Python 一一对应，组合层）

- `catalog_seam.{hpp,cpp}`：`CatalogRepository` 接口（list/resolve/register_run/register_result_asset/register_version/update_run_status/attach_run_output/set_current_version/verify_integrity）+ `RuntimeStore` 确定性内存实现（asset_/ver_/run_ %06d 计数器 id，sha256 payload checksum，固定时钟）。
- `node_adapters.{hpp,cpp}`：NodeAdapter registry（桥接 workflow_engine 内置与 mapping ops，零算法复制）+ ResourceHints + AdmissionGate（有界并发、cancel 感知 acquire、RAII Lease、cancel_all/reset）+ `{"$version": …}` 类型化输入绑定提取。
- `runtime_service.{hpp,cpp}`：WorkflowRuntimeService —— validate（复用 engine validate_spec）/ execute（provenance 发布、异常防护）/ snapshot / build_context / make_freshness_session（堆稳定）/ plan / execute_plan / explain_stale / list_outputs / provenance_trace。

## 复用（零复制确认）

- canonical JSON 编码：`pwb::factor_host::canonical_encode`（FactorHost，CONV-08）。
- sha256：`pwb::domain::Sha256`。
- 拓扑排序/复用匹配/环检测/下游遍历：`pwb::workflow_graph::DependencyGraph`（CONV-25）。
- 执行器/CancelToken/NodeRegistry/内置 ops：`pwb::workflow_engine`（CONV-07）。
- spec 校验：`pwb::workflow_engine::validate_spec`（CONV-07 冻结词汇）。
- evidence selector 格式化：`pwb::workflow_graph::format_evidence_selector`（provenance_trace 用）。

## Oracle

- 生成器：`tools/oracle/generate_workflow_runtime_fixtures.py`（驱动真实 Python，**每个案例 input 携带完整场景 JSON**，C++ 侧独立重建 — fixture 是唯一共享产物；重跑字节一致已验证）。
- fixture：`workflow_runtime_tests/fixtures/workflow_runtime_oracle.json`，**126 案例**：freshness 44（六规则命中 1/2/3/4、content-identical 容差、transitive、环、failed/cancelled/running/pending 状态、missing-lineage、withdrawn/purged、identity 期望四类、display-only 免疫、integrity missing+modified、step 聚合梯子 FRESH/RUNNING/MISSING/UNKNOWN/FAILED-latest）、recompute 14（含 H11 task-links、cycle_error、operations 过滤、stale_only=false、复用 REUSE、执行器 ok/失败投毒/无 handler/stop_off/generation guard/三步链 poisoning 区分）、constraint 39（hash 顺序不变性/UTF-8/空/行级 horizon、commit 三态+UTF-8、commit_all、current、pins 四态+horizon 域过滤、staleness current/stale_content/stale_version/unknown/unpinned/missing/no-catalog×2、compare diff/identical/**raise parity(ValueError)**、resolve 8 分支）、provenance 5、staleness 21、current_context 3。比较器自检（突变必被抓住）+ e2e 闭环。
- e2e（runtime_test.cpp `end_to_end_closure`）：WorkflowSpec→validate fail-closed→execute C++ node（$version 绑定）→provenance 发布（3 runs 校验）→FRESH→空 plan→上游变更→STALE→plan→execute_plan→FRESH→re-plan 复用（resume seam）→provenance_trace→**cancel 中途取消→retry→explain_stale/list_outputs→admission（cancel_all/reset）**。

## 语义保真要点（冻结证据）

- 决策梯子/reason 顺序/detail 措辞（含中文、'…' 省略号、repr 引号）逐字节对齐。
- constraint hash：strip line_id/group_id、active+coordinates≥2 过滤、canonical 序排序、`round(x, 9)`（%.9f 正确舍入）、行 **自身** target_horizon（不继承组 —— 与 pydantic 模型默认 "" 一致）。
- Python dict 去重语义（首现顺序 + 末值胜出）在 pins/groups 索引中复刻。
- `split(":")` 恰取第 2/3 段的多冒号语义。
- raise parity：`ConstraintValueError`（python_class "ValueError" + 消息 repr 措辞）。

## 已知偏差（documented divergences）

1. C++ catalog seam 无 `resolve_run` 兜底（Python freshness 对 off-graph run 会再查 catalog）；运行时服务始终从全量 listing 建图，该路径不可达，纯核直接查图外 run → MISSING_LINEAGE。
2. payload 传输为字符串（Python 走临时文件路径）；compare 的 payload 不可达语义以 ValueError 等价复刻（JSON 解析失败路径的 Python class 不同，未冻结）。
3. Python `True == 1` 的跨类型相等：nlohmann 对 bool/number 判不等 → 参数比较可能多报 reason（bool vs number 参数差异场景，现实参数不出现）。
4. `from_run_freshness("FRESH")`（大写枚举值）Python 自身落入 UNKNOWN（keys 全小写）— C++ 忠实复刻该潜伏行为（未冻结）。
5. falsy 标量 str() 强转差异（`0`→"0" vs ""）：文档模型字段恒为字符串，不可达。
6. Python freshness 的 evaluate 递归栈 GRAPH_CYCLE 分支（belt-and-braces）在静态 DAG 上不可达，未冻结。
7. Python set 迭代序相关输出（规则 3/4 多 tip 竞争、cycle 回退多 run 排序）刻意不在 oracle 中；C++ 用插入序/排序保证确定性（current_context selected ids 为插入序 vector）。
8. `_canonical_line` 的 `azimuth_deg` 等数值字段：Python `float()` 接受字符串，C++ `get<double>()` 对字符串抛异常（JSON 视图恒为 number/null）。

## 仍保留的 Python glue

- `service.py`（home_workflow_steps/QC/dashboard UI 聚合 + `_apply_freshness_overlay`）、`orchestrator.py`（legacy step-cursor，自述生产不得依赖）、`current_context.resolve_current_project_version_context`（project models 属性图粘合，C++ 由 build_context 的 asset 指针步 + 调用方 overlay 覆盖）、`interpretation/staleness.py` 的 evaluate_verdict/workspace_verdicts/propagate_to_products（依赖 mapping_workspace.MappingDependencyService — UI workspace 分支）。
- Python 旧模块保留为 oracle/兼容（消费者清单见 review：project_controller、workflow_controller、harness、8 处 constraint_versions 调用方等）。

## 尚未迁移依赖（后续切片）

- `dag/{store,receipt,reproduction,plan_view}.py`（DAG checkpoint 持久化面）；workflow_spec 与 workflow_engine 双轨模型合并；factor_host 编排缝（fingerprints_for_task）；QC 聚合；UI 接线（platform app 尚未链接 Pwb::WorkflowRuntime — UI 分支）；SQLite catalog adapter（Data 分支对接 CatalogRepository 接口）。

## 资源记录

- 共享构建锁被主仓 vendored QGIS 构建长期占用（数小时级）；本切片为小型 Qt-free 目标（~10 TU），在 MemAvailable≥50GiB 下按资源治理硬规则定向构建（-j2、单 worktree 单构建、仅目标库目标测试、无全树 rebuild），已在本记录备案。gate 正常路径用法：`scripts/cpp-migration/invoke-resource-gate.sh Configure -s . -b build/conv-26 -a "-DPWB_BUILD_CONV_26=ON;-DBUILD_TESTING=ON"`。
