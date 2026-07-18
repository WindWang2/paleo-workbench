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
from paleo_workbench.mapping.reference_layers import ReferenceLayerError, ReferenceLayerService
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel
from paleo_workbench.ui.pages.map_workbench_bottom import MapWorkbenchBottom
from paleo_workbench.ui.pages.mapping_helpers import (
    active_map_document,
    field_value,
    preview_payload_from_document,
    preview_payload_from_features,
)
from geoviz import CancellationToken
from paleo_workbench.ui.pages.contour_draft_worker import (
    ContourDraftResult,
    ContourDraftWorker,
    commit_contour_drafts,
)
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob


class MappingPage(QWidget):
    """GIS-shell 编图 page: toolbar, layer tree, edit view / chrome preview, attribute table."""

    draft_saved = Signal(object)
    mapping_context_changed = Signal(dict)
    generate_demo_draft_requested = Signal()
    contour_drafts_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MappingPage")
        self._active_document = None
        self._project = None
        self._preview_mode = False
        self._reference_service = ReferenceLayerService()
        self._contour_job = OwnedWorkerJob(self)
        self._contour_job.released.connect(self._clear_contour_job)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_2)

        self.toolbar = MapEditToolbar()
        outer.addWidget(self.toolbar)

        mid = QHBoxLayout()
        mid.setSpacing(tokens.SPACE_2)

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
        preview_layout.setSpacing(tokens.SPACE_2)
        self.canvas_panel = MapCanvasPanel()
        self.chrome_panel = MapChromePanel()
        preview_layout.addWidget(self.canvas_panel, 1)
        preview_layout.addWidget(self.chrome_panel, 0)
        self.center_stack.addWidget(preview_host)

        mid.addWidget(self.center_stack, 1)
        self.reference_panel = MapReferencePanel()
        mid.addWidget(self.reference_panel, 0)
        outer.addLayout(mid, 1)

        self.bottom_workbench = MapWorkbenchBottom()
        self.bottom_workbench.setMaximumHeight(220)
        self.attribute_table = self.bottom_workbench.attribute_table
        self.attribute_table.setMaximumHeight(220)
        outer.addWidget(self.bottom_workbench, 0)

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
        self.bottom_workbench.factor_shelf.contour_draft_requested.connect(
            self._on_contour_draft_requested
        )

        self.layer_tree.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self.layer_tree.document_selected.connect(self._on_document_selected)
        self.attribute_table.property_changed.connect(self._on_property_changed)
        self.reference_panel.reference_visibility_changed.connect(self._on_reference_visibility_changed)
        self.reference_panel.reference_opacity_changed.connect(self._on_reference_opacity_changed)
        self.edit_view.view_state_changed.connect(self.reference_panel.set_view_state)

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

    def set_project(self, project) -> None:
        """Bind live ProjectDocument for ContourDraft generation from factor shelf."""
        self._project = project

    def mapping_context(self) -> dict:
        """Snapshot of active map name / horizon / dirty for the sidebar."""
        doc = self._active_document
        return {
            "map_name": getattr(doc, "name", None) or "未选择",
            "horizon": getattr(doc, "linked_target_horizon", None) or "",
            "dirty": self.is_dirty(),
            "preview": self._preview_mode,
        }

    def update_state(
        self,
        map_documents: list | tuple | None,
        *,
        factor_tasks: list | tuple | None = None,
        project_crs: str | None = None,
    ) -> None:
        documents = list(map_documents or [])
        prefer_id = getattr(self._active_document, "id", None)
        document = active_map_document(documents, prefer_id=prefer_id)
        previous = self._active_document
        self._active_document = document
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            # Avoid wiping dirty geometry when the same document is re-pushed
            # from project refresh (e.g. other pages update shell state).
            same_doc = (
                previous is not None
                and document is not None
                and getattr(previous, "id", None) == getattr(document, "id", None)
                and previous is document
            )
            if not same_doc or not scene.is_dirty():
                scene.load_document(document)
                self._restore_view_state_from_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self.layer_tree.layer_is_visible(key))
            self._sync_reference_snap_points(scene, document)
        self.attribute_table.set_feature(None)
        self._publish_reference_layers(document)
        self.bottom_workbench.factor_shelf.update_state(list(factor_tasks or []))
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()

    def _on_contour_draft_requested(self) -> None:
        """Schedule ContourDraft extraction and commit on the GUI thread."""
        from PySide6.QtWidgets import QMessageBox

        if self._project is None:
            QMessageBox.information(self, "等值线初稿", "请先打开或绑定工程。")
            return
        if self._contour_job.is_running:
            return
        self.bottom_workbench.factor_shelf.contour_draft_btn.setEnabled(False)
        token = CancellationToken()
        worker = ContourDraftWorker(self._project, cancellation_token=token)
        self._contour_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_contour_completed),
                (worker.failed, self._on_contour_failed),
            ),
            cancel=token.cancel,
            target=self._project,
        )

    def _on_contour_completed(self, result: ContourDraftResult) -> None:
        from PySide6.QtWidgets import QMessageBox

        target = self._contour_job.target
        if target is None or self._project is not target:
            return
        drafts = commit_contour_drafts(target, result)
        if not drafts:
            QMessageBox.information(
                self,
                "等值线初稿",
                "没有可提取的单因素网格。请先在制备页生成单因素图。",
            )
            return
        # Prefer the map linked to the last draft as active document.
        prefer = None
        if drafts[-1].linked_map_document_id:
            prefer = next(
                (
                    d
                    for d in self._project.paleomap_documents
                    if d.id == drafts[-1].linked_map_document_id
                ),
                None,
            )
        if prefer is not None:
            self._active_document = prefer
        self.update_state(
            self._project.paleomap_documents,
            factor_tasks=self._project.factor_map_tasks,
            project_crs=getattr(
                getattr(self._project, "coordinate", None), "project_crs", None
            ),
        )
        self.contour_drafts_updated.emit()
        QMessageBox.information(
            self,
            "等值线初稿",
            f"已生成 {len(drafts)} 份等值线并加载到编图。",
        )

    def _on_contour_failed(self, message: str) -> None:
        if self._contour_job.target is not self._project:
            return
        self.bottom_workbench.factor_shelf.contour_draft_btn.setToolTip(
            f"等值线初稿失败：{message}"
        )

    def _clear_contour_job(self) -> None:
        self.bottom_workbench.factor_shelf.contour_draft_btn.setEnabled(True)

    def shutdown_workers(self, wait_ms: int = 3_000) -> None:
        self._contour_job.shutdown(wait_ms)

    def save_draft(self) -> bool:
        """Write scene features back into the active PaleoMapDocument and clear dirty."""
        doc = self._active_document
        scene = self._edit_scene()
        if doc is None or scene is None:
            return False
        scene.refresh_topology()
        valid, issues = scene.validate_for_save()
        self.bottom_workbench.topology_panel.set_issues(issues)
        if not valid:
            from PySide6.QtWidgets import QMessageBox

            n = len(issues) if issues else 0
            QMessageBox.warning(
                self,
                "无法保存编图草稿",
                f"拓扑检查未通过（{n} 项问题）。请查看底部拓扑面板并修复后再保存。",
            )
            return False
        features = scene.export_features()
        apply_features_to_document(doc, features)
        # Persist viewport (center/scale) without clobbering provenance keys
        # like is_demo_draft / generator / seed.
        self._merge_view_state_into_document(doc)
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
        self.bottom_workbench.setVisible(not self._preview_mode)

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
        scene = self._edit_scene()
        if (
            scene is not None
            and scene.is_dirty()
            and self._active_document is not None
            and document is not self._active_document
        ):
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "未保存的编图修改",
                "当前图件有未保存修改。是否先保存草稿？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                # Reselect previous document in the tree without re-entering load.
                self.layer_tree.set_active_document(self._active_document)
                return
            if reply == QMessageBox.StandardButton.Save:
                if not self.save_draft():
                    self.layer_tree.set_active_document(self._active_document)
                    return
        self._active_document = document
        if scene is not None:
            scene.load_document(document)
            self._restore_view_state_from_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self.layer_tree.layer_is_visible(key))
        self.attribute_table.set_feature(None)
        self._publish_reference_layers(document)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()

    def _publish_reference_layers(self, document) -> None:
        """Refresh offline status then push descriptors into the reference dock."""
        layers = list(getattr(document, "reference_layers", []) or []) if document else []
        for layer in layers:
            ReferenceLayerService.refresh_status(layer)
        self.reference_panel.set_layers(layers)

    def _merge_view_state_into_document(self, doc) -> None:
        """Write live viewport into doc.view_state; keep non-viewport provenance keys."""
        live = self.edit_view.view_state()
        merged = dict(getattr(doc, "view_state", None) or {})
        if "center" in live:
            center = live["center"]
            if isinstance(center, (list, tuple)) and len(center) >= 2:
                merged["center"] = [float(center[0]), float(center[1])]
            else:
                merged["center"] = center
        if "scale" in live:
            merged["scale"] = float(live["scale"])
        doc.view_state = merged

    def _restore_view_state_from_document(self, document) -> None:
        """Apply saved center/scale when present; ignore pure provenance dicts."""
        if document is None:
            return
        vs = getattr(document, "view_state", None) or {}
        if "center" not in vs and "scale" not in vs:
            return
        self.edit_view.apply_view_state(vs)
        self.reference_panel.set_view_state(self.edit_view.view_state())

    def _on_property_changed(self, feature_id: str, key: str, value: object) -> None:
        scene = self._edit_scene()
        if scene is None:
            return
        if scene.apply_property_change(feature_id, key, value):
            item = scene.item_by_id(feature_id)
            if item is not None:
                self.attribute_table.set_feature(item.to_record())

    def _reference_layer(self, layer_id: str):
        for layer in list(getattr(self._active_document, "reference_layers", []) or []):
            if layer.id == layer_id:
                return layer
        return None

    def _on_reference_visibility_changed(self, layer_id: str, visible: bool) -> None:
        layer = self._reference_layer(layer_id)
        if layer is not None:
            layer.visible = bool(visible)
            self._emit_mapping_context()

    def _on_reference_opacity_changed(self, layer_id: str, opacity: float) -> None:
        layer = self._reference_layer(layer_id)
        if layer is not None:
            layer.opacity = max(0.0, min(1.0, float(opacity)))
            self._emit_mapping_context()

    def _sync_reference_snap_points(self, scene: MapEditScene, document) -> None:
        points: list[tuple[float, float]] = []
        for layer in list(getattr(document, "reference_layers", []) or []):
            ReferenceLayerService.refresh_status(layer)
            if not layer.participates_in_snap or layer.source_kind != "vector":
                continue
            if layer.status != "ready":
                continue
            try:
                points.extend(self._reference_service.vector_snap_points(layer))
            except ReferenceLayerError:
                continue
        scene.set_reference_snap_points(points)

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
