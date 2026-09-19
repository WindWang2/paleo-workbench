# CONV-32 findings — workflow 引擎完成面 + 解释域核（scope ledger）

Branch `feat/cpp-workflow-contracts`（worktree `../worktrees/cpp-workflow-contracts`，base origin/main 5a6373bd）。
Scope = M7「工作流引擎核」收口：`workflow/dag/` 剩余 5 文件 + `workflow/constraint_capabilities.py` + `workflow/interpretation/` 剩余 7 文件。
cmake 本机不可用：验证边界 = g++ -std=c++20 直连全闭包编译 + 真实 Python oracle replay ×2 + negative self-check（CONV-31 预案先例）。CMakeLists 按 CONV-06/07 先例预接线供 CI。

## A. 终态三列（Python source → 语义要点 → C++ 目标）

### A1. 本切片移植（13 个 Python 文件 → 新 TU，oracle 冻结 + replay）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| dag/store.py (261) | 原子 JSON checkpoint（tmp+rename、indent=1 无尾换行、store_version 首键）、run 列表（点前缀 tmp 不可见、损坏跳过告警）、内存缓存索引（lazy 构建、RUNNING 跳过、from_cache/空 outputs 不入、幂等、updated_at 升序种子、newest-first 候选）、find_reusable_node 全量再验证（COMPLETED/FAILED/INTERRUPTED、非 from_cache、outputs 可解析/trashed/VERIFIED）、run_lineage 断链即停、default_store_root 双形态 | workflow_engine `store.hpp`（冻结契约）+ `store.cpp` |
| dag/reproduction.py (67) | describe_reproduction 纯投影（spec 节序、receipt 优先 cache_identity、首个带 environment 的 receipt、两条 contract 文案逐字、deterministic_action 恒 null） | `reproduction.cpp` |
| dag/receipt.py (258) | ExecutionReceipt 26 字段（成员序=to_dict 键序）、RECEIPT_SCHEMA "1.0"、build_receipt（provenance 提取、degraded_reason join";"/"verification warnings"、qc_metrics 去 provenance、duration_ms 半偶 3dp）、输出版本收集（artifacts→version_ids→singular 去重保首）、输出摘要（`<in-process handle>`/`<N items>`/`<N keys>`/artifact_count）、environment_identity 三键注入 seam | `receipt.hpp`（冻结契约）+ `receipt.cpp` |
| dag/plan_view.py (203) | PlanItem/WorkflowPlanView（from_spec/from_run/from_summary 三构面、spec 拓扑稳定排序恢复、progress 半偶 3dp、checklist 33% 填充与 current 标记、七态符号 ○●✓✗⊗↷⊘、五态中文标签） | `plan_view.hpp/cpp` |
| dag/engine.py (1120) 全语义面 | create/run/resume/rerun/cancel 生命周期、_ready_batch 轮询驱动（条件节点等 referenced 终态再判）、条件求值四类永不抛、重试（resource_shed 六标记大小写不敏感子串、backoff cancel-aware waiter seam）、缓存身份 canonical_hash + 跨 run 复用 + rerun 携带（parent_run_id、receipt 重盖）、UNAVAILABLE/INTERRUPTED、checkpoint 失败 → `__checkpoint__` 标记节点 + CheckpointFailed、双跑守卫、项目身份守卫（switch→INTERRUPTED 可恢复）、$ref/$slot/$context 运行期绑定 | `run_engine.hpp/cpp`（新 RunEngine；见 D2——legacy Engine 保留） |
| workflow/constraint_capabilities.py (295) | ConstraintKind/Support 枚举、8 方法冻结矩阵（逐字 note）、label 别名、capabilities_for_method KeyError 文案（原始参数 repr + 排序列表 repr）、evaluate_request（去重保首、partial/approximation/unsupported 诊断逐字含 em-dash 大写 NOT、strict→ConstraintViolationError ":;" 逐字）、capability_matrix 全 5 kind 物化 | workflow_interpretation `constraint_capabilities.hpp`（冻结契约）+ `.cpp` |
| interpretation/algorithm_registry.py (272) | AlgorithmSpec 13 键 to_dict（notes 不序列化）、9 条目冻结表（中文标签/别名/参数 schema 逐字）、_from_capabilities 投影（仅声明格）、别名索引 case-fold、canonical_algorithm_id（空/未知 ValueError 逐字、原始参数 repr）、UI 列表顺序权威 | `algorithm_registry.hpp`（冻结契约）+ `.cpp` |
| interpretation/factor_product.py (330) | FactorProduct 24 键投影（五 artifact 固定序 + 逐字缺席理由三分支、unit 三梯声明语义、grid_shape (h,w) 纯整型过滤、qc 10 键规范序、catalog/workspace/freshness 三 seam） | `factor_product.hpp/cpp` |
| interpretation/summaries.py (184) | SummaryRow/FactorSummary/InterpretationSummary（Python str() 语义值格式化——最短往返浮点/True/False/None、11 行固定序 + QC·4 键子集、新鲜度原状态串、12 字符 base 截断、冲突四键序） | `summaries.hpp/cpp` |
| interpretation/constraint_product.py (297) | 10 地质 kind 词表 + role→engine 映射（fault→barrier 等）、CRS 纪律（不一致抛/单边降级 note/双边 unverified，逐字 em-dash 文案）、行摘要（strength 键存在性、confidence 词表）、组投影（committed/current_constraint_version、live content_hash、uncommitted/current/unknown staleness、validity 中文逐字） | `constraint_product.hpp/cpp` |
| interpretation/revision.py (252) | InterpretationRevision 12 键 codec（tolerant from_dict）、layer 指纹（sort_keys + Python 默认分隔符 ", "/": "、数 9dp、raw 树顶点计数、空→sha256("[]")）、记录语义（内容不变→null、delta 差分、线性父链、文档突变 + integrated 域链接幂等）、summary 空链中文文案 | `revision.hpp`（冻结契约）+ `revision.cpp` |
| interpretation/compilation.py (457) | CompilationInputSet/Entry codec、create（解析快照随条目）、validate 三 verdict（blocked 优先 degraded；全角'；'拼接文案）、freeze 状态机（FLOATING 单组钉住/多组拒绝、RESOLVED/STALE 钉 + 选择器重写仅当可解析、拒绝全量回滚原子性、双冻结拒绝——全部文案逐字）、persist/active 翻转、evidence_view 单一消费适配器、legacy shell 迁移（坏选择器逐条跳过） | `compilation.hpp/cpp` |
| interpretation/integrated_interpretation.py (413) | IntegratedInterpretation 19 字段+active:true、create 去重（中文文案）、_layer_payload 规范 JSON（sort_keys 默认分隔符）、commit 编排（双护栏先行→catalog 资产查找→register_run→result_asset/version 分支→complete/failed 状态→文档同步→revision 域链接双保险→last_committed 推进）、summary missing/ok 两形 | `integrated_interpretation.hpp/cpp` |

