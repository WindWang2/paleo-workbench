# UI-05 findings — qgs-map（编图页 QGIS 承接面，7 files）

Branch: `feat/cpp-ui-qgs-map`。Base: `feat/cpp-ui-foundation` @ 69c01d05
（UI-01 shell 已落地，本切片依赖 `pwb::ui_shell`/`Pwb::UiShellQt` —
taskbook §2.1 的 "基于最新 origin/main" 假设 UI-01 已并入；本分支起点 =
foundation 分支头，merge 时无交叉文件冲突，见「冲突面声明」）。
Worktree: `../worktrees/cpp-ui-qgs-map`。切片 UI-05 of the M10 UI→C++ migration.

conv-16 分类（`docs/development/cpp-ui-panel-inventory.md` 逐文件表）：
5×QGS + 2×QT。依赖面已读：`libs/qgis`（MapSession/QgisRuntime/layer_adapter —
权威 map host）、`libs/ui`（CONV-27 layer_tree_panel = QgsLayerTreeView 领域面）、
`libs/ui_shell`（UI-01: FloatController/FloatingPanel/LayoutPersistence/
MapStatusBar/StyleRegistry/dock 词汇）、`libs/tool_policy`（ToolContext/evaluator）、
`libs/mapping_document`（document_io 的 legacy doc = JSON record 约定）、
`libs/platform_services`（theme_tokens/ThemeService）。

## Scope ledger（Python source → semantics → C++ target → status）

