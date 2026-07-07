## Final Fix 2 Report

Scope stayed within the requested files plus the report output. I left the untracked project-management plan file untouched.

### Changes

- `paleo_workbench/ui/pages/data_page.py`
  - `DataPage._handle_reader_mode_changed()` now re-emits `data_context_changed` after the reader panel has settled on its new mode.
  - This closes the stale sidebar/app-shell context case during rescans that reclassify the selected asset preview mode.

- `paleo_workbench/ui/pages/preview_provider.py`
  - Added `revision` metadata to `PreviewResult`, sourced from file stat `(size, mtime_ns)`.
  - Expanded preview cache keys to include preview-driving asset metadata (`type`, `format`, `status`, and artifact format) so rescans that change classification do not reuse the wrong cached preview.

- `paleo_workbench/ui/pages/data_reader_panel.py`
  - Image and PDF reload identity now keys off `(path, revision)` instead of path alone.
  - Resize rerenders still reuse the already loaded image/PDF document when revision is unchanged.

### Regressions Added

- `tests/test_data_page.py`
  - Rescan of the selected resource that changes reader mode now verifies the emitted context reports the new mode.

- `tests/test_data_reader_panel.py`
  - Same-path image replacement refreshes the displayed image.
  - Same-path PDF revision change reloads the document, while resize alone does not.

- `tests/test_preview_provider.py`
  - Same-path image stat change produces a new preview revision.

### Verification

- Required focused suite:
  - `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_reader_panel.py tests/test_preview_provider.py -v`
  - Result: `40 passed`

- Broader six-file nearby suite:
  - `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_reader_panel.py tests/test_preview_provider.py tests/test_data_asset_table.py tests/test_data_catalog_panel.py tests/test_sidebar.py -v`
  - Result: `53 passed`

### Notes

- The rescan bug was partly an event-order issue and partly a cache-key issue. Re-emitting context alone was insufficient until preview caching also respected metadata changes that alter preview mode.
