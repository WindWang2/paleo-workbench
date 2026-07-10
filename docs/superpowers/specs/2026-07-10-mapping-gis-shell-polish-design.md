# Mapping GIS Shell Polish Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Phase:** 20  
> **Related:**  
> - `docs/superpowers/specs/2026-07-10-ui-visual-polish-design.md` (Phase 19 global visual system)  
> - `docs/superpowers/specs/2026-07-10-mapping-editor-v1-design.md`  
> - `paleo_workbench/ui/pages/mapping_page.py`  
> - `paleo_workbench/ui/tokens.py`

## Goal

Polish the **编图 (Mapping) GIS shell** so it feels like a **compact professional GIS** chrome: consistent docks (layer tree, canvas host, attributes), a **visually grouped** toolbar, and a clearer **status-bar coordinate zone**—without changing edit / topology / save / preview **behavior**.

**Success:** Open sample project → 编图 → tools / layers / table / canvas borders and spacing look intentional; status bar project name vs coordinates are visually distinct.

### Decisions

| Dimension | Decision |
|-----------|----------|
| Scope | Mapping page shell + app StatusBar coord styling only |
| Aesthetic | Professional GIS density (lightweight QGIS-like) |
| Approach | Mapping-specific QSS + dock title objectNames + toolbar separators (方案 A) |
| Logic freeze | No signal or tool behavior changes |

## Non-Goals

- Reordering tools in a way that changes behavior or signal contracts  
- New map tools, snap algorithms, or topology rules  
- Collapsible / dockable `QDockWidget` framework rewrite  
- Restyling geo-viz canvas internals (`PaleoMapCanvas` paint pipeline)  
- Deep polish of other AppShell pages  

## Current Baseline

- Phase 19: density tokens, global button/table QSS, shared widgets.  
- Mapping page: `MapEditToolbar` · `MapLayerTree` (240px) · center stack (edit / preview) · `MapAttributeTable` (max height 160).  
- Layer tree, attribute table, canvas hosts still use **local** `setStyleSheet` with duplicated border/card rules.  
- Toolbar is a single flat row of buttons (spacing densified in Phase 19) without visual groups.  
- `StatusBar` has project status + coord string; both use default label styling.

## Architecture

```text
tokens.QSS_TEMPLATE  (+ mapping / status selectors)
        │
        ▼
MapEditToolbar  — separators between visual groups; objectName MapEditToolbar
MapLayerTree / MapAttributeTable / MapCanvasPanel / MapChromePanel — dock look via QSS
MappingPage — spacing tokens only
StatusBar — StatusCoordLabel objectName
```

**Rule:** Prefer global QSS + stable objectNames over per-widget card CSS. Do not change signal wiring.

## Shell anatomy (structure unchanged)

```text
┌─ MapEditToolbar (grouped visually) ─────────────────────────┐
├─ MapLayerTree (240) ─┬─ MapEditView / Preview stack ────────┤
│                      │                                      │
├──────────────────────┴─ MapAttributeTable (bottom) ─────────┤
└─ App StatusBar: [就绪·工程] …… [X Y 深度 层位 CRS] ──────────┘
```

## Toolbar visual groups

**Button order remains as today** (no functional reorder). Insert thin separators between groups.

Current order:

1. 选择, 移动, 节点  
2. 相带, 线, 注记  
3. 捕捉, 撤销, 重做  
4. 图面预览  
5. 重建拓扑, 合并相带, 分割相带  
6. stretch  
7. 生成演示草稿, 保存编图草稿  

| Visual group | Buttons |
|--------------|---------|
| Select | 选择, 移动, 节点 |
| Draw | 相带, 线, 注记 |
| Edit | 捕捉, 撤销, 重做 |
| Preview | 图面预览 |
| Topology | 重建拓扑, 合并相带, 分割相带 |
| (stretch) | |
| Document | 生成演示草稿, 保存编图草稿 |

**Separator widget:** `QFrame` with `objectName("ToolbarSeparator")`, fixed width 1px, min height ~`CONTROL_HEIGHT - 4`, color via QSS (`BORDER`). Helper `_add_separator(layout)` on the toolbar.

**Toolbar chrome:** Keep `objectName("MapEditToolbar")`. Move bg/border into global QSS; remove redundant local frame `setStyleSheet` when equivalent.

