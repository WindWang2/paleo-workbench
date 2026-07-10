# Phase 19 UI Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a demo-ready global visual system: density tokens, richer QSS (buttons/tables/focus), five shared widgets, shell + high-traffic page adoption—without changing business logic.

**Architecture:** Extend `tokens.py` as single source of truth; expand `QSS_TEMPLATE` for paint; add thin `ui/widgets/*` wrappers; apply shell and page margins/objectNames. Prefer global QSS over local `setStyleSheet`.

**Tech Stack:** PySide6, existing `paleo_workbench.ui.tokens`, pytest / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-10-ui-visual-polish-design.md`

---

## File map

| Path | Responsibility |
|------|----------------|
| `paleo_workbench/ui/tokens.py` | Density tokens, interaction colors, expanded QSS |
| `paleo_workbench/ui/widgets/__init__.py` | Export five widgets |
| `paleo_workbench/ui/widgets/panel_card.py` | `PanelCard` |
| `paleo_workbench/ui/widgets/section_header.py` | `SectionHeader` |
| `paleo_workbench/ui/widgets/toolbar_strip.py` | `ToolbarStrip` |
| `paleo_workbench/ui/widgets/empty_state.py` | `EmptyStateLabel` |
| `paleo_workbench/ui/widgets/page_scaffold.py` | `PageScaffold` |
| `paleo_workbench/ui/header_toolbar.py` | Button min heights; use denser chrome |
| `paleo_workbench/ui/sidebar.py` | `PAGE_MARGIN` |
| `paleo_workbench/ui/pages/home_page.py` | Scaffold / margins / spacing |
| `paleo_workbench/ui/pages/map_edit_toolbar.py` | Optional ToolbarStrip wrap or QSS-only density |
| Page files with `setContentsMargins(16,…)` | Switch to `PAGE_MARGIN` |
| `tests/test_tokens.py` | New constants + QSS snippets |
| `tests/test_ui_widgets.py` | Widget construction |
| `task_plan.md` / `progress.md` | Phase 19 delivery note |

---

### Task 1: Density tokens + expanded QSS

**Files:**
- Modify: `paleo_workbench/ui/tokens.py`
- Modify: `tests/test_tokens.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_tokens.py`:

```python
def test_density_tokens():
    assert tokens.SPACE_1 == 4
    assert tokens.SPACE_2 == 8
    assert tokens.SPACE_3 == 12
    assert tokens.SPACE_4 == 16
    assert tokens.PAGE_MARGIN == 12
    assert tokens.PANEL_PADDING == 10
    assert tokens.CONTROL_HEIGHT == 28
    assert tokens.CONTROL_HEIGHT_LG == 32
    assert tokens.HEADER_TOOLBAR_HEIGHT == 36
    assert tokens.FONT_SIZE_TITLE == "13px"
    assert tokens.FONT_WEIGHT_TITLE == "600"


def test_interaction_color_tokens():
    assert tokens.PRIMARY_HOVER == "#2b7cf0"
    assert tokens.PRIMARY_PRESSED == "#1a5fc4"
    assert tokens.PRIMARY_DISABLED == "#a8c4f0"
    assert tokens.FOCUS_RING == tokens.PRIMARY


def test_qss_has_button_states_and_panels():
    qss = tokens.QSS_TEMPLATE
    assert "PrimaryButton:hover" in qss or "QPushButton#PrimaryButton:hover" in qss
    assert "PrimaryButton:pressed" in qss or "QPushButton#PrimaryButton:pressed" in qss
    assert "PrimaryButton:disabled" in qss or "QPushButton#PrimaryButton:disabled" in qss
    assert "PanelCard" in qss
    assert "ToolbarStrip" in qss
    assert "EmptyStateLabel" in qss
    assert "QHeaderView::section" in qss
    assert "QTableView" in qss or "QTableWidget" in qss
