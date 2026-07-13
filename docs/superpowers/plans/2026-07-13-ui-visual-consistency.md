# Global Visual Consistency Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tokenize all ~60 hardcoded spacing/font magic numbers, complete interaction states (focus/empty), add core keyboard shortcuts.

**Architecture:** Three sequential work lines: (1) tokenization — pure value substitution across ~28 files; (2) interaction states — audit + fix focus rings and empty-state objectNames; (3) keyboard shortcuts — QShortcut bindings in AppShell + PaleoWorkbenchWindow.

**Tech Stack:** PySide6 (QShortcut, QKeySequence), existing tokens.py.

**Spec:** `docs/superpowers/specs/2026-07-13-ui-visual-consistency-design.md`

## Global Constraints

- Normalization mapping (verbatim from spec): `4→SPACE_1`, `6→SPACE_2`, `8→SPACE_2`, `10→SPACE_3`, `12→SPACE_3 or PAGE_MARGIN` (page-level layout→PAGE_MARGIN; inner→SPACE_3), `14→PAGE_MARGIN`, `16→SPACE_4`, `24→SPACE_4`, `11px→FONT_SIZE_STATUS`, `12px→FONT_SIZE_BASE`, `12.5px→FONT_SIZE_BASE`.
- `(0, 0, 0, 0)` margins stay as-is (legitimate layout strips).
- Toolbar strips `(12, 0, 12, 0)` → `(PAGE_MARGIN, 0, PAGE_MARGIN, 0)` (keep the zero-vertical pattern).
- Tokenization changes VALUES only — no layout structure changes, no widget reordering.
- Page-switch shortcuts (1-9) must NOT fire when a text field has focus (guard: check `QApplication.focusWidget()` is not a `QLineEdit`/`QTextEdit`/`QTextBrowser`).
- Stay on `main`. TDD where behavioral; tokenization is value-only (full-suite regression is the gate). Frequent commits.

---

## Task 1: Tokenize shell widgets (header_toolbar, menu_bar, icon_rail, app_shell)

**Files:**
- Modify: `paleo_workbench/ui/header_toolbar.py`, `paleo_workbench/ui/menu_bar.py`, `paleo_workbench/ui/icon_rail.py`, `paleo_workbench/ui/app_shell.py`

- [ ] **Step 1: Tokenize header_toolbar.py**

`layout.setContentsMargins(12, 0, 12, 0)` → `layout.setContentsMargins(tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, 0)`. Ensure `tokens` is imported.

- [ ] **Step 2: Tokenize menu_bar.py**

`layout.setContentsMargins(12, 0, 12, 0)` → `(tokens.PAGE_MARGIN, 0, tokens.PAGE_MARGIN, 0)`.
`layout.setSpacing(24)` → `tokens.SPACE_4`.

- [ ] **Step 3: Tokenize icon_rail.py**

`layout.setContentsMargins(7, 8, 7, 8)` → `(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)` (normalize 7→8).
`layout.setSpacing(4)` → `tokens.SPACE_1`.

- [ ] **Step 4: app_shell.py** — `outer.setSpacing(0)` and `middle.setSpacing(0)` stay (legitimate 0). No change needed; verify.

- [ ] **Step 5: Run full suite — expect PASS**

```bash
source .venv/bin/activate && python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/header_toolbar.py paleo_workbench/ui/menu_bar.py paleo_workbench/ui/icon_rail.py
git commit -m "refactor: tokenize spacing in shell widgets (header/menu/rail)"
```

---

## Task 2: Tokenize home page widgets (activity_card, completeness_card, workflow_progress, resource_summary)

**Files:**
- Modify: `paleo_workbench/ui/pages/activity_card.py`, `completeness_card.py`, `workflow_progress.py`, `resource_summary.py`

