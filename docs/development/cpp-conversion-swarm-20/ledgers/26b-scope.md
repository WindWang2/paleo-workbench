# CONV-26 — Workflow / Provenance / Recompute Native Runtime Closure

Branch: `feat/cpp-workflow-runtime-closure` · Base: `origin/main` (ff67dcf3)
Library: `libs/workflow_runtime` (`Pwb::WorkflowRuntime`, gate `PWB_BUILD_CONV_26B`)

## 本分支负责

1. **Freshness / stale evaluation 原生化**（A）— `workflow/current_context.py`（数据类核心）+
   `workflow/freshness.py`（FreshnessService 全量语义：evaluate_run/version/domain_task、
   selection-mismatch 6 规则、content-identical 容差、transitive stale、identity 期望、
   integrity 维度、downstream_impact、step_freshness 聚合）+
   `workflow/interpretation/staleness.py`（StalenessVerdict 汇聚词汇 + 三适配器）。
2. **Recompute plan 原生化**（B）— `workflow/recompute_plan.py` 全量：build_recompute_plan
   （roots 扩展 asset/domain 兄弟、task-links H11、stale_only 过滤、复用匹配、拓扑排序）、
   PlanExecutor（generation guard、cancel、失败隔离、version-namespace poisoning）。
3. **Constraint versioning 运行时**（C）— `workflow/constraint_versions.py` 全量：
   content hash（canonical sha256）、commit（经 repository seam，不再直连 SQLite service）、
   pins（for_task/pinned/staleness/late binding）、compare、resolve_constraint_ref。
4. **Workflow Runtime Service**（D）— `pwb::workflow_runtime::WorkflowRuntimeService`
   稳定 API，供 C++ application 直接消费。动词到方法面的映射：create＝WorkflowSpec
   构造（无服务端工厂）、validate/execute/plan/execute_plan/explain_stale/
   list_outputs/provenance_trace/snapshot/build_context 为具名方法；cancel 经
   workflow_engine CancelToken 参数传入（协作式）；resume/retry 是
   re-plan + REUSE_EXISTING seam（成功步骤留在 store 中被复用，失败步骤重算）。
5. **Task adapter bridge**（E）— NodeAdapter registry：把已有 C++ op（workflow_engine 的
   map.extract_factors / map.interpolate_idw / test.noop + runtime 内置 op）以带
   resource hint / cancel / progress / 错误映射的适配器接入；不复制算法。
6. **Provenance 一致性**（F）— `workflow/provenance_graph.py`（build_product_lifecycle_graph）
   + RuntimeStore：Workflow node → DataRun → DataVersion → Evidence → downstream stale/reuse
   单一状态源。
7. **并发与资源模型**（G）— ResourceHints（cpu/ram）、TaskAdmission（bounded concurrency、
   无界线程禁止）、CancelToken 贯穿、deterministic scheduling。
8. **Oracle/Contract testing**（H）— `tools/oracle/generate_workflow_runtime_fixtures.py`
   驱动真实 Python 实现冻结 oracle，C++ replay 对账；覆盖 empty/linear/diamond DAG、
   cycles、stale 传播、partial change、constraint current/stale、failed/canceled run、
   reuse、version missing、duplicate version/run、UTF-8、deterministic ordering、exception parity。

## 明确不负责

- Catalog SQLite / Workspace 完整迁移（Data 分支）— 本分支只定义/使用 repository seam
  （`CatalogRepository` 接口 + 内存实现 RuntimeStore）。
- QGIS UI 按钮/图层面板（UI 分支）。
- ONNX 推理实现（Prediction 分支）。
- 产品 packaging（Product Closure / Build Hardening 分支）。
- `dag/store.py`、`dag/receipt.py`、`dag/reproduction.py`、`dag/plan_view.py` 持久化面
  （后续切片；本分支 runtime store 是 catalog-lineage 侧的，不是 DAG checkpoint 侧的）。
- `service.py` 的 home_workflow_steps/QC/dashboard UI 聚合面（依赖 project models + QC
  模块，属 UI 服务层；本分支移植其纯依赖 `_FRESHNESS_STEP_OPS` 语义所需的
  step_freshness）。
- `orchestrator.py`（legacy headless step-cursor，自述"生产 UI 不得依赖"）。

## 与其他并行方向的边界

- 不修改 CONV-06/07/23/25 已冻结库的公共 API；`workflow_runtime` 只**消费**它们
  （WorkflowGraph 算法、WorkflowEngine 执行器/CancelToken/NodeRegistry、factor_host
  canonical_encode、domain Sha256/Json）。
- 根 CMakeLists.txt 只加一个 `PWB_BUILD_CONV_26B` 选项 + 一个 add_subdirectory（最小 patch）。
- ledger 台账 `.goal-loop-ledger.md` 追加一节，不重写他节。
