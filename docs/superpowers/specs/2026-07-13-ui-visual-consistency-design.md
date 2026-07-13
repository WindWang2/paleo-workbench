# Global Visual Consistency Polish Design

> **Date:** 2026-07-13
> **Status:** Approved (pending spec review)
> **Scope:** Tokenize all hardcoded spacing/font magic numbers, unify panel/page padding norms, complete interaction states (hover/focus/disabled/empty), add core keyboard shortcuts.

## Goal

Eliminate the ~60 hardcoded magic-number spacing/font values across UI widgets by replacing them with design tokens (`SPACE_*`, `PAGE_MARGIN`, `PANEL_PADDING`, `FONT_SIZE_*`). Complete missing interaction states (focus rings, empty/loading states). Add core keyboard shortcuts for navigation and file operations.

## Audit Findings (current state)

### Token system (good foundation)
`tokens.py` defines a complete token set: colors, fonts, dimensions, spacing (`SPACE_1=4`, `SPACE_2=8`, `SPACE_3=12`, `SPACE_4=16`), `PAGE_MARGIN=12`, `PANEL_PADDING=10`, `CONTROL_HEIGHT=28`, radii. The global `QSS_TEMPLATE` covers PrimaryButton/SecondaryButton/SearchBox/tables/rails/sidebar/statusbar with hover/pressed/disabled/focus states.

### Inconsistency: hardcoded margins (16 sites)
| Pattern | Count | Should be |
|---------|-------|-----------|
| `(12, 12, 12, 12)` | 7 | `PAGE_MARGIN` (page-level) or `PANEL_PADDING` (panel-level) |
| `(16, 16, 16, 16)` | 2 | `SPACE_4` |
| `(14, 14, 14, 14)` | 2 | `PAGE_MARGIN` (normalize 14→12) |
| `(16, 12, 16, 12)` | 1 | `(SPACE_4, SPACE_3, SPACE_4, SPACE_3)` |
| `(4, 6, 4, 6)` | 1 | `(SPACE_1, SPACE_2, SPACE_1, SPACE_2)` |
| `(8, 8, 8, 8)` | 1 | `SPACE_2` |
| `(7, 8, 7, 8)` | 1 | `(SPACE_1+3, SPACE_2, ...)` → normalize to `(SPACE_2, SPACE_2, SPACE_2, SPACE_2)` |
| `(12, 0, 12, 0)` | 2 | `(PAGE_MARGIN, 0, PAGE_MARGIN, 0)` (toolbar strips — correct, keep) |

### Inconsistency: hardcoded spacing (~40 sites)
Values: `0, 2, 4, 6, 8, 10, 16, 24`. Mapping: `0`→keep (layout strips), `2`→`SPACE_1` (tight), `4`→`SPACE_1`, `6`→`SPACE_2` (normalize 6→8), `8`→`SPACE_2`, `10`→`SPACE_3` (normalize 10→12), `16`→`SPACE_4`, `24`→`SPACE_4*1.5` → normalize to `SPACE_4`.

### Inconsistency: hardcoded font-size (3 sites)
- `factor_task_panel.py:63` → `font-size: 11px` → `FONT_SIZE_STATUS`
- `resource_table.py:29` → `font-size: 12.5px` → `FONT_SIZE_BASE`
- `result_summary.py:87` → `font-size: 12px` → `FONT_SIZE_BASE`

## Normalization Rules

To eliminate micro-variations (14 vs 12, 6 vs 8, 10 vs 12), normalize to the nearest token:

| Raw value | Token | Notes |
|-----------|-------|-------|
| 4 | `SPACE_1` | |
| 6 | `SPACE_2` | 6→8 (nearest step) |
| 8 | `SPACE_2` | |
| 10 | `SPACE_3` | 10→12 (nearest step) |
| 12 | `SPACE_3` or `PAGE_MARGIN` | page-level layout → PAGE_MARGIN; inner → SPACE_3 |
| 14 | `PAGE_MARGIN` | 14→12 |
| 16 | `SPACE_4` | |
| 24 | `SPACE_4` | 24→16 (normalize wide gaps) |
| 11px font | `FONT_SIZE_STATUS` | |
| 12px font | `FONT_SIZE_BASE` | 12→12.5 |
| 12.5px font | `FONT_SIZE_BASE` | |

## Component Changes

### Work Line 1: Tokenization (all files with hardcoded values)

Replace every hardcoded margin/spacing/font-size with the corresponding token per the mapping above. Files affected (from audit):
- `ui/header_toolbar.py`, `ui/menu_bar.py`, `ui/icon_rail.py`
- `ui/pages/action_header.py`, `activity_card.py`, `completeness_card.py`
- `ui/pages/data_page.py`, `data_detail_panel.py`, `data_reader_panel.py`, `data_asset_table.py`, `data_toolbar.py`, `data_workspace.py`, `inspector_panel.py`
- `ui/pages/factor_task_panel.py`, `factor_preview_grid.py`
- `ui/pages/map_canvas_panel.py`, `map_chrome_panel.py`, `map_document_panel.py`
- `ui/pages/preparation_page.py`, `review_export_page.py`, `seismic_prediction_page.py`, `sequence_framework_page.py`, `visualization_page.py`, `well_log_prediction_page.py`
- `ui/pages/preview_widgets.py`, `resource_summary.py`, `resource_table.py`, `result_summary.py`, `workflow_progress.py`
- `ui/app_shell.py`

