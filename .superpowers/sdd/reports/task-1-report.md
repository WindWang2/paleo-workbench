# Task 1 Report: Add HomePage Tokens

## Status
PASS

## Commit
- Hash: `8f8a1f9`
- Message: `feat(ui): add HomePage tokens (step colors, labels, status text, resource labels)`

## Files Modified
- `paleo_workbench/ui/tokens.py` — appended 5 new constants before `QSS_TEMPLATE`:
  - `STEP_COLORS` (list of 6 hex strings)
  - `STEP_LABELS` (list of 6 Chinese strings)
  - `STATUS_TEXT` (dict mapping 8 status keys → Chinese)
  - `ERROR_RED` (`"#dc2626"`)
  - `RESOURCE_LABELS` (dict mapping 3 resource types → Chinese)
- `tests/test_tokens.py` — appended 5 new test functions:
  - `test_step_colors_exist`
  - `test_step_labels_exist`
  - `test_status_text_mapping`
  - `test_error_red_token`
  - `test_resource_labels_exist`

## TDD Workflow
1. Appended new test functions to `tests/test_tokens.py`.
2. Ran `pytest tests/test_tokens.py -v -k "step_colors or step_labels or status_text or error_red or resource_labels"` — verified FAIL with `AttributeError` for all 5 new tests (as expected).
3. Appended new constants to `paleo_workbench/ui/tokens.py` before `QSS_TEMPLATE`.
4. Ran `pytest tests/test_tokens.py -v` — verified ALL 10 tests PASS.
5. Committed changes.

## Test Summary
10 passed in 0.04s (5 existing + 5 new). Full test suite green.

## Concerns
None. Implementation matches the brief exactly. Values follow the established design-token pattern (uppercase module constants, hex strings, Chinese UI strings). No risk of regression to existing tests.
