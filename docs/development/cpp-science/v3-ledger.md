# C 线 v3 账本（codex/cpp-v2-science）

> 任务：真实测井宿主、公共科学接口与任务发布（Prompt C v3）。
> worktree：`/home/kevin/projects/paleo_project/.worktrees/cpp-v2-science`
> （Linux 验证机；prompt 原文 Windows 路径的对应物，基线/分支/gitlink 一致）。
> 基线：`53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`。上限 15 轮，实际 6 轮。

| 轮 | 改动 | 验证（实测命令/退出码见 v3-verification.md） | 判定 | 下一步 |
|---|---|---|---|---|
| 1 | 侦察：仓库/基线 SHA/ledger 核验；工具链实测（cmake 4.4.3、GCC 16.2.1、Qt 5.15.19+6.11.2 系统 SDK、无 pwsh/MSVC）；读 CLAUDE/总设计/cpp-science 全套；C 线源码精读（TaskRuntime/publisher/adapter/测试 CMake）定位基线缺陷；建 worktree+分支，WLE submodule 以本地引用克隆固定 `f845e7ab`；先交 `v3-contracts.md`（冻结 7 公共头 blob SHA + L0–L4 线性化 + 迁移表）= `03ff8155` | worktree=cpp-v2-science@53e22b67 祖先核验 OK；gitlink f845e7ab 与本地 SDK 一致 clean | 通过 | TaskRuntime v3 |
| 2 | TaskRuntime v3：发布前置终态（publishing 阶段、`publisher.publish_threw`/`publisher.publish_failure_threw` 稳定码、exactly-once、`published` 标记、wait 后置发布、worker 线程自等待/跨任务等待检测抛 logic_error、显式幂等 `shutdown()`）；+7 屏障定序测试 = `86d8b38c` | Qt-free 4/4 绿；runtime 单测 15 用例 ×6 连跑全绿（无 sleep 依赖） | 通过 | viewer 装配 |
| 3 | viewer 装配修复：science_suite 选项拆分（BUILD_VIEWER 生产 / VIEWER_TESTS 测试，均 fail-closed）、tests 移到 adapter 之后（基线 TARGET 恒假→测试从未注册）、公共头迁移 `include/pwb/viz/`、QString 显式 include、消费程序示例；WLE 唯一构建：install tree + MANIFEST（f845e7ab/Qt6.11.2/GCC16.2/glibc2.44/Release） | `ctest -N` 含 `science.viewer.well_log`（5 测试注册）；实测编译暴露并修复 4 处引擎 API 不匹配（DepthDomain::time 不存在、grab()→grabFramebuffer、单位 M→m 规范化、WellLog::IO 链接） | 通过 | viewer 实测 |
| 4 | viewer 测试扩展：PNG 导出、Unicode 路径、缺失/损坏/空 LAS 负例（旧文档保留）、原地重载、20×加载/显示/关闭（真实 GL）；TEXT=ON 重建 SDK 复验；负例×3 fail-closed 实测；前置校验重排（错误信息归因）= `a39b6281` | 5/5 绿 ×2；像素级可见检查（蓝/红曲线=adapter 调色板、覆盖全部 750 行；标尺文字缺失如实记录）；消费程序 install-tree 与源码两路径 exit 0（840×1200 PNG） | 通过 | 收尾 |
| 5 | 文档收尾：v3-verification（实测命令/退出码/图像/偏差：Linux 环境、无 pwsh 门禁、Windows/MSVC/Qt6.8 未验证）、v3-handoff（A/D/E 消费指南、WLE 配方、已知边界）、本账本 | 文档齐 4 件（contracts/verification/handoff/ledger） | 通过 | 提交收口 |

## 未完成 / 移交项（如实）

- Windows/MSVC/Qt6.8.0 构建与 B 入库端到端：A 线（v3-handoff §1）。
- 引擎视图深度标尺/文字标注：WLE 呈现 spec 演进项（v3-handoff §4.1）。
- `Invoke-ResourceGate.ps1` 在本机不可执行（无 pwsh）：单任务串行 + 内存实测代替；
  多任务并行的 Windows 宿主仍须走原门禁。
