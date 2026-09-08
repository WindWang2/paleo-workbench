# 00 — Basene（基线审计）

> Worktree: `.worktrees/qgis-native-authoring-v7`，branch `feat/qgis-native-authoring-v7`，基线 `db21f6cf`（= main @ 2026-09-08）。
> 本文档为代码修改前的只读审计结论。审计方式：三路并行深度审计（native bridge / Python 双轨 / UI 集成）+ 关键文件人工复核。

## 1. 基线事实

### 1.1 native bridge（`native/qgis_render_bridge/`，~7.5k 行 C++）

- 版本 `0.2.17a0`；vendored QGIS **4.2.0**（`third_party/qgis`，upstream tag `final-4_2_0`，commit `ca5812c8`）。
- 模块组成：
  - `bindings.cpp`（FFI，pybind11；`QgisRenderBridge` 渲染类 + `geometry` 子模块 15 函数 + `mapstack.QgisMapStack` 74 方法 + 3 个原生对话框入口）
  - `qgis_render_bridge.cpp`（离屏渲染；进程级 QGIS 生命周期 `g_qgis_lifecycle_mutex`，只 init 不 exitQgis）
  - `map_stack_service.cpp`（QgsMapCanvas/QgsProject/QgsLayerTreeView/镜像层/工具分派/捕捉配置/项目 XML/布局导出）
  - `edit_tools.cpp`（`PwbEditPickTool` 基类 + `PwbVertexTool`/`PwbMoveTool`/`PwbSelectTool`；数据不落层，意图回调 Python）
  - `geometry_service.cpp`（union/split_by_line/make_valid/buffer/... 15 个 QgsGeometry 纯计算）
  - `gui_service.cpp`（renderer/symbol/style 三个模态对话框）
  - `style_codec.cpp`（legacy style ↔ renderer XML）
- **已有 native 工具**（`set_map_tool` kind 全集）：`pan`/`zoomIn`/`zoomOut`/`addPoint`/`addLine`/`addPolygon`/`vertex`/`move`/`select`/`identify`。display 模式只允许前三个。
- **capability probe：C++ 层不存在**。仅有 `initialized()`、`version`、`diagnostics()`、`native_tool_busy()`。探测散落 Python 侧 5+ 处（见 §3）。

### 1.2 构建/环境事实（本机 Windows）

- **本机（win32）从未构建过 QGIS 桥**：无 build 目录、无 `.pyd`、无 vendor 产物；v5/v6 的 QGIS 测试证据均在 Linux 机（`/home/kevin/...`）产生。
- 本机已有资源：
  - VS2022 Community + MSVC 14.38、CMake/Ninja（`C:/Qt/Tools/`）、31.2GB RAM、16 核、磁盘 1.2T 空闲。
  - `C:/deps/`：Qt **6.8.0**（msvc2022_64 全套 cmake 配置）、`qca-install`（Qca-qt6）、`kc-install`（Qt6Keychain）、`winflexbison`、vcpkg（GDAL 3.x/GEOS/PROJ/sqlite3 等已编译包，classic 模式）。
  - vcpkg 缺 `libzip`（QGIS `find_package(LibZip REQUIRED)` 硬依赖）→ 本 Goal 补装。
- 并行分支 `feat/qgis-geolayer-cartography-v7`、`feat/workstation-ux-v7` 也在本机（各自 worktree + venv，PySide6 6.11.2）。**无活跃构建进程**（vcpkg 锁为 8/22 陈旧残留）。
- 权威裁决：Qt 6.8.0（QGIS 4.2 官方支持代次）+ PySide6 **6.8.0.1**（同版本 Qt ABI，进程内与桥共享同一 Qt 运行时）。pyproject `pyside6>=6.6` 兼容。

### 1.3 Python 侧（双轨现状）

数据权威单轨，交互前端双轨：

