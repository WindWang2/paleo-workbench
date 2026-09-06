# Decisions — Geological Harness 2.0

架构裁决记录（等价 ADR 细节；重大项单独写 ADR-0068）。

## D1 — ActionResult 六态词汇（H1）

**裁决**：`success/degraded/failed/cancelled/rejected/unavailable` 为唯一规范状态。
旧 `ok/warning/fail` 词汇废弃并在同分支内完成迁移（agent_panel + 测试）——不做双词汇
长期共存。`rejected` 专指执行前守卫拒绝（schema/权限/上下文/静态校验），与
`failed`（执行中/验证失败）区分；`unavailable` 表示依赖的生产能力缺失（如 native
backend、模板注册表），不得伪造结果。理由：Goal 硬性要求六态；双词汇会保留第二套
真相，正是 Architecture review 要消灭的东西。

## D2 — DAG 引擎放 `workflow/dag/`，不建第二调度权威（H2）

**裁决**：新包 `paleo_workbench/workflow/dag/`（model/validation/engine/checkpoint/
cache/store/reproduction/plan_view）。调度三原则：
1. 整个 WorkflowRun 在应用内作为**一个** TaskScheduler heavy task 提交（保持全局
   IO 并发 1 契约与 #1081 单队列）；
2. 节点级并行 = 引擎内就绪集 + 结构性 max_concurrency（默认 1）。并行模式下
   引擎为就绪节点建受界 worker 池（非队列权威）；每个 action 仍各过自己的
   governor admission，资源只被治理一次。含共享进程内可变状态（如图件文档）
   的工作流必须声明 max_concurrency=1；
3. headless/测试可用同步模式（同一状态机，只是调度步进由调用方驱动）。
不复用 orchestrator.py（线性 legacy，服务首页 step 投影的另一关注点）；不复用
PlanExecutor（串行、无持久化，其 freshness/recompute 域保留原样）。

## D3 — Cache：run-store 索引 + catalog 验真（H3，review 后修订）

**裁决（实现版）**：node cache identity =（action_id@spec_version, 实际绑定参数
JSON, 输入版本 IDs）。复用查找扫描 run-store 的历史 NodeRun（identity 相等 +
终态成功 + 非携带），命中后必须在 catalog 中 resolve 每个 output 版本且
`verify_integrity == verified` —— catalog 仍是产物唯一真相，store 索引只是查找
加速。cacheable 节点执行时在 catalog 登记 `workflow.node.*` DataRun（cache
identity 入 parameters），与 provider 自身 run 并存（receipt.catalog_run_id 保留
provider run，二者互补）。in-process-only 输出（如 MapDocument handle）不可声明
cacheable（validate_action_spec 静态拒绝）；首个生产声明为
seismic.compute_attribute（确定性 ROI 核 + 派生目录版本）。

## D4 — 持久化位置与格式（H3/H4）

**裁决**：WorkflowRun 状态与 recipe 都落在 project-managed artifacts 树
（`<project>.artifacts/workflows/`），原子写（tmp+os.replace）；recipe 扩展名
`*.paleo-workflow.json`（Goal 指定）。不引入第二套工程文件格式、不写 catalog
schema。catalog 仍是数据版本唯一权威；run 文件只引用 version IDs。

## D5 — 项目切换守卫（H5）

**裁决**：WorkflowEngine 在 run 开始持有 project document 的强引用 + 可选
identity probe（host 注入 callable）。每个节点调度前校验 identity；不匹配→
剩余节点 rejected（reason=project_switch），已完成的保留。强引用保证旧 id 不会被
复用误判。执行中 handler 只见捕获的 ActionContext（含旧 project 引用），天然
写不到新工程；catalog 端口按 run 捕获的实例解析。

## D6 — Receipt 是引用不是副本（H6）

**裁决**：receipt 只引用 canonical IDs（run_id/version_id/lease title），QC
metrics/warnings 可内嵌（小、标量）。不复制 lineage 图；project history 等消费方
经 catalog 解析。

## D7 — Provider V2 = V1 加法，不加第二个 SDK（H7）

**裁决**：CapabilityProvider 协议加 optional `verify(result, context)` 与
descriptor.build_identity；`execute_provider` 在 execute 后调用 verify，
verifier FAIL → 执行 fail（fail-closed），不吞。第三方 example 以
`examples/provider_plugins/` 真实包呈现（注册路径与 builtin 相同），不搞第二套
加载器。

## D8 — 新 action 的 unavailable 语义（H8）

**裁决**：底层生产服务不存在/不可用（如 well.correlate 无 engine 接入）→ 返回
`unavailable` + 原因，绝不生成合成结果。READ 型包装 catalog/project 的能力真实
实现。地震 action 仅 small/medium ROI 参数域（schema max 约束）。

## D9 — Agent Panel 接线只做数据模型（H11）

**裁决**：新增 `workflow/dag/plan_view.py` 的纯 Python 可观察模型
（WorkflowPlanView：状态枚举+进度+回调），agent_panel 增加一个清单式渲染
（沿用现有 QTextBrowser/样式 vocabulary），不改 UI Design System、不引入第二套
任务中心。样式由 UI 方向拥有。

## D10 — 兼容与迁移

**裁决**：ActionSpec 构造参数全部向后兼容（新字段带默认值）；status 词汇迁移
（D1）是唯一 breaking change，消费者全部在本仓库内。Recipe schema version=1，
带 migrate 钩子（当前 v1→v1 恒等）。

## D11 — 阻断缺陷修复记录

- b8638b62：嵌套 provider 执行继承外层准入租约（e2e Scenario C 在 segyio 可用
  机器必失败的既有缺陷）。

## D12 — Review 修复裁决（三轮独立 review 后）

- **run 重入互锁**：run/resume 入口拒绝同 run_id 的并发驱动（双执行 +
  checkpoint 互相覆盖）。
- **carry-over identity**：新身份用调用方 live context 绑定，旧身份用执行时
  记录值——$context 绑定不再被默认 context 求值掩盖。
- **condition 求值时点**：条件引用的全部节点到终态后才判定，防"提前 SKIPPED
  且不补跑"。
- **项目切换 = INTERRUPTED**（可恢复），不是 CANCELLED；恢复匹配工程后续跑。
- **checkpoint 失败 fail-closed**：写盘失败中止 run（FAILED + __checkpoint__
  哨兵节点），绝不带着失效持久化报 COMPLETED。
- **取消贯通**：宿主/scheduler 协作取消经 `external_cancel` 注入引擎 token；
  workflow.run/resume 动作转发 context.cancel。
- **recipe.load/clone 路径边界**：仅限工程 workflow store 子树，杜绝任意路径
  文件探测。
- **store 单一路径权威**：workflow 存储走 project.paths.artifact_dir_for；
  引擎默认不钉死 store，按 context 路由（跨工程不串目录）。
- **workflow.* 不可入图**：元工作流递归在静态校验即拒绝。
