# UI-13 findings — workstation-composite（13 Python 源 → 22 核 + 12 壳 + 2 QGIS 适配）

Branch: `feat/cpp-ui-workstation-composite`（base `origin/main`，合并至
`7bf29aae` — 含 UI-12 workstation-shell 与 UI-14 root controllers）。
Worktree: `../worktrees/cpp-ui-workstation-composite`。切片 UI-13 of
the M10 UI→C++ migration：综合编修区 —— 矢量图层/编辑会话、拓扑服务
与检查器、合并计划、CRS 门、捕捉服务/空间索引、地图工具状态机、阶段
词汇/档案、属性模式、图层装饰、采集/地质层规范、QGIS 图层模式、模板、
地图快照/覆盖、CompositeEditController 及全部 Qt/QGIS 壳。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `workstation/composite_editing.py` | 编辑权威：图层 CRUD（`GEOMETRY_KINDS` 前置校验 → `unsupported geometry kind`）、模板解析（模板 kind/style/schema 覆盖入参）、active layer 链（`set_active_layer` 走全链 + snapping push）、编辑会话持有、roles/编辑门、几何命令经注入 ops seam、native/fallback 能力区分、持久化快照（`pwb/doc_id` + `__pwb_fid`）、选择语义（replace/Ctrl 并/Shift 差/Ctrl+Shift 交） | `composite_controller`（Qt-free：registry/kinds/templates/schemas/roles/snapping/topology/canvas hooks/events）+ `composite_controller_qt`（QObject 桥：core 事件 → Qt 信号，不引入第二权威） | ported |
| `workstation/composite_document.py` | 文档壳组装：timeline/canvas host/constraint HUD/identify 面板/拓扑面板/QC hub/状态栏/编辑控制器/facies 工具/图层管理/输入树/linked views/阶段面板+条；`set_canvas(QWidget*, uses_native_stack)` 区分原生/兜底；内容变更 120 ms debounce、结构变更立即重建、extent 仅刷轻量状态；QGIS 关停显式有序 | `composite_document`（Qt 壳） | ported |
| `workstation/composite_attribute_table.py` | 属性表对话框：controller 图层绑定、selectionModel→`selectedIndexes`、选中集 `std::set`→`vector` 回写 `set_selection` | `composite_attribute_table`（Qt 壳） | ported |
| `workstation/composite_panels.py` | identify 结果面板、捕捉设置对话框、输入树、linked views 等组合面板 | `composite_panels` + `layer_manager_panel`（Qt 壳） | ported |
| `workstation/mapping_stage_bar.py` | 阶段条：阶段 token/切换请求信号 | `mapping_stage_bar`（Qt 壳）+ `stage_vocabulary`/`stage_profiles`（Qt-free 核：阶段词汇/evaluator 走 canonical `tool_policy`） | ported |
| `workstation/mapping_stage_panel.py` | 阶段面板：阶段设置 + 动作可用性投影 | `mapping_stage_panel`（Qt 壳） | ported |
| `workstation/layer_decorations.py` | 图层装饰：角色/状态徽标、装饰 token | `layer_decorations`（Qt-free） | ported |
| `workstation/facies_selector.py` | 相级联选择：三级 combo（父变 → 子级清空保不住即清）、空哨兵任选停、相选/相改对话框（taxonomy 列、预选、selection chain → `level` 写入） | `facies_selector`（Qt 壳：cascade + `FaciesSelectionDialog` + `FaciesChangeDialog`） | ported |
| `workstation/merge_features_dialog.py` | 合并对话框：records 展示、字段值编辑、结果 payload | `merge_features_dialog`（Qt 壳）+ `merge_plan`（Qt-free 计划核） | ported |
| `workstation/topology_checker_panel.py` | 拓扑检查面板：错误列表（id/rule/fixable/bbox/feature/layer）、ignore keys、allowed gaps、持久化豁免、run/fix seam、blocking-error 过滤、last-run 状态、zoom 请求信号 | `topology_checker_panel`（Qt 壳）+ `topology_checker`/`topology_service`（Qt-free：忽略/豁免/run-fix seam/计数） | ported |
| `workstation/tool_page_dialog.py` | 工具页对话框 | `tool_page_dialog`（Qt 壳） | ported |
| `workstation/attribute_schema.py` | 属性模式：字段/别名/schema 构建 | `attribute_schema`（Qt-free） | ported |
| `workstation/linked_workspace.py` | 联动解译工作区：视图协调控制器绑定（UI-14 Qt 壳，CONV_30 门） | `linked_workspace`（Qt 壳源码在 `pwb_ui_composite_qt`，**仅 `TARGET Pwb::UiControllersQt` 时编译**） | gated（见偏差） |

