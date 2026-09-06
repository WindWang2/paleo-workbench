# Workstation UX V6 — 00 Baseline (source audit)

Date: 2026-09-07 · Base: `main` @ 295fabc3 · Method: seven parallel read-only source audits (shell/mapping/data+perf/well/seismic+3D/agent+task/visual+a11y), every claim backed by `file:line` evidence read from current `main`.

This document records **actual current behavior** — not intent — as the V6 starting point. Companion planning detail lives outside the repo (session audit notes).

---

## 1. Workstation shell, docking, navigation (area A)

**As-is.** Three-layer shell: `PaleoWorkbenchWindow` (QMainWindow dock host, `paleo_workbench/ui/app.py:19`) → `AppShell` (page stack, command palette, status bar) → `WorkstationFrame` (`paleo_workbench/ui/workstation/shell.py:47`). The central document is `CompositeDocument` (QGIS-centric) and is never swapped (test-pinned). 13 real `QDockWidget`s exist (nav/inspector/agent/task/logs/console/composite-layer/composite-input/composite-linked/well/seismic/hub/mapping-stage), bottom chain tabified, native title bars, versioned `saveState` (v4) with legacy-settings migration.

Navigation uses a 5-hub model (`ui/workstation/navigation.py`) with pill submodules; entries resolve from explorer-tree nodes, keys 1–5 / Alt+1–3, palette, and home cards. Hub pages open in a dock that is **force-floated** (`shell.py:642-646` — `show_hub_page`).

Workspace presets: 6 live data-only presets in `ui/workstation/layout_presets.py`, driven from the app-bar combo, 面板 menu, and palette, with honest invalidation to "自定义". A second legacy registry in `dock_manager.py` still exists (4 of 8 enum values have no layouts or users).

**Findings.**

| ID | Severity | Finding | Evidence |
|----|----------|---------|----------|
| A-P0-1 | P0 | `WorkstationFrame.showEvent` defined **twice** (`shell.py:757` and `:1090`); Python keeps the second, so the first (post-show layout restore + responsive panel pass) is dead code | AST-verified |
| A-P0-2 | P0 | `_PANEL_TOGGLE_TABLE` (`shell.py:776`) covers only 7 of 13 docks; closing 资源管理器/检查器/编图阶段 via dock X leaves no menu/palette path to reopen; `toggle_inspector` has no UI caller | `shell.py:776` |
| A-P0-3 | P0 | `apply_layout_preset` calls `dock_all_panels()` (`shell.py:912`), destroying user dock geometry despite "visibility only" docstring | `shell.py:912` |
| A-P1-1 | P1 | Command palette carries only 29 chrome commands; `_register_commands` is the sole registration site — no map/workflow/agent actions | `shell.py` `_register_commands` |
| A-P1-2 | P1 | Two live mapping surfaces (CompositeDocument vs MappingPage) with **4 layer-tree implementations**; `MapActionController` shortcuts (Ctrl+Z/Delete/Esc/Ctrl+S) bypass the central shortcut registry | `ui/workstation/map_action_controller.py` |
| A-P1-3 | P1 | `WellSeismicJointPage` unreachable in production (contract strings + 1 test only) | `ui/pages/well_seismic_joint_page.py` |
| A-P2 | P2 | Dead/duplicate code: duplicate `showEvent`, `WellSeismicJointPage`, `page_placeholder.py`, `screen_inventory.py`, `fallback_preview.py`, `ribbon_panel_entries` ×9, 4 dead `WorkspacePreset` enum values, hidden `MapEditToolbar` shim | see audit |

---

## 2. Mapping workspace / QGIS / layer tree / editing (area B)

**As-is.** `MappingStage` is workflow context, not a page: one canvas/project/tree across 3 stages with instant switching (`mapping_workspace/stages.py:22`, `controller.py:100-124`). State authority is `MappingWorkspaceState` on `ProjectDocument.mapping_workspace` (`stage_state.py:194`); UI preferences live in QSettings only. Readiness = soft per-stage profile check lists with clickable targets (`readiness.py:356`). Freshness = pinned-version domain query with honest UNKNOWN (`dependencies.py:172-201,322`). `CompositeDocument` is the map authority: 120 ms-debounced `_sync_composition_now` → mirror upsert → group reconcile (`composite_document.py:1933-1967`).