| Python source | Semantics | C++ target | Status |
|---|---|---|---|
| `pages/map_dock_manager.py` (400) | DockRail（36px 图标栏 + 可塌缩 panel area，sibling 布局让 QSplitter 回收空间）；MapDockManager：面板注册表（rail button + side area + float_key）、panels_menu（checkable 显隐 + 浮动 toggle）、rail 右键浮动菜单、**浮动镜像状态机**（rail button = "panel visible"：浮动时控窗口显隐、FloatingPanel.visibility_changed 回写 button/menu、bottom 工作台用户偏好 `_bottom_user_visible` + `_bottom_programmatic` 重入守卫） | `pwb::ui_map::DockRail` + `MapDockManager`（Qt，`pwb_ui_map_qt`；FloatController 注入走 `pwb::ui_shell::FloatController`） | ported |
| `pages/map_layer_tree.py` (332) | legacy 图件树：root「图件」→ 文档项 → 活动文档下 4 个 kind 图层（facies/well/line/label 中文标签 + 可见勾选 + ⊘ 锁标记）+「参考图层」组（offline/failed 后缀）；键差分保持展开/选中/滚动；document_selected / layer_visibility_changed / layer_lock_changed 信号 | `pwb::ui_map::MapLayerTree`（Qt，`pwb_ui_map_qt`） | ported（legacy 兼容面 — 权威图层树是 `pwb::ui::LayerTreePanel`/QgsLayerTreeView，见 deferred 注记） |
| `pages/map_document_panel.py` (132) | 只读摘要左栏：当前图件/目标层位/相带数/井数 + 文档 QListWidget（键差分） | `pwb::ui_map::MapDocumentPanel`（Qt） | ported |
| `pages/map_chrome_panel.py` (105) | 图面要素右栏：图名/启用元素只读 + title_edit + 4 元素勾选（图例/指北针/比例尺/标题栏）+ 保存/审核按钮；`chrome_changed{title,elements}` | `pwb::ui_map::MapChromePanel`（Qt） | ported |
| `pages/map_canvas_panel.py` (97) | 编图预览宿主：标题 + QStackedLayout{empty_label, canvas, native_canvas}；`load_preview(features,wells,period)`、`load_native_scene(scene)`、`update_state(document)`；空态文案双态 | `pwb::ui_map::MapCanvasPanel`（QGIS，`pwb_ui_map_qgis`）：宿主帧 + DisplayMapCanvas（自有 `pwb::qgis::MapSession` — M4 隔离约定）；geoviz `PaleoMapCanvas`/`NativeMapCanvas` 未迁移 → load_* 入口即 seam：调用方注入 features/wells/scene snapshot，内部 `preview_snapshot()` 构建双层 GeoJSON→memory QgsVectorLayer 镜像 | ported |
| `pages/workarea_map_widget.py` (191) | 只读工区图：域签名缓存 + `build_workarea_map_snapshot` + `workarea_view_extent` 初始 fit + 16px 屏幕容差井位拾取（wells/wells_flagged 层、Point、well_id）+ 选中环 overlay + decorations（比例尺/指北针/标题栏/图例）+ well_selected/well_activated + shutdown | `pwb::ui_map::WorkAreaMapWidget`（QGIS）：自有 DisplayMapCanvas（只读 QgsMapCanvas + QgsMapToolPan + <6px click filter → `map_clicked`）、`set_project(project, snapshot_builder)` — snapshot_builder 即生产者 seam（mapping 域未迁移，宿主注入）；拾取核 `pick_well_id` + `well_candidates_from_snapshot`（Qt-free）、选中环经 overlay provider、`workarea_view_extent`/`workarea_overlay_state`/`domain_signature` 进 core | ported（snapshot 生产者属 mapping 域 → seam；chrome decorations 属 UI-15 `paint_map_decorations` → `map_chrome_painter` 承接已迁移部分） |
| `pages/mapping_page.py` (2599) | GIS 壳编图页组合根：命令条（action registry 分组 strip + leftovers）、5 面板 dock 注册表（layers/reference/chrome/composer/bottom + FLOAT_KEYS）、中央 stack（edit_view / preview host）、底部分栏高度帽（220/QWIDGETSIZE_MAX）、dock splitter 持久化恢复协议（dock key→layers record→默认）、浮动 dock-back 恢复、mode 状态机（preview/canvas_priority→center index + bottom 显隐）、accessible names、mapping_context/dirty 投影、update_state 文档流转（dirty 守卫对话框）、ToolContext 投影、工具/命令 dispatch 表、等值线/导出 worker 协议、参考层/因素叠加/组图绑定、层属性应用、属性表差量缓存 | `pwb::ui_map::MappingPage`（QGIS，`pwb_ui_map_qgis`，**constrained 壳**）：布局/dock/float/persistence/mode 全量移植 + update_state 文档管线（Json 文档、layer_tree/chrome/status 实驱）+ context/dirty 投影；未迁移面板槽为 titled placeholder（edit_view/reference/composer/bottom — objectName 保留，rail/menu/float 行为同形）；authoring/scene/canvas 深部 deferred（清单见下）；dirty 守卫对话框未接（见 deferred 表） | ported（壳）+ deferred（深部） |

## C++ lib 布局（as-built）

```
libs/ui_map/
  include/pwb/ui_map/
    map_chrome_core.hpp     Qt-free 核（常数/键/模式规则/拾取/上下文投影/
                            workarea 词汇/reconcile-independent helpers）
    item_reconcile.hpp      Qt 键差分 helper（QTreeWidget/QListWidget）—
                            ledger 原拟名 reconcile_items.hpp，落地为
                            item_reconcile（私有 stand-in，见冲突面声明）
    qt_meta.hpp             Q_DECLARE_METATYPE(Json) 单点（Q_OBJECT 头共用）
    map_chrome_painter.hpp  图面要素绘制（比例尺/指北针/标题栏/图例 —
                            移植自 qgis_stack.decorations / workarea overlay）
    map_dock_manager.hpp    DockRail + MapDockManager（rail 并入此头 —
                            ledger 原拟独立 dock_rail.hpp）
    map_layer_tree.hpp      MapLayerTree（legacy 文档/kind 树）
    map_document_panel.hpp  MapDocumentPanel
    map_chrome_panel.hpp    MapChromePanel
    display_map_canvas.hpp  DisplayMapCanvas（qgis_stack.display_canvas
                            移植 — 独立 MapSession/QgsMapCanvas 宿主，
                            extent history + overlay + click-pick）
    map_canvas_panel.hpp    MapCanvasPanel（QGIS 画布宿主）
    workarea_map_widget.hpp WorkAreaMapWidget（QGIS 只读工区图）
    mapping_page.hpp        MappingPage（组合壳，constrained）
  src/*.cpp（12 个 — 与上头一一对应，qt_meta 为 header-only）
  ui_map_tests/{fixtures/ui_map_oracle.json, oracle_replay_test.cpp,
               qt_widgets_smoke_test.cpp, qgis_smoke_test.cpp,
               ui_map_test.hpp}
```

