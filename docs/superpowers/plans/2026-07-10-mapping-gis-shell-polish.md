# Phase 20 Mapping GIS Shell Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 编图 page feel like a compact professional GIS shell—grouped toolbar, unified docks, clearer status coordinates—without changing tool/topology/save behavior.

**Architecture:** Extend global `QSS_TEMPLATE` with mapping/status selectors; insert non-interactive toolbar separators; replace local dock `setStyleSheet` with objectNames + QSS; status bar coord objectName.

**Tech Stack:** PySide6, Phase 19 tokens, existing mapping widgets, pytest/pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-10-mapping-gis-shell-polish-design.md`

---

## File map

| Path | Change |
|------|--------|
| `paleo_workbench/ui/tokens.py` | Append mapping/status QSS |
| `map_edit_toolbar.py` | Separators; drop local frame QSS |
| `map_layer_tree.py` | MapDockTitle; drop frame QSS; padding tokens |
| `map_attribute_table.py` | Same |
| `map_canvas_panel.py` | EmptyState + drop redundant frame QSS if covered |
| `map_chrome_panel.py` | Align dock QSS |
| `map_edit_view.py` | objectName if missing |
| `mapping_page.py` | SPACE_2 spacing |
| `status_bar.py` | StatusCoordLabel |
| `tests/test_map_edit_toolbar.py` | Separator count |
| `tests/test_status_bar.py` or new | Coord objectName |
| `tests/test_tokens.py` | QSS contains MapLayerTree / StatusCoordLabel |
| `task_plan.md` / `progress.md` | Phase 20 delivery |

---

### Task 1: Mapping + status QSS in tokens

**Files:** `paleo_workbench/ui/tokens.py`, `tests/test_tokens.py`

- [ ] **Step 1: Failing test**

```python
def test_qss_has_mapping_and_status_selectors():
    qss = tokens.QSS_TEMPLATE
    assert "MapEditToolbar" in qss
    assert "ToolbarSeparator" in qss
    assert "MapLayerTree" in qss
    assert "MapAttributeTable" in qss
    assert "MapDockTitle" in qss
    assert "StatusCoordLabel" in qss
    assert "MapCanvasPanel" in qss
```

- [ ] **Step 2: Run — FAIL**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tokens.py::test_qss_has_mapping_and_status_selectors -v
```

- [ ] **Step 3: Append to `QSS_TEMPLATE`** (before or after existing PanelCard rules):

```python
QWidget#MapEditToolbar {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ToolbarSeparator {{
    background: {BORDER};
    border: none;
    max-width: 1px;
    min-width: 1px;
}}
QFrame#MapLayerTree,
QFrame#MapAttributeTable,
QFrame#MapCanvasPanel,
QFrame#MapChromePanel {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#MapDockTitle {{
    color: {TEXT_PRIMARY};
    font-size: {FONT_SIZE_TITLE};
    font-weight: {FONT_WEIGHT_TITLE};
    border: none;
    background: transparent;
}}
QTreeWidget#MapLayerTreeWidget {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px;
}}
QTableWidget#MapAttributeTableWidget {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
}}
QLabel#StatusCoordLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_STATUS};
    font-family: "SF Mono", "Menlo", "Consolas", "Courier New", monospace;
}}
```

- [ ] **Step 4: Pass** `pytest tests/test_tokens.py -q`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: mapping dock and status QSS selectors"
```

---

### Task 2: Toolbar separators

**Files:** `map_edit_toolbar.py`, `tests/test_map_edit_toolbar.py`

- [ ] **Step 1: Test**

```python
from PySide6.QtWidgets import QFrame

def test_toolbar_has_visual_separators(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)
    seps = [w for w in bar.findChildren(QFrame) if w.objectName() == "ToolbarSeparator"]
    assert len(seps) >= 4
```

- [ ] **Step 2: Implement `_add_separator` and insert between groups**

Keep **exact button order**. After building each group, call `_add_separator(layout)`:

1. After label tool (end of select+draw tools) — actually groups:
   - After `label` tool (end of draw) → sep  
   - After tools loop ends at label; select group is first 3, draw next 3 — add sep after vertex (select), after label (draw), after redo (edit), after preview, after split (topology)

Minimal code pattern in `__init__` after each group:

```python
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QWidget

def _add_separator(self, layout: QHBoxLayout) -> QFrame:
    sep = QFrame()
    sep.setObjectName("ToolbarSeparator")
    sep.setFixedWidth(1)
    sep.setMinimumHeight(max(1, tokens.CONTROL_HEIGHT - 4))
    layout.addWidget(sep)
    return sep
