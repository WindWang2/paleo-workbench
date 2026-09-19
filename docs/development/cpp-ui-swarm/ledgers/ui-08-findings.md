# UI-08 findings — qt-mapedit（编图编辑页簇，10 files + 3 seam files）

Branch: `feat/cpp-qt-mapedit`。Base: `main` @ c07d2e91（UI-01/02/03/05
已并入 — 本切片直接消费 `Pwb::UiDataCore`/`Pwb::UiDataQt` 的 map-edit
命令/几何/拓扑/吸附/Qt items 栈与 `Pwb::UiShellQt`/`Pwb::UiWidgets`）。
Worktree: `../worktrees/cpp-qt-mapedit`。切片 UI-08 of the M10 UI→C++ migration.

conv-16 分类：10×QT。taskbook §5 清单外额外承接三个 seam（均为被引用方，
不承接则 inspector/factor shelf 无法落地）：

- `factor_preview_grid.py`（UI-10 清单内文件，`map_factor_shelf` 直接
  消费其卡片组件 → 提前承接，UI-10 落地时去核即可）；
- `table_preview_widget.py`（inspector 治理/目录/解析三表 + 版本预览的
  虚拟化表格宿主）；
- `tag_widgets.py`（inspector 标签徽章/容器/输入对话框；
  `TagManagerDialog`/批量增删治理面 deferred 见下）。

## Scope ledger（Python source → semantics → C++ target → status）

