# Progress — Line 11 (Agent/Harness 原生转换)

## Round 1 — 2026-09-20 (base 06211541)

- 平台检查：无 /goal、/goal-loop 命令（技能清单核实）。采用文件持久化循环；预算按
  “完成即停”执行（请求 3.6 亿上限，无计量工具可查询，如实记录）。
- `git fetch origin` 成功；origin/main = 06211541ae1ccce22b0d5ba9258ce722170ca98b
  （PR #1410/#1411 已并入，与任务卡一致）。开放 PR 查询（任务生成时）为空。
- worktree：/home/kevin/project/worktrees/cpp-close-11-agent-harness
  分支 codex/cpp-close-11-agent-harness-20260920 ← origin/main，git common-dir =
  /home/kevin/project/paleo-workbench/.git（同仓共享锁）。
- 协调登记：.git/codex-coordination/cpp-close-wave/11-line.json（原子写入）。
- Oracle：`libs/closure_agent/oracle/generate_agent_oracle.py` 用真实冻结 Python
  （经 oracle-venvs/conv11，绕过包 __init__ 重依赖链加载 4 个叶子模块）生成
  `closure_agent_tests/agent_oracle.json`：8 条查询的意图判定、计划骨架、spec 校验
  problem 文案、tool_schema 派生、默认权限。Python 源 SHA = base（06211541）。
- 实现：libs/closure_agent（spec/registry/context/executor/intent/planner/events/
  checkpoint/model_transport/tool_source/session，11 对 hpp/cpp）+
  workflow/workflow_engine_runner（02 消费 adapter，TARGET Pwb::WorkflowEngine 存在时编译）。
- 根 CMakeLists：BEGIN/END CLOSURE-AGENT 命名块（option PWB_BUILD_CLOSURE_AGENT，
  implies PWB_BUILD_PROVIDERS；仅 add_subdirectory，无他人行改动）。
- 测试：7 个可执行（oracle/executor/session/checkpoint/events/model/workflow）。

## Round 2 — 构建（资源门）

- 第一次 Configure：RESOURCE_BUSY holder_pid=527609 age_min=2.4 → 按合同退避，
  继续轻量工作（本 ledger 更新）后重试。
- 资源约束：j4 上限/j2 默认；ctest parallel≤2；OMP/BLAS 单线程（本线无数值 kernel，
  主要是编译并行）。

### 命令记录
见 acceptance.md（构建/测试证据随轮次追加）。

## Round 3 — 构建/测试/修复（资源门内）

- Configure 发现：PWB_BUILD_PLATFORM 默认 ON 会拉 QGIS vendored SDK（本线不需要）；
  显式 `-DPWB_BUILD_PLATFORM=OFF`。CONV-07 需显式 PWB_BUILD_MAPPING_KERNEL=ON。
- 首次构建通过后 ctest 4/7 → 逐项修复：
  1. executor：admission lease 未释放（unique_ptr 析构不调用 release()）→ 改用
     与 providers SDK 相同的 LeaseGuard RAII（每个 return 路径恰好释放一次）。
  2. executor：validate_parameters label——冻结 Python 用默认 "parameters"
     （实测 Python 产出 `parameters.dpi: required`），去掉 "arguments" 传参，
     测试期望按冻结 Python 实测文案校正。
  3. session：run_plan 未把已授权的 WRITE 提升进 context.permissions → 按
     agent_panel 语义在授权后注入 Write；恢复路径改为从计划实时推导写集
     （pending_write_actions_ 缓存不随 checkpoint 恢复）。
  4. session：取消令牌不可赋值（atomic 成员）→ shared_ptr<CancelToken> 每轮换新。
  5. workflow adapter：RunFunctionMap 以 action_id 为键（不是 node_id）；
     summary 携带 node error；测试 spec 补 "name"/"slots"（from_dict 必填）。
  6. 测试自身：const Json operator[] 缺键 assert（session_test 读 outputs 前
     未 contains）、resume 块迭代预算语义期望（一个 ready batch/iteration）。
  7. Sha256 API 名 hex_digest；TypedInput 在 providers/registry.hpp（补 include）；
     checkpoint libc 调用去 `::` 前缀（O_RDONLY 是宏）。
- 修复后 gate 内连续两遍：`100% tests passed out of 7`（7/7：oracle/executor/
  session/checkpoint/events/model/workflow）。session 52 checks、executor 35 checks。
- 第二遍执行时 gate 曾被 line-12 的长任务持有 → 排队退避（flock probe + sleep），
  未绕过锁、未清理他人锁。

## Round 4 — 独立审查 + 修复复验 + 提交/PR

- 独立审查子代理（1 个，read-only）对 diff 与 Python 契约做全文审查：REQUEST_CHANGES
  （4 P1 阻塞 + 9 P2），全部同轮修复（明细见 findings.md Round 4）。
- P1#1 的正确落点是特征表而非散置 option：`cmake/PwbFeatures.cmake` 新增
  BEGIN/END CLOSURE-AGENT 声明块（PWB_BUILD_PROVIDERS + PWB_BUILD_CLOSURE_AGENT，
  IMPLIES 链 PROVIDERS→DATA+MAPPING_KERNEL+CONV-02），根 CMakeLists 只保留
  subdirectory 具名块；向公共特征表写入的租约已登记 11-line.json。
- 复验（资源门内）：
  - 全新 configure 仅传 `-DPWB_BUILD_CLOSURE_AGENT=ON -DPWB_BUILD_CONV_06=ON
    -DPWB_BUILD_CONV_07=ON -DPWB_BUILD_PLATFORM=OFF` → Generating done
    （implies-providers 链经 resolver 生效，审查项 #1 关闭）。
  - Build 全目标链接成功；Test 连续两遍 `100% tests passed out of 7`
    （session 66 checks，executor 36 checks）。
- 提交 22ae60b178b987e66c2efd9a171739aba11f0767（单提交，base=06211541），
  推送分支 codex/cpp-close-11-agent-harness-20260920，
  PR: https://github.com/WindWang2/paleo-workbench/pull/1420（指向当前 main，未合并）。
