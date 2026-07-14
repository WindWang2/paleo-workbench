# Full-Project UI Polish Design

> **Date:** 2026-07-13
> **Status:** Approved (pending spec review)
> **Scope:** Cross-page experience consistency (status bar + sidebar + empty/error states), tooltip coverage, page-switch transition animation, misc cleanup.
> **Approach:** One spec, four work lines, sequential SDD execution.

## Goal

Systematically polish the remaining UI rough edges across all 9 pages that the previous tokenization/interaction-state/shortcut work didn't cover. Four independent work lines, each producing testable deliverables.

## Context

The project is functionally complete (26 phases, all ✅). Previous polish rounds delivered: tokenization (zero hardcoded spacing/font), interaction states (focus rings + empty-state labels), keyboard shortcuts. This spec covers the next layer of polish: contextual information, discoverability (tooltips), transition feedback, and residual cleanup.

## Work Line 1: Cross-Page Experience Consistency + Status Bar + Sidebar

### 1a. Status Bar Enhancement

Current `StatusBar` shows only `f"就绪 · {project_name}"`. Enhance to show contextual fields like the prototype:

- **Project name** (always) - left segment.
- **Mouse coordinates** (X/Y) - shown when the active page has a map/canvas (mapping, visualization). Updated via a signal from the canvas.
- **Current horizon** - from the active compilation run's `target_horizon` or `project.stratigraphy`.
- **CRS** - from `project.coordinate.display_crs`.
- **Scale** - shown on mapping page (from map canvas zoom state).

Implementation: `StatusBar` gains a `update_context(**kwargs)` method accepting optional `coords`, `horizon`, `crs`, `scale`. The method updates only the fields provided; absent fields hide their labels. `AppShell` routes page-specific signals (e.g., `map_canvas.coords_changed`) to `status_bar.update_context(coords=...)`. Pages without a canvas don't emit coords -> label hidden.

Layout: `[就绪 · {name}]  [X: {x}  Y: {y}]  [层位: {horizon}]  [CRS: {crs}]  [1:{scale}]` -- segments separated by `·`, hidden segments omitted. Use `FONT_SIZE_STATUS` (11px) and `TEXT_SECONDARY`.

### 1b. Sidebar Enhancement

Current `TextSidebar` shows only the page name for non-data pages. Enhance to show a 4-section context panel:

- **Page title** (bold, `FONT_SIZE_TITLE`).
- **Workflow progress summary** - current step + status (e.g., "步骤 3/6 · 沉积相预测 · 进行中"). From `dashboard_state` + compilation run steps.
- **Selected item** - name of the currently selected asset/feature/task in the active page (e.g., "选中: well_001.las"). Pages emit a `selection_changed` signal; AppShell routes to sidebar.
- **Quick tips** - 1-2 line shortcut hints for the active page (e.g., "Ctrl+F 搜索 · Delete 移出").

Implementation: `TextSidebar` gains `update_context(page_name, progress=None, selection=None, tips=None)`. Each section is a QLabel; absent sections are hidden. `AppShell._switch_page` calls `update_context` with page-specific data. Data page already has `data_context_changed`; generalize the pattern.

### 1c. Empty/Loading/Error State Unification

Audit all pages for empty/loading/error states and ensure:
- Empty states use `EmptyStateLabel` objectName (already done for data page; extend to all).
- Loading states show "加载中…" with a consistent style (some pages show nothing while loading).
- Error states show the error in a consistent `ERROR_RED` styled label with the same objectName pattern.

Sites to audit: prediction pages (well-log/seismic), sequence framework, visualization, mapping, preparation, review pages.

## Work Line 2: Tooltip Coverage

Add `setToolTip(text)` to all interactive controls that lack one:

