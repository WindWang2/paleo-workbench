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


def test_tree_has_type_leaves(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([], [])
    labels = []
    def collect(item):
        labels.append(item.text(0))
        for i in range(item.childCount()):
            collect(item.child(i))
    for i in range(tree.topLevelItemCount()):
        collect(tree.topLevelItem(i))
    joined = " ".join(labels)
    assert "测井" in joined
    assert "地震" in joined
    assert "层位" in joined


def test_tree_type_leaves_populated(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([_res("well_log"), _res("seismic")], [])
    well_item = tree.find_category_item("测井")
    assert well_item is not None
    assert "测井" in well_item.text(0)
    seis_item = tree.find_category_item("地震")
    assert seis_item is not None
    assert "地震" in seis_item.text(0)


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


def test_tree_no_emit_for_nonexistent_group(qtbot):
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([], [])
    received = []
    tree.category_changed.connect(lambda name: received.append(name))
    # No group nodes anymore; selecting "全部" emits normally
    tree.setCurrentItem(tree.topLevelItem(0))
    assert received == ["全部"]
