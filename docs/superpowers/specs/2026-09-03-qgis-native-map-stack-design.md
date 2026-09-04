# QGIS 原生地图栈设计：图层管理 / 矢量显示 / 矢量编辑与 QGIS 完全一致

- 日期：2026-09-03
- 状态：已批准（用户确认方案 A + 硬依赖 + 三块一体 + 权威模型调整）
- 里程碑进度：M1–M4 已完成并合入 main（M4 HEAD `629ba15a`）。M5 收尾切片见 `docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m5-design.md`（mini-QgsProject XML + 生产路径去掉环境变量降级 + QGIS CI 门禁）；本切片在 `feat/qgis-native-map-stack-m5` 实施。
- 范围：工作站地图区（综合编修/平面图）的图层管理、矢量显示、矢量编辑、图层属性

## 背景与目标

用户要求图层管理、矢量显示、矢量编辑（含图层属性）与 QGIS **完全一致**。

已批准的约束：

1. **方案 A：嵌入 QGIS 原生控件**（`QgsMapCanvas` / `QgsLayerTreeView` / `QgsVectorLayerPropertiesDialog` / `QgsMapTool` 编辑栈），不是宿主仿 QGIS 的行为对齐。
2. **完全自包含**：不依赖系统安装的 QGIS；所有 QGIS 源码 vendored 在仓内（`third_party/qgis`，QGIS 4.2，已构建 `libqgis_core/gui/analysis`）。
3. **硬依赖，无双轨**：地图区只跑 vendored QGIS 栈；fallback 渲染器与自绘编辑叠加层**删除**；桥不可用时地图区明确报错退出。
4. **三块一体**：画布+编辑、图层树、属性对话框作为一个大项目推进，按里程碑排序交付。
5. **权威模型调整**：`QgsProject` 成为地图图层的运行时权威；我们的工程文件仍是持久化权威（井/地震/测井不是 QGIS 图层）。

## 现状（与目标的主要差距）

已是真 QGIS 的部分：渲染器/符号系统权威（renderer XML）、三个原生符号对话框（`gui_service.cpp`）、几何运算（`geometry_service.cpp`）、vendored 构建基础设施（`setup.py` ExternalProject）。

仍是宿主仿 QGIS 的部分：图层树（自绘 `QTreeWidget`）、图层属性对话框（自定义 5 页，QGIS 原生为 10+ 页）、矢量编辑交互（自绘 QGraphicsItem 叠加层，非 `QgsMapTool` 栈）。

已核实的构建事实：

- vendored 构建产物位于 `native/qgis_render_bridge/build/qgis-vendor/output/`，含 `libqgis_{core,gui,analysis,native}.so.4.2.0` 与 `data/resources/qgis.db`。
- provider 插件目录 **为空**：当前 ExternalProject 目标仅 `resources qgis_core qgis_gui qgis_analysis`。memory provider 内置于 core（矢量编辑不受影响）；栅格/数据源加载需补编 `provider_gdal`、`provider_ogr`（GDAL 已在 `native/gdal-vendored` vendored）。
- 现有桥 `qgis_render_bridge`（pybind11，约 2400 行）已验证 QGIS GUI 控件可与 PySide6 同进程共存（三个原生对话框在进程内模态运行）。
- 应用当前从未 `import qgis.core`；唯一通道是 pybind11 窄桥。

## 技术路线（已批准）

扩展现有 pybind11 桥 + `shiboken6.wrapInstance` 嵌入：

- C++ 侧创建 QGIS GUI 控件，以 `uintptr_t` 返回 QWidget 指针；Python 侧 `shiboken6.wrapInstance` 包成 PySide6 QWidget 嵌入 shell 布局。
- QGIS 的 Qt 信号在 C++ 侧转成 pybind11 `std::function` 回调，Python 注册普通 callable。

被否决的替代方案：

