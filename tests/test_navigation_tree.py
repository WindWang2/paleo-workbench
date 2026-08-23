from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.filter_index import FilterQuery
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


def test_deleted_tag_leaf_resets_filter_to_all(qtbot):
    """#656: removing the selected tag must not leave a stale invisible filter."""
    from PySide6.QtCore import Qt

    tagged = _res("well_log")
    tagged.tags = ["focus"]
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.update_counts([tagged], [])

    tag_parent = tree.tag_parent_item
    assert tag_parent is not None
    tag_leaf = tag_parent.child(0)
    assert tag_leaf is not None

    queries: list[FilterQuery] = []
    tree.filter_query_changed.connect(queries.append)
    tree.setCurrentItem(tag_leaf)
    assert queries
    assert queries[-1].node_type == "tag"
    assert queries[-1].node_value == "focus"

    queries.clear()
    tree.update_counts([_res("well_log")], [])

    current = tree.currentItem()
    assert current is not None
    current_query = current.data(0, Qt.ItemDataRole.UserRole)
    assert current_query is not None
    assert current_query.node_type == "all"
    assert queries
    assert queries[-1].node_type == "all"


# ---------------------------------------------------------------------------
# 井节点 → 具体数据文件叶
# ---------------------------------------------------------------------------


def _well_doc():
    from paleo_workbench.project.domain import EntityAssetLink, WellEntity
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("W")
    well = WellEntity(name="A1")
    doc.wells.append(well)
    doc.entity_asset_links.append(
        EntityAssetLink(
            entity_type="well",
            entity_id=well.id,
            asset_id="asset_head",
            role="well_head",
        )
    )
    doc.entity_asset_links.append(
        EntityAssetLink(
            entity_type="well",
            entity_id=well.id,
            asset_id="asset_las",
            role="well_head",
        )
    )
    return doc, well


def test_well_node_expands_to_file_leaves(qtbot):
    from PySide6.QtCore import Qt

    from paleo_workbench.ui.pages.navigation_tree import ENTITY_NODE

    doc, well = _well_doc()
    tree = NavigationTree()
    qtbot.addWidget(tree)
    labels = {"asset_head": "A1_head.dat", "asset_las": "A1.las"}
    tree.set_asset_label_provider(lambda aid: labels.get(aid, aid))
    tree.set_project(doc)

    group = tree._well_group_item  # 顶层标签带 🛢 前缀，find_group("井") 会误中“井分层”
    assert group is not None
    well_item = group.child(0)
    assert well_item is not None
    assert well_item.childCount() == 2

    leaf_texts = sorted(well_item.child(i).text(0) for i in range(2))
    assert leaf_texts == ["📄 A1.las", "📄 A1_head.dat"]
    leaf = well_item.child(0)
    query = leaf.data(0, Qt.ItemDataRole.UserRole)
    assert query is not None
    assert query.node_type == ENTITY_NODE
    assert query.node_value == well.id
    assert query.asset_id in {"asset_head", "asset_las"}
    # 选中文件叶 → 发射带 asset_id 的过滤查询
    emitted: list[FilterQuery] = []
    tree.filter_query_changed.connect(emitted.append)
    tree.setCurrentItem(leaf)
    assert emitted and emitted[-1].asset_id == query.asset_id


def test_well_file_leaf_falls_back_to_asset_id(qtbot):
    doc, well = _well_doc()
    tree = NavigationTree()
    qtbot.addWidget(tree)
    # 无 provider：显示原始 asset_id
    tree.set_project(doc)

    group = tree._well_group_item
    well_item = group.child(0)
    assert well_item is not None
    texts = [well_item.child(i).text(0) for i in range(well_item.childCount())]
    assert any("asset_las" in text for text in texts)


def test_well_file_leaves_capped(qtbot):
    from PySide6.QtCore import Qt

    from paleo_workbench.project.domain import EntityAssetLink
    from paleo_workbench.ui.pages.navigation_tree import MAX_WELL_FILE_CHILDREN

    doc, well = _well_doc()
    for idx in range(MAX_WELL_FILE_CHILDREN + 5):
        doc.entity_asset_links.append(
            EntityAssetLink(
                entity_type="well",
                entity_id=well.id,
                asset_id=f"asset_x{idx}",
            )
        )
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(doc)

    group = tree._well_group_item
    well_item = group.child(0)
    #  capped leaves + 1 overflow row
    assert well_item.childCount() == MAX_WELL_FILE_CHILDREN + 1
    overflow = well_item.child(MAX_WELL_FILE_CHILDREN)
    assert "另有" in overflow.text(0)
    assert not (overflow.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_entity_node_does_not_emit_legacy_category(qtbot):
    """实体/文件节点走 FilterQuery 通道；若再发 category_changed，
    DataPage 会把 'entity:…'/'asset:…' 解析成 legacy_category 查询
    覆盖掉实体过滤（网格变空的回归）。"""
    doc, well = _well_doc()
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(doc)

    categories: list[str] = []
    tree.category_changed.connect(categories.append)
    well_item = tree._well_group_item.child(0)
    tree.setCurrentItem(well_item)
    assert not categories
    tree.setCurrentItem(well_item.child(0))
    assert not categories
