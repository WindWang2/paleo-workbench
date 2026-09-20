# Findings — Line 11 (Agent/Harness 原生转换)

基线调查记录（base = origin/main 06211541，PR #1410/#1411 已合并，开放 PR 查询为空）。

## 已有 C++ 落点（不重建）
- `libs/providers`（line 10 工具接口权威）：`ProviderRegistry`（显式注册+隔离区）、
  `execute_provider` 守卫管线（resolve→validate→admit→execute→provenance，#1146 租约继承、
  #1137 TaskCancelled 不包裹）、`pwb::domain::Json`（nlohmann ordered_json）、
  schema 校验（providers/schema.hpp，validate_parameters 的 C++ 对应物）。
- `libs/workflow_engine`（02 线，#1410）：`RunEngine`（create/run/resume/rerun/cancel、
  崩溃映射 RUNNING→INTERRUPTED、每节点 checkpoint、`__checkpoint__` 失败节点、缓存五重门）、
  `receipt.hpp`（ExecutionReceipt + build_receipt，schema 1.0 冻结）。
- `libs/job_runtime`（CONV-30）：有界调度、协作取消 token、晚到结果记 cancelled（#1224）。
- `libs/ui_workstation`：`agent_plan.hpp`（UI-12 risk 层：WRITE 授权、registry-first fail-closed）、
  `agent_panel.hpp`（Qt 面板壳）。
- `libs/tool_policy`：编图工具状态机（与本线无关，登记避免混淆——它是 UI 工具可用性，不是 agent 工具运行时）。

## Python 冻结参考（oracle 来源）
- `paleo_workbench/harness/spec.py`：ActionSpec 字段/校验规则、`_ACTION_ID_RE`、
  cacheable⇒deterministic+output_refs、DESTRUCTIVE 不可装入默认 registry、
  tool_schema() 派生（`name.replace('.','__')`、risk 标注）。
- `paleo_workbench/harness/executor.py`：守卫顺序 lookup→schema→permission→required_context→
  admit→execute→output_schema→verifier→verdict 汇合（FAIL>WARNING>PASS）；
  TaskCancelled→`cancelled`（不 re-raise）；ImportError/ModuleNotFound→`unavailable`；
  ResourceExhausted→`rejected`；其余异常→`failed`；elapsed_ms 保守计时。
- `paleo_workbench/harness/context.py`：DEFAULT_PERMISSIONS={read,compute}；
  provider_context() 转发 cancel/progress/租约；derived() 每节点副本（不复制 admission_lease）。
- `paleo_workbench/harness/llm.py`：ToolSource(tool_schemas/execute_tool) + ChatModel(model_id/complete)；
  HarnessToolSource 名字映射 `__`↔`.`。
- `paleo_workbench/agent/intent.py`：中文关键词域打分（井/地震/空间/单因素/古地理/数据/质检/可视化）、
  地层正则、factor_type 映射、confidence 0.95/0.5。
- `paleo_workbench/agent/planner.py`：TaskGraph 七类节点固定骨架（discover→well/seismic(域条件)→
  gis→carto→viz→qa→result），就绪集=依赖全 COMPLETED。
- `paleo_workbench/agent/harness.py`：max_iterations=20、ready-set 调度、deliverable 取
  `task_result_delivery` 节点结果。
- `paleo_workbench/ui/workstation/agent_panel.py`：会话写授权（整计划写集 ⊆ 已授集）、
  取消“在安全点停止”、GUI 历史。

## 关键设计决定
1. 新库 `libs/closure_agent`，命名空间 `pwb::closure_agent`；目标 `pwb_closure_agent`（STATIC），
   `Pwb::ClosureAgent` 别名；PUBLIC 链接 `Pwb::Providers`（由此传递 Domain/MappingKernel）。
   不重建 provider registry：executor 经宿主注入的 `providers::ProviderRegistry*` 派发 provider action。
2. 取消语义：自定义 `CancelToken`（与 job_runtime 同语义：协作式、幂等、不可逆），
   执行器在每个 guard 间与 handler seam 处检查；取消后返回的结果记 `cancelled`，不复活会话状态。
3. 审计：receipt 结构对齐 `workflow_engine/receipt.hpp` 的 ActionResultView 消费面
   （status/outputs/verification/warnings/metrics/error/elapsed_ms），session 审计日志追加
   receipt_id（内容 sha256 前缀）；重复回执（同 receipt_id 二次提交）显式拒绝。
