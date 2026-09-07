# Findings — Workstation UI/UX V7

Working memory. Durable/polished versions live in `docs/development/workstation-ux-v7/`.
All paths relative to worktree root. Audit date 2026-09-08, base main @ db21f6cf.

## A. Command surface (from agent audit)

- `CommandRegistry` (`ui/command_registry.py`): 48 commands (11 nav, 6 presets, 5 view,
  13 panel, 12 stage, 1 workflow). V6 predicate machinery COMPLETE but DORMANT:
  0 registrations use `requires_write` / `applicability` / `hidden_when_unavailable`;
  only 12 stage commands use `stages` whitelist; 1 uses `context_tags`.
- Registry consumed ONLY by CommandPalette. Toolbars, menus, context menus each
  hand-build QActions — palette is not the single source.
- `MapActionController` (`ui/map_action_controller.py`): 30 actions (12 exclusive
  tools + 18 commands). `MapActionState` has 8 fields: has_active_vector_layer,
  vector_layer_writable, editing, selected_count, compatible_polygon_count, can_undo,
  can_redo, can_previous/next_extent. NO stage / role / write-grant / capability inputs.
  NO disabled reasons on QActions (reasons only in palette + status messages at dispatch).
- TWO MapActionController instances: CompositeDocument (workstation, 26 actions shown)
  + MappingPage (hub page, 30 actions) — second authority with its own
  MapToolController/SnappingService/TopologyService dispatch.
- `CompositeDocument._sync_action_state` re-enables `split` + force-syncs checks
  post-hoc (`composite_document.py:1118-1141`) — enable logic in 2 places.
- StageToolProfile (`mapping_workspace/stage_profiles.py:24-44`): governs toolbar
  VISIBILITY only, via `apply_stage_tool_profile` (composite_document.py:902-921).
  THREE parallel stage vocabularies: `edit_actions` (profile) vs
  `MappingStagePanel._PHASE1/2/3_ACTIONS` (buttons+palette) vs
  `StageActionDispatcher` handler map (execution). Profile's `command_groups` has ZERO
  consumers; half of `context_actions` ids exist nowhere (toggle_prediction_confidence,
  factor_qc, compare_factor_versions, map_components).
- Shortcuts: 14 in central registry (`ui/shortcuts.py`); 11 OUTSIDE (QAction shortcuts
  Ctrl+S/Delete/Ctrl+Z/Ctrl+Shift+Z/Esc × 2 controller instances + data_page Delete).
  `conflicts()` only sees registry. register_meta dead (0 callers). Double text-input
  guard with DIFFERENT type lists (shortcuts.py:59-67 vs app_shell.py:723-738).
- No QMenuBar anywhere (tokens.py:717-728 styles a nonexistent bar — dead rule).
- Dead toolbar items: `refresh`, `clear_selection`, `select_all`, `invert_selection`
  created but unreachable in composite surface; `MapEditToolbar` hidden shim
  (mapping_page.py:183-185) fully wired but setVisible(False) forever.
- WorkflowController owns no commands (only `workflow:recompute` palette bridge).

## B. Pages / docks / layout (from agent audit)

- 131 page files: 120 ACTIVE, 1 LEGACY (well_seismic_joint_page — string refs only),
  1 DEAD (fallback_preview), 7 TEST-ONLY (data_detail_panel, preview_strategy,
  interchange_models, map_document_panel, resource_table, seismic_task_panel,
  workarea_map_widget), 1 dead prototype, 1 facade.
- 13 host QDockWidgets (WorkstationFrame._add_dock, shell.py:289-309): nav/inspector/
  agent/task/logs/console/composite_layer/composite_input/composite_linked/well/seismic/
  hub/mapping_stage. All recoverable via 面板 menu + palette (V6 fixed).
- Hub force-float: `show_hub_page` (shell.py:705-709) — entire legacy page stack lives in
  hub_dock, force-floated on every navigation; all presets set hub=False; excluded from
  preset customization tracking. THE two-architectures seam.
- Page-level float system (FloatController + FloatingPanel + MapDockManager rails):
  second dock architecture, own persistence (`panel_layout/*` keys), own chrome.
- Two preset systems: live `WorkstationLayoutPreset` (6, layout_presets.py) vs legacy
  `DockManager.WorkspacePreset` (8 enum, 4 dead members, layouts test-only;
  dock_manager survives as float-title vocabulary registry only).
  `WorkstationLayoutPreset.float_visible` declared, never set/read — dead.
- Persistence: QSettings `layout/window_state` (v4 fence), debounced 350ms, clamped to
  screens (panel_float_controller.py:280-302), inspector responsive-hide <1280px w/
  hysteresis. First-run default pane sizes via resizeDocks post-show.
