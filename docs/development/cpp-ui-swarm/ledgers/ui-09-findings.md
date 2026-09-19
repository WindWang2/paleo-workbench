# UI-09 findings — qt-well-seismic（17 文件 + 3 支撑文件）

Branch: `feat/cpp-qt-well-seismic`（base origin/main，合并至 55881f9d）。
Worktree: `../worktrees/cpp-qt-well-seismic`。切片 UI-09 of the M10 UI→C++
migration：井/震页面簇 —— 井详情/井表/井图、测井曲线画布壳与轨道设置、
对比连线编辑、跨井导出、地震属性/控制/视图/预测页、井震联合页与 3D 地质建模页。
重量级引擎（WellLogEngine、SeismicView、geoviz 联合三维/Geo3D、QGIS 画布）
全部走注入 seam —— 不移植、不伪造；无引擎时渲染诚实的不可用占位。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `pages/well_detail_panel.py` | 井数据视图：角色槽表（成员名截 4 + 主版本 ✓ + current_version_id 截 14 + version_count 求和）、空角色（含 unresolved）尾部"缺失"行、stale/edit/missing 三卡各 8 行上限 + 兜底文案、角色中文显示名 | `well_detail`（Qt-free：role rows/empty roles/stale/edit/missing lines/role display/title/subtitle）+ `qt/well_detail_panel`（壳） | ported |
| `pages/well_log_canvas_panel.py` | 后端 combo（Legacy/WellLogEngine，env `PALEO_USE_WELLLOG_ENGINE` 默认）+ 画布 stack（引擎失败 → legacy fallback → 不可用占位）、`is_native_backend` 选择语义（与活性分离）、depth-cursor 门（legacy 恒可/engine 探测 + ft/unknown/undeclared 拒绝理由）、DepthCursorGate 120ms 保持/冲刷、legacy 导出块（engine+SVG 拒绝） | `cursor_gates`（DepthCursorGate + `depth_cursor_unavailable_reason`）+ `page_state`（backend label/env gate/export block）+ `qt/well_log_canvas_panel`（壳 + `WellLogCanvasSeam` 双槽注入 + `WellLogCanvasHooks`） | ported |
| `pages/well_log_track_settings.py` | 轨道设置对话框：`CurveTrackLayout`（curve_keys/visible/groups/scale_mode/color）merge/unmerge 公共操作 | `qt/well_log_track_settings`（壳，复用 `pwb::viz::WellLogTrackLayout` —— TU 经 `Pwb::VisualizationWellLog` 或本地编译单份，CONV-29 单权威模式） | ported |
| `pages/well_map_panel.py` | 折叠面板 + 井图页宿主：refresh_domain 构建模型（ok/flagged 双块、参考井排除、未命名兜底、坐标状态 flag）、CRS 等价/警告横幅、工区边界环、三维测区 3 角补平行四边形环、计数文案 | `well_map`（Qt-free：model/CRS/boundary/survey rings/counts）+ `qt/well_map_panel`（壳）+ `qt/well_map_canvas`（`IWellMapSurface` QPainter fallback） | ported |
| `pages/well_table_panel.py` | 井参数表：`_fmt`（≥1000 或 <0.001 走 `%.4g`，否则 `%.4f` 去尾零）、11 列清单、QC flag 归一化 + 前景 token、标题 `name · horizon`、汇总 `N 行 · flag:k` | `well_table_format`（Qt-free）+ `qt/well_table_panel`（壳） | ported |
| `pages/well_seismic_joint_page.py` | 井震联合页：`_loaded_once` 首 show 懒 reload、域 combo 拒绝回退 scene 实际域、井对 combo 跨刷新保选择、快照导出 + OUTPUT DataVersion 注册 seam、引擎不可用占位 | `qt/well_seismic_joint_page` + `engine_seams::JointHostController`（QObject seam） | ported |
| `pages/well_log_prediction_page.py` | 测井预测页：任务面板 + 证据面板 + 画布面板 + 上下文工具条编排；LAS 资源过滤/combo 标签；失败在线运行查找 + 诊断日志（端点去 userinfo/query、token/Bearer 打码、4k 截断）；输出性质/来源标签 | `qt/well_log_prediction_page` + `run_diagnostic`（latest_failed_online_run/run_error_text/run_diagnostic_log）+ `redact` + `output_labels` + `resource_sources`（well_log 过滤） | ported |
| `pages/correlation_link_editor.py` | 对比连线编辑：link/top 行渲染（井A → 井B、深度 `%.2f unit`、方法中文标签、置信度 —）、draft 增删改校验（自连/幽灵 top/空 id 拒绝）、top 选项 `name · marker (depth) #idx` | `correlation`（Qt-free：rows/mutations/choices/labels）+ `qt/correlation_link_editor`（对话框 + `pick_item` seam） | ported |
| `pages/seismic_attribute_panel.py` | 属性树：5 组（含 `未实现` 灰组）、可计算 kernel 标签白名单、disabled leaf 不可选、`selected_attribute` 缺省 `"振幅"`、`set_selected_attribute` 仅扫叶子且抑制信号 | `seismic_attributes`（组/kernel 标签/display modes）+ `qt/seismic_attribute_panel`（壳 + `computable_probe` seam） | ported |
| `pages/seismic_context_toolbar.py` | 上下文工具条：源 combo（`name · FORMAT`/未命名/空占位）、任务/层位/属性/显示模式/体 shape/输出性质展示、inferring 态 | `qt/seismic_context_toolbar`（壳，标签来自 `resource_sources`/`output_labels`） | ported |
| `pages/seismic_control_panel.py` | 控制面板：属性标签/显示模式（vd|wiggle）/井震标定 toggle，controls enable 一刀切 | `qt/seismic_control_panel`（壳 + `seismic_controls_enabled`） | ported |
| `pages/seismic_prediction_page.py` | 地震预测页：任务面板 + 上下文工具条 + 视图/控制面板编排；SEGY 资源过滤（type/format/path 三路）；inference 动作经 hooks，无 hooks 时 no-op 保页面连贯 | `qt/seismic_prediction_page` + `resource_sources`（segy 过滤/combo/signature/resolved index） | ported |
| `pages/seismic_task_panel.py` | `SeismicTaskPanel` = TaskPanelBase 特化（object_name/title/show_review_count=False）；行文案 `name · status_label`、active row = 末任务/显式选择 | `qt/task_panel_base`（TaskPanelBase + SeismicTaskPanel/PredictionTaskPanel 特化）+ `task_state`（key/active/status token/row text） | ported |
| `pages/seismic_view_panel.py` | 视图面板：empty page ⇄ 引擎 stack、interpretation 生命周期条（draft/sync/undo/redo/save/reopen 使能矩阵 = Python `_sync_interp_buttons`）、SeismicCursorGate（30ms 或 >1 inline 行跳发布）、display_mode/attribute_label 缺省 `vd`/`振幅` | `cursor_gates::SeismicCursorGate` + `qt/seismic_view_panel`（`SeismicViewSeam` 注入 + `SeismicViewHooks` + 本地状态镜像） | ported |
| `pages/cross_well_export_dialog.py` | 跨井导出：格式→可编辑项矩阵（svg 无 dpi/page_size；pdf page_size 时 width 失效；png dpi+width）→ 解析后选项 | `export_options`（Qt-free：enabled/resolve）+ `qt/cross_well_export_dialog` | ported |
| `pages/project_well_map_page.py` | 工区井图页：井列表（参考井排除）、选择/多选/清除、空间游标显隐、CRS 标签、surface 注入 seam | `qt/project_well_map_page` + `qt/well_map_canvas`（内置 fallback）+ `qgis/well_map_qgis_surface`（QGIS 实现，同 `IWellMapSurface` 契约） | ported |
| `pages/geological_modeling_3d_page.py` | 3D 建模页：左 geoviz 场景树 + Geo3D 检查器（测量/剖切/视图/QC/inspector 全转发 controller seam）、中栏工具条 + 正交切片卡 + 4-tab 分析卡（等时/井震标定/沉积相/导出诊断）+ 可折叠 2D 条、状态行在 view_container 内、joint_state JSON 往返 + well_width [2,10]/opacity [10,100] clamp、引擎不可用占位 | `joint_state`（JointAnalysisSlice round-trip + clamps）+ `qt/geological_modeling_3d_page` + `engine_seams`（JointHostController/Geo3DController/Geo3DAnalysisHooks） | ported |

