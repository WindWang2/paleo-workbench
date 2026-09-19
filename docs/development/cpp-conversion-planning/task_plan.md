# Task Plan — C++ 全面转换收尾

> 当前协调计划；旧根目录三文件的 Python 工作台记录仅作历史。
> 最后核对：2026-09-19 16:11 +08:00。
> main 基线：`7290f72728c0b6ff04c33a573cb0e964e3b5ff58`。
> 当前阶段：P0 基线与规划已整理；派发文件就绪检查 R0 待处理，P1 开发待认领。
> 本任务未派发 ZCode 作业，其他工具或用户自行派发的情况未确认。

## 目标与范围

以真实用户流程验收 C++ 产品：工程与资产 → 计算/编辑 → 发布/保存 → 显示 →
导出 → 重开恢复。已有实现（包括开放 PR）不重新开发；区分代码、合并、接线和验收。
本轮文档准备不等于开发完成，也不授权自动切换默认入口或自动合并 PR。

- 发现与证据：[findings.md](findings.md)
- 执行与验证：[progress.md](progress.md)
- 完整评估/59 个迁移 PR：[评估报告](../cpp-status-2026-09-19-7290f727.md)
- Geo-Viz 五份开发 prompt：前序会话已撰写，当前文件缺失，见 R0 和下方文件登记。
- 远端主计划：[cpp-conversion-main-plan](https://github.com/WindWang2/paleo-workbench/blob/7290f727/docs/development/cpp-conversion-main-plan.md)
- 远端 UI 分区：[UI taskbook](https://github.com/WindWang2/paleo-workbench/blob/7290f727/docs/development/cpp-ui-swarm/taskbook.md)

## 状态与事实源

执行状态只用：`pending`、`in_progress`、`blocked`、`complete`。
“blocked”必须有具体外部依赖与恢复条件，等待资源锁只是排队。
另维护交付状态：代码是否已有 / PR 是否 merged / 主程序是否 wired / 验收 SHA 与环境。
PR merged 不自动使工作项 complete；开放 PR 已有代码不回退为“待实现”。

GitHub 是 issue/PR 状态真源；本目录是规划、证据索引和执行快照。
状态更新必须记录查询时间。计划负责人是角色分配，不代表已实际启动代理。
五条线的协调任务由协调者维护本目录；开发代理只写自己 worktree 中的独占 ledger，
避免五个 PR 同时修改总计划。

## 阶段

| 阶段 | 状态 | 出口条件 |
|---|---|---|
| P0 基线与规划 | in_progress | 基线/净差量/本三文件已完成；R0 定位或恢复五份派发文件后关闭 |
| P1 正确性与接口 | pending | R1、R2、A/E 的关键前置修复有回归；跨线 API/所有权明确 |
| P2 功能与服务 | pending | A–E、D31、S1、X1 的各自用户流程通过；不重复现有内核 |
| P3 UI 与产品装配 | pending | U1/U2/U3 的净差量落地；W5 接线有真实数据和取消/重开验收 |
| P4 统一验收 | pending | 同一候选 SHA 的 Linux/Windows、GL、部署和关键回归矩阵合格 |
| P5 入口切换评审 | pending | 证据完整、兼容/回退方案明确，形成可审查决策；实际切换另行授权 |

P1–P3 可按各工作项依赖并行，不要求整个前一阶段结束后才开始。
代码准备可以先行；会触发已知内存/并发缺陷的用户链不能跳过前置修复验收。

## 可执行工作项

| ID / 计划负责人 | 净任务 | 状态 | 依赖与边界 | 完成证据 |
|---|---|---|---|---|
| R0 / 协调者 | 定位或按前序会话恢复五份 prompt，确认实际派发记录 | pending | 当前原目录为空；不把未知原因的文件移除自行当作需要回滚的改动 | 真实文件位置/内容校验、可用链接；有派发则记录执行者与 worktree |
| R1 / 工作流合流负责人，待认领 | #1378 解冲突、标准 CMake/CTest、旧新引擎消费关系 | pending | 复用已写的 RunEngine 等代码，不重写；合并需遵循仓库流程 | PR head/base、冲突解决、两遍核心回归、实际调用清单 |
| R2 / 正确性审查负责人，待认领 | #1384–#1392 剩余问题净审查与修复 | pending | 排除 C 所有 #1380/81、E 所有 #1382/83；#1387 轨道模板归 A，诊断报告归 R2 | 各 issue 可复现测试、修复 SHA、无损回归；不得仅凭标签判通过 |
| A / 测井线 | LAS/WLE bridge + 已确认绘制差量 + P-B viewer 专用门禁 | pending | 不重写 WLE；preview 总装配归 E；加载取消复用 worker；轨道模板短写归 A | 两路 LAS 一致、真实轨道与导出、viewer gate |
| B / 连井标定线 | 多井剖面、picks/tops 持久化、标定与报告 | pending | 复用 DTW/服务/现有 WLE，多井开发不空等 A；不重写已迁编辑器/对话框 | 编辑保存重开、标定 oracle、真实报告 |
| C / 联合 3D 线 | 联合场景/配准/fence/probe/时深转换 + #1380/#1381 | pending | 独占共享 store 并发修复，先提交独立修复 commit；复用 geo3d/tiled service | 确定性交错回归、联合场景、真实 GL + 降级 |
| D / 地震显示线 | VD/wiggle/horizon/crossplot、色表/stratal 净差量 | pending | 复用现有 IO/cache/job；store 发布依赖 C，纯只读显示可先开发 | 真实图像、层位编辑重开、数据/坐标对账 |
| E / 图表预览线 | charts/surface/factor 呈现 + P-A 数据/预览页装配 + #1382/#1383 | pending | 独占总预览 dispatcher 与资产生命周期修复；接 A/B/D 专用 presenter | 资产→加载→图表→导出真实 E2E、所有权回归 |
| D31 / 数据服务负责人，待认领 | catalog 31b 净差量：通用事务/DirtySet/CAS、深层服务/working-copy/lease 等 | pending | 先扣除 #1346/#1370；复用 C 的线程纪律，不能再建竞争写通路 | 错误注入、并发/恢复、兼容旧工程、真实 repository 验收 |
| S1 / 服务集成负责人，待认领 | 科学/预测/workflow 真实 catalog adapters、调用、发布与 UI 控制器连接 | pending | 复用 #1352/#1349/#1348/#1378；依据需要消费 R1/D31/C；与 UI-14 单一负责人协调 | 真工程输入→执行→版本/provenance→地图/页面→重开 |
| U1 / 业务页面负责人，待认领 | UI-10/11 净差量与 W5 业务页面接线 | pending | 图表归 E、连井/地震专用面归 B/D；先扣除 #1394 等已有壳 | 真实服务操作、状态/dirty/cancel/错误提示，不以控件构造算完成 |
| U2 / 工作站集成负责人，待认领 | UI-12..15 净差量、统一命令/文档/视图协调及 W5 总体合流 | pending | 不抢 A–E 的专用安装点；消费 S1；对公共 MainWindow 仅做可审查适配 | 命令→服务→视图闭环、工程切换、撤销/保存、无回环泄漏 |
| U3 / 验收工具负责人，待认领 | UI-16 迁移/退役裁决、截图/视觉验证与可追踪证据 | pending | Python QA 工具不必逐行重写；产品行为须被真实测试覆盖 | 能运行的视觉矩阵、声明容差、失败可定位 |
| X1 / 交换/provider 负责人，待认领 | 剩余格式 adapter、交付编排、provider 动态/生产调用净差量 | pending | 扣除 #1360/#1365；先裁定必需能力，复用 WLE/GDAL/QGIS | 包/格式读写回读、失败回滚、生产调用与能力报告一致 |
| G1 / 交付负责人，待认领 | 能力与迁移清单刷新、全功能配置、依赖部署、双平台/GL/soak | pending | 测试配置可先准备；最终验证须钉住合流候选 SHA | 见下方统一验收矩阵；历史 PR 测试不能拼成 main 全绿 |

A–E 的完整 prompt 已在前序会话撰写；本轮检查原目录为空，以下只是历史文件登记，
不是可用下载链接。**曾经 prepared 不等于当前文件可用，也不等于 dispatched**。

| 线 | 原文件名（原目录：docs/development/cpp-geoviz-zcode-parallel） | 当前状态 |
|---|---|---|
| A LAS/WLE | 01-zcode-welllog-convergence.md | 文件待定位/恢复 |
| B 连井/标定 | 02-zcode-crosswell-welltie.md | 文件待定位/恢复 |
| C 联合 3D | 03-zcode-joint3d.md | 文件待定位/恢复 |
| D 地震显示 | 04-zcode-seismic-display.md | 文件待定位/恢复 |
| E 图表/预览 | 05-zcode-charts-preview.md | 文件待定位/恢复 |

内容恢复依据为本对话前序完整 prompt；若用户已转交 ZCode，以实际工作任务/PR
登记为准，不重复派发。文件缺失原因尚未确定，本次没有回写这些可能被用户移走的文件。

## 并行与资源协议

1. 每项独立 worktree/分支，基于执行时最新 origin/main；禁止覆盖共享主工作区的用户修改。
2. A–E 的 subagent 数量/调用次数不设人为上限；同一文件只能有一个写入负责人。
3. 同机共享 Git common-dir 重型锁，configure/build/test/大型 oracle/渲染压测入同一队列。
   jobs≤2，可用内存≥8 GiB，BLAS/OMP 等为 1，链接/大内存/GL 串行。
4. 使用现有 resource gate；exit 75 退避，不能 Probe 后绕锁、另 clone 绕锁、
   删除活动锁或降低内存门限。SDK 只读复用，重编也须经过协调的同一重型锁。
5. C 的并发修复、E 的资产修复优先独立提交，供依赖者明确引用 SHA/PR；
   不各自复制补丁。新增跨线依赖登记后，以明确 stacked PR 或合流测试处理。
6. 公共 CMake/feature/capability/MainWindow 改动保持独立命名小块。
   A–E prompt 的文件归属优先；未来 S1/U2 不得同时改写这些块。
7. prompt 已授权开发代理 commit/push/create PR；本规划任务本身只完善文档，不启动开发、
   不提交外部消息、不自动合并或切换入口。

## 统一验收矩阵

| 门 | 必需内容 | 当前状态 |
|---|---|---|
| E0 来源与构建 | 候选 SHA、PR head/base、SDK/工具链、真实开关与调用链 | 待建立最终候选 |
| E1 语义 | 真 Python/WLE oracle、异常/NaN/单位/CRS、negative self-check | 分支级已有部分证据；全候选待验 |
| E2 生命周期 | 并发写、取消、迟到、关窗/换工程、失败不假成功、保存短写 | 已知问题待修复验收 |
| E3 主程序 | 真数据→服务→持久化→显示→导出→重开；无空 seam 冒充可用 | 基础流程已有；全功能待验 |
| E4 构建 | CMake ON/OFF、目标真正生成、CTest 非 0/non-skip；关键两遍 | 最新候选待验 |
| E5 环境 | Linux + Windows 完整产品；真实 GL 与 GL-less 分开 | 仅有部分历史证据 |
| E6 交付 | 干净部署运行时闭包、Python-free 原生链审计、soak/资源预算 | 开发部署骨架已有；正式候选待验 |
| E7 状态一致 | PR/ledger/能力表/迁移清单一致；未实现能力诚实显示 | 清单需刷新 |

## 下一次会话恢复

1. 读本文件、findings、progress；不要从旧根目录的 Python 约束恢复。
2. 查询远端 main、开放 PR/各工作项关联 issue；记录当前时间与 SHA，不覆盖历史证据。
3. 选择 pending 的无硬依赖任务，登记实际执行者、worktree、分支、范围后改 in_progress。
4. 先比对新 PR 是否已实现任务，缩减净范围，再执行。
5. 每个重要发现/决策进 findings，每轮实际执行/失败/验证进 progress；状态只在本计划改。
6. 结束前留下：已做、未做、下一条命令、阻塞与解除条件、PR/证据位置。

## 本次文档工作的完成条件

- [x] 三文件建立并有明确职责、基线和恢复步骤。
- [x] 五线范围/原文件名/就绪状态有登记，文件归属、公共修复和共享资源不冲突。
- [x] 明确五线之外的剩余工作，不把它们算进 Geo-Viz 已覆盖范围。
- [x] 开放 PR、审查债务、构建/GL 验收缺口可追踪。
- [x] 根目录历史保留并添加当前入口；内部链接检查通过。
- [ ] 五份 prompt 当前文件可用、实际派发情况已确认（R0，独立于本次三文件整理）。
- [ ] 开发执行和产品切换完成（这是后续目标，绝不能因规划完成打勾）。
