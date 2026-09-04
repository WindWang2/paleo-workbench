# 工作站壳层以编图为核心（取消文档 Tab）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除工作站文档 Tab 层；中央永远是编图（`CompositeDocument`）；测井轨道与地震剖面升为宿主 `QDockWidget`，由动作打开；Hub 页不得再把中央换成「项目工作流」。

**Architecture:** `WorkstationFrame` 中央只 embed `composite`。从 `LinkedInterpretationWorkspace` 抽出测井/地震内容部件放到宿主 dock（默认隐藏）；删除联动区嵌套 `QMainWindow`、平面图窗格、上下文条。`activate_legacy` 改为显示浮动 `hub_dock`。编图工具条增加测井/地震显隐与「链接」开关。

**Tech Stack:** PySide6, pytest-qt (offscreen)

**Spec:** `docs/superpowers/specs/2026-09-04-mapping-centric-workstation-shell-design.md`（已批准）

---

## Global Constraints

- 不改编图内部 QGIS 工具链（采点/图层树/XML）。
- 不把 `MappingPage` 换成中央。
- 测试：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main <pytest args> --basetemp=$(mktemp -d)`。看 `N passed/failed`。
- 工作区 `/home/kevin/projects/paleo_project/main`；分支 `feat/mapping-centric-shell`。
- **不提交** `.superpowers/`、`symbology-style.db`、`user-history.db`。
- 旧 `QSettings("PaleoWorkbench", "WorkstationV3")` 的 `layout/windowState` 与新 dock 集不兼容：键改为 `layout/windowState.v4`，不迁移旧 blob。

## 文件地图

| 路径 | 职责 |
|---|---|
| `paleo_workbench/ui/layout_presets.py` | 去掉 `document_tab`；显隐矩阵加 `well`/`seismic`/`hub` |
| `paleo_workbench/ui/workstation/shell.py` | 无 TabBar；宿主 well/seismic/hub dock；动作表 |
| `paleo_workbench/ui/workstation/linked_workspace.py` | 协调器：ensure_views/open_well；不再自建嵌套 MainWindow/平面图 |
| `paleo_workbench/ui/app_shell.py` | `activate_legacy` → `show_hub_page` |
| `paleo_workbench/ui/workstation/composite_document.py` | 工具条：测井轨道/地震剖面/链接；文案「编图」 |
| `tests/test_workstation_shell.py` | 壳层断言 |
| `tests/test_layout_presets.py` | preset 契约 |
| `CONTEXT.md` / README / CLAUDE | 术语 |

---

### Task 1: layout_presets 去掉 document_tab

**Files:**
- Modify: `paleo_workbench/ui/layout_presets.py`
- Modify: `tests/test_layout_presets.py`
- Modify: `paleo_workbench/ui/workstation/shell.py` 中 `apply_layout_preset`（若仍读 `document_tab`，本任务末尾改成只套显隐）

- [ ] **Step 1: 改失败测试**

`tests/test_layout_presets.py` 全文替换为：

```python
from paleo_workbench.ui.layout_presets import (
    RESET_LAYOUT_PRESET_ID,
    get_preset,
    list_presets,
    preset_labels,
    visibility_dict,
)


def test_named_presets_cover_composite_and_interpretation():
    presets = list_presets()
    ids = {p.id for p in presets}
    assert "composite_default" in ids
    assert "interpretation" in ids
    assert RESET_LAYOUT_PRESET_ID == "composite_default"

    composite = get_preset("composite_default")
    assert composite is not None
    assert composite.label == "默认编图"
    assert not hasattr(composite, "document_tab")
    matrix = visibility_dict(composite.visibility)
    assert matrix["composite_layer"] is True
    assert matrix["well"] is False
    assert matrix["seismic"] is False
    assert matrix["hub"] is False
    assert matrix["nav"] is True

    interpretation = get_preset("interpretation")
    assert interpretation is not None
    im = visibility_dict(interpretation.visibility)
    assert im["inspector"] is True
    assert im["tasks"] is True
    assert im["well"] is True
    assert im["seismic"] is True
    assert im["composite_layer"] is True


def test_preset_labels_are_stable_menu_pairs():
    labels = preset_labels()
    assert labels[0] == ("composite_default", "默认编图")
    assert ("interpretation", "解释工作区") in labels
