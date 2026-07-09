# Data Management Page Redesign

## Goal

Redesign the data management page as a project data workspace: a dense file/data/results manager on the left and a multi-format reader on the right. Replace the current fixed side panels with floating panels so the center of the page is reserved for actual work.

The page must support managing all project resources, generated artifacts, and files. Selection should immediately show a readable preview when the format is supported.

## Approved Direction

Use the B layout from the visual design review:

- left: primary data table for resources, artifacts, and files
- right: persistent multi-format reader
- floating left panel: data catalog, category filters, status filters
- floating lower/right panel: import and asset operations
- top toolbar: import shortcuts, search, column settings, reader visibility controls

The floating panels overlay the workspace and do not consume fixed splitter width. They can be expanded/collapsed and should never permanently shrink the table or reader.

## Current Context

The current `DataPage` already has important behavior that must be preserved:

- async data import using `QThread`
- resource and artifact table selection
- custom table columns through `DataAssetTable`
- category filtering through `DataCatalogPanel`
- action commands through `ActionPanel`
- right-side preview through `DataReaderPanel`
- PDF rendering with `PySide6.QtPdf.QPdfDocument`
- text, CSV/TSV, image, and PDF preview modes

The main UI issue is that the page still feels like several static cards placed side by side. The catalog and action panels occupy fixed horizontal space, while the reader and table compete for the remaining width. The new design should feel like a file manager with a real reader.

## Layout

### Page Shell

`DataPage` should use a vertical layout:

1. summary strip
2. compact data toolbar
3. main workspace

The main workspace contains a horizontal splitter with:

- `DataAssetTable` on the left
- `DataReaderPanel` on the right

The splitter remains resizable. Default sizing should favor management and reading together, roughly 55/45 on desktop.

### Floating Catalog Panel

The catalog/filter panel becomes a floating overlay, anchored near the left edge of the workspace.

Behavior:

- collapsed state shows a narrow vertical `目录` tab
- expanded state overlays the table area without resizing it
- contains the current category counts
- later can host tags, status filters, and type filters
- clicking a category still calls `DataAssetTable.set_category(...)`

The overlay should have a restrained workbench style: white surface, 8-10px radius, subtle border and shadow. It must not look like a marketing card.

### Floating Operations Panel

The import/action panel becomes a floating overlay anchored near the lower-right area of the table/reader boundary.

It contains:

- `导入文件`
- `导入目录`
- `重新扫描`
- `移出项目`
- `打开目录`
- operation status text

The panel should show import progress/status without blocking the workspace. Import remains asynchronous.

### Data Toolbar

The toolbar sits above the table/reader and contains:

- primary import shortcut
- import directory shortcut
- rescan shortcut
- search box
- `列设置`
- reader visibility toggle
- optional catalog toggle

The existing column settings behavior remains unchanged.

## Multi-Format Reader

The reader is a panel, not metadata and not a thumbnail. It should be a multi-format reading surface with controls appropriate to the active format.

Supported V1 reader modes:

- empty/message
- text/log/json/xml
- CSV/TSV table
- Excel workbook preview
- image
- PDF with page navigation and zoom
- LAS well log summary/curve table
- SEG-Y/seismic fallback summary, with a hook for richer geo-viz/segyio previews

## Reader Library Strategy

Use existing libraries and Qt widgets where possible:

- PDF: replace manual `QPdfDocument.render(...)` + `QLabel` with `PySide6.QtPdfWidgets.QPdfView` when available. Keep a fallback renderer for testability or environments without `QPdfView`.
- Images: keep Qt image widgets (`QPixmap`/`QLabel`) for V1; add fit-to-width and fit-to-window controls.
- Tables: use `pandas` for CSV/TSV and `openpyxl`/`pandas` for Excel. Render through a table model/widget instead of ad hoc CSV-only parsing.
- LAS: use `lasio` to load headers and curve names, then render a table/summary first. Full curve plotting can later use pyqtgraph.
- SEG-Y: use `segyio` when installed, or geo-viz-engine seismic capabilities where already available. V1 can show validated metadata and a clear "open in seismic workflow" affordance if full trace preview is not ready.
- Generic files: show format, size, path, checksum/status, and explain that inline preview is unavailable.

