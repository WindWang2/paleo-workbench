# QGIS 原生拓扑编辑机制与桌面版 undo 聚合（票 #1279）

> 一手源码调研（vendored QGIS 4.2.0，`third_party/qgis`，commit 快照 HEAD=6c08fb7d）。
> 所有行号相对本仓库 `third_party/qgis/` 下的源码文件。底座：`docs/research/topological-editing-baseline.md`（2026-09-11）。
> 核心结论预告：**拓扑编辑的跨层传播全部在 src/app（桌面工具层），不在 core 编辑缓冲区；桌面版 Ctrl+Z 没有跨层整手势聚合——它是"仅当前活动层"的 undo。**

---

## 1. `QgsProject::topologicalEditing=true` 的编辑缓冲区行为

### 1.1 该旗标只是工具行为开关，core 编辑 API 不读它

`topologicalEditing` 是 `QgsProject` 上的普通 bool 属性（`src/core/project/qgsproject.h:131,774,777`）。在 `src/core` 全量检索，读它的只有工具侧代码与 `qgstrackedvectorlayertools`/`qgsvectorlayertools`（要素拷贝移动），**`QgsVectorLayer::changeGeometry`、`QgsVectorLayerEditBuffer`、provider 写入路径完全不感知它**。也就是说：打开它不会让 core 的任何单层编辑自动产生跨层写入；跨层行为是桌面工具（`QgsVertexTool` 等）在手势时刻主动做的。

### 1.2 跨层共享节点移动的真实写入路径（不是 `QgsVectorLayerEditUtils::moveVertex`）

`QgsVectorLayerEditUtils::moveVertex`（`src/core/vector/qgsvectorlayereditutils.cpp:83-112`）是**单层单要素**简单封装：取要素 → `geometry.moveVertex` → `changeGeometry`，无任何拓扑逻辑。桌面顶点工具不走它。

真实路径（全部在 app 层 `QgsVertexTool`，`src/app/vertextool/qgsvertextool.cpp`）：

**A. 拖拽开始时发现共享节点集合**（`startDraggingMoveVertex`，:1944-1977）：

```cpp
if ( QgsProject::instance()->topologicalEditing() )          // :1963
  movingVertices.unite( findCoincidentVertices( movingVertices ) );  // :1965
```

- `findCoincidentVertices`（:1898-1919）：对每个待移动节点，遍历 `editableVectorLayers()`（:1885-1896 = 画布可见 + `isEditable()` + `isSpatial()` 的矢量层），逐层做点查询。
- 查询实现 `layerVerticesSnappedToPoint`（:2091-2096）：

```cpp
QgsPointLocator *loc = canvas()->snappingUtils()->locatorForLayer( layer );
return loc->verticesInRect( mapPoint, 1e-8, &myfilter, true );
```

即：**用每层已建好的 `QgsPointLocator`（R-tree 空间索引，挂在 canvas 的 snappingUtils 上）做 point-in-rect 查询**，不走全量遍历。容差**硬编码 1e-8（地图 CRS 单位）**——是"实质精确重合"匹配，与用户吸附容差无关（`QgsPointLocator::verticesInRect` 语义见 `src/core/qgspointlocator.h:442`）。
- 边拖拽（`startDraggingEdge`，:2226-2229）同样联合重合节点；线段上加点（`startDraggingAddVertex`，:2145-2167）则找"两端点都重合的共线段"（`layerSegmentsSnappedToSegment`，:2098-2116——先按 1e-8 吻合一个端点，再要求相邻顶点等于另一端点）。
- 跨 CRS 层的重合节点通过 map 坐标对齐（`buildExtraVertices`，:1921-1941：锚点 map→目标层 CRS 重投影，记录每节点相对锚点偏移，非重合选中节点保持相对位置）。

**B. 提交时按层写入各自 edit buffer**（`QgsVertexTool::moveVertex`，:2320-2567 → `applyEditsToLayers`，:2685-2724）：