### Work Line 2: Interaction states

1. **Focus rings**: The QSS_TEMPLATE already defines `:focus { border: 1px solid FOCUS_RING }` for PrimaryButton/SecondaryButton/SearchBox/QLineEdit/QComboBox. Audit inline-styled buttons/QLabels that bypass QSS (e.g. inline `QPushButton` without objectName) and ensure they either get an objectName that matches QSS or get a focus rule inline. Primary targets: any `QPushButton` in page widgets that uses inline stylesheet instead of `PrimaryButton`/`SecondaryButton` objectNames.

2. **Empty states**: `QLabel#EmptyStateLabel` exists in QSS (`color: TEXT_SECONDARY`). Audit all "no selection"/"empty list" placeholders across pages and ensure they use `setObjectName("EmptyStateLabel")`. Key sites: NavigationTree (empty category), InspectorPanel (no selection), reader panel empty, asset table empty, prediction/prep/viz/sequence/review pages without data.

3. **Hover/pressed/disabled**: already in QSS for standard buttons. Ensure no inline-styled button overrides `:hover`/`:pressed` without also providing `:disabled`.

### Work Line 3: Core keyboard shortcuts

Add `QShortcut` bindings at the `PaleoWorkbenchWindow` / `AppShell` level:

| Shortcut | Action | Target |
|----------|--------|--------|
| `1`-`9` | Switch to page N | `AppShell._switch_page(N-1)` |
| `Ctrl+F` | Focus search box (current page's toolbar, or header search) | Focus the active search field |
| `Ctrl+S` | Save project | `PaleoWorkbenchWindow.save_project()` |
| `Ctrl+N` | New project | `PaleoWorkbenchWindow.new_project()` |
| `Ctrl+O` | Open project | `PaleoWorkbenchWindow._on_open_project()` |
| `Delete` | Remove selected asset (data page only, when asset table has focus) | `DataPage.remove_selected_asset()` |

Implementation: register shortcuts in `AppShell.__init__` (for page-switching) and `PaleoWorkbenchWindow.__init__` (for project ops + Delete). Use `QShortcut(QKeySequence, parent, callback)`.

## Testing

### Tokenization
- No new behavioral tests needed — tokenization is a pure value substitution. The full existing suite (632+) must pass, confirming no layout regression.
- Optional: a lint-style test that greps for raw numbers in `setContentsMargins`/`setSpacing` calls in `ui/pages/*.py` and asserts they use `tokens.*`. (Best-effort; may have legitimate exceptions like `(0,0,0,0)`.)

### Interaction states
- `tests/test_empty_states.py` (new): for each page, construct with an empty project, assert the empty-state placeholder has objectName "EmptyStateLabel" or shows expected placeholder text.
- Existing focus/hover tests (if any) must pass.

### Keyboard shortcuts
- `tests/test_keyboard_shortcuts.py` (new): construct AppShell, simulate `QKeySequence("1")` → page_stack index 0; `"Ctrl+S"` → save_project called (spy); etc. Use `qtbot.keyClick` or `QShortcut` activation.

### Regression
All 632+ existing tests must pass.

## Acceptance Criteria

1. Zero hardcoded spacing magic numbers in `ui/pages/*.py` and `ui/*.py` (all use `tokens.SPACE_*`/`PAGE_MARGIN`/`PANEL_PADDING`), except legitimate `(0,0,0,0)` layout strips.
2. Zero hardcoded `font-size: Xpx` in inline stylesheets (all use `tokens.FONT_SIZE_*`).
3. Panel/page padding normalized: pages use `PAGE_MARGIN`, inner panels use `PANEL_PADDING`.
4. Focus rings visible on all interactive controls.
5. Empty-state placeholders use `EmptyStateLabel` objectName across all pages.
6. Core shortcuts work: 1-9 page switch, Ctrl+F/N/O/S, Delete.
7. All existing + new tests pass.

## Non-Goals

- Custom animations or transitions.
- Dark mode / theme switching.
- Right-to-left layout.
- Responsive/mobile layout.
- Accessibility audit beyond focus rings (screen readers, high contrast).
- Refactoring widget architecture (only style/value changes).

## Risks

- **Visual regression from normalization** (14→12, 6→8, 10→12, 24→16): subtle but visible spacing changes. Mitigated by staying within the token step scale and running the full suite. The changes tighten inconsistencies, so the net effect is a cleaner look.
- **Shortcut conflicts**: Qt may reserve some keys. `1-9` without modifier could conflict with text entry in search boxes — only register page-switch shortcuts when the focus is NOT in a text field (guard with `QApplication.focusWidget()` type check), or use `Qt.ApplicationShortcut` vs `Qt.WindowShortcut` scope. Test this.
- **Inline-styled buttons missing focus**: some buttons use inline stylesheet that overrides the QSS `:focus` rule. Need to either remove the inline override or add an explicit focus rule inline.
