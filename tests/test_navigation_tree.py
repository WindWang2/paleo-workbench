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
