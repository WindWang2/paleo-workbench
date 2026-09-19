> 当前状态以末尾 F06 / D04（20:53）为准；此前内容保留观察历史。

# Findings — C++ 收尾事实、决策与风险

> 最后外部核对：2026-09-19 16:11 +08:00。此文件保存证据和决策，不把预期写成事实。
> 工作项/阶段见 [task_plan.md](task_plan.md)；执行历史见 [progress.md](progress.md)。

## F01 基线与状态

- GitHub main：`7290f72728c0b6ff04c33a573cb0e964e3b5ff58`，commit 时间 2026-09-19 07:13:43 UTC。
- 本地主工作区 HEAD：`ff67dcf3`；此前 fetch 已更新 origin/main，相差 130 个可达提交。
  没有 merge/checkout，现存 composite_document.py 用户修改未动。
- 迁移批次 #1311 起共 59 个 PR，58 merged、1 open；范围不是仓库全部历史 PR。
- 唯一 open PR #1378：head `c60e273ca2de1343ef26fabe637c8905d5130e02`，mergeable=CONFLICTING。
  是已有实现待集成，不是缺少 RunEngine/store/receipt 的开发。
- #1380–#1392 共 13 个 issue 仍 OPEN；OPEN 不等于本轮已复现所有问题。
- [完整评估与全部迁移 PR](../cpp-status-2026-09-19-7290f727.md)。

## F02 不应重复开发的实现

| 已有实现 | PR 证据 | 仍需区分 |
|---|---|---|
| 原生组合根/自检/部署骨架、平台服务 | #1353/#1367 | 默认入口未切换、完整发行待验 |
| 工程/导入/生命周期与 catalog 域核 | #1346/#1370 | 深层 catalog 31b 仍有净差量 |
| 工作流 freshness/recompute/provenance | #1348 | 主程序真实消费未闭合 |
| RunEngine/store/receipt/解释域 | #1378 open | 冲突、标准 CMake 验收与调用适配 |
| 真实 ONNX、tiled runtime | #1349 | UI/catalog/map 消费、CUDA与格式互通 |
| 10 类科学服务 | #1352 | 生产源/发布 adapter，不能只测 InMemory/Directory |
| 文档 EditSession、样式模板、Layout 导出 | #1363/#1364/#1361 | 完整组图编辑和业务控制器 |
| WLE 解析/host/轨道/导出 | #1359 | LAS preview 双轨、差距审计、真实 UI 接线 |
| Geo3D viewport/相机/拾取/剖切 | #1366 | 联合场景，不是再造基础 3D 栈 |
| tiled 地震 IO/cache/service/10 属性 | #1369 | 高级显示差量、并发与规模验收 |
| UI-01..09 的库/组件/worker | #1371..1377/#1379/#1394 | W5 接线、后续 UI-10..16 净范围 |
| 包处理、模型 adapter/provider SDK | #1360/#1365 | 部分格式、编排、动态能力与实际调用 |

PR 链接可从评估报告全表进入。后续认领时必须再读当前 diff/代码，不能仅靠本表摘要。

## F03 证据强度