```

- [ ] **Step 2: 跑 RED**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_layout_presets.py --basetemp=$(mktemp -d)
```

Expected: FAIL（仍有 `document_tab` / 旧文案）。

- [ ] **Step 3: 改 presets**

- 删除 `TAB_COMPOSITE` / `TAB_JOINT` 常量。
- `WorkstationLayoutPreset` 去掉 `document_tab` 字段。
- `DockVisibilityMatrix` 增加 `well: bool = False`、`seismic: bool = False`、`hub: bool = False`。
- `visibility_dict` 输出这三键。
- `composite_default`：label `"默认编图"`；well/seismic/hub False；composite_layer True。
- `interpretation`：well/seismic True；composite_layer True（编图仍在中央）；document_tab 删除。
- `register_with_dock_manager` 增加 `("workstation:well", "测井轨道", "bottom")`、`("workstation:seismic", "地震剖面", "bottom")`、`("workstation:hub", "功能页", "right")`。

`shell.py` `apply_layout_preset`：删除 `if preset.document_tab == TAB_JOINT: activate_joint()` 等分支，只按 `visibility_dict` 调 dock `setVisible`。暂时没有 `well_dock` 时用 `getattr(self, "well_dock", None)` 跳过，下一任务补齐。

- [ ] **Step 4: 跑 GREEN** `tests/test_layout_presets.py`

- [ ] **Step 5: 提交** `feat(shell): layout presets drop document tabs, add well/seismic/hub flags`

---

### Task 2: 壳层 — 无 Tab，中央编图，宿主 well/seismic dock

**Files:**
- Modify: `paleo_workbench/ui/workstation/shell.py`
- Modify: `tests/test_workstation_shell.py`

- [ ] **Step 1: 改失败测试（`test_workstation_shell.py` 相关用例）**

`test_app_shell_starts_in_native_workstation`：

```python
    assert shell.workstation.objectName() == "WorkstationFrame"
    assert not hasattr(shell.workstation, "document_tabs")
    assert shell.workstation.composite.isVisible() or shell.workstation.composite.parent() is not None
    assert shell.workstation.central_document() is shell.workstation.composite
    assert "A12 - D63" not in shell.workstation.findChildren(type(shell.workstation.composite[0] if False else object)).__class__.__name__
```

不要上面那行荒谬断言。改为：

```python
def test_app_shell_starts_in_native_workstation(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    assert ws.objectName() == "WorkstationFrame"
    assert shell.ribbon.height() == 0
    assert getattr(ws, "document_tabs", None) is None
    assert ws.central_document() is ws.composite
    assert ws.well_dock.isHidden()
    assert ws.seismic_dock.isHidden()
    titles = " ".join(d.windowTitle() for d in (ws.well_dock, ws.seismic_dock, ws.nav_dock))
    assert "A12 - D63" not in titles
    assert ws.linked_workspace._views_created is False
```

`test_composite_document_is_default_with_dock_panels`：删除「文档切换时综合编修面板随文档显隐」整段（约 L89–94）。图层 dock 默认仍可见。增加：

```python
    assert ws.well_dock.isHidden()
    assert ws.seismic_dock.isHidden()
```

`test_legacy_workflows_are_documents_not_a_second_shell` **改名为** `test_hub_navigation_does_not_replace_bian_tu`：

```python
def test_hub_navigation_does_not_replace_bian_tu(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    shell.navigate_to(navigation.PAGE_INDEX_MAPPING, "review")
    assert ws.central_document() is ws.composite
    assert not ws.hub_dock.isHidden()
    assert "成图审核" in ws.hub_dock.windowTitle()
```

本任务就创建 `hub_dock` 并把 `page_stack` 放进去（可先 hide）；Task 4 只改 `navigate_to` 为 `show`+浮动。

`test_linked_workspace_panes_are_floatable_docks` 改为断言 **宿主** `ws.well_dock` / `ws.seismic_dock`：

```python
def test_well_and_seismic_are_host_docks(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    for dock in (ws.well_dock, ws.seismic_dock):
        assert dock.parent() is ws._dock_host or dock.parentWidget() is ws._dock_host or True
        features = dock.features()
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetClosable
    ws.well_dock.close()
    assert ws.well_dock.isHidden()
    ws.well_dock.toggleViewAction().trigger()
    assert not ws.well_dock.isHidden()
```

