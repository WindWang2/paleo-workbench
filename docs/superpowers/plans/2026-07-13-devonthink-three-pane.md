# DEVONthink Three-Pane Data Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the DataPage from a 2-splitter + floating-overlay-panel layout into a fixed DEVONthink-style 3-pane layout (NavigationTree / AssetTable / ReaderPanel+InspectorPanel), with action buttons moved to the toolbar.

**Architecture:** Replace `DataWorkspace`'s `QGridLayout` + two `FloatingPanel` overlays with a 3-segment horizontal `QSplitter` (NavigationTree | AssetTable | RightColumn) where RightColumn is a vertical `QSplitter` (DataReaderPanel | InspectorPanel). Extract category-count logic into `filter_index.py`. Move action buttons from the floating ActionPanel into `DataToolbar`. Remove `FloatingPanel`, `DataCatalogPanel`, `ActionPanel` from the workspace.

**Tech Stack:** PySide6 (QTreeWidget, QSplitter, existing widgets), tokens.

**Spec:** `docs/superpowers/specs/2026-07-13-devonthink-three-pane-design.md`

## Global Constraints

- NavigationTree is a `QTreeWidget` emitting `category_changed = Signal(str)` with the SAME category-name strings `FilterIndex`/`DataCatalogPanel` use today (the `CATEGORIES` dict keys: "全部", "输入数据", "成果", "参考资料", "异常", "测井", "地震", "层位", "井分层", "时深", "表格", "文档", "影像", "参考图", "未知"). The tree's selectable nodes emit exactly these strings — `FilterIndex` and `DataAssetTable.set_category` are unchanged.
- Group nodes (输入数据/成果/参考资料/异常) are non-selectable headers that only expand/collapse; they do NOT emit `category_changed`. Type leaves and "全部" are selectable.
- Count logic extracted as `compute_category_counts(resources, artifacts) -> dict[str, int]` in `filter_index.py`, mirroring the current `DataCatalogPanel.update_counts` logic (Counter on resource.type, role counts, issue count, reference aggregate). Both the function and `NavigationTree.update_counts` use it.
- InspectorPanel is read-only metadata (no editing). Reuses `TablePreviewWidget` for its table.
- ReaderPanel, AssetTableModel, DataAssetTable, FilterIndex, PreviewProvider/pipeline, import service — all UNCHANGED.
- `DataPage` keeps its public method signatures (`update_state`, `import_paths`, etc.) so `app.py` wiring is unaffected. Internal attribute names change (`catalog_panel` → `navigation_tree`, etc.) but these are not part of the public API consumed by app.py.
- Splitter defaults: main_splitter sizes [220, 600, 480]; right_splitter sizes [400, 200]. `setChildrenCollapsible(False)` on both.
- Stay on `main` branch. TDD per task. Frequent commits. Existing tests referencing the removed API must be updated as part of the migration task.

---

## File Structure

| File | Responsibility | Change |
|------|---------------|--------|
| `paleo_workbench/ui/pages/filter_index.py` | Category semantics | + `compute_category_counts` function (extracted from DataCatalogPanel) |
| `paleo_workbench/ui/pages/navigation_tree.py` | NEW — left-pane smart-group tree | Create |
| `paleo_workbench/ui/pages/inspector_panel.py` | NEW — right-pane metadata inspector | Create |
| `paleo_workbench/ui/pages/data_workspace.py` | Workspace assembly | Rewrite: 3-segment splitter + RightColumn; remove FloatingPanels |
| `paleo_workbench/ui/pages/data_toolbar.py` | Top toolbar | +remove/open_folder/visualize buttons + status label + 3 signals; −catalog_btn |
| `paleo_workbench/ui/pages/data_page.py` | Page controller | Re-wire signals to new components; update attribute names |
| `paleo_workbench/ui/pages/data_catalog_panel.py` | Legacy catalog | DELETE (replaced by NavigationTree) |
| `paleo_workbench/ui/pages/action_panel.py` | Legacy action panel | DELETE (buttons moved to toolbar) |
| `tests/test_navigation_tree.py` | NEW | Create |
| `tests/test_inspector_panel.py` | NEW | Create |
| `tests/test_data_workspace.py` | Update to new API | Rewrite |
| `tests/test_data_toolbar.py` | Update | Extend + remove catalog_btn checks |
| `tests/test_data_page.py` | Update to new API | Rewrite affected parts |
| `tests/test_data_catalog_panel.py` | Legacy | DELETE |
| `tests/test_visualization_jump.py` | Update references | Minor fixups |