- **数据权威**：`VectorLayer` + `VectorEditSession`（`mapping/vector_layer.py`）——命令模式、undo/redo、journal、revision；RAW/stage gate 在 `CompositeDocument._role_allows_editing`（`composite_document.py:1400-1429`）单点注入。
- **交互前端**：
  - 原生轨（production）：`QgisCanvasShim`（`ui/qgis_stack/canvas_shim.py`，1008 行）把 Python 工具 id 映射为原生 QgsMapTool；交互结果经 `set_digitize_callback`/`set_edit_pick_callback`/`set_selection_callback` 回灌 Python 工具 `commit_*` 落会话。
  - 回退轨：`UnifiedMapCanvas`（纯 Python 鼠标事件路由 + `FeatureSpatialIndex`/`SnappingService` Python 自算几何/捕捉）。`CompositeDocument._create_canvas`（`composite_document.py:861-877`）优先 shim、异常降级。
- **工具状态**：`MapActionState`（纯布尔）→ `MapActionController.update_state`；palette 侧已有 `UIContextSnapshot`/`CommandAvailability(enabled, reason)`（禁用带原因），**QAction 工具条侧无 reason 通道**。`ToolContext`/`ToolAvailability`/`CapabilitySnapshot` 全仓 0 命中。

## 2. 能力对照矩阵（基线）

判定基准：production = 桥可用时工作站 `CompositeDocument` 的实际执行链。

| Capability | Python 实现 | QGIS/native 实现 | 当前 production | 重复/漂移 |
|---|---|---|---|---|
| pan | `PanTool` / UnifiedMapCanvas 拖拽 | `QgsMapToolPan`（map_stack_service.cpp:1128） | native | 双实现，有意降级路径 |
| zoom | `ZoomTool` + 滚轮 | shim `zoom_by`→`set_canvas_extent`；原生 zoomIn/Out 工具 | native | 双实现 |
| identify | `FeatureSpatialIndex.identify`（map_interaction.py:293）+ `identify_all` | `QgsMapToolIdentifyFeature`（:2391）→`native_identified` 信号 | **双数据源**：面板走 Python，原生结果**无消费者** | ⚠ 漂移 |
| select（单击） | `SelectTool` + Python 索引 | `PwbSelectTool`（QgsMapToolSelectionHandler）→`commit_selection` | native 交互 + Python 选集权威 | 单权威，健康 |
| rectangle select | `RectangleSelectTool` | 同上（shim 把矩形也映射 kind=select） | native 交互 | 健康 |
| measure | `MeasureDistanceTool`（`math.dist` 自算） | **无原生工具**（shim 用视口事件过滤器 hack，canvas_shim.py:67-119） | **恒 Python** | ⚠ 唯一纯 Python 交互工具 |
| add point/line/polygon | `_CaptureTool` + Python `_snap` | `QgsMapToolDigitizeFeature`×3 → `commit_geometry` | native 采点 | 健康（捕捉执行体双轨） |
| move feature | `MoveFeatureTool` | `PwbMoveTool` → `commit_move` | native 交互 | 健康 |
| vertex edit | `VertexTool` | `PwbVertexTool` → `commit_vertex_move` | native 交互 | ⚠ 工作站未接 `on_vertex_committed`（拓扑传播断线，composite_editing.py:931） |
| delete | UI 命令 → `session.delete_feature` | 无（UI 命令，无画布交互） | Python | 单轨合理 |
| split | `vector_operations.split_polygon_by_line`（Shapely fallback） | `geometry_service` → 桥 `split_by_line`（QgsGeometry::splitGeometry） | 桥优先 QGIS 引擎 | 有序 fallback |
| merge | `vector_operations.merge_selected_polygons`（Shapely fallback） | 桥 `union` | 桥优先 | 有序 fallback |
| undo/redo | `VectorEditSession.undo/redo` | 无 | Python | 单轨合理（会话权威） |
| snapping | `SnappingService`/`FeatureSpatialIndex.snap`（vertex/endpoint/segment/midpoint/intersection/reference/grid） | `QgsSnappingConfig` 下推 + `snapToMap` 执行 | 配置单源投影（`_push_snapping_config`），执行体两轨 | ⚠ endpoint/intersection/grid 不下推；Python 执行体仍服务 fallback 采点 |
| topology 校验 | `TopologyService`（Shapely） | 桥 `is_valid`/`make_valid` 存在但**校验恒走 Shapely** | **恒 Shapely** | ⚠ 与 split/merge/repair 的桥优先策略不一致 |
| geometry repair | `topology.repair_invalid_geometry`（Shapely 兜底） | 桥 `make_valid` 优先 | 桥优先 | 有序 fallback |
| selection semantics | `VectorLayer._selection`（唯一权威）+ QGIS 修饰键语义 | QgsHighlight 只是视觉投影 | Python 权威 | 健康（全仓最严格单权威） |
| edit session | `VectorEditSession` | 无（镜像层只读，无 edit buffer） | Python | 单轨合理 |
| save/rollback | `commit_changes`/`rollback_changes` + RAW/stage/拓扑门禁 | 无 | Python | 单轨合理 |
| layer properties | legacy 对话框（fallback） | `exec_layer_properties`→QgsVectorLayerProperties | 原生栈→QGIS 对话框 | 有序 fallback |
| attribute editing | `CompositeAttributeTableDialog`→`session.change_attribute` | 无 | Python | 单轨合理 |

