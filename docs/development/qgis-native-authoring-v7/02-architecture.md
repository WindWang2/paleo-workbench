# 02 — Architecture（目标架构）

## 1. 分层

```text
┌─ UI 层（workstation shell / map_action_controller / panels）— 只消费 ToolAvailability，不判状态
├─ Evaluator 层（NEW mapping/tool_availability.py + tool_context.py）— 纯函数状态机，无 Qt
├─ Capability 层（NEW mapping/capability_model.py ← C++ capability_manifest()）— 桥/图层能力快照
├─ Native 执行层（QgisCanvasShim → QgisMapStack → QgsMapTool* / geometry service）
│    交互意图（digitize/vertex_moved/feature_moved/selection/measure）经桥回调上浮 ↓
├─ 会话权威层（CompositeEditController → VectorEditSession → EditCommand 栈）
│    NEW: EditDelta journal（从命令流派生的审计契约，非第二权威）
└─ 持久化层（ProjectDocument / RAW->DERIVED / version / provenance — 不变）
```

关键不变量：
1. **状态单源**：ToolContext 从既有权威（edit controller / layer / session / snapping service / UIContext）派生；capability 从 C++ manifest 派生。evaluator 不持有状态。
2. **数据单轨**：QGIS 镜像层只读；一切写入经 VectorEditSession；RAW/stage/拓扑门禁不变。
3. **交互单轨（production）**：桥可用时鼠标交互全部由原生 QgsMapTool 承接；Python 工具只保留 `commit_*` 落会话入口与 fallback 执行。
4. **fail-honest**：桥不可用 → `QgisCapabilitySnapshot(unavailable, reason)` → 工具禁用带原因；fallback 降级在 `CompositeDocument._create_canvas` 单点决策并显式标注（`uses_native_stack=False`）。

## 2. 数据流（以 add_polygon 为例）

```text
用户点击 → QgsMapToolDigitizeFeature(native) → digitizeCallback(completed, GeoJSON)
  → shim 分发 → AddPolygonTool.commit_geometry()
  → session.edit_source("add_polygon(native)")
  → session.add_feature(...)  [EditCommand: AddFeatureCommand]
      ├─ undo 栈 / revision / journal（既有权威机制）
      └─ delta_journal.append(EditDelta(operation=create_feature, source_tool=...,
                                         qgis_capability=manifest_hash, order=n))
  → sessions_changed → snapshot → mirror upsert（只读投影）→ refresh_canvas
```

## 3. 能力快照的派生链

```text
C++ capability_manifest()（编译期注册表，零 init 成本）
  → probe_qgis_capability()（try-import + manifest 解析 + 版本门）
      → QgisCapabilitySnapshot
  → LayerCapabilitySnapshot(layer, qgis_snap, gate, session_state)（纯派生）
  → ToolContext.capability_flags（frozenset，如 "qgis.native_capture"）
  → evaluate_tool() 规则引用 capability_flags → 禁用原因如实（"原生采点工具不可用：桥未构建"）
```

## 4. measure 收敛后的交互流

```text
工具条 measure → activate_tool → shim set_map_tool(kind="measure")（原生 PwbMeasureTool）
  → 点击/移动：QgsSnappingUtils 吸附 + QgsRubberBand 折线
  → measureCallback(updated, points, segment_lengths, total, units)
      → MapStatusBar 距离显示（QgsDistanceArea 按 CRS 选平面/椭球——修正 math.dist 的地理系错误）
  → 右键/Esc → completed/canceled → 状态清理
```
（原 `_CanvasMouseRouter` 视口过滤器路径仅保留给 fallback 画布。）

## 5. snapping 投影（增强后）

```text
Python SnappingService（状态权威）
  → _push_snapping_config：vertex/segment/midpoint/endpoint(LineEndpoint) → QgsSnappingConfig per-layer
    intersection → config.setIntersectionSnapping(True)
    grid → 不下推（Paleo 域构造，无 QGIS 对应物；fallback 采点轨继续支持，文档裁决）
  → 原生工具捕捉 = canvas snappingUtils（唯一执行体，production）
  → Python snap() 仅 fallback 画布/headless
```

## 6. 模块归属（本 Goal 变更面）

| 模块 | 变更 |
|---|---|
| `native/qgis_render_bridge/src/*` | +capability_manifest、+PwbMeasureTool、+geometry.validate/reshape、identify kind 语义 |
| `paleo_workbench/mapping/capability_model.py` | NEW |
| `paleo_workbench/mapping/tool_context.py` | NEW |
| `paleo_workbench/mapping/tool_availability.py` | NEW |
| `paleo_workbench/mapping/edit_delta.py` | NEW |
| `paleo_workbench/mapping/vector_layer.py` | +delta journal / edit_source（最小侵入） |
| `paleo_workbench/mapping/topology.py` | validate QGIS 优先 |
| `paleo_workbench/mapping/map_tools.py` | fallback 声明 + measure 原生结果消费入口 |
| `paleo_workbench/ui/qgis_stack/canvas_shim.py` | measure 原生接线、identify 转发收敛、capability 消费 |
| `paleo_workbench/ui/map_action_controller.py` | +apply_availability(reason 通道) |
| `paleo_workbench/ui/workstation/composite_editing.py` | 工具激活走 evaluator、拓扑传播接线、edit_source 标注 |
| `paleo_workbench/ui/workstation/composite_document.py` | ToolContext 构建 + availability 应用 |
| tests/ | +契约/状态机/桥能力/集成测试 |

## 7. 给并行分支的稳定接口（冻结契约）

`QgisCapabilitySnapshot` / `LayerCapabilitySnapshot` / `ToolContext` / `ToolAvailability` / `EditDelta`
均为 frozen dataclass + `to_dict()`，无 Qt import，UI 分支可直接消费（tooltip/statusbar/palette）。
字段演进只加不改；语义变化在 `03-decisions.md` 记录并 bump `contract_version`。