---

## Task 1: Extract `compute_category_counts` into filter_index.py

**Files:**
- Modify: `paleo_workbench/ui/pages/filter_index.py`
- Modify: `paleo_workbench/ui/pages/data_catalog_panel.py` (use the extracted function — temporary, panel deleted in Task 6)
- Test: `tests/test_filter_index.py` (extend or create)

**Interfaces:**
- Produces: `compute_category_counts(resources: list, artifacts: list) -> dict[str, int]` returning counts keyed by the `CATEGORIES` strings ("全部", "输入数据", "成果", "参考资料", "异常", + each resource type).

- [ ] **Step 1: Write failing test**

In `tests/test_filter_index.py` (create if absent):
```python
from paleo_workbench.project.models import ResourceItem, ExportArtifact
from paleo_workbench.ui.pages.filter_index import compute_category_counts


def _res(rtype: str, status: str = "indexed", role: str | None = None) -> ResourceItem:
    return ResourceItem(
        name=f"{rtype}", path=f"/x/{rtype}", type=rtype, format="dat", status=status, artifact_role=role
    )


def test_counts_total_and_types():
    resources = [_res("well_log"), _res("well_log"), _res("seismic")]
    counts = compute_category_counts(resources, [])
    assert counts["全部"] == 3
    assert counts["测井"] == 2
    assert counts["地震"] == 1


def test_counts_artifacts_and_roles():
    resources = [_res("well_log", role="input"), _res("horizon", role="derived")]
    artifacts = [ExportArtifact(linked_id="x", format="tiff", output_path="/x.tif")]
    counts = compute_category_counts(resources, artifacts)
    assert counts["输入数据"] == 1
    assert counts["成果"] == len(artifacts) + 1  # artifact + derived resource


def test_counts_issues_and_references():
    resources = [
        _res("well_log", status="missing"),
        _res("document"),
        _res("image_reference"),
    ]
    counts = compute_category_counts(resources, [])
    assert counts["异常"] == 1
    assert counts["参考资料"] == 2  # document + image_reference
```

- [ ] **Step 2: Run — expect FAIL**

```bash
source .venv/bin/activate && python -m pytest tests/test_filter_index.py -v
```

- [ ] **Step 3: Implement `compute_category_counts`**

In `filter_index.py`, add (importing `Counter` from collections):
```python
from collections import Counter

def compute_category_counts(resources: list, artifacts: list) -> dict[str, int]:
    """Count assets per CATEGORIES key, mirroring DataCatalogPanel logic."""
    type_counts = Counter(r.type for r in resources)
    role_counts = Counter(r.artifact_role or "input" for r in resources)
    issue_count = sum(
        1 for r in resources if r.status in {"missing", "warning", "failed", "error"}
    )
    values = {
        "全部": len(resources) + len(artifacts),
        "输入数据": role_counts["input"],
        "成果": len(artifacts) + role_counts["derived"] + role_counts["export"],
        "参考资料": sum(
            type_counts[k]
            for k in ("document", "image_reference", "reference_map", "well_reference")
        ),
        "异常": issue_count,
    }
    result = dict(values)
    for label, rtype in CATEGORIES.items():
        if label not in result:
            result[label] = type_counts[rtype] if rtype else 0
    return result
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Refactor DataCatalogPanel to use it** (temporary — keeps panel working until deleted in Task 6)

In `data_catalog_panel.py`, replace the inline count logic in `update_counts` with a call to `compute_category_counts`.

- [ ] **Step 6: Run full suite — expect PASS (no behavior change)**

```bash
python -m pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add paleo_workbench/ui/pages/filter_index.py paleo_workbench/ui/pages/data_catalog_panel.py tests/test_filter_index.py
git commit -m "refactor: extract compute_category_counts into filter_index"
```

---

## Task 2: NavigationTree

**Files:**
- Create: `paleo_workbench/ui/pages/navigation_tree.py`
- Test: `tests/test_navigation_tree.py`

**Interfaces:**
- Consumes: `compute_category_counts` (Task 1), `CATEGORIES` from `data_catalog_panel` (import the dict; it's deleted in Task 6, so copy the dict into `navigation_tree.py` or `filter_index.py` as the canonical home — **decision: move `CATEGORIES` into `filter_index.py` in this task** since filter_index already imports it).
- Produces: `NavigationTree(QTreeWidget)` with `category_changed = Signal(str)`, `update_counts(resources, artifacts)`, `selected_category() -> str`.

- [ ] **Step 1: Move CATEGORIES to filter_index.py**

In `filter_index.py`, add (move from `data_catalog_panel.py`):
```python
CATEGORIES = {
    "全部": None,
    "输入数据": "input",
    "成果": "artifact",
    "参考资料": "reference",
    "异常": "issue",
    "测井": "well_log",
    "地震": "seismic",
    "层位": "horizon",
    "井分层": "well_stratification",
    "时深": "time_depth",
    "表格": "tabular",
    "文档": "document",
    "影像": "image_reference",
    "参考图": "reference_map",
    "未知": "unknown",
}
```
Update `data_catalog_panel.py` to import `CATEGORIES` from `filter_index` (it already does — `from ...data_catalog_panel import CATEGORIES`; flip the import). Update `filter_index.py`'s own `_matches_category` to use the local `CATEGORIES`.

- [ ] **Step 2: Write failing tests**

In `tests/test_navigation_tree.py`:
```python
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


