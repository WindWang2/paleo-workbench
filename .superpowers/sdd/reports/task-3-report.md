### Task 3 Report: RecentActivityCard Widget

**Status:** Complete

**Commit:** `cea9230e5c3ac18f873842505b3a9e9b60bac92e`

**Test summary:** 4/4 passed in 0.05s — title, empty state, update_with_steps (filters pending → 2 entries), object name.

**Files:**
- Created: `paleo_workbench/ui/pages/activity_card.py`
- Created: `tests/test_activity_card.py`

**TDD workflow followed:**
1. Wrote failing test → failed with `ModuleNotFoundError` (expected).
2. Wrote implementation exactly per brief.
3. Re-ran tests → 4 passed.
4. Committed with the exact message from the brief.

**Verification:**
- TDD red phase confirmed (ModuleNotFoundError before implementation).
- TDD green phase confirmed (4 passed after implementation).
- No deviations from the brief's code.

**Concerns:**
- `STEP_TYPES` is duplicated as a module-level constant here; `tokens.STEP_LABELS` is the canonical 6-element list. If a future task introduces a shared `STEP_TYPES` constant in `tokens.py`, this local copy should be replaced to avoid drift.
- `empty_label` attribute is reassigned to a new `QLabel` instance on every `update_state` call when count==0; the original instance reference set in `__init__` is leaked (only the latest is kept as attribute). Not a correctness issue for the current tests, but the attribute identity changes across updates — consumers holding the original reference would not see updates.
- `update_state` accepts a `state: dict` parameter but never reads it. Acceptable for current test coverage but indicates incomplete integration with app state (presumably wired in a later task).
- `_clear_entries` deletes widgets via `deleteLater` but does not null the `empty_label` attribute reference when entries exist; if `entry_count > 0`, `card.empty_label` still references a deleted widget. Calling `.text()` on it would crash. No current test exercises this path, but it's a latent bug.
