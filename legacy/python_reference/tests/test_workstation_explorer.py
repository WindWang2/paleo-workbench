"""WorkstationExplorer（B3 重构）测试。

覆盖：真实数据分组（无假数据）、增量刷新（选中/展开保持）、
单组行数截断、统一右键菜单动作、搜索防抖。

全部用真实 ProjectDocument 构造，不 mock UI。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import (
    PaleoMapDocument,
    ProjectDocument,
    ResourceItem,
    UserVectorFeature,
    UserVectorLayer,
)
from paleo_workbench.ui.workstation.explorer import (
    KEY_ROLE,
    WorkstationExplorer,
)


def _project() -> ProjectDocument:
    return ProjectDocument.new("ExplorerTest", region="测试工区")


def _all_texts(explorer: WorkstationExplorer) -> list[str]:
    texts: list[str] = []

    def walk(item) -> None:
        for row in range(item.rowCount()):
            child = item.child(row)
            texts.append(child.text())
            walk(child)

    walk(explorer.model.invisibleRootItem())
    return texts


def test_project_mode_has_no_fabricated_horizon(qtbot):
    """无 target_horizon 的工程不出现 "D63" 假数据，给空态；设置后显示真值。"""
    project = _project()
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("project")

    texts = _all_texts(explorer)
    assert "D63" not in texts
    assert any("未设置目标层位" in text for text in texts)

    project.stratigraphy.target_horizon = "H2"
    explorer.notify_project_mutated()
    texts = _all_texts(explorer)
    assert "H2" in texts


def test_layers_mode_lists_real_layers_and_empty_state(qtbot):
    """图层模式只来自 user_vector_layers + paleomap_documents；无数据显示空态。"""
    project = _project()
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("layers")

    texts = _all_texts(explorer)
    assert any("暂无图层 — 在编图文档中创建" in text for text in texts)
    # 旧硬编码假图层不再出现
    for stale in ("断层解释", "井位 (A1-A20)", "A12 测井轨道", "同步拾取光标"):
        assert stale not in texts

    layer = UserVectorLayer(
        name="物源线",
        geometry_kind="line",
        visible=False,
        features=[
            UserVectorFeature(id="f1", geometry={"type": "LineString", "coordinates": [[0, 0], [1, 1]]})
        ],
    )
    document = PaleoMapDocument(
        name="M1",
        linked_target_horizon="H2",
        line_features=[{"id": "l1"}],
    )
    project.user_vector_layers.append(layer)
    project.paleomap_documents.append(document)
    explorer.notify_project_mutated()

    texts = _all_texts(explorer)
    assert any("物源线" in text for text in texts)
    assert "M1" in texts
    assert "线要素 (1)" in texts

    item = explorer.find_item(f"uvlayer/{layer.id}")
    assert item is not None
    assert item.isCheckable()
    assert item.checkState() == Qt.CheckState.Unchecked


def test_incremental_refresh_keeps_selection_and_expansion(qtbot):
    """差分刷新：插入井行数 +1、选中/展开按 key 保持；删除资源行消失。"""
    project = _project()
    wells = [WellEntity(name=f"W{i}") for i in range(3)]
    project.wells.extend(wells)
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("project")

    group = explorer.find_item("group/wells")
    assert group is not None
    # 手动展开井组并选中第二口井（key 断言的基础）
    explorer.tree.setExpanded(explorer.proxy_index_for_item(group), True)
    target = explorer.find_item(f"well/{wells[1].id}")
    explorer.tree.setCurrentIndex(explorer.proxy_index_for_item(target))

    # 插入一口新井 → 增量刷新：行数 +1，选中/展开保持
    project.wells.append(WellEntity(name="W9"))
    explorer.notify_project_mutated()
    assert group.rowCount() == 4
    current = explorer.tree.selectionModel().currentIndex()
    item = explorer.model.itemFromIndex(explorer.proxy.mapToSource(current))
    assert item is not None
    assert item.data(KEY_ROLE) == f"well/{wells[1].id}"
    assert explorer.tree.isExpanded(explorer.proxy_index_for_item(group))

    # 删除资源 → 行消失
    resource = ResourceItem(name="r.segy", path="seis/r.segy", type="seismic", format="segy")
    project.resources.append(resource)
    explorer.notify_project_mutated()
    assert explorer.find_item(f"resource/{resource.id}") is not None
    project.resources.remove(resource)
    explorer.notify_project_mutated()
    assert explorer.find_item(f"resource/{resource.id}") is None


def test_large_group_is_truncated_with_hint(qtbot):
    """单组超过 5000 行截断：显示前 5000 + 「… 还有 N 项（用搜索过滤）」。"""
    project = _project()
    project.resources.extend(
        ResourceItem(
            name=f"trace_{index}.dat",
            path=f"horizons/trace_{index}.dat",
            type="horizon",
            format="dat",
        )
        for index in range(5002)
    )
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("data")

    group = explorer.find_item("group/data/horizon")
    assert group is not None
    assert group.rowCount() == 5001  # 5000 数据行 + 1 截断提示行
    tail = group.child(group.rowCount() - 1)
    assert "还有 2 项" in tail.text()
    assert "用搜索过滤" in tail.text()


def test_context_menu_actions_emit_signals(qtbot):
    """统一右键菜单：打开/复制名称/按 kind 动作触发对应信号。"""
    project = _project()
    well = WellEntity(name="A1")
    project.wells.append(well)
    resource = ResourceItem(name="A12.segy", path="seis/A12.segy", type="seismic", format="segy")
    project.resources.append(resource)
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("project")

    # 井节点：打开 + 复制名称 + 井震联合解释
    well_index = explorer.proxy_index_for_item(explorer.find_item(f"well/{well.id}"))
    menu = explorer._build_context_menu(well_index)
    labels = [action.text() for action in menu.actions()]
    assert "打开" in labels
    assert "复制名称" in labels
    assert "井震联合解释" in labels

    fired: list[tuple] = []
    explorer.joint_workspace_requested.connect(lambda: fired.append(("joint",)))
    explorer.object_activated.connect(lambda payload: fired.append(("activated", payload)))

    next(action for action in menu.actions() if action.text() == "井震联合解释").trigger()
    assert fired == [("joint",)]

    next(action for action in menu.actions() if action.text() == "打开").trigger()
    assert len(fired) == 2
    assert fired[1][0] == "activated"
    assert fired[1][1].get("kind") == "well"

    next(action for action in menu.actions() if action.text() == "复制名称").trigger()
    clipboard = QApplication.clipboard()
    assert "A1" in clipboard.text()

    # 资源节点：激活 → object_activated
    resource_index = explorer.proxy_index_for_item(
        explorer.find_item(f"resource/{resource.id}")
    )
    menu = explorer._build_context_menu(resource_index)
    fired.clear()
    next(action for action in menu.actions() if action.text() == "激活").trigger()
    assert len(fired) == 1
    assert fired[0][0] == "activated"
    assert fired[0][1].get("kind") == "resource"


def test_history_mode_lists_real_versions(qtbot):
    """历史模式解释版本来自 horizon_interpretations，不再硬编码 "D63 · v1_current"。"""
    project = _project()
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("history")

    texts = _all_texts(explorer)
    assert "D63 · v1_current" not in texts
    assert any("尚无解释版本" in text for text in texts)

    from paleo_workbench.project.models import ExportArtifact, HorizonInterpretationRef

    project.horizon_interpretations.append(
        HorizonInterpretationRef(name="H2 解释", horizon_key="H2", current_version_id="ver_9")
    )
    project.export_artifacts.append(
        ExportArtifact(linked_id="map1", format="png", output_path="exports/m1.png")
    )
    explorer.notify_project_mutated()

    texts = _all_texts(explorer)
    assert "H2 解释 · ver_9" in texts
    assert "m1.png" in texts


def test_search_filter_is_debounced(qtbot):
    """搜索输入 200ms 防抖：击键后不立即过滤，事件循环到点后才生效。"""
    project = _project()
    project.resources.extend(
        [
            ResourceItem(name="A12.Las", path="wells/A12.Las", type="well_log", format="las"),
            ResourceItem(name="D63.dat", path="horizons/D63.dat", type="horizon", format="dat"),
        ]
    )
    explorer = WorkstationExplorer(project)
    qtbot.addWidget(explorer)
    explorer.set_mode("search")

    def visible_row_count() -> int:
        def count(index) -> int:
            total = 1
            for row in range(explorer.proxy.rowCount(index)):
                total += count(explorer.proxy.index(row, 0, index))
            return total

        return sum(count(explorer.proxy.index(row, 0)) for row in range(explorer.proxy.rowCount()))

    initial = visible_row_count()
    assert initial >= 5  # 工程根 + 两个类型组 + 两个资源行

    explorer.search_box.setText("D63")
    # 未到防抖窗口：不立即过滤
    assert visible_row_count() == initial

    qtbot.waitUntil(lambda: visible_row_count() < initial, timeout=3000)

    def visible_texts() -> list[str]:
        texts: list[str] = []

        def walk_index(index) -> None:
            texts.append(str(explorer.proxy.data(index) or ""))
            for row in range(explorer.proxy.rowCount(index)):
                walk_index(explorer.proxy.index(row, 0, index))

        for row in range(explorer.proxy.rowCount()):
            walk_index(explorer.proxy.index(row, 0))
        return texts

    texts = visible_texts()
    assert any("D63.dat" in text for text in texts)
    assert not any("A12.Las" in text for text in texts)
