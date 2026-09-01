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

## Verification

- 88 targeted Qt tests passed.
- Ruff checks passed for all new workstation code and touched integration files (existing broad
  exception rules explicitly ignored where unchanged).
- Native xcb capture loaded actual Map, Well Log and 2D Seismic widgets at DPR 2.0.

final result: passed
