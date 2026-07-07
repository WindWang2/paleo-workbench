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

---

## Reviewer follow-up: sidebar synchronization fixes

### Implementation summary
- Kept the fix scoped to `paleo_workbench/ui/app_shell.py` and `tests/test_app_shell.py`; `sidebar.py` already supported the richer context shape and did not need further changes.
- Seeded `AppShell` sidebar state immediately after connecting `DataPage.data_context_changed`, so startup now reflects the initial project data context even though `DataPage.__init__()` emitted before the connection existed.
- Changed `AppShell.update_data_page(...)` to rebuild the sidebar context from the refresh arguments plus the current `DataPage` selection/reader state, avoiding the old counts-only overwrite that reset `当前选择` and `阅读器`.
- Added focused regressions for:
  - initial sidebar synchronization from a project that already has resources
  - preserving selected asset and reader mode after `shell.update_data_page(...)`

### RED/GREEN evidence
#### RED
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py -v
```
Result:
- `tests/test_app_shell.py::test_app_shell_initializes_sidebar_from_project_data` failed because the sidebar still opened on `首页` and never received the initial data context
- `tests/test_app_shell.py::test_app_shell_update_data_page_preserves_sidebar_selection` failed because `update_data_page(...)` reset the sidebar back to `当前选择: 未选择` and `阅读器: empty`

#### GREEN
Command:
```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py -v
```
Result:
- `15 passed in 2.32s`

### Files changed
- `paleo_workbench/ui/app_shell.py`
- `tests/test_app_shell.py`

### Notes
- `DataPage` was left untouched as requested.
- `AppShell.update_data_page(...)` still honors explicit `resources` / `artifacts` arguments even when they are not yet mirrored onto `project`, while preserving the richer selection details from the live page state.