支撑核（`composite_editing` 依赖面，全部 Qt-free）：`vector_layer`
（图层+`VectorEditSession`）、`geometry`、`map_interaction`（空间索引+
`SnappingService`）、`map_tools`（工具状态机）、`map_snapshot`（快照/
覆盖）、`crs_gate`、`capture_spec`、`geological_layer_spec`、
`qgis_layer_schema`、`templates`、`roles`、`layer_groups`、
`map_styles`、`snapping_profiles`、`merge_plan`。

## 结构

`libs/ui_composite/`（三 target，同 ui_workstation/ui_review 先例）：

- **`pwb_ui_composite`**（`Pwb::UiComposite`，STATIC，Qt-free，不链
  Qt）— 22 TU。PUBLIC 链 `Pwb::Domain` + `Pwb::ToolPolicy`（canonical
  工具/阶段门权威）+ `Pwb::UiDataCore`（map-edit 几何/命令词汇）+
  `Pwb::UiWorkstation`（阶段面板复用的状态语言投影）。
- **`pwb_ui_composite_qt`**（`Pwb::UiCompositeQt`，AUTOMOC，仅
  `TARGET Qt6::Widgets`）— 11 壳 TU + `linked_workspace`（COND:
  `TARGET Pwb::UiControllersQt`）。链 `Pwb::UiComposite` + `Pwb::Ui`
  （stage_readiness 头）+ `UiShellQt` + `UiWidgets`。
- **`pwb_ui_composite_qgis`**（`Pwb::UiCompositeQgis`，仅 `Pwb::Qgis`
  + `Pwb::UiWidgetsQgis` + `_qt` 在场）— `qgis_geometry` +
  `composite_qgis_canvas` + 桥 `geometry_service.cpp` 编译进本目标
  （同 `pwb_qgis` 的 CONV-29 复用式）。

## 服务 seam（不移植不伪造）

| seam | 服务域 | 承接方式 |
|---|---|---|
| `ICompositeGeometryOps` | Python `vector_operations`/`geometry_operations`/`geometry_service`：merge/split/makeValid/multipart/trim/extend/reverse/simplify/smooth/offset/rotate/scale/centroid/reshape/add_part/delete_part | `composite_controller.hpp` 纯虚；`qgis/QgisCompositeGeometryOps` 为真 QgsGeometry 实现；缺引擎 → 命令诚实拒绝，不伪造成功 |
| `INativeEditing` | 原生 QGIS 编辑（桥 `native.` 调用族） | controller seam；原生编辑期 QGIS 可变几何为唯一权威，不引第二可变源 |
| TopologyService validate/validate_many | 几何校验 | `set_validate_fn`/`set_validate_many_fn`；`install_geometry_engine` 注入 `qgis_validate_geometry`/`qgis_validate_geometries` |
| `repair_invalid_geometry` 后端 | makeValid 修复 | `qgis_repair_geometry`（`QgsGeometry::makeValid`） |
| `CrsValidator` | CRS 可解析判定 | `crs_parseable` 注入；无 validator → 非空回退语义 |
| merge 确认 / geology 门 / `CompositeCanvasHooks` | 对话框确认、地质门、画布交互 | 全注入；`CompositeQgisCanvas` 绑 `QgisCanvasShim`（snapshot 发布经既有 `mirror_snapshot_to_project`，未变层保留原生对象） |
| `linked_workspace` 视图协调 | UI-14 `Pwb::UiControllersQt` | 目标缺席 → 面板诚实缺席（不编不进库） |

## 修缺记录（构建期暴露）