### 支撑文件（taskbook UI-02/UI-11 域 —— 本切片页面依赖的薄壳，记已知偏离）

| Python source | C++ target | 理由 |
|---|---|---|
| `pages/task_panel_base.py`（UI-11） | `qt/task_panel_base` | `seismic_task_panel.py` 直接继承；`well_log_prediction_page` 复用 —— 无它两页无法成立 |
| `pages/prediction_evidence_panel.py`（UI-11） | `qt/prediction_evidence_panel` | `well_log_prediction_page` 的右栏证据/动作面板 |
| `modelview/object_table.py` 模式（UI-02） | `qt/object_table_model`（`StringTableModel` + 稳定键选择） | correlation editor/井表/任务面板的 ColumnSpec+StableSelection 模式 —— dumb grid，单元格全部来自 Qt-free 核预渲染 |

三片均在 `pwb::ui_wellseis::qt` namespace 下，与 UI-02/UI-11 将来自交付的
正式版本不冲突；集成片决定归并/映射（同 UI-07 PreviewSettings 先例）。

## 结构

`libs/ui_wellseis/`（与 ui_map/ui_pages_preview 同构，三层）：

- **`pwb_ui_wellseis`**（`Pwb::UiWellseis`，Qt-free，不链 Qt）— 14 头/13 TU：
  `slices`（全切片 DTO）+ `task_state`、`resource_sources`、`cursor_gates`
  （Seismic/Depth 双门 + depth-unit 拒绝）、`well_table_format`、`well_map`、
  `well_detail`、`correlation`、`output_labels`、`seismic_attributes`、
  `export_options`、`joint_state`、`run_diagnostic` + `redact`、`page_state`、
  `json_helpers`。
