from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_layer_tree import LAYER_KEYS, MapLayerTree


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
