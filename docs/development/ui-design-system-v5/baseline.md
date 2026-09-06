# UI Design System V5 — Baseline（U0 审计结论）

Branch: `feat/ui-design-system-v5` · Baseline commit: `049423ab` (origin/main, 2026-09-06)

## 1. 现有架构（保留资产，不推翻）

- `paleo_workbench/tokens.py`（1575 行）：唯一 token 真源。`palette_for(theme)` 三主题
  （light/dark/high_contrast）同词汇表；`build_qss(density, theme)` 单一生产样式表，
  objectName 作用域规则；`DENSITY_TOKENS` compact/comfortable；语义别名
  （SURFACE/TEXT_MUTED 等 B1 词汇）已部分建立。
- `paleo_workbench/ui/theme.py`：`ThemeManager` 持有 theme+density 运行态，
  `theme_changed(theme, density)` 信号 + QSettings 持久化（org=PaleoWorkbench app=Workstation）。
- `paleo_workbench/ui/style.py`：`style.bind(widget, render)` 动态内联样式注册表，
  主题切换时 `repolish_all()`。**但全仓只有 2-3 个文件使用**。
- Shell：`PaleoWorkbenchWindow`（dock host）→ `AppShell` → `WorkstationFrame`
  （app bar + 12 个原生 QDockWidget + CompositeDocument 中央编图）。
- CommandPalette 已存在（`app_shell.py:65`，原生 child QFrame，360×320 固定尺寸），
  app bar 命令输入启发式路由；无中央快捷键注册表（QShortcut 散落 2 处）。
- 布局：6 个命名 preset（`layout_presets.py`）+ `QMainWindow.saveState` 持久化 +
  `LayoutPersistence` 面板级持久化；**无多显示器恢复校验**。
- 截图工具：`scripts/capture_workstation_screens.py`（12 状态 offscreen grab）
  + `scripts/visual_qa_composite.py`；无 diff/baseline 管理流程。

## 2. 债务清单（审计证据）

### 2.1 系统性：主题切换不刷新（最高优先级）
约 105 个文件以 f-string 内插 **light 值的模块常量**（`tokens.TEXT_PRIMARY` 等）
构建 `setStyleSheet`，构造时快照、永不刷新。运行时切 dark/high-contrast 后这些
控件仍是 light 配色。目前只有 `navigation_tree.py`、`table_preview_widget.py`
及 `style.bind` 用户（agent_panel、seismic_view_panel）随主题刷新。
`workstation/task_center.py:41-47` `_STATE_COLORS` 在 import 时定死；
`ui/status_bar.py`、`ui/page_placeholder.py` 同病。

### 2.2 裸 hex / 字面色（生产代码 12 处调用 / 8 文件）
- `viz/hosts/well_log_host.py:113,175` `#ffffff`；`:74` `color: white`
- `viz/hosts/well_section_host.py:40,110` `#ffffff`
- `ui/map_status_bar.py:89-90` `#ffffff` 条件字面量
- `ui/pages/geological_modeling_3d_page.py:510` `#b58900`、`:2639` `#c2410c/#fff7ed/#fed7aa`
- `ui/pages/visualization_page.py:172`、`ui/pages/seismic_slice_preview_widget.py:41` `#ffffff`
- `ui/pages/project_well_map_page.py:48-53` 7 个模块级 hex（`#409cff` 等）+ `:302`
  pyqtgraph 底色 `#f8fafc`（dark 不可用）
- `ui/pages/data_view_models.py:45-46` Element-UI 遗留 `#E6A23C/#409EFF`
- `ui/pages/lithology_crossplot_dialog.py:75-78`、`ai_check_advisor_dialog.py:38,63,66`、
  `module_relationship.py` `white`×7
- painter 层：`ui/unified_map_canvas.py`（144-194, 610-638 chrome/选区/snap 颜色）、
  `ui/qgis_stack/display_canvas.py:67` `#ffe066`、`workstation/composite_document.py:92-106,1123`、
  `workstation/composite_editing.py:209-248`
- `tokens.py:752-754` QSS 语法损坏：注释后有悬空 `; border-bottom … }}`（MenuBar 规则残片），
  可能导致后续规则解析偏移。