```

Also **update** existing:

```python
# test_dimension_constants_exist
assert tokens.HEADER_TOOLBAR_HEIGHT == 36  # was 38
```

- [ ] **Step 2: Run — expect FAIL**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tokens.py::test_density_tokens tests/test_tokens.py::test_interaction_color_tokens tests/test_tokens.py::test_qss_has_button_states_and_panels -v
```

- [ ] **Step 3: Implement tokens**

Add near dimension constants in `tokens.py` (after existing height constants):

```python
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
PAGE_MARGIN = 12
PANEL_PADDING = 10
CONTROL_HEIGHT = 28
CONTROL_HEIGHT_LG = 32
# Change:
HEADER_TOOLBAR_HEIGHT = 36  # was 38

FONT_SIZE_TITLE = "13px"
FONT_WEIGHT_TITLE = "600"

PRIMARY_HOVER = "#2b7cf0"
PRIMARY_PRESSED = "#1a5fc4"
PRIMARY_DISABLED = "#a8c4f0"
FOCUS_RING = PRIMARY
```

Replace / extend button rules and append table/panel/input rules in `QSS_TEMPLATE`. Minimal required content:

```python
# Inside QSS_TEMPLATE f-string — replace Primary/Secondary blocks with:

QPushButton#PrimaryButton {{
    background: {PRIMARY}; color: #ffffff; border: none;
    border-radius: {RADIUS_BUTTON}px;
    padding: 4px 14px;
    min-height: {CONTROL_HEIGHT_LG}px;
}}
QPushButton#PrimaryButton:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#PrimaryButton:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton#PrimaryButton:disabled {{
    background: {PRIMARY_DISABLED}; color: #ffffff;
}}
QPushButton#PrimaryButton:focus {{
    border: 1px solid {FOCUS_RING};
}}
QPushButton#SecondaryButton {{
    background: {BG_SIDEBAR}; color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 4px 12px;
    min-height: {CONTROL_HEIGHT}px;
}}
QPushButton#SecondaryButton:hover {{ background: {BG_SEARCH}; }}
QPushButton#SecondaryButton:pressed {{ background: {BORDER_LIGHT}; }}
QPushButton#SecondaryButton:disabled {{
    color: {TEXT_SECONDARY}; border-color: {BORDER};
}}
QPushButton#SecondaryButton:checked {{
    background: {BG_SEARCH}; border-color: {PRIMARY}; color: {TEXT_PRIMARY};
}}
QPushButton#SecondaryButton:focus {{
    border: 1px solid {FOCUS_RING};
}}
QLineEdit#SearchBox {{
    background: {BG_SEARCH}; border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px; padding: 4px 8px; color: {TEXT_PRIMARY};
    min-height: {CONTROL_HEIGHT}px;
}}
QLineEdit#SearchBox:focus {{ border: 1px solid {FOCUS_RING}; }}
QLineEdit {{
    min-height: {CONTROL_HEIGHT}px;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px 8px;
    background: {BG_SIDEBAR};
}}
QLineEdit:focus {{ border: 1px solid {FOCUS_RING}; }}
QComboBox {{
    min-height: {CONTROL_HEIGHT}px;
    border: 1px solid {BORDER};
    border-radius: {RADIUS_BUTTON}px;
    padding: 2px 8px;
    background: {BG_SIDEBAR};
}}
QComboBox:focus {{ border: 1px solid {FOCUS_RING}; }}
QHeaderView::section {{
    background: {BG_HEADER};
    color: {TEXT_PRIMARY};
    border: none;
    border-bottom: 1px solid {BORDER_STRONG};
    border-right: 1px solid {BORDER};
    padding: 4px 8px;
    font-weight: 600;
    min-height: {CONTROL_HEIGHT}px;
}}
QTableView, QTableWidget {{
    gridline-color: {BORDER};
    selection-background-color: #d6e6fb;
    selection-color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    background: {BG_SIDEBAR};
}}
QFrame#PanelCard {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ToolbarStrip {{
    background: {BG_SIDEBAR};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}
QLabel#EmptyStateLabel {{
    color: {TEXT_SECONDARY};
    font-size: {FONT_SIZE_BASE};
}}
```