- NO 1366×768 handling anywhere (zero grep hits). Window default 1440×900.
- Three descriptions of "pages": screen_inventory.py (11 legacy ids, TEST-ONLY consumer,
  stale museum piece) vs navigation.py (5 hubs) vs explorer hardcoded list
  (explorer.py:391-413 duplicates SUBMODULES).
- Two inspector impls: WorkstationInspector (shell) vs InspectorPanel (data page).
  Five tree impls: QgisLayerTreePanel (native QgsLayerTreeView), LayerManagerPanel
  (fallback QTreeWidget), NativeLayerTree (legacy mapping page), MapLayerTree (legacy),
  LayerTreeSnapshot (domain description).

## C. Design debt (from agent audit)

- Tokens single source: `paleo_workbench/tokens.py` (1692 ln) + theme.py + style.py
  (dynamic bind). Components (9 files) are objectName-driven, clean.
- RATCHET CURRENTLY RED: agent_panel.py 3 > budget 2 (#53616c :248, #15803d :254,
  #b45309 :260); curve_operation_dialog.py:155 "color: gray" > 0.
- 234 setStyleSheet calls / 55 prod files. 19 pure-literal; worst seismic_slice_preview
  (4), app_shell (3). REAL debt: 44 files interpolate light-token constants at
  construction WITHOUT style.bind → stale light chrome in dark/HC. Worst:
  geological_modeling_3d_page.py (47 calls, 20 font literals), inspector_panel (8),
  lineage_explorer_dialog (10), data_detail_panel (9), onboarding_report_card (8),
  completeness_card (8), factor_task_panel (8), tag_widgets (7), version_workbench (7),
  boundary_panel (7), factor_preview_grid (7).
- 104 literal font-size:Npx outside tokens (101 pages). 42 literal-int fixed sizes
  (worst: fixed-width 220/240 side panels that fight reflow).
- 34 hex/named color lines / 13 files (12 budgeted; 2 over). viz/hosts clean.
- Emoji: 43 lines / 15 files + 99 symbol-glyph lines (⇱ duplicated 8 pages, ⚠, ▾, ▣...).
  Repo has 50+ SVG icons; bypassed. state_language.py:49 has 🔒 in official glyph table.
- Status vocabulary: 3 canonical layers (tokens.STATUS_TEXT/TASK_STATUS/QC_RESULT,
  state_language.StateToken, PwbBadge tones) + 9+ local dialects (filter_index:47,
  interchange_models:77,132, integrity_worker:22, navigation_tree:63,
  workflow_contract_panel:22, module_relationship:34, mapping_stage_panel:34,
  data_view_models:36-86, status_bar:26). Synonym drift: stale=需更新/已过期/内容可疑;
  running=处理中/运行中/进行中; pending=待开始/等待/排队中/待生成; failed=异常/失败/错误.
  THREE tone grammars: {ok,info,warn,error,muted,locked} vs
  {neutral,primary,success,warning,error,process} vs {normal,running,queued,done,failed}.
- Badge implementations ×8: PwbBadge (canonical, ~0 adoption), TagBadge, FilterChip,
  factor_task_panel QLabel, status_bar engine badge, geo3d chip, HTML spans ×2,
  QSS-objectName pills (correct pattern).
- Empty-state dialects ×4 (PwbEmptyState adopted in only 6 files total; EmptyStateLabel
  ad hoc in 12 files; bare QLabel 暂无 ×8; engine placeholders). Loading ×3
  (PwbLoadingState; bare setRange(0,0) ×9 sites; PagePlaceholder). Error: backend_status
  string protocol per-page bespoke rendering; PwbErrorState ~0 adoption.
- objectName: 302 set, 118 backed by tokens.py #rules; 12 tokens.py #ids with no setter
  (dead rules candidates). QMenuBar rule dead.

## D. Context/state services (from agent audit)

- Named V7 interfaces DO NOT exist: QgisCapabilitySnapshot, LayerCapabilitySnapshot,
  ToolContext, ToolAvailability, LayerPresentationState — must be created as typing
  seams + adapters (goal §16). Nearest existing: UIContextSnapshot (15 fields),
  qgis_bridge_available() probe, uses_native_stack, degraded strings, LayerRole props,
  layer_domain_status(), FreshnessStatus, group_summary().
- UIContextService (`ui/workstation/ui_context.py`): real, production-wired, minimal.
  Providers wired in app_shell._wire_ui_context (:527-598). Consumers: palette +
  status bar only. Not in snapshot: dirty state, layer selection, per-layer freshness,
  preset, task detail, degraded-vs-unavailable distinction (bridge = one bool).
- MappingStage enum (stages.py:22) FACIES_CALIBRATION/CONSTRAINT_FACTOR/
  INTEGRATED_COMPILATION; controller.set_stage flushes edits, reassigns editing target,
  recommends docks first-entry. Stage drives: toolbar visibility, palette whitelist,
  stage bar badges, evidence group locking, context actions, persistence.
- LayerRole (30 roles) + ROLE_EDITABLE/ROLE_RAW_PROTECTED + ArtifactMaturity
  (DRAFT/REVIEWED/FROZEN/PUBLISHED) in mapping_workspace. RAW gate single choke point
  `_role_allows_editing` (composite_document.py:1400-1429). QgisLayerTreePanel does NOT
  consume roles (string metadata editable/reference flags).
- Inspector: WorkstationInspector stringly-typed show_payload kinds (well/horizon/
  interpretation/layer/project/seismic/resource/map_component/curve/generic). Layer
  domain rows via host-injected seam set_context_seam. Gaps: no feature-level inspector
  (IdentifyResultsPanel separate), no factor-raster inspector, no MapProduct inspector.
- Layer tree decorations today: ONLY edit pencil (set_edit_indicator via bridge;
  map_stack_service.cpp:3155-3184). NO dirty/stale/error/reviewed/frozen/published/
  missing/degraded decorations in any tree. group_summary() computes per-group
  {layers, stale, errors} (layer_group_controller.py:625-643) but only tests consume it.
- Task UX: TaskScheduler real cooperative cancel (Event + check_cancelled +
  sleep_interruptible; task_scheduler.py:47-86,353-379). TaskCenter QAbstractTableModel
  400ms poll differential; "取消中" shown when cancel_requested; retry resubmits spec.
  Missing: run-history/outputs UI, resume.
- QGIS dialogs: Layer Properties native via exec_layer_properties (fallback =
  MapLayerPropertiesDialog custom); Renderer/Symbol Selector wrapped
  (map_symbology_bridge.py:79-215) gated by qgis_symbology_available() with disabled
  reason; Style Manager wrapped but NO production entry point (tests only);
  Snapping = custom dialog projected onto native snappingUtils; Attribute Table =
  custom CompositeAttributeTableDialog. No CRS entry anywhere. No three-state
  native/degraded/unavailable model in UI context.

## E. Visual QA (from agent audit)

- Harness: capture_workstation_screens.py (12 V5 states + 6 V6 states, subprocess,
  QSettings sandbox, size guard); capture_ui_matrix.py (--core/--full/--v6, manifest);
  diff_ui_matrix.py (PIL, >16 gray delta, WARN 1%/ALERT 5%, non-gating);
  visual_qa_v6.py (6 V6 states + semantic checks → _checks/*.json sidecars);
  tests/test_visual_qa_v6.py (semantic checks HARD-gated in pytest; baselines pinned).
- Matrix: 3 themes × 2 densities × sizes (1440×900, 1180×720, 1920×1080) but theme
  sparse — only 01-default covers dark+HC; all V6 states light-only.
- MISSING sizes: 1366×768, 2560×1440. No DPR>1. No dynamic-field masking.
  `--update-baseline` flag dead (never read).
- MISSING states: phase1 RAW-blocked, phase1 active editing session, phase2 constraint
  line drawing, phase2 factor raster, layer tree stale/error glyphs, task cancelling,
  dedicated backend degraded, QGIS native vs fallback contrast, inspector factor,
  export/layout, other 5 presets.
- Baselines: baseline-v5 (12 @1600×900 frozen), baseline-v5-matrix (30),
  baseline-v6-matrix (36 + sidecars). v5 frozen by test.

## F. V6 known-limitations = V7 backlog (10-known-limitations.md, 16 items)

Hub force-float; dead code not deleted; group_summary no tree consumer; mirror publish
re-serializes all layers (1000-layer hotspot); fallback tree full rebuild per publish;
manual order not durable; integrity views ≥25k materialize; agent planner never WRITE
plans; Task Center retry replays closures; write_granted bool-only; seismic/3D family
untouched (silent pick rejection, 3 chromes, orphaned state); Well Content Tree not in
host; 218 legacy styles/86 fixed/106 font literals no ratchet; emoji icons; Windows/
offscreen only; no DPR>1; no 1366×768 visual state; QSettings registry race.

## G. Environment facts

- Worktree .worktrees/workstation-ux-v7, branch feat/workstation-ux-v7 @ db21f6cf.
- venv .venv cp312 (uv); editable geoviz installs OK; native pyds copied from main
  (grid_render_core, layer_model_core, seismic_3d_core, well_log_core — cp312 ABI).
- qgis_render_bridge NOT built anywhere (main included); tests skip via importorskip;
  visual QA runs bridge-less (fallback canvas = honest verified path).
- QGIS 4.2.0 installed at C:/Program Files/QGIS 4.2.0 (apps/qgis, Python312) —
  potential future bridge build target; NOT required for V7 UI work.
- Offscreen Qt works: QT_QPA_PLATFORM=offscreen, pytest-qt pyside6.
- Prior session pitfalls: root .venv editables point at MAIN checkout — never use for
  worktree tests. Windows registry QSettings race — no concurrent workstation
  construction during baseline generation.
