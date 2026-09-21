# UI-02 findings — components + modelview + qgis_stack

Scope per taskbook §5: `components/` 全部（13 源文件 + `__init__.py`）、
`modelview/` 全部 3、`qgis_stack/` 余 6（`layer_tree_panel.py` 已于
CONV-27 落在 `libs/ui`，复核标 covered，不重转）。共 22 个 Python 源
文件 + 2 个 `__init__.py` 导出壳。

库布局（`libs/ui_widgets/`，三 target，job_runtime/ui_shell 双 target
先例）：

- `pwb_ui_widgets_core`（`Pwb::UiWidgetsCore`）— Qt-free 核：epoch
  switching、facies patterns/pick/taxonomy、HUD 采样、QC hub 核、
  tree-sync 解析。不链 Qt。
- `pwb_ui_widgets`（`Pwb::UiWidgets`）— Qt Widgets 壳：全部
  components + modelview。链 `Pwb::PlatformServices`
  （ThemeService/theme_tokens/resource_locator）+ Qt6::Widgets。
- `pwb_ui_widgets_qgis`（`Pwb::UiWidgetsQgis`）— QGIS 栈：canvas
  shim / display canvas / stack events / mirror snapshot / QGIS
  widgets。仅在 vendored SDK 准入（`if(TARGET Pwb::Qgis)`）时构建，
  链 `Pwb::Qgis`（MapSession 是画布/会话权威）。

## Scope ledger（Python source → semantics → C++ target → 终态）

### components/

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `components/badges.py` | PwbBadge（tone→objectName 动态属性，不快照主题）+ PwbInlineStatus（severity 行内状态） | `badges.hpp/cpp` | ported |
| `components/buttons.py` | PwbButton（variant→objectName）/ PwbToolButton / PwbSplitButton（主区+下拉，分段点击） | `buttons.hpp/cpp` | ported |
| `components/constraint_factor_hud.py` | HUD 读数：轴定位、双线性插值（部分 NaN 容）、局部坡度（边界钳制 stencil）、置信度、最近井 | `constraint_factor_hud.hpp/cpp` + `core/hud_sampling`（Qt-free 数学） | ported |
| `components/dialog.py` | PwbDialog（统一模态壳，按钮排布/对象名） | `dialog.hpp/cpp` | ported |
| `components/facies_eyedropper.py` | 拾取器：identify 链 → facies 字段别名抽取 → equip 语义 | `facies_eyedropper.hpp/cpp` + `core/facies_pick` | ported |
| `components/facies_palette_widget.py` | 相型调色板：pattern_id 映射、SVG 砖纹 asset、确定性回退色、taxonomy 名链 | `facies_palette_widget.hpp/cpp` + `core/facies_patterns` + `core/facies_taxonomy` | ported（见缝 1/2） |
| `components/headers.py` | PwbSectionHeader / PwbInspectorSection / PwbPropertyEditor / `section_header` 自由函数 | `headers.hpp/cpp` | ported |
| `components/inputs.py` | PwbSearchBox（trailing clear action，rb-clear.svg 图标，有/无文本切换）+ `make_form_row`（WorkFieldLabel 行）；`current_density` = `ui.style` re-export | `inputs.hpp/cpp`；density 访问走 `ui_context`（缝 3） | ported |
| `components/interactive_qc_hub.py` | 按来源增量聚合（sorted merge）、错误/警告计数文案、fix registry、per-item 修复可用标记；过滤组合不实际过滤（冻结 quirk） | `interactive_qc_hub.hpp/cpp` + `core/qc_hub_core` | ported |
| `components/states.py` | PwbEmptyState / PwbErrorState / PwbLoadingState / PwbProgress | `states.hpp/cpp` | ported |
| `components/stratigraphic_timeline_slider.py` | 期次时间轴部件 + EpochTimelineController（commit/onion 信号、期次差分切换、洋葱皮回滚、echo 断路） | `stratigraphic_timeline_slider.hpp/cpp` + `core/epoch_switching` | ported（horizon IO 注入，缝 4） |
| `components/toast.py` | PwbToast（栈式、tone、auto-dismiss）+ `notify()` 顶层自由函数 | `toast.hpp/cpp` | ported |
| `components/views.py` | PwbTableView / PwbTreeView / PwbCommandBar + DensityRowDelegate（密度行高） | `views.hpp/cpp` | ported |
| `components/__init__.py` | 导出壳 | 消解为 `pwb::ui_widgets` 命名空间 | ported（消解） |

