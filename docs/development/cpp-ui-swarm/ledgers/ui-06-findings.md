# UI-06 `qt-data-home` — 侦察与移植台账

权威分片(taskbook.md UI-06):24 个 `pages/*.py`,数据管理/首页/工程概览面。
工作树 `/home/kevin/project/worktrees/cpp-ui-data-home`,基线 = UI-01 提交
`69c01d05`(含 `libs/ui_shell`)。新库 `libs/ui_pages_data/`:

- `pwb_ui_pages_data`(STATIC, C++20, Qt-free 语义核)→ `Pwb::UiPagesData`
- `pwb_ui_pages_data_qt`(STATIC, Qt Widgets 面, `if(TARGET Qt6::Widgets)`)→ `Pwb::UiPagesDataQt`
- 测试目录 `libs/ui_pages_data/ui_pages_data_tests/`;ctest 前缀 `ui_pages_data.*`
- 头文件 `include/pwb/ui_pages_data/`;所有 Q_OBJECT 头显式列入 target sources
- 根 CMake:仅在 `if(PWB_BUILD_PLATFORM)` 块内 `add_subdirectory(libs/ui_shell)` 之后
  追加 `add_subdirectory(libs/ui_pages_data)`(本台账登记)

## 共享接缝(被多个源文件引用、非本切片所有)

| Python 依赖 | 属主切片/库 | C++ 策略 |
|---|---|---|
| `FilterQuery` / `CatalogCounts` (filter_index.py) | UI-03 | `pwb::ui_pages_data::FilterQuery`/`CatalogCounts` POD 替身;UI-03 落地后去重 |
| `DataStage`/`IntegrityState`/`AssetView`/`asset_view_from_object` (data_view_models.py) | UI-03 | 字符串词表 + `AssetView` seam 结构替身 |
| `FilterIndex`/`compute_catalog_counts`/`AUXILIARY_TYPES`/`CATEGORIES` (filter_index.py) | UI-03 | 词表常量移植;FilterIndex 由 widget 注入 `AssetFilterIndex` 接口 |
| `tokens.*`(RESOURCE_LABELS/UNITS、STEP_LABELS、STATUS_TEXT、QC_*) | UI-14 tokens | `vocab.hpp` 常量表(token 接缝,去重路径登记) |
| `style.bind`/`style.palette`/`tokens` 间距 | UI-14 style | Qt 面用 `pwb::ui_shell::style_bind`(StyleRegistry) |
| `modelview`/`ObjectTableModel`/`ColumnSpec`/`bind_table_defaults` | UI-03 | 本库自带 `QAbstractTableModel`(ResourceTableModel 等);UI-03 落地后可换 |
| `components.states.PwbEmptyState` | UI-02 | `PwbEmptyStateView` 占位(QLabel 双行)替身 |
| `workstation_icon`/`tinted_map_icon` (workstation.common) | UI-12 | `icon_provider` std::function 注入,默认空 QIcon |
| `dock_manager`/`LayoutPersistence`/`FloatController` | UI-01 ✅ | 直接用 `pwb::ui_shell` 同名类 |
| `OwnedWorkerJob`/`CancellationToken` | CONV-30 ✅ | `pwb::job::qtbridge::JobOwner` + `stop_token` |
| `InspectorPanel`/`WellMapPanel`/`WellDetailPanel` | UI-07 等 | widget 工厂注入;默认 `PagePlaceholder` |
| `preview_provider`/`preview_widgets`/`preview_settings`/`lazy_visualization_tabs`/`geoviz_preview_provider`/`media_preview_widget` | UI-04/05 | `PreviewProvider`/`PreviewResult` seam + 注册表分派;原生实现 text/message/empty/image/table,其余 mode 走 message 回退(台账登记) |
| `dashboard_state`/`STEP_ORDER`/`REQUIRED_RESOURCE_TYPES` (workflow.service) | workflow ✅部分 | `STEP_ORDER`/词表为常量;`dashboard_state` 输出形状 → `DashboardStateView` seam(Json) |
| `analyze_data_folder` (project.onboarding) | 未移植 | `analyze_fn` 注入 |
| `build_workarea_map_snapshot`/`workarea_view_extent`/`snapshot_has_map_content`/`workarea_crs_warnings`/`domain_signature`/`create_display_canvas`/`WORKAREA_LEGEND_ITEMS` | 未移植(mapping) | `MapSnapshot`/`DisplayCanvas` 接口注入 |
| `role_definition`/`roles_for_entity_type` (project.roles) | 未移植 | `role_order_fn`/`role_display_fn` 注入(默认 role 本身) |
| `is_reference_well`/`coordinate_status_is_flagged` (project.domain) | project ✅部分 | seam 内存原始字段,谓词在核内复刻(oracle 验证) |
| `catalog` service(tag_usage/search_tags/create/rename/merge/delete/prune,CatalogError) | catalog ✅部分 | `TagService` 抽象接口;错误经 `CatalogError`-等价异常 |
| `import_service`/`export_service`/`exporters`/`DataLifecycleController`/`IntegrityCheckReport`/`PreviewRequestController`/`RelinkSourcesDialog`/`CatalogHealthDialog`/`GovernanceMetadataDialog`/`well_location_map.sync` | 服务层/其他切片 | `DataPageServices` 抽象接口全注入;DataPage 只含编排 |
| `get_available_formats`/`raw_layer_gate_reason` | resources/mapping | 上下文菜单 builder 参数注入(gate reason 用 `pwb::tool_policy` 若可用,否则注入) |
| `BoundaryPanel`/`FactorTaskPanel`/`FactorPreviewGrid`/`WellTablePanel` | UI-08/09/10 | 工厂注入(带 `method_combo/generate_btn/...` 属性的最小接口) |
| `factor_prepare_scheduler`/`well_qc`/`well_table`/`contour_draft_worker`/`factor_prepare_worker` | workflow 未齐 | `PrepareBackend` 接口注入 |
| `qc_helpers.derive_rule_result` | 本文件私有(qc_helpers 属本切片边界外? — qc_helpers.py 不在 24 文件清单) | 核内复刻(28 行;语义=issues 匹配 rule、error>warning、首条 message) |
| `QSettings` | Qt | saved_filters 直接 QSettings,key `data_explorer/saved_filters` 不变 |
| `QtPdf` | Qt | `find_package(Qt6Pdf QUIET)`;有则真渲染,无则 `PWB_UI_PAGES_DATA_NO_PDF` 编译期降级(仅页签容器;台账登记) |