Targets（job_runtime/ui_shell 双 target 先例）：
- `pwb_ui_map`（`Pwb::UiMap`）— Qt-free 核 → `Pwb::Domain`
  （**修正**：不链 `Pwb::ToolPolicy` — ToolContext 投影属 authoring
  dispatch 深部，随 MapToolController 一slice deferred，见下）
- `pwb_ui_map_qt`（`Pwb::UiMapQt`）— Qt 部件 → `Pwb::UiMap` +
  `Pwb::UiShellQt` + `Qt6::Widgets`（AUTOMOC；Q_OBJECT 头列入 sources）
- `pwb_ui_map_qgis`（`Pwb::UiMapQgis`）— QGIS 面 → `Pwb::UiMapQt` +
  `Pwb::Qgis` + `Pwb::UiShellQt` + `Qt6::Widgets`（AUTOMOC）
  — 不链 `Pwb::Application`（LayerTreePanel facts 未引用 — 权威图层树
  `pwb::ui::LayerTreePanel` 属 UI-07 领域面，本切片走 seam）

文档载体：`pwb::domain::Json`（ordered_json）— 与 `mapping_document::document_io`
的 legacy PaleoMapDocument = JSON record 约定一致；`field_value` = `Json.value()`。

## Oracle 计划（`tools/oracle/generate_ui_map_fixtures.py`）

环境：无 PySide6 — 沿用 UI-01 套路并扩展成「行为级 QtWidgets stub」：
`Signal`（记录发射 + 订阅）、QWidget 树（objectName/visible/layout/findChild）、
`QToolButton/QAction`（checkable+toggled）、`QTreeWidget/QListWidget`
（真项容器 — **real `modelview.reconcile` 在其上跑通**）、`QMenu`、
`QStackedWidget/QSplitter` 等；`sys.meta_path` auto-stub 供给所有未白名单的
`paleo_workbench.*`/`qgis_render_bridge.*`/`geoviz` 导入（`_AutoStub`：
bool=False/iter=空/任意属性可调用，`isinstance` 安全的具名子类）。
真实 import：7 个页面模块 + `modelview.reconcile` + `viz.mapping_helpers` +
`mapping.workarea_map_snapshot`（PySide6.QtCore/Gui/Svg stub 后即纯数据）+
`project.models`（pydantic 真模型）+ `ui.tokens`/`paleo_workbench.tokens`。

冻结组（as-built — 20 个 fixture 组 + meta，82 cases；`sort_keys=True`）：

