# Task 3 Report: Data Page Layout and Management Integration

## Implementation summary

- Replaced `DataPage`'s integrated preview surface from `DataDetailPanel` to `DataReaderPanel`.
- Added `DataPage.data_context_changed = Signal(dict)` and `DataPage.current_reader_mode()`.
- Wired selection changes to update the reader, action panel button state, and emitted data context.
- Added `ActionPanel.update_selection_state(has_resource, has_asset, reader_mode)`.
- Added `DataAssetTable.visible_asset_count()`.
- Updated focused page/table tests to assert the new reader-panel-based behavior, while leaving the standalone legacy `DataDetailPanel` coverage untouched.

## RED/GREEN evidence

### RED

Command:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_asset_table.py -v
```

Result:

- `4 failed, 20 passed`
- Failing surface matched the Task 3 brief:
  - `DataPage.reader_panel` missing
  - `DataPage.data_context_changed` missing
  - `DataAssetTable.visible_asset_count()` missing

### GREEN

Command:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_asset_table.py -v
```

Result:

- `24 passed in 1.05s`

## Tests/results

- Focused widget/integration tests run:
  - `tests/test_data_page.py`
  - `tests/test_data_asset_table.py`
- Environment:
  - `QT_QPA_PLATFORM=offscreen`
- Outcome:
  - all focused tests passed

## Files changed

- `paleo_workbench/ui/pages/data_page.py`
- `paleo_workbench/ui/pages/action_panel.py`
- `paleo_workbench/ui/pages/data_asset_table.py`
- `tests/test_data_page.py`
- `tests/test_data_asset_table.py`

## Self-review findings

- `DataPage` now emits context on both `update_state()` and direct selection changes, which keeps external listeners synchronized after import, removal, rescan, and selection.
- `ActionPanel.update_selection_state()` intentionally only enables resource-specific actions for `ResourceItem` selections; artifacts still show reader mode status but cannot be rescanned/removed/opened as resources.
- Existing page tests that previously validated `detail_panel` rendering were updated to validate `reader_panel` rendering instead; legacy `DataDetailPanel` tests remain separate and unchanged.

## Concerns

- `DataPage` now updates action status from both selection-state changes and explicit action messages. This matches current tests and brief requirements, but it means a selection refresh can replace a prior status text with `阅读器: <mode>`.