- 编辑按 `QHash<layer, QHash<fid, VertexEdit>>` 组织（:2473-2483），每个受影响要素直接 `geomTmp->moveVertex`（:2463）改几何副本；
- `applyEditsToLayers` 对**每个层**独立执行：`layer->beginEditCommand(tr("Moved vertex"))`（:2703）→ 若开启避免重叠则 `QgsAvoidIntersectionsOperation::apply`（:2704-2708）→ `layer->changeGeometry(fid, geom)`（:2715）→ `layer->endEditCommand()`（:2718）→ `triggerRepaint`。
- `beginEditCommand`/`endEditCommand` 即该层 `undoStack()` 的 `beginMacro/endMacro`（`src/core/vector/qgsvectorlayer.cpp:4608-4646`，stack 定义在 `src/core/qgsmaplayer.h:1555`）；所有缓冲区编辑以 `QgsVectorLayerUndoCommand*` 压栈（`src/core/vector/qgsvectorlayereditbuffer.cpp:149,209,253`）。
- **结论：一次拓扑手势 → 每个受影响层各得一条独立的宏命令（"Moved vertex"），写入各自 edit buffer；没有跨层单命令。**

**C. 提交后向邻层散布拓扑点**（`moveVertex`，:2487-2547）：若 `topologicalEditing`，对"每个被编辑层 × 画布上每个可编辑线/面层"，仅当 **CRS 相同**（:2511-2513 注释明确：重投影会破坏重合性）、bbox 预查有要素（:2520）时：`beginEditCommand("Topological points added by 'Vertex Tool'")`（:2523）→ 逐新节点 `vectorLayer->addTopologicalPoints(point)`（:2534）→ 有改动 `endEditCommand()`，无改动 `destroyEditCommand()` 不留 undo 痕迹（:2541-2544）。

**D. 删除节点同理**（`deleteVertex`，:2727-2769）：`topologicalEditing` 时用同一 1e-8 点查询联合"同位置所有节点"（:2750-2770），按层 `beginEditCommand("Deleted vertex")` → `layer->deleteVertices`（:2795）→ `endEditCommand/destroyEditCommand`（:2808-2814）。

### 1.3 容差语义（两套，别混）

| 环节 | 容差 | 出处 |
|---|---|---|
| 共享节点/共线段发现 | **硬编码 1e-8（map CRS 单位）**，精确重合语义 | `qgsvertextool.cpp:2095` |
| `addTopologicalPoints` 节点插入 | `getTopologicalSearchRadius`：层 `geometryPrecision`；未设则 1e-8（CRS 单位米时 0.001，英尺 0.0001）；线段 epsilon 1e-12（地理 CRS）/1e-8 | `qgsvectorlayereditutils.cpp:237-255,907-913` |
| QgsTracer 图上端点挂接 | 硬编码 epsilon 1e-6（图 CRS） | `qgstracer.cpp:265,281` |

用户吸附容差（`QgsSnappingConfig`）**不参与**以上任何一处拓扑匹配。

---

## 2. 桌面版跨层撤销聚合：不存在，是"仅活动层"

### 2.1 Ctrl+Z 的真实接线

- `mActionUndo` → `QgsUndoWidget::undo`（`src/app/qgisapp.cpp:3008`）→ `mUndoStack->undo()`（`src/app/qgsundowidget.cpp:148-152`）。
- 该 `mUndoStack` 只在活动层变化时被替换：`QgisApp::onActiveLayerChanged` → `mUndoWidget->setUndoStack( layer->undoStack() )`（`qgisapp.cpp:749-772`，关键行 :762）。
- 没有任何 project 级 QUndoStack（`src/core/project/` 无 QUndoStack 引用）；Qt 的 `QUndoGroup` 也只路由到"活动栈"，无法跨栈组合。

### 2.2 语义后果

一次跨 N 层的拓扑顶点拖拽产生 N 条独立宏命令（§1.2-B），分属 N 个层的栈。桌面 Ctrl+Z **只回退当前活动层的那一条**；其余层要用户手动切换活动层再按 Ctrl+Z。这与地图已锁定的决策「整手势原子撤销」相悖——**桌面 QGIS 不能作为该语义的参照实现，必须宿主自制。**

