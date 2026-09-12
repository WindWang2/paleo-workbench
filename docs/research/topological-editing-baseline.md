# 拓扑编辑基线事实（wayfinder 勘探，2026-09-11）

> 「相图编辑必须支持 QGIS 原生拓扑编辑」地图的起锚事实。两次只读勘探的结论，
> 全部带代码坐标。研究/决策票以此为共享底座，不重复考证。

## 1. 编辑权威现状：Python 会话是权威，QGIS 镜像层纯显示

- 权威数据结构：`VectorLayer` + `VectorEditSession` 编辑缓冲区
  （`paleo_workbench/mapping/vector_layer.py:273,370`）——工作态、撤销/重做、
  提交、回滚都在 Python。
- 镜像层（memory provider）**从不 `startEditing()`**：唯一例外是数字化私有
  草稿层 `__pwb_capture_scratch`（不在 QgsProject 中，
  `native/qgis_render_bridge/src/map_stack_service.cpp:3614-3620`），因为
  `QgsMapToolDigitizeFeature` 要求可编辑层。镜像更新只走 provider 的
  `deleteFeatures/addFeatures`（`map_stack_service.cpp:1893,1914`）。
- 原生工具不写几何，只发 JSON 回调：`vertex_moved/vertex_inserted/
  vertex_deleted`（`edit_tools.cpp:380-416`）、`feature_moved(dx,dy)`
  （`edit_tools.cpp:600`）、数字化 GeoJSON `completed`
  （`map_stack_service.cpp:3641-3667`）。
- 回调落 Python：`canvas_shim.py:1109-1175`（含
  `crs_chain.evaluate_commit_guard` CRS 提交门）→ Python 工具 `commit_*`
  → `EditCommand` 进会话（`map_tools.py:46-94`）。
- 会话编辑 → `content_changed` → `snapshot_layers`
  （`composite_editing.py:2369`）→ `mirror_snapshot_to_stack`
  （`qgis_mirror.py:431`）→ provider 级增量重发；fid 反查经 `fidResolver()`
  （`map_stack_service.cpp:3681-3696`）。

## 2. 原生交互工具清单（现状）

| 工具 | 位置 | 说明 |
|---|---|---|
| `PwbEditPickTool` | `edit_tools.cpp:29-318` | 容差拾取基类，`QgsSnapIndicator` + snap 反馈 |
| `PwbVertexTool` | `edit_tools.cpp:322-561` | 单节点拖动/双击插点/删点（最小节点防护）；**无共享节点感知** |
| `PwbMoveTool` | `edit_tools.cpp:565-601` | 整要素平移（rubber band） |
| `PwbSelectTool` | `edit_tools.cpp:604-714` | 包 `QgsMapToolSelectionHandler` |
| `PwbIdentifyTool` | `edit_tools.cpp:637-666` | 多命中排序识别 |
| `PwbMeasureTool` | `edit_tools.cpp:718-840` | 椭球测距（只读） |
| `PwbDigitizeTool` | `map_stack_service.cpp:850-940` | 子类化 `QgsMapToolDigitizeFeature` 到草稿层 |

分割/合并无原生工具——是 Python 工具栏命令：`geometry_command`
（`composite_editing.py:1953-2018`）→ `merge_selected_polygons` /
`split_polygon_by_line`（`mapping/vector_operations.py`）→ 桥接几何算子
（`geometry_service.cpp:70-84` split = `QgsGeometry::splitGeometry`），
Shapely 兜底 → `SplitFeatureCommand/MergeFeaturesCommand`
（`vector_layer.py:685-712`）。**未用** `splitFeatures(topologicalEditing=true)`。

## 3. 吸附：Python 权威配置，投影为真 QgsSnappingConfig

- Python 引擎：`SnappingService` + `FeatureSpatialIndex`
  （`map_interaction.py:336-540`）；模式词汇
  `vertex/segment/midpoint/endpoint/intersection/reference/grid`，全局像素
  容差 + per-layer 覆盖 + 优先级；JSON 快照/恢复。
- 原生投影：`_push_snapping_config`（`composite_editing.py:1714-1798`）→
  C++ `setSnappingConfig`（`map_stack_service.cpp:3377-3470`）：真
  `QgsSnappingConfig`（Advanced per-layer / AllLayers / ActiveLayer），
  `setIntersectionSnapping`，locator 预热。能力清单门控（manifest 缺项时
  降级告警，`composite_editing.py:1730-1758`）。
- `QgsProject::setTopologicalEditing` 已推送（`map_stack_service.cpp:3390-3398`），
  仅辅助原生数字化；宿主 `TopologyService` 仍是权威（双侧注释明确）。
- 角色推荐 profile：`snapping_profiles.py` 8 组（含 `topological: bool` 旗标）；
  `capture_spec.py` per-role `recommend_topological_editing`。

## 4. 拓扑校验现状：只有有效性，没有缝隙/重叠/悬挂点

