from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGraphicsView, QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.mapping.document_io import apply_features_to_document
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_helpers import active_map_document


class MappingPage(QWidget):
    """GIS-shell 编图 page: toolbar, layer tree, edit view, attribute table."""

    draft_saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MappingPage")
        self._active_document = None

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
        self.toolbar.snap_toggled.connect(self._on_snap_toggled)
        self.toolbar.save_draft_requested.connect(self.save_draft)

        self.layer_tree.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self.layer_tree.document_selected.connect(self._on_document_selected)
        self.attribute_table.property_changed.connect(self._on_property_changed)

        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.selection_ids_changed.connect(self._on_selection_ids_changed)
            scene.document_dirty_changed.connect(self._on_document_dirty_changed)
            scene.command_stack_changed.connect(self._sync_undo_redo_enabled)

        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._on_tool_changed(self.toolbar.current_tool())

    def is_dirty(self) -> bool:
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            return scene.is_dirty()
        return False

    def active_document(self):
        return self._active_document

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        document = active_map_document(documents)
        self._active_document = document
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.load_document(document)
            # Apply current layer visibility from tree.
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self.layer_tree.layer_is_visible(key))
        self.attribute_table.set_feature(None)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()

    def save_draft(self) -> bool:
        """Write scene features back into the active PaleoMapDocument and clear dirty."""
        doc = self._active_document
        scene = self._edit_scene()
        if doc is None or scene is None:
            return False
        # Topology refresh before export (warnings only; does not block save).
        scene.refresh_topology()
        features = scene.export_features()
        apply_features_to_document(doc, features)
        scene.set_dirty(False)
        self._sync_save_enabled()
        self.draft_saved.emit(doc)
        return True

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

    def _on_snap_toggled(self, enabled: bool) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.set_snap_enabled(enabled)

    def _on_layer_visibility_changed(self, kind: str, visible: bool) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.set_layer_visible(kind, visible)

    def _on_document_selected(self, document) -> None:
        self._active_document = document
        scene = self._edit_scene()
        if scene is not None:
            scene.load_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self.layer_tree.layer_is_visible(key))
        self.attribute_table.set_feature(None)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()

    def _on_property_changed(self, feature_id: str, key: str, value: object) -> None:
        scene = self._edit_scene()
        if scene is None:
            return
        if scene.apply_property_change(feature_id, key, value):
            item = scene.item_by_id(feature_id)
            if item is not None:
                self.attribute_table.set_feature(item.to_record())

    def _on_undo(self) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.undo()
        self._sync_undo_redo_enabled()
        self._refresh_attribute_from_selection()

    def _on_redo(self) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.redo()
        self._sync_undo_redo_enabled()
        self._refresh_attribute_from_selection()

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

    def _refresh_attribute_from_selection(self) -> None:
        scene = self._edit_scene()
        if scene is None:
            self.attribute_table.set_feature(None)
            return
        ids = scene.selected_feature_ids()
        self._on_selection_ids_changed(ids)

    def _on_document_dirty_changed(self, _dirty: bool) -> None:
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()

    def _sync_undo_redo_enabled(self) -> None:
        scene = self._edit_scene()
        stack = scene.command_stack() if scene is not None else None
        self.toolbar.undo_btn.setEnabled(bool(stack and stack.can_undo()))
        self.toolbar.redo_btn.setEnabled(bool(stack and stack.can_redo()))

    def _sync_save_enabled(self) -> None:
        can_save = self._active_document is not None and self.is_dirty()
        self.toolbar.save_draft_btn.setEnabled(can_save)
