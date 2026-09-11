# 01 — QGIS Capability Matrix（V10）

vendored QGIS 4.2.0 公开 API 与本仓库的对接矩阵。原则：QGIS 既有公开 API >
薄 bridge > 薄 Paleo 适配 > 有限 fallback > 自研 GIS 算法（最后一级默认禁止）。

## A. 已对接（V7–V9 落地，勿重复）

| QGIS API | 用途 | bridge 入口 | 状态 |
|---|---|---|---|
| `QgsMapCanvas` / `QgsMapTool` 家族 | canvas 与工具 | `mapstack.create_canvas` / `set_map_tool` | ✅ |
| `QgsMapToolDigitizeFeature` | 点/线/面捕获 | kind addPoint/addLine/addPolygon | ✅（scratch 层 + CRS 守卫） |
| `QgsMapToolIdentifyFeature` | 要素识别 | kind identify | ✅ |
| `QgsMapToolSelectionHandler` | 点击/矩形选择 + QGIS modifier 语义 | kind select | ✅ |
| `QgsMapToolPan` / `QgsMapToolZoom` | 导航 | kind pan/zoomIn/zoomOut | ✅ |
| `QgsSnappingUtils` / `QgsSnappingConfig` / `IndividualLayerSettings` | snapping 执行 | `set_snapping_config` | ✅ AdvancedConfiguration 下推 |
| `QgsPointLocator::Match`（经 snapToMap） | 命中解析 | `snap_to_map` | ✅（measure/vertex 拖动消费） |
| `QgsProject::setTopologicalEditing` | 捕获期拓扑行为 | config key `topological_editing` | ✅（V9） |
| `QgsVectorLayer` provider 字段 | fields_json→QgsFields/约束/控件 | `upsert_mirror_layer(fields_json=...)` | ✅（V8 W1） |
| `QgsGeometry` 17 个几何操作 | union/split/reshape/make_valid/validate/... | `geometry.*` | ✅ |
| `QgsDistanceArea` | 椭球/平面测量 | kind measure | ✅ |
| `QgsRubberBand` / `QgsVertexMarker` | 工具预览 | 工具内部 | ✅（vertex 拖动点、move 全几何、measure 线） |
| `QgsHighlight` | 选择高亮 | `highlight_features` | ✅ |
| `QgsAdvancedDigitizingDockWidget` | 捕获构造断言 | 隐藏不显示 | ✅（仅满足 ctor） |
| `QgsMapSettings::layers()` | 拾取层集 | pickFeature 内部 | ✅ |
| `QgsLayerTreeMapCanvasBridge` / `QgsLayerTree` | 图层树 | tree API | ✅ |

## B. V10 新增对接（本轮实现）

| QGIS API | 用途 | 落点 | 级别 |
|---|---|---|---|
| `QgsGeometry::insertVertex(beforeVertex, pt)` | native 顶点插入执行 | `PwbVertexTool` 双击段上 → `vertex_inserted` 回调 | P0 |
| `QgsGeometry::deleteVertex(nr)` | native 顶点删除执行 | `PwbVertexTool` Delete 键（hover 顶点）→ `vertex_deleted` 回调 | P0 |
| `QgsPointLocator::Match`（vertex/segment/层/距离 完整字段） | snapping feedback（marker + 匹配信息） | `PwbSnapIndicator`（QgsVertexMarker）+ `snap_feedback` 回调 | P0 |
| `QgsGeometry::addPart` / `deletePart` | part 操作几何语义 | `geometry.add_part` / `delete_part`（薄封装） | P1 |
| `QgsGeometry::addRing` / `deleteRing` | ring 操作 QGIS 语义校验源 | `geometry.add_ring` / `delete_ring`（可选执行） | P1 |
| `QgsGeometry::collectGeometry`（经 singlepart_to_multipart） | 单↔多部件转换编辑命令 | 既有 `geometry.singlepart_to_multipart` 接 session | P1 |
| `QgsMapToolCapture` 键盘语义（Backspace） | 捕获撤销上一顶点 | 验证 + 必要时薄子类 | P1 |

## C. 评估后不接（原因记录）

| API | 原因 |
|---|---|
| `QgsVertexTool` / `QgsMapToolMoveFeature` | app 层（APP_EXPORT）不可链接；已有裁剪重实现（V7 决策） |
| `QgsSnapIndicator` | app 层；V10 以 `PwbSnapIndicator`（QgsVertexMarker）等价实现 |
| `QgsAdvancedDigitizingDockWidget` 全功能 CAD | V8 D4 拒绝（地质语义弱）；保持隐藏仅为构造断言 |
| tracing（`QgsTracer`） | V8 D4 拒绝；地质捕获语义未定义到需要 tracing 的程度 |
| `QgsDualView` form 视图/表达式过滤 | V9 D3 拒绝（薄交互边界） |
| Z/M 编辑面 | 宿主 `VectorFeature` 系统性 2D（`_point()` 构造期降维），接 Z/M 会造第二几何形态；记录为 limitation |

## D. bridge 能力清单机制

- 编译期 `capability_manifest()`（`bindings.cpp`）= 唯一能力真源：`native_tools`
  / `geometry_ops` / `dialogs` / `features`。**新增 set_map_tool kind、geometry
  op、feature flag 必须同步登记**，否则 Python probe 不承认。
- Python 侧 `probe_qgis_capability()`（`capability_model.py`）消费 manifest →
  `QgisCapabilitySnapshot` → `capability_flags()`（`qgis.<feature>` /
  `qgis.native_tool.<kind>` / `qgis.geometry_op.<op>`）→ ToolContext /
  ToolAvailability 门禁。旧/坏 bridge → `degraded` 诚实降级。
