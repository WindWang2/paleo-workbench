# Workstation UX V6 — 07 Agent 与任务 UX

Date: 2026-09-07

## 1. Harness 2.0 权威不动

`ActionSpec/ActionRegistry/HarnessExecutor` 守卫链（lookup→validate→permission(DESTRUCTIVE 拒装)→context→governor→execute→schema→verify）与 `TaskScheduler`（重队列 IO=1 + 交互道 + 老化）**原样保持**。V6 只修产品面。

## 2. 诚实结果渲染（baseline F-P0-1）

`AgentWorkspace._on_completed` 分支化六态：

- **DEGRADED** → 「降级完成」+ 逐条 warnings（此前一律「校验通过」，warnings 丢弃）。绝不假成功。
- rejected/unavailable → 失败渲染保留守卫原因文本（如「写入未授权：当前会话只读」）。
- cancelled / failed 语义不变。

## 3. 专业 WRITE 授权（baseline F-P1-1）

`_confirm_write_actions` 重写为结构化授权对话框：

- **动作卡**：每个 WRITE 动作 id + `ActionSpec.description`（注册表权威）；未知 id 诚实标注「注册表中无此动作描述——按 WRITE 对待」。
- **安全默认**：「拒绝」按钮持有 default/focus（回车=拒绝）。
- **会话粒度**：显式勾选「本会话内记住该授权」才记住；语义是**精确动作集合**（`_write_granted_for` 子集判定，非空白支票）；授权集合变化发 `write_grant_changed`（UIContext `write_granted` 消费，§02）。
- `confirm_write` 注入钩子保留（一次性，不入会话记忆）；环境/构造器 opt-in 语义不变。

## 4. 重算流接通（baseline F-P1-2）

`WorkflowController.request_recompute()` 公共入口 + palette 命令 `workflow:recompute`（context_tags: workflow/mapping/catalog）。此前的孤儿方法 `_on_recompute_requested` 有真实发射方。

## 5. 任务中心（本轮未改，审计结论保持有效）

QAbstractTableModel 差分刷新、delegate 绘制、零 per-row widget、「取消中/已取消」区分、inline 错误——已是正确形态。`running_task_count` 口径与任务中心对齐（QUEUED+RUNNING，review round 3）。

## 6. 遗留（见 10）

正则 planner 永不产 WRITE 计划（授权对话在自然工作流中仍少被触发）；Task Center retry 重放闭包；run-history/resume UI；outputs/verification/receipts 渲染。
