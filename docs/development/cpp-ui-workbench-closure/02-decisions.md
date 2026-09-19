# CONV-27 Decisions

- **D1 组件落 libs/ui 而非 apps/**：native-product 线（开放 PR）正在拆 main.cpp/改
  main_window 服务层。新 UI 组件以 `Pwb::Ui`（纯 Qt：readiness 内核/stage dock/布局）
  + `Pwb::UiWorkbench`（QGIS 耦合：树面板/编辑工具/属性/约束）两个库交付，
  main_window 只加 `#ifdef PWB_WITH_CONV_27` 挂钩 —— 合并冲突面压到最小。
- **D2 active layer 同步走 join key**：旧 `onActiveLayerChanged` 用 tree 行号映射
  `layerIdsTopFirst()[row]`，分组/重排即错位。LayerTreePanel 用
  `currentLayerChanged → layer_adapter::layer_id_of` 解析领域 id；分组增删重排
  不再影响业务状态（facts 按 id 寻址）。
- **D3 数字化工具不直接写层**：`QgsMapToolDigitizeFeature` 的
  `featureDigitized` 是空钩子、只发 `digitizingCompleted` —— 正合架构：工具
  发信号，`EditController::add_feature_geojson`（beginEditCommand/addFeature/
  endEditCommand）是唯一写入路径，与 move_vertex 同构、可撤销。
- **D4 delete_selected 落 EditController**：`QgsVectorLayer::deleteSelectedFeatures`
  本身是一个 undoable 命令宏；加法式新方法（不改既有签名），向后兼容。
- **D5 阶段门沿用评估器白名单**：不新建阶段过滤表。`map_export` 仅
  integrated_compilation、`factor_workbench` 仅 constraint_factor 已是
  evaluator 契约；默认阶段 = Python 默认 facies_calibration（阶段语义开机即生效）。
- **D6 就绪度输入用显式 struct**：Python 读 duck-typed ProjectDocument；C++ 用
  `ReadinessInputs`（宿主从 live session/store 组装），检查 id/状态梯/文案逐字移植。
  诚实偏差见 01-findings.md。
- **D7 图层属性 = QGIS 原生 dialog + QML sidecar**：`QgsRendererPropertiesDialog`
  OK 即 `setRenderer`；持久化用 `exportNamedStyle` → `<数据文件>.qml`，重开时
  `loadNamedStyle` 复用。不自造低配 style editor。
- **D8 facts 显示走 layer metadata**：树 tooltip 由
  `QgsLayerTreeModel::ToolTipRole → layer->metadata()` 渲染；角色/成熟度/锁写入
  metadata abstract（原生通道，随层持久），不自定义 delegate。
- **D9 布局与业务态分离**：`WorkbenchLayout` 只管 QMainWindow geometry/state
  （QSettings，版本键守护，损坏/未知版本→默认布局）；业务态在 store/catalog/工作副本。
- **D10 选择/编辑信号驱动 enablement**：`QgsProject::layerAdded` 挂
  `selectionChanged/editingStarted/editingStopped → refreshActionStates`，
  enablement matrix 由 `platform.ui_closure` 钉死。
- **D11 vendor SDK 复用**：本机 Linux/GCC/Qt 的 qgis-vendor 树已有 core；
  gui/analysis 已编译对象齐全，仅补链接（-j2、单重型任务、清退遗留 ninja）。
  不重复构建 QGIS。
