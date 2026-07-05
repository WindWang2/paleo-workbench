# Task 6 Report: Integration — Wire HomePage into AppShell

## Status
✅ Complete

## Commit
`adf0acc` — feat: wire HomePage into AppShell at page index 0

## Test Summary
80 passed in 0.44s (78 existing + 2 new in `tests/test_home_integration.py`).

## TDD Cycle
1. Wrote failing test `tests/test_home_integration.py` — both tests failed with `isinstance(page, HomePage)` False, since page 0 was still `PagePlaceholder` (verified RED).
2. Applied source changes per brief:
   - `paleo_workbench/ui/pages/__init__.py` — export `HomePage`.
   - `paleo_workbench/ui/app_shell.py` — import `HomePage`, add it at `page_stack` index 0 (loop now iterates `PAGE_NAMES[1:]` for placeholders), add `update_home_page(state, steps)` method.
   - `paleo_workbench/app.py` — after `set_project_name`, derive `active_run` and `steps` from `self.project.compilation_runs` and call `self.app_shell.update_home_page(state, steps)`.
3. Re-ran `pytest -v` — all 80 tests pass (verified GREEN).
4. Committed the four files together.

## Implementation Notes
- `page_stack.count()` remains 9 (HomePage replaces one PagePlaceholder at index 0); the existing `test_app_shell_has_nine_pages` still passes unchanged.
- `update_home_page` is defensive (`hasattr(home, "update_state")`) so the AppShell can still be constructed standalone with any widget at index 0.
- `app.py` uses the last compilation run's `workflow_steps` if present, else an empty list — matching the dashboard_state contract.
- Verified interfaces against actual source:
  - `HomePage.update_state(state, steps)` exists (home_page.py:27).
  - `ProjectDocument.compilation_runs` and `CompilationRun.workflow_steps` exist (models.py:182, 99).
  - `dashboard_state()` returns the dict shape `update_home_page` consumes (service.py:30).

## Verification
- Step 2 (failing test): both integration tests RED ✓
- Step 6 (full suite): 80/80 GREEN ✓

## Concerns
None. Implementation matches the brief verbatim. `tests/test_app_shell.py` needed no modification — `test_app_shell_has_nine_pages` already asserted `count() == 9`, which still holds.
