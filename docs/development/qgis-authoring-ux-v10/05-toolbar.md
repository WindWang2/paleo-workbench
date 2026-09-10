# 05 — Toolbar 专业收敛（M2/M8）

## 保持（不重做）

两行布局（上：navigate/selection/inspection/edit_session/capture/geometry；
下：snapping/layer/symbology/factor/qa/layout_export + 视图开关 + 面板
菜单）宿主在 QMainWindow TopToolBarArea；Qt 原生 overflow。

## V10 增强

* **preferred 弱提示**：evaluator `preferred=True`（kind/角色相符的捕获
  工具）→ QToolButton `[preferred]` 下缘 accent 线（QSS），弱于 checked。
  属性写在 `widgetForAction` 上并 repolish；仅 enabled+preferred 提示。
* **tooltip 状态块**：capture/edit_session/snapping/topology 工具的
  tooltip 追加「当前编辑目标：名（几何 · 角色 · 成熟度）」与捕捉配置/
  拓扑状态行——呈现事实来自同一 ToolContext（非第二判词）。
* **身份注册**：图标/风险/呈现面偏好收进 `mapping/action_registry.py`
  （45 id 全登记；`_SURFACE_EXTENSION_IDS` 保持构建顺序）。

## 原则重申

能力缺失（桥不支持）→ **disabled + 原因**，不消失；阶段外 → 整组隐藏
（QGIS 惯例），palette 保留可发现性。业务 setEnabled 散布 = 违规（评审
R1 检查项）。