4. checkpoint：session 级 JSON（会话头+计划+每节点状态+receipts），写盘 = tmp+fsync+rename，
   外层信封 `{checksum_sha256, payload}`；载入先验 checksum，损坏→CheckpointCorruptError，
   绝不静默丢弃或假恢复。
5. 模型传输：`IChatModel` seam 完全对齐 llm.py（model_id/complete(messages,tools)）；
   `RecordedChatModel` 按脚本顺序回放录制响应（确定性测试权威）；
   `RemoteChatModelConfig` 存在但无 TLS/网络栈时 `complete` 返回显式 unavailable 错误对象
   ——绝不用 mock 冒充在线能力；本环境无凭据，在线验证如实标注未执行。
6. workflow 消费：`IWorkflowRunner` seam（session 计划节点可委托 02 RunEngine）；
   adapter 目标 `pwb_closure_agent_workflow` 仅在 CONV-06+CONV-07 开启时编译，测试用真实 RunEngine。

## 环境事实
- 40 核 / 62 GiB（可用 ~38 GiB）；资源门 `scripts/cpp-migration/invoke-resource-gate.sh`
  （flock 落 common git dir；j<=4，默认 j2；ctest parallel<=2）。
- 协调登记：`.git/codex-coordination/cpp-close-wave/11-line.json`（工作区外，不入库）。
- 平台无 /goal、/goal-loop 命令 → 文件持久化循环替代（见 task_plan.md）。
- Qt 测试面板不在本线范围（12 装配）；Qt-free 核 + adapter 签名是交付面。

## Round 4 — 独立审查结论与修复（1 个子代理，read-only，全文 diff + Python 契约对照）

审查结论：REQUEST_CHANGES（无 P0）。阻塞项与处置：
1. **P1 CMake 时序**：`PWB_BUILD_CLOSURE_AGENT=ON` 单独配置时 implication 在
   providers 子目录 guard 之后才生效 → 静默不构建。修复：option+implication 块
   移到 providers guard 之前（复验 configure 仅传 CLOSURE_AGENT 一个开关验证）。
2. **P1 checkpoint 失败未致命**：checkpoint_now 失败后循环继续、终态可被覆盖为
   completed。修复：checkpoint_failure_ 标志中断循环，终态映射优先路由 failed，
   终局 checkpoint 跳过重复写；新增测试（不可写 store → turn failed、无 completed 节点）。
3. **P1 cancel() 跨线程数据竞争**：cancel() 曾写 state_/发事件（违反事件总线单线程
   发布契约）。修复：cancel() 只 arm 原子 token；Cancelling 状态迁移移到 run 循环
   安全点（运行线程独占状态写）。头文件线程契约明示。
4. **P1 adapter 取消覆盖是空壳**：测试头宣称覆盖但实际 no-op。修复：删除虚假宣称，
   在 executor_test 增加 cancel_probe→cancelled 的桥接 seam 真实断言；引擎侧 token
   翻转属 02 线引擎自身测试域，workflow 测试头如实声明覆盖范围。
5. **P1 RecordedChatModel checksum 文档过度宣称**：实现之——脚本可携带
   checksum_sha256（responses 规范化 dump 的 sha256），构造时验证，篡改拒绝；
   新增正反测试。

P2 同轮修复：#6 recover() 对缺 turn 对象的 payload 抛 CheckpointCorruptError（不再
const operator[] UB）；#7 output-schema 改为校验包装后的 outputs（Python 顺序 wrap→
validate）+ ActionValidationError 文案模板；#8 文案 parity（NaN 百分比 %.1f、scientific
label=action_id、merge_verification 键序 verdict,reasons,key,others、异常类型名前缀
不可移植已在注释声明差异）；#9 fsync 失败抛 CheckpointStoreError；#10 derived() 复制
cancel_probe；#11 删除死字段 TaskNode::harness_action；#12 resume() 不复活
completed/rejected 终态；#13 checkpoint id 文档更新。

审查确认的正面结论（引用）：守卫顺序与六态映射逐条与 Python 一致；oracle 为外部
真实 Python 生成（审查者本地重放 byte-identical）；session e2e 非自证（真实 provider
SDK 工件、真实文件篡改、真实恢复流）；无假成功路径；CMake 两块为纯插入不改他人块。
