# Paleogeography Workbench AppShell Design

> **Date:** 2026-07-05
> **Status:** Approved (pending user spec review)
> **Predecessor:** `2026-07-05-paleogeography-workbench-design.md` (MVP)
> **Scope:** AppShell skeleton + 9-page navigation + design tokens + global QSS

## Background

The MVP (`commit 1691a38`) shipped a 29-line `paleo_workbench/ui/dashboard.py` that only displays project name and workflow counters. The standalone prototype `古地理图编制系统 (standalone).html` defines a richer AppShell with a 4-zone layout, 9-page icon navigation, design tokens, and a status bar. This spec closes that gap.

The standalone HTML is a minified bundle and cannot be parsed for structure at runtime. Layout data in this spec was extracted via headless browser computed-CSS inspection (dimensions, colors, fonts) and accessibility-tree snapshots (navigation structure).

## Goal

Replace the placeholder `WorkflowDashboard` with a production-quality `AppShell` that strictly follows the standalone prototype's layout, colors, typography, and navigation structure. The AppShell is the foundation for all subsequent page specs.

## Non-Goals

- Real page content for any of the 9 pages (each page gets a placeholder widget only).
- `geo-viz-engine` viewer integration (e.g., `PaleoMapCanvas` in the mapping page).
- Search box `Cmd+K` actual search logic.
- Status bar live coordinates/depth (requires map/canvas signal wiring).
- Top menu bar dropdown menu items (labels are display-only in this phase).
- Collapsible sidebar animation (sidebar is fixed 248px in this phase).

## Layout Structure (4 Zones)

```
+------------------------------------------------------+
|  Top Menu Bar  36px    工程与文件/视图/工具/帮助       |  bg #f3f5f9
+------------------------------------------------------+
|  Header Toolbar  38px   新建/打开/保存/属性 + search   |  bg #f3f5f9
+-------+--------------+-------------------------------+
| Icon  | Text Sidebar |  Main Content Area             |
| Rail  |  248px       |                                |
| 60px  |  bg #ffffff  |  bg #eef0f4                   |
| dark  |              |  page-specific content         |
| blue  |  contextual  |  (placeholder in this phase)   |
| 9 nav |  panel       |                                |
+-------+--------------+-------------------------------+
|  Status Bar  24px   就绪·坐标·深度·层位·CRS           |  bg #eef2f7
+------------------------------------------------------+
```

- Total top height: 36 + 38 = 74px
- Total left width: 60 + 248 = 308px

### Zone 1 - Top Menu Bar (36px)

- Background `#f3f5f9`, bottom border `1px solid #dde2e9`
- 4 display-only labels: 工程与文件 / 视图 / 工具 / 帮助 (no dropdowns this phase)

### Zone 2 - Header Toolbar (38px)

- Background `#f3f5f9`, bottom border `1px solid #e2e6ec`
- Left: 4 buttons (新建工程 primary `#1f6fe0` white text; 打开/保存/属性 secondary transparent, hover `#eef2f7`); all `border-radius 5px`
- Right: search box (`bg #eef2f7`, `border-radius 5px`, placeholder `搜索井名 / 层位 / 功能…  Cmd+K`, non-functional)

### Zone 3 - Icon Rail (60px, dark blue)

- Background dark blue (border color `#16407f` measured; use `#1b3a6b` as solid approximation, verify during implementation)
- 9 nav items, each 46x46px, icon (white SVG) + short label (12.5px)
- Active: `bg rgba(255,255,255,0.18)`, white text. Inactive: transparent, `rgba(255,255,255,0.66)`. Hover: `rgba(255,255,255,0.08)`.

### Zone 4 - Text Sidebar (248px)

- Background `#ffffff`, right border `1px solid #e2e6ec`
- Contextual panel changing per active page. This phase: shows page name + placeholder label.

### Zone 5 - Main Content Area

- Background `#eef0f4`, contains `QStackedWidget` with 9 placeholder pages
- Each placeholder: centered `QLabel` with page name. Workflow cards (最近活动/数据完整度) deferred to page content specs.

### Zone 6 - Status Bar (24px)

- Background `#eef2f7`, top border `1px solid #dde2e6`, font 11px, color `#7e8794`
- Static: `就绪 · 惠州26区·珠江组古地理重建` (left) + `X: 0  Y: 0  深度: 0 m  层位: -  CGCS2000 / EPSG:4326` (right). Live values deferred.

## Navigation (9 Pages)