### modelview/

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `modelview/async_query.py` | latest-only epoch 语义：协作取消前任务、迟到投递作废、绝不强杀 native worker；destroyed→detach 到 keeper | `async_query.hpp/cpp` | ported |
| `modelview/object_table.py` | ObjectTableModel+ColumnSpec：stable key 差分（同键序→dataChanged、键序变→reset）、排序重排索引不搬对象、stable_sort、持久索引 remap；StableSelection 跨 reset 选中 | `object_table.hpp/cpp` | ported |
| `modelview/reconcile.py` | reconcile_widget_items：按键差分，identity 保持，仅必要时做结构操作，被删 item 显式 delete | `reconcile.hpp/cpp` | ported |

### qgis_stack/

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `qgis_stack/canvas_shim.py`（1840 行） | 原生画布适配器：13 信号、extent 历史（programmatic 去重 + aspect-fit 容差 `_is_fitted_compatible`）、工具映射、snapping、mirror 发布/失败→backend_status、`shutdown_live_shims` 进程级清理、edit-pick 分发、导出（PNG/SVG/PDF，重入哨兵） | `qgis/canvas_shim.hpp/cpp`（链 Pwb::Qgis，MapSession 持有 QgsMapCanvas） | ported（见缝 5/6，生命周期 P0 修复） |
| `qgis_stack/display_canvas.py` | `create_display_canvas` 探测式构造 + QgisDisplayCanvas（自有 QgsProject 只读预览画布）：5 信号、extent 历史 100、zoom_by 钳正、manhattanLength<6 click 判定、mirror failures→degraded、shutdown/destroyed 记账分离 | `qgis/display_canvas.hpp/cpp` | ported（生命周期 P0 修复） |
| `qgis_stack/events.py`（47 行） | StackEvents：桥回调→Qt signal 重排队（`QTimer.singleShot(0, ctx,…)` 带 context，防死对象发射 #951 同款） | `qgis/stack_events.hpp/cpp` | ported |
| `qgis_stack/mirror.py`（10 行） | re-export shim；真身 `mapping/qgis_mirror.py`（文档域，非 UI 域） | `qgis/mirror_snapshot.hpp/cpp`（UI 侧 snapshot→project 同步路径） | ported（文档域真身 deferred，见缝 7） |
| `qgis_stack/tree_sync.py`（144 行） | TreeChangeSet/TreeEvent/TreeChangeBatch：legacy 平铺 + schema-2 typed events + 结构快照；坏 JSON/非 dict→空集不抛；visibility 强转 bool、rename 强转 str；revision 门控过期回声 | `core/tree_sync`（Qt-free） | ported |
| `qgis_stack/widgets.py`（121 行） | cpp_pointer/wrap_widget/canvas_viewport/as_tree_view（shiboken 工件）消解；configure_layer_tree_view（branch QSS+expandAllNodes）；QgisCanvasHost / QgisLayerTreeHost | `qgis/qgis_widgets.hpp/cpp` | ported（shiboken 面消解，见缝 8） |
| `qgis_stack/__init__.py` | 导出壳（QgisCanvasHost/QgisDisplayCanvas/create_display_canvas） | 消解为命名空间 | ported（消解） |
| `qgis_stack/layer_tree_panel.py`（778 行） | QgsLayerTreeView 图层面板 | `libs/ui`（CONV-27 已交付） | covered（复核，不重转） |

## 缝 / 越界声明（dependency seams — 如实披露，不伪造）

1. **`core/facies_patterns` + `core/facies_taxonomy`** — 真身
   `paleo_workbench/mapping/facies_patterns.py` /
   `facies_taxonomy.py` 在 **domain 迁移轨**（不在 `ui/` 树，不属任何
   UI-NN 切片）。`facies_palette_widget.py` / `facies_eyedropper.py`
   （在本切片内）import 它们；为让在册部件可立，UI-02 在
   `pwb_ui_widgets_core` 内放了**自足语义核**（pattern_id 映射、
   确定性回退色、taxonomy GeoJSON 解析 + 字段别名）。domain 轨迁移
   这两个模块时应收编/去重此核 —— 已记 decisions D2。