- 历史 native-product 65/65、部署树自检 12/12：该分支/配置的证据，不是最新 main 全部模块通过。
- #1349 的 Windows runtime 737 checks：证明预测子系统验收，不是 Windows 全桌面验收。
- #1370/#1378 采用 g++ 直连验证；CMake 注册存在不等于真实 CMake/CTest 跑过。
- #1366 GL-less 通过不能证明真实 GL 像素路径。
- #1394 披露其他 UI suites 的 libodbc.so.2 环境问题，UI-09 自身通过不等于全部 UI 通过。
- 本轮规划没有编译、运行产品测试或修复代码。
- [产品能力表](https://github.com/WindWang2/paleo-workbench/blob/7290f727/cmake/PwbNativeProduct.cmake)
  与生成的迁移 inventory 有快照滞后；不能用旧“29 units”“UI Python-only”等数字算当前完成率。

## F04 风险与归属

| 风险/问题 | 跟踪入口 | 当前代码修复计划归属 | 解除条件 |
|---|---|---|---|
| store 并发写/假成功 | #1380/#1381 | C | 全共享写入口统一纪律，确定性交错回归 |
| 资产悬垂/variant/null | #1382/#1383 | E | 真实生命周期与全部分支回归 |
| 预测/表格热路径、解析/导出边界 | #1384..1386/#1388..1392 | R2（与对应模块协调） | 每个问题先复现，定量或语义验证 |
| 短写/磁盘满误报保存成功 | #1387 | A：轨道模板；R2：诊断报告 | 两子路径分别有失败注入 |
| WLE 数据/绘制双轨 | Geo-Viz V1/V2 | A | 采用既有 SDK 并关闭真实行为差距 |
| 主页面未接、空 engine seam | UI W5/P-A | E + U1/U2/S1 | 真数据/真服务主程序链 |
| 无真实 GL/双平台全验收 | V2/V4/G1 | 各线提供证据，G1 汇总 | 明确候选 SHA、环境、图像/日志 |
| 五 worktree 同时编译 | resource gate | 所有执行者 | 一个重型槽、jobs≤2、空闲内存≥8 GiB |

## D01 本次规划布局

仓库根目录 task_plan/findings/progress 记录的是 #1302 Python 工作台历史，
含“subagents≤3”“不重编 C++”等该旧任务约束。保留原文，只加当前入口。
当前 C++ 计划放在本目录，避免覆盖旧成果、混用约束或制造已开工假象。

## F05 本轮发现五份派发文件缺失

三文件链接检查首次发现 5 个无效目标：前序会话生成的
docs/development/cpp-geoviz-zcode-parallel 目录当前为空；仓库 docs 和已检查的任务目录
未找到同名文件。原内容曾在本对话中生成并检查成功，但移除/转移原因未确认。
不推断用户是否已经派发，也不未经判断恢复可能被用户移动/删除的文件。
计划新增 R0，取消失效超链接，保留文件名与范围；后续用实际存放位置或原会话内容恢复。
这是派发材料就绪缺口，不是引擎代码回退。

没有找到可用的 planning-with-files 独立 SKILL.md；采用项目现有三文件工作方式，
不宣称调用/安装了该技能。goal-loop 是已读到的仓库技能，五份 prompt 已引用，
本次仅完善协调文件，不运行开发 goal-loop。

## D02 状态与完成定义

- 不给缺少验收分母的总体百分比；代码完成、merged、wired、verified 分列。
- 已在 PR 实现的内容从新增开发扣除，即使未合并。
- pending 任务只有实际认领/开工后才改 in_progress；prepared prompts 不等于已启动 ZCode。
- 关键外部依赖/硬件不足可阻塞验收，不能降格为“占位显示也算完成”。
- 规划完成不意味着系统完成；自动 PR 创建在开发 prompts 范围内，自动 merge/入口切换不在本次范围。

## D03 五线与全项目的关系

A–E 只承担 Geo-Viz 净差量与明示公共修复/P-A/P-B。它们不覆盖所有 catalog、
工作流/UI 控制器、交换/provider 与发布问题。额外以 R1/R2/D31/S1/U1/U2/U3/X1/G1
登记待认领工作，先做差量分析，不依据旧文件清单再移植一次。

## 待开发期间回答的问题

这些不是阻塞本次规划的用户问题，由认领代理先读代码/实验裁定并留证：
- WLE 与 geoviz renderer 的真实差距有多大？哪些仅需 adapter？
- P-A 的 presenter 如何复用现有 dispatcher 而不创建平行注册架构？
- C 的 store 序列化方案能否覆盖 GUI 提交、导入、属性发布且无死锁？
- 新 RunEngine 与现有 runtime/JobScheduler 如何划分职责，避免双执行器语义漂移？
- catalog 31b 哪些旧 Python 行为已由当前原生架构替代，哪些是真正缺失？
- UI-10..16 哪些行为被先前 PR 零散覆盖，哪些应 retired 而非再写？
- 最终默认能力集合、测试预算/soak 场景与目标部署平台如何形成明确清单？

新发现按 F05…追加，新决策按 D04…追加；更正历史结论时保留原观察时间与替代证据。


## F06 2026-09-19 20:53 增量核对（替代 F01 中的“当前”状态）

main=349a0ba8；迁移 PR 69 个，66 merged/3 open。#1378 已合并，
旧 CONFLICTING 描述只保留为历史。catalog 31b #1398 与 UI-10/11/12/14/15/16 已合并。
不再把这些已实现领域列成需要从头开发。UI-13 未见完整交付，UI-17 已定义为 W5 集成。

A=#1404、B=#1400、C=#1402 已由原任务提交，故前述“无法确认 A/B/C 派发”已经过时。
原 prompt 文件缺失不阻塞定位这三条执行线；D/E 仍需核对。B 查询时 CONFLICTING。
C 已提交 #1380/#1381 及 #1399 修复，但 issues 均 OPEN；不能在主线记为已关闭。

新证据：C 有 Mesa llvmpipe 真实软件 GL 截图；全树 109/111，受影响 64×2。
A 有 LAS 三路一致与专用 viewer gate；B 有 6 项×2 和真实 dock，
但完整 app 曾被 #1399 阻断、LAS 需 A 合流。以上都是 PR 声明，本轮未重跑。

[本轮详细报告](../cpp-status-2026-09-19-349a0ba8.md)。
主程序 apps 从上一文档提交到新基线无差异；UI 新库状态不能升级为已装配产品。
#1398 仍是 g++ 直连验证口径，标准 CMake 合流验收不能省略。

## D04 不把外部开发状态推断为本任务执行

规划跟踪外部 PR 即可将 A/B/C 标为 in_progress，但不能写成本代理启动了 ZCode。
不重复派发现有分支；D/E 未见 PR只表示提交状态未确认。
R1/D31、U1/U2/U3 的工作描述随已有实现收缩，完成标准仍要求真实消费与统一验证。
