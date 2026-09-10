# 06 — Snapping & Topology（V10）

## A. 权威划分（不变）

```
QGIS（执行权威）                       Paleo（语义/事务权威）
  QgsSnappingUtils/Config                SnappingService（fallback 执行 + 配置投影）
  QgsPointLocator::Match                 snapping_profiles（role → 推荐配置）
  AdvancedConfiguration 下推             ToolContext.snapping_available（manifest 派生）
  topologicalEditing（捕获期跟随）       TopologyService（跨层传播 + compound undo）
```

## B. snapping 链路（native 主路径）

1. `SnappingService`（宿主单一配置状态：全局开关/mode/容差/参考层/逐层覆盖）
   → `_push_snapping_config`（composite_editing）翻译为 JSON →
   `bridge.set_snapping_config(canvas, json)`。
2. C++ `setSnappingConfig`（map_stack_service.cpp）：
   `layers` 存在 → `AdvancedConfiguration` + `IndividualLayerSettings`
   （doc_id → 镜像层解析，未知 doc_id 跳过并计数）；`tolerance_px`
   （默认 12，**像素单位 = 缩放自适应**）；`types`（vertex/segment/midpoint/
   centroid/area/endpoint）；`intersection_enabled` → setIntersectionSnapping；
   `reference_enabled` → `pwb/reference=="true"` 层自动 vertex；
   `topological_editing` → `QgsProject::setTopologicalEditing`。
3. 执行：工具内 `canvas->snappingUtils()->snapToMap(mapPoint)`
   （`PwbEditPickTool::snapOrRaw` / V10 新增 feedback 查询）。
4. manifest 门禁：`snapping_push`/`snapping_endpoint`/`snapping_intersection`
   /`snapping_topological_editing` 缺失 → 诚实降级 + 警告（V7 D5 纪律）。

### V10 新增：反馈闭环

```
canvasMoveEvent（捕获/vertex/move 工具）
  → snapToMap(point)
  → PwbSnapIndicator: vertex 命中→十字 marker；segment 命中→投影点 marker
  → callback snap_feedback {matched, x, y, layer_doc_id, feature_id,
                            match_type: vertex|segment|midpoint|endpoint|intersection,
                            distance}
  → canvas_shim 信号 → 宿主状态栏（层名 + 类型 + 距离）
```

- 无命中 → marker 隐藏 + `matched:false`（节流：仅状态变化或位移超容差时回传，
  避免每次 mouse move 打 Python）。
- fallback 路径 `SnappingService` 已有匹配信息（V7 消费），不新建第二套。

### 自捕获（self-snapping）

活动镜像层在 AdvancedConfiguration 的 `layers` 集内 → 自身参与 snapping
（QGIS 语义，捕获 scratch 层不参与——它是独立隐藏层，不在配置内）。
V10 以 qgis-marked 测试锁定该行为。

## C. topological editing 双层同向

| 层 | 职责 | 时机 |
|---|---|---|
| QGIS `topologicalEditing` | 捕获期：新顶点吸附到已存在边界时**自动插入共享节点**（digitizer 行为） | 捕获进行中 |
| Paleo `TopologyService.propagate_shared_vertex` | 提交期：顶点移动传播到跨层共享顶点，compound undo 组 | vertex move 宏关闭后 |

不冲突：一个管"捕获时造出共享边界"，一个管"编辑时保持共享顶点一致"。
`TopologyService.enabled` 下推到 QGIS（V9 W2），单一开关两层生效。

### V10 测试补强（Milestone H）

- 捕获期 topological editing ON：新面边界顶点吸附到相邻面边界 → 两面共享
  节点（qgis-marked）。
- 共享顶点 move → 传播 → compound undo 一次回滚（已有 V8 测试，补
  native 路径 e2e）。
- 共享边界上 insert/delete vertex：**不自动传播**（V10 边界，见
  11-known-limitations——插入/删除传播需要边界段匹配语义，本轮只保证
  move 传播，诚实地不假实现）。

## D. 验证一致性（topology error count）

`TopologyService.cached_error_count`（(data_revision, session revision) 缓存）
在有限刷新点更新（save/flush/几何命令/undo/redo/显式校验），作为 merge
gate 的 `topology_error_count` 事实源——不逐帧全层扫描（V9 W2 纪律，V10
新增命令族挂入同一刷新点）。