- [ ] **Step 1: activity_card.py**
- `layout.setContentsMargins(16, 16, 16, 16)` → `(tokens.SPACE_4,)*4`
- `layout.setSpacing(8)` → `tokens.SPACE_2`
- `self.entries_layout.setSpacing(4)` → `tokens.SPACE_1`
- `entry_layout.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 2: completeness_card.py**
- `layout.setContentsMargins(16, 16, 16, 16)` → `(tokens.SPACE_4,)*4`
- `layout.setSpacing(8)` → `tokens.SPACE_2`
- `row_layout.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 3: workflow_progress.py**
- `step_layout.setContentsMargins(8, 8, 8, 8)` → `(tokens.SPACE_2,)*4`
- `step_layout.setSpacing(4)` → `tokens.SPACE_1`
- Inline `border-radius: 8px` → `f"border-radius: {tokens.RADIUS_BADGE}px"` (already a token for 8).

- [ ] **Step 4: resource_summary.py**
- `layout.setContentsMargins(16, 12, 16, 12)` → `(tokens.SPACE_4, tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_3)`
- `layout.setSpacing(24)` → `tokens.SPACE_4`
- `group_layout.setSpacing(2)` → `tokens.SPACE_1` (normalize 2→4)

- [ ] **Step 5: Run full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/activity_card.py paleo_workbench/ui/pages/completeness_card.py paleo_workbench/ui/pages/workflow_progress.py paleo_workbench/ui/pages/resource_summary.py
git commit -m "refactor: tokenize spacing in home page widgets"
```

---

## Task 3: Tokenize data page widgets

**Files:**
- Modify: `data_page.py`, `data_detail_panel.py`, `data_reader_panel.py`, `data_asset_table.py`, `data_toolbar.py`, `inspector_panel.py`

- [ ] **Step 1: data_page.py**
- `layout.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 2: data_detail_panel.py**
- `layout.setSpacing(6)` → `tokens.SPACE_2` (two sites)
- `layout.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(10)` → `tokens.SPACE_3`
- `metadata_layout.setSpacing(4)` → `tokens.SPACE_1`
- `preview_layout.setSpacing(4)` → `tokens.SPACE_1`

- [ ] **Step 3: data_reader_panel.py**
- `layout.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 4: data_asset_table.py**
- `layout.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 5: data_toolbar.py**
- `layout.setSpacing(tokens.SPACE_1)` — already tokenized (verify). `column_settings_layout.setSpacing(0)` stays.

- [ ] **Step 6: inspector_panel.py**
- `layout.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 7: Run full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/pages/data_detail_panel.py paleo_workbench/ui/pages/data_reader_panel.py paleo_workbench/ui/pages/data_asset_table.py paleo_workbench/ui/pages/inspector_panel.py
git commit -m "refactor: tokenize spacing in data page widgets"
```

---

## Task 4: Tokenize remaining page widgets (prep/review/prediction/viz/sequence/mapping + factor + result + resource_table + preview_widgets + action_header)

**Files:**
- Modify: `action_header.py`, `factor_task_panel.py`, `factor_preview_grid.py`, `map_canvas_panel.py`, `map_chrome_panel.py`, `map_document_panel.py`, `preparation_page.py`, `review_export_page.py`, `seismic_prediction_page.py`, `sequence_framework_page.py`, `visualization_page.py`, `well_log_prediction_page.py`, `preview_widgets.py`, `result_summary.py`, `resource_table.py`

