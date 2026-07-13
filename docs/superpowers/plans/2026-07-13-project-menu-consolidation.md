# 工程操作并入菜单栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将工程操作收进“工程与文件”菜单，并移除独立工程工具栏以释放一整行空间。

**Architecture:** `MenuBar` 承担菜单、搜索框和五个语义信号，窗口仍持有项目生命周期处理器。`AppShell` 不再创建 `HeaderToolbar`，壳体重建后由窗口重新连接新 `MenuBar` 的信号。

**Tech Stack:** Python 3、PySide6、pytest、pytest-qt。

## Global Constraints

- 顶栏只能保留一行；搜索框位于 `MenuBar` 的右侧。
- “工程与文件”菜单项固定为：新建工程、打开工程、打开样例工程、保存工程、分隔线、工程属性。
- 不新增“视图、工具、帮助”的功能。
- 不保留 `HeaderToolbar` 兼容壳或公共导出。

---

### Task 1: 将工程菜单和搜索框实现为 MenuBar 的职责

**Files:**
- Modify: `paleo_workbench/ui/menu_bar.py`
- Modify: `paleo_workbench/ui/tokens.py:141-186`
- Modify: `tests/test_menu_bar.py`
- Delete: `tests/test_header_toolbar.py`

**Interfaces:**
- Produces: `MenuBar.new_project_requested`, `open_project_requested`, `open_sample_project_requested`, `save_project_requested` 和 `properties_requested`（均为零参数 `Signal`）。
- Produces: `MenuBar.project_menu_button: QPushButton`、`project_menu: QMenu`、五个命名动作属性及 `search_box: QLineEdit`，供壳体和测试使用。

- [ ] **Step 1: 写出菜单布局与信号的失败测试**

```python
def test_project_menu_contains_actions_and_search(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    assert bar.project_menu_button.text() == "工程与文件"
    assert [action.text() for action in bar.project_menu.actions()] == [
        "新建工程", "打开工程", "打开样例工程", "保存工程", "", "工程属性",
    ]
    assert bar.search_box.objectName() == "SearchBox"


def test_project_menu_actions_emit_semantic_signals(qtbot):
    bar = MenuBar()
    qtbot.addWidget(bar)

    cases = [
        (bar.new_project_action, bar.new_project_requested),
        (bar.open_project_action, bar.open_project_requested),
        (bar.open_sample_project_action, bar.open_sample_project_requested),
        (bar.save_project_action, bar.save_project_requested),
        (bar.properties_action, bar.properties_requested),
    ]
    for action, signal in cases:
        with qtbot.waitSignal(signal, timeout=1000):
            action.trigger()
```

- [ ] **Step 2: 运行失败测试并确认当前缺少菜单接口**

Run: `pytest tests/test_menu_bar.py -q`

Expected: FAIL，提示 `MenuBar` 没有 `project_menu_button`、动作或工程操作信号。

- [ ] **Step 3: 最小实现菜单、动作、搜索和信号**

```python
class MenuBar(QFrame):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()

    def _add_project_action(self, text: str, signal: Signal) -> QAction:
        action = self.project_menu.addAction(text)
        action.triggered.connect(signal)
        return action
```

在 `__init__` 中创建 `QPushButton("工程与文件")` 与其 `QMenu`，按固定顺序保存五个 `QAction` 属性并在保存动作后调用 `addSeparator()`；将原来的其余三个标签保留在同一水平布局中。创建原 `HeaderToolbar` 的 `SearchBox`（相同占位文字与最大宽度），在 `layout.addStretch()` 后添加它。删除 `QFrame#HeaderToolbar` 样式，仅为 `MenuBar` 内的工程菜单按钮添加与普通菜单文字一致的轻量样式，不改变 `SearchBox` 样式。

- [ ] **Step 4: 运行菜单测试并确认通过**

Run: `pytest tests/test_menu_bar.py -q`

Expected: PASS。

- [ ] **Step 5: 删除已废弃工具栏测试并提交菜单实现**

Run: `git add paleo_workbench/ui/menu_bar.py paleo_workbench/ui/tokens.py tests/test_menu_bar.py tests/test_header_toolbar.py && git commit -m "feat: move project actions into menu"`

Expected: commit 创建成功；已删除的测试由暂存删除记录。

