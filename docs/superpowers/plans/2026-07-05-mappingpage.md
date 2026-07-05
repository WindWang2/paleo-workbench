# MappingPage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `编图` page at AppShell index 7 with `PaleoMapCanvas` backed by `ProjectDocument.paleomap_documents`.

**Architecture:** Add three focused child widgets under `paleo_workbench/ui/pages/`, assemble them in `MappingPage`, then wire the page through `AppShell` and `PaleoWorkbenchWindow`. The center widget embeds `geoviz_paleo_map.PaleoMapCanvas` and keeps all rendering responsibility in geo-viz-engine.

**Tech Stack:** Python 3.12, PySide6, pytest, pytest-qt, local `geo-viz-engine` package on the existing pytest pythonpath.

## Global Constraints

- Do not add runtime dependencies.
- Keep widgets display-first; do not mutate `ProjectDocument`.
- Use the latest `PaleoMapDocument` as the active map document.
- Preserve AppShell page order from `tokens.PAGE_NAMES`; `编图` stays index 7.
- Use `PaleoMapCanvas.load_features(features, period_name, wells)` rather than reimplementing map rendering.
- Use TDD: write failing tests before production code.

---

### Task 1: Mapping Child Widgets

**Files:**
- Create: `paleo_workbench/ui/pages/mapping_helpers.py`
- Create: `paleo_workbench/ui/pages/map_document_panel.py`
- Create: `paleo_workbench/ui/pages/map_canvas_panel.py`
- Create: `paleo_workbench/ui/pages/map_chrome_panel.py`
- Test: `tests/test_map_document_panel.py`
- Test: `tests/test_map_canvas_panel.py`
- Test: `tests/test_map_chrome_panel.py`

**Interfaces:**
- Produces: `active_map_document(map_documents)`, `MapDocumentPanel.update_state(map_documents)`, `MapCanvasPanel.update_state(document)`, `MapChromePanel.update_state(document)`

- [ ] Add failing tests for active document selection, map name/horizon/count display, canvas feature loading, and chrome defaults.
- [ ] Run the three new test files and confirm import failures.
- [ ] Implement the helper and three child widgets with existing card styling.
- [ ] Re-run the three new test files.

### Task 2: MappingPage Assembly

**Files:**
- Create: `paleo_workbench/ui/pages/mapping_page.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_mapping_page.py`

**Interfaces:**
- Produces: `MappingPage.update_state(map_documents)`

- [ ] Add failing tests asserting object name, child widget types, and update delegation.
- [ ] Run `pytest tests/test_mapping_page.py -q` and confirm failure.
- [ ] Implement `MappingPage`.
- [ ] Export `MappingPage` from the pages package.
- [ ] Re-run `pytest tests/test_mapping_page.py -q`.

### Task 3: App Integration

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_mapping_integration.py`

**Interfaces:**
- Consumes: `MappingPage.update_state(map_documents)`
- Produces: `AppShell.update_mapping_page(map_documents)`

- [ ] Add failing tests asserting AppShell index 7 is `MappingPage` and `PaleoWorkbenchWindow` renders project map document values.
- [ ] Run `pytest tests/test_mapping_integration.py -q` and confirm failure.
- [ ] Wire `MappingPage` into AppShell index 7.
- [ ] Add `AppShell.update_mapping_page()`.
- [ ] Call it from `PaleoWorkbenchWindow`.
- [ ] Re-run integration tests.

### Task 4: Verification and Ledger

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [ ] Run focused Mapping tests with `QT_QPA_PLATFORM=offscreen`.
- [ ] Run full `QT_QPA_PLATFORM=offscreen pytest -q`.
- [ ] Update progress from 5/9 to 6/9 pages complete and record the final test count.
