# Ribbon 五工作区 UI 接入开发计划

日期：2026-09-22。状态：计划草案（待评审）。
上游依据：分支 `origin/codex/qt-ribbon-prototype`（提交 `bbe9acb6`）的原型与设计文档。

## 1. 背景与结论

用户决定：将 `codex/qt-ribbon-prototype` 分支中的界面原型采纳为本项目的正式 UI。

原型是独立 Qt 6 Widgets 程序（`prototypes/qt_ribbon_native/main.cpp`，296 行），展示五工作区 + 轻量 Ribbon 命令带：数据管理、1 智能预测、2 约束与单因素、3 综合编图、验证。全部数据为合成，任务为定时器模拟。其价值在于**信息架构、命令组织与交互纪律**，不在于任何科学实现。

**核心结论**：这次改造是"外壳重组"，不是"功能重写"。生产 C++ 端（`pwb-platform`）已具备命令注册表、命令面板（Ctrl+K）、快捷键注册表、JobCenter 任务运行时、dock 体系、主题 token、选井/层位联动总线、三阶段（stage）权威模型——且三个 stage 的中文名与原型中间三个工作区**完全一致**。真正缺失的只有四块：

1. Ribbon 命令带组件本体（分组命令带、折叠/紧凑/标准三模式、上下文组）。
2. 五工作区 ↔ hub×子模块 ↔ stage 的映射层与中央区重组。
3. 验证工作区的两处功能缺口：解释 vs 预测对比视图、问题级人工复核状态机。
4. 综合编图的版式（纸张/图框/比例尺）轻量控件、单因素参考缩略图带。

改造只在 C++ 端进行。Python UI（`paleo_workbench/ui/`）是冻结产品，按 cpp-conversion-main-plan 的 M12 退役路线，本次不触碰（v14-three-stage-ux/02-architecture.md:103 明令"Python 生产路径零新增"）。

## 2. 现状分析

### 2.1 权威文档顺序

`qt-ribbon-workspaces-2026-09-21/README.md`（R，外壳/Ribbon 层）> `qt-five-workspaces-2026-09-21/README.md`（F，科学视图/行为/令牌）> `workstation-v3-spec.md` / `audit-and-ia.md`（旧代，仅未冲突条款有效：OpenGL 惰性创建、五态语义、三主题机制、状态栏 CRS/坐标契约等）。

### 2.2 生产外壳现状

```
MainWindow (QMainWindow)
├─ 菜单栏 8 菜单 + "地图工具"工具栏（main_window.cpp:825-1007）
├─ statusBar：status_label_ + cursor_label_ + AppShell::StatusBar
└─ central = AppShell
   ├─ WorkstationFrame（内部 QMainWindow dock 宿主，14 dock）
   │  ├─ 顶行：WorkstationAppBar + mount_top_bar(MappingStageBar ①②③+层位)
   │  ├─ central = CompositeDocument（QGIS 画布 + 全套编图 dock）
   │  └─ "hub" dock = AdaptivePageStack(5 hub)，默认隐藏
   └─ CommandPalette(Ctrl+K) 基于进程级 CommandRegistry
```

两条正交切换轴：**hub 导航**（数据/井/地震/编图/可视化 5 hub × 子模块，`libs/ui_shell/src/navigation.cpp:8-58`）与 **stage 阶段**（facies_calibration / constraint_factor / integrated_compilation，权威在 `ProjectSession::mapping_stage()`，唯一写入口 `MainWindow::applyStageValue`，main_window.cpp:3407-3431）。

### 2.3 原型五工作区 ← 生产组件映射

