# Task 1 Report: Preview Provider

## Implementation Summary
- Added `paleo_workbench/ui/pages/preview_provider.py` with `PreviewProvider`, `PreviewResult`, and the exported bounds constants.
- Provider handles `None`, `ResourceItem`, and `ExportArtifact`.
- Text previews are bounded to `MAX_TEXT_PREVIEW_BYTES`.
- Table previews are bounded to a header row plus at most `MAX_TABLE_ROWS` data rows and at most `MAX_TABLE_COLUMNS` columns.
- Added caching so repeated previews for an unchanged file return the same `PreviewResult` object.

## Tests and Results
- Added `tests/test_preview_provider.py` with six focused tests covering:
  - empty state
  - bounded text preview
  - bounded CSV table preview
  - missing file handling
  - cache reuse
  - export artifact messaging
- Verification run:
  - `pytest tests/test_preview_provider.py -v`
  - Result: `6 passed`

## RED / GREEN TDD Evidence
- RED:
  - Ran `pytest tests/test_preview_provider.py -v` before implementation.
  - Result: import failure on `paleo_workbench.ui.pages.preview_provider` because the module did not exist yet.
- GREEN:
  - Implemented the provider.
  - Re-ran `pytest tests/test_preview_provider.py -v`.
  - Result: `6 passed`.

## Files Changed
- `paleo_workbench/ui/pages/preview_provider.py`
- `tests/test_preview_provider.py`
- `.superpowers/sdd/task-1-report.md`

## Self-Review Findings
- Table preview logic keeps the CSV header separate from `table_rows`, which matches the task contract of one header row plus bounded data rows.
- The cache key includes path metadata and checksum where available, so unchanged files reuse the same preview object while file edits invalidate the cache.
- `clear()` fully resets the in-memory cache.

## Concerns
- None at this stage.

## Reviewer Fixes
- Reworked `_text_preview()` to read at most `MAX_TEXT_PREVIEW_BYTES + 1` bytes from disk and decode only that bounded chunk.
- Reworked `_table_preview()` to read a bounded binary preview chunk, split it into at most one header row plus `MAX_TABLE_ROWS` data rows, and parse each row individually with `csv.reader`.
- Switched `PreviewResult.table_headers` and `PreviewResult.table_rows` to immutable tuples so cached preview results cannot leak mutable list state across calls.

## Fresh Verification
- Command: `pytest tests/test_preview_provider.py -v`
- Result: `6 passed`
