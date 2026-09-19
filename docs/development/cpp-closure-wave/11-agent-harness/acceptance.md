# Acceptance — Line 11 (Agent/Harness 原生转换)

验收状态基于 base 06211541ae1ccce22b0d5ba9258ce722170ca98b（origin/main，PR #1410/#1411 已并入）。
所有命令在资源门（scripts/cpp-migration/invoke-resource-gate.sh，flock 落
/home/kevin/project/paleo-workbench/.git/cpp-migration-heavy.lock）内执行；
编译 j≤4、ctest parallel=2；同一主机与其它线共享同一把锁。

## 本线四列能力清单（implemented / merged / wired / verified）

| 能力 | implemented | merged | wired | verified |
|---|---|---|---|---|
| ActionSpec V2 契约 + schema/spec 校验（harness/spec.py） | ✔ 本线 | 本 PR | executor/registry | ✔ oracle（agent_oracle.json 冻结判定） |
| ActionRegistry 单一权威 + tool_schema 派生（harness/registry.py） | ✔ 本线 | 本 PR | executor/session/tool_source | ✔ oracle + executor_test |
| 守卫执行器六态管线（harness/executor.py） | ✔ 本线 | 本 PR | session/workflow adapter | ✔ executor_test（守卫顺序/文案 parity） |
| ActionContext + selection snapshot + provider_context（harness/context.py） | ✔ 本线 | 本 PR | executor | ✔ executor_test |
| 意图解析（agent/intent.py，中文关键词/地层/factor） | ✔ 本线 | 本 PR | session.submit | ✔ oracle 8 条查询逐字段 |
| DAG 计划器（agent/planner.py 七类节点骨架） | ✔ 本线 | 本 PR | session.submit | ✔ oracle（节点/依赖/顺序） |
| 会话状态机 + 写授权边界（agent_panel.py 会话语义） | ✔ 本线 | 本 PR | session（12 装配 Qt 面） | ✔ session_test（部分授权不运行/拒绝终止） |
| 审计回执 + 重复回执拒绝 | ✔ 本线 | 本 PR | session | ✔ session_test（7 回执/重复拒绝） |
| 会话 checkpoint（sha256 信封原子写）+ 损坏拒绝 | ✔ 本线 | 本 PR | session | ✔ checkpoint_test + session_test（篡改拒绝） |
| 恢复/恢复点续跑（崩溃映射 RUNNING→PENDING 语义） | ✔ 本线 | 本 PR | session.recover/resume | ✔ session_test（中断→恢复→续跑完成；失败步不静默重试） |
| 事件流（订阅/顺序/回放） | ✔ 本线 | 本 PR | session 全量发布 | ✔ events_test + session_test 事件断言 |
| 取消 + 取消后晚到结果拒绝 | ✔ 本线 | 本 PR | session + executor CancelToken | ✔ session_test（晚到结果记 skipped，不复活） |
| 模型传输 seam（harness/llm.py）+ 确定性录制回放 | ✔ 本线 | 本 PR | IChatModel/RecordedChatModel | ✔ model_transport_test |
| 工具面绑定（HarnessToolSource `__`↔`.`） | ✔ 本线 | 本 PR | 外部 agent runtime 绑定面 | ✔ model_transport_test |
| 消费 10 typed providers（line 10 SDK） | 消费方 | 已在 base | execute_provider + register_builtin_providers | ✔ executor_test/session_test 走真实 geology.factor_stats |
| 消费 02 workflow（RunEngine checkpoint/resume） | 消费方 | 已在 base（#1410） | WorkflowEngineRunner adapter + IWorkflowRunner | ✔ workflow_adapter_test（节点经守卫管线、store 落盘、越权节点 rejected）；token→cancel_probe 桥接在 executor 层断言（引擎 token 中途翻转属 02 线引擎测试域，workflow 测试头已如实声明范围） |

## 已执行验证（真实命令与结果）

资源门内（j2，ctest）连续两遍，第二遍为修复后确认：

- Build: `invoke-resource-gate.sh Build -s <worktree> -b <worktree>/build -j 4
  -t "pwb_closure_agent;closure_agent.oracle;closure_agent.executor;
  closure_agent.session;closure_agent.checkpoint;closure_agent.events;
  closure_agent.model;closure_agent.workflow;pwb_closure_agent_workflow"`
  → ninja 全部链接成功（唯一 warning 在 02 线既有 workflow_engine/run_engine.cpp，
  非本线文件）。
- Configure 参数：`-DPWB_BUILD_PLATFORM=OFF -DPWB_BUILD_CLOSURE_AGENT=ON
  -DPWB_BUILD_PROVIDERS=ON -DPWB_BUILD_MAPPING_KERNEL=ON -DPWB_BUILD_CONV_06=ON
  -DPWB_BUILD_CONV_07=ON -DBUILD_TESTING=ON -DCMAKE_BUILD_TYPE=Release -G Ninja`
- Test: `invoke-resource-gate.sh Test -j 2 -r closure_agent`
  - 修复前基线：7/7（两遍）。
  - 独立审查修复后（全新 configure，仅 -DPWB_BUILD_CLOSURE_AGENT=ON
    -DPWB_BUILD_CONV_06=ON -DPWB_BUILD_CONV_07=ON -DPWB_BUILD_PLATFORM=OFF，
    验证特征表 implication 链）：Build 全目标成功；Test 连续两遍
    `100% tests passed out of 7`（session 66 checks / executor 36 checks）。
- Oracle 生成：`oracle-venvs/conv11/bin/python libs/closure_agent/oracle/
  generate_agent_oracle.py`（真实冻结 Python 树，SHA=base 06211541；只读使用主
  工作区，输出落入本 worktree）。

## 诚实限制（未宣称项）

1. **在线模型验证未执行**：本环境无任何模型服务凭据（环境变量为空，网络栈无 TLS）。
   RemoteChatModel 在无原生传输/无凭据时如实抛 ModelUnavailableError
   （model_transport_test 断言该行为与“绝不伪造在线能力”）；已验证的是注入
   HttpExchange 后的真实交换路径（端点/密钥从环境变量读取，测试用自注入的假
   exchange，不外发任何请求）。在线最小验证需真实凭据后另行执行。
2. **GUI 安装面**：本线交付 Qt-free 会话核 + 事件流 + adapter 签名；Qt 面板装配由
   line 12 按合同装配（本线未改 apps/paleo_workbench_platform）。GL/硬件证据不适用
   （本线无 GL 路径）。
3. **统一全量产品矩阵**由 line 12 在集成候选 SHA 上执行；本线提交了可重放命令
   （上文）与资源约束。
4. Python 侧 `agent/agents/*` 八个演示 swarm agent、skill/algorithm/template 三个
   registry 判定为测试参考/非生产路径（见 findings.md 逐文件分类），未移植；
   handler 能力由宿主经 ActionRegistry 注入——无能力时节点显式失败
   （"Agent 'x' not found."），绝不以空列表假成功。