| 原型区域 | 生产对应 | 结论 |
|---|---|---|
| 数据管理：资源树+资产表+预览+导入 | NavigationTree/DataWorkspace/DataAssetTable/DataReaderPanel/IngestPlanDialog | ✅ 基本可直接复用 |
| 智能预测：主图+地震+测井三联+联动 | CompositeDocument 画布 + LinkedWorkspace（linked_workspace.hpp，已是"主图+测井+地震+联动"协调器）+ SeismicSliceWidget + WellLogCanvasPanel | 🔧 需组版 |
| 约束与单因素：主图+连井剖面+计算 | stage② + PreparationPage + factor_prepare_production（constrained_idw/idw/kriging 真核）+ VizBCrossWellDock + ConstraintPanel | 🔧 需组版 |
| 综合编图：主成果+参考带+版式 | CompositeDocument + MapFactorShelf/FactorPreviewGrid + CompositionPanel；版式控件缺 UI | 🔧 参考带需横向化；版式页 ❌ 需新建 |
| 验证：对照+问题列表+复核 | QcIssueTable + InteractiveQCHub + review_qc_core（16 条真规则）+ run_map_qc/导出报告 | 问题列表 ✅；解释vs预测对比视图 ❌；问题级复核状态机 ❌ |
| Ribbon 命令带本体 | 无（最近者：WorkstationAppBar、MappingStageBar） | ❌ 需新建 |
| command() 注册 + Ctrl+K 搜索 | CommandRegistry/CommandPalette/ShortcutRegistry | ✅ 强于原型 |
| 任务进度/取消/防重复 | JobCenter + WorkstationTaskCenter + run 守卫 | ✅ |
| 选井/层位/深度游标联动 | SelectionBus/ViewCoordinationCore/CoordinateHubApi | ✅ 远强于原型 |
| 主题/图标 | ThemeService + theme_tokens + icon_factory（SVG 重染） | 🔧 需补设计稿线性图标资产 |

### 2.4 原型与生产的两处行为冲突（以生产为准）

1. **层位**：原型每图一条 horizon tab；生产是全局单一 `target_horizon`（stage_flow_install.cpp:303-336）。设计规范 I1/I2 也要求单一来源——**采生产模型**，horizon 标签条是同一状态的视图。
2. **导入**：原型"只登记元信息不解析"；生产是真实两段式 ingest（扫描→计划→校验→确认执行）。**采生产模型**，原型语义仅对应其中的"计划/确认"步骤。

## 3. 关键架构决策

- **D1 五工作区标签 = Ribbon 标签，且中间三个标签就是三个 stage。** 阶段权威仍是 `ProjectSession::mapping_stage`，标签是其视图；切到数据管理/验证不改写 stage（满足 F:25），切到 1/2/3 即 `applyStageValue`。MappingStageBar 的 ①②③ 段退役为 Ribbon 标签，层位下拉迁到状态栏（G2），避免第二份阶段状态。
- **D2 中央区改为 QStackedWidget**：数据管理页（DataWorkspace）、科学宿主页（CompositeDocument，工作区 1/2/3 共享同一 QGIS 画布权威）、验证页。科学宿主页的底部面板随 stage 切换：① LinkedWorkspace 三联（地震+测井）→ ② VizBCrossWellDock 连井剖面 → ③ 单因素参考缩略图带。这复用现有 StageLayoutProfile 投影机制（stage_flow_install.cpp:182-225）。
- **D3 新建 `libs/ui_ribbon` 库**（不在 ui_workstation 内扩展）：仿 ui_stageflow/ui_controllers 惯例——Qt-free core（工作区模型、命令组表、折叠/紧凑状态机）+ `pwb_ui_ribbon_qt`（Ribbon 控件）。根 CMakeLists 加 `# BEGIN UI-18` TARGET 门控块；app 接线走根文件后置块 + `ribbon_install.cpp`（与 stage_flow_install.cpp 同构）。不新增 `option()`（CMakeLists.txt:513-532 既定规则）。
- **D4 命令唯一来源**：Ribbon 按钮只承载既有 governed QAction（`main_window.hpp` ToolActionSet）与 CommandRegistry 注册的命令；禁止平行 QAction。菜单栏按 R:20 收敛到文件菜单 + 命令搜索，**保留全部既有快捷键**。
- **D5 验证工作区新建组合页**：画布（只读 DisplayMapCanvas）+ 地震剖面 + QcIssueTable/InteractiveQCHub + 新建"解释 vs 预测对比视图"与"问题级复核面板"。复核语义：已复核 ≠ 检查通过，必须填理由，版本变化时旧报告标记已过期（F:72-80）。
- **D6 生产多余功能的归属**：HomePage 项目概述 → 数据管理页首 tab 或文件菜单入口；井震联合 3D → 验证/智能预测的可选 dock；层序格架/地层对比 → 约束与单因素工作区内的 tab（地层对比并入连井剖面宿主）；可视化 hub → 降级为数据管理预览能力；Agent/任务/日志/console → 可收起 dock 保持现状。
- **D7 布局/偏好持久化统一** `(PaleoWorkbench, Workstation)` QSettings 命名空间，新开 ribbon 键；原型的 `PaleoWorkbenchPrototype/RibbonQt` 命名空间与 JSON 状态文件格式均不引入生产。