| Python source | Semantics | C++ target | Status |
|---|---|---|---|
| `pages/map_edit_scene.py` (1309) | QGraphicsScene 编排核：6 工具（select/move/vertex/line/facies/label）、feature 注册/移除/文档加载、hit-query 索引、selection_ids、dirty 信号、EditCommandStack(max_depth=50) 撤销重做、edit_history(200) 审计、line/facies 草稿创建、吸附（参考点+索引候选）、图层可见性、拓扑刷新/保存门禁/adjacency 警告/强制重建、merge/split seam、vertex handle 编辑（增删移、环同步、双点插入边）、导航 LOD | `pwb::ui_pages_mapedit::MapEditScene`（Qt，QGraphicsScene 子类）+ Qt-free 核 `map_edit_api`（hit_test/环操作/最近边投影/吸附候选）+ `feature_query_index`（命中索引）+ `document_features`（PaleoMapDocument↔features 归一化）；复用 `ui_data_core` EditCommandStack/VertexEditCommand/RingEditCommand/CreateFeatureCommand/PropertyChangeCommand/topology/snap/draft 与 `ui_data_qt` FeatureItemApi 项 | ported |
| `pages/map_edit_view.py` (165) | QGraphicsView：AnchorUnderMouse、wheel 1.15 缩放、导航 LOD 启停（wheel/scrollContentsBy + idle 结束）、view_state dict（center/hscroll/vscroll）往返（`_same_view_state` 整型滚动条去抖）、cursor_position_changed 场景坐标、keyPress 委托 scene、reset_view | `pwb::ui_pages_mapedit::MapEditView` | ported |
| `pages/map_edit_toolbar.py` (188) | 编辑工具条：6 工具 checkable 互斥按钮 + undo/redo + 吸附开关 + 预览开关 + 缩放控件；tool_changed/snap_toggled/preview_toggled 等信号；objectName/accessibleName | `pwb::ui_pages_mapedit::MapEditToolbar` + `map_icons`（图标名→QIcon 缝） | ported |
| `pages/map_attribute_table.py` (461) | 属性表：`_FeatureSelectorList`（QListWidget 伪装 QComboBox 接口 currentData/findData/itemText/setCurrentIndex）、可见 feature id 过滤（kind+搜索 debounce+排序）、selector 键差分 + pin_id、属性 QTableWidget 重建/编辑回写（property_changed(feature_id,key,value)）、feature_selection_requested、geometry summary、apply_filter/sort_features/set_selected_ids | `pwb::ui_pages_mapedit::MapAttributeTable` | ported |
| `pages/boundary_panel.py` (105) | 边界面板：只读边界信息渲染（QFrame） | `pwb::ui_pages_mapedit::BoundaryPanel` | ported |
| `pages/map_reference_panel.py` (123) | 参考图层面板：层列表（勾选可见性+状态后缀 offline/failed）、opacity slider、status summary、reference_visibility_changed(str,bool)/reference_opacity_changed(str,float)/overlay_requested(str) 信号、view_state | `pwb::ui_pages_mapedit::MapReferencePanel`（状态色走动态主题绑定，不硬编码） | ported |
| `pages/map_topology_issue_panel.py` (142) | 拓扑问题面板：`_TopologyCellProxy` + `_TopologyTableView`（QTableWidget 兼容面 rowCount/item/setCurrentCell/itemDoubleClicked）、set_issues(list[dict])、双击/行激活 → locate_requested(feature_id)、空态、resize 列适配、排序代理下安全激活 | `pwb::ui_pages_mapedit::MapTopologyIssuePanel` | ported |
| `pages/map_workbench_bottom.py` (34) | 底部工作台 QTabWidget：属性表 + 拓扑问题两 tab、set_feature 透传、set_collapsed | `pwb::ui_pages_mapedit::MapWorkbenchBottom` | ported |
| `pages/map_factor_shelf.py` (102) | 因素架子：任务卡片网格宿主（FactorPreviewGrid）、5 请求信号（contour_draft/factor_overlay(str)/create_factor_map/fault_interpretation/map_product）、update_state(tasks)、view_state/cursor_position 往返 | `pwb::ui_pages_mapedit::MapFactorShelf`（首成果/fallback-id 语义已校订） | ported |
| `pages/inspector_panel.py` (1026) | 资产检查器：overview 行（逻辑名/类型/格式/生命周期/版本/托管态/完整性/路径/大小/mtime/来源 + 可选 trash/CRS/map usage）、governance 三表（治理键序 GOVERNANCE_KEYS + display 映射；catalog 元数据 sorted 键剔治理键；parsed_summary 中文标签 + 角色映射 + bool/list 显示规则）、标签容器、版本表（模型驱动 + version_id 稳定选行恢复）、LineageTreeWidget、TablePreviewWidget 版本预览、完整性主题渲染、版本标签控件、RAW-only 派生副本控件、checksum 复制、governance_edit_requested | `pwb::ui_pages_mapedit::InspectorPanel` + `table_preview_widget` + `tag_widgets` 缝 | ported |
| `pages/factor_preview_grid.py` (189, seam) | 单因素卡片网格：range/R²/去重诚实标注、title truthiness、range=None 格式化 | `pwb::ui_pages_mapedit::FactorPreviewGrid` | ported（seam — UI-10 正式清单文件，本切片承接去核） |
| `pages/table_preview_widget.py` (400, seam) | 虚拟化 QTableView 模型：MAX_PREVIEW_CELLS=1e6 截断+tooltip/status、lazy display data、深度列样式（DEPT/DEPTH/深度）、曲线定义样式（mnemonic/unit 列）、数值格式/对齐、NaN 前景、主题画刷、≤400 行采样列自适、复制、legacy 访问器（rowCount/columnCount/item/header） | `pwb::ui_pages_mapedit::TablePreviewWidget` | ported（seam） |
| `pages/tag_widgets.py` (712, seam) | `parse_multi_tag_input`（ASCII/全角逗号分号+空白分隔、去 `#`、trim、128 字符帽、保序去重）、TagBadge/TagContainerWidget/TagInputDialog | `pwb::ui_pages_mapedit::TagBadge`/`TagContainerWidget`/`TagInputDialog`/`parse_multi_tag_input` | ported（seam — 治理大面 deferred，见下） |

## C++ lib 布局（as-built）

```
libs/ui_pages_mapedit/
  include/pwb/ui_pages_mapedit/    18 headers
    map_edit_api.hpp               Qt-free 命中测试/环操作/吸附核
    feature_query_index.hpp        Qt-free feature 查询索引
    document_features.hpp          Qt-free 文档↔features 归一化
    map_icons.hpp                  图标名→QIcon 缝
    table_preview_widget.hpp       虚拟化表格（Q_OBJECT）
    tag_widgets.hpp                标签徽章/容器/输入框（Q_OBJECT）
    map_edit_scene.hpp             MapEditScene（Q_OBJECT）
    map_edit_view.hpp              MapEditView（Q_OBJECT）
    map_edit_toolbar.hpp           MapEditToolbar（Q_OBJECT）
    map_attribute_table.hpp        MapAttributeTable（Q_OBJECT）
    map_topology_issue_panel.hpp   （Q_OBJECT）
    map_reference_panel.hpp        （Q_OBJECT）
    boundary_panel.hpp             （Q_OBJECT）
    map_workbench_bottom.hpp       （Q_OBJECT）
    factor_preview_grid.hpp        （Q_OBJECT）
    map_factor_shelf.hpp           （Q_OBJECT）
    inspector_panel.hpp            InspectorPanel（Q_OBJECT）
  src/*.cpp                        18 sources，与头一一对应
  ui_pages_mapedit_tests/
    helpers_test.cpp               Qt-free 核测试（16 cases）
    widgets_test.cpp               场景+部件 parity 测试（13 cases）
    ui_pages_mapedit_test.hpp      共享 CHECK 断言宏
    CMakeLists.txt
```

