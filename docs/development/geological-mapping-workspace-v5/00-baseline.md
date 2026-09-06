# 00 — 基线（M0 架构审计）

基线 commit：`origin/main @ 37640957`（本分支 worktree 起点）。

## 既有架构事实（V5 开发前的权威现状）

### Workstation 壳
- `WorkstationFrame`（`ui/workstation/shell.py`）：中央**永远是**
  `CompositeDocument`（编图文档，永不浮动）；其余 12 个面板全部是宿主
  QMainWindow 的 `QDockWidget`。AppBar 是固定 QToolBar 行。
- 布局持久化：`QMainWindow.saveState` → QSettings `layout/window_state`
  （版本栅栏 v4）；`WorkstationLayoutPreset`（6 个预设）只管 dock 显隐
  矩阵，与工作流阶段无关。
- 无任何 stage/page 概念（导航 hub 页是浮动的功能页 dock，不是中央文档
  切换）。

### QGIS 栈（唯一地图渲染权威）
- vendored QGIS（`third_party/qgis`）+ pybind11 C++ 桥
  （`native/qgis_render_bridge` → `qgis_render_bridge.mapstack.QgisMapStack`）。
- `QgsLayerTreeView` + `QgsLayerTreeModel(QgsProject::layerTreeRoot())` 在
  C++ 侧创建，Python 经 `QgisLayerTreeHost`（地址边界单点转换）嵌入。
- **基线局限**：镜像层只插 root 顶层（平铺）；树回写 JSON 只有
  `{"visibility","order","renames}` 平铺图层语义；组 API 不存在。
- 桥缺失时诚实降级 `UnifiedMapCanvas` + `LayerManagerPanel`（同构 16 信号）。

### 编辑权威
- `CompositeEditController`（flat dict `VectorLayer`）+ per-layer
  `VectorEditSession`（QGIS 式编辑缓冲/undo/redo/拓扑门禁）。
- 单一 active layer 模型；工程持久化经 `UserVectorLayer`（GeoJSON 特征）+
  `map_qgis_project_xml`（呈现态信封）。

### Catalog / 溯源
- `DataCatalogService`（SQLite：assets/versions/runs/lineage/run_inputs/
  run_outputs）+ `CatalogPort` 协议；`FreshnessService` 已有 run 级评估。
- `MapProduct` 组装器（fail-closed 溯源）已有。

## V5 必须解决的缺口（本分支范围）
1. 无阶段状态机——三个编图阶段靠用户手工组织。
2. 图层树平铺——数百图层无结构、无角色、无阶段归属。
3. 无跨阶段版本依赖/过期提示——上游更新后下游静默变旧。
4. 无 RAW→DERIVED 保护——原始相图可被直接编辑。
5. 无阶段化工具/面板上下文。

## 边界（不在本分支）
Kriging/IDW 内核、测井引擎、Harness DAG、Catalog schema、Design System、
QGIS 渲染引擎——全部复用现有 production service。
