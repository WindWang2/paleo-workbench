# Data Table Custom Columns Design

## Goal

Allow users to customize which columns are visible in the data page file list. This makes the data management table easier to scan for different workflows without changing the underlying project data model.

## Current Context

`DataAssetTable` currently renders a fixed eight-column table:

- 文件名
- 类型
- 格式
- 状态
- 角色
- 大小
- 来源
- 路径

The table already supports category filtering, search, selection synchronization, resources, and export artifacts. Those behaviors must continue to work regardless of which columns are visible.

## V1 Behavior

Add a column settings control to the data page table area.

Users can:

- open a column settings menu
- show or hide optional columns with checkboxes
- keep the table selection and reader state unchanged when columns change
- reset to the default column set

The default visible columns remain the current eight columns.

`文件名` is required and cannot be hidden. It remains the primary identity column and always stores the row asset object for selection.

## Column Set

V1 supports the existing table fields only:

- 文件名
- 类型
- 格式
- 状态
- 角色
- 大小
- 来源
- 路径

Future fields such as 校验值, 标签, 坐标系, 更新时间, 文件角色, and 资源 ID are out of scope for this revision.

## Persistence

V1 stores column visibility in memory only for the current application session.

Project-file persistence is intentionally out of scope because it should be part of a broader user preference or project setting design. This avoids adding project schema churn for a UI preference.

## Architecture

Replace the current `HEADERS` list with structured column definitions in `DataAssetTable`.

Each column definition should include:

- stable key
- display label
- default visibility
- whether it is required
- value resolver for `ResourceItem`
- value resolver for `ExportArtifact`

`DataAssetTable` owns:

- current visible column keys
- `set_visible_columns(keys: list[str]) -> None`
- `visible_column_keys() -> list[str]`
- `reset_columns() -> None`

`DataPage` owns the user-facing settings control and calls these methods.

## UI Placement

Place the column settings button directly above or beside the file list table, inside the table panel area. The control should be compact and operational, not a large card or separate page.

Recommended text:

- button: `列设置`
- reset action: `恢复默认列`

The settings menu should use checkable actions so column state is visible without opening a modal dialog.

## Data Flow

1. User opens `列设置`.
2. User toggles a column checkbox.
3. `DataPage` calls `DataAssetTable.set_visible_columns(...)`.
4. `DataAssetTable` rerenders headers and rows from existing resources/artifacts.
5. The current selected asset is resynchronized by asset ID.
6. Search and category filters keep using full asset data, not only visible columns.

## Error Handling

- Unknown column keys are ignored.
- If a caller tries to hide every column, `文件名` remains visible.
- If `文件名` is omitted from requested keys, it is automatically restored.

## Tests

Add focused tests for:

- default columns remain unchanged
- setting visible columns changes header labels and column count
- required `文件名` cannot be hidden
- unknown column keys are ignored
- reset restores the default eight columns
- search still matches fields in hidden columns
- selection remains synchronized after changing columns

## Out of Scope

This revision does not include:

- project-file persistence of column settings
- user profile preferences
- drag-to-reorder columns
- custom computed fields
- sorting
- column width persistence
