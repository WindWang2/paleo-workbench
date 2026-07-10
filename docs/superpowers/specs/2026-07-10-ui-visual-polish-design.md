# UI Visual Polish Design (Global Visual System)

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Phase:** 19  
> **Related:**  
> - `docs/superpowers/specs/2026-07-05-appshell-design.md`  
> - `docs/paleo_workbench_screen_inventory.md`  
> - `paleo_workbench/ui/tokens.py`  
> - Prototype: `古地理图编制系统 (standalone).html`  
> - Optional ref: `geo-viz-engine/UI-REF/`

## Goal

Make the Paleogeography Workbench look **demo-ready**: keep the **prototype color system**, apply **professional desktop density**, unify **chrome and controls**, and introduce **light shared widgets**—without changing business logic or page roles.

**Success (demo walkthrough):** 打开样例工程 → shell / toolbars / tables / cards / primary buttons look finished; hover / focus / disabled states are readable; empty states are not bare unstyled labels.

### Decisions

| Dimension | Decision |
|-----------|----------|
| Scope | Global visual system (not a single page) |
| Aesthetic | Hybrid: prototype palette + professional density |
| Approach | Token/QSS-first + 3–5 shared widgets (方案 A) |
| Success bar | Demo-ready + light componentization |
| Boundary | Visual + micro-interactions only; no business logic changes |

## Non-Goals

- Redesigning information architecture or workflows  
- Dark mode or multi-theme engine  
- Full design-system documentation site or large widget catalog  
- Per-page feature work (prediction ML, map tools, etc.)  
- Pixel-perfect match to every standalone.html region (no screenshot CI)  
- Restyling geo-viz engine internal canvases (`WellLogCanvas`, `SeismicView`, etc.)

## Current Baseline

- Design tokens and `QSS_TEMPLATE` in `paleo_workbench/ui/tokens.py` (AppShell extraction from prototype).  
- Global QSS applied in `main.py` via `app.setStyleSheet(tokens.QSS_TEMPLATE)`.  
- Many pages use ad-hoc `setContentsMargins(16, …)` and local `setStyleSheet` on frames/labels.  
- Primary/Secondary buttons exist by objectName but lack full hover/pressed/disabled/focus treatment.  
- Tables and cards rely heavily on per-widget styling → uneven density and “scaffold” feel.  
- Functional phases 1–18 (shell, data, mapping, viz adapter, sample pipeline) are on `main`.

## Architecture

```text
1. tokens.py          — colors, type scale, spacing, radii, control heights
2. QSS_TEMPLATE       — global widget styles (buttons, frames, tables, inputs)
3. Shared widgets     — 3–5 thin wrappers applying tokens consistently
4. Shell application  — menu / header / rail / sidebar / status
5. Page adoption      — margins, objectNames, drop conflicting local QSS
```

**Rule:** Prefer **global QSS + objectName** over per-widget CSS. Shared widgets only when structure (layout + default margins) needs code, not only paint.

### Layering detail

| Layer | Responsibility | Consumers |
|-------|----------------|-----------|
| Tokens | Single source of numeric/color constants | QSS, widgets, pages |
| QSS | Paint: buttons, inputs, tables, panel objectNames | Entire app |
| Widgets | Layout defaults + stable objectNames | Shell + pages |
| Shell | Chrome density and hierarchy | All pages |
| Pages | Adopt margins / cards / toolbars; no logic change | User |

## Density and type scale

| Token | Value | Use |
|-------|-------|-----|
| `SPACE_1` … `SPACE_4` | 4 / 8 / 12 / 16 px | Gaps, padding |
| `PAGE_MARGIN` | 12 px | Page outer margins (replace mixed 16) |
| `PANEL_PADDING` | 10 px | Card interiors |
| `CONTROL_HEIGHT` | 28 px | Toolbar / secondary buttons |
| `CONTROL_HEIGHT_LG` | 32 px | Header primary actions |
| `HEADER_TOOLBAR_HEIGHT` | 36 px (from 38) | Denser chrome |
| `MENU_BAR_HEIGHT` | 36 px | Unchanged |
| `FONT_SIZE_BASE` | ~12.5 px | Body (keep) |
| `FONT_SIZE_TITLE` | 13 px | Section headers |
| `FONT_WEIGHT_TITLE` | 600 | Section headers |

### Color interactions (prototype family preserved)

Keep existing `PRIMARY`, `ACCENT`, `BG_*`, `BORDER_*`, `TEXT_*`.

Add:

| Token | Role |
|-------|------|
| `PRIMARY_HOVER` | e.g. `#2b7cf0` |
| `PRIMARY_PRESSED` | e.g. `#1a5fc4` |
| `PRIMARY_DISABLED` | e.g. `#a8c4f0` |
| `FOCUS_RING` | Primary-colored focus border/outline |

Prefer **border** over heavy drop shadows in Qt; optional soft card elevation only if it does not fight platform styles.

## Shared components (exactly five)

Package: `paleo_workbench/ui/widgets/`