- **Toolbar buttons** (data toolbar, mapping toolbar, action headers): Chinese tooltip describing the action (e.g., "导入文件" button -> "导入数据文件到当前工程").
- **Navigation icons** (icon rail): page name + brief description (e.g., "数据 · 多源数据管理").
- **Table column headers**: tooltip on each header explaining the column (e.g., "状态" -> "文件解析状态").
- **Action panel buttons** (remove/open-folder/visualize/rescan): action description.

Implementation: add `setToolTip` calls in each widget's `__init__`. Tooltips are static strings (no dynamic content this phase). Use concise Chinese descriptions (<=15 chars).

## Work Line 3: Page-Switch Transition

Add a brief fade-in highlight when switching pages in the QStackedWidget:

- On `_switch_page(index)`: set the new page's `windowOpacity`-equivalent (QWidget has no opacity; use `QGraphicsOpacityEffect`) from 0.7 to 1.0 over ~150ms via `QPropertyAnimation`.
- The icon rail's active item already gets a highlight (QSS `active` property) -- no change needed there.
- Guard: if the animation is already running (rapid page switches), stop and restart.

Implementation: `AppShell._switch_page` creates a `QGraphicsOpacityEffect` on the new page's widget, animates `opacity` property 0.7->1.0, duration 150ms, easing `OutQuad`. Clean up the effect after animation completes.

## Work Line 4: Misc Cleanup

- `paleo_workbench/ui/widgets/section_header.py`: `setSpacing(2)` -> `tokens.SPACE_1` (missed in the tokenization pass).
- Any other residual hardcoded values found in `ui/widgets/` directory (audit).
- Ensure `ui/widgets/` directory follows the same token conventions as `ui/pages/`.

## Testing

### Work Line 1
- `tests/test_status_bar.py` (extend): `update_context(coords=...)` shows coord label; absent coords hides it; all fields together render correctly.
- `tests/test_sidebar.py` (extend): `update_context` with all 4 sections shows them; with None hides sections.
- `tests/test_empty_states.py` (extend): audit-driven, one test per page verifying empty-state uses `EmptyStateLabel`.

### Work Line 2
- `tests/test_tooltips.py` (new): spot-check that key buttons/icons have non-empty tooltips. (Not exhaustive -- sample representative controls from each page.)

### Work Line 3
- `tests/test_page_transition.py` (new): after `_switch_page`, verify a `QGraphicsOpacityEffect` was attached to the new page (or verify the animation completed and opacity is 1.0).

### Work Line 4
- No new tests; full-suite regression is the gate.

### Regression
All existing tests must pass.

## Acceptance Criteria

1. Status bar shows project name + contextual fields (coords/horizon/CRS/scale) when available; hides absent fields.
2. Sidebar shows title + progress + selection + tips for every page.
3. All pages' empty/loading/error states use consistent styling.
4. All toolbar buttons, nav icons, table headers, and action buttons have tooltips.
5. Page switch has a ~150ms fade-in transition.
6. `section_header.py` tokenized; `ui/widgets/` follows token conventions.
7. All existing + new tests pass.

## Non-Goals

- Dark mode / theme switching.
- Custom animations beyond the page-switch fade.
- Dynamic tooltip content (e.g., "file size: 2.3 MB").
- Status bar memory indicator (prototype had it; YAGNI for desktop).
- Sidebar reordering or customization.
- Accessibility audit beyond tooltips/focus.

## Risks

- **Status bar signal wiring complexity**: pages need to emit contextual signals (coords from canvas, selection from tables). Each page has different signal patterns -- the `update_context(**kwargs)` approach keeps StatusBar generic, but wiring is per-page. Mitigate by starting with the pages that already have signals (data page has `data_context_changed`; mapping has canvas signals) and adding others incrementally.
- **QGraphicsOpacityEffect on QStackedWidget pages**: the effect must be attached to the page widget, not the stack. Some widgets may already have effects or paint overrides. Test that the effect doesn't interfere with existing rendering (especially map canvas / QtWebEngine).
- **Tooltip text maintenance**: static strings could drift from actual behavior. Keep them short and generic.