- **`pwb_ui_wellseis_qt`**（`Pwb::UiWellseisQt`）— 20 个 widget TU：
  17 页面壳 + `task_panel_base`/`prediction_evidence_panel`/`object_table_model`
  支撑 + `engine_seams.hpp`（seam 抽象集中地）。链 `Pwb::UiWellseis` +
  `Qt6::Widgets`；`WellLogTrackLayout` TU 经 `Pwb::VisualizationWellLog`
  （`PWB_SCIENCE_BUILD_VIEWER=ON` 时）否则本地编译单份 —— 永不两份同链。
- **`pwb_ui_wellseis_qgis`**（`Pwb::UiWellseisQgis`，仅 `Pwb::Qgis` 入场时）—
  `well_map_qgis_surface`：自有 `pwb::qgis::MapSession`（隔离 QgsProject +
  QgsMapCanvas，DisplayMapCanvas 角色），`WellMapScene` 镜像进 memory vector
  layers；hover/click 命中契约与 QPainter fallback 一致（8px、wells 先于
  wells_flagged）；QGIS 未初始化 → 显式不可用占位（非静默空板）。

## 重量级引擎 seam（deferred —— 不移植不伪造）

| seam | 引擎域 | 本切片承接方式 |
|---|---|---|
| `WellLogCanvasSeam` + `WellLogCanvasHooks` | WellLogEngine 原生画布 + LAS 绑定 + legacy 导出 | 双槽注入 + `engine_view`/`has_bound_las`/`export_legacy` hooks；空 seam → 不可用占位/legacy fallback |
| `SeismicViewSeam` + `SeismicViewHooks` | SeismicView 剖面引擎 + interpretation session | widget 注入 + 全操作 hook 转发；interpretation 使能矩阵由 host 计算注入 |
| `JointHostController`/`Geo3DController`/`Geo3DAnalysisHooks` | geoviz 联合三维 + Geo3D dock + 分析算法 | QObject controller 抽象（scene snapshot/域/切片/fence/相机/色标/可见性/拾取）；页只转发，分析动作经 hooks |
| `CorrelationEditorHooks.pick_item` 等 | 对比存储/拾取对话框 | draft slice 进出 + 可注入选择 seam |
| 在线推理/API | inference_api_online 运行 | `run_diagnostic` 只吃 `RunSlice` 输入（查找+打码已移植）；预测页动作 hooks |
| 快照导出注册 | OUTPUT DataVersion | `register_snapshot_export` seam |
| QGIS 画布 | QgsMapCanvas | `IWellMapSurface` 契约双实现（QPainter fallback 内置，QGIS 版独立 target） |

## 测试（ctest `ui_wellseis.*`，linux-ninja preset）

- **`ui_wellseis.core_smoke`** — 17 tests / 0 failures：任务键/active 行、
  状态 token（含未知态原文 muted）、资源过滤/标签/signature、双 cursor 门、
  depth-unit 拒绝理由、输出性质/来源/类分布/证据行、correlation 行与 draft
  变更、诊断打码 + 失败运行回放、井表格式（`%.4g`/`%.4f` 分支 + QC token +
  汇总）、井图模型/CRS 警告/边界/测区环、page_state 杂项、joint_state 往返
  + clamp 与空 payload 默认、export options 矩阵、属性词汇表、井详情行。
- **`ui_wellseis.qt_widgets_smoke`** — 18 tests / 0 failures（offscreen）：
  每个壳构造即答（任务面板/工具条/属性树/控制面板/视图 seam/测井画布/
  井面板/井图表面/工区井图页/连线编辑/导出对话框/轨道设置/证据面板/
  联合页/两预测页/3D 页/表模型）；空引擎 → 诚实占位；Fake controller 验证
  reload/shutdown 转发。
- **`ui_wellseis.qgis_smoke`** — 3 tests / 0 failures（真 QgsApplication +
  QgisRuntime）：surface backend=qgis、scene→layers→视图操作、QPainter 与
  QGIS 两实现的命中契约一致。**运行时初始化失败即 FAIL**（不可用面契约靠
  构造路径检验，永不跳过当成功）。

## Smoke/parity 修正轮（本轮实测揪出的偏差）