### 2.3 setStyleSheet 规模
254 处 / 58 文件。重灾区：`geological_modeling_3d_page.py`(43)、`module_relationship.py`(23)、
`inspector_panel.py`(14)、`data_detail_panel.py`(9)、`completeness_card.py`(9)。

### 2.4 重复组件（无 ui/components/ 包）
- SectionHeader：`QLabel`+`setObjectName("MapDockTitle")` 复制 **25+ 处**。
- Badge/pill 5 种实现：ModuleCardStatus×2、SeismicAttributeCardStatus、TagBadge、
  Joint2DTimeChip（SubmodulePill 走全局 QSS 是唯一正确姿势）。
- Empty-state 6 种 ad-hoc；无共享 Error/Loading/Degraded 状态组件。
- 表单行 3 变体：`TaskPanelBase._add_value`、`factor_task_panel.Row`、geo3d 配置行。
- Dialog 玻璃拟态 QSS 3 份近重复（lithology_crossplot/ai_check_advisor/tag_widgets）。
- TrackVisibilityDialog 手工按钮 + `color: white`，无 Cancel。

### 2.5 密度失效点
`tokens.CONTROL_HEIGHT` 是 compile-time comfortable 常量；`map_edit_toolbar.py`(13)、
`data_toolbar.py`(13)、`map_factor_shelf.py`(4)、`workflow_contract_panel.py`、
`composition_panel.py`(3) 等 `setMinimumHeight(tokens.CONTROL_HEIGHT)` 构造时定死，
切 compact 后行高不缩、与 QSS 24px 不齐。`app_bar.py:39` 固定 46px；`activity_rail.py`
固定 54px 宽 48×52 按钮；`shell.py` 默认 dock 尺寸硬编码。

### 2.6 固定尺寸 / 适配
`module_relationship.py` 固定 1180×580 画布；`home_page.py` min 1140/1100/380px；
`inspector_panel.py` 18/22px 控件低于 CONTROL_HEIGHT。

### 2.7 文本字形图标（8 处）
`floating_panel.py:73` "✕"、`completeness_card.py:67,72` "✓"/"✗"、
`composite_panels.py:64` "✕"、`tag_widgets.py:73` "×"、prototype "◀▶"。
仓库已有 50+ SVG 图标（含 chevrons/circle-check 等）。

### 2.8 宿主 chrome
- QGIS 原生 `QgsMapCanvas`/`QgsLayerTreeView` 内部不可 QSS 化（C++ 菜单 provider）——边界：
  保留 QGIS 专业语义，宿主面板已 conformant（PanelCard/WorkstationContextButton）。
- Well/Section host 白底 hex；`SeismicHost` 裸引擎视图无 chrome（引擎语义保留）。
- 降级态三种方言：文本协议（`backend_status` 字符串）、未样式化 placeholder QLabel、
  无统一组件。

### 2.9 工具缺陷
- `capture_workstation_screens.py` stale hook：`ws.process_hub.agent` 已改为 `agent_panel`
  （B18 移除 process_hub 属性）→ 08-agent-running 截图必 AttributeError。
- 无 baseline/diff 管理、无多主题×密度×尺寸矩阵驱动、无动态字段 masking。
- 无 UI token 卫生 lint。

### 2.10 死代码
`ui/pages/prototypes/workstation_composite_prototype.py`（584 行，零 importer）、
`ui/prototypes/proto_dual_volume_overlay.py`（零 importer）、3 个 HTML wireframe
（被 wheel 资产测试引用，保留）。

## 3. 基线截图（本分支捕获于 `visual_qa/baseline-v5/`）
12 状态 offscreen 基线在 token/组件迁移前捕获，作为视觉回归对照基线；
矩阵扩展（主题×密度×尺寸）由 U8 harness 生成。

## 4. 测试基线
- `tests/test_tokens.py`、`test_theme_and_sidebar.py`、`test_workstation_*.py`(8)、
  `test_layout_*.py`(2)、`test_ui_*.py` 等在 baseline commit 全绿（42 项抽样验证通过）。
- 既有 3 个 `test_unified_map_visual_regression.py` 失败为环境性（native C++ 扩展缺失，
  baseline 上同样失败），非本方向回归。
