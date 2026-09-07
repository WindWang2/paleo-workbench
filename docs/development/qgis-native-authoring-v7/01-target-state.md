# 01 — Target State（目标状态）

## 0. 边界总纲

```text
QGIS = 2D authoring interaction/geometry execution authority（交互执行与几何引擎权威）
Paleo = domain/persistence/provenance authority（地质语义、生命周期、溯源权威）
```

所有 professional 2D 空间交互（绘制、选择、捕捉、几何操作执行、测量）以 QGIS 原生路径为 production；
Python 自算 GIS 内核（`map_interaction.py` 索引/捕捉、`map_tools.py` 执行器）显式降级为 fallback
（headless/无桥环境），不得获得 QGIS 路径没有的专业新功能。

## 1. Contract 层（本 Goal 的核心交付，纯 Python、无 Qt 依赖、可 headless 测试）

### 1.1 `paleo_workbench/mapping/capability_model.py`

- `QgisCapabilitySnapshot`：桥级能力快照。
  - `status: "available" | "degraded" | "unavailable"` + `reason`（人类可读；available 时为空）。
  - `native_tools: frozenset[str]`（set_map_tool 支持的 kind，含新增 `measure`/`reshape`）。
  - `geometry_ops: frozenset[str]`（union/split_by_line/make_valid/validate/reshape/...）。
  - `dialogs: frozenset[str]`、`snapping_push: bool`、`layer_tree: bool`、`selection_highlight: bool`。
  - `bridge_version`/`qgis_version`。
  - `feature(name)` 单能力探测：`(available, reason)`。
- `LayerCapabilitySnapshot`：图层级能力（§8 全集 13 项），每项 `(available, reason)`；由 layer 状态 + 桥快照 + 编辑门禁派生。
- `probe_qgis_capability()`：组装函数——桥不可 import → `unavailable`（fail-honest，带构建指引）；manifest 缺项/版本不符 → `degraded`（带具体缺项）。
- C++ 侧新增**编译期** `capability_manifest()`（不触发 QGIS init，零成本探测的权威来源）；Python 快照从 manifest 派生，不手工镜像第二份。

### 1.2 `paleo_workbench/mapping/tool_context.py`

`ToolContext`（frozen dataclass，完全可序列化）：goal §3 列出的全部字段
（project_open/qgis_available/native_canvas_available/active_layer_*/wkb_type/layer_role/artifact_maturity/
mapping_stage/vector_writable/editing/dirty/selection_count/selection_geometry_types/can_undo/can_redo/
snapping_available/enabled/topology_available/enabled/crs_valid/edit_gate_open/raw_locked/stage_locked/
blocking_task/current_tool/capability_flags + stage_tool_profile 可见域）。
构建器从 CompositeEditController/CompositeDocument 的既有权威状态**派生**，不新建第二状态源。

### 1.3 `paleo_workbench/mapping/tool_availability.py`

- `ToolAvailability(tool_id, visible, enabled, checked, disabled_reason, preferred, conflicts)`。
- `evaluate_tool(tool_id, ctx)` / `evaluate_all(ctx)`：唯一 evaluator；goal §4 状态矩阵全量落规则、全部钉测试。
- 覆盖工具全集（30 个）：Navigation 6 / Inspection 6 / Session 4 / Capture 3 / Geometry 7（含 reshape/repair）/ GIS state 2 / undo-redo 2。
- 禁用必带人类可读 reason（复用 palette 侧 `CommandAvailability.reason` 的既有语义，统一到 tool 面）。

### 1.4 `paleo_workbench/mapping/edit_delta.py`

- `EditDelta`（goal §6 全字段）：operation ∈ create_feature/move_feature/move_vertex/delete_feature/
  split_feature/merge_features/replace_geometry/update_attributes。
- `VectorEditSession` 增 `delta_journal`（审计观测层，从命令流**派生**，非第二权威）+
  `session.edit_source(tool_id)` context manager 标注 `source_tool`（含 native/python-fallback 后缀）+
  `qgis_capability`（manifest 摘要 hash 或 `unavailable`）+ 单调 order token + session_id。
- 所有既有写路径（采点 commit、顶点/移动回调、split/merge/repair 命令、属性表）均产生 delta。

## 2. Native 收敛（C++，`native/qgis_render_bridge/`）

1. **Native Measure**：`PwbMeasureTool : QgsMapTool`——QgsRubberBand 折线 + QgsDistanceArea 距离
   （按 CRS 正确选择平面/椭球测算，修正 Python `math.dist` 在地理坐标系下的科学错误），
   回调 `measure_updated/completed/canceled`；`set_map_tool` 新 kind `measure`；
   shim 不再用视口事件过滤器 hack。
2. **capability manifest**：模块级 `capability_manifest()` 返回编译期能力注册表（工具 kinds、几何 ops、对话框、特性 flag）。
3. **geometry validate**：`geometry.validate(geojson)` 返回逐要素错误详情（QgsGeometry::validateGeometry），
   供 TopologyService QGIS 优先校验。
4. **reshape 几何操作**：`geometry.reshape(geometry, line)`（QgsGeometry::reshapeGeometry，core 可链接）。
5. **identify 收敛**：`native_identified` 接入面板打开路径（原生拾取作为点击锚点；面板多层数据仍走 Python identify_all 单一数据权威）。

## 3. 行为收敛（Python 侧）

1. **拓扑校验 QGIS 优先**：`TopologyService.validate` 桥可用 → `geometry.validate`（QGIS GEOS），
   无桥 → Shapely（现有实现，显式 fallback）；repair 已 QGIS 优先（保持）。
2. **工作站顶点拓扑传播接线**：`composite_editing` VertexTool 装配补 `on_vertex_committed`（对齐编图页）。
3. **snapping 下推增强**：endpoint → QGIS `LineEndpoint` snapping type（vendored 4.2 支持）；
   intersection → `QgsSnappingConfig` intersection flag；grid 保持 Python 专有（Paleo 域构造，文档裁决）。
4. **map_tools.py fallback 声明**：模块 docstring + MapToolController 注释明确 production=native、
   fallback=renderer-independent testing/headless；fallback 不新增专业功能。
5. **工具条 reason 通道**：`MapActionController.apply_availability(evaluate_all(ctx))`——enabled+tooltip(disabled_reason)；
   `MapActionState` 保留为兼容适配（由 ToolContext 派生），既有测试不破坏。

## 4. 测试与验收（详见 05/06）

- 纯契约测试（无 Qt/无桥）+ 状态机全矩阵测试：本机必绿。
- QGIS 标记测试（PALEO_REQUIRE_QGIS=1）：本机 vendored build 完成后真实执行，留证据。
- 性能探针：call-count/重建计数/复杂度比，不用绝对毫秒 gate。
- 三轮 review（正确性/架构/UX-性能-对抗）全 P0/P1 修复。

## 5. 明确不做

- 100GB seismic（硬排除，仅 synthetic/small/medium 接口完整性）。
- 不替换 `map_interaction.py` 索引（fallback 保留但冻结功能扩张；不删除——headless 测试依赖）。
- 不把 QGIS project 变持久化权威；不引入 qgis Python 包依赖（一切经桥）。
- 不重构 workstation shell / design system / mapping factor algorithms。
