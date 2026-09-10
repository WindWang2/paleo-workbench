# 03 — Target Architecture（V10）

V10 不是新架构轮次，而是对既有 QGIS Native Authoring Kernel 的**纵深加固**：
修正既有缺陷、补齐编辑能力面、把交互质量抬到专业数字化工具水平。权威划分
一字不变：

```
QGIS  = 2D 空间执行权威（canvas/工具/几何操作/snapping 执行/provider 运行时）
Paleo = 地质语义权威（LayerRole/MappingStage/编辑权限）
        + 事务权威（VectorEditSession/EditDelta/undo/redo/DataVersion/provenance）
```

## A. V10 目标态增量

### A1 vertex 工具升到专业三操作

`PwbVertexTool`（move）→ move + insert + delete：

```
press/drag/release → vertex_moved（既有）
doubleClick（段上） → vertex_inserted {layer_doc_id, feature_id, path, x, y}
hover             → QgsVertexMarker 提示；Delete 键 → vertex_deleted {..., path}
```

- insert 的 path 语义 =「新顶点应插入的坐标下标」（与 session
  `insert_vertex` 的 `parent.insert(index, point)` 对齐）；native 端用
  `QgsGeometry::vertexNrFromVertexId` 反查 beforeVertex 计算。
- delete 前置守卫：删除后顶点数 < 类型最小值（Line 2 / Ring 4 / Triangle 3）
  → 拒绝回调（fail-closed，不发半成品）。
- ring 闭环不变量：session 层维护（见 A4），native 无需特殊处理。

### A2 ring/part/convert 命令族

- 新 session 命令类型：`AddPartCommand` / `DeletePartCommand` / `MovePartCommand`
  （SetGeometryCommand 子类，delta → replace_geometry）+
  `DuplicateFeatureCommand`（AddFeatureCommand 语义复用，独立类型便于审计）。
- ring：复用既有 `add_ring`/`delete_ring`（GeoJSON list op）+ QGIS `validate`
  作校验；part 几何语义走 bridge `geometry.add_part/delete_part`
  （`QgsGeometry::addPart/deletePart` 薄封装）。
- explode/collect：复用 `split_feature`/`merge_features`（语义完全吻合：
  1→N 替换 / N→1 合并），几何分别走 bridge `multipart_to_singlepart` /
  `singlepart_to_multipart`（collect 不 dissolve）。

### A3 snapping feedback

`PwbSnapIndicator`（edit_tools.cpp 内部类，`QgsVertexMarker` 组合）：

- 捕获类工具 + vertex/move 工具的 canvasMoveEvent 上查询
  `canvas->snappingUtils()->snapToMap(point)`；
- 顶点命中 → 十字 marker 于 snapped 点；边命中 → marker 于投影点；
- 回调 `snap_feedback {matched, x, y, layer_doc_id, feature_id, match_type,
  distance}` → canvas_shim 信号 → 宿主状态栏/工具提示。
- Python fallback `SnappingService` 已有等价信息（V7 已消费）——不新建第二套。

### A4 闭环 ring 不变量（session 层，权威修复）

`set_vertex` / `insert_vertex` / `delete_vertex` 在**多边形 ring 上下文**
（Polygon `coordinates[r]` / MultiPolygon `coordinates[p][r]`，`len>=4` 且
首=尾）：

- set：index==0 → 同步闭合点；index==len-1 → 同步首点；
- insert：index==0 → 插入后闭合点改为新首点；index==len-1（闭合点前）→
  自然保持闭合；
- delete：删除首点 → 闭合点改为新首点；删除闭合点 → 余尾自然=首点；
- 最少顶点守卫：删除后 <4 顶点（含闭合）→ ValueError。

修复位于 session 而非工具层：native 与 fallback 两条提交路径同时受益，
且 undo 快照自动正确（before/after 都是闭合几何）。

### A5 属性策略显性化

- split（含 explode）：每个 replacement 继承原要素**全部属性**（几何操作
  只管几何；语义 = 一个地质体被细分，属性不丢）。
- merge（含 collect）：merged 要素属性 = **首个选中要素**的属性
  （选择序），几何之外的属性以首要素为准，其余丢弃——QGIS 桌面 merge
  attributes 对话框不做（薄交互边界），策略记录于 04-decisions D2。
- duplicate：全属性复制，新 feature_id。

### A6 工具面接线

`tool_availability.py` 新增/扩展工具 id（canonical evaluator 唯一真源）：

- `vertex_insert` / `vertex_delete`（并入 vertex 工具的交互，不单列按钮——
  availability 由 vertex 工具同一门禁 + 几何类型守卫）
- `add_ring` / `delete_ring` / `add_part` / `delete_part` / `explode_multipart`
  / `collect_multipart` / `duplicate_selected` / `select_all` / `invert_selection`
  / `clear_selection`（edit_command 族，菜单/面板入口）

全部走既有 `edit_command` 单入口 re-gate，不产生第二执行路径。

## B. 明确不做（V10 边界）

- 不做 rotate/scale/tracing/CAD 面板/剪贴板粘贴（04-decisions D5/D6）。
- 不把 fallback canvas 升级出 native 专属能力（V7 §5 继续有效；
  fallback 的 vertex insert/delete 不实现）。
- 不动 dock 框架/toolbar 布局（V9 adaptive-ui 方向所有权）。
- 不重建 vendored QGIS、不碰 PROJ/GDAL runtime、不碰 100GB seismic。
- 不引入第二个 snapping/几何/topology 内核；Python 侧新增代码只做
  会话命令与门禁，几何执行一律 QGIS-first。