| 位置 | 问题 | 修法 |
|---|---|---|
| `geometry.cpp` | `crs_parseable` 定义按值参（`std::string`）与头 `const std::string&` 声明形成另一重载 → 链接 undefined | 定义签名对齐 `const std::string&`，函数体内复制 |
| `composite_attribute_table.cpp` | `QTableView::selectedIndexes()` protected；`std::set`→`vector` 形参不匹配 | 走 `selectionModel()->selectedIndexes()`；选中集转 vector 再 `set_selection` |
| Qt 壳 | `stage_readiness.hpp` 头在 `Pwb::Ui` 未链 | `_qt` 目标加 `Pwb::Ui` |
| `composite_controller_qt.cpp` | Qt `emit` 宏撞 core 事件回调名 | 直调 `controller_->events.state_changed`（判空后） |
| `composite_document.hpp` | `QVBoxLayout` 未声明 → 签名解析错位 | 前向声明/包含补齐 |
| `merge_features_dialog.hpp` | 缺 `using pwb::domain::Json` → 成员声明级联错位 | 补别名 |
| `qgis_geometry.cpp` | `QgsGeometry::boundary()` 不存在（API 在 `QgsAbstractGeometry`） | `constGet()->boundary()` 取抽象边界再包 `QgsGeometry`；空 → 回退几何本体 |
| `composite_qgis_canvas.cpp` | `MirrorSnapshot`/`MirrorLayerSpec` 仅前向声明 | 补 `mirror_snapshot.hpp` 实 include |
| `qgis_geometry.hpp/.cpp` + 测试 | `validate_geometry`/`repair_geometry` 与 core `vector_layer.hpp` 同名 → `using namespace` 双名歧义 | 加 `qgis_` 前缀（`qgis_validate_geometry`/`qgis_validate_geometries`/`qgis_repair_geometry`） |
| `composite_controller.cpp` | `create_layer` 模板分支后才查 kind（Python 先验 `GEOMETRY_KINDS`）；无效 kind 时 `preset->second` 越 `end()` | 前置 kind 校验（invalid_argument parity）+ `.at(kind)` |
| `qgis_geometry.cpp` `trim_line` | 桥 `geometry_intersection` 空交即抛 `GeometryServiceError`，Python 语义为空几何 → `ValueError` | catch `GeometryServiceError` → `invalid_argument("trim produced no line segments")` |
| 测试 | `create_layer` 传 `"Polygon"`（`GEOMETRY_KINDS` 全小写）；合并断言假定 union 环首顶点；`delete_part` 期望 demote `Polygon`（QgsGeometry 留单件 `MultiPolygon`）；facies fixture 缺 `id`/`facies` 名键、`parent_id` 误用名而非父要素 id | 测试对齐实现与 Python parity（顶点全扫求 xmin/xmax、接受单件 MultiPolygon、fixture 补 `id`/`facies`/`parent_id` 要素链） |
| `mirror_snapshot.hpp` | `data_revision` 为 `int`，修订 token 需 64 位 | `int`→`qint64`（`MirrorLayerSpec` + `MirrorLedger::Tokens` 同步） |

## 测试（ctest `ui_composite.*`，linux-ninja preset，vendored QGIS SDK）

- **`ui_composite.core`** — **29 checks / 0 failures**：词汇核、捕捉/
  空间索引、拓扑服务/检查器、merge plan、CRS 门、阶段词汇/档案、
  attribute schema、图层装饰、map tools、快照/覆盖、controller
  全链（CRUD/会话/门/事件/快照/工具上下文/几何命令拒绝语义）。
- **`ui_composite.qt_widgets_smoke`** — **20 checks / 0 failures**
  （`QT_QPA_PLATFORM=offscreen`）：拓扑面板、阶段条/面板、相级联+
  对话框、合并对话框、identify/捕捉设置、图层管理+输入树+linked
  views、工具页、属性表绑 controller、`CompositeDocument` 宿主
  注入画布（fallback 路径）+ 阶段 wiring。
- **`ui_composite.qgis_smoke`** — **38 checks / 0 failures**
  （真 `QgsGeometry`，offscreen + vendored runtime env）：merge/
  split/makeValid/multipart/trim/extend/reverse/simplify/smooth/
  offset/rotate/scale/centroid/reshape/add_part/delete_part 真核 +
  Python 拒绝词汇（invalid_argument parity）+ validator/repair
  seam 安装 + `CompositeQgisCanvas`（shim 持有、canvas hooks
  attach/address、当前层往返、有序 shutdown detach）。

## 偏差 / 遗留

- **`linked_workspace` 诚实缺席**：`src/linked_workspace.cpp` 已移植，
  但绑定 UI-14 `Pwb::UiControllersQt`；本配置
  `PWB_BUILD_PREDICTION_RUNTIME=OFF` → UI-14 未入场 → 面板不编译
  （`PWB_HAVE_LINKED_WORKSPACE` 不定义，测试段条件跳过）。CONV_30
  图补齐时自动入场，无需再改本库。
- Python `trim_line` 的 `keep="outside"` 分支上游未实现 —— C++ 同样
  只算 intersection（注释标明 byte-faithful）。
- `pwb_ui_composite_qgis` 复用桥 `geometry_service.cpp` TU（同
  `pwb_qgis` CONV-29 式），不复制内核；无桥环境 ops seam 缺省 →
  控制器命令诚实拒绝。
- 宿主编排（把 `CompositeDocument` 挂进 MainWindow/WorkstationFrame
  factory）属集成片，不在本切片。