Do not build custom parsers for formats that have mature libraries in the environment.

## Reader Controls

The reader header should show:

- filename/title
- type, format, status
- path or short location
- open directory action

The reader control bar should adapt by mode:

- PDF: previous page, next page, page number, zoom in/out, fit width/window
- image: zoom in/out, fit window
- table/Excel: sheet selector, row limit indicator
- text: wrap toggle, encoding/truncation indicator
- LAS/SEG-Y: summary tabs or mode selector if data is loaded

Controls should be stable in size and should not resize the reader content unpredictably.

## Component Architecture

Introduce or refactor toward these units:

- `DataWorkspace`: owns the splitter, table, reader, and floating overlays.
- `FloatingPanel`: reusable overlay frame with collapsed/expanded state and anchor positioning.
- `DataToolbar`: top operational toolbar for search, import shortcuts, column settings, and panel toggles.
- `DataAssetTable`: remains the table model/view owner and keeps column customization.
- `DataReaderPanel`: remains the reader shell, but delegates format-specific rendering.
- `PreviewProvider`: becomes responsible for selecting preview mode and lightweight metadata.
- Format readers:
  - `PdfPreviewWidget`
  - `ImagePreviewWidget`
  - `TablePreviewWidget`
  - `TextPreviewWidget`
  - `WellLogPreviewWidget`
  - `SeismicPreviewWidget`

Implementation can be incremental: first introduce the workspace and floating panels while preserving existing reader behavior, then upgrade reader widgets by format.

## Data Flow

1. User imports files or directories from toolbar or floating operations panel.
2. Import runs in the existing background thread path.
3. `DataPage` applies `ImportReport`.
4. Summary strip, catalog counts, and table refresh.
5. User filters or searches.
6. User selects a row.
7. `DataReaderPanel` requests a preview from `PreviewProvider`.
8. The active preview widget renders the selected asset.
9. Reader mode changes update the action state and data context signal.

## Error Handling

- If a floating panel action is unavailable, keep the button disabled and keep status text visible.
- If preview loading fails, show an inline reader message with the file path and failure reason.
- If a preview dependency is missing, degrade to metadata summary and avoid crashing the page.
- If import is already running, keep the existing "正在导入，请稍候" behavior.
- If a file is missing, keep the existing missing status and reader message.

## Performance

- Keep import, scanning, checksum, and heavy parsing off the UI thread.
- Initial preview should load a bounded subset for large files.
- Table and Excel previews should enforce row/column limits.
- Reader widgets should cache the current loaded document/image when the file revision has not changed.
- Avoid reloading PDF or image content on simple resize if the document has not changed.

## Testing

Add or update tests for:

- `DataPage` assembles `DataWorkspace`, toolbar, table, reader, and floating panels.
- catalog and action panels are overlays, not splitter children.
- floating catalog panel toggles collapsed/expanded state.
- floating action panel exposes import/rescan/remove/open-directory buttons.
- existing async import tests still pass through toolbar and floating panel actions.
- selection still updates the reader and data context.
- existing column settings tests still pass.
- PDF reader uses `QPdfView` when available and can fall back in tests.
- table preview supports CSV/TSV and Excel through the library-backed path.
- missing dependency or unsupported format degrades to a message view.

## Out of Scope For First Implementation

- persistent floating panel position
- drag-resizing floating panels
- drag-and-drop import
- true virtualized table model for very large project catalogs
- full SEG-Y trace visualization inside the data page
- full LAS curve plotting
- saving reader zoom/page state per file

These can be added after the layout and reader architecture are stable.

## Success Criteria

- The data page visually reads as a dedicated data manager, not a set of static metadata cards.
- The table and reader are the dominant first-viewport content.
- Catalog and actions are available without consuming permanent horizontal width.
- Supported formats render in the reader using appropriate library-backed widgets.
- The page remains responsive during import and preview loading.
- Existing data management behavior continues to pass tests.
