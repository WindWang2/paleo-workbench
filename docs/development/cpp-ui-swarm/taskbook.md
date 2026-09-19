# UI C++ 转换 Swarm 任务书（M10，UI-01 ~ UI-16）

> 目标：`paleo_workbench/ui/` 全部 227 个 Python 文件 C++ 化收尾。
> 协调文档 = 本文件；切片台账 = `docs/development/cpp-ui-swarm/ledgers/ui-NN-*.md`。
> 分区已验证：221 文件分 16 片、0 重复、0 遗漏、6 已移植（见 §5）。

## 0. 先读

- 主计划 `docs/development/cpp-conversion-main-plan.md`：M10 = "原生 QGIS 组件可
  承接面板分层清单 → 按面板簇分期移植 → MainWindow 逐轮长出面板"。
- **conv-16 全量分类**：`docs/development/cpp-ui-panel-inventory.md` +
  `ledgers/16-findings.md` + `16-agent-findings.md` —— 132 个 page 已逐文件分类：
  **CORE 33**（Qt-free 核+薄壳，oracle 富矿）/ **QT 76**（直译 widget）/
  **QGS 13**（QGIS 原生承接）/ **DEFER 10**（依赖未迁移服务层）/ **RET 0**。
  切片 agent 必须先读对应文件的分类与笔记，再实现。
- 已有 C++ UI 面：`libs/ui/`（layer_tree_panel、edit_tool_controller、stage_dock、
  stage_readiness、tool_actions、workbench_layout、constraint_panel、
  layer_properties，CONV-27 交付）；`platform_services`（ThemeService/theme_tokens
  = `ui/theme.py`+`tokens.py`、LayoutKeys、SettingsService）；`job_runtime`
  （= `ui/owned_worker_job.py`+`thread_keeper.py` 语义）；`geo3d_dock`
  （= `pages/geo3d_workspace.py`）。

## 1. 环境

```bash
source ~/pwb-sdks/env.sh          # cmake/ninja/Qt/gdal/proj 进 PATH
cmake --preset linux-native-product   # 全量（含 QGIS platform）
cmake --preset developer-fast         # Qt-free 快速环（PLATFORM=OFF）
```

无 QGIS SDK 时：Qt-only 库可用 `PLATFORM=ON` 但跳过 QGIS 链接的部分需如实披露；
`g++ -fsyntax-only -fPIC $(pkg-config --cflags Qt6Widgets)` 做语法级验证兜底。

## 2. 纪律（与 CONV 系列一致）

1. **每片独立**：`feat/cpp-ui-<name>` 分支 + `../worktrees/cpp-ui-<name>` worktree，
   基于最新 `origin/main`。不得动其他 worktree。
2. **文件归属**：只碰本切片文件清单（§5）+ 自己的新 C++ 文件 + 自己的台账 +
   `.goal-loop-ledger.md` 追加 `## UI-NN 区段`。共享文件最小手术式追加：
   - 根 `CMakeLists.txt`：只在 platform 块加一行 `add_subdirectory(libs/ui_<x>)`，
     **不新增 option()** —— UI 全部 gate 在 `PWB_BUILD_PLATFORM` 下，避免 flag 抢占。
   - `apps/paleo_workbench_platform/*`：本波切片 **不接线**（wiring 是 UI-01
     之后单独的集成片）。切片只交付"库+测试"。
   - `docs/development/cpp-migration-inventory.md`：不动（收尾统一刷）。
3. **库布局**：`libs/ui_<name>/` → `include/pwb/ui_<name>/*.hpp` + `src/` +
   `<name>_tests/` → `Pwb::Ui<Name>` alias。Qt-free 逻辑先进 `<name>_core`
   （不链 Qt），Qt 壳单独 target（job_runtime 双 target 先例）。
4. **Oracle**：CORE 切片（UI-03/04）必须 `tools/oracle/generate_ui_<x>_fixtures.py`
   真实 Python 冻结 + replay + negative check。QT 切片：行为测试对应 Python
   测试用例（`tests/python/**` 若存在）逐条映射，无法 oracle 的写 parity 说明。
5. **测试**：ctest 名 `ui_<lib>.<test>`；`QT_QPA_PLATFORM=offscreen`；
   PROJ_LIB/GDAL_DATA 沿用 tests/cpp/platform 模式；套件 `--no-tests=error`。
