# DEVONthink Three-Pane Data Page Design (Phase A)

> **Date:** 2026-07-13
> **Status:** Approved (pending spec review)
> **Scope:** Restructure the DataPage from a 2-splitter + floating-overlay-panel layout into a fixed DEVONthink-style 3-pane layout: navigation tree / asset table / preview + inspector.
> **Decomposition:** Sub-project A of the data page overhaul. B (multimodal preview) is complete. C (performance) is separate. A and C do not overlap.

## Goal

Replace the current `DataWorkspace` (a 2-way `QSplitter` of asset-table + reader, with floating `FloatingPanel` overlays for catalog/actions) with a true fixed 3-pane layout modeled on DEVONthink:

1. **Left pane — NavigationTree**: a smart-group tree (QTreeWidget) with category nodes carrying count badges. Replaces the floating catalog panel.
2. **Center pane — AssetTable**: the existing `DataAssetTable` (unchanged), moved into the splitter's middle segment.
3. **Right pane — ReaderPanel + InspectorPanel**: the existing `DataReaderPanel` (preview, unchanged including Phase B multimodal modes) stacked vertically with a new `InspectorPanel` (metadata table), in a vertical `QSplitter`.

Action buttons (import/rescan/remove/open-folder/visualize) move into the top `DataToolbar`. Floating panels are removed.

## Non-Goals

- Virtual folders / saved searches (YAGNI — smart groups cover the need).
- Tag nodes in the tree (ResourceItem.tags exists but tree-by-tag deferred; smart groups only).
- Drag-and-drop reordering of tree nodes.
- Editing metadata in the inspector (read-only this phase).
- Performance work (virtual scrolling, debouncing, concurrency) — that is sub-project C.
- Changing the preview provider/widget pipeline (Phase B is done).

## Current Layout (what changes)

```
DataWorkspace (QGridLayout, z-ordered overlays):
  content_splitter (QSplitter horizontal): [AssetTable | ReaderPanel]
  catalog_floating_panel  (FloatingPanel, top-left overlay)   ← REMOVED
  actions_floating_panel  (FloatingPanel, bottom-right overlay) ← REMOVED
```

`DataPage` wires the floating panels' signals and exposes `content_splitter`, `catalog_panel`, `action_panel` attributes consumed by tests and the toolbar toggle logic.

## New Layout

```
DataPage (QVBoxLayout):
  ResourceSummaryBar  (unchanged)
  DataToolbar         (extended: +remove/open-folder/visualize buttons + import status label)
  DataWorkspace       (rebuilt — see below)
```

```
DataWorkspace (QHBoxLayout):
  main_splitter (QSplitter horizontal, 3 segments, non-collapsible ends):
    [0] NavigationTree       (fixed min 180px, default 220px)
    [1] DataAssetTable       (stretch 1)
    [2] RightColumn          (fixed min 320px, default 480px)
```

```
RightColumn (QVBoxLayout → single QSplitter vertical):
  right_splitter (QSplitter vertical, 2 segments):
    [0] DataReaderPanel      (stretch 2, the preview — unchanged)
    [1] InspectorPanel       (stretch 1, the metadata table — new)
```

- `main_splitter.setChildrenCollapsible(False)` — panes resize but don't vanish.
- `right_splitter.setChildrenCollapsible(False)`.
- Splitter sizes restored to sensible defaults on construction; persistence of splitter geometry is a follow-up (not this phase).

## Components

### NavigationTree — `navigation_tree.py` (new)

Smart-group tree replacing the floating catalog panel.

