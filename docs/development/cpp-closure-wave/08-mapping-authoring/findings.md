# 08 — findings（盘点结论，全部经代码核实）

## 能力清单基线（本线 implemented/merged/wired/verified 四列）

| 能力 | Python 冻结源 | C++ 核 | wired | verified |
|---|---|---|---|---|
| 组合文档模型/会话 | mapping/composer/{models,components}.py | libs/mapping_document composition{,_session} (CONV-02/27, oracle) | service facade 有 | oracle 有 |
| 组合面板 UI | ui/pages/composition_panel.py (941 行) | libs/ui_seqviz qt/composition_panel.{hpp,cpp} **从未编译** | ❌（CMake 除名） | ❌ |
| 制备 worker 核 | factor_prepare_worker.py + workflow/factor_prepare_scheduler.py | libs/ui_workers factor_prepare（oracle） | seam 注入待接 | oracle 有 |
| 等值线核 | contour_draft_worker.py + workflow/contour_draft.py | libs/ui_workers contour_draft（oracle） | seam 注入待接 | oracle 有 |
| 制备页组装 | ui/pages/preparation_page.py (377 行) | libs/ui_pages_data qt/preparation_page.hpp 有 / **.cpp 不存在** | ❌（PagePlaceholder） | ❌ |
| 制备子面板 | factor_task_panel / well_table_panel / factor_preview_grid / boundary_panel | ui_seqviz factor_panels / ui_wellseis well_table_panel / ui_pages_mapedit {factor_preview_grid,boundary_panel} | ❌（无宿主） | 部分组件测试 |
| 编图编辑场景 | ui/pages/map_edit_scene.py 等 | libs/ui_pages_mapedit（17 TU + 32 测试） | ❌ **无任何 app 实例化**（ui_map mapping_page.cpp:81 仅占位文本） | 组件级 widget 测试有 |
| 地图文档模型/IO | mapping/document_io.py, layers.py | mapping_document map_document/document_io/map_document_session/document_service | facade 有 | oracle 有 |
| 编图画布壳 | mapping_page.py | libs/ui_map MappingPage（图层树/dock/浮动真件；编辑视图/参考/组图/底部=占位） | AppShell hub3 canvas 已装 | ui_map 测试有 |
| 原生编辑会话 | mapping/native_edit_session.py 等 4 文件 | PR #1412（未合并）feat/cpp-map-document-edit-session | ❌ | PR 内自述全绿 |

## 关键事实

1. **三个“缺失 API”在 Python 无对应物**：`composition_history_state`/`schema_editor_descriptors`/
   `element_geometry_state` 只出现在未编译的 composition_panel.cpp 中（L568/L590/L610），是 agent
   杜撰名。真实 core API：`history_state(session*)`（返回 HistoryState{can_undo,can_redo}，无 tip 字段）、
   `schema_editor_descs(property_schema_json, element, chart_series_schemas)`、
   `property_geometry_state(element*)`（返回 GeometryView{x,y,w,h,editable,lock_hint_visible}）。
2. composition_panel.cpp 其余偏差：make_editor 用了 core 没有的 SchemaEditorKind::Int 与
   desc.decimals/step/options 字段（core 为 Number(min,max)/choices）；SeriesTable 契约是
   [{label,value}] 两列（label/value），panel 画的是 curve/label；Json kind 是 QLineEdit JSON 框
   （初始文本 desc.json_text），Text 才是 QTextEdit；duplicate 应走 session_->duplicate_element；
   set_element_flag → set_locked；reorder_element(mode) → bring_to_front/send_to_back；
   apply_element_geometry 的 field ∈ {x,y,w,h}（panel 传 x_mm/width_mm 等）。
3. core 缺 3 个值转换助手（panel 需要）：schema_bool_value / schema_float_value / schema_text_value
   （Python bool()/float() 失败→0.0/str 语义；series_collect 内部已有同款 float 语义）。
4. **MapEditScene 绑定 PaleoMapDocument 形状 Json\*（非拥有）**，legacy 键
   facies_polygons/well_overlays/line_features/label_features；document_io::features_from_document/
   apply_features_to_document 正是 mapping_document::MapDocument ↔ legacy 记录 的桥。
   → closure 适配器以此让 MapDocumentService 成为持久化权威（crs/样式/期次字段在层与 metadata）。
5. PreparationPage.hpp 是全注入设计（域对象以 void* 传递）；真实域核在 ui_workers
   （build_prepare_snapshot L228 / 运行面），commit_prepare_batch_result / commit_contour_drafts
   按 Python 契约 host-side —— 由本线 closure 适配器实现，落 libs/project schema 的
   factor_map_tasks / contour_drafts 段（schema.cpp L513/515 已有）。
6. 工程模型：libs/project schema 已含 contour_drafts/factor_map_tasks JsonList；
   paleomap 文档无专属段 → 期次/图件文档由 closure_mapping 以 MapDocumentService bank 持有
   （原生 .mapdoc JSON 文件，save_file 原子写+bak 恢复），不建第二套文档模型。
7. AppShell hub3：`add_submodule("preparation","数据制备", PagePlaceholder)`（app_shell.cpp L201-203）；
   ui_map::MappingPage 4 个占位槽 objectName：MapEditView/MapReferencePanel/CompositionPanel/
   MapWorkbenchBottom（mapping_page.cpp L81/L100/L111/L146）。
8. 命名块模式：main_window.cpp `// BEGIN <TOKEN>` + `#ifdef PWB_WITH_<TOKEN>`；安装器先例
   viz_a_install.hpp `bool install(...)`；04 线在 app_shell 用函数级租约（adopt_data_page）。
9. 依赖：PR #1412（mapping_document 原生编辑会话核）未合并。本线 R2–R5 不依赖它（编译/面板/
   制备/场景级 undo-redo 与保存闭环独立成立）；原生 QGIS 桥编辑接线属其范围，登记为后续合流项。
10. 资源门/工具链坑：cmake 不在默认 PATH（/home/kevin/pwb-sdks/root/usr/bin，需 LD_LIBRARY_PATH=
    .../usr/lib 引 librhash）；ninja 有 -j40 alias，必须显式 -j≤2。QGIS vendor 产物只读复用主
    工作区，源树用本 worktree vendor 副本（06 线同款配置）。