6. **审核**：PR 前自审三轮（A=Python parity 逐符号 / B=Qt 边界质量
   （ownership、QObject 树、signal 生命周期、线程亲和、EGL 顶层窗口禁则）/
   C=闭环（无冲突标记、守卫配平、无越界文件）），P0/P1 清零。
7. **不删 Python**；不碰 `_vendored/`、`native_backend.py`；不碰
   `.github/workflows/`；不处理 qgis-renderer CI 预存失败。
8. **台账**：`docs/development/cpp-ui-swarm/ledgers/ui-NN-{findings,decisions,pr}.md`
   （findings = 逐文件 scope 表：Python source → 语义 → C++ 落点 → 终态）。
9. 完成 = 分支 push + `gh pr create`（title `feat(ui): UI-NN — <name>`，
   body 含文件→终态映射、测试清单、limitations）。

## 3. 依赖波次

| 波 | 切片 | 说明 |
|---|---|---|
| W0 | **UI-01** | foundation shell（dock/command/navigation/theme/app_shell），先行串行 |
| W1 | UI-02, UI-03, UI-04 | 无 shell 依赖：设计系统 widgets、CORE 核、worker 核 |
| W2 | UI-05~UI-11 | QT/QGS page 簇（widget 先立，接线后补） |
| W3 | UI-12, UI-13 | workstation 簇（依赖 UI-01 的 dock/command 面） |
| W4 | UI-14, UI-15, UI-16 | 控制器/canvas/visual_qa（依赖服务层与 shell） |
| W5 | 集成片 | MainWindow/AppContext 逐簇接线（另行编号） |

DEFER-10（conv-16）随各簇走：依赖未迁移服务层的语义如实记 decisions，
只搬已验证纪律（offscreen GL 守卫、worker 迟到拒绝、凭证打码），不伪造。

## 4. 终态枚举（同非 UI 口径）

| 终态 | 含义 |
|---|---|
| ported | C++ 语义等价，oracle/行为测试过 |
| wired | 接入产品路径（本波多数片不达成，如实标 ported-only） |
| retired | 被新架构取代（写理由） |
| deferred | 依赖未迁移服务层（写理由 + 已搬纪律清单） |

## 5. 文件分区（逐片清单，已验证不相交）

> 路径相对 `paleo_workbench/ui/`。`[已移植]` = tokens.py、theme.py、
> owned_worker_job.py、thread_keeper.py、pages/geo3d_workspace.py、
> qgis_stack/layer_tree_panel.py —— 复核后在 inventory 标 covered，不重转。

### UI-01 foundation（分支 feat/cpp-ui-foundation）
style.py、dock_framework.py、command_registry.py、navigation.py、dock_manager.py、
shortcuts.py、status_bar.py、map_status_bar.py、page_placeholder.py、
floating_panel.py、panel_float_controller.py、layout_persistence.py、
layout_presets.py、deferred_page_bindings.py、app_shell.py、screen_inventory.py、
crs_guidance.py、operations.py（18）

### UI-02 components+modelview+qgis_stack（22）
components/ 全部 14（badges、buttons、constraint_factor_hud、dialog、
facies_eyedropper、facies_palette_widget、headers、inputs、interactive_qc_hub、
states、stratigraphic_timeline_slider、toast、views）+
modelview/ 全部 3（async_query、object_table、reconcile）+
qgis_stack/ 余 5（canvas_shim、display_canvas、events、mirror、tree_sync、widgets
——注意 widgets/events 是否含未转面，findings 点名）

### UI-03 core-data-preview（20）★oracle 富矿
pages/{asset_table_model、paged_asset_model、data_view_models、data_table_columns、
filter_index、preview_strategy、preview_cache、preview_disk_cache、preview_provider、
preview_worker、preview_settings、interchange_models、qc_helpers、sequence_helpers、
map_edit_commands、map_edit_draft、map_edit_factory、map_edit_items、map_edit_snap、
map_edit_topology}.py

### UI-04 core-workers（7）→ job_runtime 语义
pages/{contour_draft_worker、correlation_load_worker、dtw_propagation_worker、
factor_prepare_worker、geological_modeling_workers、integrity_worker、
well_log_load_worker}.py