## 源 → 语义 → C++ 目标 映射

| # | 源文件(行) | 关键语义 | C++ 目标 | 深度 |
|---|---|---|---|---|
| 1 | `start_guide_card.py` (61) | PanelCard + 3 按钮 → `new_project_requested`/`open_project_requested`/`open_sample_requested` | qt: `StartGuideCard` | 全量 |
| 2 | `onboarding_report_card.py` (171) | report dict → 6 label 显隐+文本;by_type 降序;extent [x,x]·[y,y] `.1f` 或"无坐标井位范围";issues+warnings 合并前 5 条 | core: `format_onboarding_report(Json)→ReportView` + qt: `OnboardingReportCard` | 全量(oracle) |
| 3 | `resource_summary.py` (80) | readiness dict → REQUIRED 类型计数+单位;"数据完整"/"缺少: A、B";ready→SUCCESS/ERROR_RED | core: `format_resource_readiness` + qt: `ResourceSummaryBar` | 全量(oracle) |
| 4 | `completeness_card.py` (117) | 同上 + 每类型行 已就绪/缺失 + summary tone | core 复用 + qt: `DataCompletenessCard` | 全量(oracle) |
| 5 | `activity_card.py` (113) | 非 pending steps → "刚刚, {STEP_LABELS[i]}: {STATUS_TEXT[s]}";全 pending → fallback 六项(resource_counts dict 求和带"项"后缀,余 int>0);"暂无活动"显隐 | core: `compute_activity_entries` + qt: `RecentActivityCard` | 全量(oracle) |
| 6 | `action_header.py` (107) | horizon 解析:reports[0].linked_map_document_id→docs 匹配,否则 docs[-1].horizon,再否则"—";规则 chips=reports[0].rules 否则 DEFAULT_QC_RULES;run⇔docs、export⇔reports、finalize⇔docs | core: `resolve_action_header` + qt: `ActionHeader`(4 信号) | 全量(oracle) |
| 7 | `result_summary.py` (161) | reports[0].rules 逐条 derive_rule_result→pass/warning/error 计数;error>0→红"建议先处理…"否则绿"全部通过…";artifacts→"• {fmt} — {path}" | core: `derive_rule_result`+`summarize_qc` + qt: `ResultSummary` | 全量(oracle) |
| 8 | `resource_table.py` (147) | 5 列(文件名/类型label/格式/状态/路径);status 前景 token parsed→SUCCESS,error→ERROR_RED,else TEXT_SECONDARY;key=id‖path‖name;空态 PwbEmptyState 覆层 | core: `status_color_token` + qt: `ResourceTableModel`(QAbstractTableModel)+`ResourceTable` | 全量 |
| 9 | `filter_chips_bar.py` (249) | `_dimensions`:非 all 视图(`_NODE_LABELS`+` · value`)/text/stage/type/每 tag 一 chip/tags>1 时 operator chip(全部满足⇔and)/asset_id→第二个 view chip"资产: {id[:16]}…";QSettings JSON [{name,query}] 保存/应用/删除 | core: `filter_dimensions`+`query_to_dict`/`query_from_dict`+`saved_filters_load/dump` + qt: `FilterChipsBar`/`FilterChip`(信号 chip_removed/clear_all/filter_applied) | 全量(oracle) |
| 10 | `data_asset_table.py` (672) | 见下"表格" | core: `remove_filter_dimension`+`ordered_column_keys`+`asset_key` + qt: `DataAssetTable` | 大部分(oracle 覆盖 query 变换) |
| 11 | `asset_context_menu.py` (254) | build→有序动作模型:trashed→restore+open_folder+open_system;RAW→create_derived/(well_log,las→curve)/edit_locked(gate reason);DERIVED‖INTERMEDIATE→new_version+promote;OUTPUT→export_open;!managed→materialize/relink(disabled);verify;version_wb/lineage(disabled);add_tag;ResourceItem→rescan+归类为 submenu(CATEGORIES 去 None/自身);export submenu(get_available_formats+INVENTORY for ResourceItem);open_folder;open_system(本地路径非 http/https/ftp 才 enabled);viz/well/seismic 条件;分隔;remove(红 icon);多选→hdr+3 bulk+分隔+bulk_remove | core: `build_asset_menu_model` + qt: `AssetContextMenu` | 全量(oracle) |
| 12 | `navigation_tree.py` (898) | 树模型:全部/回收站/工区概览/entity_group(井◉/地震◈)/其他参考井◆/地质解释/辅助资料/工作数据(derived,intermediate)/成果(output);生命阶段/数据类型/标签/状态完整性/治理 组;entity 排序(name,id) 分页 500/页 + "▣ 显示更多(x/y)";well 展开 role 分组(role_order 注入,display,计数) + 文件叶 cap 30 + overflow "…另有 N 个文件";⚠/⚠坐标 标记;counts 更新 label `{base} {n}`;tag/review 动态叶 + 选中消失→回落全部;`highlight_well` 按需物化页;上下文菜单 管理标签/删除井;信号 category_changed/filter_query_changed/entity_activated/delete_well_requested/manage_tags_requested | core: `NavTreeModel`(NavProjectView seam) + qt: `NavigationTree` | 全量(oracle 覆盖行模型) |
| 13 | `module_relationship.py` (764) | status→tone(complete→success,running→primary,pending→neutral,warning→warning,failed→error);step→card 映射 data_check→data,factor_map→sequence,prediction→well+seismic,map_compile→facies,qc→mapping;卡点击→navigation_requested(int);QPainter 手绘箭头/虚线/图例 | core: `step_card_tones` + qt: `ModuleCard`/`ModuleRelationshipCanvas`/`ModuleRelationshipWidget`/`LegendWidget` | 全量(oracle 覆盖映射;绘制为原生) |
| 14 | `hub_page.py` (115) | pill 切换 + QStackedWidget;add_submodule(>1 才显示切换条);switch_to→active 属性 polish+activate_page 转发+page_activated(hub,key),emit 时另发 submodule_changed | qt: `HubPage` | 全量 |
| 15 | `data_toolbar.py` (316) | 13 信号;import 下拉(文件/文件夹/计划);verify→取消校验 切换;tag 过滤菜单(checkable tags+and/or)+tag_manager;搜索 180ms 去抖;cancel_import 仅运行时可见;column_settings_slot;reader_toggled;set_search_text_silent 防回环 | qt: `DataToolbar` | 全量 |
| 16 | `data_detail_panel.py` (434) | PdfPreviewPanel:420×560 基准,×1.25 步进,0.10–8.00 夹紧,Ctrl+wheel;页 prev/next;详情卡路由 ResourceItem vs ExportArtifact→元数据+预览路由 | core: `PdfZoomModel` + qt: `PdfPreviewPanel`(Qt6Pdf 可选)+`DataDetailPanel` | 全量(oracle 覆盖 zoom;QPdf 可选) |
| 17 | `data_reader_panel.py` (705) | mode→handler 分派表 13 种;`render` 流程(stop media⇔mode!=media、viz 可用判定、geoviz prepared 判定、`_load_target_widget`、`_commit_result`:title/meta/warning(表格截断合并)/stack 切换/toolbar 显隐/reader_mode_changed);show_loading;lazy media/web/geoviz;settings 传播;copy TSV/系统打开;context menu | core: `preview_target(mode)` + qt: `DataReaderPanel`(`PreviewProvider` 接口注入;原生 empty/message/text/table/image,其他 mode→message 回退登记) | 大部分(分派+commit 全量;重型预览 widget 为 seam) |
| 18 | `data_workspace.py` (270) | 三列 splitter(nav | center stack: table/overview/well_detail | right splitter reader/inspector);dock keys data:navigation|reader|inspector|well_map;FloatController+LayoutPersistence(ui_shell);400ms 持久化去抖;map 面板 overview 态重挂载+折叠态保存;float 时展开/dock 回 fold | qt: `DataWorkspace`+`PanelFloatButton`(非我面板的 3 个 widget 工厂注入) | 全量(布局/浮动) |
| 19 | `new_project_wizard.py` (502) | step1 校验(名非空/数据目录存在/同目录或中间目录存在/{name}.paleo.json 不存在);step2 状态机 idle/running/success/failed;分析报告→summary/清单表(≤260px)/issues≤20/井图;Back/reject/close 关 worker;640 minW,860×640 | core: `validate_step1`+`format_analysis_summary` + qt: `NewProjectWizardDialog`(`analyze_fn`+JobOwner) | 全量(oracle 覆盖校验+摘要) |
| 20 | `project_overview_panel.py` (189) | 8 统计块:wells/surveys=len;raw/derived(+intermediate)/output=stages 或"—"(counts None);issues=missing+modified 或"—"(integrity_known=False);unresolved=unresolved_links+flagged_coords;recent=最新 compilation_run(updated_at).name 或"—";meta=CRS+区域;hints 3 种(unresolved/bad_coords/boundary‖wells 范围 .1f) | core: `compute_project_overview` + qt: `ProjectOverviewPanel` | 全量(oracle) |
| 21 | `tag_widgets.py` (712) | `parse_multi_tag_input`:分隔 [,，;；\s]+、strip、lstrip#、截 128 字符、保序去重;TagBadge/容器(添加钮);TagInputDialog(existing 校验);MultiTagInputDialog;TagSelectDialog(checkable);TagManagerDialog:usage 表(name/display_name/assets/versions、搜索过滤、display_name casefold 排序)、错误→hint 不装空表、create/rename(collision→merge 确认)/merge/delete(in_use 拒)/prune(全量计数确认)、行双击→tag_selected | core: `parse_multi_tag_input`+`tag_usage_rows(service seam)` + qt: 全部 6 组件(`TagService` 抽象) | 全量(oracle 覆盖 parse+rows) |
| 22 | `preparation_page.py` (377) | 3 列 splitter(240/900/240);panels 注入;`_resolve_display_well_table`(project.well_tables[0] 优先,否则首个带 sample_points 的 task→well_table_from_factor_task);generation 守卫(current vs prepare_generation,项目切换作废);QC 流程+汇总字符串;prepare/contour 双 JobOwner;summary_label 文案;shutdown_workers 3000ms | core: `resolve_display_well_table`+`format_prepare_progress/done` + qt: `PreparationPage`(panel 工厂+`PrepareBackend` 注入) | 大部分(oracle 覆盖解析+文案) |
| 23 | `home_page.py` (387) | map 第一(swap snapshot⇔domain_signature 变化才重建;extent;空态;CRS warnings 横幅"⚠ "+"；".join);16px 井拾取最近邻→well_activated;step→contract 映射首个 pending/stale/running/warning;start guide 显隐(total_resources==0 && !has_report);report card;side column 显隐=任一卡可见;常量 340/260/380 | core: `pick_well(features,click,tol)`+`first_incomplete_contract(steps)`+`guide_visibility` + qt: `HomePage`(DisplayCanvas/MapSnapshot 接口注入) | 大部分(oracle 覆盖纯函数;canvas 为 seam) |
| 24 | `data_page.py` (3154) | 8 worker 类+页面编排:~150 方法。本切片职责=页面外壳:toolbar+workspace 组合、13+ 信号、`update_state` stage 推导(_stage 名称映射)、FilterQuery 路由(tree→table、paged 回退)、trash 视图、selection 发布(data_context_changed)、busy 标志+JobOwner 槽、shutdown_workers(5000ms);服务调用全部注入 | qt: `DataPage`(`DataPageServices` 全注入;import/register/rescan/bind/deliver/export/verify 经 JobOwner);core: `page_stage_map`+`context_payload` | 外壳+路由(oracle 覆盖纯函数;管线本体为 seam,见下) |