- **构建 QGIS 官方 Python 绑定（sip/PyQt6）**：与 PySide6 同进程混用不受支持；全仓迁 PyQt6 不值得。
- **QGIS 独立进程嵌入**：Wayland 下跨进程嵌入不可行。

## 设计

### 1. 总体架构

```
PySide6 shell（app_bar / dock / 状态栏不变）
 └─ QgisMapStack（Python 新增包 paleo_workbench/ui/qgis_stack/）—— 唯一与桥交互的层
     └─ qgis_render_bridge.mapstack（pybind11，扩展现有模块）
         └─ vendored QGIS 4.2（third_party/qgis）
```

`QgsProject` 单例为地图图层运行时权威；`QgsMapCanvas` 嵌入综合编修文档区中央；图层树、属性对话框、编辑工具全部原生。fallback 渲染器与自绘编辑叠加层删除（非保留开关）。

### 2. C++ 桥扩展

新文件 `native/qgis_render_bridge/src/map_stack_service.{hpp,cpp}`，在现有 pybind11 模块加 `mapstack` 子模块：

- **生命周期**：`create_project()` / `create_canvas(parent_addr)` / `set_prefix_path()`（初始化 `QgsApplication` 的 resources/svg 路径，指向 vendored output）。
- **控件句柄**：创建 canvas / `QgsLayerTreeView` / `QgsLayerTreeMapCanvasBridge`，返回 `uintptr_t`。
- **图层操作**：`add_vector_layer / add_raster_layer / remove / rename / set_visibility / set_opacity / zoom_to_layer / set_crs`。
- **编辑栈**：`create_map_tool(canvas, kind)`（pan/zoom/select/add-feature/vertex/move/split/reshape/measure）、`set_map_tool`、`set_current_layer`、snapping config 读写、`start_editing / commit / rollback`、`undo / redo`。
- **属性对话框**：复用 `gui_service` 的 DialogSession 模式，新增 `run_layer_properties_dialog(layer_id)`（`QgsVectorLayerPropertiesDialog` / `QgsRasterLayerPropertiesDialog`）。
- **信号**：`QgsProject::layersAdded/removed`、`QgsMapCanvas::xyCoordinates/extentsChanged`、编辑提交等 → Python 回调。
- 规模估计：约 1500–2000 行新 C++，绑定函数约 40–50 个；模式参照现有 `bindings.cpp` / `gui_service.cpp`。

### 3. Python 嵌入层（`paleo_workbench/ui/qgis_stack/`，新增小包）

- `widgets.py`：`wrapInstance` + 薄封装（`QgisCanvasHost(QWidget)` 等），桥句柄 → 可进布局的 PySide6 控件。
- `events.py`：桥回调 → Qt Signal 转发；非 GUI 线程回调用 `QTimer.singleShot(0, …)` marshal 回主线程。
- `project_io.py`：工程文件 ↔ `QgsProject` 序列化（见 §7）。
- 规模估计：约 600–800 行。

### 4. 图层管理（替换 `LayerManagerPanel`）

`QgsLayerTreeView` + 自定义 `QgsLayerTreeViewMenuProvider` 子集：原生右键菜单（缩放至图层、属性、移除、重命名、分组、可见性、不透明度）。dock 壳保留，内容换原生树。QGIS 语义（显示顺序=渲染顺序、组、互斥分组）由 QGIS 提供。

### 5. 图层属性（替换 `MapLayerPropertiesDialog`）

`QgsVectorLayerPropertiesDialog` 全量页（信息/源/符号化/标注/字段/属性表单/Joins/图表/渲染/元数据）模态运行；栅格/网格图层用 `QgsRasterLayerPropertiesDialog`。现有 `map_symbology_bridge` 三对话框由属性对话框内嵌的 `QgsRendererPropertiesDialog` 取代。

### 6. 矢量编辑（替换 `CompositeEditController` + map_edit 叠加层）