The prototype has 9 icon-rail items (the screen inventory's "7 pages" was a simplification; update `docs/paleo_workbench_screen_inventory.md` to 9 pages).

| # | Label | Page Class | Description |
|---|-------|-----------|-------------|
| 1 | 首页 | HomePage | Project dashboard |
| 2 | 数据 | DataPage | Multi-source data management |
| 3 | 测井预测 | WellLogPredictionPage | Well log + prediction |
| 4 | 地震预测 | SeismicPredictionPage | Seismic + prediction |
| 5 | 层序格架 | SequenceFrameworkPage | Sequence stratigraphy |
| 6 | 可视化 | VisualizationPage | Composite visualization |
| 7 | 制备 | PreparationPage | Factor map preparation |
| 8 | 编图 | MappingPage | Paleogeographic map |
| 9 | 成图审核 | ReviewExportPage | QC and export |

Each page is a `QWidget` with centered placeholder `QLabel`. `QStackedWidget` switches on icon rail click. Active state reflected in icon rail + sidebar.

## Design Tokens

Extracted from standalone prototype computed CSS. Single source of truth.

### Colors

| Token | Value |
|-------|-------|
| primary | `#1f6fe0` |
| accent | `#6f47cf` |
| success | `#1f9d57` |
| teal | `#0f93a4` (newly discovered) |
| bg-body | `#eef0f4` |
| bg-header | `#f3f5f9` |
| bg-sidebar | `#ffffff` |
| bg-search | `#eef2f7` |
| bg-rail | `#1b3a6b` (approximation) |
| text-primary | `#28323f` |
| text-secondary | `#7e8794` |
| text-dark | `#1b2330` |
| text-on-rail | `rgba(255,255,255,0.66)` |
| text-on-rail-active | `#ffffff` |
| border | `#e2e6ec` |
| border-strong | `#dde2e9` |
| border-light | `#d8dee6` |

### Typography

- Family: `"PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif`
- Base: 12.5px, Status: 11px, Sidebar secondary: 10.5px

### Dimensions

menu-bar 36px, header 38px, icon-rail 60px, sidebar 248px, status 24px, rail-item 46px, radius button 5px / card 9px / badge 8px / panel 10px.

## Architecture

### File Structure

```
paleo_workbench/ui/
  __init__.py            # exports AppShell
  app_shell.py           # AppShell(QWidget): assembles 4 zones
  menu_bar.py            # MenuBar(QFrame): 36px
  header_toolbar.py      # HeaderToolbar(QFrame): 38px
  icon_rail.py           # IconRail(QFrame): 60px, 9 items
  sidebar.py             # TextSidebar(QFrame): 248px
  status_bar.py          # StatusBar(QFrame): 24px
  page_placeholder.py    # PagePlaceholder(QWidget)
  tokens.py              # Design token constants + QSS template
  assets/icons/          # 9 SVG nav icons (white)
```

### AppShell Assembly

`AppShell(QWidget)` replaces `WorkflowDashboard`. Layout: `QVBoxLayout` outer (menu_bar, header_toolbar, `QHBoxLayout` middle, status_bar). Middle holds icon_rail, sidebar, `QStackedWidget` (stretch=1).

`IconRail` emits `page_changed(int)` signal. `AppShell._switch_page(index)` switches QStackedWidget and updates sidebar context.

`PAGE_NAMES` constant holds the 9 Chinese labels.

### Integration

- `paleo_workbench/app.py` creates `AppShell` instead of `WorkflowDashboard`.
- `workflow/service.py::dashboard_state()` dict populates status bar (project name) and sidebar context.
- `WorkflowDashboard` (29 lines) deleted; its tests updated to test `AppShell`.
- `adapters/paleo_map.py` untouched.

## Global QSS

Applied to `QApplication` in `main.py`. Styles widgets by object name (`#MenuBar`, `#HeaderToolbar`, `#IconRail`, `#TextSidebar`, `#StatusBar`, `#PrimaryButton`, `#SecondaryButton`, `#SearchBox`) and property selectors (`[navItem=true]`, `[active=true]`).

QSS uses raw hex values (PySide6 QSS does not support CSS variables). `tokens.py` provides Python constants + `QSS_TEMPLATE` string.

## Icon Assets

9 white SVG icons (24x24 viewBox, stroke-based). Try extracting from standalone bundle first; fall back to Lucide icon set mapped to the 9 concepts. Must render white on dark blue rail.

## Testing

- Unit: AppShell assembly, each zone widget, icon rail nav switching, sidebar context, status bar, tokens, QSS loaded.
- Integration: `app.py` creates AppShell, dashboard_state consumed, 9 pages switch.
- Regression: existing 24 MVP tests still pass (update WorkflowDashboard references).
- Target: 30+ new tests, 24 existing still green.

## Acceptance Criteria

1. `python -m paleo_workbench.main` launches window with 4-zone AppShell.
2. 9 icon rail items switch QStackedWidget pages.
3. Active page highlighted in icon rail; sidebar updates.
4. Design tokens match spec values; QSS applied globally.
5. All tests pass (30+ new + 24 existing).
6. `WorkflowDashboard` deleted; no references remain.