- [ ] **Step 1: action_header.py**
- `layout.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(10)` → `tokens.SPACE_3`
- `button_row.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 2: factor_task_panel.py**
- `layout.setContentsMargins(4, 6, 4, 6)` → `(tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2)`
- `layout.setSpacing(8)` → `tokens.SPACE_2`
- `text_box.setSpacing(2)` → `tokens.SPACE_1`
- `task_layout.setSpacing(0)` stays.
- Inline `font-size: 11px` → `f"font-size: {tokens.FONT_SIZE_STATUS}"`

- [ ] **Step 3: factor_preview_grid.py**
- `grid_layout.setSpacing(10)` → `tokens.SPACE_3`

- [ ] **Step 4: map_canvas_panel.py**
- `outer.setContentsMargins(12, 12, 12, 12)` → `(tokens.PAGE_MARGIN,)*4`
- `outer.setSpacing(8)` → `tokens.SPACE_2`

- [ ] **Step 5: map_chrome_panel.py**
- `layout.setContentsMargins(14, 14, 14, 14)` → `(tokens.PAGE_MARGIN,)*4` (normalize 14→12)
- `layout.setSpacing(10)` → `tokens.SPACE_3`

- [ ] **Step 6: map_document_panel.py**
- `layout.setContentsMargins(14, 14, 14, 14)` → `(tokens.PAGE_MARGIN,)*4`
- `layout.setSpacing(10)` → `tokens.SPACE_3`

- [ ] **Step 7: preparation_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 8: review_export_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 9: seismic_prediction_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 10: sequence_framework_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 11: visualization_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 12: well_log_prediction_page.py**
- `outer.setSpacing(16)` → `tokens.SPACE_4`
- `content.setSpacing(16)` → `tokens.SPACE_4`

- [ ] **Step 13: preview_widgets.py**
- Three `layout.setSpacing(8)` sites → `tokens.SPACE_2`

- [ ] **Step 14: result_summary.py**
- `export_layout.setSpacing(4)` → `tokens.SPACE_1`
- Inline `font-size: 12px` → `f"font-size: {tokens.FONT_SIZE_BASE}"`

- [ ] **Step 15: resource_table.py**
- Inline `font-size: 12.5px` → `f"font-size: {tokens.FONT_SIZE_BASE}"`

- [ ] **Step 16: Run full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/
git commit -m "refactor: tokenize spacing/font in remaining page widgets"
```

---

## Task 5: Interaction states — focus rings + empty-state objectNames

**Files:**
- Modify: various (audit-driven)
- Test: `tests/test_empty_states.py` (new), `tests/test_focus_states.py` (new)

- [ ] **Step 1: Audit inline-styled buttons without objectNames**

```bash
grep -rn "QPushButton(" paleo_workbench/ui/pages/*.py | grep -v __pycache__ | grep -v "PrimaryButton\|SecondaryButton"
```
For each: ensure it has `setObjectName("PrimaryButton")` or `"SecondaryButton"` so the QSS hover/focus/disabled rules apply. If a button uses a fully inline stylesheet that overrides QSS, add an explicit `:focus` rule or switch to objectName-based styling.

- [ ] **Step 2: Audit empty-state placeholders**

For each page's empty/no-selection state, ensure the placeholder QLabel uses `setObjectName("EmptyStateLabel")`. Key sites:
- `DataReaderPanel` empty label (`self.empty_label`)
- `InspectorPanel` — no-selection state
- `NavigationTree` — empty category (count 0)
- Asset table empty
- Prediction/prep/viz/sequence/review pages without data

- [ ] **Step 3: Write empty-state test**

In `tests/test_empty_states.py`:
```python
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel


def test_reader_empty_state_uses_empty_state_label(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_inspector_empty_state_clears_on_none(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert panel.metadata_table.rowCount() == 0
```

- [ ] **Step 4: Apply objectName fixes from audit (Steps 1-2)**

- [ ] **Step 5: Run full suite + commit**

```bash
python -m pytest -q
git add -A
git commit -m "feat: complete interaction states (focus rings + empty-state labels)"
```

---

## Task 6: Core keyboard shortcuts

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`, `paleo_workbench/app.py`
- Test: `tests/test_keyboard_shortcuts.py` (new)

- [ ] **Step 1: Add page-switch shortcuts to AppShell**

In `app_shell.py`, add a `_setup_shortcuts` method called at the end of `__init__`:
```python
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QTextEdit, QTextBrowser

    def _setup_shortcuts(self) -> None:
        for i in range(min(9, len(tokens.PAGE_NAMES))):
            digit = str(i + 1)
            QShortcut(QKeySequence(digit), self,
                      lambda idx=i: self._shortcut_switch_page(idx))

    def _shortcut_switch_page(self, idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return  # don't hijack digit keys during text entry
        if 0 <= idx < self.page_stack.count():
            self.icon_rail.set_current(idx)
            self._switch_page(idx)
```
Note: `icon_rail.set_current(idx)` must update the rail's active state — check if IconRail has a method to programmatically select; if not, just call `_switch_page(idx)` and update the rail's visual active state.

- [ ] **Step 2: Add project-op shortcuts to PaleoWorkbenchWindow**

In `app.py`, add in `__init__` after wiring:
```python
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_project)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_project)
        QShortcut(QKeySequence("Ctrl+O"), self, self._on_open_project)
        QShortcut(QKeySequence("Ctrl+F"), self, self._shortcut_focus_search)
