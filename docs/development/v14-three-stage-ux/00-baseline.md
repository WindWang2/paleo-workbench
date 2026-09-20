# 00 — Baseline（V14-THREE-STAGE-UX 执行时基线）

- 执行日期：2026-09-20
- 基线 SHA：`412d8baf22a6a928c860e2e3d6c1108a9c035c78`（= 当时 `origin/main`，与 Prompt 快照一致）
- Worktree：`../paleo-workbench-v14-three-stage-ux`，分支 `feat/v14-three-stage-workbench-ux`
- 当时 open PR：仅 **#1434**（详见 01-overlap-audit.md）
- 当时 open issues：#1339–#1345 / #1357 / #1358 / #1385 / #1388 / #1392 / #1427–#1431（全部由 #1434 承接）

## 基线上的 C++ 产品形态（审计实证）

外壳三层嵌套：`MainWindow(QMainWindow)` → `AppShell` → `WorkstationFrame(内嵌 QMainWindow dock host)`
→ 中央 `CompositeDocument` + 14 描述符 dock + 「功能页」dock 内 `AdaptivePageStack`（5 个 hub：
数据/井/地震/编图/可视化，全部急切构造，`libs/ui_shell/src/navigation.cpp:11-38`）。

### 与本线直接相关的基线事实（file:line 见 02-architecture.md 引用表）

1. **阶段权威已存在且与三阶段逐字对应**：`pwb::tool_policy::MappingStage`
   （`facies_calibration / constraint_factor / integrated_compilation`，中文标签
   「① 智能预测 / ② 约束与单因素 / ③ 综合编图」）。运行时权威 = `ProjectSession::mapping_stage_`
   （唯一产品写入口 `MainWindow::applyStageValue`）。
2. **`MappingStageBar` 是孤儿**：`CompositeDocument::stage_bar` 构造、信号已接
   （stage_requested/horizon_requested → CompositeDocument 信号），但从未 addWidget——用户不可见。
3. **命令面板是空壳**：`ui_shell::command_registry()` 有完整评估引擎（stage 白名单、write 门、
   谓词、disabled reason），但产品代码零注册——Ctrl+K 无命令。
4. **任务中心 dock 空转**：`WorkstationTaskCenter` 组件完整（snapshot/operation provider 注入缝），
   产品从未注入 → 永远空态；反馈面是各 job 独立的 QProgressDialog。
5. **SelectionBus/ViewCoordination 完整但未实例化**：`libs/ui_controllers` 的
   `SelectionBus + QtSelectionContext + ViewCoordinationController + ViewCoordinationCore`
   （井选择路由/回显抑制/节流/时深权威分级）产品零接线，且 `ui_controllers` 未链接进 pwb-platform。
6. **hub3 编图页数据断链**：`MappingPage::update_state` 产品无调用者（图层树/chrome/预览永远空）；
   `MapDocumentBank` 的 active_changed/document_saved/dirty_changed 悬空；`MapEditScene` 的
   选择/脏/拓扑/撤销信号无消费者；`MapEditToolbar` 已移植未安装。
7. **stage 不随工程恢复**：`ProjectSession.mapping_stage_` 内存值；工程文档
   `mapping_workspace.current_stage` 有 codec 但主窗口不回读。
8. **状态组件未主题化**：`Pwb*` 状态组件（Empty/Error/Loading/Progress/Badge）objectName 词汇表
   存在，但 C++ `build_platform_qss` 不含任何 `Pwb*` 选择器。
9. **窗口布局双写**：`WorkbenchLayout`（WorkstationCpp 身份）与 `platform_services`（Workstation
   身份）各存一份。

## 构建环境（本机 Windows）

- MSVC 14.38 + Windows SDK 10.0.22621 + VS 自带 cmake 3.27.2 + ninja；Qt 6.8.0（`C:/deps/Qt`）；
  QGIS 4.2 vendored SDK 只读复用主仓 `native/qgis_render_bridge/build/qgis-vendor/output`。
- 资源门：POSIX 版在 Git Bash exit 77（无 flock），必须走 `Invoke-ResourceGate.ps1`。
- 本机内存常态：31.2 GiB 总量、空闲仅 1.3–2.8 GiB（桌面应用占用），commit 余量 47.5 GiB、
  pagefile 93 GiB（用 8.9）。资源门默认 8 GiB 物理内存门无法通过；经脚本自带 `-MinFreeGiB`
  参数调至 1（不绕过 flock 互斥锁），全程 `-j2`。