Targets：

- `pwb_ui_pages_mapedit`（`Pwb::UiPagesMapedit`，STATIC，AUTOMOC）—
  `PUBLIC Pwb::UiDataCore Pwb::UiDataQt Pwb::UiWidgets Pwb::UiShellQt
  Pwb::Catalog Qt6::Widgets`；`PRIVATE Qt6::Gui`。
  gated on `TARGET Qt6::Widgets AND TARGET Pwb::UiDataQt`，整库在
  根 `if(PWB_BUILD_PLATFORM)` 块内 `add_subdirectory`。
- 测试：`ui_pages_mapedit.helpers` / `ui_pages_mapedit.widgets`
  （ctest 名 `ui_pages_mapedit.*`，`QT_QPA_PLATFORM=offscreen`）。

文档载体：`pwb::domain::Json`（ordered_json）— Python dict/list 语义
保序；Python truthiness 由 `ui_data_core::json_truthy`/`json_get_bool`/
`json_float` 承接（whitespace 整串校验数值字符串、0/False/""/空集合 →
falsy）。

## 关键移植纪律（parity 要点）

- **MapEditScene 不自建几何/命令**：move/vertex/ring/create/property/
  merge/split 全部委托 `ui_data_core` 命令对象 + `EditCommandStack`；
  拖拽/顶点编辑 mouse-move 只走视觉 preview，release 时才生成
  undoable 命令（与 Python 一致）。snap 候选与 hit 索引在几何提交/
  可见性变化时失效，不在每次 mouse-move 重建。
- **常量逐字**：scene rect `QRectF(-5000,-5000,10000,10000)` + pad 50、
  snap/feature/edge 容差 8px、handle 拾取 4px、adjacency gap 0.5 世界
  单位、history 200、stack 50。
- **truthiness 审计**（Python `if v:`/`v or x` ↔ C++ optional presence
  不等价处全部修正）：
  - `feature_query_index`：`record.get(k) or ""` — falsy JSON（0/false/
    ""）→ `""`，不字符串化；
  - `create_feature`：`record.get("id") or new_id(...)` — falsy id 走
    生成器；
  - inspector lineage：optional<string> 含 `""` 视同缺失跳过；
  - inspector checksum：`""` → 「未生成校验和」，禁用复制；
  - `view.governance` 已是 `governance_values()` 输出（非空字符串对），
    `_populate_metadata` 的 `if value:` 等价 — `governance_display_rows`
    直用成立；
  - `json_float` 支持 Python 同款数值字符串解析（前后空白+整串校验）。
- **document_features 局部化**：`libs/mapping_document` 已有同语义
  归一化实现但属 CONV-02 条件 target，不在 UI-08 link set 内 → 本切片
  保留局部实现（同冻结语义，复用 ui_data_core helper）。集成片可统
  一去重。
- **表预览全量重写**：首版仅 string cell；补齐 1e6 cell cap/截断 status、
  深度列与 mnemonic/unit 列样式、数值对齐、NaN 前景、主题画刷、400 行
  采样列宽、复制、legacy 访问器。
- **merge/split 空后端**：`geometry_backend=nullptr` 复刻 Python
  no-shapely 环境（返回 nullopt，shape 校验问题为空）。
- **clear_features 所有权**：remove + delete 自有 feature items
  （防泄漏）。

## 不移植 / deferred（如实）

