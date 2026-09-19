# UI Python 状态矩阵（W5/UI-17 终态汇总）

`paleo_workbench/ui/` 233 个 `.py` 文件的迁移终态，逐文件有据。

- **wired**（177）：C++ 对应物在 `pwb-platform` 链接闭集内，经 AppShell 页注册表/
  dock/navigation 路径接入产品。证据：`ninja -t commands pwb-platform` 的链接行
  + `platform.app_shell` / `platform.qgis_smoke_app`（offscreen 全链绿）。
- **ported**（47）：C++ 对应物编译进 lib target 且过测试，但不在 app 链接闭集
  （预览 widget 宿主注入、编修场景、控制器、独立 canvas、QA harness）。
- **deferred**（3）：无可用 C++ 实现，理由逐文件注明——绝不以占位实现冒充。
- **retired**（6）：`__init__.py` 包胶水，无 C++ 对应物概念。

| 文件 | 状态 | 切片 | 证据 |
|---|---|---|---|
| `__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `app_shell.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `command_registry.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `components/badges.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/buttons.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/constraint_factor_hud.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/dialog.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/facies_eyedropper.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/facies_palette_widget.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/headers.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/inputs.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/interactive_qc_hub.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/states.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/stratigraphic_timeline_slider.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/toast.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `components/views.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `crs_guidance.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `data_lifecycle_controller.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `deferred_page_bindings.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `dock_framework.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `dock_manager.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `floating_panel.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `layout_persistence.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `layout_presets.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `map_action_controller.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `map_export_worker.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `map_layer_properties.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `map_status_bar.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `map_symbology_bridge.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `modelview/__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `modelview/async_query.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `modelview/object_table.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `modelview/reconcile.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `native_layer_tree.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `native_map_canvas.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `native_render_worker.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `navigation.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `operations.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `owned_worker_job.py` | wired | pre-ported | job_runtime qtbridge JobOwner（链接闭集内） |
| `page_placeholder.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `pages/action_header.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/activity_card.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/ai_check_advisor_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/asset_context_menu.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/asset_table_model.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/boundary_panel.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/catalog_health_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/completeness_card.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/composite_visualization_panel.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/composition_panel.py` | deferred | UI-10 | composition_panel.cpp 引用未交付的 mapping_document 组合 API（composition_history_state/schema_editor_descriptors 等），从未编译过——从 pwb_ui_seqviz_qt 源表除名登记 |
| `pages/contour_draft_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/correlation_link_editor.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/correlation_load_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/create_factor_map_dialog.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/cross_well_export_dialog.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/curve_operation_dialog.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_asset_table.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_detail_panel.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_page.py` | deferred | UI-06 | DataPage 复合页未实现——无 data_page.cpp；AppShell 由 DataWorkspace 承载管理面（libs/ui_pages_data/CMakeLists.txt 登记 deferred） |
| `pages/data_reader_panel.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_table_columns.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_toolbar.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_view_models.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/data_workspace.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/dtw_propagation_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/factor_prepare_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/factor_preview_grid.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/factor_task_panel.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/filter_chips_bar.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/filter_index.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/geo3d_workspace.py` | ported | pre-ported | libs/geo3d_viz（PWB_BUILD_GEO3D_VIZ=OFF——native 3D 查看器不在本配置产品闭集） |
| `pages/geological_modeling_3d_page.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/geological_modeling_workers.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/geotiff_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/geoviz_preview_provider.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/governance_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/home_page.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/hub_page.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/image_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/impact_preview_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/ingest_plan_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/inspector_panel.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/integrity_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/interchange_models.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/json_tree_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/lazy_visualization_tabs.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/lineage_explorer_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/lithology_crossplot_dialog.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_attribute_table.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_canvas_panel.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_chrome_panel.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_dock_manager.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_document_panel.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_commands.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_draft.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_factory.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_items.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_scene.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_edit_snap.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_toolbar.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_edit_topology.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_edit_view.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_factor_shelf.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_layer_tree.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/map_reference_panel.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_topology_issue_panel.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/map_workbench_bottom.py` | ported | UI-08 | UI-08 → ui_pages_mapedit（编修场景 Qt 面未入 app 链接闭集） |
| `pages/mapping_page.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/media_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/message_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/module_relationship.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/navigation_tree.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/new_project_wizard.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/onboarding_report_card.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/paged_asset_model.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/pdf_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/prediction_evidence_panel.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/prediction_task_panel.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preparation_page.py` | deferred | UI-06 | PreparationPage 实现 deferred——仅有头（Q_OBJECT 已从 AUTOMOC 除名，避免无定义 thunk）；AppShell 在 数据制备 槽位放 PagePlaceholder |
| `pages/preview_cache.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preview_disk_cache.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preview_provider.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preview_settings.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preview_settings_panel.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/preview_strategy.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/preview_widgets.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/preview_worker.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/project_overview_panel.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/project_well_map_page.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/prototypes/workstation_composite_prototype.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/qc_helpers.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/qc_issue_table.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/relink_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/resource_summary.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/resource_table.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/result_summary.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/review_export_page.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/rich_text_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/seismic_attribute_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/seismic_context_toolbar.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/seismic_control_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/seismic_prediction_page.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/seismic_slice_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/seismic_task_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/seismic_view_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/sequence_boundary_table.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/sequence_framework_page.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/sequence_helpers.py` | wired | UI-03 | UI-03 → ui_data_core + ui_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/sequence_scheme_summary.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/sequence_target_panel.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/start_guide_card.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/stratigraphy_correlation_page.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/summary_table_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/table_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/tag_widgets.py` | wired | UI-06 | UI-06 → ui_pages_data + ui_pages_data_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/task_panel_base.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/text_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/version_workbench_dialog.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/visualization_page.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/visualization_summary_panel.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/visualization_trace_panel.py` | wired | UI-10 | UI-10 → ui_seqviz + ui_seqviz_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/web_document_preview_widget.py` | ported | UI-07 | UI-07 → ui_pages_preview + ui_pages_preview_qt（未入 app 链接闭集——预览 widget 由宿主 seam 注入，当前无消费方链接） |
| `pages/well_detail_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_log_canvas_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_log_load_worker.py` | wired | UI-04 | UI-04 → ui_workers（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_log_prediction_page.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_log_track_settings.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_map_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_seismic_joint_page.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/well_table_panel.py` | wired | UI-09 | UI-09 → ui_wellseis + ui_wellseis_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/workarea_map_widget.py` | wired | UI-05 | UI-05 → ui_map + ui_map_qt + ui_map_qgis（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `pages/workflow_contract_panel.py` | wired | UI-11 | UI-11 → ui_review + ui_review_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `panel_float_controller.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `preview_settings_dialog.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `project_controller.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `project_save_worker.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `prototypes/proto_dual_volume_overlay.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `qgis_stack/__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `qgis_stack/canvas_shim.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `qgis_stack/display_canvas.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `qgis_stack/events.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `qgis_stack/layer_tree_panel.py` | wired | pre-ported | libs/ui layer_tree_panel（Pwb::Ui，链接闭集内） |
| `qgis_stack/mirror.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `qgis_stack/tree_sync.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `qgis_stack/widgets.py` | wired | UI-02 | UI-02 → ui_widgets_core + ui_widgets（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `screen_inventory.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `shortcuts.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `status_bar.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `style.py` | wired | UI-01 | UI-01 → ui_shell + ui_shell_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `theme.py` | wired | pre-ported | platform_services ThemeService（AppShell theme/density 信号直绑） |
| `thread_keeper.py` | wired | pre-ported | job_runtime DetachedJobKeeper（链接闭集内） |
| `tokens.py` | wired | pre-ported | ui_data_core/vocab + ui_seqviz/page_tokens 常量表（链接闭集内） |
| `unified_map_canvas.py` | ported | UI-15 | UI-15 → ui_canvas + ui_canvas_qgis（canvas 独立面未入 app——会话画布经 CompositeDocument 注入） |
| `view_coordination.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `visual_qa_v10.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `visual_qa_v11.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `visual_qa_v6.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `visual_qa_v7.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `visual_qa_v8.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `visual_qa_v9.py` | ported | UI-16 | UI-16 → ui_visualqa + ui_visualqa_qt（QA harness 不入产品） |
| `workflow_controller.py` | ported | UI-14 | UI-14 → ui_controllers（组合根控制器未入 app 链接闭集——ProjectController/WorkflowController 语义仍由 AppContext/MainWindow 承载） |
| `workstation/__init__.py` | retired | — | Python 包初始化胶水——无 C++ 对应物概念，再导出由移植模块覆盖 |
| `workstation/action_help.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/activity_rail.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/agent_panel.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/app_bar.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/attribute_schema.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/common.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/composite_attribute_table.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/composite_document.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/composite_editing.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/composite_panels.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/explorer.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/facies_selector.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/inspector.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/keybinding_manager.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/layer_decorations.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/linked_workspace.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/mapping_stage_bar.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/mapping_stage_panel.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/merge_features_dialog.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/mode_state.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/process_hub.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/shell.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/stage_actions.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/state_language.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/task_center.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/tool_page_dialog.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/tool_surface.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/topology_checker_panel.py` | wired | UI-13 | UI-13 → ui_composite + ui_composite_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
| `workstation/ui_context.py` | wired | UI-12 | UI-12 → ui_workstation + ui_workstation_qt（pwb-platform 链接闭集；AppShell 页注册表路径） |