### 2.3 不建 app 库时的等价机制（可行性评估）

可行，且所需 API 全部在已构建的 core/gui：

1. **按手势驱动各层 stack（推荐）**：宿主手势管理器在每个手势开始时登记"受影响层有序表"；提交时逐层 `beginEditCommand/endEditCommand`（把每层改动收成一条宏，语义同 `applyEditsToLayers`）；撤销时**逆序**对每层 `layer->undoStack()->undo()`，重做正序 `redo()`。宏内原子性由 QUndoStack 保证，整手势原子性由宿主的逆序分组保证。需记录手势期间每层 stack 的 index 快照以支持"点击历史列表跳转"。
2. QUndoStack 宏合并（`QUndoCommand::mergeWith`）**不能跨栈**，只适合同层连续命令合并，不适配本问题。
3. 注意死区：`destroyEditCommand`（`qgsvectorlayer.cpp:4648-4669`）用 obsolete 命令技巧清栈，宿主若中途取消某层改动应走它而不是手动弹栈。

---

## 3. 避免重叠（Avoid Intersections）生效点

### 3.1 生效链路（数字化/捕获路径）

```
QgsMapToolCapture::cadCanvasReleaseEvent ... 各提交点
  → 虚函数 geometryCaptured(g)                  qgsmaptoolcapture.cpp:1825,1920-1928,2164,2197
    → QgsMapToolCaptureLayerGeometry::geometryCaptured   (GUI 层!)
        qgsmaptoolcapturelayergeometry.cpp:25-92
        Line/Polygon 模式:
          按 QgsProject::avoidIntersectionsMode() 组层:  :46-58
            CurrentLayer → [当前层]; Layers → project 列表; Allow → 跳过
          g.avoidIntersectionsV2( avoidIntersectionsLayers )   :61
          几何被差分到空 → Critical 消息 + stopCapturing,要素不入库  :66-71
```

### 3.2 `QgsMapToolDigitizeFeature` 子类是否免费获得？

**是。** `QgsMapToolDigitizeFeature : public QgsMapToolCaptureLayerGeometry`（`src/gui/maptools/qgsmaptooldigitizefeature.h:32`），而避免重叠逻辑全在 GUI 基类 `QgsMapToolCaptureLayerGeometry::geometryCaptured`（`qgsmaptoolcapturelayergeometry.cpp:25-92`，头文件自述 "automatically handles intersection avoidance"，`qgsmaptoolcapturelayergeometry.h:27-28`）。只要（a）宿主设置了 `QgsProject::setAvoidIntersectionsMode/Layers`（`qgsproject.h:1188,1195`），（b）捕获走标准提交路径（`geometryCaptured` 被调用），自定义数字化子类免费获得。项目现有 `PwbDigitizeTool`（子类化 `QgsMapToolDigitizeFeature` 到草稿层）已满足前提。

### 3.3 `avoidIntersectionsV2` 本身是纯函数（只读邻层）

`QgsGeometry::avoidIntersectionsV2`（`src/core/geometry/qgsgeometry.cpp:3596-3623`）→ `QgsGeometryEditUtils::avoidIntersections`（`src/core/geometry/qgsgeometryeditutils.cpp:375-449`）：仅面几何；对每个 avoid 层做 bbox+ExactIntersect 要素迭代（跳过 `ignoreFeatures`，:407-411），收集近邻几何 → GEOS `combine` + `difference`（:429-435）→ 返回差分后几何。**不写任何邻层**；类型塌缩成 multi 时由调用方处理。

跨层副作用都在 **app 层**，需要宿主复刻的两处：
- `QgsMapToolAddFeature::featureDigitized`（`src/app/qgsmaptooladdfeature.cpp:118-152`）：`topologicalEditing && mode==AvoidIntersectionsLayers && 线/面捕获` 时，先给 avoid 层中可编辑面层 `addTopologicalPoints(feature.geometry())`（:134-144），再给画布所有层散布拓扑点（:146-150）——注释明确"否则无法保证几何间无小缝"（:130-131）。
- `QgsAvoidIntersectionsOperation::apply`（`src/app/maptools/qgsavoidintersectionsoperation.cpp:29-138`，顶点工具在每层宏内调用，`qgsvertextool.cpp:2704-2708`）：调 `avoidIntersectionsV2` + 多部件塌缩时保留最大块并给"Restore others"消息条（:61-96）+ `topologicalEditing` 时把新产生的交点作为拓扑点散布到所有 avoid 层（:125-135）。