`meta` / `constants`（LAYER_KEYS+LABELS、FLOAT_KEYS、dock splitter key、
RAIL_{width,button,icon}、well pick 16px、bottom 帽 220、QWIDGETSIZE_MAX、
workarea 层 id 表、DEFAULT_CHROME_ELEMENTS）/ `field_value` /
`active_map_document`（prefer_id 命中/未命中/None/空表）/
`tree_keys`（`_document_key`/`_reference_layer_key`/`_document_list_key`
id 在/缺 → `@` 回退形）/ `panel_title`（精确键 / float_key 别名 /
`:`-后缀回退）/ `chrome`（default elements）/ `mode_ui`
（resolve_mode_ui：preview/canvas_priority/authoring × bottom 显隐 +
center index + height cap）/ `dock_splitter`（三级优先）/
`unified_revisions`（raw→effective 单调、owner 切换 present-kind bump、
authoring=None / mode off → None）/ `layer_field_names`（去重/`__` 前缀/
64-cap 在 feature 边界）/ `mapping_context`（含 is_dirty 三路径）/
`toolbar_groups`（action registry 分组 ∩ registered + leftovers）/
`rebind_tool`（_rebind_tool_after_layer_switch 决策表）/
`kind_visibility`（registry → composition → legacy tree 权威链）/
`workarea`（真 `build_workarea_map_snapshot` + `workarea_view_extent`）/
`domain_signature` / `workarea_widget`（`_well_feature`/`_on_map_clicked`
16px 拾取 + 退化 extent 守卫 #1166/`_overlay_state`/`_current_half_span`/
`select_well` zoom）/ `canvas_core`（ExtentHistory record/previous/next/
coalesce/100-cap + `map_units_per_pixel` + `zoom_by` 系数式+中点 +
`snapshot_source_version_ids` 有序去重）/ `preview_payload`
（`preview_payload_from_document`）。

**计划→落地偏差（如实）**：
- 计划的 widget 构造组（chrome_panel/document_panel/layer_tree/
  dock_manager/canvas_panel/mapping_page 构造探针）未冻结 — AST 提取只
  覆盖纯函数；部件构造语义由 `qt_widgets_smoke`/`qgis_smoke` 用真 Qt
  直接断言（同语义的 Python 测试逐条映射），oracle 侧不重复冻结。
- `tool_context_projection`（组 10）未冻结 — `_sync_action_state` 的
  ToolContext 投影属 authoring dispatch 深部，随 MapToolController 深部
  deferred（页壳不构造 ToolContext）。
- `reconcile`（组 20）未冻结 — `reconcile_widget_items` 属 UI-02 领域
  （`Pwb::UiWidgets`）；本切片私有 `item_reconcile` 由 qt smoke 的
  layer_tree/document_panel 结构断言覆盖，合并时以 UiWidgets 版为准。
- `negative_selfcheck`（组 21）移入测试侧（篡改断言，非 fixture 组）。

## 不移植 / deferred（如实）