def _res(rtype, status="indexed"):
    return ResourceItem(name=rtype, path=f"/x/{rtype}", type=rtype, format="dat", status=status)


def test_tree_object_name(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    assert tree.objectName() == "NavigationTree"


def test_tree_has_top_level_all(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([_res("well_log")], [])
    top = tree.topLevelItem(0)
    assert top is not None
    assert "全部" in top.text(0)


def test_tree_group_nodes_present(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([], [])
    labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    joined = " ".join(labels)
    assert "输入数据" in joined
    assert "成果" in joined
    assert "参考资料" in joined
    assert "异常" in joined


def test_tree_type_leaves_under_input(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([_res("well_log"), _res("seismic")], [])
    input_group = tree.find_group("输入数据")
    assert input_group is not None
    child_labels = [input_group.child(i).text(0) for i in range(input_group.childCount())]
    assert any("测井" in l for l in child_labels)
    assert any("地震" in l for l in child_labels)


def test_tree_counts_populated(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([_res("well_log"), _res("well_log"), _res("seismic")], [])
    top = tree.topLevelItem(0)
    assert "3" in top.text(0)  # 全部 (3)


def test_tree_selecting_type_emits_category(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([_res("well_log")], [])
    received = []
    tree.category_changed.connect(lambda name: received.append(name))
    well_leaf = tree.find_category_item("测井")
    tree.setCurrentItem(well_leaf)
    assert received == ["测井"]


def test_tree_group_node_does_not_emit(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([], [])
    received = []
    tree.category_changed.connect(lambda name: received.append(name))
    group = tree.find_group("输入数据")
    tree.setCurrentItem(group)
    assert received == []  # group node only expands, no filter change
```

- [ ] **Step 3: Run — expect FAIL (module missing)**

- [ ] **Step 4: Implement NavigationTree**

In `navigation_tree.py`:
```python
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.filter_index import CATEGORIES, compute_category_counts

# Tree structure: group nodes (non-selectable headers) + their type leaves.
GROUP_NODES = ["输入数据", "成果", "参考资料", "异常"]
# Which CATEGORIES are type-leaves under "输入数据"
TYPE_LEAVES = ["测井", "地震", "层位", "井分层", "时深", "表格", "文档", "影像", "参考图", "未知"]


class NavigationTree(QTreeWidget):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationTree")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setStyleSheet(
            f"QTreeWidget#NavigationTree {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self.setMinimumWidth(180)
        self.itemClicked.connect(self._on_item_clicked)
        self._build_nodes()

    def _build_nodes(self):
        all_item = QTreeWidgetItem(self, [f"{CATEGORIES and '全部' or '全部'} 0"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, "全部")
        for group in GROUP_NODES:
            group_item = QTreeWidgetItem(self, [f"{group} 0"])
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)  # non-selectable
            for leaf in TYPE_LEAVES:
                leaf_item = QTreeWidgetItem(group_item, [f"{leaf} 0"])
                leaf_item.setData(0, Qt.ItemDataRole.UserRole, leaf)

    def update_counts(self, resources: list, artifacts: list) -> None:
        counts = compute_category_counts(resources, artifacts)
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            self._update_node_count(top, counts)
        # Preserve selection (QTreeWidget keeps current item across text changes)

    def _update_node_count(self, item: QTreeWidgetItem, counts: dict) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        label = self._label_of(item)
        if key is not None:
            item.setText(0, f"{label} {counts.get(key, 0)}")
        else:
            # group node: sum its children counts
            child_sum = 0
            for j in range(item.childCount()):
                child = item.child(j)
                self._update_node_count(child, counts)
                child_key = child.data(0, Qt.ItemDataRole.UserRole)
                child_sum += counts.get(child_key, 0)
            item.setText(0, f"{label} {child_sum}")

    @staticmethod
    def _label_of(item: QTreeWidgetItem) -> str:
        return item.text(0).rsplit(" ", 1)[0]

    def find_group(self, label: str) -> QTreeWidgetItem | None:
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if self._label_of(top) == label:
                return top
        return None

    def find_category_item(self, label: str) -> QTreeWidgetItem | None:
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if self._label_of(top) == label:
                return top
            for j in range(top.childCount()):
                child = top.child(j)
                if self._label_of(child) == label:
                    return child
        return None

    def selected_category(self) -> str:
        current = self.currentItem()
        if current is None:
            return "全部"
        key = current.data(0, Qt.ItemDataRole.UserRole)
        return key if key is not None else "全部"

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key is not None:
            self.category_changed.emit(key)
```

- [ ] **Step 5: Run — expect PASS** (adjust tests if `itemClicked` doesn't fire `setCurrentItem`; if needed use `currentItemChanged` signal instead — the test calls `setCurrentItem`, so connect `_on_item_clicked` via `currentItemChanged` for test reliability)

- [ ] **Step 6: Run full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/navigation_tree.py paleo_workbench/ui/pages/filter_index.py paleo_workbench/ui/pages/data_catalog_panel.py tests/test_navigation_tree.py
git commit -m "feat: add NavigationTree smart-group tree widget"
```

---

## Task 3: InspectorPanel

**Files:**
- Create: `paleo_workbench/ui/pages/inspector_panel.py`
- Test: `tests/test_inspector_panel.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`, `RESOURCE_TYPE_LABELS` from `asset_table_model.py`, `TablePreviewWidget` from `preview_widgets.py`.
- Produces: `InspectorPanel(QFrame)` with `update_asset(asset | None)`.

- [ ] **Step 1: Write failing tests**

In `tests/test_inspector_panel.py`:
```python
from paleo_workbench.project.models import ResourceItem, ExportArtifact
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel


def test_inspector_object_name(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "InspectorPanel"


def test_inspector_resource_rows(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed", crs="EPSG:32649", tags=["ZJ-2", "sand"],
    )
    panel.update_asset(res)
    texts = [panel.metadata_table.item(r, 0).text() for r in range(panel.metadata_table.rowCount())]
    assert "名称" in texts
    assert "路径" in texts
    assert "CRS" in texts


def test_inspector_tags_joined(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(name="x", path="/x", type="well_log", format="LAS", status="ok", tags=["a", "b"])
    panel.update_asset(res)
    # find the 标签 row value
    for r in range(panel.metadata_table.rowCount()):
        if panel.metadata_table.item(r, 0).text() == "标签":
            assert "a, b" == panel.metadata_table.item(r, 1).text()
            return
    assert False, "标签 row not found"


def test_inspector_empty_state(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert panel.metadata_table.rowCount() == 0


def test_inspector_artifact_rows(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    art = ExportArtifact(linked_id="m1", format="GeoTIFF", output_path="/out/map.tif")
    panel.update_asset(art)
    texts = [panel.metadata_table.item(r, 0).text() for r in range(panel.metadata_table.rowCount())]
    assert "格式" in texts
    assert "输出路径" in texts
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement InspectorPanel**

In `inspector_panel.py`:
```python
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.preview_widgets import TablePreviewWidget


class InspectorPanel(QFrame):
    """Read-only metadata inspector for the selected asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setStyleSheet(
            f"QFrame#InspectorPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("检查器")
        self.title_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.metadata_table = TablePreviewWidget()
        layout.addWidget(self.metadata_table, 1)

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        if asset is None:
            self.metadata_table.load_table((), ())
            return
        if isinstance(asset, ResourceItem):
            rows = self._resource_rows(asset)
        else:
            rows = self._artifact_rows(asset)
        self.metadata_table.load_table(("属性", "值"), rows)

    @staticmethod
    def _resource_rows(res: ResourceItem) -> tuple[tuple[str, str], ...]:
        size = res.parsed_summary.get("size_bytes")
        tags = ", ".join(res.tags) if res.tags else "—"
        return (
            ("名称", res.name),
            ("路径", res.path),
            ("类型", RESOURCE_TYPE_LABELS.get(res.type, res.type)),
            ("格式", res.format),
            ("CRS", res.crs or "—"),
            ("标签", tags),
            ("校验和", res.checksum or "—"),
            ("状态", res.status),
            ("大小", str(size) if size is not None else "—"),
            ("来源", res.source),
            ("外部", "是" if res.external else "否"),
        )

    @staticmethod
    def _artifact_rows(art: ExportArtifact) -> tuple[tuple[str, str], ...]:
        return (
            ("格式", art.format),
            ("输出路径", art.output_path),
            ("关联对象", art.linked_id),
            ("包含要素", ", ".join(art.included_map_elements) or "—"),
            ("生成时间", art.generated_at),
            ("来源任务", ", ".join(art.source_task_ids) or "—"),
        )
```

- [ ] **Step 4: Run — expect PASS + full suite + commit**

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/inspector_panel.py tests/test_inspector_panel.py
git commit -m "feat: add InspectorPanel metadata widget"
```

---

## Task 4: Extend DataToolbar with action buttons

**Files:**
- Modify: `paleo_workbench/ui/pages/data_toolbar.py`
- Test: `tests/test_data_toolbar.py`

**Interfaces:**
- Produces: `DataToolbar` gains `remove_btn`, `open_folder_btn`, `visualize_btn`, `operation_status_label`, and signals `remove_requested`, `open_folder_requested`, `visualize_requested`. Removes `catalog_btn` and `catalog_toggled`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_data_toolbar.py`:
```python
def test_toolbar_has_remove_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.remove_btn.text() == "移出项目"


def test_toolbar_has_open_folder_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.open_folder_btn.text() == "打开目录"


def test_toolbar_has_visualize_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert tb.visualize_btn.text() == "可视化"


def test_toolbar_remove_signal(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    received = []
    tb.remove_requested.connect(lambda: received.append(1))
    tb.remove_btn.click()
    assert received == [1]


def test_toolbar_no_catalog_button(qtbot):
    tb = DataToolbar()
    qtbot.addWidget(tb)
    assert not hasattr(tb, "catalog_btn")
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Modify DataToolbar**

In `data_toolbar.py`:
- Add signals: `remove_requested = Signal()`, `open_folder_requested = Signal()`, `visualize_requested = Signal()`.
- Remove `catalog_toggled = Signal()` and the `catalog_btn` widget + its connection.
- Add after `rescan_btn`:
```python
        self.remove_btn = QPushButton("移出项目")
        self.remove_btn.setObjectName("SecondaryButton")
        self.remove_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.remove_btn.clicked.connect(self.remove_requested.emit)
        layout.addWidget(self.remove_btn)

        self.open_folder_btn = QPushButton("打开目录")
        self.open_folder_btn.setObjectName("SecondaryButton")
        self.open_folder_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.open_folder_btn.clicked.connect(self.open_folder_requested.emit)
        layout.addWidget(self.open_folder_btn)

        self.visualize_btn = QPushButton("可视化")
        self.visualize_btn.setObjectName("SecondaryButton")
        self.visualize_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.visualize_btn.clicked.connect(self.visualize_requested.emit)
        layout.addWidget(self.visualize_btn)
```
- Add the status label after `visualize_btn`:
```python
        self.operation_status_label = QLabel("")
        self.operation_status_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        layout.addWidget(self.operation_status_label)
```

- [ ] **Step 4: Run — expect PASS + full suite + commit**

Note: existing `test_data_toolbar.py` tests referencing `catalog_btn`/`catalog_toggled` must be updated/removed in this step.

```bash
python -m pytest -q
git add paleo_workbench/ui/pages/data_toolbar.py tests/test_data_toolbar.py
git commit -m "feat: move action buttons into DataToolbar, remove catalog toggle"
```

---

## Task 5: Rewrite DataWorkspace (3-pane splitter) + DataPage rewiring + delete legacy panels + test migration

**Files:**
- Modify: `paleo_workbench/ui/pages/data_workspace.py` (rewrite)
- Modify: `paleo_workbench/ui/pages/data_page.py` (re-wire)
- Delete: `paleo_workbench/ui/pages/data_catalog_panel.py`, `paleo_workbench/ui/pages/action_panel.py`
- Modify tests: `tests/test_data_workspace.py` (rewrite), `tests/test_data_page.py` (update), `tests/test_data_catalog_panel.py` (delete), `tests/test_visualization_jump.py` (fixup)

**Interfaces:**
- Consumes: `NavigationTree` (Task 2), `InspectorPanel` (Task 3), extended `DataToolbar` (Task 4), unchanged `DataAssetTable` + `DataReaderPanel`.
- Produces: `DataWorkspace` exposes `navigation_tree`, `asset_table`, `reader_panel`, `inspector_panel`, `main_splitter`, `right_splitter`, `set_right_visible(bool)`.

This is the integration task — the largest. It must be one task because the workspace, page rewiring, panel deletion, and test migration are all interdependent (partial migration leaves the app broken).

- [ ] **Step 1: Rewrite DataWorkspace**

In `data_workspace.py`, replace the entire class body:
```python
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QWidget

from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.navigation_tree import NavigationTree


class DataWorkspace(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataWorkspace")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("DataMainSplitter")
        self.main_splitter.setChildrenCollapsible(False)

        self.navigation_tree = NavigationTree()
        self.asset_table = DataAssetTable()

        # Right column: vertical splitter of reader + inspector
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.reader_panel = DataReaderPanel()
        self.inspector_panel = InspectorPanel()
        self.right_splitter.addWidget(self.reader_panel)
        self.right_splitter.addWidget(self.inspector_panel)
        self.right_splitter.setStretchFactor(0, 2)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([400, 200])

        self.main_splitter.addWidget(self.navigation_tree)
        self.main_splitter.addWidget(self.asset_table)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([220, 600, 480])

        layout.addWidget(self.main_splitter)

    def set_right_visible(self, visible: bool) -> None:
        self.right_splitter.setVisible(visible)
```

- [ ] **Step 2: Re-wire DataPage**

In `data_page.py`, update `__init__` and all references:
- Replace `self.catalog_panel = self.workspace.catalog_panel` → `self.navigation_tree = self.workspace.navigation_tree`.
- Remove `self.action_panel = self.workspace.action_panel` and all `self.action_panel.*` references.
- `self.import_btn` / `import_folder_btn` / `rescan_btn` / `remove_btn` / `open_visualization_btn` → now come from `self.data_toolbar` (import_btn/import_folder_btn/rescan_btn already on toolbar; remove_btn/open_folder_btn/visualize_btn new on toolbar). `open_folder_btn` → `self.data_toolbar.open_folder_btn`.
- `self.operation_status_label` → `self.data_toolbar.operation_status_label`.
- Signal wiring:
  - `self.navigation_tree.category_changed.connect(self.asset_table.set_category)`
  - `self.asset_table.selected_asset_changed.connect(self._set_selected_asset)` (existing) AND `.connect(self.inspector_panel.update_asset)`
  - `self.data_toolbar.remove_requested.connect(self.remove_selected_asset)`
  - `self.data_toolbar.open_folder_requested.connect(self.open_selected_folder)`
  - `self.data_toolbar.visualize_requested.connect(self._emit_open_visualization)`
  - Remove `catalog_toggled`/`_toggle_catalog_from_toolbar`/`_on_catalog_expanded_changed`/`_sync_toolbar_toggle_state` (catalog toggle gone).
  - `reader_toggled` → connect to `self.workspace.set_right_visible` toggle (keep `_toggle_reader_from_toolbar` but call `set_right_visible`).
- `update_state`: replace `self.catalog_panel.update_counts(...)` → `self.navigation_tree.update_counts(...)`. Remove `self.action_panel.update_selection_state(...)`.
- `_set_selected_asset`: the inspector update happens via the `selected_asset_changed` connection; remove any direct `action_panel.update_selection_state` call.
- Remove `self.content_splitter` reference.
- `_set_action_status`: `self.action_panel.operation_status_label` → `self.data_toolbar.operation_status_label`.
- `_set_import_running`: update button enable refs to toolbar buttons.

- [ ] **Step 3: Delete legacy files**

```bash
rm paleo_workbench/ui/pages/data_catalog_panel.py
rm paleo_workbench/ui/pages/action_panel.py
rm tests/test_data_catalog_panel.py
```
Remove any imports of these from `__init__.py` or elsewhere (grep first).

- [ ] **Step 4: Rewrite test_data_workspace.py**

```python
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.navigation_tree import NavigationTree
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel


def test_workspace_has_three_panes(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert isinstance(ws.navigation_tree, NavigationTree)
    assert isinstance(ws.asset_table, DataAssetTable)
    assert isinstance(ws.reader_panel, DataReaderPanel)
    assert isinstance(ws.inspector_panel, InspectorPanel)


def test_workspace_main_splitter_three_segments(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert ws.main_splitter.count() == 3


def test_workspace_right_splitter_two_segments(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    assert ws.right_splitter.count() == 2


def test_workspace_set_right_visible(qtbot):
    ws = DataWorkspace()
    qtbot.addWidget(ws)
    ws.set_right_visible(False)
    assert not ws.right_splitter.isVisible()
```

- [ ] **Step 5: Update test_data_page.py** — replace all `catalog_panel`/`action_panel`/`content_splitter`/`catalog_btn` references with `navigation_tree`/toolbar buttons. Remove tests for the floating panels. Add:
```python
def test_page_selecting_asset_updates_inspector(qtbot):
    # ... construct page, select an asset, assert inspector_panel.metadata_table.rowCount() > 0


def test_page_navigation_tree_routes_to_asset_table(qtbot):
    # ... emit navigation_tree.category_changed("测井"), assert asset_table filter applied
```

- [ ] **Step 6: Fix test_visualization_jump.py** — update any `action_panel`/`open_visualization_btn` references to toolbar.

- [ ] **Step 7: Run full suite — fix any remaining references**

```bash
python -m pytest -q
```
Greps to find stragglers:
```bash
grep -rn "catalog_panel\|action_panel\|content_splitter\|catalog_floating\|actions_floating\|catalog_btn\|toggle_catalog\|toggle_actions\|DataCatalogPanel\|ActionPanel" paleo_workbench/ tests/ | grep -v __pycache__
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: rewrite DataWorkspace as DEVONthink 3-pane layout

Replace floating-panel overlay with fixed 3-segment QSplitter: NavigationTree
(left) / DataAssetTable (center) / ReaderPanel+InspectorPanel (right, vertical
split). Action buttons moved to DataToolbar. Delete DataCatalogPanel +
ActionPanel + FloatingPanel usage."
```

---

## Task 6: Final review + ledger sync

**Actions:**
- Whole-branch review: layout correctness, signal wiring completeness (no dangling references to removed panels), category contract intact, inspector syncs on selection, splitter geometry sane.
- Verify no `FloatingPanel`/`DataCatalogPanel`/`ActionPanel` references remain anywhere.
- Run full suite, confirm count.
- Update `task_plan.md` / `progress.md` / `findings.md`.

**Commit:** `chore: sync SDD progress ledger (DEVONthink 3-pane Phase A complete)`

## Self-Review (completed during authoring)

- **Spec coverage:** NavigationTree (Task 2), InspectorPanel (Task 3), toolbar action migration (Task 4), workspace rewrite + page rewiring + panel deletion + test migration (Task 5), count extraction (Task 1). All 8 acceptance criteria map to tasks. ✓
- **Placeholder scan:** Every code step has actual code; tests have actual code. No TBD. ✓
- **Type consistency:** `category_changed = Signal(str)`, `update_counts(resources, artifacts)`, `update_asset(asset|None)`, `set_right_visible(bool)` — consistent across tasks. `CATEGORIES` moves to `filter_index.py` (Task 2 step 1) and is imported by both NavigationTree and the (temporary) DataCatalogPanel. ✓
- **Risk addressed:** Task 5 is deliberately one big integration task (workspace + page + deletion + tests) because partial migration breaks the app — called out in the task description. The grep in Step 7 catches stragglers. ✓
- **Known ambiguity:** NavigationTree uses `itemClicked` for emission but tests use `setCurrentItem`. If `setCurrentItem` doesn't fire `itemClicked`, switch the connection to `currentItemChanged` — flagged in Task 2 Step 5. The implementer should verify which signal fires on programmatic selection and wire accordingly. ✓
