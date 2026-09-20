# Task Plan — Line 11: Agent/Harness 与工具编排的原生转换

## 目标
在 origin/main 06211541ae1ccce22b0d5ba9258ce722170ca98b 基础上，把 Python 产品已有的
agent/harness 能力原生转换为 C++（Qt-free、Python-free），交付可审查 PR。
Branch: `codex/cpp-close-11-agent-harness-20260920`，worktree:
`/home/kevin/project/worktrees/cpp-close-11-agent-harness`。

## 平台说明（诚实记录）
- 执行平台未提供 `/goal`、`/goal-loop` 斜杠命令（本会话技能清单无此二者）。
  采用等价的文件持久化循环：本目录 task_plan/findings/progress/acceptance 四文件
  在每轮更新，上下文压缩后先读四文件恢复。
- 预算请求 360,000,000 tokens（含全部子代理累计）；平台无按调用计量的预算工具可查询，
  以“完成即停”执行，不做机械重复消耗。

## 范围审计结论（基线 06211541）
| Python 源 | 分类 | C++ 去向 |
|---|---|---|
| `harness/spec.py` (ActionSpec V2/六态/校验) | 生产必需 | **本线新移植** `libs/closure_agent/spec.*` |
| `harness/registry.py` (ActionRegistry/工具 schema 派生) | 生产必需 | **本线新移植** `registry.*` |
| `harness/context.py` (ActionContext/SelectionSnapshot) | 生产必需 | **本线新移植** `context.*`（服务经 seam 注入） |
| `harness/executor.py` (守卫管线/六态/取消/降级) | 生产必需 | **本线新移植** `executor.*` |
| `harness/validation.py` (grid/map 校验钩子) | 生产必需(裁剪) | `executor` 内 verify seam；grid 统计校验随最小集移植 |
| `harness/llm.py` (ToolSource/ChatModel seam) | 生产必需 | **本线新移植** `model_transport.*` + `tool_source.*` |
| `agent/intent.py` + `agent/planner.py` (意图→DAG 计划) | 生产必需 | **本线新移植** `intent.*` + `planner.*` |
| `agent/harness.py` (会话执行循环/交付物) | 生产必需 | 并入 `session.*`（与 agent_panel 交互模型一致） |
| `agent/agents/*` 8 个 domain agent | 测试参考/演示 | 不移植：handler 由宿主经 registry 注入，swarm 骨架由 session DAG 承担 |
| `agent/registries/*` (tool/skill/algorithm/template) | 已由 C++ 替代 | tool→`pwb::providers` registry（line 10 权威）；skill/algorithm/template 非生产路径，登记为测试参考 |
| `ui/workstation/agent_panel.py` 会话交互/写授权/取消 | 生产必需 | `session.*` 状态机 + `ui_workstation` 既有 risk 层对接；Qt 面板装配归 line 12 |
| `workflow_engine` RunEngine (02 线) | 已由 C++ 实现 | **消费**（IWorkflowRunner seam + 可选 adapter target） |
| `providers` SDK (line 10 工具接口) | 已由 C++ 实现 | **消费** execute_provider + registry（不重建） |
| `job_runtime` (CONV-30 取消/调度) | 已由 C++ 实现 | **消费** CancelToken 语义 |

## 交付物
1. `libs/closure_agent/`（Qt-free、Python-free；`pwb::closure_agent`）：
   - `spec.hpp/cpp`：ActionRisk/ActionStatus 六态/ActionSpec/validate_action_spec/schema 校验
   - `registry.hpp/cpp`：显式注册、重复拒绝、DESTRUCTIVE 拒装、tool_schema 派生、inventory
   - `context.hpp/cpp`：ActionContext（selection snapshot、permissions、cancel token、provider context 工厂）
   - `executor.hpp/cpp`：守卫管线 → ActionResult（success/degraded/failed/cancelled/rejected/unavailable）+ receipt
   - `intent.hpp/cpp`、`planner.hpp/cpp`：关键词意图解析（冻结中文关键词表）+ DAG 计划器
   - `session.hpp/cpp`：AgentSession 状态机（Idle→Planning→Confirming→Running→…）、会话写授权、
     每步 checkpoint、恢复、事件流发布、取消后晚到结果处置
   - `checkpoint.hpp/cpp`：原子 JSON（tmp+rename+fsync）+ sha256 完整性信封；损坏显式拒绝
   - `events.hpp/cpp`：有序事件流（订阅/退订/回放）
   - `model_transport.hpp/cpp`：IChatModel seam（port harness/llm.py）+ RecordedChatModel（确定性录制回放）
     + 远程配置在无网络栈时如实 unavailable
   - `tool_source.hpp/cpp`：HarnessToolSource（executor+registry 绑定为 agent 工具面）
   - `workflow_runner.hpp`：IWorkflowRunner seam；`closure_agent_workflow` adapter（仅 CONV-07 开启时编译）
2. 测试（CTest，无框架依赖、check() 约定同 providers_tests）：
   - e2e 确定性录制响应：query→计划→工具调用（经真实 pwb::providers）→结果→审计 receipt→checkpoint→取消→恢复
   - 负面：越权 WRITE/DESTRUCTIVE 拒绝、未知 action 拒绝、损坏 checkpoint 拒绝、重复回执拒绝、取消后晚到结果不复活
   - recorded ChatModel 确定性回放 + 篡改检测（checksum/sequence tamper → fail-closed）
   - workflow adapter（CONV-07+CONV-06+kernel on 时）：session 驱动真实 RunEngine run/cancel/resume
3. 根 CMakeLists 增加 BEGIN/END CLOSURE-AGENT 命名块（不改他人行）。
4. 本 ledger 四文件随 PR 提交。

## 验收门（本线）
- [ ] 确定性录制响应覆盖 计划→工具→结果→审计→恢复（≥2 遍）
- [ ] 负面用例全绿：越权/损坏 checkpoint/重复回执/取消后晚到
- [ ] 在线模型验证：本环境无凭据 → 如实标注“未执行”，录制回放为唯一被证路径
- [ ] 生产路径零 Python/零解释器/零 mock 假成功
- [ ] 独立审查（子代理）完成，高优先级问题修复并复验
- [ ] PR 创建，base=当前 main，ledger 引用完整

## 循环
盘点(本文件+findings) → 实现 → 资源门内构建/测试 → 审查 → 修复 → 复验 → 提交/PR。
每轮在 progress.md 记 SHA/命令/退出码/租约；acceptance.md 只记有证据的验收项。