### Task 2: 移除 HeaderToolbar，并将窗口连接切换到 MenuBar

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py:1-52`
- Modify: `paleo_workbench/app.py:188-207`
- Modify: `paleo_workbench/ui/__init__.py:3-20`
- Delete: `paleo_workbench/ui/header_toolbar.py`
- Modify: `tests/test_app_shell.py:10-20`
- Modify: `tests/test_project_lifecycle.py:220-238`
- Modify: `tests/test_ui_exports.py:8-17`

**Interfaces:**
- Consumes: Task 1 中 `MenuBar` 的五个工程操作信号和 `search_box`。
- Produces: `AppShell` 不含 `header_toolbar` 属性；`PaleoWorkbenchWindow._wire_menu_bar()` 将新壳体 `menu_bar` 的信号连接到现有处理器。

- [ ] **Step 1: 将壳体和重建连接测试改为新接口**

```python
def test_app_shell_assembles_all_zones(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert shell.menu_bar is not None
    assert not hasattr(shell, "header_toolbar")
    assert shell.menu_bar.search_box.objectName() == "SearchBox"


def test_project_menu_signals_wired_after_refresh(qtbot, monkeypatch):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    counter = {"n": 0}
    monkeypatch.setattr(window, "_on_new_project", lambda: counter.__setitem__("n", counter["n"] + 1))

    window.new_project("After Refresh")
    window.app_shell.menu_bar.new_project_requested.emit()

    assert counter["n"] == 1
```

同时从 UI 导出测试中移除 `HeaderToolbar`，并删除对该模块的独立导入。

- [ ] **Step 2: 运行受影响测试并确认壳体仍在引用 HeaderToolbar**

Run: `pytest tests/test_app_shell.py tests/test_project_lifecycle.py::test_project_menu_signals_wired_after_refresh tests/test_ui_exports.py -q`

Expected: FAIL，提示 `AppShell` 仍有工具栏属性或窗口还在 `_wire_toolbar` 中读取它。

- [ ] **Step 3: 最小迁移壳体、窗口连接和公共导出**

```python
# paleo_workbench/ui/app_shell.py
self.menu_bar = MenuBar()
outer.addWidget(self.menu_bar)

# paleo_workbench/app.py
def _wire_menu_bar(self) -> None:
    menu_bar = self.app_shell.menu_bar
    menu_bar.new_project_requested.connect(self._on_new_project)
    menu_bar.open_project_requested.connect(self._on_open_project)
    menu_bar.open_sample_project_requested.connect(self._on_open_sample_project)
    menu_bar.save_project_requested.connect(self._on_save_project)
    menu_bar.properties_requested.connect(self._on_properties)
```

从 `AppShell` 删除 `HeaderToolbar` 导入、实例化和布局项；将窗口初始化和 `_refresh_shell()` 中的 `_wire_toolbar()` 调用改名为 `_wire_menu_bar()`。从 `paleo_workbench.ui.__all__` 与 `_EXPORTS` 删除 `HeaderToolbar`，并删除 `paleo_workbench/ui/header_toolbar.py`。

- [ ] **Step 4: 运行受影响测试并确认通过**

Run: `pytest tests/test_menu_bar.py tests/test_app_shell.py tests/test_project_lifecycle.py tests/test_ui_exports.py -q`

Expected: PASS。

- [ ] **Step 5: 静态检查不存在的旧接口并提交迁移**

Run: `rg -n 'HeaderToolbar|header_toolbar|_wire_toolbar' paleo_workbench tests || true`

Expected: 无匹配结果。

Run: `git add paleo_workbench/app.py paleo_workbench/ui/app_shell.py paleo_workbench/ui/__init__.py paleo_workbench/ui/header_toolbar.py tests/test_app_shell.py tests/test_project_lifecycle.py tests/test_ui_exports.py && git commit -m "refactor: remove project toolbar row"`

Expected: commit 创建成功；旧工具栏源文件由暂存删除记录。

### Task 3: 回归验证并进行视觉烟测

**Files:**
- Modify: `docs/superpowers/plans/2026-07-13-project-menu-consolidation.md`（仅勾选完成项）

**Interfaces:**
- Consumes: Task 1 和 Task 2 的菜单接口与壳体迁移。
- Produces: 已记录的自动化验证和手动视觉检查结果。

- [ ] **Step 1: 运行完整相关测试集**

Run: `pytest tests/test_menu_bar.py tests/test_app_shell.py tests/test_project_lifecycle.py tests/test_ui_exports.py -q`

Expected: PASS，且不再收集 `tests/test_header_toolbar.py`。

- [ ] **Step 2: 启动应用进行视觉烟测**

Run: `PYTHONPATH=geo-viz-engine:geo-viz-engine/packages/geoviz_common:geo-viz-engine/packages/geoviz_paleo_map:geo-viz-engine/packages/geoviz_plots:geo-viz-engine/packages/geoviz_seismic:geo-viz-engine/packages/geoviz_well_log:geo-viz-engine/packages/geoviz_cross_well:geo-viz-engine/packages/geoviz_well_tie:geo-viz-engine/packages/geoviz_map python -m paleo_workbench.main`

Expected: 仅有一行顶栏；“工程与文件”菜单包含五项操作；搜索框在右侧；其下直接是主工作区。

- [x] **Step 3: 勾选已完成计划项并提交计划记录**

Run: `git add docs/superpowers/plans/2026-07-13-project-menu-consolidation.md && git commit -m "docs: record project menu verification"`

Expected: commit 创建成功。