| 语义 | 去处 | 理由 |
|---|---|---|
| `MapEditScene/MapEditView/MapEditToolbar`（QGraphicsView 编辑面） | UI-08 | 未迁移；center_stack_ 的 edit_view_ 槽为 titled placeholder（objectName=`MapEditView`）— 有文档时 `resolve_mode_ui` 走 unified 分支，与 Python `isinstance` 守卫同终态 |
| `MapAuthoringDocument`/edit session/layer revisions/`MapToolController`/工具类（map_tools/map_interaction/topology/reference_layers/map_scene_adapter） | mapping 域波次 | 未迁移服务层；页面对应深度（save_draft/工具绑定/undo-redo/属性表差量/参考层同步/层树安装）deferred — 已搬纪律：context 投影、kind 可见性权威链、revision 翻译核、抑制 id 集 |
| `MapActionController`/`_SURFACE_ICONS`/QAction 注册表 | UI-14 | 未迁移；strip 分组核 `toolbar_strip_groups`（grouped ∩ registered + leftovers）已移植 + seam 注入 action host |
| `workstation.tool_surface.ToolContext/availability_for_context` | `pwb::tool_policy`（已移植） | 复用目标 — 但本切片壳不构造 ToolContext（`_sync_action_state` 属 authoring dispatch 深部，随 MapToolController deferred；无 oracle 冻结组） |
| `create_display_canvas`/QgisMapStack/`UnifiedMapCanvas`/`NativeMapCanvas`/`native_factor_map`/`native_layer_tree`/`map_layer_properties`/`map_export_worker` | UI-02/UI-15 | 未迁移；画布职责由 `Pwb::Qgis` MapSession/QgsMapCanvas 承接（权威 host，自有 QgsProject — M4 隔离），native/fallback 叠层未接 |
| `MapAttributeTable`/`MapReferencePanel`/`MapWorkbenchBottom`/`MapFactorShelf`/`MapTopologyIssuePanel`/`inspector_panel`/`CompositionPanel`/`CreateFactorMapDialog` | UI-08/10/11 | 未迁移；dock 注册表保留其面板槽为 titled placeholder（objectName 保留 — rail/menu/float/persistence 行为同形，宿主切片落地时换 widget 即可） |
| `contour_draft_worker`/`OwnedWorkerJob` 深部 | UI-04/job_runtime | 未移植 — 壳无 worker 成员；worker 启动/完成/shutdown 协议整体 deferred |
| `preview_payload_from_features`/`viz.native_factor_map` | viz 域 | `preview_payload_from_document` **已移植进 core**（oracle 组 `preview_payload` 冻结）；from_features/native composition deferred — `MapCanvasPanel::load_native_scene(scene_snapshot)` 即承接 seam |
| `workarea_map_snapshot`/`project.domain` | mapping/project 域 | widget 的 `set_project(project, snapshot_builder)` 注入 seam；`workarea_view_extent`/`domain_signature`/图例词汇/拾取核已移植（oracle 组 `workarea`/`domain_signature`/`workarea_widget` 冻结真实生产者输出作输入） |
| `paint_map_decorations`（比例尺/指北针精细绘制） | UI-15 | `map_chrome_painter` 已移植基础 decorations（选中环/标题/图例/比例尺/指北针 — workarea overlay 同源）；viz 侧全精细度版本 deferred，elements 词汇透传一致 |
| `tinted_map_icon`/`panel_icon` 图标资源 | UI-12 | `QIcon::fromTheme(icon_name)` 直接承接（DockRail/面板菜单）— Python `tinted_map_icon` 缺资源同样返回空，fromTheme 未命中同终态 |
| 保存确认对话框/消息框 | 集成轮 | **未接** — `update_state` 切文档时 `presentation_dirty_` 直接复位，无 dirty 守卫 prompt；接入点 = `update_state` 前段（需 injectable confirm seam，本切片未预留） |

## 测试计划（ctest `ui_map.*` — as-built，全过）

- `ui_map.oracle_replay`（Qt-free）：20 个 fixture 组对账 + negative
  self-check — **22 checks / 0 fail**
  （`PWB_UI_MAP_ORACLE` 指向 `fixtures/ui_map_oracle.json`，82 cases）
- `ui_map.qt_widgets_smoke`（offscreen，无 QGIS）：dock manager/panels、
  layer tree 结构、document/chrome panel — **4 checks / 0 fail**
- `ui_map.qgis_smoke`（offscreen + PALEO_QGIS_RUNTIME/PROJ_LIB/GDAL_DATA，
  tests/cpp/platform 同款 ENVIRONMENT_MODIFICATION）：真 QgisRuntime +
  MapSession — DisplayMapCanvas backend/extent/zoom/mirror-failure/
  shutdown、MapCanvasPanel surface 切换、WorkAreaMapWidget
  snapshot/pick/select/shutdown、MappingPage 构造 + update_state +
  mode/splitter — **4 checks / 0 fail**

## Session-2 corrections（build + parity 修复，本切片二轮）

续作会话接手时 13 hpp/cpp + 测试已写就但未编译过。本节记录落地修正：

**Build（真 SDK API 校订）**
- `display_map_canvas.cpp`：`QgsSymbol` 无 `setSize`/`setWidth`（vendored
  QGIS 3.x API）→ `QgsMarkerSymbol::setSize` / `QgsLineSymbol::setWidth` /
  `QgsSimpleFillSymbolLayer::setStrokeWidth` /
  `QgsSimpleMarkerSymbolLayer::setStrokeWidth`（stroke_width 按 symbol
  类型分派）。
