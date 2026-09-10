# 03 — Design System (V9)

## What exists (kept)

- `paleo_workbench/tokens.py` — canonical 1792-line token sheet: semantic palettes per theme, `DENSITY_TOKENS` (compact/comfortable), `build_qss(theme, density)` — all QSS px/hex literals centralized here.
- `ui/style.py` — dynamic bind registry: `style.bind(widget, render)` re-renders on `theme_changed`; `bind_metrics` re-applies density-driven fixed sizes; weakref lifecycle.
- `ui/theme.py` — ThemeManager (theme + density, persisted, broadcast).

## V9 convergence work

1. **Theme-drift elimination (the big one).** Raw `setStyleSheet(f"...{tokens.BG_SIDEBAR}...")` used compile-time light-theme snapshots — dark/high-contrast switches left stale colors. V9 migrated the 9 worst offender files (39 sites) to `style.bind` with re-fetching `palette()` renderers, and locked the remaining 26 sites (26 files, 1-3 each) behind a snapshot ratchet (`tests/test_ui_sizing_ratchet_v9.py::test_no_new_theme_drifted_stylesheets`). New code must bind; counts may only shrink.
2. **Panel chrome unification.** Fixed widths on whole side panels (the "every module looks different" driver) replaced with one pattern: minimum floor 200 + unrestricted growth + collapsible splitter + scroll degradation. The bounded-elastic band (min 220-240/max 1.6x) panels keep their design but no longer lock docks.
3. **Density vs viewport separation of concerns.** Density (font/control metrics) is a user setting (Ctrl+Alt+D / view menu). Viewport class (compact/normal/wide/ultrawide) drives only non-preference layout constraints (command-input floor, stage-bar label, inspector fold). The two systems compose; neither impersonates the other.

## De-carding status

The worst card-style concentrations (home relationship cards, module cards) stay for now — they are content diagrams inside scroll containers, no longer layout-blocking. Professional-surface components (`PanelHeader`, `SectionHeader`, `PropertyRow`, state badges, `InlineToolbar`) already exist from V6/V7 in `ui/components/` and `workstation/common.py`; new panels must use them (enforced by review, not yet by ratchet).

## Card-avoidance rule for new UI

Prefer: section header, inline controls, property rows, tree/table, split view, inspector section, status strip. Avoid: `QFrame + border + rounded box` wrappers around whole panels (the audit's card pattern). The token sheet's card tokens remain for genuinely card-like content (dashboard tiles on the home page only).
