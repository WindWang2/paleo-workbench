# Task Plan: Paleogeography Workbench — UI Page Implementation

> **Updated:** 2026-07-05
> **Goal:** Implement real content for all 9 AppShell pages, replacing placeholders with production widgets.

## Project Status: 3/9 pages complete (首页 + 数据 + 制备), 119 tests passing

## Current Architecture

- **AppShell** (4-zone): menu bar (36px) + header toolbar (38px) + icon rail (60px, 9 nav, gradient bg, SVG icons) + text sidebar (248px) + QStackedWidget (9 pages) + status bar (24px)
- **Design tokens** in `paleo_workbench/ui/tokens.py` — colors, fonts, dimensions, QSS_TEMPLATE, step colors/labels, status text, resource labels/units
- **Global QSS** applied in `main.py` via `app.setStyleSheet(tokens.QSS_TEMPLATE)`
- **Pages package** at `paleo_workbench/ui/pages/`

## Phases

### Phase 1: AppShell Skeleton — ✅ COMPLETE
- 4-zone layout, 9-page navigation, SVG icons, gradient rail, design tokens, global QSS
- Commits: `01b3a9e`..`c7352e1`, then icon fixes `6222a80`..`203c457`
- Tests: 57 (all passing)
- Spec: `docs/superpowers/specs/2026-07-05-appshell-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-appshell.md`

### Phase 2: 首页 Dashboard — ✅ COMPLETE
- WorkflowProgress (6-step colored badges + status), RecentActivityCard (two-column entries + scroll), DataCompletenessCard (resource readiness + unit suffixes)
- M3 polish: connecting lines, two-column activity, unit suffixes, QScrollArea
- Commits: `8f8a1f9`..`adf0acc`, polish `c507629`, fix `96c88f9`
- Tests: +23 new (80 total at completion, now 95 with DataPage)
- Spec: `docs/superpowers/specs/2026-07-05-homepage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-homepage.md`

### Phase 3: 数据页 DataPage — ✅ COMPLETE
- ResourceSummaryBar (counts + readiness), ResourceTable (QTableWidget, 5 cols, type mapping, status coloring), ActionPanel (import/convert buttons)
- Commits: `ea255c4`..`28a3a04`, fix `bd8d7be`
- Tests: +14 new (95 total)
- Spec: `docs/superpowers/specs/2026-07-05-datapage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-datapage.md`

### Phase 4: 制备页 PreparationPage — ✅ COMPLETE
- FactorTaskPanel (task list + horizon/method header + summary footer), FactorPreviewGrid (completed factor map cards with value range + R²), BoundaryPanel (probability threshold / smoothing / min area form)
- Commits: `054b8f5`..`446ee05`, label fix `a438167`
- Tests: +24 new (119 total)
- Spec: `docs/superpowers/specs/2026-07-05-preparationpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-preparationpage.md`

### Phase 5: 成图审核页 ReviewExportPage — 🔲 PENDING (next)
- QC issue table, export formats, artifact summary
- Complexity: Low (no engine dependency)
- Data source: `project.quality_reports`, `project.export_artifacts`

### Phase 6: 层序格架页 SequenceFrameworkPage — 🔲 PENDING
- Target horizon editor, sequence scheme management
- Complexity: Medium
- Data source: `project.stratigraphy`

### Phase 7: 编图页 MappingPage — 🔲 PENDING (high complexity)
- PaleoMapCanvas from geo-viz-engine, facies polygons, well overlay, legend, north arrow, scale bar
- Complexity: High (requires geo-viz-engine integration)

### Phase 8: 测井预测页 WellLogPredictionPage — 🔲 PENDING (high complexity)
- WellLogCanvas from geo-viz-engine, prediction adapter
- Complexity: High (requires geo-viz-engine integration)

### Phase 9: 地震预测页 SeismicPredictionPage — 🔲 PENDING (high complexity)
- SeismicView from geo-viz-engine, prediction adapter
- Complexity: High (requires geo-viz-engine integration)

### Phase 10: 可视化页 VisualizationPage — 🔲 PENDING (high complexity)
- Composite visualization (well/seismic/cross-well)
- Complexity: High (requires geo-viz-engine integration)

## Known Follow-up Items (Minor, non-blocking)

| # | Item | Source |
|---|------|--------|
| 1 | Legacy `screen_inventory.py` module (7 pages) diverges from updated doc (9 pages) | AppShell final review |
| 2 | `STEP_TYPES`/`RESOURCE_TYPES` duplicated across modules instead of importing from `workflow.service` | HomePage/DataPage reviews |
| 3 | WorkflowProgress: no test asserts badge styling/colors are applied | Task 2 review |
| 4 | ResourceSummaryBar: combined label instead of separate label+count (spec deviation) | DataPage final review |
| 5 | ActionPanel inlined as method instead of separate class (spec deviation) | DataPage final review |
| 6 | FactorTaskPanel.Row uses unscoped `QWidget` stylesheet selector (mitigated by child resets) | PreparationPage final review |
| 7 | BoundaryPanel `area_spin` (最小图斑面积) has no dedicated test | PreparationPage final review |
| 8 | `FactorPreviewGrid` rsquared visibility assertion on un-shown widget (Qt-version-fragile) | PreparationPage final review |

## Page Progress Matrix

| # | Page | Status | Tests | Spec | Plan |
|---|------|--------|-------|------|------|
| 1 | 首页 | ✅ Complete | 23 | ✅ | ✅ |
| 2 | 数据 | ✅ Complete | 14 | ✅ | ✅ |
| 3 | 测井预测 | 🔲 Placeholder | — | — | — |
| 4 | 地震预测 | 🔲 Placeholder | — | — | — |
| 5 | 层序格架 | 🔲 Placeholder | — | — | — |
| 6 | 可视化 | 🔲 Placeholder | — | — | — |
| 7 | 制备 | ✅ Complete | 24 | ✅ | ✅ |
| 8 | 编图 | 🔲 Placeholder | — | — | — |
| 9 | 成图审核 | 🔲 Placeholder | — | — | — |

## Test History

| Date | Tests | Status |
|------|-------|--------|
| 2026-07-05 (AppShell) | 57 | ✅ |
| 2026-07-05 (HomePage) | 80 | ✅ |
| 2026-07-05 (HomePage polish) | 81 | ✅ |
| 2026-07-05 (DataPage) | 95 | ✅ |
| 2026-07-05 (PreparationPage) | 119 | ✅ |