| Widget | Role | Depends on |
|--------|------|------------|
| **`PanelCard`** | White card: border, radius, padding; optional title | tokens + QSS `#PanelCard` |
| **`SectionHeader`** | Single-line section title (optional subtitle) | tokens |
| **`ToolbarStrip`** | Horizontal compact bar (bg, border, 28px controls) | tokens |
| **`EmptyStateLabel`** | Centered secondary text for empty/loading/error | tokens |
| **`PageScaffold`** | Outer VBox: page margin + optional header row + content stretch | composes above |

**Not in V1:** Dialog kit, form-field widgets, data-table redesign (tables via QSS only).

Public exports via `paleo_workbench.ui.widgets` (and re-export from `ui` if that matches existing patterns).

## Global QSS extensions

Still a single `QSS_TEMPLATE` string in `tokens.py`.

1. **Buttons**  
   - `PrimaryButton`: min-height `CONTROL_HEIGHT_LG`; hover / pressed / disabled  
   - `SecondaryButton`: visible border or clear hover fill; min-height `CONTROL_HEIGHT`; checked state clearer  
2. **Inputs**  
   - `SearchBox` and generic `QLineEdit` / `QComboBox`: height ~28; focus border `FOCUS_RING`  
3. **Tables**  
   - `QHeaderView::section`: `BG_HEADER`, border, ~28px height, weight 600  
   - `QTableView` / `QTableWidget`: soft grid; selection tint from primary  
4. **Panels**  
   - `#PanelCard`, `#ToolbarStrip`, `#EmptyStateLabel`  
5. **Shell**  
   - Status bar / sidebar hierarchy via existing objectNames  
   - **Do not** restyle geo-viz canvas internals  

### Micro-interaction states

| State | Behavior |
|-------|----------|
| hover | Primary lighten; secondary fill `BG_SEARCH` |
| pressed | Primary darken |
| disabled | Muted / `PRIMARY_DISABLED` |
| focus | Border or outline using `FOCUS_RING` |
| empty | `EmptyStateLabel` → `TEXT_SECONDARY`, centered |

## File map (by implementation slice)

| Slice | Files |
|-------|--------|
| Tokens / QSS | `paleo_workbench/ui/tokens.py`, token/QSS tests |
| Widgets | `paleo_workbench/ui/widgets/*`, `tests/test_ui_widgets.py` |
| Shell | `header_toolbar.py`, `menu_bar.py`, `sidebar.py`, status bar as needed; `app_shell.py` only if required |
| High-traffic | `home_page.py`, data toolbar/workspace chrome, `map_edit_toolbar.py` |
| Page margins | prediction / seismic / prep / review / sequence / viz / mapping: use `PAGE_MARGIN` |
| Cleanup | Grep-driven: frames that duplicate card chrome → `objectName("PanelCard")` and drop equivalent local QSS |

**Leave alone unless blocking:** local styles inside geo-viz host panels that only color internal labels.

## Adoption order

1. Tokens + QSS (global look improves immediately)  
2. Shared widgets + unit tests  
3. AppShell chrome density  
4. High-traffic pages: 首页, 数据 (toolbar/cards), 编图 toolbar  
5. Remaining pages: margins + PanelCard objectNames where frames already exist  
6. Sweep conflicting local `setStyleSheet` that undoes global buttons/cards  

Each slice must leave the full test suite green.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Local `setStyleSheet` overrides global QSS | Targeted cleanup only where equivalent; do not mass-delete page styles |
| Tests hard-code height 38 / margin 16 | Update expectations to density tokens |
| Accidental layout/logic changes | No signal/API changes; review diffs for behavioral edits |
| Over-scoping into full design system | Cap at five widgets; tables via QSS only |

## Testing strategy

| Level | What |
|-------|------|
| Unit | New tokens exist; widgets construct with correct objectName and min heights |
| QSS smoke | Template contains primary/secondary + panel/table/focus rules; app still applies stylesheet |
| Regression | Full suite green after expectation updates |
| Manual gate | Demo walkthrough (sample project → key pages) for visual readiness |

No screenshot CI or automated visual regression in this phase.

## Acceptance checklist

- [ ] Density tokens documented in `tokens.py` and used by QSS/widgets  
- [ ] Primary/Secondary have hover / pressed / disabled / focus  
- [ ] Tables (header + selection) look intentional under global QSS  
- [ ] Five shared widgets exist and are used in shell and/or ≥2 pages  
- [ ] Page outer margins use `PAGE_MARGIN` consistently on adopted pages  
- [ ] No business-logic or signal API changes  
- [ ] Full pytest green  
- [ ] Demo walkthrough subjectively “not scaffold-like”  

## Open follow-ups (not Phase 19)

- Per-page deep layout redesign  
- Dark theme  
- Replacing geo-viz internal chrome  
- Expanding the component set beyond the five widgets  
- Pixel-diff against standalone.html  

## Success criteria (program)

1. Global visual language is consistent across shell and main pages.  
2. Demo path (sample project open + core pages) looks product-like.  
3. Future pages can adopt tokens/widgets without reinventing card/button styles.
