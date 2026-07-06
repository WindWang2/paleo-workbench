# Data Management Page Design

> **Status:** Approved draft, pending user spec review
> **Date:** 2026-07-06
> **Scope:** Upgrade the existing Data page into a project-wide data, result, and file management center with lightweight previews.

## Goal

The Data page becomes the central workspace for managing every file-like asset in a paleogeography project:

- Input data: well logs, seismic, horizons, well stratification, time-depth tables, spreadsheets.
- Reference files: documents, images, historical maps, WLP files, and other supporting material.
- Results and products: generated factor maps, prediction outputs, map documents, QC reports, and export artifacts where they have file-backed outputs.

The page must support import, rescan, classification, deduplication, table browsing, detail inspection, and preview for supported file types. It should remain dense, operational, and consistent with the existing AppShell design language.

## Non-Goals For First Implementation

- No deep LAS, SEGY, PDF, or Excel parsing beyond lightweight preview summaries.
- No file copying into a managed project directory by default.
- No destructive delete of source files.
- No full provenance graph editor.
- No asynchronous background worker unless import latency proves problematic in tests or manual QA.
- No new persistence format migration unless the existing `ProjectDocument` cannot represent the required state.

## Current Foundation

Existing code already provides most of the import foundation:

- `scan_resources(root, project_path=None)` walks a directory and returns `ResourceItem` records.
- `classify_path(path)` maps file names/extensions to resource type, format, and status.
- `ResourceItem` stores name, path, type, format, status, tags, parsed summary, checksum, external flag, and optional artifact role.
- `ProjectDocument.resources` stores input/reference resources.
- `ProjectDocument.export_artifacts` stores generated outputs.
- `ProjectManager.save/load` already relativizes resource paths.

The current Data page is narrower: it renders a summary bar, a resource table, and an action panel with buttons that are not wired to import behavior.

## Page Layout

Use a three-zone operational layout inside the existing AppShell content area.

### Left: Data Catalog

The left panel is a compact category navigator. It groups project assets by operational role and type:

- 全部
- 输入数据
- 成果
- 参考资料
- 异常
- 测井
- 地震
- 层位
- 井分层
- 时深
- 表格
- 文档
- 影像
- 参考图
- 未知

Each row shows label and count. Selecting a row filters the center table. This panel should not be a decorative card nested inside another card; it is a standalone side panel matching existing page panels.

### Center: File Table

The center table is the primary work surface. It extends the existing resource table with enough information to manage project assets:

- 文件名
- 类型
- 格式
- 状态
- 角色
- 大小
- 来源
- 路径

The table supports:

- Search by name/path/tag.
- Filter by selected catalog category.
- Selection-driven detail/preview update.
- Import files.
- Import folder.
- Rescan selected resources.
- Remove from project.
- Open containing folder.

Removal means unregistering from the project document, not deleting source files.

### Right: Details And Preview

The right panel shows the selected item. It has two stacked areas:

1. Metadata details:
   - path
   - checksum
   - size
   - external/project-relative status
   - resource type and format
   - role
   - status
   - tags
   - parse or preview errors

2. Preview area:
   - Well log (`las`): lightweight log summary first; later may render `WellLogCanvas` when curve extraction is available.
   - Seismic (`sgy`/`segy`): file metadata first; explicit "load preview" path can later render `SeismicView(auto_load=False)`.
   - Images (`png`, `jpg`, `jpeg`, `tif`, `tiff`): `QPixmap` preview.
   - Tables (`xlsx`, `xls`, `dat`, `xml`): first rows/columns summary where cheap and safe.
   - Map documents or reference maps: `PaleoMapCanvas` preview when feature data exists; otherwise metadata.
   - Documents (`pdf`, `ppt`, `pptx`): metadata plus external-open action.
   - Unknown/unsupported: metadata-only preview.

Preview loading is lazy and must not block project import. A failed preview leaves the resource in the project and shows a warning in the details panel.

## Data Model Strategy

Use the existing model in the first implementation:

- `ProjectDocument.resources` remains the source for imported data and reference files.
- `ProjectDocument.export_artifacts` remains the source for generated export files.
- `ResourceItem.artifact_role` marks asset role when needed: `input`, `reference`, `derived`, `export`.
- `ResourceItem.parsed_summary` stores lightweight preview metadata such as size, row count, image dimensions, or error summaries.

Do not introduce a new `ProjectFileItem` model in the first implementation. The current model is sufficient for a first data management center and avoids migration risk.

## Import Flow

### Import Files

1. User clicks "导入文件".
2. File picker returns one or more paths.
3. Each path is classified with `classify_path()`.
4. Each file becomes a `ResourceItem`.
5. Existing resources are deduplicated by normalized absolute path and checksum.
6. New resources are appended to `ProjectDocument.resources`.
7. Summary, catalog, table, and details refresh.
8. Status message reports added, skipped duplicate, and unsupported counts.

### Import Folder

1. User clicks "导入目录".
2. Folder picker returns a directory.
3. `scan_resources()` scans recursively.
4. Dedupe and refresh use the same path as file import.

## Deduplication

Deduplication must be deterministic and testable:

- If an imported path resolves to the same absolute path as an existing resource, skip it.
- If a checksum matches an existing resource and the file name differs, skip it as duplicate content but report it separately.
- If checksum is unavailable because a file cannot be read, keep the resource with warning status and an error summary.

## Error Handling

- Missing file: keep existing project record, mark display status as missing.
- Permission/read error during import: do not crash; add a warning result for the file.
- Unsupported preview: display "暂不支持预览" with metadata.
- Preview parse failure: display error summary in the details panel.
- Large files: never deep-load automatically; show metadata and require an explicit preview action in a future phase.

## Component Boundaries

New or revised components:

- `DataCatalogPanel`: category counts and filter selection.
- `DataAssetTable`: extended table and selection API.
- `DataDetailPanel`: metadata and preview host.
- `DataImportService`: pure logic for file/folder import, dedupe, and result reporting.
- `PreviewStrategy` helpers: choose preview mode and produce lightweight preview data.
- `DataPage`: orchestrates state, delegates import calls, updates child widgets.

The import service should be UI-independent and unit tested. UI widgets should receive structured state, not perform filesystem traversal directly.

## Testing Plan

Unit tests:

- `classify_path()` coverage for key extensions and path-based DAT variants.
- `scan_resources()` coverage for recursive import, checksum, size, relative/external paths.
- `DataImportService` adds resources, skips duplicates by path, skips duplicates by checksum, and reports unreadable files.
- Preview strategy maps known types to preview modes and falls back to metadata-only.

Widget tests:

- Catalog renders category counts and emits selected category.
- Extended table renders columns and filters by category/search.
- Detail panel shows metadata for selected resource.
- Detail panel shows image preview for a small image.
- Unsupported preview shows metadata-only message.

Integration tests:

- `PaleoWorkbenchWindow` passes `ProjectDocument.resources` and `export_artifacts` to Data page.
- Clicking/import service path updates project resources and Data page rows.
- Save/load preserves imported resource paths and external flags.

## Acceptance Criteria

- Data page can register files and folders into the project without crashing.
- Imported assets appear in catalog counts and table rows.
- Duplicate imports are skipped with a clear result count.
- Selecting a row updates the detail panel.
- Supported preview types show a preview or lightweight summary.
- Unsupported or failed previews show a readable non-crashing state.
- Existing 9-page AppShell behavior remains intact.
- Full root test suite remains green.