## 4. 分阶段计划

### M0 准备与基线（0.5 周）

- 将原型分支的设计文档与原型代码合入 main（`git merge origin/codex/qt-ribbon-prototype` 或 cherry-pick `bbe9acb6`；原型目录独立、无冲突）。
- 确认基线：`build/native-product` 预构建二进制 `pwb-platform --self-check` 13/13 PASS（已实证）；`ctest -R '^platform\.'` 全绿。
- 本计划评审，冻结 D1-D7 决策。
- 验收：文档入库；基线测试记录。

### M1 `libs/ui_ribbon` 组件库（1.5 周）

目标：可独立测试的 Ribbon chrome，不碰 AppShell。

- Qt-free core：工作区枚举与注册表（五区固定顺序）、命令组表（workspace→groups→command id，数据驱动）、三模式状态机（标准 76–96px / 紧凑 40–48px / 折叠）、每区默认主动作声明、禁用原因通道（复用 CommandRegistry evaluate 的 fail-closed reason）。
- Qt 控件：RibbonBar（QTabBar 五标签 + QStackedWidget 命令带 + QToolButton 组 + 分隔线 + 组内溢出菜单）、折叠三入口（Ctrl+F1 / 双击活动标签 / 折叠钮）、紧凑模式、QAT 快捷访问区（保存/撤销/重做，行为随活动文档路由）。
- 与 CommandRegistry/ShortcutRegistry/icon_factory 绑定；Ctrl+F1 注册前跑 `shortcut_registry.conflicts()` 清零。
- 测试：`ui_ribbon.core_smoke`（状态机/组表）+ `ui_ribbon.qt_smoke`（offscreen：三模式尺寸落区间、溢出、禁用原因提示、键盘遍历）。
- 验收：三模式尺寸在 R:21-23 逻辑像素区间内；C3 禁止缩字；紧凑模式把次级动作收入组内菜单。

### M2 工作区映射层与中央区重组（2 周）

目标：五工作区成为顶层导航，替换 hub 轴。

- 新映射层（ui_ribbon core 或 ui_shell）：workspace ↔ (hub, submodule, stage) 对照表；`navigation.cpp` 的 5-hub 注册表重定义，`kHubCount` 及全部索引引用点同批改（workflow_install.cpp:1296/1311、stage_flow_install.cpp:166-174、workflow_controller.cpp:96-140、test_app_shell.cpp）。
- AppShell：中央改 QStackedWidget（D2）；`navigate_to`（app_shell.cpp:379-405）保持唯一导航实现但改为切工作区；`show_hub_page` 退役或改为工作区 raise；hub dock 内容迁入各工作区页。
- stage_flow_install：stage bar 从 mount_top_bar 退役；①②③ → Ribbon 标签（D1）；`command_seeds()` 的 nav.hub.*/stage.goto.* 重指向；StageLayoutProfile 扩展出"数据管理/验证"两区 profile（现为 3 阶段）。
- 快捷键重映射：1..5 → 五工作区；stage.goto 的 1/2/3 hint 与 nav 快捷键概念重叠处用 conflicts() 清零；HomePage 模块卡片旧序数 → legacy_page_to_hub 映射表重写。
- 测试：更新 platform.app_shell / platform.three_stage_flow / platform.ui_wiring 断言。
- 验收：五区切换状态保持（F:25）；数据管理/验证不改写 stage；返回原区恢复所选对象、缩放与面板；导航无第二入口（F:27）。

### M3 五工作区内容组版（2.5 周）