---

## 4. `QgsVectorLayer::splitFeatures(..., topologicalEditing=true)` 确切语义

### 4.1 层级实现（`qgsvectorlayereditutils.cpp:483-745`）

- **目标集合**：有选中则只切选中要素，否则切"与切分线 bbox ExactIntersect 相交"的所有要素（:494-531；退化 bbox 有补正 :504-528）。
- **逐要素**调 `QgsGeometry::splitGeometry(curve, newGeometries, preserveCircularForGeom, topologicalEditing, featureTopologyTestPoints)`（:554）。
- **最大块继承原要素 fid**（:559-572），原要素 `changeGeometry`（:575）；新块按字段 split policy（DefaultValue/Duplicate/GeometryRatio/UnsetField，:641-713）经 `QgsVectorLayerUtils::createFeatures` 批量 `addFeatures`（:731-737）——**一次 splitFeatures 调用内含 changeGeometry + addFeatures 多条 undo 命令，调用方必须用 beginEditCommand 包裹**（桌面工具正是如此，`qgsmaptoolsplitfeatures.cpp:116-131`）。
- `topologicalEditing=true` 的两个层内效果：(a) 传给 `splitGeometry` 用于生成 `topologyTestPoints`（见 4.2）；(b) 成功后把本要素的 test points 重新 `addTopologicalPoints` 到**本层**（:715-722）。
- 返回码：≥1 要素被切 → `Success`；0 → `NothingHappened`；否则传播单要素错误（:739-744）。

### 4.2 与 `QgsGeometry::splitGeometry` 的差异

`QgsGeometry::splitGeometry`（`qgsgeometry.cpp:1243-1325`）是**单几何纯 GEOS 操作**：

- 先把切分线顶点预插为目标几何的拓扑点（修 issue #29270，保证跨段切分有效，:1252-1277）；带 Z 面有专门的 GEOS 插值补偿（:1260-1275 注释 + 后处理）。
- 其 `topological` 参数**只决定是否计算 `topologyTestPoints`**（`qgsgeos.cpp:1111-1118` → `topologicalTestPointsSplit`，:1140-1190：GEOSIntersection 求切分线与被切几何的交点序列），**不改变切分结果本身**。
- 层级 `splitFeatures` 才管要素/fid/属性策略/undo；几何级只返回碎片。

### 4.3 跨层行为：邻层不分割，只插拓扑点

core `splitFeatures` 完全单层。跨层传播在桌面工具 `QgsMapToolSplitFeatures`（`src/app/qgsmaptoolsplitfeatures.cpp:109-163`）：

```cpp
vlayer->beginEditCommand( tr( "Features split" ) );                       // :116
returnCode = vlayer->splitFeatures( curve.get(), topologyTestPoints, true, topologicalEditing );  // :124
// Success → endEditCommand（:127）；否则 destroyEditCommand（:131）
if ( topologicalEditing && !topologyTestPoints.isEmpty() )                // :137
  for ( 画布上其它可编辑线/面层 )                                          // :140-148
    vectorLayer->beginEditCommand( "Topological points from Features split" );  // :150
    vectorLayer->addTopologicalPoints( topologyTestPoints );              // :151
    // 有改动 endEditCommand，无改动 destroyEditCommand                    // :152-160
```

**`topologyTestPoints` 的用途就是这份跨层插点清单**（+ 4.1-b 的本层再插点）。邻层**不会被同步分割**，只在切分线交点处获得新节点——迁移规格若需要"邻层同步分割"，原生语义不提供，需自行扩展。

---

## 5. QgsTracer：API 全貌、接入方式、图重建成本