- 工具条按钮 → `canvas.setMapTool()`：原生 `QgsMapToolAddFeature`（点/线/面）、`QgsMapToolMoveFeature`、`QgsVertexTool`、`QgsMapToolSplitFeatures`、`QgsMapToolReshapeFeatures`、`QgsMapToolSelect`、`QgsMapToolMeasure`；捕捉用 `QgsSnappingUtils` + `QgsSnappingConfig`。
- 撤销/重做接 `QgsVectorLayerEditBuffer` undo 栈（原生，含属性编辑）。
- 识别用 `QgsMapToolIdentifyFeature`。
- `VectorEditSession` / EditCommand 事务模型退役（edit buffer 接管）；`geometry_service` 的 QGIS 几何运算保留（算法场景仍在用）。

### 7. 持久化

工程文件格式不变，新增"地图图层段"：地图图层以 mini-`QgsProject` XML 嵌入（`QgsProject::write` 到字符串嵌入，打开时 `read` 恢复），含源 URI、crs、renderer/labeling XML、可见性/不透明度/顺序/分组。旧 `qgis_style` payload 迁移读取。

### 8. 构建与分发

- `setup.py` 的 vendored ExternalProject 目标增加 `provider_gdal`、`provider_ogr` 及对应 CMake 选项。
- 开发机一次性安装：`pip install -e native/qgis_render_bridge`（数小时级构建）。
- 删除 `qgis_backend_probe` / `PALEO_DISABLE_QGIS_RENDERER` 降级逻辑；桥不可用 → 地图区构造时明确报错退出。
- CI：`.github/workflows/qgis-renderer.yml` 专轨扩展为跑地图栈测试。

### 9. 测试策略

- offscreen 平台下 `QgsMapCanvas` 可渲染（QGIS 自身测试同法），pytest-qt 驱动。
- 分层：桥绑定单测（参照 standalone_test 模式）、嵌入层（wrap/信号 marshal）、集成测试（图层增删改 → canvas 帧像素断言，基准为 QGIS 渲染输出）。
- fallback 相关测试（`tests/test_map_render_backend.py` 等约 10 个文件）随 fallback 删除而移除/改写。

### 10. 里程碑（项目内依赖顺序）

- **M1 地基**：provider 补编 + `mapstack` 桥骨架 + canvas 嵌入综合编修区（显示/缩放/平移）→ 可演示。
- **M2 图层**：`QgsProject` 权威化 + `QgsLayerTreeView` 图层管理 + 属性对话框 → 可演示。
- **M3 编辑**：map tool 编辑栈 + 捕捉 + 撤销重做 → 完整交付。
- **M4 只读页**（已完成）：见 `docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m4-design.md`。
- **M5 收尾**（本切片）：见 `docs/superpowers/specs/2026-09-04-qgis-native-map-stack-m5-design.md`（mini-`QgsProject` XML、生产路径去掉 `PALEO_DISABLE_QGIS_RENDERER`、QGIS CI 专轨执行 mapstack 测试）。MapEditView 原生化、编修迁出 `QgsProject::instance()`、删除 `FallbackMapRenderBackend`、`provider_gdal/ogr` 仍不在本程序。

## 风险

1. provider 补编的依赖链（GDAL 已 vendored，预期可接上，需验证 CMake 选项对齐）。
2. `QgsVectorLayerPropertiesDialog` 的部分页（3D、依赖管理器）可能引用未构建组件，需在桥里裁剪。
3. 编辑工具与 Agent 自动化（HarnessExecutor）的对接必须保留：Agent 指令仍走项目控制器，落到 QgsProject 操作上。
4. 开发机首次构建时长（数小时）；需要在 README/AGENTS.md 写明。

## 非目标（YAGNI）

- QGIS 插件体系（Python 插件、Processing 工具箱）不在本期范围。
- 3D 视图页、依赖管理器页裁剪而非实现。
- 井/地震/测井页面不改动（它们不是 QGIS 图层域）。