Keep existing MenuBar / HeaderToolbar / IconRail / TextSidebar / StatusBar rules; they already use height tokens.

- [ ] **Step 4: Pass tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_tokens.py -q
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/tokens.py tests/test_tokens.py
git commit -m "feat: density tokens and richer global QSS for UI polish"
```

---

### Task 2: Five shared widgets

**Files:**
- Create: `paleo_workbench/ui/widgets/__init__.py`
- Create: `paleo_workbench/ui/widgets/panel_card.py`
- Create: `paleo_workbench/ui/widgets/section_header.py`
- Create: `paleo_workbench/ui/widgets/toolbar_strip.py`
- Create: `paleo_workbench/ui/widgets/empty_state.py`
- Create: `paleo_workbench/ui/widgets/page_scaffold.py`
- Create: `tests/test_ui_widgets.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_ui_widgets.py
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from paleo_workbench.ui import tokens
from paleo_workbench.ui.widgets import (
    EmptyStateLabel,
    PageScaffold,
    PanelCard,
    SectionHeader,
    ToolbarStrip,
)


def test_panel_card_object_name_and_padding(qtbot):
    card = PanelCard(title="标题")
    qtbot.addWidget(card)
    assert card.objectName() == "PanelCard"
    assert card.title_label.text() == "标题"
    # body layout uses PANEL_PADDING
    lay = card.layout()
    m = lay.contentsMargins()
    assert m.left() == tokens.PANEL_PADDING


def test_section_header(qtbot):
    h = SectionHeader("区块", subtitle="说明")
    qtbot.addWidget(h)
    assert h.objectName() == "SectionHeader"
    assert h.title_label.text() == "区块"
    assert h.subtitle_label.text() == "说明"


def test_toolbar_strip(qtbot):
    strip = ToolbarStrip()
    qtbot.addWidget(strip)
    assert strip.objectName() == "ToolbarStrip"
    btn = QPushButton("X")
    strip.add_widget(btn)
    assert strip.layout().count() >= 1


def test_empty_state_label(qtbot):
    lab = EmptyStateLabel("暂无数据")
    qtbot.addWidget(lab)
    assert lab.objectName() == "EmptyStateLabel"
    assert lab.text() == "暂无数据"
    assert lab.alignment() & Qt.AlignmentFlag.AlignCenter


def test_page_scaffold_margins(qtbot):
    page = PageScaffold(title="页面")
    qtbot.addWidget(page)
    assert page.objectName() == "PageScaffold"
    m = page.layout().contentsMargins()
    assert m.left() == tokens.PAGE_MARGIN
    assert m.top() == tokens.PAGE_MARGIN
    body = QLabel("content")
    page.set_body(body)
    assert page.body_widget is body
```

- [ ] **Step 2: Run — FAIL**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_widgets.py -v
```

- [ ] **Step 3: Implement widgets**

`panel_card.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class PanelCard(QFrame):
    """White bordered card with optional title and body layout."""

    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        self._root.setSpacing(tokens.SPACE_2)
        self.title_label = QLabel(title or "")
        self.title_label.setObjectName("SectionHeaderTitle")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE};"
            f" font-weight: {tokens.FONT_WEIGHT_TITLE}; border: none; background: transparent;"
        )
        if title:
            self._root.addWidget(self.title_label)
        else:
            self.title_label.hide()
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(tokens.SPACE_2)
        self._root.addLayout(self.body, 1)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)
```

`section_header.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SectionHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE};"
            f" font-weight: {tokens.FONT_WEIGHT_TITLE};"
        )
        layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};")
        if not subtitle:
            self.subtitle_label.hide()
        layout.addWidget(self.subtitle_label)
```

`toolbar_strip.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QWidget

from paleo_workbench.ui import tokens


class ToolbarStrip(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolbarStrip")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        self._layout.setSpacing(tokens.SPACE_1)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_stretch(self) -> None:
        self._layout.addStretch(1)
```

