# Data Page Context Menu + Format Export Design

> **Date:** 2026-07-15
> **Status:** Approved (pending spec review)
> **Scope:** Right-click context menu on the data page asset table with 6 actions (preview, rescan, export, open-folder, visualize, remove) + 4 format-conversion exporters.

## Goal

Add a right-click context menu to the `DataAssetTable` that exposes all existing data-page operations (preview, rescan, open-folder, visualize, remove) plus a new format-conversion export feature. Menu items dynamically show/hide based on the selected asset type and available converters.

## Non-Goals

- Batch/multi-select operations (single-selection only this phase).
- Custom conversion parameters or options dialogs (fixed output format per converter).
- Export progress bars (conversions are fast for typical file sizes; show a completion message).
- Export to cloud/network destinations (local file only).
- Drag-and-drop export.

## Context Menu Structure

```
┌─ Context Menu (shown when right-clicking a row with a selected asset) ─┐
│  预览                          ← always; triggers reader preview        │
│  重新扫描                      ← ResourceItem only                      │
│  导出 ▸                        ← only when converters available         │
│    ├ CSV                       ← LAS -> CSV                              │
│    ├ JSON                      ← table -> JSON                          │
│    ├ PNG                       ← image -> PNG                           │
│    └ TXT                       ← text -> TXT                            │
│  打开目录                      ← always                                 │
│  在可视化页面打开              ← ResourceItem + VizAdapter.supports     │
│  ─────────                     ← separator                              │
│  移出项目                      ← always; styled with ERROR_RED          │
└─────────────────────────────────────────────────────────────────────────┘
```

- No selection -> no menu (right-click does nothing).
- Export submenu: only the formats applicable to the selected asset's format appear. If none apply, the "导出" item is hidden entirely.

## Format Converters

New module `paleo_workbench/resources/exporters.py`. Each converter is a pure function `convert(input_path: Path, output_path: Path) -> None` that raises `ExportError` on failure.

### Conversion pairs

| Converter | Input formats | Output ext | Implementation |
|-----------|--------------|------------|----------------|
| `las_to_csv` | `.las` | `.csv` | `lasio.read(path)` -> pandas DataFrame -> `df.to_csv(output)` |
| `table_to_json` | `.csv`, `.xlsx`, `.xls` | `.json` | `pd.read_csv` or `pd.read_excel` -> `df.to_json(orient="records")` |
| `image_to_png` | `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `.bmp` | `.png` | Pillow `Image.open(path).save(output, "PNG")`. For GeoTIFF: try rasterio read (strip geo metadata) -> Pillow save; fall back to direct Pillow open. |
| `text_to_txt` | `.txt`, `.md`, `.json`, `.xml`, `.log`, `.dat` | `.txt` | `Path.read_text()` -> `Path.write_text()` (strip to plain text; for JSON/XML it's the raw text). |

### Format availability query

```python
def get_available_formats(asset: ResourceItem | ExportArtifact) -> list[tuple[str, callable]]:
    """Return [(label, convert_fn), ...] for formats the asset can export to."""
```

- `ResourceItem`: check `asset.format` against each converter's input set.
- `ExportArtifact`: no converters (artifacts are already output products) -> empty list -> "导出" hidden.

### ExportError

```python
class ExportError(Exception):
    """Raised when a format conversion fails."""