### A2. 已移植（此前切片，本切片核对语义并引用为证）

| Python | 证据 |
|---|---|
| contracts/ 全部 6 文件（models/modules/registry/validation/readiness/report） | libs/workflow_contracts（modules_data.inc 冻结 14 契约 + readiness/report 全分支；本切片复核 FULL，未改） |
| dag/model.py + dag/validation.py | libs/workflow_spec（CONV-06：NodeCondition/RetryPolicy/全字段 NodeRun/WorkflowRun/create_run 注入/canonical_hash/bind_parameters/slot 门） |
| interpretation/evidence.py | libs/workflow_graph/evidence（选择器文法全分支/逐 kind 解析/is_usable——本切片 compilation 直接消费，复核 FULL） |
| interpretation/staleness.py 词表+三适配器 | libs/workflow_runtime/staleness（FULL；见 A3 的 3 函数 seam） |
| workflow/constraint_versions.py | libs/workflow_runtime/constraint_versions（current_constraint_version/content_hash/resolve_constraint_ref——本切片 constraint_product/compilation 消费） |
| workflow/factor_units.py | libs/factor_fusion/factor_units（unit_for_factor；FACTOR_FAMILIES 未导出→本切片在 factor_product.cpp 局部冻结，见 D6） |

### A3. 如实不移植/延后（理由 + 边界）