`empty_state.py`:

```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class EmptyStateLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("EmptyStateLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
```

`page_scaffold.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.widgets.section_header import SectionHeader


class PageScaffold(QWidget):
    def __init__(self, title: str | None = None, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("PageScaffold")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        self._layout.setSpacing(tokens.SPACE_3)
        self.header: SectionHeader | None = None
        if title:
            self.header = SectionHeader(title, subtitle=subtitle)
            self._layout.addWidget(self.header)
        self.body_widget: QWidget | None = None
        self._body_index = self._layout.count()

    def set_body(self, widget: QWidget) -> None:
        if self.body_widget is not None:
            self._layout.removeWidget(self.body_widget)
            self.body_widget.setParent(None)
        self.body_widget = widget
        self._layout.addWidget(widget, 1)
```

`widgets/__init__.py`:

```python
from paleo_workbench.ui.widgets.empty_state import EmptyStateLabel
from paleo_workbench.ui.widgets.page_scaffold import PageScaffold
from paleo_workbench.ui.widgets.panel_card import PanelCard
from paleo_workbench.ui.widgets.section_header import SectionHeader
from paleo_workbench.ui.widgets.toolbar_strip import ToolbarStrip

__all__ = [
    "EmptyStateLabel",
    "PageScaffold",
    "PanelCard",
    "SectionHeader",
    "ToolbarStrip",
]
```

- [ ] **Step 4: Tests pass**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_ui_widgets.py -q
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/widgets tests/test_ui_widgets.py
git commit -m "feat: add shared UI widgets for visual polish"
```

---

### Task 3: Shell chrome density

**Files:**
- Modify: `paleo_workbench/ui/header_toolbar.py` — set button min height via tokens if needed; ensure layout spacing uses `SPACE_2`
- Modify: `paleo_workbench/ui/sidebar.py` — margins `PAGE_MARGIN` (was 16)
- Modify: `paleo_workbench/ui/menu_bar.py` — spacing only if obvious
- Tests: update any height 38 assumptions; `tests/test_header_toolbar.py` still passes

- [ ] **Step 1: Sidebar margin test** (add or extend)

```python
# In tests/test_sidebar.py if exists, else tests/test_app_shell.py
def test_sidebar_uses_page_margin(qtbot):
    from paleo_workbench.ui.sidebar import TextSidebar
    from paleo_workbench.ui import tokens
    side = TextSidebar()
    qtbot.addWidget(side)
    m = side.layout().contentsMargins()
    assert m.left() == tokens.PAGE_MARGIN
```

- [ ] **Step 2–4: Implement + pass + commit**

```bash
git commit -m "feat: denser AppShell chrome margins and toolbar spacing"
```

**Header toolbar:** In `__init__` after creating buttons, optionally:

```python
for btn in self.buttons:
    btn.setMinimumHeight(tokens.CONTROL_HEIGHT if btn.objectName() != "PrimaryButton" else tokens.CONTROL_HEIGHT_LG)
```

Import tokens in `header_toolbar.py`.

Do **not** change signals or button order.

---

### Task 4: High-traffic pages (home, data toolbar, mapping toolbar)

**Files:**
- Modify: `paleo_workbench/ui/pages/home_page.py` — margins/spacing to `PAGE_MARGIN` / `SPACE_3`/`SPACE_4`
- Modify: `paleo_workbench/ui/pages/data_toolbar.py` — denser spacing; ensure import/secondary buttons keep objectNames
- Modify: `paleo_workbench/ui/pages/map_edit_toolbar.py` — min heights / spacing via tokens; keep all signals
- Optionally wrap home cards' outer frames with objectName PanelCard **only if** they already look like cards and local QSS duplicates border — prefer changing objectName + stripping duplicate border QSS

**Home page example:**

```python
from paleo_workbench.ui import tokens

