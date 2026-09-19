# Task Plan — C++ 全面转换收尾

> 当前协调计划，更新时间：2026-09-19 20:53 +08:00。
> 代码基线：`349a0ba8eb350218caca2f72115a7580b2510c0e`。
> 当前阶段：P1/P2/P3 并行推进；A/B/C 已有开放 PR，不能重复派发。
> 这是基于远端证据的协调状态，不表示本任务亲自运行了开发或产品测试。

## 目标、入口和状态规则

验收真实用户流程：工程与资产→计算/编辑→发布/保存→显示→导出→重开恢复。
已有代码（包括开放 PR）从新增开发范围扣除；merged 不等于 wired/verified。

- [最新评估](../cpp-status-2026-09-19-349a0ba8.md)
- [此前评估（历史）](../cpp-status-2026-09-19-7290f727.md)
- [事实与决策](findings.md)
- [执行日志](progress.md)
- [UI 任务书/UI-17](https://github.com/WindWang2/paleo-workbench/blob/349a0ba8/docs/development/cpp-ui-swarm/taskbook.md)

执行状态：pending / in_progress / blocked / complete；同时记录实现/合并/接线/验收四层。
GitHub 为 PR/issue 状态真源，表格为带时间的快照。
“执行负责人”是逻辑职责；已经存在的分支由原开发任务继续，不擅自接管。
协调者维护本目录，子代理只改自身 ledger，不让所有并行 PR 争写总计划。

## 最新变化：替代 16:11 快照

- #1378 已 merged：R1 不再解冲突或重写 RunEngine，转标准 CMake/消费者验收。
- #1398 已 merged：catalog 31b 已有深核实现，D31 改为验收/生产适配与已披露差量。
- UI-10/11/12/14/15/16 已合并；加上 UI-01..09，共 15/16 原编号切片有交付 PR。
  这不是 93.75% 产品完成率；UI-13 未见对应完整交付，UI-17 是新增接线任务。
- A=#1404、B=#1400、C=#1402 均 open，代码已存在；B 查询时 CONFLICTING。
- C 的 PR 已包含 #1380/#1381 修复和 #1399 编译问题修复声明，但未合入主线。
- D/E 尚未检索到对应新 PR，实际是否运行未知；先定位原任务，禁止盲目重复派发。

## 阶段

| 阶段 | 状态 | 出口 |
|---|---|---|
| P0 基线与执行记录 | in_progress | 本轮基线完成；R0 仍需确认 D/E 实际任务与材料位置 |
| P1 正确性/接口 | in_progress | C/E/审查修复合流验证；接口与所有权明确 |
| P2 可视化与服务 | in_progress | A–E 净功能、服务/交换差量在真实链路验收 |
| P3 UI 装配 | in_progress | UI-13 净差量与 UI-17 完成，真实生产服务注入 |
| P4 统一验收 | pending | 同一候选 SHA 的完整配置/双平台/GL/部署矩阵 |
| P5 入口切换评审 | pending | 能力/证据/兼容与回滚材料完备；实际切换另行授权 |

## 工作项与当前下一步

| ID | 状态 | 已有交付 / 归属 | 下一步与完成条件 |
|---|---|---|---|
| R0 执行登记 | in_progress | A/B/C 可由 PR 确认；原五份 prompt 目录缺失 | 定位 D/E 任务、worktree、head 和实际材料，不重新派发 A/B/C |
| R1 工作流合流 | in_progress | #1378 merged，RunEngine/store/receipt/解释域已实现 | 在标准 CMake 配置验证并消费新执行器；scheduler/cache-run catalog 剩余路径不得忽略 |
| R2 审查修复 | pending | #1380–#1392 全部仍 OPEN | #1384–#1392 净问题先复现后修；排除 C/E 所有修复；#1387 轨道模板归 A、诊断报告归 R2 |
| A 测井 | in_progress | [#1404](https://github.com/WindWang2/paleo-workbench/pull/1404)，codex/viz-a-welllog-convergence | 复核 LAS 三路桥接/专用门禁后合流；XML worker 未桥接、app 迟到守卫仅编译覆盖等需裁决 |
| B 连井/标定 | in_progress | [#1400](https://github.com/WindWang2/paleo-workbench/pull/1400)，codex/viz-b-crosswell-welltie | 解决冲突，接 A 的真实 LAS 通路；#1399 修复合流后验证完整 app，不重写已实现模型/标定/导出 |
| C 联合 3D | in_progress | [#1402](https://github.com/WindWang2/paleo-workbench/pull/1402)，codex/viz-c-joint3d | 审核锁/项目身份后合流；复验 #1380/#1381/#1399；GUI 冷 tile 读仍需异步化或明确验收裁决 |
| D 地震显示 | pending | 未见对应提交 PR；运行状态未确认 | 先定位原任务；仅补高级显示差量与当前属性注册断言过期问题 |
| E 图表/预览 | pending | 未见对应提交 PR；运行状态未确认 | 先定位原任务；charts + P-A + #1382/#1383，与 UI-17 划分总装配边界 |
| D31 catalog 验收 | in_progress | [#1398](https://github.com/WindWang2/paleo-workbench/pull/1398) 已合并 | 不再开发 DirtySet/CAS/WC/lease/模型注册；标准 CMake 回归、生产调用、Transaction::commit 错误传播遗留 |
| S1 服务消费 | pending | 预测/科学/workflow/catalog 实现均存在 | 真 catalog adapters→服务→版本/provenance→地图/UI；消费现有 UiControllers，不再写第二套控制器 |
| U1 业务页面接线 | pending | UI-10/11 已合并 #1396/#1395 | 绑定真实服务；PreparationPage 等 deferred 差量逐项裁决，进入 UI-17 |
| U2 工作站/控制器装配 | pending | UI-12/14/15 已合并 #1397/#1401/#1405 | UI-13 净差量仍需实现；其余集中到 UI-17，消费现有 shell/controller/canvas |
| U3 视觉验收 | pending | UI-16 已合并 #1403 | 不再移植 QA 框架；将 fake/unbound probe 切换成真实装配产品，保存截图和失败证据 |
| X1 交换/provider | pending | #1360/#1365 既有实现 | 格式/交付/动态加载/生产调用净差量，先裁定必要能力再实现 |
| G1 最终门禁 | pending | 构建/部署骨架已有 | 刷新能力清单，同 SHA 全功能 CMake/CTest、GL、双平台和部署/soak |

UI-17 属总体接线，不另开通用 UI 库。MainWindow/AppContext 修改由协调者划分：
E 负责数据/预览/图表；A/B/C/D 负责各自专用安装点；U2 负责全局导航/命令/文档/视图协调；
S1 负责生产服务适配。不能多人重写相同入口。

## 开放 PR 的验收边界

| PR/head（查询快照） | 已有证据（PR 声明，非本轮重跑） | 不能据此宣告完成 |
|---|---|---|
| A #1404 / 0d7c1e6f | 6 类测试，三路 LAS 一致、专用两遍门禁/ON-OFF | XML worker、真实 app 迟到路径；图案为声明近似 |
| B #1400 / fb1f6940 | 6 测试×2 + MALLOC，连井/标定/真实 dock | 整个 app 曾被 #1399 阻断；LAS 仍需 A 合流；当前合并冲突 |
| C #1402 / f41a222e | 64 受影响测试×2；Mesa llvmpipe 真实软件 GL 截图 | 全树 111 中 109 过，2 失败；硬件 GL 未测；冷 tile 在 GUI 读取 |

UNKNOWN mergeability 不等于可无冲突合并。PR 更新或 base 变化后重新查询并钉住验收 SHA。

## 公共缺陷与合流纪律

- C 独占 #1380/#1381：已有修复 PR，不再作为“待写实现”；合并和验证前仍是主线风险。
  特别复核导入开始/完成时工程切换的语义，不能只凭“加锁”视为数据身份安全。
- E 独占 #1382/#1383：仍 OPEN，未见其修复 PR，先确认 E 状态。
- #1399 已由 C 声明修复；主线 issue 仍 OPEN，B 的完整 app 验收依赖该修复。
- 不替用户关闭 issue，不自动 merge PR；文档中的“验收通过”要有真实日志，不引用 closes 文案作证。

## 资源与工作区

每项独立 worktree，已有任务沿自身分支继续；不覆盖用户主工作区修改。
A–E subagent 数量/调用次数不设人为上限，同文件独占写入。
共享 Git common-dir 重型锁，configure/build/test/大型 oracle/GL 压测统一入场；
jobs≤2、可用内存≥8 GiB、BLAS/OMP=1，链接/GL/大内存串行。
exit 75 退避，不 Probe 后绕锁、不删活动锁、不另 clone 绕锁，SDK 只读复用。
公共 CMake/capability/MainWindow 仅独立命名小块；生产链无 Python 回退伪装成功。

## 完成门

1. 每个能力分别证明 implemented / merged / wired / verified，按真实用户流程。
2. 真参考 oracle + negative self-check；关键回归两遍、CMake ON/OFF，非 0 tests/全 skip。
3. 并发写、项目切换、取消/迟到、短写/磁盘满、恢复重开都有失败路径验证。
4. 真实 GL 与降级分开；软件 GL 有效但不能冒充硬件路径验收。
5. 同一最终 SHA 的 Linux/Windows 产品配置、运行时部署、Python-free 原生入口审计及 soak。
6. 能力表/迁移清单/PR/ledger 一致；Python 默认入口切换另行评审。

## 恢复步骤

读本三文件→刷新 main/open PR/issue→核对已有实现→定位原执行任务→按净差量继续。
每轮发现写 findings、实际命令/结果写 progress、阶段/下一步写本文件。
本次只更新和发布规划，不运行开发测试，不把所有 in_progress 改为 complete。