- `NavigationTree(QTreeWidget)`, objectName "NavigationTree".
- Single column, header hidden. Style: bg `BG_SIDEBAR`, border 1px `BORDER`, radius `RADIUS_CARD`.
- Tree structure (two levels):

  ```
  全部 (N)                          ← top-level "all", always present
  ▾ 输入数据 (N)                    ← group node (artifact_role == "input")
    测井 (N)                        ← type leaf under input
    地震 (N)
    层位 (N)
    井分层 (N)
    时深 (N)
    表格 (N)
    文档 (N)
    影像 (N)
    参考图 (N)
    测井参考 (N)
    未知 (N)
  ▾ 成果 (N)                        ← group node (artifacts + derived/export roles)
  ▾ 参考资料 (N)                    ← group node (document/image_reference/reference_map/well_reference types)
  ▾ 异常 (N)                        ← group node (status in issue set)
  ```

  The group nodes are non-selectable headers (selecting a group filters to that group's superset). The type leaves and "全部" are selectable and emit `category_changed` with the same category-name string the existing `FilterIndex` consumes (so `FilterIndex` and `DataAssetTable` logic is unchanged).

- Each node shows `"名称 (count)"`. Counts computed via the same logic as `DataCatalogPanel.update_counts` (extract that into a shared helper to avoid duplication — see Architecture).
- `category_changed = Signal(str)` — same contract as `DataCatalogPanel`.
- `update_counts(resources, artifacts)`: recompute all node counts; preserve current selection.
- Selection: clicking a selectable node emits `category_changed`. Clicking a group node expands/collapses it (default behavior) but does not change the filter.
- `selected_category() -> str`: returns the active category (default "全部").

### InspectorPanel — `inspector_panel.py` (new)

Read-only metadata table for the selected asset.

- `InspectorPanel(QFrame)`, objectName "InspectorPanel".
- Style: bg `BG_SIDEBAR`, border 1px `BORDER`, radius `RADIUS_CARD`, padding 12px.
- Title label "检查器" (`TEXT_PRIMARY` 13px bold).
- `metadata_table`: reuse `TablePreviewWidget` (2 columns: 属性 / 值), read-only.
- `update_asset(asset: ResourceItem | ExportArtifact | None)`:
  - If None: clear table, show placeholder "未选择数据项".
  - If `ResourceItem`: rows = 名称/路径/类型/格式/CRS(or "—")/标签(or "—", comma-joined)/校验和(or "—")/状态/大小(from parsed_summary.size_bytes or "—")/来源/外部(是/否).
  - If `ExportArtifact`: rows = 格式/输出路径/关联对象/包含要素/生成时间/来源任务.
- No editing (read-only). Type labels in Chinese (复用 `RESOURCE_TYPE_LABELS` from `asset_table_model.py`).

### RightColumn — inlined in `data_workspace.py` (no new file)

- `RightColumn` is a thin `QWidget` wrapping the vertical splitter. Not a separate file — built inside `DataWorkspace` to keep the workspace cohesive.

### DataToolbar extension — `data_toolbar.py` (modify)

Add 3 action buttons + 1 status label (moved from the floating action panel):
- `remove_btn` (移出项目, SecondaryButton) — was on ActionPanel.
- `open_folder_btn` (打开目录, SecondaryButton) — was on ActionPanel.
- `visualize_btn` (可视化, SecondaryButton) — was `open_visualization_btn`.
- `operation_status_label` (QLabel) — import/action feedback (was `operation_status_label` on ActionPanel).

New signals: `remove_requested`, `open_folder_requested`, `visualize_requested`.

The existing `catalog_btn`/`reader_btn` toggle buttons: **remove** `catalog_btn` (tree is now always-visible in the left pane). Keep `reader_btn` to toggle the right column visibility (collapses right pane).

### DataWorkspace rewrite — `data_workspace.py` (modify)

Replace the `QGridLayout` + floating panels with the 3-segment horizontal splitter + vertical right splitter described in New Layout. Expose:
- `self.navigation_tree` (NavigationTree)
- `self.asset_table` (DataAssetTable — unchanged)
- `self.reader_panel` (DataReaderPanel — unchanged)
- `self.inspector_panel` (InspectorPanel)
- `self.main_splitter`, `self.right_splitter` (for size persistence / tests)
- `set_right_visible(bool)` (replaces `set_reader_visible`)

Remove: `catalog_panel`, `catalog_floating_panel`, `action_panel`, `actions_floating_panel`, `content_splitter`, `toggle_catalog_panel`, `toggle_actions_panel`.

### DataPage rewiring — `data_page.py` (modify)

- Replace floating-panel signal wiring with: `navigation_tree.category_changed → asset_table.set_category`; `asset_table.selected_asset_changed → inspector_panel.update_asset` (in addition to the existing preview request).
- Remove references to `catalog_panel`, `action_panel`, `content_splitter`, floating toggle logic.
- Toolbar's new `remove_requested`/`open_folder_requested`/`visualize_requested` signals → existing `_on_*` handlers (the handler logic already exists on DataPage; just re-wire from action panel buttons to toolbar signals).
- `_emit_data_context` unchanged (still emits the context dict for the app-shell sidebar).
- `update_state` unchanged signature; internally calls `navigation_tree.update_counts` instead of `catalog_panel.update_counts`.

## Architecture

### Count-logic extraction

`DataCatalogPanel.update_counts` currently computes category counts inline. `DataCatalogPanel` is being removed (replaced by `NavigationTree`), but its count logic is reusable. Extract a pure function `compute_category_counts(resources, artifacts) -> dict[str, int]` into a shared module (`filter_index.py` — it already owns category semantics). `NavigationTree.update_counts` calls it. This keeps the tree logic testable without duplicating the Counter-based logic.

### Data flow (unchanged category contract)

```
NavigationTree.category_changed(name)
  → DataAssetTable.set_category(name)
    → FilterIndex.filter(name, search_text) → AssetTableModel.set_filtered_rows
```
This is the exact existing flow; `FilterIndex` and category-name strings (`CATEGORIES` dict keys) are reused verbatim. The tree just emits the same strings.

### What stays untouched

- `PreviewProvider`, `PreviewRequestController`, `PreviewCache`, all preview widgets (Phase B).
- `AssetTableModel`, `DataAssetTable`, `FilterIndex`, column-settings logic.
- `DataReaderPanel` internals.
- Import worker (`_ImportWorker`), `import_service`, `scanner`, `classifier`.
- `ResourceSummaryBar`.

## Testing

### New tests

- `tests/test_navigation_tree.py` (~6):
  - objectName; tree has 全部 + 4 group nodes; type leaves under 输入数据; counts populated correctly (e.g. 3 well_log → 测井 (3)); selecting a type leaf emits category_changed with right name; selecting 全部 emits "全部"; group node selection does not change filter (only expands).
- `tests/test_inspector_panel.py` (~4):
  - objectName; ResourceItem → rows include name/path/format/CRS; tags joined; empty state "未选择数据项"; ExportArtifact rows.
- `tests/test_data_workspace.py` (extend/rewrite, ~3):
  - workspace has navigation_tree + asset_table + reader_panel + inspector_panel; main_splitter has 3 segments; right_splitter has 2 segments; set_right_visible toggles.
- `tests/test_data_toolbar.py` (extend, ~3):
  - new buttons present (remove/open_folder/visualize); new signals fire; operation_status_label present; catalog_btn removed.
- `tests/test_data_page.py` (extend, ~2):
  - selecting an asset updates inspector_panel; navigation_tree.category_changed routes to asset_table.

### Regression

All existing data-page tests must pass. Tests referencing `catalog_panel`, `action_panel`, `content_splitter`, floating panels, `catalog_btn` must be updated to the new API (these are mechanical signal/attribute renames). The existing `test_data_catalog_panel.py` tests are removed with the panel (the tree tests cover the same behavior).

## Acceptance Criteria

1. DataPage renders a fixed 3-pane layout: NavigationTree (left) / AssetTable (center) / ReaderPanel+InspectorPanel (right).
2. No floating panels remain; no `FloatingPanel` instances in the data workspace.
3. NavigationTree shows smart groups with correct counts; selecting a node filters the asset table (same category contract).
4. InspectorPanel shows the selected asset's metadata; updates on selection change.
5. Action buttons (remove/open-folder/visualize) live in the toolbar; import status shows there.
6. ReaderPanel (preview) behavior unchanged, including Phase B multimodal modes.
7. AssetTable, FilterIndex, preview pipeline unchanged.
8. All existing (updated) + new tests pass.

## Risks

- **Test churn**: many existing tests reference the floating-panel API (`catalog_panel`, `action_panel`, `content_splitter`, `catalog_btn`). These need mechanical updates — flag as a dedicated task in the plan so the migration is explicit, not scattered.
- **Attribute renames break DataPage internals**: `DataPage` exposes many attributes (`catalog_panel`, `action_panel`, `import_btn`, etc.) consumed internally. The rewiring must update all internal references consistently — the plan task must enumerate them.
- **Splitter geometry**: default sizes must be sane on first render (tree ~220, center stretch, right ~480). Persistence deferred.
- **Selection sync**: when the tree filter changes, the asset table's selection may become invalid → inspector must clear to avoid showing a stale asset. Handled by wiring `asset_table.selected_asset_changed` to clear inspector when selection is lost.
