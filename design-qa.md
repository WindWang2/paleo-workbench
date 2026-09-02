# Workstation V3 Light Design QA

## Evidence

- Source visual truth: `docs/ui-redesign/reference/workstation-v3-light.png`
- Source pixels: 1487x1058, generated visual target, density not encoded.
- Implementation: `/home/kevin/.codex/visualizations/2026/09/01/01a05cda-cf03-7b71-96ad-8f06eab9345b/paleo-redesign/after-1440x900.png`
- Implementation pixels: 2880x1800 for a 1440x900 logical Qt window at DPR 2.0.
- Responsive implementation: `/home/kevin/.codex/visualizations/2026/09/01/01a05cda-cf03-7b71-96ad-8f06eab9345b/paleo-redesign/after-1180x720.png`
- Full comparison: `/home/kevin/.codex/visualizations/2026/09/01/01a05cda-cf03-7b71-96ad-8f06eab9345b/paleo-redesign/qa/full-comparison-final.png`
- Focused comparison: `/home/kevin/.codex/visualizations/2026/09/01/01a05cda-cf03-7b71-96ad-8f06eab9345b/paleo-redesign/qa/focused-top-workspace-final.png`

## Normalization

The source aspect is 1.405 and the selected desktop implementation viewport is 1.600. The source
was proportionally fitted and centered on a 1440x1024 white canvas. The implementation was
downsampled from DPR 2.0 to 1440x900 and centered on the same canvas. No image was stretched.
The comparison therefore judges hierarchy, density, panel roles, color, and component language,
not false pixel precision caused by different source aspect ratios.

## State

Both artifacts show the light, project-open, linked well/seismic/map workspace. The source is an
ideation state with a synthetic D63 picked point, interpreted faults, and a contour map. The Qt
capture uses the real `project_area` data: A12, a raw 200P amplitude section, the project well map,
real well curves, and a running D63 interpolation task. The domain-content difference is expected;
the implementation does not invent interpretation results that the current project has not loaded.

## Full-view Comparison

- Information architecture matches: global-only app bar; project/data/layer rail and object tree;
  multi-document tabs; central linked panes; contextual Inspector; bottom Agent/Task region; status.
- Central scientific content remains dominant. Explorer and Inspector have stable, distinct roles.
- White and cool-gray surfaces, hairline dividers, low radii, teal active state, and amber processing
  state match the selected direction. There are no gradients, large cards, or dashboard composition.
- The implementation is intentionally somewhat denser in its task table and less dense in the
  Inspector because it shows a Well selection rather than the source's Horizon pick.

## Focused Comparison

- Typography: 13px technical UI body, 11px status text, 600/700 panel hierarchy, zero letter
  spacing, and Chinese/Latin fallbacks remain legible at DPR 2.0. No actionable wrapping or
  truncation remains at 1440x900.
- Layout rhythm: 46px app bar, 54px rail, compact document tabs, 280px Inspector, rectilinear panes,
  and consistent 1px boundaries align with the reference language.
- Colors: white surfaces and neutral plot backgrounds are balanced by teal selection/link states;
  amber is limited to the active task count and process meaning.
- Assets/icons: visible product imagery is real engine output. Navigation and context icons are
  repository SVG assets tinted through Qt for light-surface contrast; no text glyph, handcrafted SVG,
  or placeholder illustration substitutes a source asset.
- Copy/content: labels identify real Project/Data/Layer/Document/Inspector/Task concepts and remain
  coherent outside the design brief.

## Interaction And Responsive Evidence

- Project/Data/Layer/Search/History/Workspace modes rebuild the same model/view Explorer.
- Document tabs switch linked, map, well, and compatibility workflow states; split panes maximize
  and restore through native `QSplitter` state.
- The actual Agent command `打开井 A12，把 GR 曲线放到第一道` completed through
  `HarnessExecutor`, emitted `open_well_requested('A12')`, and produced a verified GUI receipt.
- Task Center displayed a live TaskScheduler job at 61% with elapsed time and Cancel.
- At 1180x720 the Inspector collapses automatically; App Bar, tabs, contextual tools, center panes,
  Process Hub, and status remain reachable with no overlap.
- Offscreen tests do not instantiate native renderers; xcb visual QA created the real views lazily.

## Comparison History

### Iteration 1 - blocked

