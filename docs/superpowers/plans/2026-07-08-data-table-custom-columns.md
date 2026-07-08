# Data Table Custom Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users choose which columns are visible in the data page file list.

**Architecture:** `DataAssetTable` owns structured column definitions and current in-memory visible column keys. `DataPage` owns a compact `列设置` menu and forwards user toggles to the table.

**Tech Stack:** Python, PySide6, pytest-qt, existing `DataPage` and `DataAssetTable`.

## Global Constraints

- Default visible columns remain `文件名`, `类型`, `格式`, `状态`, `角色`, `大小`, `来源`, `路径`.
- `文件名` is required and cannot be hidden.
- Column visibility is in-memory only for V1.
- Search and category filtering continue to use full asset data, not only visible columns.
- Selection, reader, action panel, and sidebar context must remain synchronized when columns change.
- Project-file persistence, drag-to-reorder, sorting, and column width persistence are out of scope.

---

### Task 1: Structured Table Columns

**Files:**
- Modify: `paleo_workbench/ui/pages/data_asset_table.py`
- Modify: `tests/test_data_asset_table.py`

**Interfaces:**
- Produces `DataAssetTable.visible_column_keys() -> list[str]`
- Produces `DataAssetTable.set_visible_columns(keys: list[str]) -> None`
- Produces `DataAssetTable.reset_columns() -> None`

- [x] Write failing tests for default columns, hidden optional columns, required `文件名`, unknown keys, reset, hidden-field search, and selection preservation.
- [x] Implement structured column definitions and visible-column rendering.
- [x] Run `QT_QPA_PLATFORM=offscreen pytest tests/test_data_asset_table.py -v`.
- [x] Commit with `feat: support configurable data table columns`.

### Task 2: Data Page Column Settings UI

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `tests/test_data_page.py`

**Interfaces:**
- Adds a `列设置` button near the file table.
- Adds checkable menu actions for optional columns.
- Adds a `恢复默认列` action.

- [x] Write failing tests for the settings button/menu, toggling a column, required column disabled, and reset action.
- [x] Implement menu UI and hook actions to `DataAssetTable`.
- [x] Run `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_asset_table.py -v`.
- [x] Commit with `feat: add data table column settings menu`.

### Task 3: Verification

**Files:**
- No planned production changes.

- [x] Run `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_asset_table.py -v`.
- [x] Run `QT_QPA_PLATFORM=offscreen pytest`.
- [x] Launch the app and confirm it starts.
- [x] Push the commits.