```

## Components

### AssetContextMenu - `asset_context_menu.py` (new)

- `AssetContextMenu(QMenu)`, constructed per right-click with the current selected asset.
- `build(asset: ResourceItem | ExportArtifact | None, viz_supported: bool) -> None`: populates menu items with dynamic visibility.
  - If `asset is None`: no items (menu not shown).
  - 预览: always visible. Signal `preview_requested`.
  - 重新扫描: visible if `isinstance(asset, ResourceItem)`. Signal `rescan_requested`.
  - 导出: visible if `get_available_formats(asset)` is non-empty. Submenu with one action per format. Signal `export_requested(str format_label)`.
  - 打开目录: always visible. Signal `open_folder_requested`.
  - 在可视化页面打开: visible if `viz_supported`. Signal `visualize_requested`.
  - 移出项目: always visible, after separator. Signal `remove_requested`.

### DataAssetTable enhancement - `data_asset_table.py` (modify)

- Enable `self.table.setContextMenuPolicy(Qt.CustomContextMenu)`.
- Connect `customContextMenuRequested` to a handler that:
  1. Maps the click position to a row via `self.table.rowAt(pos.y())`.
  2. Selects that row (so the asset becomes the selected asset).
  3. Emits `context_menu_requested(QPoint global_pos, asset)`.

### DataPage enhancement - `data_page.py` (modify)

- Connect `asset_table.context_menu_requested` to a handler that:
  1. Builds an `AssetContextMenu` with the current selected asset.
  2. Connects the menu's signals to existing DataPage methods (`_preview_controller.request`, `rescan_selected_asset`, `open_selected_folder`, `_emit_open_visualization`, `remove_selected_asset`).
  3. For `export_requested`: calls new `_export_selected_asset(format_label)` method.
- `_export_selected_asset(format_label)`:
  1. Get the selected asset's file path.
  2. `QFileDialog.getSaveFileName` with suggested name `{stem}.{output_ext}`.
  3. If cancelled, return.
  4. Call the converter function in a try/except.
  5. On success: `_set_action_status(f"已导出: {output_path}")`.
  6. On `ExportError`: `_set_action_status(f"导出失败: {error}")`.

## Data Flow

```
User right-clicks a row in DataAssetTable
  -> table.rowAt(pos.y()) selects the row
  -> asset_table.context_menu_requested.emit(global_pos, asset)
  -> DataPage._show_context_menu(global_pos, asset)
  -> AssetContextMenu.build(asset, viz_supported)
  -> menu.exec(global_pos)
  -> user clicks an action
  -> corresponding signal fires
  -> DataPage method executes (existing or new export)
```

## Testing

### Exporter unit tests - `tests/test_exporters.py` (new)

- `test_las_to_csv`: write a minimal LAS file -> convert -> output CSV exists + has header row.
- `test_table_to_json_csv`: write a CSV -> convert -> output JSON is valid + has records.
- `test_image_to_png`: create a small PNG via Pillow -> convert -> output is valid PNG.
- `test_text_to_txt`: write a .md file -> convert -> output .txt has same text content.
- `test_get_available_formats_las`: ResourceItem(format="las") -> returns [("CSV", las_to_csv)].
- `test_get_available_formats_none`: ResourceItem(format="unknown") -> returns [].
- `test_export_error_on_missing_file`: convert with nonexistent input -> raises ExportError.

### Context menu tests - `tests/test_asset_context_menu.py` (new)

- `test_menu_empty_when_no_asset`: build(None) -> no actions.
- `test_menu_has_preview_always`: build(resource) -> 预览 action present.
- `test_menu_rescan_only_for_resource`: build(ExportArtifact) -> 重新扫描 absent.
- `test_menu_export_hidden_when_no_converters`: build(resource with format="unknown") -> 导出 absent.
- `test_menu_export_shown_with_subitems`: build(resource with format="las") -> 导出 has CSV sub-action.
- `test_menu_visualize_hidden_when_unsupported`: build(resource, viz_supported=False) -> 在可视化页面打开 absent.
- `test_menu_remove_always_present`: build(any) -> 移出项目 present.

### Integration test - `tests/test_data_page.py` (extend)

- `test_context_menu_triggers_remove`: right-click -> 移出项目 -> asset removed.
- `test_context_menu_export_las_to_csv`: right-click on LAS resource -> 导出 -> CSV -> file exists.

### Regression

All existing tests must pass.

## Acceptance Criteria

1. Right-clicking a row in the asset table shows a context menu.
2. Menu items dynamically show/hide based on asset type and available converters.
3. 预览/重新扫描/打开目录/可视化/移出 route to existing DataPage methods.
4. 导出 submenu shows only applicable format conversions.
5. LAS -> CSV, table -> JSON, image -> PNG, text -> TXT conversions work and produce valid output files.
6. Export failures show an error message without crashing.
7. No selection -> no context menu.
8. All existing + new tests pass.

## Risks

- **QTableView rowAt with hidden rows**: if the table is filtered, `rowAt(pos.y())` maps to the viewport row, not the model row. Use `self.table.rowAt(pos.y())` which returns the viewport row index (correct for `asset_at(view_row)`). Verify in tests.
- **LAS files with missing curves**: `lasio.read` may fail on malformed LAS. `ExportError` catches this gracefully.
- **Large Excel files**: `pd.read_excel` can be slow for large files. Acceptable for this phase; no progress bar (Non-Goal).
- **GeoTIFF -> PNG**: rasterio may fail on non-raster TIFFs. Fall back to direct Pillow `Image.open`.
