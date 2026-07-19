# 数据页信息侧栏移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在数据页隐藏重复的全局信息侧栏，让资源树、文件列表和预览区域使用完整的可用宽度。

**Architecture:** `AppShell` 是全局 `TextSidebar` 的唯一布局所有者，因此页面切换时根据页面索引切换侧栏可见性即可。数据上下文仍按原有信号更新；Qt 隐藏控件后会从 `QHBoxLayout` 中释放其固定宽度，切换到其他页面时再显示并渲染对应上下文。

**Tech Stack:** Python 3、PySide6、pytest、pytest-qt。

## Global Constraints

- 仅在 `PAGE_INDEX_DATA` 隐藏 `TextSidebar`；其他页面保留现有侧栏。
- 不改变资源统计、当前选择、导入、重扫、打开目录或预览逻辑。
- 切换回其他页面必须恢复侧栏并显示对应页面上下文。

---

### Task 1: 按页面切换侧栏可见性

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py:84-91`
- Modify: `tests/test_app_shell.py`

**Interfaces:**
- Consumes: `PAGE_INDEX_DATA`、`self.sidebar: TextSidebar` 与 `IconRail.page_changed`。
- Produces: `AppShell._switch_page(index: int) -> None` 在数据页调用 `self.sidebar.setVisible(False)`，其他页调用 `self.sidebar.setVisible(True)`。

- [x] **Step 1: 写入失败的页面切换测试**

在 `tests/test_app_shell.py` 增加：

```python
def test_app_shell_hides_sidebar_on_data_page_and_restores_on_navigation(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)

    shell.icon_rail.nav_buttons[1].click()
    assert shell.page_stack.currentIndex() == PAGE_INDEX_DATA
    assert shell.sidebar.isHidden()

    shell.icon_rail.nav_buttons[4].click()
    assert shell.page_stack.currentIndex() == 4
    assert not shell.sidebar.isHidden()
    assert shell.sidebar.context_label.text() == tokens.PAGE_NAMES[4]
```

- [x] **Step 2: 运行测试，确认改动前失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_app_shell.py::test_app_shell_hides_sidebar_on_data_page_and_restores_on_navigation -q`

Expected: FAIL，因为当前 `_switch_page` 从不隐藏 `self.sidebar`。

- [x] **Step 3: 在应用壳层实施最小可见性切换**

在 `paleo_workbench/ui/app_shell.py` 的 `_switch_page` 中，在 `setCurrentIndex` 后加入：

```python
self.sidebar.setVisible(index != PAGE_INDEX_DATA)
```

保留现有的数据、编图与其他页面上下文更新分支，确保恢复显示的侧栏仍接收正确内容。

- [x] **Step 4: 运行定向测试，确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_app_shell.py::test_app_shell_hides_sidebar_on_data_page_and_restores_on_navigation -q`

Expected: PASS。

- [x] **Step 5: 运行关联回归测试**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py -q`

Expected: 侧栏上下文测试与新的数据页隐藏/恢复测试全部通过。若无音频后端导致 `AppShell` 测试环境阻塞，单独运行新测试并记录该已知环境限制。

- [x] **Step 6: 提交实现**

```bash
git add paleo_workbench/ui/app_shell.py tests/test_app_shell.py
git commit -m "feat: hide sidebar on data page"
```
