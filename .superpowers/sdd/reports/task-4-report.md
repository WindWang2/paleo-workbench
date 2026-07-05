### Task 4 Report: DataCompletenessCard Widget

**Status:** Complete

**Commit:** `6ab0896c2fd0558a369c78c4f94242688f440f40`

**Test summary:** 5/5 passed in 0.05s — title, three rows with correct labels, update_state ready path ("数据完整"), update_state missing path ("缺少"), object name.

**Files:**
- Created: `paleo_workbench/ui/pages/completeness_card.py`
- Created: `tests/test_completeness_card.py`

**TDD workflow followed:**
1. Wrote failing test → failed with `ModuleNotFoundError` (expected).
2. Wrote implementation exactly per brief.
3. Re-ran tests → 5 passed.
4. Full suite regression check → 75/75 passed.
5. Committed with the exact message from the brief.

**Verification:**
- TDD red phase confirmed (ModuleNotFoundError before implementation).
- TDD green phase confirmed (5 passed after implementation).
- No deviations from the brief's code.

**Concerns:**
- `Qt` is imported from `PySide6.QtCore` but never used in the implementation. Preserved verbatim per the brief; a linter that flags unused imports would flag it.
- `RESOURCE_TYPES` is a module-level constant here that mirrors the keys of `tokens.RESOURCE_LABELS`. If the canonical resource set changes in `tokens.py`, this local list will silently drift. Could be derived as `list(tokens.RESOURCE_LABELS.keys())` in a future refactor, but ordering would then be dict-iteration-dependent.
- `update_state` reads only `available_counts`, `missing_types`, and `ready` from `resource_readiness`; the `required_types` field in the state is ignored. The widget instead iterates over the hardcoded `RESOURCE_TYPES` list. If a state ever reports `required_types` that differ from the canonical three, the widget would not reflect them. No current test exercises this divergence.
