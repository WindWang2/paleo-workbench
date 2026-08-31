# ADR 0066: Geological Agent Harness（稳定专业动作层）

- Status: Accepted
- Date: 2026-08-31
- Deciders: WindWang2（产品裁决），ZCode P2 convergence 会话
- 关联: ADR 0064（资源治理）、ADR 0065（Provider SDK）、ADR 0056（目录权威）

## Context

要让 AI/Agent 参与地质工作流，错误做法是让 LLM 驱动 UI（findChild/click）或直接开 SQLite/
项目文件。正确做法：把已稳定的专业工作流（Workspace/Well/Seismic/Mapping/Geology）收敛为
**稳定专业动作**，harness 负责暴露、校验、执行、验证、反馈；规划交给外部 agent（LLM 无关）。

## Decision

**`paleo_workbench/harness/`，四件套 + 守卫执行**：

1. **ActionSpec**（单一事实源）：action_id/description/JSON-schema/风险（READ/COMPUTE/
   WRITE；DESTRUCTIVE 存在于词汇但默认注册表拒装）/resource_profile/required_context/
   supports_cancel/provider_id。**tool schema（OpenAI/Gemini 形状）由 spec 派生**——运行时
   校验、agent 工具、文档三处同源，禁止另写一套。
2. **ActionContext**：会话上下文（工作区、SelectionSnapshot 只读快照、激活井/体/图、
   catalog 端口）；`from_app()` 从 P1 协调单一权威读取。Agent 只读上下文，修改只能走动作。
3. **HarnessExecutor 守卫管线**：lookup → schema 校验 → 权限门 → 上下文门 → governor
   admission（P2-A lease）→ handler（领域服务）或 capability provider（P2-B）→
   ScientificValidator + MapValidationHook → ActionResult（ok/warning/fail + 验证 + 指标）。
   handler 异常隔离；验证 FAIL 不得宣称成功。
4. **验证钩子**：科学验证（全 NaN FAIL、覆盖稀薄/常值 WARNING、轴非升序/越界/CRS 错配
   FAIL）；图验证（图层/范围/CRS/合成要素，导出 fail-closed：验证不过不出图）。
5. **动作清单（20 个，粗粒度）**：workspace(5)/well(5)/seismic(3)/map(7)/geology(2)/
   workflow(1)。地图导出路径**限制在工作区内且拒绝覆盖既有文件**（无破坏性导出）。
6. **LLM seam**：`ToolSource`/`ChatModel` 纯协议 + `HarnessToolSource` 适配器；零厂商客户端。

## Consequences

- Agent 场景（井位图/开井显曲线/体属性/克里金成图/导出）全部走生产路径端到端跑通
  （tests/e2e/test_harness_scenarios.py，无 mock）。
- READ 动作派发开销实测 <1 ms（预算 <10 ms，不含业务 IO）；registry 查找 ~O(1)。
- `well.create_display` 产出显示文档（纯数据）而非驱动控件——UI 负责渲染；井/地质解释的
  草稿-版本写入暂留 UI 邻接工作流，harness 只读暴露（诚实范围，待有守卫写入器再扩）。
- 既有 `paleo_workbench/agent/`（规则式 swarm）不被替代也不重复：ActionRegistry 是动作
  权威，旧 harness 的 ToolRegistry 如需可从其派生 schema。
- 已知限制：进程内 MapDocument 存于会话上下文；持久化仍走既有项目保存路径。