### 5.1 API（core 类，`src/core/qgstracer.h:44-226`；已构建可链）

- 配置面：`setLayers`/`layers`（:55-57）、`setDestinationCrs(crs, transformContext)`（:69）、`setRenderContext`（:75，按渲染器过滤可见要素）、`setExtent`（:80，空 = 不限）、`setOffset`+`setOffsetParameters`（:92-106，追踪路径偏移）、`setMaxFeatureCount`（:111，超限拒建图 → `ErrTooManyFeatures`）、`setAddPointsOnIntersectionsEnabled`（:155，4.x 新增，交点处是否加节点）。
- 查询面：`init`/`isInitialized`（:119,122，惰性）、`hasTopologyProblem`（:128，noding 失败标记）、**`findShortestPath(p1, p2, PathError*)`**（:145）、`isPointSnapped`（:148）。PathError 枚举：ErrNone/ErrTooManyFeatures/ErrPoint1/ErrPoint2/ErrNoPath（:131-138）。
- **勘误（基线文档 §6）**：4.2 的 `QgsTracer` **没有 `setSnapTolerance`**。端点吸附容差来自常规 `QgsSnappingConfig`（见 5.2），图内挂接 epsilon 是硬编码 1e-6（`qgstracer.cpp:265,281`）。

### 5.2 接入 capture 工具的方式（GUI 层，无需 app）

- 每 canvas 一个单例 `QgsMapCanvasTracer : QgsTracer`（`src/gui/qgsmapcanvastracer.h:42`，注册表 `tracerForCanvas`，`qgsmapcanvastracer.cpp:62-65`）。宿主需自建该实例并（可选）挂 `setActionEnableTracing`/`setActionEnableSnapping` 两个 checkable QAction（:52-69）作为开关面。
- `QgsMapToolCapture::tracingEnabled()`（`src/gui/maptools/qgsmaptoolcapture.cpp:209-213`）= canvas 有 tracer 且开关 action 勾选。捕获工具的集成点：
  - 鼠标移动 `tracingMouseMove`（:227-312）：**要求 `e->isSnapped()`**（:229——端点来自常规吸附，这就是"追踪容差=吸附容差"的来源），起点用上次追踪终点 `mTracingStartPoint`（:216-224，offset 场景续接），`tracer->findShortestPath` 画临时橡皮筋并 `transientGeometryChanged` 预览。
  - 落点 `tracingAddVertex`（:315-379）：首点必须 `tracer->isPointSnapped`（:330）；路径点经 `nextPoint` 转层 CRS（含 Z/M 插值回填，:352-369）后 `addCurve` 入捕获曲线。
- **任何 `QgsMapToolCapture` 派生（含 `QgsMapToolDigitizeFeature` 子类、自制工具）免费获得追踪**，只要 canvas 上注册了启用的 tracer。项目现状未注册（基线 §6 "可链未接"）。

### 5.3 图重建成本特征（`src/core/qgstracer.cpp`）