- **数据管理**：DataWorkspace 迁入中央；左资源树定型（二选一：NavigationTree vs WorkstationExplorer，建议 NavigationTree + 补"约束与单因素图/综合编图/回收站"节点）；属性/版本/来源右 dock 由 lineage_rows 组装版本历史页；ExplorerFacts/InspectorPayload 宿主适配器补上（现 widget 在、数据供给不在）。
- **智能预测**：科学宿主页 + LinkedWorkspace 三联底部（SeismicSliceWidget/WellLogCanvasPanel 嵌入）；右侧图层/参数/样式沿用 LayerManagerPanel + inspector 裁剪页签；联动走 SelectionBus/ViewCoordinationCore 既有总线。
- **约束与单因素**：PreparationPage 能力迁入科学宿主页布局；底部嵌入 VizBCrossWellDock 连井剖面（地层对比作为其 tab）；ConstraintPanel 约束列表 + 捕捉开关与画布控件同步（D6 单一状态）；FactorStatsDock 挂右侧。
- **综合编图**：CompositeDocument 完整形态；底部新建**单因素参考缩略图带**（FactorPreviewGrid 横向化 + 单选模型 + 缩略图缓存 + 大栅格防重复解析）；点击只切参考对象/详情，不替换主成果（F:68）。
- **验证**（新组合页）：DisplayMapCanvas（只读）+ SeismicSliceWidget 对照 + QcIssueTable + 复核面板；问题点击 → locate 同步视图（复用 InteractiveQCHub::locate_selected + pan_to_extent）；默认只开与当前问题相关视图。
- 验收：五区布局符合 F:15-19/R:39-43 契约；主图:底部 ≈ 65:35；1280×720 下右 dock 可折叠且不缩字。

### M4 命令带填充与菜单收敛（1.5 周）

- 按原型组结构（每区 4-5 组）填充五区命令组表，全部指向既有 QAction/CommandRegistry 命令：
  - 数据管理：数据导入/整理/质量检查/版本与关联/输出（主动作=导入数据）
  - 智能预测：输入与模型/预测运行/叠加对照/结果（主动作=运行预测）
  - 约束与单因素：约束编辑/插值计算/连井分析/等值线/结果（主动作=计算单因素）
  - 综合编图：相界编辑/参考图/图件整饰/版式/输出（主动作=导出图件）
  - 验证：对象与基准/联动对比/检查/复核/报告（主动作=运行验证）
- 菜单收敛：文件菜单迁入 Ribbon chrome 文件按钮（保留 MRU、全部快捷键）；"地图工具"工具栏动作分配到各工作区分组；test_ui_wiring 的 map-toolbar/≥13 治理动作契约同步重指向。
- 禁用原因：无工程/无图层/只读/任务忙时动作禁用并显示具体原因（D8）；取消仅在任务可取消时启用；运行中主动作防重复提交（接 JobCenter 状态）。
- 验收：动作与旧菜单等价（R:55）；同一 QAction 四处复用（Ribbon/菜单/快捷键/命令搜索）可审计；`self_check.cpp` checkUiShell 更新通过。

### M5 功能缺口补齐（2 周）

- **解释 vs 预测对比视图**（验证区）：新建对比组件（并排/叠加/差异三模式，语义同原型 compare plot）；数据源接 StratigraphyCorrelationPage 解释版本 + WellLogPredictionPage 预测成果；岩性与沉积相分别对照（K6）；深度 m 与双程时 ms 不经时深标定不联动（K5）。
- **问题级人工复核状态机**：扩展 review 域——状态词汇 通过/未通过/待复核/未执行/不适用/已过期；复核备注必填；已复核不改原检查结论；输入版本变化 → 旧报告保留并标记已过期 + 提示重跑；以 finalize_map_version 为签发底座，复核记录入报告导出。
- **版式轻量页**（综合编图）：纸张/图框/图例/比例尺控件，进入版式模式才显示；接 libs/layout_export 服务层；导出先确认内容/格式/分辨率并报告真实写入结果。
- **上下文 Ribbon 组**：选中约束线/标注/图例/地图框时在当前 Ribbon 内显示对应组，不新增顶层工作区、主按钮不大幅跳位（R:33）。
- 验收：复核纪律（F:78）逐条过；版式导出报告真实结果；上下文组进出不跳位。

### M6 验收与 QA 体系（1 周）

