# Task 3 Report: Data Workspace Layout With Floating Overlays

## Scope

Implemented the Task 3 workspace split:

- added `paleo_workbench/ui/pages/data_workspace.py`
- added `tests/test_data_workspace.py`
- updated `tests/test_data_page.py`
- rewired `paleo_workbench/ui/pages/data_page.py` to compose `DataToolbar` + `DataWorkspace`

I did not modify unrelated `.superpowers/sdd/*` files that were already dirty.

## TDD Evidence

### RED

1. Added `tests/test_data_workspace.py`.
2. Updated `tests/test_data_page.py` to assert the new splitter contract and `workspace` composition.

Ran:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py -q
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_uses_workspace_toolbar_and_floating_panels -q
```

Observed failures:

- `ModuleNotFoundError: No module named 'paleo_workbench.ui.pages.data_workspace'`
- the new `DataPage` test also failed on the same missing module during collection

### GREEN

Implemented `DataWorkspace` with:

- `content_splitter` containing only `asset_table` and `reader_panel`
- `catalog_panel` inside `catalog_floating_panel`
- `action_panel` inside `actions_floating_panel`
- `toggle_catalog_panel()`
- `toggle_actions_panel()`
- `set_reader_visible(visible: bool)`

Rewired `DataPage` to:

- instantiate `DataToolbar` and `DataWorkspace`
- preserve public attributes required by tests
- rehome the asset table column settings button into the toolbar slot
- keep existing catalog filtering, selection, reader, import, rescan, remove, and open-folder wiring
- connect toolbar actions to the same async import and reader/catalog controls
- disable toolbar import buttons while async import is in progress

Ran:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py -q
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_uses_workspace_toolbar_and_floating_panels -q
```

Results:

- `tests/test_data_workspace.py`: `3 passed`
- `test_data_page_uses_workspace_toolbar_and_floating_panels`: `1 passed`

## Focused Verification

Ran the brief’s focused suite:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_workspace.py tests/test_data_toolbar.py tests/test_data_page.py -q
```

Result:

- `37 passed in 0.77s`

## Notes

- Updated the existing splitter contract test so it now asserts:
  - table index `0`
  - reader index `1`
  - catalog/action panels are not splitter children
- Preserved `DataPage` public attributes used by tests:
  - `content_splitter`
  - `catalog_panel`
  - `asset_table`
  - `reader_panel`
  - `action_panel`
  - `import_btn`
  - `import_folder_btn`
  - `rescan_btn`
  - `remove_btn`
  - column settings attributes

## Self-Review

- The change is scoped to Task 3-owned files plus the required `data_page.py` wiring.
- The new layout contract is enforced directly in tests.
- Async import behavior still routes through the existing worker-thread code path.
- Selection and reader updates still flow through `_set_selected_asset()` and `reader_mode_changed`.
- No concerns found in the focused verification scope.
