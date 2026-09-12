# 01 — UI Audit (Workbench UX V11)

Base: `workbench-ux-v11` (= `origin/main` `6c08fb7d` + PR #1277 stack). All paths relative to `paleo_workbench/`.
Method: six parallel deep-audit passes (item-widget inventory, action system, context/selection, inspector/task/states, visual system, IA/workflows/tests), every finding backed by file:line evidence.

## Existing foundations confirmed strong (preserve, extend — never fork)

| Foundation | Evidence | Verdict |
|---|---|---|
| Single availability authority `evaluate_tool` | `mapping/tool_availability.py` (`ToolAvailability` with invariants, rule table, coarse→fine gate order); toolbar/canvas-menu/palette/execution all consume it; execution re-gates on every path | Keep; add structured reason metadata |
| `SelectionContext` bus + `ViewCoordinationController` | `viz/selection_context.py` (thread-safe, source-aware), `ui/view_coordination.py` (source tags, changed-field-only routing, duplicate guards, throttles, clear-on-project) | Keep; extend slots + identity discipline |
| `UIContextService` provider model | `ui/workstation/ui_context.py` — frozen snapshot, provider callables, differential emit, fail-closed | Keep; widen vocabulary |
| Dock framework | `ui/dock_framework.py` descriptors/registry, grow-only resize, GL no-float set, viewport classes, version-fenced persistence | Untouchable API (15+ shell call sites) |
| Paged/virtual models already shipped | `pages/paged_asset_model.py` (SQL paging, LRU+epoch), `pages/table_preview_widget.py` (virtual preview), `workstation/composite_attribute_table.py` (virtual + differential refresh, this stack), `workstation/task_center.py` (incremental diff model + delegate), `workstation/explorer.py` (key-diff tree) | Generalize patterns into shared foundation |
| Design system | `tokens.py` single QSS source + override-dict themes, `ui/style.py` bind registry, `workstation/common.py` tint factory, `state_language.py` vocabulary, `ui/components/` Pwb* set | Keep; adopt (usage is thin) |
| TaskCenter | 6 states incl. DEGRADED/CANCELLING, delegate-painted progress + cancel, 100-row cap | Keep; feed it more operations |

## A. Architecture

- **A1 · Two layer gates.** Fallback `LayerManagerPanel` gets evaluator verdicts via probes; the QGIS native-stack tree (`qgis_stack/layer_tree_panel.py:238,406,482`) gates on a stale `metadata["editable"]=="true"` snapshot and receives **no probes** (`composite_document.py:1265-1271`). Same layer, different menu state; native-stack users learn the RAW/frozen reason only after click. *(mine to fix)*
- **A2 · Registry/evaluator vocabulary drift** — `action_registry.py:90` `native_only` lacks `add_ring/add_part`; 5 write tools registered `risk=read` (`action_registry.py:92-97`). Pinning test `test_authoring_ux_v10.py::test_action_registry_flags_match_evaluator_tables` fails. **Owned by open PR #1267 (#1255/#1256) — NOT fixed here.**
- **A3 · RAW-gate wording triplicated** — evaluator/host chain (`composite_document.py:3017`), asset menu (`pages/asset_context_menu.py:85-87`), status chip (`ui/map_status_bar.py:286-288`): three hand-maintained strings for one rule.
- **A4 · `CommandRegistry` second stage-gate** — `ui/command_registry.py:112-143` re-implements stage whitelist/write-grant decisions that the evaluator already owns (wording shared, decision duplicated).
- **A5 · Dead explainability path** — `action_help.explain()`/`format_details()` (requirements/impact/missing) has **no UI consumer**; palette shows only the reason suffix; inspector never calls it.
- **A6 · Legacy mapping page forces gate open** — `pages/mapping_page.py:1990-1992` builds `ToolContext(edit_gate_open=True, vector_writable=True)`; documented legacy surface, real divergence. Documented, not forking behavior.

## B. Information architecture

- **B1 · Rail modes ≠ navigation** — activity rail `数据/图层/工作区` buttons filter the explorer tree (`shell.py:1537-1546`), they do not navigate; a user pressing 数据 expects the Data page.
- **B2 · Three hosts for mapping pages** — hub dock, `ToolPageDialog` (`shell.py:1107-1115`), and canvas-hides-hub (`shell.py:1101-1104`): the same logical page moves between hosts.
- **B3 · Visualization hub is self-declared temporary** but holds a permanent top-level keyboard slot (`5`).
- **B4 · Duplicate well-log/seismic surfaces** — hub page vs workstation dock, linked only via coordination sinks.
- Full route map + per-job page mapping recorded in `02-information-architecture.md`.

## C. Consistency (context)

- **C1 · Well identity key split** — bus/hub keyed by well **name**, Data map + one 3D path emit **entity id** (`project_well_map_page.py` `_rebuild_cache`, `geological_modeling_3d_page.py:2830`); name-keyed consumers silently no-op. The same bus slot means two things depending on publisher.
- **C2 · Data-page selection is invisible off-page** — `DataPage.data_context_changed` (`pages/data_page.py:285,2865`) has **zero subscribers**; cross-page jumps run on ad-hoc `WorkflowController` direct calls instead.
- **C3 · Bus `active_layer_id` is write-only** — published by explorer (`shell.py:1012-1035`) but no view consumes it; real layer selection runs on a parallel direct path. Selected layer ≠ active(edit) layer ≠ edit target are three owners (`composite_editing.py:1037`, `mapping_workspace/controller.py:71`, bus) with no unified vocabulary.
- **C4 · Index-based well-log selection** — `WellLogPredictionPage.update_state` clamps `_selected_index` only when out of range (`well_log_prediction_page.py:294-315`); a rebuilt task list silently retargets selection (DataPage re-points by id — the correct pattern).
- **C5 · Missing context slots** — no first-class: selected data asset, selected version, survey, workflow stage, active task, running operation. Stage/edit-target exist but in three different owners.
- **C6 · Attach discipline uneven** — only `attach_well_log_page` disconnects-on-rebind (`view_coordination.py:436-450`); `shell.py:1010` `attach_coordination` and `linked_workspace.py:225` connect without idempotency guards.
- **C7 · Process-global leftovers on project close** — `get_scheduler()` task statuses outlive the session (UIContext `running_task_count` can count a dead project); `command_registry` module-level, never unregistered (replace-semantics only).

## D. Performance / GUI-thread contract

- **D1 · Synchronous lineage per selection** — `data_page._update_inspector` runs `get_lineage_chain()` **twice** (up+down) on the GUI thread for every asset selection change (`data_page.py:2019-2024`).
- **D2 · 100k item-per-cell surfaces** (ranked): ① `well_table_panel.py:75` 井点表 (11 cols, full rebuild `:94-139`, source = sample-point grid → 1.1M items at 100k); ② `map_attribute_table.py:46` feature `QComboBox` (one entry per layer feature, full refill per filter/sort `:112-116,132`); ③ `map_topology_issue_panel.py:14` (no cap); ④ `correlation_link_editor.py:104` tops (wells×markers); ⑤ `catalog_health_dialog.py:74` (full rebuild on GUI thread after worker `:197-209`); ⑥ `inspector_panel.py:477` versions table (rebuild per selection); ⑦ `version_workbench_dialog.py:201` (rebuild per mutation); ⑧ `resource_table.py:19`; ⑨ `relink_dialog.py:103` (`insertRow`-in-loop); ⑩ `visualization_summary_panel.py:55`; ⑪ inspector lineage tree full materialization; ⑫ `geological_modeling_3d_page.py:291,968`; ⑬ `tag_widgets.py:346` rebuild-per-keystroke; ⑭ correlation well list (already incremental — OK pattern); ⑮ `map_layer_tree.py:45` full rebuild per document selection change.
- **D3 · `WorkstationInspector._well_has_trajectory`** scans all `entity_asset_links` on every render (`workstation/inspector.py:702-711`).
- **D4 · `IntegrityWorker.progress` signal exists but is never connected** (`pages/integrity_worker.py:81`; only `finished/failed` wired at `data_lifecycle_controller.py:1395-1396`) — bulk SHA-256 sweep is invisible.
- **D5 · `mapping_page` post-export `register_exported_view` on GUI thread** (`mapping_page.py:2426-2436`); export status overloads the map status bar **scale field** (`:2402-2446`).
- Correctly off-thread today: import, integrity compute, delivery copy, previews, exports, saves, deep audit, factor prep, DTW, 3D modeling.

## E. Visual hierarchy / theme

- **E1 · ~38 construction-time `setStyleSheet(tokens.X)` snapshots** go stale on theme switch (worst: `filter_chips_bar.py:229`, `map_edit_view.py:35`, `preview_settings_panel.py:55`, `resource_table.py:23`, `home_page.py:158`, `data_asset_table.py:138`) — the exact failure `style.bind` exists to fix; 30 files already use bind correctly.
- **E2 · Map toolbar icons not theme-aware** — 8 duplicated raw `QIcon(path)` loaders (`map_action_controller.py:23`, `native_layer_tree.py:33`, `data_toolbar.py:16`, `map_dock_manager.py:40`, `map_chrome_panel.py:17`, `map_workbench_bottom.py:17`, `map_factor_shelf.py:17`, `well_map_panel.py:26`); `map/*.svg` baked `#505050/#415a75` strokes are near-invisible on dark toolbars. `workstation_icon()` tint factory exists. *(5 missing geometry-tool SVG assets are #1256/#1267's — not added here.)*
- **E3 · Duplicated QSS fragments** — card-title label ×10 (unused `PwbSectionHeader` global rule exists), table chrome re-stated ×4, PanelCard frame ×3, mono font literals ×3.
- **E4 · Keyboard focus invisible in views** — `QTableView/TreeView/ListView` `outline:none` with no `::item:focus` rule.
- **E5 · Density incomplete** — tabs/menu/combo/tree-item paddings not parameterized by `DENSITY_TOKENS`; compact mode leaves them comfortable.
- **E6 · Edit-state strokes hard-coded** — `composite_editing.py:222-261` `#d62728/#1c7ed6/#868e96/#2f9e44` ignore theme (should be `CANVAS_*` family); stray `#8a94a6` `composite_document.py:2729`; no `ON_BADGE` token for the last `#ffffff` literals.
- **E7 · `ERROR_RED` misuse** — "Inline 剖面" navigational badge (`seismic_view_panel.py:450-458`).
- Only 57 hex literals outside tokens/prototypes overall — system is fundamentally healthy.

## F. Accessibility / keyboard

- **F1 · Zero `setTabOrder` in the package** — tab order is construction order on complex pages.
- **F2 · Digit-shortcut guard gap** — bare `1`-`5` hub shortcuts guard text inputs but not `QSpinBox`/editable `QComboBox`/item-view editors (`ui/shortcuts.py:74-81`).
- **F3 · No F5 refresh / F1 help**; `whatsThis` unused anywhere; `Delete`-in-view shortcuts unregistered (invisible to conflict checker).
- **F4 · Icon-only buttons** largely have tooltips; accessibleName coverage uneven.

## G. Feedback (task/error/empty)

- **G1 · 7 progress idioms** coexist (delegate bar, in-panel busy, modal indeterminate ×5, status-text-as-progress, wait cursor, unused `PwbProgress`, button-as-cancel).
- **G2 · Shared state components unused** — `PwbErrorState/PwbLoadingState/PwbInlineStatus/PwbProgress/PwbToast` have **zero consumers**; only `PwbEmptyState` escaped (×2). 142 modal `QMessageBox` sites; toasts never used.
- **G3 · Page task panels divergent** — `TaskPanelBase` shows raw English status strings; `FactorTaskPanel` is a separate implementation with its own tone map (not `state_language.tone_to_badge`).
- **G4 · Result jumps nearly absent** — the one good pattern (lineage node double-click → asset locate) is isolated.
- **G5 · Duplicated empty texts** — `未选择预测任务` ×11 in 5 files; `请选择数据项` ×3 variants; 未绑定工程 ×3 wordings; export-done ×2 wordings ×5 sites.
- **G6 · Badge vocabulary under-adopted** — `state_language` + `layer_decorations` exist; missing from: mapping page native tree, explorer, inspector (plain text only), task panels, asset table (third glyph dialect).

## H. Workflow (stages)

- Stage model is well-guarded (flush-before-switch, once-only dock recommendations, no recompute on switch, explicit edit-target reset with status message).
- **H1** Stage actions that navigate away (`_HUB_ROUTES`) break canvas context; **H2** first-entry dock recommendation overrides user visibility once; both documented in `02-information-architecture.md` with mitigations (return-to-canvas affordance; recommendation respects explicitly-user-toggled docks).

## I. Dead / inconsistent UI

- `DataPage.data_context_changed` dead signal (C2). · WorkstationInspector 历史 tab is decorative filler ("已选择井 X"). · `MapLayerPropertiesDialog` fully English inside a Chinese UI. · TaskPanelBase leaks English statuses. · `EmptyStateLabel` objectName dialect ×12 vs `PwbStateSurface`.

## J. Duplicate components (to consolidate)

Resource identity rows ×4 implementations · missing-value rendering ×2 idioms · empty-selection text ×3 · card-title label ×10 · table chrome QSS ×4 · search box vocabularies ×3 · button vocabularies ×2 (PwbButton vs raw+objectName) · task panels ×2 · RAW-gate strings ×3 · status→tone maps ×3 (`TASK_STATUS_COLORS`, task_center tables, factor `_STATUS_TONES`).

## K. Lifecycle

- **K1** `style.on_theme_change()` strong-ref subscription trap (`ui/style.py:145`) — latent. · **K2** `shell.py:1010` non-idempotent connect. · **K3** app-shell→UIContext refresh via bare lambdas (safety rests on swallowed `RuntimeError`). · **K4** scheduler + command_registry outlive sessions (C7). · Production `QTimer.singleShot` uses are all context-object form (good); `OwnedWorkerJob` is the model citizen.

## Prioritized fix list for this goal

| ID | Fix | Area |
|---|---|---|
| P0-1 | UIContext v2: well identity adapter, asset/version/survey/stage/task slots, selected/active/edit layer vocabulary, kill dead signal, idempotent attach, session detach | C1-C7 |
| P0-2 | Probes → QGIS native stack tree; stage-panel disabled+reason; shared gate wording; explain() wired to palette/inspector | A1,A3,A5 |
| P0-3 | Model/View foundation module + migration of ranked surfaces ①-⑮ | D2 |
| P0-4 | Async query contract (epoch/latest-only/stale-reject) + lineage-off-GUI + integrity progress wiring | D1,D3,D4 |
| P1-1 | State components adoption + badge vocabulary + empty-text unification | E,G |
| P1-2 | style.bind migration (38 sites), map-icon tint routing, ::item:focus, density parameterization | E1-E5 |
| P1-3 | Inspector 2.0: Version/Run sections, Well/MapLayer enrichment, badges | §11 |
| P1-4 | Keyboard/a11y: tab order, digit guard, F5/F1, accessibleNames | F |
| P2 | Visual QA v11 matrix; structural perf tests; docs | §20,§21 |

Registry vocab drift (A2) and 5 missing tool SVGs remain owned by open PR #1267; the failing pinning test is pre-existing on this base and excluded from this goal's green-board (documented in `13-verification.md`).