- **C++ 截图 harness**：移植原型 `--self-test --output` 模式为 CTest（offscreen 五区截图 + 1280 紧凑/1920 宽屏）；以 `libs/ui_visualqa` 的 Qt-free snapshot core 为种子，生成 Ribbon 视觉基线。
- **规范验收清单全过**（见 §5）；DPI 100/150/200% × 1280×720/1672×941/1920×1080 矩阵不裁切。
- 布局重开恢复（geometry + dock + Ribbon 模式，统一 QSettings）。
- 测试树全绿：`platform.*`、`ui_ribbon.*`、受影响断言更新完毕；Python 测试不动。
- 文档：更新 docs/ui-redesign 权威指针、navigation/stage 相关 AGENTS 或开发文档。

## 5. 验收规范清单（摘自 R/F，必须级）

- 层次：标题栏 → 文件菜单+五工作区标签 → Ribbon 命令带 → 图面层位标签 → 停靠区 → 任务/日志 → 状态栏（R:17）；五区固定顺序，标签即 Ribbon 标签（R:19、F:24）。
- 三模式：标准 76–96px / 紧凑 40–48px / 折叠仅标签行；Ctrl+F1+双击标签+折叠钮三入口；禁止缩字（R:21-23）。
- 每区唯一默认主动作；取消仅可取消时启用；主动作防重复提交（R:29）。
- 同一 QAction 四处复用；保存/撤销/重做 QAT 随活动文档路由；不丢任何旧快捷键（R:20,31）。
- 无工程/只读/忙禁用动作并给原因（R:33）；焦点可见、键盘可达、图标+文字+颜色三通道状态（R:49、F:44）。
- 层位下拉与标签同一 ProjectSession 状态；焦点不擅自改层位；批量跨层位显示"全部/多个"（R:35）。
- 任务/日志/Agent 为可收起 dock，默认不挤占科学视图；真实状态不显示假成功（F:29）。
- 令牌：Fusion 浅色；#F0F0F0/#FFFFFF/#CCD1D6/#25313D/#0078D4；正文 13–14px；图标统一尺寸风格，不用截图裁按钮（F:36-42、R:49）。
- 不为 Ribbon 挤掉完整连井剖面或单因素参考带（R:25）；主图:剖面 ≈ 65:35（F:46）。
- 复核≠通过、必填理由；缩略图不替换主成果；导入两段式确认；无提示不覆盖当前版本；m/ms 不经时深关系不联动（F:52-80）。
- 布局重开恢复；UI 偏好不写数据版本（R:55、F:93）。

## 6. 风险与注意事项

1. **hub 索引是 load-bearing 常量**：导航层重定义必须同批改完所有引用点（含测试），否则出现半迁移态。M2 建议单次提交完成切换 + 测试更新。
2. **测试契约会红**：platform.app_shell（kHubCount、hub dock 标题）、three_stage_flow（top_bar_mounted、stage.goto）、ui_wiring（map-toolbar、≥13 动作）——这些是预期内的断言迁移，不是回归。
3. **共享 QGIS 画布**是科学宿主页跨 stage 复用的前提，改动 central 结构时不得破坏 canvas 注入契约（AppShell::install_canvas）。
4. **原型代码不移植**：原型 main.cpp 全部合成数据与内联 QSS 均不进入生产；只参照其组结构与交互。设计图是概念稿不是实施真源（K2）。
5. **图标资产**：设计稿要求统一线性图标；现 icon_factory 支持 SVG 重染但资产未必齐，M1 期间盘点缺口。
6. 资源门/构建纪律：全程走 `scripts/cpp-migration/invoke-resource-gate.sh`，CTest offscreen 协议（tests/cpp/platform/CMakeLists.txt:63-79）；编译 main_window.cpp 的测试目标必须 `pwb_link_job_runtime()`。

---

## 7. 实施状态（M6 收尾，2026-09-22）

**总评：M0–M6 全部完成。** 五工作区方案已在 C++ 端（`pwb-platform`）落地；验收基线：全量 ctest 255 项 244 绿，11 项失败全部为同一先已存在的环境问题（libodbc.so.2 缺失导致二进制加载期失败，含任务书点名的 ui_shell.qt_widgets_smoke、ui_widgets.modelview、ui_widgets.widgets_smoke 及同族 8 个 lib 测试，均不进入测试逻辑、与本改造无关）；产品自检 13/13；视觉 harness `platform.ribbon_visual(+dpi15)` 111 项结构检查全过。另：`closure_science.core` 需环境变量 `PALEO_ONNXRUNTIME_LIBRARY` 指向本机 onnxruntime（/home/kevin/pwb-sdks/ort/...），设置后通过。

