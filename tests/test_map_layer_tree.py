from PySide6.QtWidgets import QLabel

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_layer_tree import LAYER_KEYS, MapLayerTree


def test_layer_tree_dock_title_object_name(qtbot):
    w = MapLayerTree()
    qtbot.addWidget(w)
    titles = [c for c in w.findChildren(QLabel) if c.objectName() == "MapDockTitle"]
    assert len(titles) >= 1
    assert titles[0].text() == "图件与图层"
    assert w.objectName() == "MapLayerTree"
    assert w.tree.objectName() == "MapLayerTreeWidget"


def test_layer_tree_lists_documents_and_default_layers(qtbot):
    tree = MapLayerTree()
    qtbot.addWidget(tree)

    docs = [
        PaleoMapDocument(name="Map A", linked_target_horizon="H1"),
        PaleoMapDocument(name="Map B", linked_target_horizon="H2"),
    ]
    tree.set_documents(docs)

    # Root group + two document items
    assert tree.tree.topLevelItemCount() == 1
    root = tree.tree.topLevelItem(0)
    assert root.childCount() == 2
    assert root.child(0).text(0) == "Map A"
    assert root.child(1).text(0) == "Map B"

    # Active document gets child layers 相带/井/线/注记
    tree.set_active_document(docs[1])
    root = tree.tree.topLevelItem(0)
    active_item = root.child(1)
    layer_labels = [active_item.child(i).text(0) for i in range(active_item.childCount())]
    assert layer_labels == ["相带", "井", "线", "注记"]
    assert LAYER_KEYS == ("facies", "well", "line", "label")


def test_layer_tree_emits_document_selected(qtbot):
    tree = MapLayerTree()
    qtbot.addWidget(tree)
    docs = [
        PaleoMapDocument(name="Map A", linked_target_horizon="H1"),
        PaleoMapDocument(name="Map B", linked_target_horizon="H2"),
    ]
    tree.set_documents(docs)
    tree.set_active_document(docs[0])

    selected = []
    tree.document_selected.connect(selected.append)

    root = tree.tree.topLevelItem(0)
    tree.tree.setCurrentItem(root.child(1))
    assert selected == [docs[1]]


def test_layer_tree_visibility_and_lock_signals(qtbot):
    tree = MapLayerTree()
    qtbot.addWidget(tree)
    doc = PaleoMapDocument(name="Map A", linked_target_horizon="H1")
    tree.set_documents([doc])
    tree.set_active_document(doc)

    visibility = []
    locks = []
    tree.layer_visibility_changed.connect(lambda k, v: visibility.append((k, v)))
    tree.layer_lock_changed.connect(lambda k, v: locks.append((k, v)))

    root = tree.tree.topLevelItem(0)
    facies_item = root.child(0).child(0)
    assert facies_item is not None

    # Uncheck visibility (column 0 checkbox)
    from PySide6.QtCore import Qt

    facies_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert ("facies", False) in visibility

    # Toggle lock via tree helper / column 1
    tree.set_layer_locked("facies", True)
    assert ("facies", True) in locks

def test_layer_tree_shows_reference_layers_under_active_document(qtbot):
    """Reference layers appear in a separate '参考图层' group below editable layers."""
    from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument
    from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree

    tree = MapLayerTree()
    qtbot.addWidget(tree)
    layer = MapReferenceLayer(
        name="断层参考",
        source_path="/tmp/faults.geojson",
        source_kind="vector",
        source_crs="EPSG:4326",
        project_crs="EPSG:3857",
        status="ready",
    )
    doc = PaleoMapDocument(
        name="Map A",
        linked_target_horizon="H1",
        reference_layers=[layer],
    )
    tree.set_documents([doc])
    tree.set_active_document(doc)

    root = tree.tree.topLevelItem(0)
    doc_item = root.child(0)
    # 4 editable layers + 1 reference group
    assert doc_item.childCount() == 5
    ref_group = doc_item.child(4)
    assert ref_group.text(0) == "参考图层"
    assert ref_group.childCount() == 1
    assert "断层参考" in ref_group.child(0).text(0)


def test_layer_tree_reference_layers_show_offline_status(qtbot):
    from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument
    from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree

    tree = MapLayerTree()
    qtbot.addWidget(tree)
    layer = MapReferenceLayer(
        name="地形图",
        source_path="/tmp/missing.tif",
        source_kind="raster",
        source_crs="EPSG:4326",
        project_crs="EPSG:3857",
        status="offline",
    )
    doc = PaleoMapDocument(
        name="Map A",
        linked_target_horizon="H1",
        reference_layers=[layer],
    )
    tree.set_documents([doc])
    tree.set_active_document(doc)

    root = tree.tree.topLevelItem(0)
    doc_item = root.child(0)
    ref_group = doc_item.child(4)
    ref_item = ref_group.child(0)
    assert "离线" in ref_item.text(0)


def test_layer_tree_no_reference_group_when_empty(qtbot):
    from paleo_workbench.project.models import PaleoMapDocument
    from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree

    tree = MapLayerTree()
    qtbot.addWidget(tree)
    doc = PaleoMapDocument(name="Map A", linked_target_horizon="H1")
    tree.set_documents([doc])
    tree.set_active_document(doc)

    root = tree.tree.topLevelItem(0)
    doc_item = root.child(0)
    # Only 4 editable layers, no reference group
    assert doc_item.childCount() == 4