Layer tree is a real `QgsLayerTreeView` via the bridge (`qgis_stack/widgets.py:32`, `layer_tree_panel.py:57`); the QGIS tree is the runtime authority and the domain desired-tree is diffed incrementally (`layer_group_controller.py:346-446`, O(N) batch placements). Stable `group_id`/`LayerRole` vocabulary; drag-drop validated by role routing with force-reconcile of invalid drops. Glyphs: `✏` edit indicator + stage-bar `✓/~/!/N↑` badges.

Editing target is stage-scoped, re-resolved on switch, never inherited (`controller.py:135-153`). RAW gate `_role_allows_editing` (`composite_document.py:1290-1319`) covers tree/toolbar/repair/active-save.

**Findings.**

| ID | Severity | Finding | Evidence |
|----|----------|---------|----------|
| B-P0-1 | P0 | RAW gate has two holes: attribute table starts edit sessions ungated (`composite_attribute_table.py:174`); `flush_edit_sessions` commits ALL sessions without role re-check (`composite_editing.py:783-797`) → RAW attributes silently committable on save/stage switch | as cited |
| B-P1-1 | P1 | Mirror publish re-serializes and truncate/reloads **every** layer per publish (`qgis_mirror.py:40-129`; `map_stack_service.cpp:1472-1486`) — the 1000-layer repaint-noise hotspot | as cited |
| B-P1-2 | P1 | `StageToolProfile.command_groups/edit_actions` fully defined with **zero consumers** — toolbar is static (`composite_document.py:908-926`); command/stage coupling does not exist today | `stage_profiles.py:24-33` |
| B-P1-3 | P1 | No per-layer staleness glyphs; `group_summary` hardcodes zeros (`layer_group_controller.py:623`); fallback panel full clear+rebuild per publish (`composite_document.py:531-549`) | as cited |
| B-P2 | P2 | In-group manual order not durable (snapshot order overwrites user drags, `layer_group_controller.py:229-250,339`); attribute table non-virtualized; duplicate badge logic; legacy MappingPage tree uses `beginResetModel` per op and is still live (`app.py:197`) | as cited |

---

## 3. Data management / lifecycle / large-list UX + materialization bypasses (areas C+I)