## data_asset_table 细目(#10)

- `_remove_filter_dimension` 键集:view(→all+清 asset_id)/text(清空+emit)/stage/type/tag_operator(→and)/tag:<name>(移除该 tag) — 移植为 core `remove_filter_dimension`,oracle 覆盖。
- `set_visible_columns`:按 COLUMN_DEFINITIONS 顺序+required 恒在;空→["name"]。
- `set_search_text`:strip().lower() 后回灌 query.search_text。
- `apply_saved_filter`:先采用 query.search_text 再走 set_filter_query(修 #应用过滤器 语义)。
- 选中恢复 `_asset_key`=("artifact"|"resource", id)、`_sync_selection`(wanted 集合→visible 行序恢复)、`_emit_selection_changes`(主/多选 diff 才 emit)。
- 排序:`_on_header_clicked` 显式方向切换;`_reapply_sort` 重放 model.last_sort。
- 列宽:auto-fit 仅列集变化时;user_resized 豁免;>4000 cell 走固定 120px;max 300。
- paged 模式:provider seam(`CatalogPageProvider` 接口);unmappable→`paged_mode_unavailable`+回退物化;`row_for_key` 恢复选中。本切片:接口+物化路径全量;SQL provider 实现为 seam(UI-03/catalog)。
- `FilterIndex`/`AssetTableModel`/`PagedAssetTableModel`/`data_table_columns`/COLUMN_DEFINITIONS 属 UI-03 → 本表注入 `AssetTableModelBase` 接口(或内置最小列模型,默认 8 列:文件名/类型/格式/阶段/大小/状态/路径/标签 — 以 Python COLUMN_DEFINITIONS 为准)。

## 未移植/延期(理由)

1. **data_page.py 管线本体**:import/register/rescan/deliver/export/verify 的 worker 体=服务编排(import_service/lifecycle/delivery/exporters/integrity)。C++ 侧 `libs/data_suite`/`libs/catalog`/`libs/ingest` 词表不同,忠实接线=集成任务。本切片移植页面外壳+状态机+路由,管线经 `DataPageServices` 接口注入——不复制服务。
2. **重型预览 widget**:well_log/seismic/pdf(QPDF 可选)/rich_text/web_document/json_tree/geotiff/media/geoviz/lazy_visualization_tabs 属 UI-04/05。DataReaderPanel 原生实现 empty/message/text/table/image + 分派/commit 全量;未知 mode 走 message 回退(与 Python `get` 缺省一致)。
3. **WellMapPanel/InspectorPanel/WellDetailPanel/BoundaryPanel/FactorTaskPanel/FactorPreviewGrid** — 非本切片文件,工厂注入 + PagePlaceholder。
4. **HomePage 地图后端**:build_workarea_map_snapshot/display canvas 未移植 → `MapSnapshotProvider`/`DisplayCanvas` 接口;widget 测层用 stub canvas。
5. **PreparationPage 科学后端**:factor_prepare_scheduler/contour_draft_worker/well_qc/well_table 未移植 → `PrepareBackend` 接口;页面守卫/文案/生命周期全量。
6. **对话框**:RelinkSourcesDialog/CatalogHealthDialog/GovernanceMetadataDialog/版本工作台/血缘浏览器 — 非本切片文件 → 工厂 seam。
7. **QtPdf**:系统存在 `find_package(Qt6Pdf)`;编译期探测,缺失时 `PWB_UI_PAGES_DATA_NO_PDF` 降级为页签容器(如实登记,不假装渲染)。

## 测试计划

- Oracle 生成器 `tools/oracle/generate_ui_data_home_fixtures.py`:leaf-load + PySide6 stub(沿用 generate_ui_shell_fixtures.py 手法),冻结真实 Python 输出:
  - `parse_multi_tag_input`(~12 用例:全角分隔/#前缀/去重/128 截断/空)
  - `filter_dimensions`+`remove_dimension`(~14 用例:每维度、tag 组、operator、asset view、清除)
  - saved_filters 序列化往返(~4)
  - `format_onboarding_report`(~6:无报告/全字段/无 extent/异常 extent/by_type 排序/超长 issues)
  - readiness strip + completeness(~5)
  - activity entries(~5:混合 steps/全 pending+fallback/空)
  - `build_asset_menu_model`(~10:RAW well_log/RAW 其他/DERIVED/INTERMEDIATE/OUTPUT/trashed/unmanaged/多选/带 viz+预测/带 formats)
  - `NavTreeModel`(~8:构建/排序分页/role 分组 cap/flags/counts/tag+review 回落/entity 文件叶)
  - `compute_project_overview`(~5)
  - `resolve_action_header`/`summarize_qc`/`derive_rule_result`(~8)
  - `validate_step1`/`format_analysis_summary`(~8)
  - `step_card_tones`/`pick_well`/`first_incomplete_contract`/`guide_visibility`(~8)
  - `PdfZoomModel`(夹紧边界 ~6)
  - `resolve_display_well_table`+prepare 文案(~5)
  - `ordered_column_keys`/`asset_key`(~4)
  合计 **~115 冻结用例**。
- C++ 回放 `ui_pages_data.oracle_replay` + 负自检(篡改 fixture 必失败)。
- Qt 冒烟 `ui_pages_data.qt_widgets_smoke`(QT_QPA_PLATFORM=offscreen):全部 widget 构造+信号+update_state 往返。

## 验证实绩(post-mortem 补全)

原 agent 在测试前终止;后续由协调流程补全:

- `ui_pages_data.smoke`(69 checks / 0 failures)— 覆盖 tag 解析(全角分隔/#
  前缀/保序去重/128 字符截断)、PdfZoomModel(1.25 步进/0.10–8.00 夹紧/页导航/
  Ctrl+wheel)、filter_dimensions+remove(8 维含 operator chip,已核对 Python
  `filter_chips_bar._dimensions` 顺序:view→text→stage→type→tags→operator→asset
  view)、saved_filters JSON 往返+重名去重+casefold 排序、activity fallback
  ("数据资源: N 项" 半角冒号,已核对 `activity_card._append_entry`)。
- 计划中的 `generate_ui_data_home_fixtures.py` oracle 生成器未实现(登记为
  缺口;smoke 期望值已逐一对照 Python 源核实,非冻结回放)。
- `pwb_ui_pages_data_qt` 修复轮(moc/编译):补 QLabel/QTextEdit/QTableView/
  QPixmap/QStyle include;`home_page.hpp` WellPickPoint 经 `home_model.hpp`;
  `ModuleMapWidget`→`ModuleRelationshipWidget`、`NavigationTreeWidget`→
  `NavigationTree` 正名;`module_map_widget.cpp` 局部 `slots`→`card_slots`
  (Qt `slots` 宏冲突);`AssetView` 增 `checksum`/`linked_id`;
  `vocab` 增 `resource_type_label()`(RESOURCE_TYPE_LABELS 复刻);
  `DataToolbar::icon_provider()` 公开静态访问器。
- ctest `ui_pages_data.*` 100% pass;Qt widget smoke(offscreen)未实现(缺口,
  widget 面仅经编译验证)。

## 接线状态备注（2026-09，#1392 台账）

- `ResourceTable`/`ResourceTableModel`（src/qt/resource_table.cpp 整 TU）
  截至本日期全仓**零调用方**（未接线死代码）；保留备后续资源面板接线，
  勿与 `DataAssetTable` 双份维护。

## 根 CMake 变更登记

`if(PWB_BUILD_PLATFORM)` 块内 `add_subdirectory(libs/ui_shell)` 之后追加一行
`add_subdirectory(libs/ui_pages_data)`。无新 option。
