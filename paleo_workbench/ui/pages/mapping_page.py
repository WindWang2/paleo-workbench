from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_helpers import active_map_document


class MappingPage(QWidget):
    """GIS-shell 编图 page: toolbar, layer tree, edit view, attribute table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MappingPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        self.toolbar = MapEditToolbar()
        outer.addWidget(self.toolbar)

        mid = QHBoxLayout()
        mid.setSpacing(10)

        self.layer_tree = MapLayerTree()
        mid.addWidget(self.layer_tree, 0)

        self.edit_view = MapEditView()
        mid.addWidget(self.edit_view, 1)

        outer.addLayout(mid, 1)

        self.attribute_table = MapAttributeTable()
        self.attribute_table.setMaximumHeight(160)
        outer.addWidget(self.attribute_table, 0)

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        document = active_map_document(documents)
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.load_document(document)
        # Attribute table stays empty without selection (Task 4+).
        self.attribute_table.set_feature(None)
