# SDR：工作站壳层以编图为核心（取消文档 Tab 层）

- 日期：2026-09-04
- 状态：待用户确认
- 范围：`WorkstationFrame` 信息架构。不改编图画布内部的 QGIS 工具链（M1–M5 已交付）。
- 触发：用户截图标出文档 Tab +「剖面 / 链接」上下文条，判定这一层没有必要。

## 1. 问题

当前中央区叠了**两层文档壳**，显示同一组视图：

| 层 | 控件 | 内容 |
|---|---|---|
| 文档 Tab（`QTabBar`） | 井震联合剖面 / 平面图 / 井轨道 / 项目工作流 / 综合编修 | 切 `QStackedWidget` |
| 井震联合内部 | 上下文条「剖面 / 平面 / 井轨道 / 链接」+ **嵌套** `QMainWindow` 三 dock | 地震剖面、平面图、测井轨道 |

后果：

1. 「平面图」Tab 只是把联动工作区里的地图窗格最大化；「综合编修」又是另一张 QGIS 编图画布。两张地图。
2. 「井轨道」「井震联合」Tab 与内部 dock 重复。点 Tab 并不打开新文档，只是切换同三个窗格的最大化状态。
3. 「项目工作流」把 Hub 页（数据管理 / 测井预测 / …）塞进中央，把编图挤走。
4. 空工程仍显示硬编码标题 `A12 - D63`，像打开了真实文档。

用户要求：只用一个编图做核心；井道图、地震图是 dock panel；特定动作才打开这些窗口。

## 2. 术语（本 SDR 锁定）

| 用户用语 | 本 SDR 的意思 | 今日代码 |
|---|---|---|
| **编图** | 中央永不替换的地质图件画布（数字化 / 符号 / 图层树） | `CompositeDocument` + `QgisCanvasShim`。UI 文案「综合编修」改为「编图」 |
| **测井轨道** | 按需打开的井曲线 dock | `LinkedInterpretationWorkspace.well_pane` 升到宿主 `QMainWindow` |
| **地震剖面** | 按需打开的剖面 dock | `linked_workspace.seismic_pane` 同样升级 |
| **成图排版** | 图框/图例/比例尺排版，不是中央编图 | `MappingPage` / `MapEditView`。本切片不改内部，只规定它不得占用文档 Tab |
| **Hub 页** | 数据管理、测井预测、地震预测、3D、成图审核等 | `page_stack` + `navigation.py` |

若用户说的「编图」其实是 `MappingPage` 成图排版而不是 QGIS 综合编修，本 SDR 第 4 节方案要整段重选。默认按地质图件数字化理解。

## 3. 方案对比

### 方案 A（推荐）：中央固定编图 + 宿主级视图 Dock

- 删除 `document_tabs`。
- `WorkstationFrame` 中央永远是编图（`CompositeDocument`）。
- 地震剖面、测井轨道升为**宿主** `QDockWidget`（与资源管理器、图层管理同级），默认隐藏。
- 动作打开对应 dock 并 `raise_()`，编图不离开中央。
- 去掉联动工作区里的嵌套 `QMainWindow` 和「平面图」窗格（编图已含工区井位 + 编修层）。
- 「链接」成为编图与已打开视图 dock 之间的选择同步开关，挂在编图工具条，不单独占一层上下文条。

优点：与用户原话 1:1；Qt dock 语义已存在；消灭双地图。  
缺点：Hub 页若仍走 `activate_legacy` 会再次盖住编图，必须一并改路由。

### 方案 B：保留一个文档 Tab，仅编图 / 井震联合两个文档

优点：改动面小。  
缺点：用户点名的「这一层」还在；双地图仍在。

### 方案 C：中央仍是三窗格分屏，只删 Tab，用「窗格」菜单

优点：最少代码。  
缺点：空工程仍占满三块空态；编图不是核心，只是其中一块。

**采用 A。**

## 4. 目标布局

```
┌─ App bar（工程名 / Ctrl+K / Agent）─────────────────────────────────┐
│ 资源管理器 │                 编图（中央，永不替换）        │ 图层管理 │
│ Activity   │                 QgsMapCanvas                  │ 检查器   │
│ Rail+树    │                                               │         │
│            │                                               │         │
│            ├────────── 测井轨道（动作打开，可关）──────────┤         │
│            ├────────── 地震剖面（动作打开，可关）──────────┤         │
│            └────────── Agent / 任务（动作打开）────────────┘         │
└──────────────────────────────────────────────────────────────────────┘
```

默认可见：资源管理器 + 编图 + 图层管理。  
默认隐藏：测井轨道、地震剖面、检查器（窄屏规则可保留）、Agent、任务中心、输入与结果、联动视图。

浮动 / 停靠 / 叠 Tab / 关闭后从「面板」菜单重开：沿用现有 `QMainWindow` dock 设施，**不再**给联动视图单独做一套嵌套 MainWindow。

## 5. 打开窗口的动作（权威表）

动作只 `show` + `raise_` 已有 dock，不新建文档、不切中央栈。