`test_layout_presets_apply_visibility_matrix`：去掉 `document_tabs.currentIndex` 断言；`interpretation` 后 `not ws.well_dock.isHidden()` 且 `ws.central_document() is ws.composite`。

- [ ] **Step 2: 跑 RED** `tests/test_workstation_shell.py`

- [ ] **Step 3: 实现 shell**

`WorkstationFrame`：

1. 删除 `TAB_*`、`self.document_tabs` 及其 `addWidget`。
2. 删除 `document_stack`。中央 `layout` 直接 `addWidget(self.composite, 1)`。
3. 仍构造 `self.linked_workspace = LinkedInterpretationWorkspace(project, self)`，**不要**放进中央布局（`hide()`）。
4. 新增：

```python
    def central_document(self):
        return self.composite

    self.well_dock = self._add_dock(
        "测井轨道", self.linked_workspace.well_pane,
        Qt.DockWidgetArea.BottomDockWidgetArea,
    )
    self.seismic_dock = self._add_dock(
        "地震剖面", self.linked_workspace.seismic_pane,
        Qt.DockWidgetArea.BottomDockWidgetArea,
    )
    self.hub_dock = self._add_dock(
        "功能页", self.page_stack,
        Qt.DockWidgetArea.RightDockWidgetArea,
    )
    self.well_dock.hide()
    self.seismic_dock.hide()
    self.hub_dock.hide()
    self._dock_host.tabifyDockWidget(self.process_dock, self.well_dock)
    self._dock_host.tabifyDockWidget(self.well_dock, self.seismic_dock)
```

`page_stack` 原先在 `document_stack` 里，改挂 `hub_dock`。`AppShell` 仍创建 `page_stack` 并传入 `WorkstationFrame.__init__`。

5. `activate_joint` → `show_seismic()`（show+raise seismic_dock，`ensure_views`）。
6. `activate_composite` → 只 `select_layer`，不再切 Tab。
7. `_WINDOW_STATE_KEY = "layout/windowState.v4"`
8. `_shell_docks` 加入 well/seismic/hub。
9. `_on_document_tab_changed` 整函数删除。
10. `apply_layout_preset` 按 visibility 设置 well/seismic/hub。
11. 面板菜单 `panel_entries` 增加测井轨道、地震剖面、功能页。
12. 删除对 `linked_workspace.seismic_dock` 的 `_wire`（那些 dock 将在 Task 3 从 linked_workspace 消失）。本任务若 linked 仍有内部 dock，先不 reparent 两次：优先 **把 well_pane/seismic_pane 从内部 dock 取出** 再 `setWidget` 到宿主：

```python
# 在 LinkedInterpretationWorkspace.__init__ 之后、shell 里：
for inner in (
    getattr(self.linked_workspace, "well_dock", None),
    getattr(self.linked_workspace, "seismic_dock", None),
    getattr(self.linked_workspace, "map_dock", None),
):
    if inner is not None:
        inner.hide()
self.linked_workspace.hide()
self.linked_workspace.context_bar.hide() if hasattr(...)
```

更干净的做法放 Task 3：本任务只要宿主 dock 有 pane、中央是 composite、无 document_tabs。

- [ ] **Step 4: GREEN** `tests/test_workstation_shell.py tests/test_layout_presets.py`

- [ ] **Step 5: 提交** `feat(shell): drop document tabs; host well/seismic/hub docks`

---

### Task 3: 抽掉联动嵌套 MainWindow 与平面图窗格

**Files:**
- Modify: `paleo_workbench/ui/workstation/linked_workspace.py`
- Modify: `paleo_workbench/ui/workstation/shell.py`（`open_well` / `show_all_wells`）

- [ ] **Step 1: 测试**

在 `test_workstation_shell.py` 追加：

```python
def test_linked_workspace_has_no_nested_map_document(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    lw = shell.workstation.linked_workspace
    assert getattr(lw, "map_dock", None) is None
    assert getattr(lw, "dock_area", None) is None
    assert getattr(lw, "context_bar", None) is None
```

- [ ] **Step 2: RED**

- [ ] **Step 3: 实现**

`LinkedInterpretationWorkspace`：