- 建图 `initGraph`（:473-606）：层要素按 `setDestinationCrs` 重投影 + `setFilterRect(extent)` 限界 + 渲染器可见性过滤迭代 → `extractLinework`（曲线段化，:416-424）→ **全量 GEOS noding**（`GEOSNode_r`，:557-583）→ `makeGraph`。耗时三段（提取/noding/建图）有内置计时日志（:603-606）。
- **失效即全量重建，无增量**：`invalidateGraph()` 只 `mGraph.reset(nullptr)`（:702-705），下次 `findShortestPath → init()`（:753,690-699）重建。触发面：要素增删/几何变/属性变（渲染器过滤）/dataChanged/styleChanged/层移除（:630-746）；`QgsMapCanvasTracer` 追加 canvas CRS/transform/layers/**extents**（每次平移缩放）变化与吸附配置变化（`qgsmapcanvastracer.cpp:44-49`）。
- 成本护栏：`maxFeatureCount`（默认取设置 `settingsDigitizingTracingMaxFeatureCount`，`qgsmapcanvastracer.cpp:54`），超限报 ErrTooManyFeatures 并提示缩放/关层（:81-83）。图层来源按吸附模式：ActiveLayer→当前层；AllLayers→全部可见矢量层；Advanced→吸附配置层∩可见（`configure()`，`qgsmapcanvastracer.cpp:101-145`）。
- 对相图场景的推论：图幅尺寸（~16000 单位本地坐标）内要素量有限，全量重建可接受；但**每次平移缩放都会失效重建**，长会话高频缩放需注意（缓存策略或放宽 extent 是宿主可调项——`setExtent` 由宿主控制）。

---

## 6. 战略结论：构建 qgis_app 复用桌面工具 vs 继续自制瘦工具

### 6.1 构建 qgis_app 的真实成本

- **构建面**：上游 `src/app/CMakeLists.txt` 本就把 app 编成库目标 `add_library(qgis_app ...)`（:490-492），技术上可链。但依赖面新增 **QWT、Qt6::QuickControls2、Qt6::Sql、Qt6::UiTools、libdxfrw**（`target_link_libraries(qgis_app ...)`，:608-622），可选再拉 qgis_3d/qgispython；含 QML welcome screen 模块注册（:509-540）。当前 vendor 构建（core+gui+analysis+native，`-DWITH_DESKTOP=OFF`）需显著扩容，编译量含 17,772 行的 `qgisapp.cpp` 全家。
- **运行时耦合（更致命）**：桌面工具写死 `QgisApp::instance()` 单例——`QgsVertexTool` 9 处（vertex editor dock `:1738`、消息条 `:698` 等）、`QgsMapToolSplitFeatures` 构造即取 `QgisApp::instance()->cadDockWidget()`（`qgsmaptoolsplitfeatures.cpp:29`）且消息全走其 messageBar（:166-178）、`QgsAvoidIntersectionsOperation` 依赖其 messageBar + `pasteFeatures`（`qgsavoidintersectionsoperation.cpp:84-95`）。要么实例化整个 QMainWindow（不接受），要么对 vendored 源码做侵入式补丁（每次升级 vendor 都要重放，维护成本高）。
- **收益错配**：即便接通，桌面工具也**不提供**本项目最想要的整手势原子撤销（§2 桌面自己就没有）——核心收益仍要宿主自研。

### 6.2 瘦工具路线的真实工作量（本调研证明可复制）

拓扑编辑的可复用价值是**算法模式**而非工具类，且全部落点在已构建的 core/gui API 上：

| 桌面能力 | 核心机制 | 宿主复刻所需 API（全部已链） |
|---|---|---|
| 共享节点发现 | 每层 `locatorForLayer->verticesInRect(pt, 1e-8)` | `QgsSnappingUtils`/`QgsPointLocator`（gui/core） |
| 跨层手势提交 | 按层 beginEditCommand→changeGeometry→endEditCommand | `QgsVectorLayer` 全套 |
| 拓扑点散布 | 同 CRS 线/面层 addTopologicalPoints 循环 | `QgsVectorLayerEditUtils`（core） |
| 避免重叠 | `QgsProject` mode/layers + `avoidIntersectionsV2`（数字化免费，§3.2）；顶点编辑需 `QgsAvoidIntersectionsOperation` 语义（≈100 行可重写，剥掉 QgisApp 依赖） | core |
| 拓扑分割 | `splitFeatures(curve, topologyTestPoints, true, topo)` + 邻层插点循环 | core |
| 追踪 | `QgsMapCanvasTracer` 注册 + 开关 action | gui |

### 6.3 倾向性结论

**维持现有"桥接层自制瘦工具"模式，升级其算法到原生语义；不构建 qgis_app。** 理由：(1) 手势原子撤销（地图决策 #4）无论选哪条路都必须宿主自研，app 库不省这块最大工作量；(2) qgis_app 的依赖扩容 + `QgisApp::instance()` 侵入改造 + vendor 升级维护成本，远超复刻上述算法模式的成本；(3) 现有 `PwbEditPickTool` 骨架（snap 反馈、容差拾取）已覆盖交互底座，缺的只是 §1.2 的三步算法（发现联合 → 按层宏提交 → 拓扑点散布）。若未来出现复杂需求（reshape/trim-extend 等一大批桌面工具），可再评估"抽取单个 app 源文件进 bridge 编译"的中间路线（如 `qgsavoidintersectionsoperation.cpp` 剥 QgisApp），而非整库。

---

## 7. 对迁移契约票 #1281 / 工具规格票 #1282 的直接含义

### 7.1 → #1281（编辑权迁移契约）

1. **撤销权威必须分层+手势两级**：层内用 `QgsVectorLayer::undoStack()` 宏（begin/endEditCommand），手势级由宿主手势管理器维护"受影响层有序表"，整手势撤销 = 逆序逐层 `undo()`、重做 = 正序 `redo()`（§2.3）。契约需规定手势边界（鼠标释放/命令确认）与失败半程处理（`destroyEditCommand` 清理）。
2. **跨层传播的 CRS 前提**：拓扑点散布仅限同 CRS 层（`qgsvertextool.cpp:2511-2513`）；共享节点匹配在 map CRS 下 1e-8。基线 §7 的"工程 CRS 声明失配"（EPSG:4326 vs 本地坐标）在 QGIS 权威模式下会直接掐死跨层拓扑——**迁移契约必须先锁可编辑层 CRS 一致性**。
3. **拓扑匹配语义要写进契约**：共享节点=map CRS 下 1e-8 精确重合（不是吸附容差）；拓扑点插入容差=层 geometryPrecision（未设默认 1e-8/0.001m）。Python 现状 `propagate_shared_vertex` 的 1e-9 精确匹配语义与此同族，迁移时以 QGIS 值为准。
4. **每层每手势恰一条宏命令**是桌面不变式（applyEditsToLayers 模式），契约应保持，使"手势=每层一宏"成为撤销分组依据。
5. `QgsProject::setTopologicalEditing/setAvoidIntersectionsMode` 是工具行为开关而非数据约束——契约里应明确它们随编辑会话配置推送（现有 `_push_snapping_config` 已推 topoEditing，`map_stack_service.cpp:3390-3398`），但**不得**被当作校验保证。

### 7.2 → #1282（工具规格）

1. **PwbVertexTool 拓扑升级规格**（最高价值）：拖拽开始→联合 `locatorForLayer(layer)->verticesInRect(mapPt, 1e-8)` 重合节点（含选中节点集）；提交→按层宏提交 + 同 CRS 线/面层拓扑点散布（bbox 预查 + 空层 destroy 不留痕）；删除→同位置节点联合删除。参考实现坐标：`qgsvertextool.cpp:1898-1919, 2091-2096, 2320-2567, 2685-2724, 2727-2769`。
2. **数字化避免重叠零成本开通**：只需桥接推送 `setAvoidIntersectionsMode/Layers`，`PwbDigitizeTool`（经 `QgsMapToolDigitizeFeature`）自动获得（§3.2）；顶点/移动工具的避免重叠需桥接复刻 `QgsAvoidIntersectionsOperation` 语义（多部件保留最大块 + 交点散布拓扑点，§3.3）。
3. **分割命令升级**：从裸 `QgsGeometry::splitGeometry`（`geometry_service.cpp:70-84` 现状）升级为层 API `splitFeatures(curve, topologyTestPoints, true, topologicalEditing)` + 邻层拓扑点循环（§4.3）；规格需明确"邻层只插点不分割"是原生语义，如需邻层同切要另立扩展项。
4. **追踪（Tracer）接入规格**：新建 canvas 级 `QgsMapCanvasTracer` + 两个开关 action 即可让现有捕获工具免费获得（§5.2）；端点容差=吸附容差（`e->isSnapped()` 门槛）；需设定 `maxFeatureCount` 与 extent 策略（缩放失效全量重建，§5.3）。无 `setSnapTolerance` API（基线勘误）。
5. **撤销分组标注**：手势提交的宏文本沿用桌面词汇（"Moved vertex"/"Deleted vertex"/"Topological points added by ..."）可让 QUndoView 历史与桌面经验对齐；宿主手势日志额外标记跨层组。
