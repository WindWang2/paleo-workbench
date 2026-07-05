# Task 7: StatusBar Widget — Report

## Status
Complete

## Commit
da9e72bff058aee0db65850cafbdb231c67e9d9f

## Test Summary
4 passed in 0.03s (test_status_bar_default_text, test_status_bar_coord_label, test_status_bar_set_project_name, test_status_bar_object_name)

## Steps
1. Wrote `tests/test_status_bar.py` (4 tests per brief).
2. Verified FAIL — `ModuleNotFoundError: No module named 'paleo_workbench.ui.status_bar'`.
3. Created `paleo_workbench/ui/status_bar.py` — `StatusBar(QFrame)` with `status_label`, `coord_label`, `set_project_name(name)`, objectName `"StatusBar"`.
4. Verified PASS — 4/4.
5. Committed as `da9e72b`.

## Concerns
- Unused imports `QSpacerItem` and `QSizePolicy` carried over verbatim from the brief; left as-is per "follow it exactly". Could be removed in a later cleanup.
- Coord label is static placeholder text; live coordinate updates will need wiring when map interaction lands.