- `getCoordinateTransform()` 返回 `const QgsMapToPixel*`（非引用）→
  `->transform()`/`->toMapCoordinates(QPoint)`；`toMapCoordinates` 不在
  `QgsMapCanvas` 上。加 `isValid()` + isfinite 守卫（#1166 退化 extent）。
- `CanvasOverlay` 原在匿名命名空间 — 与头内 `friend class CanvasOverlay`
  声明的 `pwb::ui_map::CanvasOverlay` 不同名 → 移出匿名命名空间匹配
  friend（private `overlay_provider_` 访问成立）。

**Parity（oracle/smoke 驱动修正）**
- `unified_data_revisions`：缺失缓存项原实现一律 bump — Python
  `dict.get(kind)` 缺失时回 `None`，`None != None` 为 False → 缺席 kind
  （raw=None）不应 bump。修成 `it==end() ? !raw.is_null() : it->second!=raw`
  （dict.get parity）。owner 切换时 line/label 不再误 bump。
- `layer_field_names` fixture：`sort_keys=True` 使盘上 properties 键序
  变字母序，而 `expected` 冻结的是 Python 插入序（f0..f79 vs f0,f1,f10,…）
  → 生成器改为预排序输入，保证冻结输出与盘上序一致（64-cap 语义不变）。
- `MapLayerTree::layer_item_keys`：`std::map` 存储序（字母序）→ 按
  `kLayerKeys` 返回（Python LAYER_KEYS tuple 序：facies/well/line/label）。
- `MapChromePanel::emit_changed`/`current_chrome`：同样 `std::map` 序
  问题 — elements payload 改按 `default_chrome_elements()` 声明序发射
  （图例/指北针/比例尺/标题栏）。
- `MappingPage::update_state`：`previous` 指针在 `documents_=` 重赋值后
  捕获 → 悬挂解引用（读旧 vector 存储）。改为赋值前捕获 previous id，
  以 id 比较决定是否复位 `presentation_dirty_`。

**Test（断言校订）**
- `layer_tree_documents`：`topLevelItemCount()==2` 误 — Python 结构为
  单一 `图件` root 下挂文档行 → 断言改为 top==1 && root->childCount()==2。
- `display_canvas_backend`：`e[2]-e[0]<60` 误 — `QgsMapCanvas::setExtent`
  会按视口纵横比扩展请求 extent（400×300 视口上 100×100 → ~133 宽）。
  改为方形视口（400×400）+ 相对收缩断言（zoom 0.5 作用于调整后 extent）。

结果：`ctest -R ui_map` 3/3 通过（22+4+4 checks）。

## 冲突面声明（merge 时）

- 根 `CMakeLists.txt`：`if(PWB_BUILD_PLATFORM)` 块内
  `add_subdirectory(libs/ui_map)`（`add_subdirectory(libs/ui_shell)` 之后）。
- 独有文件：`libs/ui_map/**`、`tools/oracle/generate_ui_map_fixtures.py`、
  `docs/development/cpp-ui-swarm/ledgers/ui-05-*.md`。
- `item_reconcile.hpp` 与 UI-02 `pwb::ui_widgets::reconcile` 语义重叠 —
  集成时以 UiWidgets 版为准（本文件私有，无公开语义承诺）。
- UI-02 已并入 `libs/ui_widgets`（含 `Pwb::UiWidgetsQgis` —
  display_canvas/canvas_shim/mirror_snapshot/qgis_widgets/stack_events）：
  **本切片未消费其 API**（DisplayMapCanvas 在切片内自持 MapSession —
  M4 隔离约定要求独立 QgsProject，UiWidgetsQgis 的 shim 是宿主侧绑定
  面）。若协调层决定画布实现应走 UiWidgetsQgis::canvas_shim，冲突点在
  `display_map_canvas.{hpp,cpp}` 单文件内，可换实现不动 API。
- 不触碰 `apps/`、`main_window.*`、`app_context.*`、其他 libs、Python 源。
