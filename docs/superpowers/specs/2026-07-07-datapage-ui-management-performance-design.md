# Data Page UI, Management, and Performance Design

## Goal

Rework the data page so it matches the intended workbench layout and behaves as a real data management surface. The page must support project-wide data, result, and file management while providing a high-utility multi-format reader instead of a metadata-heavy preview card.

## Current Problems

- The left context sidebar is not implemented for the data workflow shown in the target UI.
- The right preview area reads visually as metadata, not as a document/file reader.
- PDF preview exists, but it is too small and not the primary interaction.
- File previews are generated directly inside the detail panel, which makes it hard to add scrolling, paging, caching, and larger reader layouts.
- Large text/table/PDF inputs can cause unnecessary work if previews read or render too much at once.
- Data management actions exist but are not visually integrated with selection, reader state, and project context.

## Target Layout

The data page keeps the workbench shell and uses this internal structure:

1. **Left context sidebar**
   - Lives in the existing app sidebar area.
   - Shows real data workflow context, not placeholder text.
   - Includes project data counts, missing/blocked data hints, current selected asset, reader mode, and management shortcuts.

2. **Main data area**
   - Top summary strip remains.
   - Lower area uses a horizontal splitter:
     - data catalog
     - data table
     - multi-format reader
   - The splitter lets users resize the table and reader.

3. **Right action panel**
   - Keeps import and management commands visible.
   - Shows the latest operation report.
   - Reflects whether the current selection supports rescan, remove, open folder, or reader preview.

## Data Management Behavior

The page manages all project-level data objects currently represented in `ProjectDocument`:

- input resources
- derived resources
- export artifacts
- reference documents
- reference images/maps
- unknown or unsupported files
- missing or warning-state files

Required actions:

- import files
- import directory
- rescan selected file
- remove selected file from project
- open selected file directory
- filter by catalog category
- search assets by name, type, format, status, source, and path
- keep selection, reader, action panel, and context sidebar synchronized

Removing an asset only removes it from the project document. It must not delete files from disk.

## Reader Behavior

The right-side reader is the primary selected-file surface. Metadata appears as a compact header or secondary section, not as the main body.

Supported reader modes:

- **PDF**
  - Render one page at a time.
  - Provide previous/next controls.
  - Display current page and total pages.
  - Scale to available reader width.

- **Image**
  - Show the image scaled to the reader viewport while preserving aspect ratio.
  - Do not crop by default.

- **Plain text / logs / DAT**
  - Show a scrollable monospace preview.
  - Read only a bounded preview chunk.
  - Display a truncation notice when the file is larger than the preview limit.

- **CSV / TSV**
  - Show a scrollable table preview.
  - Read only a bounded number of rows and columns.
  - Show row/column limit notices when truncated.

- **JSON / XML**
  - Show formatted or line-preserved text in a scrollable monospace reader.
  - Read only a bounded preview chunk.

- **Unsupported / missing**
  - Show a clear reader message.
  - Keep management actions available where valid.

## Performance Requirements

Preview generation must be bounded and repeatable:

- Text previews read at most 256 KiB.
- Table previews read at most 200 rows and 40 columns.
- PDF previews render only the visible page.
- Image previews scale from the selected file and do not generate multiple hidden variants.
- Preview results are cached by stable asset identity plus file path, checksum, size, and modification time where available.
- Re-selecting the same unchanged asset should reuse cached preview state.
- Category filtering and search should update the table without re-reading file contents.

The data table should only render table rows and lightweight metadata. It must not parse file bodies.

## Component Design

### `DataPage`

Owns project-facing state and coordinates:

- summary bar
- catalog panel
- asset table
- reader panel
- action panel
- selection updates
- import/rescan/remove/open-folder actions

It should notify the app shell when the selected asset or data counts change so the left context sidebar can update.

### `DataReaderPanel`

New dedicated reader widget. It owns:

- compact asset header
- reader body stack
- PDF controls
- scrollable text preview
- scrollable table preview
- image preview area
- unsupported/missing state

It consumes a selected `ResourceItem | ExportArtifact | None` and a preview provider.

### `PreviewProvider`

New focused service for bounded preview preparation. It produces structured preview states without creating Qt widgets.

The reader panel turns those preview states into UI.

Suggested output modes:

- `empty`
- `pdf`
- `image`
- `text`
- `table`
- `message`

### `TextSidebar`

The existing sidebar should expose an update method for data context:

- resource count
- artifact count
- issue count
- selected asset name
- selected asset type/format
- reader mode

The data page should call this through `AppShell` rather than directly depending on the sidebar.

## Error Handling

- Missing files display a missing-file reader state and mark the resource as `missing` when rescanned.
- Decode errors fall back to replacement-character text preview and display a warning.
- CSV parsing errors fall back to text preview.
- PDF load/render errors display a reader error message.
- Import warnings remain visible in the action panel status.

## Tests

Add tests that cover behavior without relying on real dialogs:

- reader panel shows an empty state with no selection
- selecting a text resource shows bounded text preview
- selecting a CSV resource shows bounded table preview
- selecting a PDF resource creates a PDF reader state with paging controls
- missing resources show a missing-file reader message
- category/search changes do not invoke preview loading
- selection updates the app sidebar data context
- import/remove/rescan actions refresh counts and reader state

## Out of Scope

This revision does not implement:

- full project lifecycle actions in the top toolbar
- deleting files from disk
- full-file editing
- geoscience-specific SEG-Y volume visualization
- spreadsheet formula evaluation
- PDF text extraction
- asynchronous background parsing

Those can be added after the data page layout, reader boundary, and management flow are stable.