2. **`core/epoch_switching`** — 同上，真身
   `paleo_workbench/mapping_workspace/epoch_switching.py`（domain
   轨）。timeline controller 需要其期次分组/classify/switch
   plan/onion 选择语义，UI-02 自足实现所需子集。记 decisions D2。
3. **`ui_context`**（`ui_context.hpp/cpp`）— `inputs.py` 的
   `current_density` 是 `ui.style.current_density` 的 re-export
   alias（`theme_manager.density.value`，异常回退 "comfortable"）。
   `style.py` 属 UI-01/12 域；UI-02 提供 `ui_context` 作为组件层
   的 theme/density 访问面 —— `set_theme_service` 注入宿主
   `ThemeService`，未注入时用进程级惰性 fallback（与 Python
   theme_manager 单例同语义，读同一持久化 (theme,density) 对）。
   `current_density` 由 ThemeService 的 density 访问器承担。
4. **`stratigraphic_timeline_slider` 的 `workflow.stratigraphy`** —
   Python controller 调 `active_target_horizon(project)` /
   `set_target_from_boundary(project,key)`（`paleo_workbench/
   workflow/`，domain 轨，未迁移）。C++ 侧以 `HorizonIo` seam
   （`read_active`/`write_target` std::function）注入；图层管理器
   同样以 `LayerManagerSeam` 注入。**DEFER 纪律**：依赖未迁移服务
   层 → 注入 seam，不伪造默认实现。
5. **`canvas_shim` 的 `_bridge_features`/`capability_manifest`** —
   Python 经桥 capability manifest 探测特性；C++ 原生 = 恒可
   （`native` 即能力），不支持的编辑操作走诚实 defer（
   `native_tool_activation_failed`→回退 pan、commit 拒绝可感知）。
   无桥探测层。
6. **`map_chrome`**（`map_chrome.hpp/cpp`）— `canvas_shim.py` 的
   `_ScaleChrome`/`_NorthChrome`/`_LegendChrome` 惰性 import
   `unified_map_canvas.py` 的 `_paint_scale_bar_impl` /
   `_scale_bar_spec_impl` / `paint_map_decorations` /
   `legend_chrome_size` / `ensure_basic_map_chrome` /
   `_facies_pattern_pixmap`。`unified_map_canvas.py` 在 **UI-15**
   文件清单；UI-02 把这些**纯 paint 帮助函数**抽成 `map_chrome`
   共享工具（chrome ink 相对图体色、CANVAS_* 交互色、device-pixel
   尺寸）。**只含自由函数、不含 UnifiedMapCanvas 部件** —— 部件本
   体仍属 UI-15；UI-15 移植画布时应直接复用 map_chrome 而非重转。
   记 decisions D3。
7. **`mirror.py` 文档域真身** — `mapping/qgis_mirror.py`（M7 分
   层：镜像同步是文档域工作）。UI-02 的 `mirror_snapshot` 提供 UI
   侧 snapshot→QgsProject 同步；文档域编排（`mirror_snapshot_to_
   stack` 的 catalog/asset 编排）随 domain 轨，记 deferred。
8. **`widgets.py` shiboken 面** — `cpp_pointer`/`wrap_widget`/
   `canvas_viewport`/`as_tree_view` 是 PySide6 wrapInstance 工件
   （同地址只认首次 wrap 类型 → 三层回退）。C++ 直接持有
   `QgsMapCanvas*`/`QgsLayerTreeView*`，此面整体消解。
   `configure_layer_tree_view`（branch QSS + expandAllNodes，
   map/tree-branch-*.svg）与两个 Host 部件保留语义。

## Oracle

无 oracle 生成器 —— UI-02 是 **QT 切片**（taskbook §4：CORE oracle
富矿是 UI-03/04）。验证靠行为测试逐条对应冻结 Python 语义：

- `ui_widgets.core` — 20 个 PWB_TEST case / 80 checks（epoch
  group/classify/switch-plan/onion、facies pattern/taxonomy/pick/
  field-alias、HUD axis/bilinear/slope/confidence/nearest-well、QC
  merge/counts、tree-sync legacy+schema2+revision 门控+坏 JSON）。