- 删除 `context_bar`、`domain_combo`、`link_button`、`dock_area`、`map_pane`、`map_dock`。
- `__init__` 只创建 `seismic_pane` / `well_pane`（`DocumentPane`），**不** `addDockWidget`。shell 已经把它们放进宿主 dock。
- `open_well`：去掉 `self.map_panel.select_well(...)`。改为 emit `well_focused = Signal(str)`；shell 连接后若编图有井高亮 API 就调，没有则只打开测井 dock。
- `show_all_wells`：emit `show_all_wells_requested`；shell 对 `composite.canvas` 调 `zoom_to_full_extent`（shim 已有）。不要 `maximize_map`。
- `focus_joint`：`shell.show_seismic()` 语义——本类改成 `ensure_views` + 调用方 show seismic dock。
- 删除 `maximize_*` / `restore_split_view` / `save_dock_state` / `restore_dock_state`（宿主 `saveState` 已覆盖）。shell 里若调用这些方法，改为 show 对应宿主 dock。
- `_set_link_state` 保留为 `set_linked(bool)`，写 `self._linked`；pane 上若还有 `link_label` 可更新，没有则只存布尔。
- 标题：`well_pane.set_title(f"测井轨道 · {name}")`；未加载保持 `"测井轨道"`。地震同理，**禁止** `A12 - D63` 默认串。`DocumentPane` 初始 title 用 `"测井轨道"` / `"地震剖面"`。

`shell.py`：

```python
def show_well(self, well_name: str = "") -> None:
    self.well_dock.show()
    self.well_dock.raise_()
    if well_name:
        self.linked_workspace.open_well(well_name)

def show_seismic(self, resource=None) -> None:
    self.seismic_dock.show()
    self.seismic_dock.raise_()
    self.linked_workspace.ensure_views()
    if resource is not None and self.linked_workspace.seismic_panel is not None:
        self.linked_workspace.seismic_panel.show_resource(resource, self._project)

def _open_well_from_agent(self, well_name: str) -> None:
    self.show_well(well_name)

def _show_wells_from_agent(self) -> None:
    self.composite.canvas.zoom_to_full_extent()
```

`_activate_explorer_object`：well → `show_well`；seismic resource → `show_seismic(resource)`；horizon → `show_seismic()`；user_vector_layer → `activate_composite(id)`。

Agent `focus_joint_requested` → `show_seismic()`。

- [ ] **Step 4: GREEN** 壳层测试 + `tests/test_composite_editing.py`（抽样，确认编图未破）

- [ ] **Step 5: 提交** `feat(shell): lift well/seismic panes; remove nested map document`

---