## 3. 已识别缺口（vs Goal）

1. **无统一 capability snapshot**：探测散落 5+ 处（`qgis_style.qgis_bridge_available` 仅 import 探测；`map_render_backend.qgis_backend_probe` 运行时探测；`layer_group_controller` hasattr 探测；`canvas_shim.export_capabilities`；`geometry_service._BRIDGE_PROBE`）。无 `unavailable/degraded` 统一语义，UI 无法直接消费。
2. **无 ToolContext/ToolAvailability**：工具条 enabled 是布尔，无人类可读 disabled_reason；启用条件分散在 `MapActionController.update_state` + `CompositeEditController.activate_tool` 装配守卫 + `CompositeDocument._split_inputs` 特例三处。
3. **measure 无 native 工具**（视口事件过滤器 hack 维持 Python 执行）。
4. **native identify 结果无消费者**（信号发射后无人 connect，面板数据走另一套 Python 计算）。
5. **拓扑校验恒 Shapely**（桥可用时不用 QGIS GEOS 校验，策略不一致）。
6. **工作站顶点编辑未接拓扑传播**（编图页接了，工作站没接——行为漂移）。
7. **无 EditDelta contract**：编辑意图直接进 `EditCommand`，无 `source_tool`/`qgis_capability`/order token 等归一化契约。
8. **`map_tools.py` 无 fallback 显式标识**（docstring 未声明其为非 production 执行器）。
9. **snapping endpoint/intersection/grid 模式 QGIS 无对应**：Python 专有模式在生产原生轨实际不可用（原生捕捉只收到 vertex/segment/midpoint 子集）。

## 4. 测试基线

- 43 个 `pytest.mark.qgis` 测试文件；`tests/qgis_support.py` + `conftest.py` 提供 `PALEO_REQUIRE_QGIS` fail-closed 门、QSettings 隔离、timer fence、shim 收尾 fixture。
- 本机桥未构建 → 当前所有 qgis 用例处于 skip 状态（`QGIS_SKIP_REASON`）。
- 非 QGIS 测试可在 venv 内全量运行（基线验证于本 worktree：见 05-verification.md）。

## 5. 边界与并行分支

- 本 Goal 拥有：`native/qgis_render_bridge/**`、`paleo_workbench/ui/qgis_stack/**`、新增 authoring/capability adapter、相关 tests/docs。
- 尽量不动：`ui/components/**`、`workstation/shell*`、design system、mapping factor algorithms、geological cartography product model。
- 跨模块契约改动须最小化 + compatibility adapter + `03-decisions.md` 记录。
- 并行分支共享：vendored QGIS 源（同 commit）、`C:/deps` 依赖树、（完成后）本 worktree 的 vendor build 产物（按 setup.py `PALEO_QGIS_REUSE_VENDOR` 官方约定向兄弟 worktree 开放复用）。
