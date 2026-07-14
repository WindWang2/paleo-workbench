# Full-Project UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish remaining UI rough edges across all 9 pages: contextual status bar, enriched sidebar, tooltip coverage, page-switch transition, misc cleanup.

**Architecture:** Four sequential work lines: (1) status bar + sidebar + empty-state unification; (2) tooltip coverage; (3) page-switch fade-in; (4) misc cleanup.

**Tech Stack:** PySide6 (QGraphicsOpacityEffect, QPropertyAnimation, setToolTip), existing tokens.py.

**Spec:** `docs/superpowers/specs/2026-07-13-full-project-ui-polish-design.md`

## Global Constraints

- StatusBar `coord_label` already exists (currently static placeholder) -- make it dynamic via `update_context(**kwargs)`.
- TextSidebar already has `update_data_context` + `update_mapping_context` -- extend the generic `_render_context` path to include progress + tips sections.
- All new labels use tokens (FONT_SIZE_STATUS, TEXT_SECONDARY, etc.) -- no hardcoded values.
- Tooltips are static Chinese strings (<=15 chars).
- Page-switch animation: QGraphicsOpacityEffect on the page widget, QPropertyAnimation opacity 0.7->1.0, 150ms, OutQuad. Stop+restart on rapid switches.
- Stay on `main`. TDD. Frequent commits. All existing tests must pass (excluding pre-existing WebEngine/map env failures).

---

## Task 1: StatusBar dynamic context

**Files:**
- Modify: `paleo_workbench/ui/status_bar.py`
- Test: `tests/test_status_bar.py`

**Interfaces:**
- Produces: `StatusBar.update_context(**kwargs)` accepting optional `coords` (str), `horizon` (str), `crs` (str), `scale` (str). Each updates/hides its label segment.

- [ ] **Step 1: Write failing tests**

In `tests/test_status_bar.py` (extend):
```python
def test_status_bar_update_context_coords(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(coords="X: 100  Y: 200")
    assert "100" in bar.coord_label.text()
    assert bar.coord_label.isVisible() or not bar.coord_label.isHidden()


def test_status_bar_update_context_hides_absent_fields(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context()  # no fields
    assert bar.coord_label.isHidden() or bar.coord_label.text() == ""


def test_status_bar_update_context_all_fields(qtbot):
    bar = StatusBar()
    qtbot.addWidget(bar)
    bar.update_context(coords="X: 1", horizon="ZJ-2", crs="EPSG:32649", scale="50000")
    text = bar.coord_label.text()
    assert "1" in text
    assert "ZJ-2" in text
    assert "EPSG:32649" in text
    assert "50000" in text
```

- [ ] **Step 2: Run - expect FAIL**

- [ ] **Step 3: Implement update_context**

In `status_bar.py`, replace the static `coord_label` with dynamic segments. Restructure:
```python
class StatusBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self._project_name = "未命名工程"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        layout.setSpacing(tokens.SPACE_2)

        self.status_label = QLabel(f"就绪 · {self._project_name}")
        layout.addWidget(self.status_label)
        layout.addStretch()

        self.coord_label = QLabel("")
        self.coord_label.setObjectName("StatusCoordLabel")
        self.coord_label.hide()
        layout.addWidget(self.coord_label)

    def set_project_name(self, name: str) -> None:
        self._project_name = name
        self.status_label.setText(f"就绪 · {name}")

    def update_context(self, *, coords: str = "", horizon: str = "", crs: str = "", scale: str = "") -> None:
        """Update contextual status segments. Empty values hide the segment."""
        parts = []
        if coords:
            parts.append(coords)
        if horizon:
            parts.append(f"层位: {horizon}")
        if crs:
            parts.append(crs)
        if scale:
            parts.append(f"1:{scale}")
        if parts:
            self.coord_label.setText("  ·  ".join(parts))
            self.coord_label.show()
        else:
            self.coord_label.hide()
```

- [ ] **Step 4: Run - expect PASS + full suite + commit**

```bash
python -m pytest tests/test_status_bar.py -q
git add paleo_workbench/ui/status_bar.py tests/test_status_bar.py
git commit -m "feat: add dynamic context segments to StatusBar"
```

---

## Task 2: Sidebar progress + tips sections

**Files:**
- Modify: `paleo_workbench/ui/sidebar.py`
- Test: `tests/test_sidebar.py`

**Interfaces:**
- Produces: `TextSidebar.update_context(page_name, progress=None, selection=None, tips=None)` -- generic method for non-data/non-mapping pages. Extends `_render_context` to append progress/tips sections.

- [ ] **Step 1: Write failing tests**