layout.setContentsMargins(
    tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
)
layout.setSpacing(tokens.SPACE_3)
bottom.setSpacing(tokens.SPACE_3)
```

- [ ] **Step 1: Tests** — home page still constructs; existing home tests pass; no new behavior tests required beyond margins if covered by smoke

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_home_page.py tests/test_home_integration.py tests/test_data_toolbar.py tests/test_map_edit_toolbar.py -q
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: apply density tokens on home, data, mapping chrome"
```

---

### Task 5: Page margin sweep (remaining pages)

**Files** (all pages using `setContentsMargins(16, 16, 16, 16)` under `paleo_workbench/ui/pages/` and any shell pages):

Use:

```python
from paleo_workbench.ui import tokens
layout.setContentsMargins(
    tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
)
```

Typical list (verify with grep):

- `well_log_prediction_page.py`
- `seismic_prediction_page.py`
- `preparation_page.py`
- `review_export_page.py` (or equivalent)
- `sequence_framework_page.py`
- `visualization_page.py`
- `mapping_page.py`
- `data_page.py` if 16

**Do not** change inner panel margins that are intentionally tight (attribute tables).

- [ ] **Step 1:**

```bash
rg -n "setContentsMargins\(16" paleo_workbench/ui --glob "*.py"
```

Replace each page-outer occurrence.

- [ ] **Step 2:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_well_log_prediction_page.py tests/test_seismic_prediction_page.py tests/test_mapping_page.py tests/test_visualization_page.py tests/test_preparation_page.py tests/test_review_export_page.py tests/test_sequence_framework_page.py -q
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: unify page outer margins to PAGE_MARGIN"
```

---

### Task 6: Safe local QSS cleanup + EmptyState adoption samples

**Goal:** Remove **only** local styles that **fully duplicate** global card border for frames that can become `PanelCard` objectName, and use `EmptyStateLabel` in 2+ high-visibility empty states.

**Safe targets (examples — verify before edit):**

1. Frames with only `background: white; border: 1px solid BORDER; border-radius: RADIUS_CARD` → `setObjectName("PanelCard")` and delete that block if no other rules.  
2. Empty labels that only set secondary color + center → replace with `EmptyStateLabel` in:
   - `WellLogCanvasPanel.empty_label` **or** keep QLabel but `setObjectName("EmptyStateLabel")` (prefer objectName to avoid layout risk)
   - Same for `SeismicViewPanel.empty_label`

**Prefer objectName reassignment over widget class change** when tests hold references to `empty_label` as QLabel.

```python
self.empty_label.setObjectName("EmptyStateLabel")
# remove local color stylesheet if global covers it
```

- [ ] **Step 1:** Grep and fix 3–8 clear duplicates  
- [ ] **Step 2:** Focused panel tests + full suite  
- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: adopt PanelCard/EmptyState objectNames; drop duplicate QSS"
```

---

### Task 7: Full suite + docs

- [ ] **Step 1:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Expected: all pass (baseline ~535+). Fix only polish-related expectation breaks.

- [ ] **Step 2:** Update `task_plan.md` — Phase 19 complete; test count; link design + plan.  
- [ ] **Step 3:** Update `progress.md` session log.  
- [ ] **Step 4: Commit**

```bash
git commit -m "docs: record Phase 19 UI visual polish delivery"
```

- [ ] **Step 5: Manual note** (in progress.md): demo walkthrough checklist from spec.

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| Density tokens SPACE/PAGE_MARGIN/CONTROL_* | 1 |
| PRIMARY_HOVER/PRESSED/DISABLED/FOCUS | 1 |
| Button/table/panel QSS | 1 |
| Five widgets | 2 |
| Shell chrome | 3 |
| High-traffic pages | 4 |
| Page margins | 5 |
| Local QSS cleanup + empty states | 6 |
| Acceptance / docs | 7 |

**Out of plan (by design):** dark mode, geo-viz internals, full component library, screenshot CI.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-ui-visual-polish.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans checkpoints  

Which approach?