| 里程碑 | 状态 | 关键产物 |
|---|---|---|
| M0 | ✅ | 原型文档合流、基线记录 |
| M1 | ✅ | `libs/ui_ribbon`（core + RibbonBar 三模式/QAT/溢出/禁用原因通道） |
| M2 | ✅ | RibbonBar 挂载、`navigate_workspace` 导航权威、stage↔工作区双向同步（防回环）、层位下拉迁状态栏、hub 轴退役为路由 seam、布局持久化 `(PaleoWorkbench, Workstation) ribbon/*` |
| M3 | ✅ | 科学宿主 65:35 + 底部三页栈（ws1 井震两联 / ws2 连井剖面+数据制备 / ws3 单因素参考带，真栅格缩略图缓存）；验证页真实组合 |
| M4 | ✅ | 58 条命令全部注册（34 真实 + 24 当时禁用）；文件菜单做全（MRU 双挂）；地图工具工具栏退役（动作全保留）；D8 禁用原因通道接实时 session 快照 |
| M5-1 | ✅ | 解释 vs 预测对比视图（三模式、真实 payload、时深门 F:75）；复核状态机（六态/备注必填/复核≠通过/指纹过期/记录跨重跑保留/导出带复核段） |
| M5-2 | ✅ | 版式轻量页（模板 9 真清单/矢量预览/版式模式不替换画布）；上下文 Ribbon 组（R:33，布局稳定性测试断言） |
| M5-3 | ✅ | ws0 版本历史/来源关系页签（catalog 真实血缘）；7 条 data.* 命令（5 点亮 + 2 准确禁用）；hub 轴解散（页面全部住进工作区，viz 退役 D6，hub dock 收窄为编图工具） |
| M6 | ✅ | `platform.ribbon_visual` 截图 harness（evidence 入构建树，像素仅记录）；图标缺口闭合（dev 树资源根 + rb-opacity.svg）；DPI 1.5 结构断言 |

### 已知遗留（M6 验收逐项记录）

1. **hub dock 未整体拆除**：收窄为「编图工具」单页 dock（mapping_page/MapEditView 要素编辑宿主）。彻底拆除需把编辑场景并入 CompositeDocument——独立评估项。
2. **解释版本写入端未绑**：`StratigraphyCorrelationPage` 的 `save_draft` seam 无 C++ 宿主绑定（页面自身诚实提示）；对比视图数据通路已就绪，接入即有真数据。
3. **时深标定无数据源**：`verify.link` 联动门接入点为文档 `coordinate.time_depth_calibrations`，写入端未建，开关保持禁用 + 诚实原因（F:75）。
4. **菜单栏保留未全量收敛**（M4 决策）：Ribbon=高频+文件入口；菜单栏=低频+全部快捷键权威宿主；无命令丢失、无平行 QAction。后续路线：M6 之后按菜单逐条评估。
5. **仍禁用的命令（原因已写进注册，palette/ribbon tooltip 可见）**：
   `data.link_well`/`data.set_role`（无关联/角色写入后端）、`predict.select_well`/`model_params`/`params`/`link`（预测参数/联动面未建）、`factor.crosswell_path`/`link`（连井路径/联动无后端）、`verify.cancel`（QC 同步执行无可取消任务）、`verify.select_object`/`select_baseline`（由对比视图选择器承担，可改点亮聚焦命令）。
6. **多选批量视图**：血缘面板为单选（bus 单一权威），表格多选→bus 语义扩展留给后续。
7. **viz 页面对象**仍存活（closure_preview provider 绑定引用），UI 面已退役；最终清除待该绑定改挂数据读取面板。

### 验证入口

- 构建：`cmake -S . -B build/native-product` → 资源门 Build。
- 测试：`ctest -R '^platform\.|^ui_ribbon\.|^ui_stageflow\.|^closure_review\.|^ui_review\.'`；视觉 harness：`ctest -R platform.ribbon_visual`（evidence：`build/native-product/visual-evidence/ribbon/`）。
- 产品自检：`pwb-platform --self-check` 13/13。
