# 编图页工具栏图标化与布局优化 — 设计

日期: 2026-08-23
状态: 已定稿（auto 模式下按用户指示直接实施）

## 问题

`MappingPage` 顶部 4 条 `QToolBar`（Map Navigation / Selection / Digitizing / Advanced
Editing）纵向堆叠，共 29 个 `QAction` 全部**纯文字**显示（`setIconText(label)` 强制文本），
且 `tokens.build_qss()` 对 `QToolBar`/`QToolButton` 无任何样式。结果是四行文字按钮墙，
与 QGIS 专业制图定位不符。

## 目标

- 工具按钮改为 **icon-only**（图标来自 vendored QGIS 默认主题 SVG），文字保留在
  tooltip/statusTip/action.text（供无障碍与菜单复用）。
- 4 行合并为 **2 行**：第 1 行"浏览与选择"（导航 + 选择/量测），第 2 行"编辑"（编辑开关 +
  数字化 + 撤销/删除 + 高级编辑 + 捕捉/拓扑/取消），组间用 `addSeparator` 分隔。
- 标签改为中文（与全应用中文 UI 一致；快捷键与 action id 不变）。
- `build_qss()` 增加 `QToolBar`/`QToolButton` 样式：面板化背景、分隔线、hover/checked/
  disabled 态、圆角，复用现有 token（`BG_SIDEBAR`/`BG_SEARCH`/`BG_NAV_ACTIVE`/`BORDER`）。

## 图标来源与分发

- 源: `third_party/qgis/images/themes/default/*.svg`（QGIS 默认主题，24×24）。
- 运行时**不依赖** third_party（wheel 不打包它）：将 29 个 SVG 以 action id 命名拷贝到
  `paleo_workbench/ui/assets/icons/map/{action_id}.svg`，沿用 `menu_bar._icon()` 的
  文件系统加载模式。
- `tests/test_wheel_assets.py::EXPECTED_SVG` 16 → 45。

映射（action_id → QGIS 图标）:
pan→mActionPan, zoom_in→mActionZoomIn, zoom_out→mActionZoomOut,
full_extent→mActionZoomFullExtent, previous_extent→mActionZoomLast,
next_extent→mActionZoomNext, refresh→mActionRefresh, identify→mActionIdentify,
select→mActionSelect, select_rectangle→mActionSelectRectangle,
measure_distance→mActionMeasure, clear_selection→mActionDeselectAll,
select_all→mActionSelectAll, invert_selection→mActionInvertSelection,
toggle_editing→mActionToggleEditing, save_edits→mActionSaveEdits,
rollback→mActionRollbackEdits, add_point→mActionCapturePoint,
add_line→mActionCaptureLine, add_polygon→mActionAddPolygon,
move_feature→mActionMoveFeature, vertex→mActionVertexTool,
delete_selected→mActionDeleteSelected, undo→mActionUndo, redo→mActionRedo,
split→mActionSplitFeatures, merge→mActionMergeFeatures,
snapping→mIconSnapping, topology→mIconTopologicalEditing,
cancel→mActionCancelEdits.

## 改动点

1. **新资产**: `paleo_workbench/ui/assets/icons/map/`（29 个 SVG，从 third_party 拷贝）。
2. **`paleo_workbench/ui/map_action_controller.py`**:
   - `_LABELS` 改中文；
   - 新增 `_icon(action_id)`（Path 存在才加载，缺失回退空 QIcon，模式同 `menu_bar._icon`）；
   - `_action()` 里 `action.setIcon(...)`，删除 `setIconText`；
   - `toolbar()` 支持元素为 tuple（组），组间自动 `addSeparator()`；平铺 tuple 用法保持兼容
     （现有测试不破坏）。
3. **`paleo_workbench/ui/pages/mapping_page.py`**: 4 次 `toolbar()` 调用改为 2 次，
   传入分组嵌套结构；`setToolButtonStyle(Qt.ToolButtonIconOnly)`、
   `setIconSize(QSize(18,18))`（在 controller.toolbar 内统一设置）；行间距 0 → `SPACE_1`。
4. **`paleo_workbench/tokens.py` `build_qss()`**: 追加 `QToolBar`、`QToolBar::separator`、
   `QToolButton`（含 hover/pressed/checked/disabled）样式段。
5. **测试**:
   - `tests/test_map_action_controller.py` 新增：每个 action 均有非空 icon；分组 toolbar
     生成 separator；中文 tooltip 存在。
   - `tests/test_wheel_assets.py`: `EXPECTED_SVG = 45`。

## 不做（YAGNI）

- 不引入 Qt resource 编译（.qrc），沿用文件系统加载。
- 不动隐藏兼容 shim `MapEditToolbar`。
- 不改 action id / 信号 / 快捷键 / 状态机（`update_state` 逻辑不变）。
- 不做浅色/深色双主题（QGIS 默认主题单色即可，QToolButton 样式随全局 token）。

## 风险

- 图标缺失回退空 QIcon → 按钮仍可用（有 tooltip），不会崩；测试断言防回归。
- 窄窗口 2 行 15+14 个 24px 图标 ≈ 400px 宽，安全。