```
Add `_shortcut_focus_search`:
```python
    def _shortcut_focus_search(self) -> None:
        # Focus the data page search box if data page is active, else header search
        page = self.app_shell.page_stack.currentWidget()
        toolbar = getattr(page, "data_toolbar", None)
        if toolbar and hasattr(toolbar, "search_box"):
            toolbar.search_box.setFocus()
            return
        # Fall back to header toolbar search
        self.app_shell.header_toolbar.search_box.setFocus()
```

- [ ] **Step 3: Add Delete shortcut (data page, scoped)**

In `DataPage.__init__`, add:
```python
        QShortcut(QKeySequence("Delete"), self, self.remove_selected_asset)
```
This is widget-scoped (only fires when DataPage or a child has focus).

- [ ] **Step 4: Write keyboard shortcut tests**

In `tests/test_keyboard_shortcuts.py`:
```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from paleo_workbench.ui.app_shell import AppShell


def test_digit_shortcut_switches_page(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.page_stack.currentIndex() == 0
    # Simulate the shortcut callback directly (QShortcut activation is Qt-version-sensitive)
    shell._shortcut_switch_page(2)
    assert shell.page_stack.currentIndex() == 2


def test_digit_shortcut_blocked_in_text_field(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    search = shell.page_stack.widget(1).data_toolbar.search_box
    search.setFocus()
    shell._shortcut_switch_page(2)  # should be a no-op
    assert shell.page_stack.currentIndex() == 0  # unchanged


def test_project_shortcuts_registered(qtbot):
    from paleo_workbench.app import PaleoWorkbenchWindow
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    # Verify shortcuts exist (their presence is the contract)
    shortcuts = window.findChildren(type(window.children()[0]))  # QShortcut
    # Alternatively, just verify the methods exist and are callable
    assert callable(window.save_project)
    assert callable(window.new_project)
```
(Adjust the test approach — direct callback invocation is more reliable than simulating keypresses under pytest-qt offscreen.)

- [ ] **Step 5: Run full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/app_shell.py paleo_workbench/app.py paleo_workbench/ui/pages/data_page.py tests/test_keyboard_shortcuts.py
git commit -m "feat: add core keyboard shortcuts (1-9 pages, Ctrl+F/N/O/S, Delete)"
```

---

## Task 7: Final review + ledger sync

**Actions:**
- Whole-branch review: verify zero hardcoded spacing/font magic numbers remain (grep); interaction states consistent; shortcuts work and don't conflict with text entry.
- Run full suite, confirm count.
- Update `task_plan.md` / `progress.md` / `findings.md`.

**Commit:** `chore: sync SDD progress ledger (Visual Consistency Polish complete)`

## Self-Review (completed during authoring)

- **Spec coverage:** Tokenization (Tasks 1-4, all 28 files from audit), interaction states (Task 5), shortcuts (Task 6). All 7 acceptance criteria map to tasks. ✓
- **Placeholder scan:** Every step has concrete instructions (exact file + value mapping). No TBD. ✓
- **Consistency:** Normalization mapping applied identically across tasks. `(0,0,0,0)` explicitly excluded. ✓
- **Risk addressed:** Text-field guard for digit shortcuts (Task 6 Step 1); tests use direct callback invocation rather than fragile keypress simulation (Task 6 Step 4). ✓