### UI-05 qgs-map（7）QGIS 原生承接
pages/{mapping_page、map_canvas_panel、map_layer_tree、map_dock_manager、
map_document_panel、map_chrome_panel、workarea_map_widget}.py

### UI-06 qt-data-home（24）
pages/{data_page、data_workspace、data_asset_table、data_detail_panel、
data_reader_panel、data_toolbar、asset_context_menu、filter_chips_bar、home_page、
hub_page、start_guide_card、onboarding_report_card、new_project_wizard、
project_overview_panel、navigation_tree、action_header、activity_card、
resource_summary、resource_table、result_summary、completeness_card、
module_relationship、tag_widgets、preparation_page}.py

### UI-07 qt-preview（15）
pages/{geotiff、image、json_tree、media、message、pdf、rich_text、seismic_slice、
summary_table、table、text、web_document}_preview_widget.py + preview_widgets.py +
preview_settings_panel.py + lazy_visualization_tabs.py

### UI-08 qt-mapedit（10）
pages/{map_attribute_table、boundary_panel、map_reference_panel、
map_topology_issue_panel、map_workbench_bottom、map_edit_scene、map_edit_view、
map_edit_toolbar、map_factor_shelf、inspector_panel}.py

### UI-09 qt-well-seismic（17）
pages/{well_detail_panel、well_log_canvas_panel、well_log_track_settings、
well_map_panel、well_table_panel、well_seismic_joint_page、well_log_prediction_page、
correlation_link_editor、seismic_attribute_panel、seismic_context_toolbar、
seismic_control_panel、seismic_prediction_page、seismic_task_panel、
seismic_view_panel、cross_well_export_dialog、project_well_map_page、
geological_modeling_3d_page}.py

### UI-10 qt-seq-factor-viz（16）
pages/{sequence_boundary_table、sequence_framework_page、sequence_scheme_summary、
sequence_target_panel、stratigraphy_correlation_page、factor_preview_grid、
factor_task_panel、create_factor_map_dialog、composite_visualization_panel、
composition_panel、visualization_page、visualization_summary_panel、
visualization_trace_panel、geoviz_preview_provider、lithology_crossplot_dialog、
curve_operation_dialog}.py

### UI-11 qt-review-gov（15）
pages/{review_export_page、governance_dialog、catalog_health_dialog、
lineage_explorer_dialog、impact_preview_dialog、version_workbench_dialog、
prediction_evidence_panel、prediction_task_panel、ingest_plan_dialog、
relink_dialog、ai_check_advisor_dialog、qc_issue_table、task_panel_base、
workflow_contract_panel、prototypes/workstation_composite_prototype}.py

### UI-12 workstation-shell（16）
workstation/{shell、app_bar、activity_rail、explorer、inspector、task_center、
process_hub、tool_surface、ui_context、mode_state、state_language、
keybinding_manager、action_help、common、stage_actions、agent_panel}.py

### UI-13 workstation-composite（13）
workstation/{composite_attribute_table、composite_document、composite_editing、
composite_panels、mapping_stage_bar、mapping_stage_panel、layer_decorations、
facies_selector、merge_features_dialog、topology_checker_panel、tool_page_dialog、
attribute_schema、linked_workspace}.py

### UI-14 root-controllers（6）
{data_lifecycle_controller、project_controller、workflow_controller、
map_action_controller、project_save_worker、view_coordination}.py

### UI-15 root-canvas（8）
{unified_map_canvas、native_map_canvas、native_layer_tree、native_render_worker、
map_layer_properties、map_symbology_bridge、map_export_worker、
preview_settings_dialog}.py

### UI-16 visualqa-misc（7）
visual_qa_v{6,7,8,9,10,11}.py + prototypes/proto_dual_volume_overlay.py

## 6. 收尾（全部切片后）

1. 逐簇集成片：MainWindow/AppContext 接线（页注册表 → dock/navigation）。
2. `pwb_migration_inventory.py` 刷新 + 本表终态汇总。
3. 全量 configure+build+ctest ×2（linux-native-product）。
4. ui 包 Python 文件状态矩阵：ported/wired/retired/deferred，逐个有据。
