# 00 — Baseline (V9 Adaptive Workstation UI)

Date: 2026-09-10 · Base: `origin/main` @ 39bc1147 · Branch: `feat/adaptive-workstation-ui-v9`

## Scope audited

- `paleo_workbench/ui/` — 209 files, ~77k lines (workstation/, components/, pages/, qgis_stack/, prototypes/)
- `paleo_workbench/app.py`, `paleo_workbench/main.py`, `viz/hosts/*`
- Full sizing-term sweep (`setFixedWidth … minimumSizeHint`): **454 hits** classified in `.scratch/audit-sizing.tsv`
- Dock/window/lifecycle trace: `.scratch/audit-dock-lifecycle.md`

## Current architecture (as found)

```
PaleoWorkbenchWindow (QMainWindow, app.py:19; resize 1440x900, min 1180x720)
└─ central: AppShell (ui/app_shell.py:209)
   ├─ page_stack (QStackedWidget, 5 hubs) ← also hosted inside hub_dock
   ├─ WorkstationFrame (ui/workstation/shell.py:49) — central doc area
   │   ├─ CompositeDocument (central map, min width 420)
   │   └─ 13 QDockWidgets on the window (only QDockWidget construction site)
   └─ status bar → host statusBar()
```

- 13 docks: nav / inspector / agent / task / logs / console / composite_layer / composite_input / composite_linked / well / seismic / hub / mapping_stage (shell.py:197-253).
- Persistence: native `saveState` bytes + version fence (v5) + 350ms debounce + teardown freeze + `restoreGeometry` + screen clamp. Solid.
- Separate page-level systems: `MapDockManager` icon rails, `FloatController`+`FloatingPanel` (page side-panel floating), `panel_layout/*` QSettings.
- Density/theme: `tokens.py` (1792-line canonical sheet) + `ui/style.py` bind registry + `theme.py` manager; `Ctrl+Alt+D` toggles compact/comfortable.

## Headline problems (evidence in audit reports)

| # | Severity | Problem | Root |
|---|---|---|---|
| B-1 | P0 | hub_dock min width = current hub page min (side panels `setFixedWidth(220/240)` + non-collapsible splitters) → dock unresizable depending on current page | seismic_attribute_panel.py:51, seismic_control_panel.py:22, task_panel_base.py:25, map_document_panel.py:15, visualization_summary_panel.py:28, well_location_preview.py:251 |
| B-2 | P0 | Constraint stack: inspector 280 + explorer 210 + rail 48/54 + central 420 + window min 1180x720 → infeasible at moderate widths | inspector.py:48, explorer.py:97, shell.py:160, app.py:45 |
| B-3 | P0 | Programmatic `resizeDocks` clobbers user sizes: every preset apply fires `_apply_default_pane_sizes`; every agent open snaps bottom row to 245 | shell.py:1209→1422-1448, shell.py:1391-1395 |
| B-4 | P1 | Responsive inspector hide runs inside `resizeEvent` → mid-drag reflow under cursor | shell.py:1035-1066 |
| B-5 | P0 | GL viewports inside user-floatable docks (well/seismic/hub) — documented EGL segfault class on float/dock reparent | qt_platform.py:44-83, main.py:44-70 |
| C-4 | P1 | Only 10/13 docks wired to layout save signals | shell.py:366-380 |
| C-7 | P1 | No runtime screenAdded/primaryScreenChanged handling | grep clean |
| D-2 | P1 | Page-fade QGraphicsOpacityEffect forces premature GL init of hidden GL sibling pages | app_shell.py:827-877 |
| S-1 | P1 | 62 FORBIDDEN_LARGE rigid constraints on docks/trees/panels/pages | audit-sizing.tsv |
| S-2 | P1 | Window min 1180x720 + home/relationship ~1000px minimums → narrow windows structurally impossible (1366@125% ≈ 1093 logical px) | app.py:45, home_page.py, module_relationship.py |
| S-3 | P2 | 47 files raw `setStyleSheet` (104 sites) bypass the bind registry → theme/density drift | audit-sizing-summary.md |

Already good (keep, do not redo): native docks without custom title bars; version-fenced persistence; teardown discipline; MappingStagePanel min-0/Ignored pattern; token sheet + bind registry; V7 tool_surface/availability convergence.

## Baseline test status

`tests/test_workstation_shell.py + test_layout_presets.py + test_workstation_presets.py + test_layout_persistence.py` — 45 passed (offscreen, PySide6 6.9.2, Python 3.13.9).
