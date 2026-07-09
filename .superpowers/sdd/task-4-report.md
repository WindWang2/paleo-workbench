# Task 4 Report: Preview Widgets Shell And QPdfView Reader

## Scope
- Added `paleo_workbench/ui/pages/preview_widgets.py` with `MessagePreviewWidget`, `TextPreviewWidget`, `TablePreviewWidget`, `ImagePreviewWidget`, and `PdfPreviewWidget`.
- Refactored `paleo_workbench/ui/pages/data_reader_panel.py` to delegate preview rendering to those widgets while preserving the existing public fields: `text_preview`, `table_preview`, `image_label`, `pdf_widget`, `pdf_prev_btn`, `pdf_next_btn`, and `pdf_page_label`.
- Added `image_preview_widget` and `pdf_preview_widget` public attributes and updated `tests/test_data_reader_panel.py` to assert through them.

## TDD Evidence
### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_uses_pdf_preview_widget -q
```
Result:
- Failed with `AttributeError: 'DataReaderPanel' object has no attribute 'pdf_preview_widget'`.

### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_uses_pdf_preview_widget -q
```
Result:
- `1 passed in 0.14s`

### Full Verification
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q
```
Result:
- `9 passed in 0.34s`

## Implementation Notes
- `PdfPreviewWidget` uses `PySide6.QtPdfWidgets.QPdfView` when available and falls back to image rendering with the same paging controls when it is not.
- `DataReaderPanel` now uses widget-level `load()` / `load_text()` / `load_table()` methods instead of owning per-format render state directly.
- Resize coverage now targets the public `image_preview_widget` and `pdf_preview_widget` handles; the PDF resize tests explicitly force the fallback path and patch `preview_widgets.QPdfDocument` before panel construction.

## Self-Review
- Verified the refactor kept the compatibility aliases required by the task brief (`image_label -> image_preview_widget`, `pdf_widget -> pdf_preview_widget`, and the PDF control aliases).
- Checked that PDF navigation wrappers remain on `DataReaderPanel` and delegate to the widget.
- Kept edits scoped to the task-owned files plus this report.

## Commit
- `feat: add library-backed preview widgets`

## Concerns
- None.
