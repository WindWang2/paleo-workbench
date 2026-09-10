# 01 — Authority boundaries（V9）

## 1. 权威分工（本 goal 后的稳定形态）

```
Paleo Geological Semantics          GeologicalLayerSpec / LayerRole / MappingStage
        │                            ArtifactMaturity / DataVersion / provenance
        ▼
GeologicalCaptureSpec (W9)          role → 模板字段/默认属性/捕捉推荐/拓扑建议
        ▼
Canonical ToolAvailability          tool_context (v3) → tool_availability（唯一 evaluator）
        ▼
QGIS Native Map Tool                QgsMapToolDigitizeFeature / PwbVertexTool / …
        ▼
QgsMapCanvas                        捕捉（含 topologicalEditing，W2）/ 渲染 / 比例尺
        ▼
QgsVectorLayer / provider           QgsFields（spec fields_json 物化）+ 发布验证（W6）
        ▼
VectorEditSession / EditDelta       命令式编辑 / undo / redo / compound（V8 M3）
        ▼
Paleo Version / Provenance / QC     save_edits → project → catalog lineage
```

## 2. QGIS 决定（执行权威）

| 面 | V9 变化 |
|---|---|
| 几何计算 | union/split/clip/… 桥算子优先（V7 既有）；PIP/bbox 共享内核保留（V8 裁定，热路径） |
| 地图交互 | digitize/vertex/move/select/identify/measure 原生工具（V7）；V9 补 **数字化提交 CRS 守卫**（W7） |
| 捕捉 | `set_snapping_config`（AdvancedConfiguration，V7）；V9 增 `topological_editing` 键（W2）——QgsProject 顶级编辑随配置下推 |
| 比例尺 | **新增 `canvas_scale`**（W1）：`QgsMapCanvas::scale()` 是 scale_denominator 的唯一原生真源 |
| 画布 CRS | **新增 `canvas_destination_crs`**（W7）：守卫比对的画布侧真值 |
| provider schema | fields_json → QgsFields/约束/控件（V8）；V9 增**发布后读回验证**（W6，`mirror_layer_schema_json` 比对） |

## 3. Paleo 决定（语义权威）

| 面 | V9 变化 |
|---|---|
| 角色语义 | `role_of_layer` 单点注入（stage membership → 控制器），快照 metadata.role / 捕获默认 / 属性表列元数据 / 捕捉推荐全部派生（W6/W9/W5/W4） |
| 阶段/成熟度/版本 | 不变（V5-V8 既有） |
| CRS 契约 | **`mapping/crs_contract.py` 单一谓词/解析权威**（W3）：`resolve_crs` 永不静默 4326；地理谓词、米制轴、Geod、诚实比例尺分母集中于此 |
| 捕捉推荐 | `snapping_profiles.py`（W4）：角色 → 模式/容差/拓扑建议 + rationale——**推荐 ≠ 硬编码真值**（用户可改，写既有 per-layer 覆盖通道） |
| 拓扑 | `TopologyService` 宿主权威（V8）；V9 增**运行时错误计数生产者**（W2）+ 计数刷新点（保存/flush/开关/几何命令/undo/redo/显式校验） |
| 阻塞任务 | `_mapping_blocking_task_label`（W1）：持有编图工程产物的工作流 DAG 运行（kind=background.compute、title=workflow:*）→ 全局 blocking 事实 |

## 4. 明确不做（防第二真源）

- 不建第二 evaluator / 第二 ToolAvailability（tool_surface.py 仍只是 presentation adapter）。
- 不建第二角色表（role 单权威 = stage membership；控制器只持查询钩子）。
- 不建第二捕捉配置（profile 应用写 SnappingService 既有覆盖通道）。
- 不建第二 schema（属性表列元数据派生自 GeologicalLayerSpec——与镜像 fields_json 同源）。
- 不做 QgsDualView 全托管 C++ 面板（评估决策见 03-decisions D3）。
- 100GB seismic：零接触。