- `ui_widgets.modelview` — 8 case / 17 checks（ObjectTableModel
  差分/排序/stable key/StableSelection、reconcile identity/
  delete、AsyncQuery latest-only/迟到作废/取消）。
- `ui_widgets.widgets_smoke` — 15 case / 82 checks（全部部件构造+
  响应：badges/buttons/headers/inputs/states/toast/dialog/views/
  timeline/qc-hub/hud/eyedropper/palette）。
- `ui_widgets.qgis` — 5 case / 33 checks（**真 vendored SDK**：
  canvas shim extent 历史+aspect-fit 容差+snapping+mirror、display
  canvas zoom/click/degraded、stack events 重排队、host widgets，
  会话有序销毁）。

`QT_QPA_PLATFORM=offscreen`（modelview/widgets_smoke/qgis）；core 无
Qt。QGIS 测试沿用 tests/cpp/platform 的 PROJ_LIB/GDAL_DATA/运行时
闭包 env 模式。

## 验证

- `cmake --preset linux-native-product` configure + `ninja
  pwb_ui_widgets_core pwb_ui_widgets pwb_ui_widgets_qgis
  ui_widgets.core ui_widgets.modelview ui_widgets.widgets_smoke
  ui_widgets.qgis` 全绿。
- `ctest -R ui_widgets` → **4/4 pass（48 case，全绿）**，QGIS 腿用真
  vendor SDK（非 fallback）。

## 生命周期 P0（自审揪出并已修）

`QObject::destroyed` 回调在控件/QGIS 子树**已半销毁**时运行。初版
`QgisDisplayCanvas::mark_disposed` / `QgisCanvasShim::mark_disposed`
在 destroyed 里 `session_.reset()` —— 于半销毁 QGIS 子树上析构
`MapSession`，析构期 SIGSEGV/`free(): invalid size`。

修复：`mark_disposed` 只置记账标志（`shutdown_done_` /
`canvas_destroyed_`），**绝不调 `session_.reset()` / `MapSession::
close()` / 任何 QGIS API** —— 与 Python `_mark_disposed`「析构期纯
记账绝不进桥/QGIS」（16-agent-findings canvas_shim 分支与边界）语义
一致。session 由正常析构/成员销毁顺序负责（`shutdown()` 在析构体做
有序 `session_->close()`，QGIS 对象仍处有效序）。

## Known deviations / limitations

1. `EpochTimelineController` 的 horizon 写穿依赖注入的 `HorizonIo`
   —— 未绑定时 current key 不持久化到 stratigraphy（Python 直接调
   domain 服务）；接线由后续集成片提供真值。记 deferred 非等价缺失。
2. `map_chrome` 是 unified_map_canvas 帮助函数子集抽取（见缝 6）；
   UI-15 复用而非重转。
3. shiboken 包装面（widgets.py）消解 —— C++ 无 wrapInstance 语义。
4. `EpochTimelineController`（stratigraphic_timeline_slider.cpp:294-542）
   截至 2026-09 全仓**零调用方**（未接线死代码，#1392）。接线前先修
   `apply_onion` 每层 `raise_layer_to_top` 内部重取 `layers()` 快照的
   O(n²) 拷贝。
5. 本切片**不接线** MainWindow/AppContext（taskbook §2.2：接线是
   后续集成片）；只交付 库+测试。

## 冲突面声明（merge 时）

- 根 `CMakeLists.txt`：`if(PWB_BUILD_PLATFORM)` 块内单行
  `add_subdirectory(libs/ui_widgets)`（platform_services 之后）——
  与其他 UI 片的同位 add_subdirectory 会文本相邻，保留各自单行。
- `libs/qgis/CMakeLists.txt`：补 `if(TARGET Pwb::Domain) link
  Pwb::Domain`（main 预存缺陷修复 —— `canvas_state_json` 无条件
  include `pwb/domain/json.hpp`，PLATFORM 不开 CONV_29 即断）。
  与 UI-01 同款守卫形式，冲突时保留 `if(TARGET ...)` 块。
- 不触碰 `apps/`、`main_window.*`、`app_context.*`、`_vendored/`、
  `native_backend.py`、`.github/workflows/`。