- P1: Explorer was normalized to the 54px rail minimum on first show, obscuring project navigation.
- P1: the embedded 3D seismic renderer produced an invalid/blank OpenGL first frame under X11 QA.
- P2: original light-stroke rail icons had insufficient contrast on the requested white rail.
- P2: map labels collided, CRS copy clipped, and the initial 1180px layout propagated oversized
  legacy minimum hints.

Evidence: `after-1440x900-v1.png` and `after-1440x900-v2.png` in the redesign evidence directory.

### Fixes

- Restored splitter state after final window geometry and capped propagated content minimum hints.
- Reused the seismic engine's real VD 2D profile in the joint document; kept 3D lazy for its own
  document and prevented invalid OpenGL painting on this first screen.
- Tinted repository icons with `QPainter` for the white Qt rail.
- Disabled crowded map labels in the compact pane, shortened CRS display with the full value in a
  tooltip, and auto-collapsed Inspector below 1280px.

### Iteration 2 - passed

Post-fix evidence is the final full and focused comparison plus the 1180x720 capture listed above.
No actionable P0/P1/P2 mismatch remains. The source's richer horizon/fault overlays are a future
document-adapter capability, not a shell-fidelity defect. A P3 follow-up is to expose a named
Interpretation layout preset once Horizon and Fault adapters are migrated.

### Iteration 3 - visual polish pass - passed

Component-language refinement over the passing Iteration-2 state; no structural change:

- Icon language unified: every workstation-surface `QStyle` standard pixmap (app-bar project /
  back / forward / sync, explorer refresh / tree folders, pane maximize) replaced with tinted
  Lucide-style repository SVGs (`arrow-left/right`, `chevrons-left/right`, `refresh-cw`,
  `folder(-open)`, `circle-check`, `pane-maximize/restore`); the rail collapse affordance is now
  a state-flipping double-chevron icon instead of the `<<` text glyph.
- Context bar grouped with hairline separators between domain / tools / display clusters; the
  well pane is labelled 测井轨道 consistently with its document tab.
- Task Center: status column is color-coded per state, the progress column is a 6px borderless
  bar whose chunk color follows task state (running = amber per the process-color rule, done =
  green, failed = red), percent shown beside the status label, and the empty row is dimmed.
- Inspector: value fields are flat selectable read-only editors (soft fill, no hard border);
  missing values render as a dimmed italic em-dash; numeric KB/TD gain metre units and counts
  gain measure words.
- Document tabs tightened to the 32px spec; QMenu radius brought into the 2/3/4px system;
  command input height harmonized with app-bar chrome buttons; status-bar engine badge dropped
  its emoji prefixes; empty document panes use a dashed hairline frame.

Evidence: `docs/ui-redesign/screenshots/after-workstation-v3-light.png` (1440x900, DPR 2.0) and
`docs/ui-redesign/screenshots/after-workstation-v3-light-1180x720.png`. Pixel checks confirmed
clean line icons, visible context separators, teal selected-tab accent, slim task bars, dimmed
missing Inspector values, and correct Inspector auto-hide at 1180x720. Three new regression
tests cover the collapse affordance, state-colored task progress, and Inspector missing-value
marking.

### Known issue: Wayland fractional scaling rasterizes canvas annotations

Under a Wayland session with fractional scaling (Plasma 125%, DPR 1.25), the *displayed* window
bitmap-upsamples thin canvas text — seismic ms tick labels, inline numbers, map axis ticks —
while regular UI text stays sharp. Not reproducible under xcb or integer DPR (2.0), and not a
drawing defect: `QWidget.grab()` (bypassing the compositor) renders the same annotations
vector-crisp on both platforms, and the engine paints them with native `QPainter.drawText`.

Isolation experiments (minimal Qt window + KDE Spectacle compositor captures + edge-gradient
statistics):

- no GL child: crisp; hidden `QOpenGLWidget`: identical bytes (no effect);
- *visible* `QOpenGLWidget`: measurable edge softening even at integer DPR 2.0, and the
  degradation **sticks after the widget is hidden**;
- the production window's four `GLViewWidget`s all report `isValid() == False` (never
  initialized), so the live trigger is the Qt 6.11 + KWin fractional-scale buffer negotiation
  itself — a known ecosystem defect (see community reports on Qt/KDE fractional-scaling blur).

Mitigation shipped: `PALEO_WAYLAND_INTEGER_SCALE=1` (opt-in, `paleo_workbench/main.py`) rounds
the device scale to an integer before `QApplication` construction, restoring crisp canvas text
at the cost of physically larger/smaller UI by the rounding step. Default unchanged (fractional
look preserved); the size trade-off stays a user decision. Long-term fix belongs upstream
(Qt Wayland fractional-scale-v1 handling of raster backing stores).