```

Insert:

```text
[select, move, vertex] sep
[facies, line, label] sep
[snap, undo, redo] sep
[preview] sep
[topology, merge, split] stretch
[demo, save]
```

Remove local:

```python
self.setStyleSheet(...)  # MapEditToolbar bg — now global QSS
```

Keep `setObjectName("MapEditToolbar")`.

- [ ] **Step 3: All toolbar tests pass**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_map_edit_toolbar.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: visual separators on mapping edit toolbar"
```

---

### Task 3: Layer tree + attribute table docks

**Files:** `map_layer_tree.py`, `map_attribute_table.py`, tests that assert objectNames if any

- [ ] **Step 1: Tests** (add to existing or new `tests/test_map_layer_tree.py` / attribute tests)

```python
def test_layer_tree_dock_title_object_name(qtbot):
    from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
    w = MapLayerTree()
    qtbot.addWidget(w)
    titles = [c for c in w.findChildren(QLabel) if c.objectName() == "MapDockTitle"]
    assert len(titles) >= 1
    assert titles[0].text() == "图件与图层"

def test_attribute_table_dock_title_object_name(qtbot):
    from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
    w = MapAttributeTable()
    qtbot.addWidget(w)
    titles = [c for c in w.findChildren(QLabel) if c.objectName() == "MapDockTitle"]
    assert len(titles) >= 1
```

- [ ] **Step 2: Implement**

`map_layer_tree.py`:

- Keep `setObjectName("MapLayerTree")`
- **Remove** frame-level `setStyleSheet` for MapLayerTree border/bg
- Title label: `setObjectName("MapDockTitle")`; remove title's font setStyleSheet if QSS covers
- Margins: `tokens.PANEL_PADDING` / spacing `tokens.SPACE_2`
- Tree: keep `MapLayerTreeWidget`; **remove or thin** local tree setStyleSheet if global covers border

`map_attribute_table.py`: same pattern for `MapAttributeTable` / title / table widget.

- [ ] **Step 3:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_map_layer_tree.py tests/test_map_attribute_table.py tests/test_mapping_page.py -q
```

Create missing test files if tests were new-only.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: unify mapping layer tree and attribute dock chrome"
```

---

### Task 4: Canvas host, chrome, mapping_page spacing

**Files:** `map_canvas_panel.py`, `map_chrome_panel.py`, `map_edit_view.py`, `mapping_page.py`

- [ ] **Step 1–3:**

`map_canvas_panel.py`:

- Keep objectName `MapCanvasPanel`
- Remove frame-level border setStyleSheet if QSS covers
- `empty_label.setObjectName("EmptyStateLabel")` if not set; drop redundant color stylesheet

`map_chrome_panel.py`:

- Ensure objectName `MapChromePanel` (set if missing)
- Remove duplicate frame border QSS when global applies

`map_edit_view.py`:

```python
self.setObjectName("MapEditView")  # if not already
```

`mapping_page.py`:

```python
outer.setSpacing(tokens.SPACE_2)
mid.setSpacing(tokens.SPACE_2)
preview_layout.setSpacing(tokens.SPACE_2)
```

- [ ] **Step 4:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_map_canvas_panel.py tests/test_map_chrome_panel.py tests/test_mapping_page.py tests/test_mapping_integration.py -q
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: denser mapping page spacing and canvas dock chrome"
```

---

### Task 5: StatusBar coordinate styling

**Files:** `status_bar.py`, tests

- [ ] **Step 1: Test**

```python
def test_status_coord_label_object_name(qtbot):
    from paleo_workbench.ui.status_bar import StatusBar
    bar = StatusBar()
    qtbot.addWidget(bar)
    assert bar.coord_label.objectName() == "StatusCoordLabel"
```

- [ ] **Step 2: Implement**

```python
self.coord_label.setObjectName("StatusCoordLabel")
layout.setSpacing(tokens.SPACE_2)
layout.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
# optional: QFrame separator before coord_label
```

Import tokens. Do not change `set_project_name` text format.

- [ ] **Step 3:** `pytest tests/test_status_bar.py` (create if needed) + app_shell if it touches status

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: style status bar coordinate zone"
```

---

### Task 6: Full suite + docs

- [ ] **Step 1:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Fix polish-only failures.

- [ ] **Step 2:** Update `task_plan.md` Phase 20 complete; test count; links to design + plan.  
- [ ] **Step 3:** Update `progress.md` session log.  
- [ ] **Step 4:**

```bash
git commit -m "docs: record Phase 20 mapping GIS shell polish delivery"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Mapping/status QSS | 1 |
| Toolbar separators, no reorder | 2 |
| Layer tree + attribute docks | 3 |
| Canvas/chrome/page spacing | 4 |
| StatusCoordLabel | 5 |
| Acceptance / docs | 6 |

**Logic freeze:** No signal renames, no topology/save changes.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-mapping-gis-shell-polish.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task  
2. **Inline Execution** — this session with checkpoints  

Which approach?