| 动作 | 打开 |
|---|---|
| 资源树双击井 / Agent「打开井 A12」/ 编图单击井位 | 测井轨道（定位到该井） |
| 资源树双击地震 / Agent「显示剖面」 | 地震剖面（加载该体） |
| 资源树双击用户矢量图层 | 编图选中该层（已在中央，只选中） |
| 编图工具条「测井轨道」开关 | 显隐测井轨道 dock |
| 编图工具条「地震剖面」开关 | 显隐地震剖面 dock |
| App bar Agent / 任务 | 底部对应 dock（现状保留） |
| Activity rail「数据」等 | **P1 不进中央**。P1：只展开资源树对应视图。P2：Hub 页改为独立 dock 或模态工作区 |

「链接」勾选：编图选择井 ↔ 测井轨道当前井 ↔ 地震剖面过井线。关闭则各视图独立。状态权威仍是既有 `SelectionContext` / coordination，不新建总线。

## 6. 中央栈怎么改

今日 `document_stack` 三页：`linked_workspace` / `composite` / `page_stack`。

P1：

- 中央只留 `composite`。
- `LinkedInterpretationWorkspace` 不再是一页文档。拆出 `seismic_panel` / `well_panel` 的内容部件，交给宿主 dock；类可缩成协调器（ensure_views / open_well / 链接开关），或把协调函数挪到 `WorkstationFrame`。
- `page_stack`（Hub）P1 不再调用 `activate_legacy` 替换中央。导航信号改为打开对应 dock（若该 Hub 尚无 dock，P1 允许弹已有页面于**浮动 dock**，标题用 Hub 名，关闭即回编图）。禁止再出现「项目工作流」Tab。

硬编码 Tab 文案 `井震联合剖面: A12 - D63` 删除。Dock 标题用当前对象：`测井轨道 · {well}`、`地震剖面 · {survey}`；未加载时 `测井轨道`、`地震剖面`。

## 7. 与 M1–M5 编图画布的关系

- 编图中央仍是 `QgisCanvasShim`。图层树、属性对话框、原生采点/捕捉/undo、`map_qgis_project_xml` 不动。
- 编图已含工区底图 + 参考层 + 用户矢量，因此联动工作区里的「平面图」窗格删除，避免第二张 `QgisDisplayCanvas`/`UnifiedMapCanvas`。
- 首页 / 工区图预览（M4 只读画布）仍是**非工作站中央**的页面，本 SDR 不改。

## 8. 非目标（本切片不做）

- 把 `MappingPage`/`MapEditView` 换成 QGIS 原生制图工具。
- 重做 Activity rail 图标信息架构。
- 3D 地质建模页内部。
- 退役 `VectorEditSession`。
- 把测井预测 / 地震预测算法页重写成新模块（只改它们出现的壳）。

## 9. 文件地图（实施时）

| 路径 | 变化 |
|---|---|
| `paleo_workbench/ui/workstation/shell.py` | 删除 `document_tabs` 与 TAB_*；中央只 embed `composite`；宿主增加 `well_dock` / `seismic_dock`；动作表 |
| `paleo_workbench/ui/workstation/linked_workspace.py` | 去掉嵌套 MainWindow、map pane、context bar；内容部件可被 shell 抽走 |
| `paleo_workbench/ui/layout_presets.py` | preset 不再含 `document_tab`；改为 dock 显隐矩阵 |
| `paleo_workbench/ui/app_shell.py` | `activate_legacy` 改为打开浮动 Hub dock，不切中央 |
| `paleo_workbench/ui/workstation/composite_document.py` | 工具条增加「测井轨道 / 地震剖面」显隐；「链接」开关 |
| 测试 | `test_workstation_shell.py` 等：无 TabBar；默认中央是 composite；打开井只 raise well dock |

## 10. 验收

1. 启动后中央是编图，没有文档 Tab，没有「剖面 / 链接」那一条独立上下文条。
2. 空工程不出现 `A12 - D63` 伪文档标题。
3. 双击井 → 测井轨道 dock 出现，编图仍在中央。
4. 双击地震 → 地震剖面 dock 出现，编图仍在中央。
5. 关掉这两个 dock 后，编图与图层树仍可用；「面板」菜单能再打开。
6. 综合编修既有测试（图层树 / 采点 / XML）不因壳层改动变红。
7. Hub 导航不再把编图换成「项目工作流」整页。

## 11. 切片

- **P1（本 SDR 实施范围）：** 删文档 Tab；中央编图；测井/地震升宿主 dock；动作表；Hub 不盖中央。
- **P2：** Hub 页各自稳定 dock（数据管理、测井预测、3D、成图排版），而不是一个共用浮动窗。

## 12. 风险

- `saveState`/`restoreState` 的 objectName 会变，旧 `layout/windowState` 可能错位。P1 升 `WorkstationV3` settings 键或 bump 后忽略旧几何一次。
- Agent `focus_joint` / `open_well` 必须改走动作表，不能再 `setCurrentIndex(TAB_JOINT)`。
- 测试里大量 `document_tabs` 断言要改成 dock 可见性。
