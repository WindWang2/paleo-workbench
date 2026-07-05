# SequenceFrameworkPage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Layer Sequence page at AppShell index 4 with stratigraphy-backed widgets.

**Architecture:** Add three focused child widgets under `paleo_workbench/ui/pages/`, assemble them in `SequenceFrameworkPage`, then wire the page through `AppShell` and `PaleoWorkbenchWindow`. The implementation mirrors the existing DataPage/PreparationPage/ReviewExportPage display-first pattern.

**Tech Stack:** Python 3.12, PySide6, pytest, pytest-qt, existing `paleo_workbench.ui.tokens`.

## Global Constraints

- Do not add runtime dependencies.
- Keep widgets display-first; do not mutate `ProjectDocument`.
- Use `ProjectDocument.stratigraphy` as the source of truth.
- Preserve AppShell page order from `tokens.PAGE_NAMES`; `层序格架` stays index 4.
- Use TDD: write failing tests before production code.

---

### Task 1: Sequence Tokens

**Files:**
- Modify: `paleo_workbench/ui/tokens.py`
- Test: `tests/test_tokens.py`

**Interfaces:**
- Produces: `SEQUENCE_SCHEMES`, `SYSTEMS_TRACT_LABELS`

- [ ] Add failing token tests asserting `SEQUENCE_SCHEMES == ["三级层序格架（推荐）", "四级高频层序", "体系域二分方案"]` and `SYSTEMS_TRACT_LABELS == ["LST", "TST", "HST"]`.
- [ ] Run `pytest tests/test_tokens.py -q` and confirm failure from missing constants.
- [ ] Add constants to `tokens.py`.
- [ ] Re-run `pytest tests/test_tokens.py -q`.

### Task 2: Sequence Child Widgets

**Files:**
- Create: `paleo_workbench/ui/pages/sequence_target_panel.py`
- Create: `paleo_workbench/ui/pages/sequence_boundary_table.py`
- Create: `paleo_workbench/ui/pages/sequence_scheme_summary.py`
- Test: `tests/test_sequence_target_panel.py`
- Test: `tests/test_sequence_boundary_table.py`
- Test: `tests/test_sequence_scheme_summary.py`

**Interfaces:**
- Produces: `SequenceTargetPanel.update_state(stratigraphy)`, `SequenceBoundaryTable.update_state(stratigraphy)`, `SequenceSchemeSummary.update_state(stratigraphy)`

- [ ] Add failing tests for target horizon/scheme/version/count display.
- [ ] Add failing tests for boundary rows and empty state.
- [ ] Add failing tests for scheme summary, boundary count, systems tract labels, and button text.
- [ ] Run the three new test files and confirm import failures.
- [ ] Implement the three widgets with existing card styling and conservative defaults.
- [ ] Re-run the three new test files.

### Task 3: Page Assembly

**Files:**
- Create: `paleo_workbench/ui/pages/sequence_framework_page.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_sequence_framework_page.py`

**Interfaces:**
- Produces: `SequenceFrameworkPage.update_state(stratigraphy)`

- [ ] Add failing tests asserting the page object name, child widget types, and update delegation.
- [ ] Run `pytest tests/test_sequence_framework_page.py -q` and confirm failure.
- [ ] Implement `SequenceFrameworkPage`.
- [ ] Export `SequenceFrameworkPage` from the pages package.
- [ ] Re-run `pytest tests/test_sequence_framework_page.py -q`.

### Task 4: App Integration

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_sequence_integration.py`

**Interfaces:**
- Consumes: `SequenceFrameworkPage.update_state(stratigraphy)`
- Produces: `AppShell.update_sequence_framework_page(stratigraphy)`

- [ ] Add failing integration tests asserting AppShell index 4 is `SequenceFrameworkPage` and `PaleoWorkbenchWindow` renders project stratigraphy values.
- [ ] Run `pytest tests/test_sequence_integration.py -q` and confirm failure.
- [ ] Wire `SequenceFrameworkPage` into AppShell index 4.
- [ ] Add `AppShell.update_sequence_framework_page()`.
- [ ] Call it from `PaleoWorkbenchWindow`.
- [ ] Re-run integration tests.

### Task 5: Verification and Ledger

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [ ] Run focused Sequence tests.
- [ ] Run full `pytest -q`.
- [ ] Update progress from 4/9 to 5/9 pages complete and record the final test count.