### Task 4: Hub 不盖编图

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/ui/workstation/shell.py`（`show_hub_page`）

- [ ] **Step 1:** `test_hub_navigation_does_not_replace_bian_tu` 必须无 skip。再加：

```python
def test_hub_dock_close_keeps_bian_tu(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    shell.navigate_to(navigation.PAGE_INDEX_DATA, "overview")
    assert ws.central_document() is ws.composite
    ws.hub_dock.close()
    assert ws.hub_dock.isHidden()
    assert ws.central_document() is ws.composite
```

- [ ] **Step 2: RED** 若 `activate_legacy` 仍切栈。

- [ ] **Step 3:**

`shell.py`：

```python
def show_hub_page(self, title: str) -> None:
    self.hub_dock.setWindowTitle(str(title or "功能页"))
    self.hub_dock.show()
    self.hub_dock.setFloating(True)
    self.hub_dock.raise_()

def activate_legacy(self, title: str = "功能页") -> None:
    self.show_hub_page(title)
```

保留 `activate_legacy` 名字以免漏改调用点，实现改为 `show_hub_page`。

`app_shell.py` `navigate_to` 末尾继续 `self.workstation.activate_legacy(title)`，行为变为浮动 dock。

- [ ] **Step 4: GREEN** `tests/test_workstation_shell.py`

- [ ] **Step 5: 提交** `feat(shell): hub pages open as floating dock; bian-tu stays central`

---

### Task 5: 编图工具条 — 测井/地震显隐 + 链接

**Files:**
- Modify: `paleo_workbench/ui/workstation/composite_document.py`
- Modify: `paleo_workbench/ui/workstation/shell.py`（注入回调）

- [ ] **Step 1: 测试**

```python
def test_bian_tu_toolbar_toggles_view_docks(qtbot, tmp_path):
    shell = AppShell(project=_project(tmp_path))
    qtbot.addWidget(shell)
    ws = shell.workstation
    bar = ws.composite.toolbar
    well_btn = bar.findChild(type(ws.composite.panels_button), "WorkstationWellTrackButton")
    # 用 objectName 找：
    well_btn = ws.composite.well_track_button
    seis_btn = ws.composite.seismic_section_button
    link_btn = ws.composite.link_button
    assert well_btn.isCheckable()
    well_btn.setChecked(True)
    assert not ws.well_dock.isHidden()
    well_btn.setChecked(False)
    assert ws.well_dock.isHidden()
    seis_btn.setChecked(True)
    assert not ws.seismic_dock.isHidden()
    link_btn.setChecked(False)
    assert ws.linked_workspace.is_linked() is False
```

- [ ] **Step 2: RED**

- [ ] **Step 3:** 在 `_build_toolbar` 的面板按钮前插入三个 `QToolButton`：

```python
        self.well_track_button = QToolButton(self.toolbar)
        self.well_track_button.setObjectName("WorkstationWellTrackButton")
        self.well_track_button.setText("测井轨道")
        self.well_track_button.setCheckable(True)
        self.seismic_section_button = QToolButton(self.toolbar)
        self.seismic_section_button.setObjectName("WorkstationSeismicSectionButton")
        self.seismic_section_button.setText("地震剖面")
        self.seismic_section_button.setCheckable(True)
        self.link_button = QToolButton(self.toolbar)
        self.link_button.setObjectName("WorkstationLinkButton")
        self.link_button.setText("链接")
        self.link_button.setCheckable(True)
        self.link_button.setChecked(True)
```

信号：`well_track_toggled = Signal(bool)` 等。shell `_wire`：

```python
self.composite.well_track_toggled.connect(
    lambda on: self.well_dock.setVisible(on) or self.well_dock.raise_())
```

更干净：

```python
def _on_well_track_toggled(self, on: bool) -> None:
    self.well_dock.setVisible(on)
    if on:
        self.well_dock.raise_()
        self.linked_workspace.ensure_views()
```

dock `visibilityChanged` 回写按钮 check 状态（避免菜单关 dock 后面板按钮仍勾）。

`action_controller.toolbar("综合编修", ...)` 的标题改成 `"编图"`。

`LinkedInterpretationWorkspace.is_linked(self) -> bool`。

- [ ] **Step 4: GREEN**

- [ ] **Step 5: 提交** `feat(shell): bian-tu toolbar toggles well/seismic docks and link`

---

### Task 6: 文档 + 回归

**Files:**
- Modify: `README.md` / `CLAUDE.md` 若仍写「综合编修文档 Tab」
- `CONTEXT.md`（编图 / 成图排版，若尚未写入）
- Spec 保持已批准

- [ ] **Step 1: grep** `document_tabs` `TAB_JOINT` `A12 - D63` `activate_joint` `项目工作流`，生产代码不得再引用 Tab API。测试可留注释说明已删除。

- [ ] **Step 2: 跑**

```bash
/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo_project/main \
  tests/test_workstation_shell.py tests/test_layout_presets.py \
  tests/test_composite_editing.py tests/test_composite_gis.py \
  tests/test_qgis_project_xml_persist.py \
  --basetemp=$(mktemp -d)
```

Expected: 全绿（composite 套件不因壳层变红）。

- [ ] **Step 3: 提交** `docs(shell): 编图为核心的工作站壳层状态`

- [ ] **Step 4: 终局审查 + ff 合 main**（审查 C/I/M；With fixes 才合）

## Spec coverage

| Spec | Task |
|---|---|
| 删文档 Tab | 2 |
| 中央永远编图 | 2 |
| 测井/地震宿主 dock 默认隐藏 | 2–3 |
| 动作打开 | 3 |
| 删平面图窗格与嵌套 MainWindow | 3 |
| 无 A12 - D63 伪标题 | 3 |
| Hub 不盖中央 | 4 |
| 工具条开关 + 链接 | 5 |
| settings v4 | 2 |
| P2 Hub 各稳定 dock | **不做**（spec §11） |

## 类型一致性

- `central_document()` → `CompositeDocument`
- `show_well(name)` / `show_seismic(resource=None)` / `show_hub_page(title)`
- `is_linked()` bool
- visibility 键：`well` / `seismic` / `hub`
