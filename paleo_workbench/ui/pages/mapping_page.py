from __future__ import annotations

from PySide6.QtWidgets import QGraphicsView, QHBoxLayout, QVBoxLayout, QWidget

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

        self.toolbar.tool_changed.connect(self._on_tool_changed)
        self.toolbar.undo_requested.connect(self._on_undo)
        self.toolbar.redo_requested.connect(self._on_redo)

        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.selection_ids_changed.connect(self._on_selection_ids_changed)
            scene.document_dirty_changed.connect(self._on_document_dirty_changed)
            scene.command_stack_changed.connect(self._sync_undo_redo_enabled)

        self._sync_undo_redo_enabled()
        self._on_tool_changed(self.toolbar.current_tool())

    def is_dirty(self) -> bool:
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            return scene.is_dirty()
        return False

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        document = active_map_document(documents)
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.load_document(document)
        self.attribute_table.set_feature(None)
        self._sync_undo_redo_enabled()

    def _edit_scene(self) -> MapEditScene | None:
        scene = self.edit_view.scene()
        return scene if isinstance(scene, MapEditScene) else None

    def _on_tool_changed(self, tool_id: str) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.set_tool(tool_id)
        if tool_id == "select":
            self.edit_view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        else:
            self.edit_view.setDragMode(QGraphicsView.DragMode.NoDrag)

    def _on_undo(self) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.undo()
        self._sync_undo_redo_enabled()

    def _on_redo(self) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.redo()
        self._sync_undo_redo_enabled()

    def _on_selection_ids_changed(self, ids: list) -> None:
        scene = self._edit_scene()
        if not ids or scene is None:
            self.attribute_table.set_feature(None)
            return
        item = scene.item_by_id(str(ids[0]))
        if item is None:
            self.attribute_table.set_feature(None)
            return
        self.attribute_table.set_feature(item.to_record())

    def _on_document_dirty_changed(self, _dirty: bool) -> None:
        self._sync_undo_redo_enabled()

    def _sync_undo_redo_enabled(self) -> None:
        scene = self._edit_scene()
        stack = scene.command_stack() if scene is not None else None
        self.toolbar.undo_btn.setEnabled(bool(stack and stack.can_undo()))
        self.toolbar.redo_btn.setEnabled(bool(stack and stack.can_redo()))