| 位置 | 偏差 | 修正 |
|---|---|---|
| `geological_modeling_3d_page.cpp` ctor | 状态行经 `qobject_cast<QVBoxLayout*>(this->layout())` 加到页根 —— 页根是 `QHBoxLayout`，cast 得 nullptr → `insertWidget` 段错误 | Python `_joint_status` 加在 `view_container` 的 `view_layout`：改为 `view_layout->addWidget(status_)`，objectName 对齐 `JointStatusRow`，并把引擎宿主插入移到 view_layout 末尾（Python 序：toolbar/切片卡/分析卡/状态行/3D host） |
| `seismic_attribute_panel.cpp` | `selected_attribute()` 无当前叶返回 `""`；Python 兜底 `"振幅"`；`set_selected_attribute` 经 findItems 可命中组项 | 返回 `"振幅"` 兜底 + 仅叶节点可 setCurrentItem |
| `seismic_view_panel.cpp` | display_mode/attribute_label 纯 hook 转发，无 hooks 返回 `""` | 面板本地镜像 + Python 缺省 `vd`/`振幅`（hooks 在时仍优先转发读取） |
| `well_log_canvas_panel.cpp` | `is_native_backend()` 额外要求 engine widget 非空 | Python 为纯选择语义（`return self._backend == "engine"`，原生加载失败仍保持选中）——去掉 widget 条件 |
| `core_smoke_test.cpp` | `well_table_fmt(1234.5)` 期望 `"1235"` —— Python `%.4g` round-half-even 为 `"1234"` | 测试期望改 `"1234"`（C printf 同 glibc 行为） |
| `core_smoke_test.cpp` | `well_missing_lines` 期望 1 行 —— Python `empty` 含全部无成员槽（unresolved 不豁免），fixture 得 `角色缺失: 分层顶` + `源文件缺失: asset-9` 两行 | 测试期望改 2 行（实现本就 parity） |
| `qt_widgets_smoke_test.cpp` | `joint_page` 期望 `reload_count==1` —— Python `_loaded_once` 首 showEvent 已计一次懒加载 | 改为断言增量（`after_show + 1`） |

此前轮次已修（编译期）：Qt `slots` 宏撞名（`role_slots` 改名）、命名空间内
`QTableView`/`QVBoxLayout` 前向声明遮蔽、`.connect` Python 语法、QGIS 头
`qgsvectorlayersimplelabeling.h`→`qgsvectorlayerlabeling.h`、`QgsPalLayerSettings`
无 `enabled` 成员（走 layer labeling config）、`std::min(int, qsizetype)` 收窄。

## 验证结果

- `ninja -C build/presets/linux-ninja`：全目标链接通过（含 pwb-platform，
  本切片未接线进 app）。
- `ctest -R ui_wellseis`：**3/3 PASS**（core 17 + qt 18 + qgis 3 用例）。
- 全量 ctest：81/86 通过；5 个失败均为**预存环境问题** —
  `ui_widgets.modelview`、`ui_widgets.widgets_smoke`、`ui_shell.qt_widgets_smoke`、
  `ui_map.qt_widgets_smoke`、`ui_pages_preview.qt_widgets_smoke` 报
  `libodbc.so.2: cannot open shared object file`（vendor Qt/QGIS 传递依赖，
  其测试注册未带 `LD_LIBRARY_PATH`）。与 UI-09 无关：这些目标不依赖
  ui_wellseis，本切片未改其源码/链接。

## Not ported / deferred

| 面 | 理由 |
|---|---|
| WellLogEngine/SeismicView/geoviz/Geo3D 引擎本体 | 重量级 seam（`PWB_SCIENCE_BUILD_VIEWER`、viz/hosts、geoviz 域）——注入契约承接，不移植不伪造 |
| interpretation/session 服务 | 版本化解释草稿是 deferred seam；面板只收使能矩阵 |
| 在线推理端点调用 | 服务未迁移；诊断侧（失败运行查找 + 日志打码）已移植 |
| MainWindow/AppContext 接线 | W5 集成片域（taskbook §6），本波不接线 |
| `task_panel_base.py`/`prediction_evidence_panel.py`/`object_table.py` 正式版 | UI-11/UI-02 归属文件；本切片在 `ui_wellseis` namespace 交付页面所需薄壳，集成片归并 |

## 冲突面声明

- 根 `CMakeLists.txt`：platform 块内 UI-04 之后新增
  `add_subdirectory(libs/ui_wellseis)`（`PWB_BUILD_PLATFORM + Pwb::UiWorkers
  + Qt6::Widgets` 门控；`pwb_well_science` 缺失时经 `pwb_add_subdirectory_once`
  补入 —— depth-unit 词汇需要）。无新 `option()`。
- 未动 Python UI 文件、未动其他切片文件、未接线 `apps/paleo_workbench_platform`。
