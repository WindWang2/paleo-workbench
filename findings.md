# Findings — Paleo UI Workbench (feat/paleo-ui-workbench)

## Environment
- 主仓 main @ e7214566；worktree C:\Users\wangj.KEVIN\projects\paleo-workbench-paleo-ui
  branch feat/paleo-ui-workbench；geo-viz-engine 子模块已用本地 reference 初始化
- 主仓 .venv (cp312, PySide6 6.11.2) 可复用：editable MetaPathFinder 位于
  sys.meta_path 尾部，pytest pythonpath=["."]（rootdir=worktree）先命中 → worktree
  代码生效（实测 paleo_workbench.__file__ 指向 worktree）
- UI 测试配方：QT_QPA_PLATFORM=offscreen + `-m "not slow and not opengl"`；
  冒烟 tests/test_facies_taxonomy.py 15 passed

## Architecture (Explore 双报告要点, 2026-09-14)

### Shell / 工作台
- WorkstationFrame (ui/workstation/shell.py L96)：dock_host QMainWindow 持有全部
  QDockWidget；_add_dock L344 走 workstation_dock_registry；_wire_mapping_stage
  L534 是期次/horizon 联动主接线点；_on_mapping_horizon L871 = set_target_from_boundary
  + stage_controller.refresh_evaluation()（无换层，仅元数据）
- 新 dock 需登记：dock_framework.py WORKSTATION_DOCKS + shell._PANEL_TOGGLE_TABLE +
  _shell_docks()；浮动覆盖层 parenting 范式 = PwbToast.show_on(parent)（reparent 到
  window，QTimer child 自动消亡）
- UIContextService (ui_context.py L116)：UIContextSnapshot ~40 字段 + provider 注册
  —— HUD 事实流应经此投影（如 MapStatusBar.apply_context 模式）

### 画布双栈
- QgisCanvasShim (qgis_stack/canvas_shim.py L348)：set_extent L634(record_history,
  coalesce_history) 直接设无动画；zoom_by L682；map_position_changed(tuple) 光标坐标
  信号；native_identified(dict) 识别；export_png L1460；set_layer_snapshot L1399
  增量镜像（changed_hints）；shutdown_live_shims L41
- UnifiedMapCanvas (unified_map_canvas.py L360) fallback：同鸭子面 + map_clicked(tuple)
  L376（裸左键）+ render_export_image L855；无 identify 工具
- Python 权威拾取：composite_editing.identify_all(point, base_layers) L2802（editable
  走 FeatureSpatialIndex L287，base 走 _geometry_hit）→ 吸色管双栈可用

### 期次/层序现状（GAP）
- horizon = 纯字符串 stratigraphy.target_horizon；workflow/stratigraphy.py:
  set_target_from_boundary L86 / active_target_horizon L105 / horizons_from_data L121
  / horizon_choices L163 / ensure_horizon_catalog L145
- PaleoMapDocument.linked_target_horizon（每 horizon 一图档）；user_vector_layers
  单层集不分 horizon；代码中无 寒武系/奥陶系 等年代名（grep 空）
- MappingStageBar.horizon_combo (mapping_stage_bar.py L148) + _commit_horizon L247
  （_suppress_horizon echo 防护范式）
- 层组：layer_groups.py GroupTemplate/system templates；LayerGroupController.
  reconcile L347 tree_transaction + keyed-LCS diff_trees；apply_stage_visibility L497
  只推变更组 —— 期次可见性切换可复用同思路

### 相带
- FaciesTaxonomy (mapping/facies_taxonomy.py L52)：builtin=resources/facies_taxonomy.json
  {"_meta","tree":{相:{亚相:{微相:{}}}}} 8/24/66；project override ProjectDocument.
  facies_taxonomy；from_geojson_features
- 特征属性 facies/sub_facies/micro_facies/level；分配=模态 FaciesSelectionDialog
  （composite_document._assign_facies_dialog L4210）；无当前相带持续状态（GAP）
- 颜色：stage_actions._categorized_facies_style（分类渲染器）；花纹：
  mapping/facies_patterns.py fill_patterns；图例 overlay=_top_facies_legend L4167
- 捕获后自动赋值挂点：edit_controller.feature_captured → _on_feature_captured

### QC
- TopologyCheckerPanel (topology_checker_panel.py L37)：issue dict {id,rule,layer_id,
  feature_id,other_feature_id,message,fixable,bbox,methods}；信号 zoom_requested(list)/
  highlight_requested(str)/fix_requested(str,int)/fix_all/ignore/restore；_RULE_LABELS
  {overlap,gap,is_valid,workspace_remainder,dangle}
- cartographic_qa.py：15 规则族纯检测（collect_cartographic_qa L1215）；issue=
  workflow/qc.make_issue {rule,severity,message,feature_id,feature_kind,ref,geometry,
  centroid,extra}；无 UI 无修复（GAP=QC Hub 首个消费者）
- 修复件：topology.repair_invalid_geometry L311；geometry_operations.repair L442；
  composite_editing.repair_layer_geometries L2364

### 跨视图联动
- ViewCoordinationController (view_coordination.py L42)：SelectionContext(viz/
  selection_context.py L74) changed-field 路由 + source-tag skip + emit=False 回切
  + 节流(30-120ms) —— echo 防护范式库
- 已有 sinks：set_spatial_cursor_sink L729 (x,y→图标记)、set_link_cursor_sink L750
  ((well_name,md)→engine crosshair)；连井 CrossWellHost (viz/hosts/cross_well_host.py)
  未接 SelectionContext（GAP=本任务接线）
- 单因素运行时：FactorGridResult(workflow/factor_grid_result.py L240) grid_z/grid_x/
  grid_y/variance_grid/input_points(=控制井样点)；factor_grid_artifacts.py
  peek_live_factor_grid L341；FACTOR_DEFAULTS(workflow/factor_units.py L27, 砂地比%)

### 撤销/快捷键/测试
- 撤销：VectorEditSession undo_stack/redo_stack + begin/end_edit_command
  (vector_layer.py L474+)；native=gesture 宏；无 QUndoStack
- shortcuts.py：register_shortcut L43 (ApplicationShortcut, 同 id 替换, 文本输入守卫)；
  conflicts() L126；已占用键见 task_plan
- 测试范式：AppShell 全壳 / WorkstationFrame 直构+ _force_fallback monkeypatch /
  FakeCheckerStack 纯鸭子；conftest isolate_qsettings + cleanup_qt_deferred_deletes
  (reap 匿名 parentless) autouse
- 视觉：visual_qa_v11.py v11_shot_table L857 name→builder；像素 diff 非 gate (V5 D8)

## Open questions to verify by test
- Qt 快捷键跨上下文优先级：ApplicationShortcut("1" hub) vs WidgetWithChildrenShortcut
  ("1" 画布) 同键并存时是否只触发画布域（Ticket 2 首个测试实证，记入 00-decisions D6）