### Iteration 4 - workarea-map label halo fix - passed

User report: the home 工区地图 (GIS overview) well-name labels read as rasterized/pixelated.

Root cause (app-side, platform-independent — reproduced identically in `QWidget.grab()` on xcb
DPR 2.0 and Wayland DPR 1.25): the fallback map renderer faked label halos by stamping four
`drawText` copies at ±x/±y offsets. The union of four antialiased copies leaves lumpy, ratty
halo edges that visually read as bitmap text.

Fix (`map_render_backend.py`, both the inline painter and the deferred `_paint_label_specs`
path): the halo is now a round-join/round-cap stroke of the label's `QPainterPath` (the GIS
standard technique), followed by a `fillPath` glyph fill. Pixel-zoom comparisons before/after
show smooth uniform halos and crisp glyphs at both DPR 1.25 and 2.0. 46 map/render tests pass;
the 3 failures in `test_unified_map_visual_regression.py` are the pre-existing missing native
C++ extension environment issue (fail on the untouched baseline as well).

### Iteration 5 - 综合编修 document (variant C) - implemented

User direction after the in-workstation layout prototype (three variants on a gated prototype
tab): adopt **variant C — full-bleed map with floating panels**, and make the panels genuinely
floating (draggable, collapsible, hideable).

**Iteration 5b (same day) superseded the custom FloatingPanel with Qt-native window
management**: except for the main map, every panel is a `QDockWidget` in a
`QMainWindow`-based `CompositeDocument` — dockable to all four edges, draggable out into
floating OS windows, tabifiable against each other, closable, reopenable via a 面板 menu
(each dock's `toggleViewAction` + 恢复默认布局), with `saveState`/`restoreState` layout
persistence under `WorkstationV3/composite/windowState` (debounced on dock change signals).
Default view honours variant C's full-bleed intent: only the 图层管理 dock is open; 输入与结果
(real well/seismic/map-document tree) and 联动视图 (honest empty state until linked views land)
open from the 面板 menu. A compact icon-only overlay toolbar stays centred on top of the canvas
(pan/zoom±/全图/上一视图/下一视图 live; 选择/测距/查询 disabled with 待接入 tooltips).

Also fixed during bring-up: `UnifiedMapCanvas.shutdown()` — explicit, idempotent backend
teardown used by host worker shutdown; a project-switch shell rebuild raced the previous
canvas's render worker and segfaulted (closeEvent alone is not reliable for hidden canvases).

**Iteration 5c (same day) promoted the dock host to the top-level window**: user direction —
the map area *is* the main window and never floats; **every other panel** floats. The QMainWindow
must be top-level (Qt constraint; a nested QMainWindow is never laid out by its parent layout —
verified by minimal repro), so `PaleoWorkbenchWindow` is now the QMainWindow dock host;
`WorkstationFrame` is its central document area (app bar + document tabs + stack), and all six
panels — 资源管理器 (rail+explorer, left), 检查器 + 图层管理 (right, tabified), 任务/Agent +
联动视图 (bottom, tabified), 输入与结果 (left, on demand) — are QDockWidgets of the top window
with full window management (dock 4 edges / drag out to float / tabify / close / reopen via the
面板 menu / `saveState` persistence, debounced and guarded against saving while closed). Project
switch rebuilds detach the old docks before the new shell mounts. Composite panels follow the
document tab (shown only on 综合编修, remembering per-dock visibility). Central-area minimum-size
hints are suppressed (`Ignored` policies) so dock content hints can't blow up the window minimum.

Evidence: xcb captures `after-composite-docks.png` (default: full-bleed map + explorer/inspector-
layers/tasks docks) and `after-composite-docks-all.png` in the screenshots directory; 80
workstation/token/map tests pass.

Evidence: interactive checks confirmed tab default, dock float/undock/tabify round-trips,
panel-menu reopen, layer mutations re-rendering, layout persistence across restart, and clean
project switch (no segfault). 10 workstation tests pass; xcb captures of the default and
all-panels-open states are in the QA evidence directory.

## Verification

- 88 targeted Qt tests passed.
- Ruff checks passed for all new workstation code and touched integration files (existing broad
  exception rules explicitly ignored where unchanged).
- Native xcb capture loaded actual Map, Well Log and 2D Seismic widgets at DPR 2.0.

final result: passed