- `TopologyService.validate`（`topology.py:182-239`）：逐要素 GEOS 有效性
  （优先桥接 `geometry.validate`）+ 面环闭合检查。**无 gap/overlap/dangle**。
- 保存门禁：`save_edits` 拓扑开关打开时有错即阻断
  （`composite_editing.py:1267-1283`）；flush 门禁同
  （1331-1340）；状态条拓扑 chip（`map_status_bar.py:410`）；
  修复 = makeValid → `SetGeometryCommand`（`composite_editing.py:1881-1914`）。
- 共享节点传播（Python 侧已实现）：`propagate_shared_vertex`
  （`topology.py:263-361`）——精确坐标匹配（1e-9）跨门禁层同步移节点，
  注册跨层 `CompoundUndoGroup`（原子撤销，`topology.py:67-87,365-539`）。
  接线：`composite_editing.py:1458-1493`。

## 5. 撤销/重做架构（Python 权威的一部分）

- 单层：快照式 `EditCommand` + undo/redo 栈（`vector_layer.py:380-734`）；
  宏分组 `begin/end_edit_command`。
- 跨层：`CompoundUndoGroup` 原子撤销（冲突扫描 + 修订号守卫），
  `pop_command/push_command_back` 绕过 redo 栈。
- 审计：`EditDelta` 日志 + `edit_source(tool)` 溯源（原生提交标注如
  `vertex(native)`）。

## 6. Vendored QGIS 4.2 能力审计

Vendor 前缀：`native/qgis_render_bridge/build/qgis-vendor/output`；
**构建了 core+gui+analysis+native，无 app 库、无插件**（`lib/qgis/plugins/`
为空；`-DWITH_DESKTOP=OFF`）。头文件来自源码快照 `third_party/qgis`。

可用（头在 + 库已链）：
- `QgsProject::setTopologicalEditing`（`core/project/qgsproject.h:774,777`）——已接线。
- `QgsSnappingConfig` 含 `setIntersectionSnapping`/per-layer——已接线。
- 避免重叠：`QgsProject::setAvoidIntersectionsMode/Layers`
  （`qgsproject.h:1173-1195`）+ `QgsGeometry::avoidIntersectionsV2`
  （`qgsgeometry.h:2836`）——**可链未接**。
- 拓扑分割：`QgsVectorLayer::splitFeatures/splitParts`（带
  `topologicalEditing` 旗标，`qgsvectorlayer.h:1456-1544`）——可链未用。
- 合并：`QgsVectorLayerEditUtils::mergeFeatures`
  （`qgsvectorlayereditutils.h:293`）——可链未接（桌面版
  `QgisApp::mergeSelectedFeatures` 在 app 库，未构建）。
- 追踪：`QgsTracer` 是 **core** 类（`core/qgstracer.h:44`，
  `findShortestPath`/`setSnapTolerance`）——可链未接。
- `makeValid`/`validateGeometry`——桥接已暴露（`geometry_service.cpp:137-155`）。

缺失（源码在 `third_party/qgis` 但未构建）：
- 全部 APP_EXPORT 交互工具：`QgsVertexTool`、`QgsMapToolMoveFeature`、
  `QgsMapToolSplitFeatures`、`QgsMapToolTrimExtendFeature`、reshape 工具
  （`src/app/`；桥接头注释 `edit_tools.hpp:4` 明确不可链，故自制瘦版本）。
- 拓扑检查插件 `src/plugins/topology/` 与几何检查器
  `src/plugins/geometry_checker/`——依赖 QgisInterface，未构建。
  但 `QgsGeometryCheck` 检查器框架在 **analysis 库**（`qgis_analysis` 已链），
  `QgsCheckValidityAlgorithm` 亦在 analysis。

API 形状注意：QGIS 4.2 枚举已迁入 `Qgis`` 命名空间
（`Qgis::SnappingMode/SnappingTypes/AvoidIntersectionsMode/...`）；
`validateGeometry`/`reshapeGeometry` 非常量（桥接已处理）。

## 7. 已知阻塞项

- **工程 CRS 声明失配**：工程声明 `EPSG:4326` 但相图数据为本地坐标
  （0-16000），`crs_chain.evaluate_commit_guard` 拒绝原生数字化提交。
  编辑权迁移后此问题更 central，需专门决策（票：可编辑层 CRS 契约）。

## 8. 访谈已锁定的地图决策（2026-09-11，grilling）

1. 架构路线：**编辑权迁移 QGIS**（镜像层升级真可编辑，Python 会话改同步方）。
2. 地图终点：**决策+规格+路线图**（实施不在本地图内）。
3. 迁移范围：**相图草稿先行**（面状草稿层验证后二阶段推广）。
4. 撤销语义：**整手势原子撤销**（跨层统一，不留半手势状态）。
5. 检查策略：**双档**——实时拓扑面板（定位/高亮）+ 保存门禁零错误；
   自动修复作为可撤销编辑命令。
