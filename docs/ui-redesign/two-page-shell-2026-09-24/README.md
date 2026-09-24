# Paleo Workbench：两页式 Ribbon 壳层

日期：2026-09-24。状态：**已实现（design authority，取代五工作区方案）**——在
[`../qt-ribbon-workspaces-2026-09-21/README.md`](../qt-ribbon-workspaces-2026-09-21/README.md)
的基础上收敛顶层信息架构。原五工作区中的三个科学阶段不再各占一个顶层
页签，而是降为「编图」页内的三个**模式**；地震/测井/Geo3D/预测/验证等
功能面板全部退役出界面（功能保留在库内，诚实缺席不伪造面板）。

## 顶层结构（恒定两层）

```
窗口标题栏
└─ RibbonBar（壳层 chrome，沿用 ui_ribbon，浅色主题）
   ├─ 导航行：[文件] [QAT 保存|撤销|重做] [数据管理] [编图]  ␣  [命令搜索][任务][折叠]
   └─ 命令带（随页签切换）：
       ├─ 数据管理带：数据导入 | 整理 | 质量检查 | 版本与关联 | 输出
       └─ 编图带：「编图模式」组(智能预测|单因素图|编图 互斥) + 阶段命令组
└─ AppShell 中央 = QStackedWidget（恰 2 页，无 WorkstationFrame）
└─ QStatusBar：坐标 · 比例尺 · CRS · 层位（沿用既有 StatusBar 组装）
```

## 两页

### 页 0 — 数据管理（`DataManagementPage`）

QSplitter 两栏：左「数据列表」（`QTreeView`），右「信息展示」（选中条目
的详情面板）。条目由宿主经 `set_entries(QVector<DataEntry>)` 注入
（`DataEntry{name, kind, location, detail}`）；工具行「刷新」信号让宿主
重读数据权威后回推。不做编图行为，进入本页**不写**映射阶段
（D1 不变式保留）。

### 页 1 — 编图（`QgisAuthoringPage`，搬 QGIS app 组成惯例）

页面本身是一个 `QMainWindow`——QGIS 的 dock 面板归「图窗」管，而不是
归外层壳层：

- 中央区 = `QgsMessageBar`（画布上缘消息条，无消息自隐）+ 会话
  `QgsMapCanvas`（`adopt_canvas` 收编，重复调用幂等）。
- dock 面板经 `adopt_dock(dock, area, tabify_with)` 收编进左右 dock 区；
  图层树（`QgsLayerTreeView`/`LayerTreePanel`）与 QGIS 数据浏览器
  （`QgsBrowserGuiModel`+`QgsBrowserTreeView`）按 QGIS 惯例在左栏
  tab 化。
- 功能面板（预测/约束/地震等）后续按需以同一 `adopt_dock` 入口收编
  ——页面只提供宿主框架，本轮不展示。

支持三种模式。模式即领域既有的 `MappingStage`：

| 模式 | MappingStage | 关注点 |
|---|---|---|
| 智能预测 | `FaciesCalibration` | 预测任务/两联对照/地震预测面板 |
| 单因素图 | `ConstraintFactor` | 约束/连井剖面/单因素参考带/等值线 |
| 编图 | `IntegratedCompilation` | 相界编辑/参考图/图件整饰/版式输出 |

- 模式切换控件：编图命令带首组「编图模式」三个互斥 Toggle 命令
  （`mode.predict` / `mode.factor` / `mode.author`），由宿主用一个
  exclusive `QActionGroup` 绑定（D4：与菜单/快捷键/命令搜索同一 QAction）。
- 模式切换写 `ProjectSession::mapping_stage`（唯一写路径：
  `stage_apply` seam → `MainWindow::applyStageValue`）；dock 投影与
  Ribbon 上下文随模式切换。
- **页面切换不写 stage**；外部写 stage（命令、恢复）时若当前在编图页，
  反向同步模式组高亮（原 `sync_workspace_for_stage` 语义保留，三个
  stage 现在都映射到编图页）。
- 「验证」及其余功能页（地震/测井/Geo3D/预测等）整体退役出界面：
  `AppShell` 对应访问器返回 `nullptr`、相关动作发状态栏诚实提示
  （如 `show_validation_dock()` →「验证界面未启用」），不伪造面板；
  功能代码仍留在 `libs/` 与安装器内供后续收编。

## QGIS 面板方案（搬运 qgis_gui / 移植 app 部件）

| 面板 | 来源 | 停靠 |
|---|---|---|
| 图层树 | `QgsLayerTreeView`/`LayerTreePanel`（已有） | 编图页左栏 |
| 数据浏览器 | `QgsBrowserGuiModel`+`QgsBrowserTreeView`（已有） | 编图页左栏（与图层 tab 化） |
| 画布 | 会话 `QgsMapCanvas`（已有，`adopt_canvas`） | 编图页中央 |
| 消息条 | `QgsMessageBar`（qgis_gui 部件） | 画布上缘 |
| 状态栏 | 坐标/比例尺/CRS/层位（已有 `StatusBar` 组装） | 窗口底 |
| 图层样式 / 处理工具箱 | `QgsLayerStylingWidget`/`QgsProcessingToolbox*`（后续按需 adopt_dock） | 右（未启用） |

编图页的 dock 由 `QgisAuthoringPage`（内嵌 QMainWindow）自管，不走
`WorkstationFrame`/`workstation_dock_registry()`——后者随壳层退役，
注册表保持与 Python oracle 的冻结 parity 不动。模式→Ribbon 上下文组
投影沿用 `sync_workspace_for_stage`/`apply_stage_composition` 机制。

## 命令与上下文（沿用原规则）

- 每区一个默认主动作：数据管理=导入数据；编图=导出图件。模式组是切换
  器，不算主动作。
- Ribbon/菜单/快捷键/命令搜索复用同一 QAction；命令带尾部保留层位
  选择器常驻槽。
- 无工程/无图层/任务忙时禁用动作并给出原因（`set_command_evaluator`）。

## 不变式

- Qt-free 域逻辑留 `libs/`；宿主接线留 `apps/`。
- `pwb-platform` 无 Python 静默回退；诚实缺席（退役面板→`nullptr`/状态
  栏提示，不伪造界面）。
- Ribbon/菜单/快捷键同一命令身份。
- QGIS 为工程/图层/版式权威；模式切换只是工具集与编辑目标的投影。

## 验收

- 顶层恰 2 个页签；编图页内恰 3 个互斥模式，模式与 stage 权威一致。
- 数据管理页为列表+信息展示；编图页中央为 QGIS 画布。
- 折叠/紧凑 Ribbon、Ctrl+F1、命令搜索、键盘可达保持可用。
- `--self-check` 全绿；`navigate_workspace`/`stage_apply` 语义经测试锁定。
