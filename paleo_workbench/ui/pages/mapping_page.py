from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGraphicsView,
    QHBoxLayout,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.document_io import apply_features_to_document
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_helpers import (
    active_map_document,
    field_value,
    preview_payload_from_document,
    preview_payload_from_features,
)


class MappingPage(QWidget):
    """GIS-shell 编图 page: toolbar, layer tree, edit view / chrome preview, attribute table."""

    draft_saved = Signal(object)
    mapping_context_changed = Signal(dict)
    generate_demo_draft_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MappingPage")
        self._active_document = None
        self._preview_mode = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(10)

        self.toolbar = MapEditToolbar()
        outer.addWidget(self.toolbar)

        mid = QHBoxLayout()
        mid.setSpacing(10)

        self.layer_tree = MapLayerTree()
        mid.addWidget(self.layer_tree, 0)

        self.center_stack = QStackedWidget()
        self.center_stack.setObjectName("MappingCenterStack")

        self.edit_view = MapEditView()
        self.center_stack.addWidget(self.edit_view)

        preview_host = QWidget()
        preview_host.setObjectName("MappingPreviewHost")
        preview_layout = QHBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)
        self.canvas_panel = MapCanvasPanel()
        self.chrome_panel = MapChromePanel()
        preview_layout.addWidget(self.canvas_panel, 1)
        preview_layout.addWidget(self.chrome_panel, 0)
        self.center_stack.addWidget(preview_host)

        mid.addWidget(self.center_stack, 1)
        outer.addLayout(mid, 1)

        self.attribute_table = MapAttributeTable()
        self.attribute_table.setMaximumHeight(160)
        outer.addWidget(self.attribute_table, 0)

        self.toolbar.tool_changed.connect(self._on_tool_changed)
        self.toolbar.undo_requested.connect(self._on_undo)
        self.toolbar.redo_requested.connect(self._on_redo)
        self.toolbar.snap_toggled.connect(self._on_snap_toggled)
        self.toolbar.preview_toggled.connect(self._on_preview_toggled)
        self.toolbar.topology_rebuild_requested.connect(self.rebuild_topology)
        self.toolbar.merge_facies_requested.connect(self.merge_selected_facies)
        self.toolbar.split_facies_requested.connect(self.split_selected_facies)
        self.toolbar.save_draft_requested.connect(self.save_draft)
        self.toolbar.generate_demo_draft_requested.connect(self.generate_demo_draft_requested.emit)
        self.chrome_panel.save_btn.clicked.connect(self.save_draft)

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
        self._apply_mode_ui()
        self._emit_mapping_context()

    def is_dirty(self) -> bool:
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            return scene.is_dirty()
        return False

    def is_preview_mode(self) -> bool:
        return self._preview_mode

    def set_preview_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._preview_mode == enabled:
            if enabled:
                self._refresh_preview()
            return
        self._preview_mode = enabled
        self.toolbar.set_preview_mode(enabled)
        self._apply_mode_ui()
        if enabled:
            self._refresh_preview()
        self._emit_mapping_context()

    def active_document(self):
        return self._active_document

    def mapping_context(self) -> dict:
        """Snapshot of active map name / horizon / dirty for the sidebar."""
        doc = self._active_document
        return {
            "map_name": getattr(doc, "name", None) or "未选择",
            "horizon": getattr(doc, "linked_target_horizon", None) or "",
            "dirty": self.is_dirty(),
            "preview": self._preview_mode,
        }

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        document = active_map_document(documents)
        self._active_document = document
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.load_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self.layer_tree.layer_is_visible(key))
        self.attribute_table.set_feature(None)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()

    def save_draft(self) -> bool:
        """Write scene features back into the active PaleoMapDocument and clear dirty."""
        doc = self._active_document
        scene = self._edit_scene()
        if doc is None or scene is None:
            return False
        scene.refresh_topology()
        features = scene.export_features()
        apply_features_to_document(doc, features)
        scene.set_dirty(False)
        self._sync_save_enabled()
        if self._preview_mode:
            self._refresh_preview()
        self.draft_saved.emit(doc)
        self._emit_mapping_context()
        return True

    def rebuild_topology(self) -> dict:
        """Forced shared-node snap + full topology validation."""
        scene = self._edit_scene()
        if scene is None:
            return {"changed": False, "snapped_count": 0}
        report = scene.rebuild_topology_forced()
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._refresh_attribute_from_selection()
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()
        return report

    def merge_selected_facies(self) -> str | None:
        scene = self._edit_scene()
        if scene is None:
            return None
        new_id = scene.merge_selected_facies()
        if new_id is None:
            QMessageBox.information(
                self,
                "合并相带",
                "请选中恰好两个相带多边形后再合并（需 shapely）。",
            )
            return None
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._refresh_attribute_from_selection()
        self._emit_mapping_context()
        return new_id

    def split_selected_facies(self) -> list[str] | None:
        scene = self._edit_scene()
        if scene is None:
            return None
        new_ids = scene.split_selected_facies_by_line()
        if not new_ids:
            QMessageBox.information(
                self,
                "分割相带",
                "请同时选中一个相带和一个切割线（线需穿过多边形，需 shapely）。",
            )
            return None
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._refresh_attribute_from_selection()
        self._emit_mapping_context()
        return new_ids

    def _edit_scene(self) -> MapEditScene | None:
        scene = self.edit_view.scene()
        return scene if isinstance(scene, MapEditScene) else None

    def _on_preview_toggled(self, enabled: bool) -> None:
        self.set_preview_mode(enabled)

    def _apply_mode_ui(self) -> None:
        self.center_stack.setCurrentIndex(1 if self._preview_mode else 0)
        self.attribute_table.setVisible(not self._preview_mode)

    def _refresh_preview(self) -> None:
        doc = self._active_document
        scene = self._edit_scene()
        period = str(field_value(doc, "linked_target_horizon", "") or "") if doc else ""
        if scene is not None and (scene.is_dirty() or doc is not None):
            # Always prefer live scene geometry so unsaved edits appear in preview.
            features, wells, period = preview_payload_from_features(
                scene.export_features(),
                period_name=period,
            )
            # If scene is empty but document still has saved data (edge), fall back.
            if not features and not wells and doc is not None and not scene.is_dirty():
                features, wells, period = preview_payload_from_document(doc)
        elif doc is not None:
            features, wells, period = preview_payload_from_document(doc)
        else:
            features, wells, period = [], [], ""
        self.canvas_panel.load_preview(features, wells=wells, period_name=period)
        self.chrome_panel.update_state(doc)

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
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()

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
        if self._preview_mode:
            self._refresh_preview()

    def _on_redo(self) -> None:
        scene = self._edit_scene()
        if scene is not None:
            scene.redo()
        self._sync_undo_redo_enabled()
        self._refresh_attribute_from_selection()
        if self._preview_mode:
            self._refresh_preview()

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
        self._emit_mapping_context()

    def _sync_undo_redo_enabled(self) -> None:
        scene = self._edit_scene()
        stack = scene.command_stack() if scene is not None else None
        self.toolbar.undo_btn.setEnabled(bool(stack and stack.can_undo()))
        self.toolbar.redo_btn.setEnabled(bool(stack and stack.can_redo()))

    def _sync_save_enabled(self) -> None:
        can_save = self._active_document is not None and self.is_dirty()
        self.toolbar.save_draft_btn.setEnabled(can_save)
        self.chrome_panel.save_btn.setEnabled(can_save)

    def _emit_mapping_context(self) -> None:
        self.mapping_context_changed.emit(self.mapping_context())
