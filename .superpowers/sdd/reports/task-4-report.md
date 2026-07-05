### Task 4 Report: Integration — Wire DataPage into AppShell

**Status:** Complete

**Workflow:** TDD — wrote failing test first (2 failures: page 1 was PagePlaceholder), implemented changes, all 95 tests pass.

**Changes:**

1. `tests/test_data_integration.py` (created) — two tests verifying page 1 is `DataPage` and that `resource_table` row count matches `project.resources` length.
2. `paleo_workbench/ui/pages/__init__.py` — added `DataPage` import and `__all__` export.
3. `paleo_workbench/ui/app_shell.py`:
   - Imported `DataPage`.
   - Inserted `self.page_stack.addWidget(DataPage())` at index 1; placeholder loop now starts at `tokens.PAGE_NAMES[2:]`.
   - Added `update_data_page(state, resources)` method that delegates to the page's `update_state` when present.
4. `paleo_workbench/app.py` — calls `self.app_shell.update_data_page(state, self.project.resources)` immediately after `update_home_page`.

**Test summary:** 95 passed, 0 failed (93 existing + 2 new data integration tests).

**Verification:**
- Pre-implementation: `pytest tests/test_data_integration.py -v` → 2 failed (page 1 was `PagePlaceholder`).
- Post-implementation: `pytest -v` → 95 passed.

**Concerns:** None. The `update_data_page` follows the same defensive `hasattr` pattern as `update_home_page`, so the integration is consistent with existing conventions.