`set_preview_mode` disable list stays: exclusive tools + snap + topology buttons. Separators are not disabled as controls.

## Mapping / status QSS (append to `QSS_TEMPLATE`)

Conceptual selectors:

| Selector | Role |
|----------|------|
| `QWidget#MapEditToolbar` | Dock-like strip: `BG_SIDEBAR`, border, `RADIUS_CARD` |
| `QFrame#ToolbarSeparator` | 1px `BORDER`, no border chrome |
| `QFrame#MapLayerTree`, `#MapAttributeTable`, `#MapCanvasPanel`, `#MapChromePanel` | Shared dock: `BG_SIDEBAR`, 1px `BORDER`, `RADIUS_CARD` |
| `QLabel#MapDockTitle` | `FONT_SIZE_TITLE` / `FONT_WEIGHT_TITLE`, primary text, transparent bg |
| `QTreeWidget#MapLayerTreeWidget`, `QTableWidget#MapAttributeTableWidget` | Inner surface; avoid double-heavy outer frame (prefer lighter inner border or none if parent docks) |
| `QLabel#StatusCoordLabel` | `TEXT_SECONDARY`, `FONT_SIZE_STATUS`, monospace-friendly font stack |

Optional: set `MapEditView` objectName and soft border only if needed for consistency.

## Panel and page code changes

| File | Change |
|------|--------|
| `map_edit_toolbar.py` | Insert separators between groups; drop redundant local QSS |
| `map_layer_tree.py` | Title → `MapDockTitle`; remove frame-level duplicate QSS; margins `PANEL_PADDING` / `SPACE_2` |
| `map_attribute_table.py` | Same pattern for title + frame |
| `map_canvas_panel.py` | Rely on dock QSS; empty label → `EmptyStateLabel` objectName if missing |
| `map_chrome_panel.py` | Align frame to dock QSS if it has its own border |
| `map_edit_view.py` | objectName if missing; no paint logic change |
| `mapping_page.py` | `outer` / mid spacing → `SPACE_2` (or `SPACE_3` consistently) |
| `status_bar.py` | `coord_label.setObjectName("StatusCoordLabel")`; spacing tokens; optional separator before coords |
| `tokens.py` | Append mapping/status QSS rules |

## Interaction / logic freeze

| Keep | Do not change |
|------|----------------|
| All toolbar signals | Tool ids, topology, save, demo draft, preview toggle |
| Layer tree / attribute signals | Visibility, lock, document select, property_changed |
| Preview stack index and payload helpers | Preview generation logic |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Double borders (panel + tree/table) | Prefer outer dock border; lighten or remove inner widget border |
| Tests assume layout child counts | Prefer `findChildren(..., "ToolbarSeparator")` over raw counts |
| Accidental signal breakage | No reconnect of tools; separators are non-interactive frames |

## Testing strategy

| Level | What |
|-------|------|
| Unit | ≥4 `ToolbarSeparator`s on toolbar; status coord objectName; dock titles `MapDockTitle` |
| Regression | Existing mapping / toolbar / scene / integration suites green |
| Full suite | Green |
| Manual | Sample project → 编图 → 生成演示草稿: groups, docks, status coords |

## Rollout slices

1. Tokens QSS (mapping + status selectors)  
2. Toolbar separators + drop local toolbar QSS  
3. Layer tree + attribute table dock polish  
4. Canvas host / chrome panel / mapping_page spacing  
5. StatusBar coord styling  
6. Docs (`task_plan` / `progress`) + full suite  

Each slice leaves tests green.

## Acceptance checklist

- [ ] Toolbar visual groups via separators; no signal/API changes  
- [ ] Map dock panels share consistent border/bg via QSS  
- [ ] No unacceptable double-border “box in box” on tree/table  
- [ ] StatusBar project vs coordinates visually distinct  
- [ ] Full pytest green  
- [ ] Demo glance: 编图 feels denser / more GIS-like than Phase 19 baseline  

## Open follow-ups (not Phase 20)

- True multi-row toolbars or QToolBar sections  
- Dockable / collapsible layer panel  
- Status bar live cursor coordinates from map view  
- Other pages’ three-column shell unification  

## Success criteria

1. Mapping chrome looks professionally dense and consistent.  
2. Behavior parity with pre-Phase-20 mapping editor.  
3. Status bar coordinate zone is clearly secondary to project status.