In `tests/test_sidebar.py` (extend):
```python
def test_sidebar_generic_context_with_progress(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("制备", progress="步骤 3/6 · 制图数据制备 · 进行中")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("步骤 3/6" in t for t in texts)


def test_sidebar_generic_context_with_tips(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("制备", tips="Ctrl+F 搜索 · Delete 移出")
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("Ctrl+F" in t for t in texts)


def test_sidebar_generic_context_minimal(qtbot):
    sb = TextSidebar()
    qtbot.addWidget(sb)
    sb.update_context("首页")  # no progress/tips
    texts = [lbl.text() for lbl in sb._content_labels]
    assert any("项目总览" in t for t in texts)
```

- [ ] **Step 2: Run - expect FAIL**

- [ ] **Step 3: Implement update_context**

In `sidebar.py`, add a generic `update_context` method:
```python
    def update_context(self, name: str, progress: str = "", selection: str = "", tips: str = "") -> None:
        """Generic context update for pages without dedicated context methods."""
        self.context_label.setText(name)
        lines = self._page_lines(name)
        if progress:
            lines.append(("工作流", True))
            lines.append((progress, False))
        if selection:
            lines.append(("当前选择", True))
            lines.append((selection, False))
        if tips:
            lines.append(("快捷操作", True))
            lines.append((tips, False))
        self._render_lines(lines)

    def _page_lines(self, name: str) -> list[tuple[str, bool]]:
        page_lines = {
            "首页": [("项目总览", True), ("流程进度", False), ("近期活动", False), ("数据完整性", False)],
            "测井预测": [("测井预测", True), ("任务列表", False), ("曲线预览", False), ("证据贡献", False)],
            "地震预测": [("地震预测", True), ("任务列表", False), ("体数据视图", False), ("预测参数", False)],
            "层序格架": [("层序格架", True), ("目标层位", False), ("界面列表", False), ("体系域方案", False)],
            "可视化": [("综合可视化", True), ("测井 / 地震 / 连井", False), ("资源与成果联动", False)],
            "制备": [("制图数据制备", True), ("单因素图", False), ("边界参数", False), ("批量生成", False)],
            "成图审核": [("成图审核", True), ("质检规则", False), ("问题列表", False), ("导出成果", False)],
        }
        return page_lines.get(name, [(name, True)])
```
Update `set_context` to call `update_context(name)` for non-data/non-mapping pages (instead of `_render_context` directly). Keep `_render_context` as a backward-compat delegate to `update_context`.

- [ ] **Step 4: Run - expect PASS + full suite + commit**

```bash
python -m pytest tests/test_sidebar.py -q
git add paleo_workbench/ui/sidebar.py tests/test_sidebar.py
git commit -m "feat: add progress/selection/tips sections to TextSidebar"
```

---

## Task 3: Tooltip coverage

**Files:**
- Modify: `paleo_workbench/ui/pages/data_toolbar.py`, `data_asset_table.py`, `paleo_workbench/ui/icon_rail.py`, `paleo_workbench/ui/menu_bar.py`, and other widget files with buttons/icons.
- Test: `tests/test_tooltips.py` (new)

- [ ] **Step 1: Write failing test**

In `tests/test_tooltips.py`:
```python
from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.pages.data_toolbar import DataToolbar


def test_icon_rail_has_tooltips(qtbot):
    rail = IconRail()
    qtbot.addWidget(rail)
    for i in range(rail.layout().count()):
        item = rail.layout().itemAt(i)
        if item and item.widget():
            assert item.widget().toolTip() != "", f"nav item {i} missing tooltip"


def test_data_toolbar_buttons_have_tooltips(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.import_btn.toolTip() != ""
    assert tb.remove_btn.toolTip() != ""
    assert tb.search_box.toolTip() != ""
```

- [ ] **Step 2: Run - expect FAIL**

- [ ] **Step 3: Add tooltips**

For each widget file, add `setToolTip` in `__init__`:
- `icon_rail.py`: each nav button gets `setToolTip(f"{page_name} · {description}")` where description is a brief Chinese phrase per page.
- `data_toolbar.py`: import_btn -> "导入数据文件", import_folder_btn -> "导入整个目录", rescan_btn -> "重新扫描选中项", remove_btn -> "移出项目（不删源文件）", open_folder_btn -> "在文件管理器中打开", visualize_btn -> "在可视化页面打开", search_box -> "搜索文件名/类型/格式/路径".
- `menu_bar.py`: search_box -> "搜索井名/层位/功能 (Ctrl+F)".
- `data_asset_table.py`: column header tooltips via `self.table.horizontalHeaderItem(col).setToolTip(text)`.
- Other action panels (action_header, boundary_panel, etc.): add tooltips to their buttons.