| 面 | 终态 | 理由 |
|---|---|---|
| engine.py `_drive_parallel`/`submit_to_scheduler`/scheduler token 同步 | 延后（顺序驱动） | 主计划明文「DAG 执行器不是 TaskRuntime」；CONV-07 顺序先例；C++ 宿主暂无调度器桥需求（D5） |
| engine.py `_register_cache_run`（catalog provenance 轨） | 延后 | Python 自注释复用限于 store；catalog 桥属消费方接线切片 |
| engine.py session 指针 merge/restore | 最小 ISessionContext seam（默认 no-op） | 跨进程指针本就不可恢复（Python 注释）；宿主上下文随接线切片注入 |
| engine.py WorkflowEngine 全语义面 vs legacy Engine | **并存**：新 RunEngine = 全语义；legacy Engine（CONV-07 最小面）保留 | legacy 有在库消费者（apps self_check、workflow_runtime node_adapters/runtime_service）；重写波及平台面，超出本切片（D2）；退役随消费方接线切片 |
| interpretation/staleness.py `evaluate_verdict`/`workspace_verdicts`/`propagate_to_products` | 延后 | 依赖 mapping_workspace.MappingDependencyService（未移植域）；本切片消费方（compilation/integrated）不用 |
| interpretation `version_compare` | 不存在 | `__init__.py` 文档引用但仓库无此文件（Python 侧即缺） |
| compilation `_pin_floating_constraints` 的 catalog 依赖 | CatalogRepository* seam（null=拒绝浮动钉住） | 与 Python catalog=None 语义一致 |

## B. 共享/冲突文件（swarm 并行纪律）

- 冻结头（协调者持有，实现 agent 只读）：`store.hpp`、`receipt.hpp`、`constraint_capabilities.hpp`、`algorithm_registry.hpp`、`revision.hpp` —— 解除 engine↔store/receipt、registry 双簇、revision↔integrated 的并行环。
- `libs/workflow_engine/CMakeLists.txt`：追加 5 个 TU + PUBLIC Pwb::WorkflowSpec；根 CMakeLists CONV-07 门新增要求 CONV_06。
- 根 `CMakeLists.txt`：`# BEGIN CONV-32` 块（PWB_BUILD_CONV_32 门 + add_subdirectory(libs/workflow_interpretation)，前置要求 CONV_25/26B/24）。
- 新库 `libs/workflow_interpretation`（8 TU + 5 测试目标，链接 Graph/Runtime/Fusion/Domain）。
- 无 ui/、无 QGIS、无 Qt（全部 Qt-free core）。

## C. 验证口径

- oracle：8 个生成器（`tools/oracle/generate_workflow_{store,receipt_plan_view,engine_lifecycle,interpretation_registry,interpretation_factor,interpretation_constraint,interpretation_compilation,interpretation_integrated}_fixtures.py`）真实 import 冻结；再生成字节一致（各 agent diff/sha 验证）。
- replay：8 个测试二进制全绿 ×2（598 checks）+ negative self-check 共 30 处（篡改必检出）+ 旧 `workflow_engine.run` 回归绿 ×2（legacy 面未破坏）。
- 集成闭包 = 8 解释 TU + runtime 全 9 TU + engine 新 5 TU + legacy 2 TU + spec/graph/fusion/factor_host/mapping_kernel(除 ring_ops)/domain —— 单一命令行并编通过（ODR/命名冲突清零；namespace 内全限定 `workflow_spec::` 规避 legacy 同名最小类型）。
- 生成器确定论：uuid/time/environment 全注入或 monkeypatch；{ROOT}/{TMP} 占位。