**As-is.** `DataCatalogService` (`catalog/service.py`) is the lifecycle authority. **Correction to older docs: `catalog.sqlite` is canonical; `catalog.json` is a checkpoint/export manifest** (`catalog/store.py:1-12`, issue #1027). Data Explorer = `DataPage` (`data_page.py:554-665`) + paged NavigationTree + `DataAssetTable`/`ProjectOverviewPanel` + threaded `DataReaderPanel` + `InspectorPanel`; lifecycle orchestration in `ui/data_lifecycle_controller.py` (trash-first removal, off-thread payload copies #931, chunked import registration).

Paged mode engages above 25k assets (`paged_asset_model.py:46`) through the service paged facade (`data_page.py:694-729`): off-thread pages with epoch/latest-only delivery, LRU 24 pages, keyset cursors, SQL sorts, honest refusal of unmappable filters; tests pin <50 ms/page and <100 ms/count at 100k. NavigationTree pages entities at 500/page (#1046). **Not covered:** integrity/auxiliary/review views, entity sets >5k, Data Overview, and everything reading `project.resources` directly.

**Materialization bypass inventory (GUI thread).**

| # | Path | Evidence | Trigger | Scale risk | Fixed? |
|---|------|----------|---------|-----------|--------|
| 1 | Data Overview click runs full materialized count pass; cached aggregates unused; plain refresh shows zeroed counts | `data_page.py:2457-2474` | clicking 工区概览 | 100k ≈ multi-second freeze | NO — **P0** |
| 2 | Integrity smart views ≥25k exit paged mode into full rebuild | `data_page.py` (smart-view path) | opening integrity view | 100k ≈ 4.5–8.9 s | NO — **P0** |
| 3 | Map attribute table rebuilds every feature record + refills whole feature combo per edit | `mapping_page.py:1790-1807`; `map_attribute_table.py:146-167` | each feature edit | 5k features 10–30× over 50 ms target | NO — **P0** |
| 4 | Stratigraphy well list + prediction/visualization source combos rebuilt per `update_state` | `stratigraphy_correlation_page.py`; combos in prediction page | every state update | 10k wells ≈ 0.5–2 s | NO — P1 |
| 5 | `_trashed_companions()` full pass per refresh even in paged mode | `data_page.py:574` | explorer refresh | 100k scan per refresh | NO — P1 |
| 6 | `_asset_legacy_map`/`_asset_name_map` full-document walks per revision | `data_page.py` | catalog revision | 100k walk per change | NO — P1 |
| 7 | Snapping dialog builds 5 widgets × all layers | snapping dialog path | dialog open | 1000 layers ×5 | NO — P1 |

**Findings (lifecycle UX).** Trash badge counts via full scans; context menus build eagerly in several views; version/run/lineage display exists on the data page but not from other surfaces.

---

## 4. Well / correlation / linked interpretation (area D)

**As-is.** Two parallel single-well hosts: `WellLogCanvasPanel` (`ui/pages/well_log_canvas_panel.py:49`, dual engine/legacy backend, 120 ms-gated depth-cursor producer, ft-axis fail-closed) and `WellLogHost` (`viz/hosts/well_log_host.py:115`, composite tab, honest PNG-only export on engine). Correlation lives in `StratigraphyCorrelationPage` (`ui/pages/stratigraphy_correlation_page.py:109`, DTW in worker, immutable interpretation versions) plus a weaker second surface `WellSectionHost` (`viz/hosts/well_section_host.py:30`). `LinkedInterpretationWorkspace` (`ui/workstation/linked_workspace.py:71`) carries the L10 domain status bar (calibration provenance/coverage/未复核 markers). `WellLocationPreview` (`viz/hosts/well_location_preview.py:221`) has duplicate-name disambiguation + SourceCRS provenance. Coordination: `SelectionContext` (display-name well keys, `selection_context.py:29-49`) → `ViewCoordinationController` (differential routing, calibrated/approximate/None MD authority, `view_coordination.py:814-920`) → `CoordinateTransformHub` (fail-closed `TimeDepthCalibration`, `coordinate_hub.py:20-101,214-218`). Curve operations are DERIVED-only with full provenance (`workflow/curve_interpretation.py:99-293`; `curve_operation_dialog.py`; data-page context menu entry `data_page.py:1640`).

**Findings.**

| ID | Severity | Finding |
|----|----------|---------|
| D-P0-1 | P0 | Engine pick signals `curve_picked`/`depth_selection_changed` have no production consumer; inspector has no `curve` kind — picks land nowhere |
| D-P1-1 | P1 | Well key = display name collides on duplicates despite existing adapters (`WellIdentityAdapter`); `JointWellId` convention not applied to all lists |
| D-P1-2 | P1 | Well Content Tree / Display Set / table mode implemented only engine-side (wellplot-desktop), not in the workbench host — engine backend has zero curve-level display control or version badge |
| D-P1-3 | P1 | Scientific curve ops undiscoverable from well views (only data-page context menu); engine multi-well correlation view-only |
| D-P2 | P2 | Silent `except: pass` overlay injection; `WellSectionHost`/`StratigraphyCorrelationPage` duplication; link refusals visible only in debug logs |

---

## 5. Seismic / 3D hosts (area E)

**As-is.** Five surfaces, three registered: `SeismicPredictionPage` (`ui/pages/seismic_prediction_page.py:80-170`) wrapping `SeismicViewPanel` (`ui/pages/seismic_view_panel.py:113-1205`, embeds geoviz `SeismicView` + P1-B interpretation bar); `GeologicalModeling3DPage` (`ui/pages/geological_modeling_3d_page.py:82-826`); composite-tab `SeismicHost` (`viz/hosts/seismic_host.py:10-87`, stale-overlay guard). `WellSeismicJointPage` is orphaned (not registered). Non-UI hosts: `WellSeismicJointHost` (`viz/joint_host.py:326+`, 3 off-thread workers, LOD ladder, honest dense-fallback warnings) and `Geo3DWorkspaceController` (`ui/pages/geo3d_workspace.py:78-905` — QC, measurements, bounds-derived clipping, camera presets, persistence). **`SeismicVolumeState` (`viz/seismic_volume_state.py:35-152`) is orphaned — test-only import; the panel probes engine privates instead** (`seismic_view_panel.py:698-712,805-821`). Picking: engine picks → `HorizonPickingController` (snap tolerance 0.25, orthogonal densification) → `HorizonInterpretationDraft` (sparse delta patch undo); save/reopen refuses geometry mismatch. 3D objects: dual-root scene tree (static geoviz captions + V5 domain objects with QC coloring and honest "(demo)/(未加载)" badges), read-only HTML inspector (`geo3d_workspace.py:275-319`), 6-mode measurement tool, QC severity ladder (`viz/geomodel/qc.py:52`).

**Findings.**

| ID | Severity | Finding |
|----|----------|---------|
| E-P0-1 | P0 | Silent pick rejection (`picking_controller.py:143-146` — no snap feedback, only aggregate count); draft state invisible on canvas; unstyled undo/redo buttons (`seismic_view_panel.py:204-206,225-229`) |
| E-P0-2 | P0 | Navigation/interpretation commands interleaved on engine toolbar and hidden via private attribute names + caption frozenset matching (`seismic_view_panel.py:84-110,540-559`) |
| E-P1-1 | P1 | `SeismicVolumeState` orphaned; inspector read-only text (no typed fields/actions); three seismic surfaces with different chromes (composite tab cannot interpret at all); engine chrome hardcodes colors vs Pwb tokens (`engine seismic_view.py:132-143,675-697`); `depth_slice_unavailable_reason` built but never displayed; modal failure dialogs vs in-page #937-6 pattern |
| E-P2 | P2 | Dead chrome (hidden attribute strip/right rail/clip card); raw "vd"/"wiggle" labels; duplicated measure-mode tables; caption-keyed tree visibility; substring interpretation matching |

---

## 6. Agent / Task Center / permission / progress (area F)

**As-is.** Harness guard chain intact in `HarnessExecutor.execute` (`harness/executor.py:132-245`): lookup→validate→permission (WRITE denied unless granted; guard refusals = "rejected")→context→governor admission→execute→output-schema→verify (fail-closed). Cancellation→"cancelled" (`:211-218`); missing backend→"unavailable" (`:219-223`). Risk vocabulary `spec.py:36-40`; 6-state `ActionStatus` (`spec.py:43-63`); DEFAULT_PERMISSIONS READ+COMPUTE (`spec.py:69`); registry refuses DESTRUCTIVE (`registry.py:47-53`). Inventory: 51 actions = 30 READ / 10 COMPUTE / 11 WRITE / 0 DESTRUCTIVE. Permission state in `ActionContext.permissions` (`context.py:88,106-107`); `from_app` grants READ+COMPUTE only (`context.py:198-262`). TaskScheduler: heavy lane IO=1 + interactive lane + aging + admission leases + claim-window cancel-race handling (`runtime/task_scheduler.py:315-342,507-509,613-621`).

Surfaces: agent panel (`ui/workstation/agent_panel.py:124-604`, own dock, regex Chinese planner with 5 intents — can never plan WRITE, risk labels + receipt echo, WRITE confirm = generic Yes/No `QMessageBox` `:303-318` with env/constructor opt-in `:21-37,145-149`, unknown actions fail closed as WRITE `:276-301`); Task Center (`ui/workstation/task_center.py`) is `QAbstractTableModel` differential refresh, delegate-painted progress/cancel, zero per-row widgets, "取消中" vs "已取消" distinct (`:273-278`), inline errors, retry/copy-id/details menu. Workflow display: `WorkflowPlanView` pure model (`workflow/dag/plan_view.py:46-203`, INTERRUPTED resumable); home strip truth = `workflow/service.py:175-244` (evidence+freshness overlay).

**Findings.**

| ID | Severity | Finding |
|----|----------|---------|
| F-P0-1 | P0 | Degraded results print "校验通过" — warnings discarded (`agent_panel.py:471,496-498` vs `executor.py:91-96`) |
| F-P1-1 | P1 | WRITE-grant UI unreachable dead UX (planner never emits WRITE); grant has no scope/params display |
| F-P1-2 | P1 | "更新受影响成果" recompute flow orphaned — `_on_recompute_requested` has no emitter (`workflow_controller.py:173-265`) |
| F-P1-3 | P1 | Task Center retry replays captured closures → re-applies agent GUI sync (`task_center.py:415-416`); commands silently dropped while busy (`agent_panel.py:253,320-325`); no run-history/resume UI despite engine support |
| F-P2 | P2 | Outputs/verification/receipts unrendered; cancelled uses queued color; queue-wait shown as runtime; `paleo_workbench/agent` swarm + WorkflowOrchestrator unwired legacy shadows |

---

## 7. Visual design / theme / density / a11y / DPI / multi-monitor (areas G+H)

**As-is.** `paleo_workbench/tokens.py` (1693 lines) is the single token source: one vocabulary, 3 curated theme palettes (`palette_for` :452, `build_qss` :472), `DENSITY_TOKENS` compact/comfortable (:159, accessors :192). `ui/theme.py` holds runtime switching + QSettings persistence; `ui/style.py` provides `style.bind`/`bind_metrics` dynamic re-render registry; `ui/components/*` (PwbBadge/PwbButton/PwbProgress/PwbTableView…) styled purely via QSS objectNames; `ui/shortcuts.py` central registry with text-input guards and conflict warnings. Contrast floors, token-hygiene ratchet, and shortcut behavior are test-pinned.

**Findings.**

| ID | Severity | Finding |
|----|----------|---------|
| G-P0-1 | P0 | Adoption gap: 234 `setStyleSheet` in 59 files — 218 in the 50 legacy page files, 0 in workstation chrome. Page sheets interpolate light-locked module constants → dark/high-contrast switching leaves legacy pages stale; `style.bind` used in only 7 files; Pwb components in only 4 files outside the library |
| G-P1-1 | P1 | 86 literal fixed sizes (28 px rows, 980 px min widths); density-blind QSS literals (32 px tabs, 22 px combo drop-downs); 106 inline `font-size:Npx` incl. 9/10/12.5 px outliers; 158 hex color matches (12-file shrink-only ratchet exists) |
| G-P1-2 | P1 | Icons: DPR-aware tinted-SVG factory is good (`workstation/common.py:47`) but 20 of 27 action SVGs are dead; data pages use emoji state icons (🔒✅⚠️) — split visual language |
| G-P1-3 | P1 | A11y: only 19 `setAccessibleName`, 0 `accessibleDescription`/`whatsThis`; item views `outline:none`; 5 focus-policy calls; no app-wide Escape contract; Ctrl+S/N/O/F defined twice (direct QShortcut + registry) |
| G-P1-4 | P1 | Multi-monitor/DPI: `clamp_geometry_to_screens` exists (`panel_float_controller.py:280`, tested) but only on the legacy float path; `QMainWindow.restoreState` unclamped; main-window geometry never persisted; suspect `setDevicePixelRatio(1.0)` in `components/states.py:30` |
| G-P2 | P2 | visual_qa covers 12 states + theme×density×size matrix (30 baselines, PIL diff, non-gating) but lacks 1366×768 and DPR>1 states |

---

## 8. Cross-cutting status/state language (area overlap; V6 §5)

Current state displays are fragmented: stage bar uses `✓/~/!/N↑`; data pages use emoji; task center uses color-coded model roles; linked workspace uses text chips; inspector has no badge system. No single "editing target + maturity + freshness + backend + permission" status vocabulary exists yet. The `✏` glyph in the layer tree is the only editing-target indicator.

## 9. What V6 must NOT break (authoritative contracts)

- SelectionContext (selection authority, geological slots, source-tag echo suppression)
- QGIS layer tree runtime authority; `CompositeDocument` as central 编图 canvas
- `DataCatalogService` lifecycle authority; RAW immutability; sqlite-canonical/index split per #1027
- `MappingWorkspaceState` mapping workflow state; readiness/freshness honesty incl. UNKNOWN
- `TaskScheduler` single heavy queue; `ResourceGovernor` admission
- Harness `ActionSpec`/`ActionRegistry`/`HarnessExecutor` guard chain; WRITE gating
- `workflow/service.py` `home_workflow_steps` as workflow status truth
- `tokens.py`/`ui/theme.py`/`ui/shortcuts.py` registries; Pwb component contracts; visual_qa baselines

## 10. Baseline conclusion

The workstation's **architecture is largely right** (authorities, registries, honest-degradation discipline, test-pinned contracts). V6's work is (1) closing correctness holes (RAW gate, fake success, dead-code P0s); (2) building the missing **context→command→inspector→status** spine (UIContext, command applicability, typed inspector, unified status language); (3) eliminating the remaining production-scale GUI materialization paths; (4) converging fragmented surfaces (seismic chrome, correlation surfaces, mapping page leftovers); (5) finishing design-system adoption outside workstation chrome; (6) extending visual QA + tests to pin all of it.