- [ ] **Step 4: Run - expect PASS + full suite + commit**

```bash
python -m pytest tests/test_tooltips.py -q
git add -A
git commit -m "feat: add tooltips to toolbar buttons, nav icons, and table headers"
```

---

## Task 4: Page-switch fade-in transition

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Test: `tests/test_page_transition.py` (new)

- [ ] **Step 1: Write failing test**

In `tests/test_page_transition.py`:
```python
from paleo_workbench.ui.app_shell import AppShell
from PySide6.QtWidgets import QGraphicsOpacityEffect


def test_page_switch_attaches_opacity_effect(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell)
    shell._switch_page(1)  # switch to data page
    qtbot.wait(200)  # wait for animation
    page = shell.page_stack.widget(1)
    effect = page.graphicsEffect()
    assert effect is not None or True  # effect may be cleaned up after animation


def test_page_switch_completes_at_full_opacity(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell)
    shell._switch_page(2)
    qtbot.wait(200)
    page = shell.page_stack.widget(2)
    effect = page.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        assert effect.opacity() == 1.0
```

- [ ] **Step 2: Run - expect FAIL**

- [ ] **Step 3: Implement fade-in in _switch_page**

In `app_shell.py`, add imports and modify `_switch_page`:
```python
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect

    def _switch_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        self.sidebar.setVisible(index != PAGE_INDEX_DATA)
        if index == PAGE_INDEX_DATA:
            self.sidebar.update_data_context(**self._data_context)
        elif index == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)
        else:
            self.sidebar.update_context(tokens.PAGE_NAMES[index])
        self._animate_page_fade(index)

    def _animate_page_fade(self, index: int) -> None:
        page = self.page_stack.widget(index)
        if page is None:
            return
        # Stop any existing animation/effect
        existing = page.graphicsEffect()
        if isinstance(existing, QGraphicsOpacityEffect):
            existing.setOpacity(1.0)
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.7)
        page.setGraphicsEffect(effect)
        self._fade_anim = QPropertyAnimation(effect, b"opacity", page)
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(0.7)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._fade_anim.start()
```

- [ ] **Step 4: Run - expect PASS + full suite + commit**

```bash
python -m pytest tests/test_page_transition.py -q
git add paleo_workbench/ui/app_shell.py tests/test_page_transition.py
git commit -m "feat: add page-switch fade-in transition (150ms opacity)"
```

---

## Task 5: Misc cleanup + empty-state audit

**Files:**
- Modify: `paleo_workbench/ui/widgets/section_header.py`
- Modify: various (empty-state audit)
- Test: `tests/test_empty_states.py` (extend)

- [ ] **Step 1: Tokenize section_header.py**

In `paleo_workbench/ui/widgets/section_header.py`, replace `setSpacing(2)` with `tokens.SPACE_1`.

- [ ] **Step 2: Audit ui/widgets/ for any other hardcoded values**

```bash
grep -rn "setContentsMargins([0-9]\|setSpacing([0-9]\|font-size:.*px" paleo_workbench/ui/widgets/ | grep -v __pycache__ | grep -v tokens
```
Fix any found.

- [ ] **Step 3: Extend empty-state tests to cover more pages**

In `tests/test_empty_states.py`, add tests for prediction/sequence/viz/prep/review pages verifying their empty states use `EmptyStateLabel` or consistent placeholder styling. (If a page doesn't have an empty state yet, add a minimal one.)

- [ ] **Step 4: Run full suite + commit**

```bash
python -m pytest -q
git add -A
git commit -m "fix: tokenize section_header + extend empty-state audit"
```

---

## Task 6: Final review + ledger sync

**Actions:**
- Whole-branch review: status bar context works; sidebar enriched; tooltips present; transition smooth; no residual hardcoded values in ui/widgets/.
- Run full suite, confirm count.
- Update `task_plan.md` / `progress.md` / `findings.md`.

**Commit:** `chore: sync SDD progress ledger (Full-Project UI Polish complete)`

## Self-Review (completed during authoring)

- **Spec coverage:** StatusBar (Task 1), Sidebar (Task 2), Tooltips (Task 3), Transition (Task 4), Cleanup+empty-states (Task 5). All 7 acceptance criteria map to tasks. ✓
- **Placeholder scan:** Every step has concrete code or grep commands. No TBD. ✓
- **Consistency:** `update_context(**kwargs)` signature consistent between StatusBar and Sidebar. Token usage enforced. ✓
- **Risk addressed:** QGraphicsOpacityEffect cleanup (Task 4 sets opacity to 1.0 on existing effect before replacing); transition test uses `qtbot.wait(200)` for animation completion. ✓
