# Task 4 Report: App Shell Sidebar Synchronization

## Implementation summary
- Expanded `TextSidebar.update_data_context(...)` to render resource count, artifact count, issue count, current selection, format, reader mode, and management actions.
- Stored `DataPage` on `AppShell` as `self.data_page`, connected `data_context_changed` to a new `AppShell.update_data_context(context: dict)` adapter, and forwarded emitted context into the sidebar.
- Updated `AppShell.update_data_page(...)` to keep the sidebar's aggregate counts aligned with the richer sidebar contract, including derived issue counts.
- Added regression coverage for the expanded sidebar rendering and the shell-to-sidebar synchronization path driven by `DataPage._set_selected_asset(...)`.

## RED/GREEN evidence
### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py -v
```
Result:
- `tests/test_sidebar.py::test_sidebar_renders_expanded_data_context` failed with `TypeError: TextSidebar.update_data_context() got an unexpected keyword argument 'issue_count'`
- `tests/test_app_shell.py::test_app_shell_syncs_data_page_context_to_sidebar` failed because the sidebar still showed the home-page context instead of the selected asset details

### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py -v
```
Result:
- `13 passed in 2.03s`

## Tests and results
- Focused widget suite run in headless mode with `QT_QPA_PLATFORM=offscreen`
- Verified passing:
  - `tests/test_sidebar.py`
  - `tests/test_app_shell.py`

## Files changed
- `paleo_workbench/ui/app_shell.py`
- `paleo_workbench/ui/sidebar.py`
- `tests/test_app_shell.py`
- `tests/test_sidebar.py`

## Self-review findings
- Kept the change inside the owned files and did not modify `DataPage`.
- Used the existing `data_context_changed` payload directly instead of duplicating selection inference in `AppShell`.
- Updated pre-existing tests whose expectations no longer matched the new sidebar contract, so the suite now checks live data context rather than the removed static reader capability copy.

## Concerns
- Focused verification is limited to `tests/test_sidebar.py` and `tests/test_app_shell.py`; broader UI integration coverage was not run in this task.
