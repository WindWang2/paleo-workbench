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

---

## Review Fix Round
### Findings Addressed
- Added a visible fallback state for the `QPdfView` branch when `QPdfDocument.load()` fails.
- Added focused `QPdfView`-branch tests that substitute lightweight fake `QPdfView` / document classes before constructing `DataReaderPanel`.
- Cleared stale fallback pixmaps before showing PDF render/load failure messages.

### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q
```
Result:
- `1 failed, 11 passed in 0.39s`
- Failing test: `test_reader_panel_shows_failure_message_when_qpdfview_load_fails`
- Failure detail: `assert panel.pdf_widget.fallback_image.isVisible()`

### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q
```
Result:
- `12 passed in 0.35s`

### Changed Files
- `paleo_workbench/ui/pages/preview_widgets.py`
- `tests/test_data_reader_panel.py`
- `.superpowers/sdd/task-4-report.md`

---

## Re-Review Fix Round 2
### Findings Addressed
- Made failed `PdfPreviewWidget` loads durable for the same path/revision so a repeat `load()` does not fall through into `_render_page()` after an earlier document load failure.
- Added a regression test covering repeated `QPdfView` renders for the same failed PDF result and asserting the fallback message, `0 / 0` label, disabled buttons, and no navigator `jump()` calls.

### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_keeps_failed_qpdfview_state_for_same_path_and_revision -q
```
Result:
- `1 failed in 0.19s`
- Failure detail: `assert panel.pdf_widget.fallback_image.isVisible()`

### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py::test_reader_panel_keeps_failed_qpdfview_state_for_same_path_and_revision -q
```
Result:
- `1 passed in 0.13s`

### Full Verification
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_reader_panel.py -q
```
Result:
- `13 passed in 0.34s`

### Changed Files
- `paleo_workbench/ui/pages/preview_widgets.py`
- `tests/test_data_reader_panel.py`
- `.superpowers/sdd/task-4-report.md`
