# Task Plan: Paleogeography Workbench — UI Page Implementation

> **Updated:** 2026-07-06
> **Goal:** Implement real content for all 9 AppShell pages, then upgrade DataPage into a project-wide data/result/file management center.

## Project Status: 9/9 pages complete (all AppShell pages implemented), Data Management Center design pending spec review, 212 tests passing with clean root pytest output

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

### Phase 5: 成图审核页 ReviewExportPage — ✅ COMPLETE
- ActionHeader (title + 3 action buttons + rules chips), QCIssueTable (one row per QC rule, derived 通过/警告/待处理 result + colored cell), ResultSummary (pass/warning/error counts + advisory + export artifacts list); shared derive_rule_result helper (error precedence)
- Commits: `a70a19f`..`3ad80ce`, refactor `1bdd23d`
- Tests: +30 new (149 total)
- Spec: `docs/superpowers/specs/2026-07-05-reviewexportpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-reviewexportpage.md`

### Phase 6: 层序格架页 SequenceFrameworkPage — ✅ COMPLETE
- SequenceTargetPanel (target horizon + interpretation version + scheme selector + applicable well/seismic counts), SequenceBoundaryTable (sequence boundary rows + empty state), SequenceSchemeSummary (scheme + boundary count + systems tract labels + save action)
- Tests: +12 new (161 total)
- Spec: `docs/superpowers/specs/2026-07-05-sequenceframeworkpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-sequenceframeworkpage.md`

### Phase 7: 编图页 MappingPage — ✅ COMPLETE
- MapDocumentPanel (active map document + horizon + polygon/well counts + list), MapCanvasPanel (embedded geo-viz-engine `PaleoMapCanvas` loading facies polygons and well overlays), MapChromePanel (title/elements summary + draft/review actions)
- Tests: +11 new (172 total)
- Spec: `docs/superpowers/specs/2026-07-05-mappingpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-mappingpage.md`

### Phase 8: 测井预测页 WellLogPredictionPage — ✅ COMPLETE
- PredictionTaskPanel (active prediction task + status/probability/review counts + list), WellLogCanvasPanel (embedded geo-viz-engine `WellLogCanvas` fed by deterministic `PredictionTask` → `WellLogData` conversion), PredictionEvidencePanel (evidence weights + mock/replaceable status + actions)
- Tests: +12 new (184 total)
- Spec: `docs/superpowers/specs/2026-07-05-welllogpredictionpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-welllogpredictionpage.md`

### Phase 9: 地震预测页 SeismicPredictionPage — ✅ COMPLETE
- SeismicTaskPanel (active prediction task + status/probability + list), SeismicViewPanel (embedded geo-viz-engine `SeismicView` fed by deterministic `PredictionTask` → seismic volume conversion), SeismicControlPanel (volume shape + mode + mock/replaceable status + actions)
- Tests: +12 new (196 total)
- Spec: `docs/superpowers/specs/2026-07-05-seismicpredictionpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-seismicpredictionpage.md`

### Phase 10: 可视化页 VisualizationPage — ✅ COMPLETE
- VisualizationSummaryPanel (resource/prediction/map counts), CompositeVisualizationPanel (WellLogCanvas + SeismicView + CrossWellWidget tabs), VisualizationTracePanel (active task/map + actions)
- Tests: +9 new (205 total)
- Spec: `docs/superpowers/specs/2026-07-05-visualizationpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-visualizationpage.md`

### Phase 11: 数据管理中心 Data Management Center — 📝 DESIGN REVIEW
- Upgrade DataPage from resource summary/table/actions into a project-wide data, result, and file management center with import, catalog filters, dedupe, details, and lightweight previews.
- Spec: `docs/superpowers/specs/2026-07-06-datamanagementpage-design.md`
- Plan: pending after user spec review
- Implementation: pending

## Known Follow-up Items (Minor, non-blocking)

No currently tracked non-blocking UI follow-ups remain after the 2026-07-06 hardening pass.

## Page Progress Matrix

| # | Page | Status | Tests | Spec | Plan |
|---|------|--------|-------|------|------|
| 1 | 首页 | ✅ Complete | 23 | ✅ | ✅ |
| 2 | 数据 | ✅ Complete | 14 | ✅ | ✅ |
| 3 | 测井预测 | ✅ Complete | 12 | ✅ | ✅ |
| 4 | 地震预测 | ✅ Complete | 12 | ✅ | ✅ |
| 5 | 层序格架 | ✅ Complete | 12 | ✅ | ✅ |
| 6 | 可视化 | ✅ Complete | 9 | ✅ | ✅ |
| 7 | 制备 | ✅ Complete | 24 | ✅ | ✅ |
| 8 | 编图 | ✅ Complete | 11 | ✅ | ✅ |
| 9 | 成图审核 | ✅ Complete | 30 | ✅ | ✅ |
| 11 | 数据管理中心升级 | 📝 Design Review | — | ✅ | ⏳ |

## Test History

| Date | Tests | Status |
|------|-------|--------|
| 2026-07-05 (AppShell) | 57 | ✅ |
| 2026-07-05 (HomePage) | 80 | ✅ |
| 2026-07-05 (HomePage polish) | 81 | ✅ |
| 2026-07-05 (DataPage) | 95 | ✅ |
| 2026-07-05 (PreparationPage) | 119 | ✅ |
| 2026-07-05 (ReviewExportPage) | 149 | ✅ |
| 2026-07-05 (SequenceFrameworkPage) | 161 | ✅ |
| 2026-07-05 (MappingPage) | 172 | ✅ |
| 2026-07-05 (WellLogPredictionPage) | 184 | ✅ |
| 2026-07-05 (SeismicPredictionPage) | 196 | ✅ |
| 2026-07-05 (VisualizationPage) | 205 | ✅ |
| 2026-07-06 (Post-implementation hardening) | 206 | ✅ |
| 2026-07-06 (Post-implementation hardening 2) | 212 | ✅ |
| 2026-07-06 (Preflight warning cleanup) | 212 | ✅ |
