# 06 — Layer Tree UX（M5）

## 回退树（LayerManagerPanel）右键菜单

* **编辑入口消费 evaluator**：`menu_probe = CompositeDocument.
  layer_menu_facts(layer_id)` 返回 `LayerMenuFacts(toggle_editing,
  repair_geometry, raw_protected)`——「开始/停止编辑」「修复无效几何」的
  enable 与禁用判词来自 canonical 求值（目标图层事实投影进 ToolContext）。
* **RAW 工作流入口**：RAW 保护图层显示「复制为草稿…」（duplicate 通道）
  ——正确的下一步操作取代注定失败的「开始编辑」。
* **执行 re-gate 升级**：`_toggle_layer_editing`/`_repair_layer` 从
  「只复查角色门禁」升级为完整 evaluator（blocking/kind 一并拦截）——
  `_layer_tool_availability(layer_id, tool_id)` 是 `_layer_repair_
  availability`（V8 M2）的泛化。

## 原生树（QgisLayerTreePanel）

C++ 菜单组合按 `pwb/editable` 身份旗标（无桥覆写 API——本方向不动 C++）。
Python 侧执行 re-gate（升级后）是权威；拒绝时状态条给判词。已知限制
见 13（原生菜单项 enable 的 evaluator 化需要桥菜单校验 API，移交后续
方向）。

## 装饰（V7/V9 已建，保持）

`LayerPresentationState`（editing ✏ / dirty / stale / missing / frozen /
published / degraded）优先级单点；原生行指示器经 `set_row_indicators`
（能力门控）。