| 语义 | 去处 | 理由 |
|---|---|---|
| `TagManagerDialog` / 批量增删标签对话框 | UI-11（治理波次） | 属 catalog tag 服务治理面；inspector 只消费 badge/container/input 三件套 |
| `TagEditDelegate`/deep tag 治理文案 | 同上 | 同上 |
| `MapAttributeTable` 的字段级 schema 校验 | mapping 域 | Python 侧无独立校验层（编辑直接发 property_changed） |
| shapely 几何后端实体 | `ui_data_core::MapGeometryBackend` 接口已留 | 后端实现属 mapping_kernel 域；空后端 = Python no-shapely 终态 |
| QGIS 画布集成 | UI-05/`Pwb::Qgis` 既有面 | MapEditScene 是独立 QGraphicsScene 编辑面；QGIS mapstack 契约不触碰（M4 隔离） |
| worker/async（factor 计算等） | job_runtime/服务域 | 本簇无自有 worker |
| 面板接线进 mapping_page/apps | 集成片 | taskbook §2.2：切片只交付库+测试，不接线 |

## 测试计划（ctest `ui_pages_mapedit.*` — as-built，全过）

- `ui_pages_mapedit.helpers`（offscreen）：Qt-free 核 —
  map_edit_api 命中/环/投影/吸附、feature_query_index、
  document_features 归一化/往返、parse_multi_tag_input —
  **16 cases / 0 fail**
- `ui_pages_mapedit.widgets`（offscreen）：MapEditScene
  （工具/选择/dirty/undo-redo/vertex/拓扑/LOD/merge-split seam）、
  view/toolbar/panels/inspector/table_preview/tag widgets 构造与
  行为 — **13 cases / 0 fail**

复验（本切片二轮 parity 修复后）：
`cmake --build build/mapedit --target pwb_ui_pages_mapedit
ui_pages_mapedit.helpers ui_pages_mapedit.widgets` 全绿；
`ctest -R ui_pages_mapedit` 2/2 pass（0.42s）。

## Session 修正记录（二轮 parity 审计）

- `map_reference_panel.cpp`：状态标签硬编码色 → 动态主题绑定。
- `map_factor_shelf.cpp`：首成果/fallback-to-id 语义校订。
- `factor_preview_grid.cpp`：title truthiness、`range=None` 格式化。
- `map_edit_scene.cpp`：clear_features 补 delete；create_feature/
  feature id falsy 语义。
- `map_topology_issue_panel.{hpp,cpp}`：proxy 生命周期 + 排序下行激活
  安全。
- `map_edit_toolbar.hpp`：补 QFrame/QAbstractButton 前置声明。
- `map_edit_view.{hpp,cpp}`：`emit` 形参改名（Qt 宏冲突）+ 事件路径。
- `inspector_panel.{hpp,cpp}`：不完整类型所有权/include；lineage
  run_id/workflow_step 与 checksum 的空串 truthiness。
- `feature_query_index.cpp`：falsy JSON（0/false）不再字符串化。
- `table_preview_widget.{hpp,cpp}`：全量重写补齐虚拟化/样式/截断/复制。
- `inspector_panel.cpp`：lambda 捕获 static `role_labels` 告警 → `[]`。

## 冲突面声明（merge 时）

- 根 `CMakeLists.txt`：`if(PWB_BUILD_PLATFORM)` 块内
  `add_subdirectory(libs/ui_pages_mapedit)`（`libs/ui_map` 之后、
  `apps/` 之前）— 单行追加，无 option()。
- 独有文件：`libs/ui_pages_mapedit/**`、
  `docs/development/cpp-ui-swarm/ledgers/ui-08-*.md`。
- `factor_preview_grid`/`table_preview_widget`/`tag_widgets` 属 UI-10/
  其他清单文件 — 本切片为 seam 提前承接；若其他分支同名落地，以本
  切片语义为准核对去重（`factor_preview_grid` 属 UI-10 清单 —
  合并时该文件归 UI-08 实现，UI-10 只补差量）。
- `document_features` 与 `libs/mapping_document` 归一化语义重叠 —
  集成片可统一；本切片不依赖该条件 target。
- 不触碰 `apps/`、mapping_document、Python 源（11 个 Python 文件全部
  原样保留，`git diff` 下 `paleo_workbench/` 零改动）。
- 全仓 build 存在既有无关失败：`tests/cpp/platform/
  test_project_session.cpp` 引 `MainWindow::newProject`（该 API 由
  `PWB_WITH_DATA_INTEGRATION` 守卫），`PWB_BUILD_DATA=OFF` 配置下
  platform 测试仍编译 → 非本切片引入，未动。
