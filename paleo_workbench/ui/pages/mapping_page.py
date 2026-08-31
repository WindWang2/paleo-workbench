from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsItem,
    QGraphicsView,
    QHBoxLayout,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.document_io import apply_features_to_document
from paleo_workbench.mapping.map_authoring import MapAuthoringDocument, feature_to_record
from paleo_workbench.mapping.map_document_snapshot import extent_for_snapshot
from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex, SnappingService
from paleo_workbench.mapping.map_scene_adapter import LegacyDocumentSceneAdapter
from paleo_workbench.mapping.map_tools import (
    AddLineTool,
    AddPointTool,
    AddPolygonTool,
    MapToolController,
    MeasureDistanceTool,
    MoveFeatureTool,
    PanTool,
    RectangleSelectTool,
    SelectTool,
    VertexTool,
    ZoomTool,
)
from paleo_workbench.mapping.topology import TopologyService
from paleo_workbench.mapping.reference_layers import ReferenceLayerError, ReferenceLayerService
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_dock_manager import MapDockManager, panel_icon
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_reference_panel import MapReferencePanel
from paleo_workbench.ui.pages.map_workbench_bottom import MapWorkbenchBottom
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from paleo_workbench.ui.map_action_controller import MapActionController, MapActionState
from paleo_workbench.ui.map_layer_properties import MapLayerPropertiesDialog
from paleo_workbench.ui.map_status_bar import MapStatusBar
from paleo_workbench.viz.mapping_helpers import (
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
from paleo_workbench.ui.map_export_worker import snapshot_map_export, start_map_export_job
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

logger = logging.getLogger(__name__)


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
        self._project_path: str | None = None
        self._project_crs: str | None = None
        self._factor_tasks_by_overlay_id: dict[str, object] = {}
        self._native_factor_scene = None
        self._unified_scene_adapter = LegacyDocumentSceneAdapter()
        self._unified_document_id: str | None = None
        self._authoring_document: MapAuthoringDocument | None = None
        self._unified_authoring_mode = False
        # Authoring revision tracking: raw (data_revision, session revision) keys
        # are translated into small effective integers so unchanged refreshes
        # skip feature rebuilding end to end. Reset when the authoring document
        # object is replaced.
        self._unified_raw_revisions: dict[str, tuple] = {}
        self._unified_effective_revisions: dict[str, int] = {}
        # Strong reference: while the page holds it, its id() cannot be reused,
        # so owner identity comparisons stay valid.
        self._unified_revisions_owner: object | None = None
        self._map_tools = MapToolController()
        self._snapping = SnappingService()
        self._topology = TopologyService()
        self._last_measurement: float | None = None
        self._presentation_dirty = False
        self._suppressed_layer_ids: set[str] = set()
        self._preview_mode = False
        self._canvas_priority = False
        self._reference_service = ReferenceLayerService()
        self._contour_job = OwnedWorkerJob(self)
        self._contour_job.released.connect(self._clear_contour_job)
        self._export_job = OwnedWorkerJob(self)
        self._export_job.released.connect(self._on_export_job_released)
        self._export_busy = False
        self._pending_export: dict | None = None
        # Attribute-table record cache keyed by (layer, data revision) so
        # selection-only tool operations never reconvert every feature.
        self._attribute_table_records: tuple[object, int, list[dict[str, Any]]] | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_2)

        # True QAction/QToolBar command surface: one icon-only strip carrying
        # every map action.  ``MapEditToolbar`` remains a hidden compatibility
        # shim while downstream callers migrate to actions.
        self.action_controller = MapActionController(self)
        self.map_toolbars = QWidget(self)
        self.map_toolbars.setObjectName("MapAuthoringToolbars")
        toolbar_layout = QHBoxLayout(self.map_toolbars)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(tokens.SPACE_1)
        # Single command strip (QGIS-theme icons); logical groups are
        # separated by toolbar separators.
        toolbar_layout.addWidget(self.action_controller.toolbar(
            "Map Authoring", (
                ("pan", "zoom_in", "zoom_out", "full_extent", "previous_extent", "next_extent", "refresh"),
                ("identify", "select", "select_rectangle", "measure_distance", "clear_selection", "select_all", "invert_selection"),
                ("toggle_editing", "save_edits", "rollback"),
                ("add_point", "add_line", "add_polygon", "move_feature", "vertex"),
                ("undo", "redo", "delete_selected"),
                ("split", "merge"),
                ("snapping", "topology", "cancel"),
            ), self.map_toolbars
        ), 1)
        outer.addWidget(self.map_toolbars)

        self.toolbar = MapEditToolbar()
        self.toolbar.setVisible(False)
        outer.addWidget(self.toolbar)

        # Panel manager: collapsible side docks (icon rails) around the central
        # canvas, plus a checkable 面板 menu exposed on the toolbar strip.
        self.dock_manager = MapDockManager(self)

        self.layer_tree_stack = QStackedWidget()
        self.layer_tree = MapLayerTree()
        self.layer_tree_stack.addWidget(self.layer_tree)
        self._native_layer_tree = None
        self.dock_manager.add_panel(
            "layers", "图层面板", "panel-layers", self.layer_tree_stack, side="left", checked=True
        )

        self.center_stack = QStackedWidget()
        self.center_stack.setObjectName("MappingCenterStack")
        self.center_stack.setMinimumWidth(360)

        self.edit_view = MapEditView()
        self.center_stack.addWidget(self.edit_view)

        preview_host = QWidget()
        preview_host.setObjectName("MappingPreviewHost")
        preview_layout = QHBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(tokens.SPACE_2)
        self.preview_canvas_stack = QStackedWidget()
        self.canvas_panel = MapCanvasPanel()
        self.unified_canvas = UnifiedMapCanvas()
        self.unified_canvas.set_map_tool_controller(self._map_tools)
        self.unified_canvas.set_overlay_provider(self._unified_overlay_state)
        self.preview_canvas_stack.addWidget(self.canvas_panel)
        self.preview_canvas_stack.addWidget(self.unified_canvas)
        self.chrome_panel = MapChromePanel()
        preview_layout.addWidget(self.preview_canvas_stack, 1)
        self.center_stack.addWidget(preview_host)

        self.reference_panel = MapReferencePanel()
        self.dock_manager.add_panel(
            "reference", "参考图面板", "panel-reference", self.reference_panel, side="right", checked=True
        )
        self.dock_manager.add_panel(
            "chrome", "图面要素面板", "panel-chrome", self.chrome_panel, side="right", checked=False
        )
        # Composition authoring (P0-D): template-driven professional layout
        # with component CRUD/undo and physical-size PNG/SVG/PDF export.
        from paleo_workbench.ui.pages.composition_panel import CompositionPanel

        self.composition_panel = CompositionPanel()
        self.dock_manager.add_panel(
            "composer", "组图面板", "panel-chrome", self.composition_panel, side="right", checked=False
        )

        # Rails sit outside the splitter so collapsing a docked panel area
        # returns its space to the central canvas.
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(tokens.SPACE_1)
        mid.addWidget(self.dock_manager.left_dock.rail, 0)
        mid_splitter = QSplitter(Qt.Orientation.Horizontal)
        mid_splitter.setObjectName("MappingDockSplitter")
        mid_splitter.addWidget(self.dock_manager.left_dock.area)
        mid_splitter.addWidget(self.center_stack)
        mid_splitter.addWidget(self.dock_manager.right_dock.area)
        mid_splitter.setStretchFactor(0, 0)
        mid_splitter.setStretchFactor(1, 1)
        mid_splitter.setStretchFactor(2, 0)
        mid_splitter.setSizes([300, 1000, 280])
        mid.addWidget(mid_splitter, 1)
        mid.addWidget(self.dock_manager.right_dock.rail, 0)
        outer.addLayout(mid, 1)

        self.status_bar = MapStatusBar(self)
        outer.addWidget(self.status_bar)

        self.bottom_workbench = MapWorkbenchBottom()
        self.bottom_workbench.setMaximumHeight(220)
        self.attribute_table = self.bottom_workbench.attribute_table
        self.attribute_table.setMaximumHeight(220)
        outer.addWidget(self.bottom_workbench, 0)
        self.dock_manager.register_bottom(
            "bottom", "底部工作区", "panel-bottom", self.bottom_workbench, self._apply_mode_ui
        )

        # Panels menu lives on the right end of the command strip.
        panels_button = QToolButton(self.map_toolbars)
        panels_button.setObjectName("MapPanelsMenuButton")
        panels_button.setIcon(panel_icon("panel-manager"))
        panels_button.setIconSize(QSize(18, 18))
        panels_button.setToolTip("面板")
        panels_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        panels_button.setMenu(self.dock_manager.panels_menu(panels_button))
        toolbar_layout.addWidget(panels_button, 0)

        self.toolbar.tool_changed.connect(self._on_tool_changed)
        self.toolbar.undo_requested.connect(self._on_undo)
        self.toolbar.redo_requested.connect(self._on_redo)
        self.toolbar.snap_toggled.connect(self._on_snap_toggled)
        self.toolbar.preview_toggled.connect(self._on_preview_toggled)
        self.toolbar.canvas_priority_toggled.connect(self.set_canvas_priority)
        self.toolbar.topology_rebuild_requested.connect(self.rebuild_topology)
        self.toolbar.merge_facies_requested.connect(self.merge_selected_facies)
        self.toolbar.split_facies_requested.connect(self.split_selected_facies)
        self.toolbar.save_draft_requested.connect(self.save_draft)
        self.toolbar.generate_demo_draft_requested.connect(self.generate_demo_draft_requested.emit)
        self.action_controller.tool_requested.connect(self._on_action_tool_requested)
        self.action_controller.command_requested.connect(self._on_action_command_requested)
        self.unified_canvas.tool_operation.connect(self._on_unified_tool_operation)
        self.unified_canvas.map_position_changed.connect(self._on_unified_cursor_position)
        self.unified_canvas.extent_changed.connect(self._on_unified_extent_changed)
        self.unified_canvas.backend_status_changed.connect(lambda _status: self._sync_map_status())
        self.chrome_panel.save_btn.clicked.connect(self.save_draft)
        self.chrome_panel.chrome_changed.connect(self._on_chrome_changed)
        self.bottom_workbench.factor_shelf.create_factor_map_requested.connect(
            self._on_create_factor_map_requested
        )
        self.bottom_workbench.factor_shelf.contour_draft_requested.connect(
            self._on_contour_draft_requested
        )
        self.bottom_workbench.factor_shelf.fault_interpretation_requested.connect(
            self._on_fault_interpretation_requested
        )
        self.bottom_workbench.factor_shelf.map_product_requested.connect(
            self._on_map_product_requested
        )
        self.bottom_workbench.factor_shelf.factor_overlay_requested.connect(
            self._on_overlay_requested
        )
        self.bottom_workbench.topology_panel.locate_requested.connect(
            self._on_topology_locate_requested
        )

        self.layer_tree.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self.layer_tree.document_selected.connect(self._on_document_selected)
        self.attribute_table.property_changed.connect(self._on_property_changed)
        self.attribute_table.feature_selection_requested.connect(self._on_attribute_feature_selected)
        self._pending_opacity_refresh = False
        self._opacity_refresh = QTimer(self)
        self._opacity_refresh.setSingleShot(True)
        self._opacity_refresh.setInterval(100)
        self._opacity_refresh.timeout.connect(self._flush_reference_opacity)
        self.reference_panel.reference_visibility_changed.connect(self._on_reference_visibility_changed)
        self.reference_panel.reference_opacity_changed.connect(self._on_reference_opacity_changed)
        self.reference_panel.opacity_slider.sliderReleased.connect(self._flush_reference_opacity)
        self.edit_view.view_state_changed.connect(self.reference_panel.set_view_state)
        self.edit_view.view_state_changed.connect(
            self.bottom_workbench.factor_shelf.set_view_state
        )
        self.edit_view.cursor_position_changed.connect(
            self.bottom_workbench.factor_shelf.set_cursor_position
        )
        # The reference dock's overlay request shares the factor overlay path.
        self.reference_panel.overlay_requested.connect(self._on_overlay_requested)

        scene = self.edit_view.scene()
        if isinstance(scene, MapEditScene):
            scene.selection_ids_changed.connect(self._on_selection_ids_changed)
            scene.document_dirty_changed.connect(self._on_document_dirty_changed)
            scene.command_stack_changed.connect(self._sync_undo_redo_enabled)
            scene.topology_issues_changed.connect(
                self.bottom_workbench.topology_panel.set_issues
            )
            scene.command_stack_changed.connect(self._refresh_unified_composition)

        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._sync_action_state()
        self._sync_map_status()
        self._on_tool_changed(self.toolbar.current_tool())
        self._apply_mode_ui()
        self._emit_mapping_context()

    def is_dirty(self) -> bool:
        if self._presentation_dirty:
            return True
        if self._authoring_document is not None and self._authoring_document.is_dirty():
            return True
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

    def is_canvas_priority(self) -> bool:
        return self._canvas_priority

    def set_canvas_priority(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._canvas_priority == enabled:
            return
        self._canvas_priority = enabled
        # Preserve the established explicit-widget visibility contract for the
        # legacy tree (tests and accessibility consumers query it directly), while
        # the dock manager reflects the same state on its rail buttons.
        self.dock_manager.set_panel_visible("layers", not enabled)
        self.layer_tree.setVisible(not enabled)
        if self._native_layer_tree is not None:
            self._native_layer_tree.setVisible(not enabled)
        self.dock_manager.set_panel_visible("reference", not enabled)
        self._apply_mode_ui()
        if self.toolbar.canvas_priority_btn.isChecked() != enabled:
            self.toolbar.canvas_priority_btn.blockSignals(True)
            self.toolbar.canvas_priority_btn.setChecked(enabled)
            self.toolbar.canvas_priority_btn.blockSignals(False)
        self._emit_mapping_context()

    def active_document(self):
        return self._active_document

    def set_project(self, project) -> None:
        """Bind live ProjectDocument for ContourDraft generation from factor shelf."""
        self._project = project

    def set_project_path(self, path) -> None:
        """Receive the open ``*.paleo.json`` path (AppShell broadcast).

        Fault interpretation saves derive their artifact directory from the
        real project file; without the path the action stays disabled rather
        than writing into a phantom artifacts tree.
        """
        self._project_path = str(path) if path else None
        has = self._project_path is not None
        self.bottom_workbench.factor_shelf.fault_interpretation_btn.setEnabled(has)

    def _on_map_product_requested(self) -> None:
        """Assemble the multi-factor paleogeographic product (P1-D): valid
        factor grids + interpretation refs + composition → ONE catalog
        OUTPUT version with full lineage. Fail-closed; nothing is laundered."""
        import json as _json
        import tempfile
        from PySide6.QtWidgets import QMessageBox

        from paleo_workbench.workflow.map_product import (
            MapProductAssembly,
            assemble_map_product,
        )

        if self._project is None or not getattr(self, "_project_path", None):
            QMessageBox.information(self, "古地理成果", "请先打开并保存工程。")
            return
        tasks = [
            t
            for t in (getattr(self._project, "factor_map_tasks", None) or [])
            if getattr(t, "status", "") == "complete"
            and getattr(t, "grid_artifact_version_id", None)
            and str(getattr(t, "source_kind", "")) not in ("mock", "mixed")
        ]
        if not tasks:
            QMessageBox.information(
                self, "古地理成果", "没有可用的真实单因素成果（需完成插值并持久化网格版本）。"
            )
            return
        service = None
        try:
            from paleo_workbench.catalog import get_catalog_service

            service = get_catalog_service()
        except Exception:
            service = None
        if service is None:
            QMessageBox.information(self, "古地理成果", "未打开数据目录，无法注册成果版本。")
            return
        composition_ref = None
        panel = getattr(self, "composition_panel", None)
        document = panel.document() if panel is not None else None
        if document is not None:
            composition_ref = str(document.id)
        interpretation_refs = [
            str(ref.id)
            for ref in (getattr(self._project, "horizon_interpretations", None) or [])
        ]
        assembly = MapProductAssembly(
            product_name=f"{getattr(self._project.stratigraphy, 'target_horizon', '') or '综合'} 古地理成果图",
            factor_task_ids=[str(t.id) for t in tasks],
            interpretation_refs=interpretation_refs,
            composition_ref=composition_ref,
            notes="多因素古地理综合成果",
        )
        manifest = {
            "product_name": assembly.product_name,
            "factor_tasks": [
                {
                    "id": str(t.id),
                    "name": str(t.name),
                    "grid_version": str(t.grid_artifact_version_id),
                }
                for t in tasks
            ],
            "interpretation_refs": interpretation_refs,
            "composition_ref": composition_ref,
        }
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            _json.dump(manifest, handle, ensure_ascii=False, indent=2)
            staged = Path(handle.name)
        try:
            result = assemble_map_product(
                self._project,
                assembly=assembly,
                catalog=service,
                payload_path=staged,
            )
        except Exception as exc:
            QMessageBox.warning(self, "古地理成果", f"成果装配失败: {exc}")
            return
        QMessageBox.information(
            self,
            "古地理成果",
            f"已注册古地理成果 OUTPUT 版本\n{len(tasks)} 个因素 · {len(interpretation_refs)} 项解释\n输出版本: {result.output_version_id[:18]}…",
        )

    def _on_fault_interpretation_requested(self) -> None:
        """Lift the active map's break/fault polylines into a versioned fault
        interpretation (P1-B): map-plane coordinates stay the scientific
        authority, the lifecycle mints the immutable version + lineage."""
        from PySide6.QtWidgets import QMessageBox

        from paleo_workbench.workflow.constraints import constraints_from_map_document
        from paleo_workbench.workflow.fault_lifecycle import (
            draft_from_constraint_layers,
            save_fault_draft,
        )

        if self._project is None or not getattr(self, "_project_path", None):
            QMessageBox.information(self, "断层解释", "请先打开并保存工程。")
            return
        document = self._active_document
        if document is None:
            QMessageBox.information(self, "断层解释", "当前没有活动图件。")
            return
        layers = constraints_from_map_document(document)
        draft = draft_from_constraint_layers(
            layers, crs=str(getattr(document, "map_crs", "") or "")
        )
        if not draft.payload.traces:
            QMessageBox.information(
                self, "断层解释", "当前图件没有断线/断层多段线，无可保存的断层解释。"
            )
            return
        ref, message = save_fault_draft(draft, self._project, self._project_path)
        if ref is None:
            QMessageBox.warning(self, "断层解释", f"保存失败: {message}")
            return
        # Announce the fault identity on the coordination bus (scenario D).
        controller = getattr(self, "view_coordination", None)
        publish = getattr(controller, "publish_fault_selection", None)
        if callable(publish):
            publish(str(ref.id), source="map")
        QMessageBox.information(
            self, "断层解释", f"已保存断层解释版本（{len(draft.payload.traces)} 条断层）"
        )

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
        prefer_id: str | None = None,
    ) -> None:
        documents = list(map_documents or [])
        tasks = list(factor_tasks or [])
        self._project_crs = project_crs
        self._factor_tasks_by_overlay_id = {}
        for task in tasks:
            task_id = str(getattr(task, "id", "") or "")
            if task_id:
                self._factor_tasks_by_overlay_id[task_id] = task
            for output_id in list(getattr(task, "output_resource_ids", None) or []):
                self._factor_tasks_by_overlay_id[str(output_id)] = task
        previous = self._active_document
        if prefer_id is None:
            prefer_id = getattr(previous, "id", None)
        document = active_map_document(documents, prefer_id=prefer_id)
        scene = self.edit_view.scene()
        if (
            isinstance(scene, MapEditScene)
            and previous is not None
            and document is not None
            and getattr(previous, "id", None) != getattr(document, "id", None)
            and self.is_dirty()
        ):
            # A refresh resolved a DIFFERENT document than the one holding the
            # user's unsaved edits.  Reloading it directly would silently
            # discard those edits, and the scene would then keep stale geometry
            # under the new active id, so a later save_draft could write one
            # map's features into another (#532).  Mirror the layer-tree switch
            # prompt instead of wiping.
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
                document = previous
            elif reply == QMessageBox.StandardButton.Save:
                if not self.save_draft():
                    document = previous
        self._active_document = document
        if document is not previous:
            self._presentation_dirty = False
        self.layer_tree.set_documents(documents)
        self.layer_tree.set_active_document(document)
        if isinstance(scene, MapEditScene):
            # Avoid wiping dirty geometry when the same document is re-pushed
            # from project refresh (e.g. other pages update shell state). The
            # guard keys on the document id ONLY: a refresh may legitimately
            # deliver the same id as a brand-new object, and that is exactly
            # when unsaved edits must be preserved (#423).
            same_doc = (
                previous is not None
                and document is not None
                and getattr(previous, "id", None) == getattr(document, "id", None)
            )
            if not same_doc or not scene.is_dirty():
                scene.load_document(document)
                self._restore_view_state_from_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self._kind_visibility(key))
            self._sync_reference_snap_points(scene, document)
        if document is None:
            self._authoring_document = None
            self._unified_authoring_mode = False
            self._suppressed_layer_ids.clear()
        elif document_id := str(getattr(document, "id", "") or "map"):
            if self._authoring_document is None or self._authoring_document.document_id != document_id:
                self._authoring_document = MapAuthoringDocument.from_document(
                    document, project_crs=project_crs
                )
            self._unified_authoring_mode = True
            self._map_tools.set_active_tool(PanTool())
            state = dict(getattr(document, "layer_state", None) or {})
            self._suppressed_layer_ids = {str(value) for value in state.get("removed_layer_ids") or ()}
        self._apply_mode_ui()
        self.attribute_table.set_feature(None)
        self.chrome_panel.update_state(document)
        self._publish_reference_layers(document)
        self._refresh_unified_composition()
        self._sync_attribute_table_from_authoring()
        self._install_native_layer_tree(self.unified_scene)
        self.bottom_workbench.factor_shelf.update_state(tasks)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._sync_action_state()
        if self._preview_mode:
            self._refresh_preview()
        self._emit_mapping_context()

    def _on_create_factor_map_requested(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from paleo_workbench.ui.pages.create_factor_map_dialog import CreateFactorMapDialog

        if self._project is None:
            QMessageBox.information(self, "地质单因素编图", "请先打开或绑定工程。")
            return
        dialog = CreateFactorMapDialog(self._project, parent=self)
        dialog.map_created.connect(self._on_geological_factor_map_created)
        dialog.exec()

    def _on_geological_factor_map_created(self, map_doc) -> None:
        self.load_project(self._project, project_crs=self._project_crs)
        self.contour_drafts_updated.emit()
        self._sync_composition_bindings()

    def _sync_composition_bindings(self) -> None:
        """Resolve the composition's declarative data bindings from the
        project's factor tasks (P1-D: factor maps drive professional layouts
        through bindings, not copy-pasted values)."""
        panel = getattr(self, "composition_panel", None)
        if panel is None or self._project is None:
            return
        binding_context: dict = {}
        for task in getattr(self._project, "factor_map_tasks", None) or []:
            descriptor = getattr(task, "grid_metadata", None) or {}
            stats = descriptor.get("statistics") or {}
            if "min" not in stats or "max" not in stats:
                continue
            ramp_name = str(
                (getattr(task, "parameters", None) or {}).get("color_ramp") or "viridis"
            )
            try:
                from paleo_workbench.mapping.color_ramps import get_color_ramp

                stops = tuple(
                    (float(stop.position), str(stop.color))
                    for stop in get_color_ramp(ramp_name).stops
                )
            except Exception:
                stops = ((0.0, "#053061"), (0.5, "#f7f7f7"), (1.0, "#67001f"))
            binding_context["factor.colorbar"] = {
                "title": f"{task.name} ({descriptor.get('unit') or ''})".strip(),
                "min": float(stats["min"]),
                "max": float(stats["max"]),
                "stops": stops,
            }
            break  # the active factor defines the primary colorbar binding
        if binding_context:
            panel.apply_bindings(binding_context)

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
            # #937-6: async completion — in-page status instead of a modal
            # (the Save/Discard/Cancel guard below stays interactive: it
            # protects unsaved edits from silent disposal, #532).
            self.status_bar.scale.setText("没有可提取的单因素网格。请先在制备页生成单因素图。")
            return
        # Prefer the map linked to the last draft as active document.  The
        # preference is passed to update_state instead of mutating
        # _active_document first: a pre-mutation defeats update_state's dirty
        # guard (previous already equals the new id), leaving a dirty scene
        # from another document under the new active id (#532).
        prefer_id = None
        if drafts[-1].linked_map_document_id:
            prefer_id = str(drafts[-1].linked_map_document_id)
        self.update_state(
            self._project.paleomap_documents,
            factor_tasks=self._project.factor_map_tasks,
            project_crs=getattr(
                getattr(self._project, "coordinate", None), "project_crs", None
            ),
            prefer_id=prefer_id,
        )
        self.contour_drafts_updated.emit()
        # #937-6: async completion — in-page status instead of a modal
        # (shell may be rebuilding, #897 family). Success is visible in the
        # persistent scale/status surface, not a stacked dialog.
        if getattr(self, "status_bar", None) is not None:
            self.status_bar.scale.setText(f"等值线初稿：已生成 {len(drafts)} 份并加载到编图。")

    def _on_contour_failed(self, message: str) -> None:
        if self._contour_job.target is not self._project:
            return
        text = f"等值线初稿失败：{message}"
        shelf = self.bottom_workbench.factor_shelf
        shelf.contour_draft_btn.setToolTip(text)
        # A tooltip alone is an invisible failure (the button simply re-enables).
        # Mirror the preparation page's summary text on the page's persistent
        # status surface so the failure is actually visible (#843).
        if getattr(self, "status_bar", None) is not None:
            self.status_bar.scale.setText(text)

    def _clear_contour_job(self) -> None:
        self.bottom_workbench.factor_shelf.contour_draft_btn.setEnabled(True)

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        joined = self._contour_job.shutdown(wait_ms)
        export_ok = self._export_job.shutdown(wait_ms)
        self._end_export_busy()
        # The native raster worker lives on the embedded NativeMapCanvas and
        # never receives a QCloseEvent when the window/shell is torn down —
        # without this the QThread is destroyed while running (qFatal abort on
        # exit, H12). Shut it down explicitly on the same hook.
        raster_ok = True
        try:
            canvas_panel = getattr(self, "canvas_panel", None)
            native_canvas = getattr(canvas_panel, "native_canvas", None)
            if native_canvas is not None:
                controller = getattr(native_canvas, "_raster_controller", None)
                if controller is not None:
                    res = controller.shutdown(wait_ms)
                    if res is False:
                        raster_ok = False
        except Exception:
            pass
        return joined and export_ok and raster_ok

    def save_draft(self) -> bool:
        """Write scene features back into the active PaleoMapDocument and clear dirty."""
        doc = self._active_document
        scene = self._edit_scene()
        if doc is None or scene is None:
            return False
        use_authoring = bool(
            self._authoring_document is not None
            and self._unified_authoring_mode
            and (self._authoring_document.is_dirty() or self._presentation_dirty)
        )
        original_document = None
        pending_audit: list[dict[str, object]] = []
        if use_authoring:
            # Validate the working edit buffer before promoting it.  The legacy
            # scene is only a validator/migration mirror; retaining an exact
            # document copy means a failed validation cannot leak a partial edit
            # into the persisted working version.
            original_document = doc.model_copy(deep=True)
            features = self._authoring_document.records()
            apply_features_to_document(doc, features)
            # Keep the legacy surface as a non-authoritative compatibility mirror
            # for legacy project migration and its established topology validator.
            scene.load_document(doc)
        scene.refresh_topology()
        valid, issues = scene.validate_for_save()
        self.bottom_workbench.topology_panel.set_issues(issues)
        if not valid:
            if original_document is not None:
                for field_name in type(doc).model_fields:
                    setattr(doc, field_name, getattr(original_document, field_name))
                scene.load_document(doc)
            from PySide6.QtWidgets import QMessageBox

            n = len(issues) if issues else 0
            if issues and issues[0].get("feature_id"):
                self._on_topology_locate_requested(str(issues[0]["feature_id"]))
            QMessageBox.warning(
                self,
                "无法保存编图草稿",
                f"拓扑检查未通过（{n} 项问题）。已定位至首项几何问题，请查看底部拓扑面板修复后再保存。",
            )
            return False
        if use_authoring:
            pending_audit = self._authoring_document.commit_changes()
            if pending_audit:
                doc.edit_history.extend(pending_audit)
        if not use_authoring:
            features = scene.export_features()
            apply_features_to_document(doc, features)
            self._authoring_document = MapAuthoringDocument.from_document(
                doc, project_crs=self._project_crs
            )
        # Persist viewport (center/scale) without clobbering provenance keys
        # like is_demo_draft / generator / seed.
        self._merge_view_state_into_document(doc)
        scene.set_dirty(False)
        self._presentation_dirty = False
        self._sync_save_enabled()
        self._sync_action_state()
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
        authoring = self._authoring_document
        if (
            authoring is not None
            and authoring.active_kind == "facies"
            and authoring.active_session is not None
        ):
            try:
                from paleo_workbench.mapping.vector_operations import merge_selected_polygons

                new_id = merge_selected_polygons(
                    authoring.active_session, authoring.active_layer.selection
                )
            except (RuntimeError, ValueError) as exc:
                QMessageBox.information(self, "合并相带", str(exc))
                return None
            authoring.active_layer.set_selection((new_id,))
            self._on_unified_tool_operation()
            return new_id
        scene = self._edit_scene()
        if scene is None:
            return None
        try:
            new_id = scene.merge_selected_facies()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "合并相带",
                f"合并操作失败：{exc}",
            )
            return None
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
        authoring = self._authoring_document
        if authoring is not None:
            facies = authoring.layer("facies")
            lines = authoring.layer("line")
            if facies.edit_session is not None and facies.selection and lines.selection:
                polygon_id = next(iter(sorted(facies.selection)))
                line_id = next(iter(sorted(lines.selection)))
                try:
                    from paleo_workbench.mapping.vector_operations import split_polygon_by_line

                    line_source = lines.edit_session or lines
                    line = line_source.feature(line_id)
                    new_ids = split_polygon_by_line(facies.edit_session, polygon_id, line)
                except (KeyError, RuntimeError, ValueError) as exc:
                    QMessageBox.information(self, "分割相带", str(exc))
                    return None
                facies.set_selection(new_ids)
                self._on_unified_tool_operation()
                return list(new_ids)
        scene = self._edit_scene()
        if scene is None:
            return None
        try:
            new_ids = scene.split_selected_facies_by_line()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "分割相带",
                f"分割操作失败：{exc}",
            )
            return None
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
        # The QGIS/fallback unified canvas is the normal authoring surface.  The
        # graphics editor remains loaded only for legacy migration compatibility.
        self.center_stack.setCurrentIndex(1 if self._preview_mode or self._unified_authoring_mode else 0)
        if self._preview_mode or self._unified_authoring_mode:
            self.preview_canvas_stack.setCurrentWidget(self.unified_canvas)
        # Bottom workbench visibility combines the user's panel-manager
        # preference with the mode flags (preview / canvas priority hide it).
        self.bottom_workbench.setVisible(
            self.dock_manager.bottom_user_visible()
            and not self._canvas_priority
            and not self._preview_mode
        )

    def _refresh_preview(self) -> None:
        self._refresh_unified_composition()
        if self._native_factor_scene is not None:
            # Factor grids now share the unified renderer with facies/contours/
            # samples. NativeMapCanvas remains populated only as a compatibility
            # export surface until unified export replaces it in Phase 5.
            self.preview_canvas_stack.setCurrentWidget(self.unified_canvas)
            self.chrome_panel.update_state(self._active_document)
            return
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
        # A built QGIS bridge makes this the primary preview composition. The
        # legacy preview remains as an explicit compatibility fallback until the
        # editor migration is complete; it is never reported as QGIS rendering.
        # Continue loading the compatibility preview payload even while QGIS is
        # the visible renderer: existing export/accessibility callers consume it
        # during the migration, but the user sees the unified QGIS frame.
        self.canvas_panel.load_preview(features, wells=wells, period_name=period)
        self.preview_canvas_stack.setCurrentWidget(self.unified_canvas)
        self.chrome_panel.update_state(doc)

    @property
    def unified_scene(self):
        """Registry-backed composition used by the unified renderer during migration."""
        return self._unified_scene_adapter.scene

    def _unified_data_revisions(self) -> dict[str, int] | None:
        """Translate authoring-layer revision keys into stable per-kind integers."""
        authoring = self._authoring_document
        if authoring is None or not self._unified_authoring_mode:
            return None
        if self._unified_revisions_owner is not authoring:
            # New authoring object: force a bump for every kind even when raw
            # keys repeat, keeping effective revisions globally monotonic (the
            # document feature cache is keyed by them and must never collide).
            self._unified_revisions_owner = authoring
            self._unified_raw_revisions.clear()
        revisions: dict[str, int] = {}
        for kind in ("facies", "well", "line", "label"):
            raw = authoring.data_revision_key(kind)
            if self._unified_raw_revisions.get(kind) != raw:
                self._unified_raw_revisions[kind] = raw
                self._unified_effective_revisions[kind] = self._unified_effective_revisions.get(kind, 0) + 1
            revisions[kind] = self._unified_effective_revisions.get(kind, 1)
        return revisions

    def _kind_visibility(self, kind: str) -> bool:
        """Visibility for a compatibility kind from the authority chain (#1033).

        Resolution order: live ``LayerRegistry`` entry → persisted
        ``layer_state["composition"]`` → legacy tree checkbox. The legacy
        ``MapLayerTree`` widget is a view that only SEEDS a kind the registry
        has no layer for; its state can never overwrite an authored native
        toggle.
        """
        document = self._active_document
        registry = (
            getattr(self.unified_scene, "registry", None)
            if self.unified_scene is not None
            else None
        )
        if registry is not None and document is not None:
            document_id = str(getattr(document, "id", "") or "")
            layer = registry.get(f"{document_id}:{kind}")
            if layer is not None:
                return bool(layer.visible)
            wanted_id = f"{document_id}:{kind}"
            composition = (getattr(document, "layer_state", None) or {}).get(
                "composition"
            )
            for entry in composition or ():
                if (
                    isinstance(entry, dict)
                    and str(entry.get("id") or "") == wanted_id
                    and "visible" in entry
                ):
                    return bool(entry["visible"])
        return self.layer_tree.layer_is_visible(kind)

    def _composition_visibility(self) -> dict[str, bool]:
        return {key: self._kind_visibility(key) for key in ("facies", "well", "line", "label")}

    def _refresh_unified_composition(self) -> None:
        """Project current live editor records into the unified renderer seam."""
        if self.unified_scene is None:
            return
        document = self._active_document
        scene = self._edit_scene()
        records = None
        layer_revisions = None
        if self._authoring_document is not None and self._unified_authoring_mode:
            records = self._authoring_document.records()
            layer_revisions = self._authoring_document.data_revisions()
        elif scene is not None and document is not None:
            records = scene.export_features()
        visibility = self._composition_visibility()
        self._unified_scene_adapter.sync(
            document,
            project_crs=self._project_crs,
            visibility=visibility,
            records=records,
            layer_revisions=layer_revisions,
            excluded_layer_ids=self._suppressed_layer_ids,
            data_revisions=self._unified_data_revisions(),
            cache_owner=self._authoring_document,
        )
        self._sync_reference_render_layers(document)
        if self._authoring_document is not None:
            for kind in ("facies", "well", "line", "label"):
                vector_layer = self._authoring_document.layer(kind)
                if not vector_layer.style and not vector_layer.labels:
                    continue
                current_style = self.unified_scene.vector_style(vector_layer.id)
                current_style.update(vector_layer.style)
                if vector_layer.labels:
                    current_style["labels"] = dict(vector_layer.labels)
                self.unified_scene.set_vector_style(vector_layer.id, current_style)
        self._restore_unified_composition_state(document)
        snapshot = self.unified_scene.render_snapshot(project_crs=str(self._project_crs or ""))
        document_id = str(getattr(document, "id", "") or "") if document is not None else None
        self.unified_canvas.set_layer_snapshot(snapshot)
        if document_id != self._unified_document_id:
            self._unified_document_id = document_id
            saved = list((getattr(document, "view_state", None) or {}).get("extent") or []) if document else []
            applied_extent = False
            if len(saved) == 4:
                try:
                    self.unified_canvas.set_extent(tuple(float(value) for value in saved))
                    applied_extent = True
                except (TypeError, ValueError):
                    pass
            if not applied_extent:
                self.unified_canvas.set_extent(extent_for_snapshot(snapshot))
        self._sync_map_status()

    def _install_native_layer_tree(self, scene) -> None:
        """Swap the left dock to the C++ registry-backed tree for native overlays."""
        if scene is None or getattr(scene, "registry", None) is None:
            return
        if self._native_layer_tree is not None and self._native_layer_tree.model.registry is scene.registry:
            self._native_layer_tree.model.refresh()
            return
        if self._native_layer_tree is not None:
            self.layer_tree_stack.removeWidget(self._native_layer_tree)
            self._native_layer_tree.deleteLater()
        from paleo_workbench.ui.native_layer_tree import NativeLayerTree

        tree = NativeLayerTree(scene.registry, self.layer_tree_stack)
        tree.zoom_to_layer_requested.connect(self.unified_canvas.set_extent)
        tree.model.layer_changed.connect(self._on_native_layer_registry_changed)
        tree.properties_requested.connect(self._open_layer_properties)
        tree.active_layer_changed.connect(self._on_native_active_layer)
        tree.add_layer_requested.connect(self._on_native_add_layer_requested)
        self._native_layer_tree = tree
        self.layer_tree_stack.addWidget(tree)
        self.layer_tree_stack.setCurrentWidget(tree)
        tree.expand_all()

    def _on_native_active_layer(self, layer_id: str | None) -> None:
        if layer_id is None or self._authoring_document is None:
            return
        for kind in ("facies", "well", "line", "label"):
            if self._authoring_document.layer(kind).id == layer_id:
                self._authoring_document.set_active_kind(kind)
                # The active tool captured the PREVIOUS layer's index and
                # edit session; without a rebind, clicks and edits kept
                # landing on the old layer (#523).
                self._rebind_tool_after_layer_switch()
                self._sync_action_state()
                self._sync_map_status()
                return

    def _on_native_layer_registry_changed(self, layer_id: str) -> None:
        if self.unified_scene.registry.get(str(layer_id)) is None:
            self._suppressed_layer_ids.add(str(layer_id))
        if self._active_document is not None:
            self._presentation_dirty = True
        self._stage_composition_state()
        self._refresh_unified_composition()
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _on_native_add_layer_requested(self) -> None:
        """Import an immutable GDAL reference into the unified composition."""
        document = self._active_document
        if document is None:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "添加参考图层",
            "",
            "GIS 文件 (*.tif *.tiff *.gpkg *.geojson *.json *.shp);;所有文件 (*)",
        )
        if not path:
            return
        try:
            layer = self._reference_service.import_layer(
                path, str(self._project_crs or getattr(document, "map_crs", "") or "")
            )
        except ReferenceLayerError as exc:
            QMessageBox.warning(self, "添加参考图层", str(exc))
            return
        document.reference_layers.append(layer)
        self._presentation_dirty = True
        self._publish_reference_layers(document)
        self._refresh_unified_composition()
        self._install_native_layer_tree(self.unified_scene)
        if self._native_layer_tree is not None:
            self._native_layer_tree.set_active_layer(self._reference_scene_layer_id(layer.id))
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _reference_scene_layer_id(self, reference_id: str) -> str:
        document_id = str(getattr(self._active_document, "id", "") or "map")
        return f"{document_id}:reference:{reference_id}"

    def _sync_reference_render_layers(self, document) -> None:
        """Mirror ready external sources into MapScene without owning their data."""
        if document is None:
            return
        # Keep the established snapping seam substitutable in headless/legacy
        # callers.  A minimal snap-only service has no render-payload API and
        # must not prevent the document/editor from opening.
        if not hasattr(self._reference_service, "vector_render_payload") or not hasattr(
            self._reference_service, "raster_render_extent"
        ):
            return
        prefix = f"{getattr(document, 'id', '') or 'map'}:reference:"
        references = list(getattr(document, "reference_layers", []) or [])
        for reference in references:
            ReferenceLayerService.refresh_status(reference)
        wanted = {
            self._reference_scene_layer_id(layer.id)
            for layer in references
            if layer.status == "ready"
            and self._reference_scene_layer_id(layer.id) not in self._suppressed_layer_ids
        }
        for existing in tuple(self.unified_scene.registry.layers()):
            if str(existing.id).startswith(prefix) and str(existing.id) not in wanted:
                self.unified_scene.remove_layer(str(existing.id))
        for reference in references:
            layer_id = self._reference_scene_layer_id(reference.id)
            if layer_id not in wanted or reference.status != "ready":
                continue
            existing = self.unified_scene.registry.get(layer_id)
            if reference.source_kind == "raster":
                try:
                    extent = self._reference_service.raster_render_extent(reference)
                except ReferenceLayerError:
                    if existing is not None:
                        self.unified_scene.remove_layer(layer_id)
                    continue
                if existing is None:
                    self.unified_scene.add_raster_source(
                        layer_id,
                        reference.source_path,
                        name=reference.name,
                        extent=extent,
                        crs=reference.source_crs,
                        source_ref=f"reference:{reference.id}",
                        source_revision=reference.cache_key,
                    )
                else:
                    self.unified_scene.set_raster_source(
                        layer_id, reference.source_path, source_revision=reference.cache_key, extent=extent
                    )
                    existing.name = reference.name
                    existing.crs = reference.source_crs
                existing = self.unified_scene.registry.get(layer_id)
                if existing is not None:
                    existing.visible = bool(reference.visible)
                    existing.opacity = float(reference.opacity)
                continue
            try:
                features, extent = self._reference_service.vector_render_payload(reference)
            except ReferenceLayerError:
                if existing is not None:
                    self.unified_scene.remove_layer(layer_id)
                continue
            if existing is None:
                existing = self.unified_scene.add_vector_layer(
                    layer_id,
                    features,
                    name=reference.name,
                    extent=extent,
                    crs=reference.project_crs,
                    source_ref=f"reference:{reference.id}",
                    style={"fill": "#9c6644", "stroke": "#4d3322", "stroke_width": 1.0},
                )
            else:
                self.unified_scene.set_vector_features(layer_id, features, extent=extent)
                existing.name = reference.name
                existing.crs = reference.project_crs
            existing.visible = bool(reference.visible)
            existing.opacity = float(reference.opacity)

    def _show_legacy_layer_tree(self) -> None:
        self.layer_tree_stack.setCurrentWidget(self.layer_tree)

    def _active_authoring_index(self) -> FeatureSpatialIndex | None:
        if self._authoring_document is None:
            return None
        return self._snapping.index_for(self._authoring_document.active_layer)

    def _snap_map_point(self, point: tuple[float, float]) -> tuple[float, float]:
        if self._authoring_document is None:
            return point
        tolerance = self._snapping.pixel_tolerance * self.unified_canvas.map_units_per_pixel
        layers = (self._authoring_document.active_layer,) if self._snapping.current_layer_only else self._authoring_document.layers()
        return self._snapping.snap(point, tolerance=tolerance, layers=layers)

    # Tools that capture the active layer/index/session at construction
    # (#523). After an active-layer switch they must be REBOUND to the new
    # layer; kind-forcing tools (add_*) are deactivated instead when the
    # switch moved away from their kind (re-requesting them would hijack
    # the user's layer choice).
    _LAYER_BOUND_TOOL_ACTIONS = frozenset(
        {"select", "identify", "select_rectangle", "move_feature", "vertex"}
    )
    _KIND_BOUND_TOOL_ACTIONS = {
        "add_point": "well", "add_line": "line", "add_polygon": "facies",
    }

    def _rebind_tool_after_layer_switch(self) -> None:
        action = getattr(self, "_active_tool_action", None)
        if not action or action in ("pan", "zoom_in", "zoom_out", "measure_distance"):
            return  # not bound to a layer
        if action in self._LAYER_BOUND_TOOL_ACTIONS:
            self._on_action_tool_requested(action)
        elif action in self._KIND_BOUND_TOOL_ACTIONS:
            kind = self._KIND_BOUND_TOOL_ACTIONS[action]
            if self._authoring_document is None or (
                self._authoring_document.active_kind != kind
            ):
                self._on_action_tool_requested("pan")

    def _on_action_tool_requested(self, action_id: str) -> None:
        authoring = self._authoring_document
        if authoring is None:
            return
        self._active_tool_action = action_id
        if action_id == "pan":
            tool = PanTool()
        elif action_id in {"zoom_in", "zoom_out"}:
            tool = ZoomTool(
                zoom=self.unified_canvas.zoom_by,
                factor=0.5 if action_id == "zoom_in" else 2.0,
                tool_id=action_id,
            )
        elif action_id == "measure_distance":
            tool = MeasureDistanceTool(measurement_ready=self._on_measurement_ready)
        else:
            kind_for_action = {
                "add_point": "well", "add_line": "line", "add_polygon": "facies",
            }.get(action_id)
            if kind_for_action is not None:
                authoring.set_active_kind(kind_for_action)
                if authoring.editing() and authoring.active_session is None:
                    authoring.start_editing()
            layer = authoring.active_layer
            index = self._active_authoring_index()
            if index is None:
                return
            tolerance = lambda: self._snapping.pixel_tolerance * self.unified_canvas.map_units_per_pixel
            if action_id in {"select", "identify"}:
                tool = SelectTool(layer, identify=lambda point: index.identify(point, tolerance()))
            elif action_id == "select_rectangle":
                tool = RectangleSelectTool(layer, select_rectangle=index.select_rectangle)
            else:
                session = layer.edit_session
                if session is None:
                    return
                if action_id == "add_point":
                    tool = AddPointTool(session, snap=self._snap_map_point)
                elif action_id == "add_line":
                    tool = AddLineTool(session, snap=self._snap_map_point)
                elif action_id == "add_polygon":
                    tool = AddPolygonTool(session, snap=self._snap_map_point)
                elif action_id == "move_feature":
                    tool = MoveFeatureTool(session, identify=lambda point: index.identify(point, tolerance()))
                elif action_id == "vertex":
                    tool = VertexTool(
                        session,
                        identify_vertex=lambda point: index.identify_vertex(point, tolerance()),
                        on_vertex_committed=self._on_unified_vertex_committed,
                    )
                else:
                    return
        self._map_tools.set_active_tool(tool)
        self.unified_canvas.setFocus()
        self._sync_action_state()

    def _on_action_command_requested(self, command_id: str) -> None:
        authoring = self._authoring_document
        if command_id == "full_extent":
            self.unified_canvas.set_extent(extent_for_snapshot(self.unified_scene.render_snapshot(project_crs=self._project_crs or "")))
        elif command_id == "previous_extent":
            self.unified_canvas.previous_extent()
        elif command_id == "next_extent":
            self.unified_canvas.next_extent()
        elif command_id == "refresh":
            self._refresh_unified_composition()
        elif command_id == "clear_selection" and authoring is not None:
            authoring.clear_selection()
        elif command_id == "select_all" and authoring is not None:
            authoring.active_layer.select_all()
        elif command_id == "invert_selection" and authoring is not None:
            authoring.active_layer.invert_selection()
        elif command_id == "toggle_editing" and authoring is not None:
            if authoring.active_session is None:
                authoring.start_editing()
            else:
                self.save_draft()
        elif command_id == "save_edits":
            self.save_draft()
        elif command_id == "rollback" and authoring is not None:
            authoring.rollback_changes()
        elif command_id == "undo" and authoring is not None and authoring.active_session is not None:
            authoring.active_session.undo()
        elif command_id == "redo" and authoring is not None and authoring.active_session is not None:
            authoring.active_session.redo()
        elif command_id == "delete_selected" and authoring is not None and authoring.active_session is not None:
            for feature_id in sorted(authoring.active_layer.selection):
                authoring.active_session.delete_feature(feature_id)
            authoring.active_layer.set_selection(())
        elif command_id == "snapping":
            self._snapping.enabled = self.action_controller.actions["snapping"].isChecked()
        elif command_id == "topology":
            self._topology.enabled = self.action_controller.actions["topology"].isChecked()
        elif command_id == "cancel":
            self._map_tools.key_press("escape")
        elif command_id == "merge":
            self.merge_selected_facies()
        elif command_id == "split":
            self.split_selected_facies()
        self._on_unified_tool_operation()

    def _on_unified_cursor_position(self, point: tuple[float, float]) -> None:
        # The existing shelf accepts map coordinates and remains useful in the
        # unified canvas; it is no longer tied exclusively to QGraphicsView.
        self.bottom_workbench.factor_shelf.set_cursor_position(point)
        self._sync_map_status(point=point)

    def _on_unified_extent_changed(self, _extent: tuple[float, float, float, float]) -> None:
        self._sync_map_status()
        self._sync_action_state()

    def _on_measurement_ready(self, distance: float) -> None:
        """Report a completed map-space distance without changing map data."""
        self._last_measurement = float(distance)
        self.status_bar.scale.setText(f"Measure: {self._last_measurement:.6g} map units")

    def _sync_map_status(self, *, point: tuple[float, float] | None = None) -> None:
        authoring = self._authoring_document
        self.status_bar.update_state(
            point=point,
            extent=self.unified_canvas.view_extent,
            crs=str(self._project_crs or getattr(self._active_document, "map_crs", "") or ""),
            renderer=self.unified_canvas.backend_status,
            selection_count=(sum(len(layer.selection) for layer in authoring.layers()) if authoring is not None else 0),
            editing=bool(authoring and authoring.active_session is not None),
        )

    def _open_layer_properties(self, layer_id: str) -> None:
        layer = self.unified_scene.registry.get(str(layer_id))
        if layer is None:
            return
        style = (
            self.unified_scene.scalar_style(str(layer_id))
            if self.unified_scene.scalar_layer(str(layer_id)) is not None
            else self.unified_scene.vector_style(str(layer_id))
        )
        dialog = MapLayerPropertiesDialog(
            layer,
            style=style,
            parent=self,
            features=self.unified_scene.vector_features(str(layer_id)),
            fields=self._layer_field_names(str(layer_id)),
        )
        dialog.properties_applied.connect(self._apply_layer_properties)
        dialog.open()

    def _layer_field_names(self, layer_id: str) -> tuple[str, ...]:
        """Attribute names available for symbology expressions/classification."""
        names: list[str] = []
        seen: set[str] = set()
        for feature in self.unified_scene.vector_features(str(layer_id)):
            properties = (feature or {}).get("properties") or {}
            if not isinstance(properties, dict):
                continue
            for key in properties:
                text = str(key)
                if text and text not in seen and not text.startswith("__"):
                    seen.add(text)
                    names.append(text)
            if len(names) >= 64:
                break
        return tuple(names)

    def _apply_layer_properties(self, layer_id: str, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        layer = self.unified_scene.registry.get(str(layer_id))
        if layer is None:
            return
        layer.name = str(payload.get("name") or layer.name)
        layer.crs = str(payload.get("crs") or layer.crs)
        layer.opacity = float(payload.get("opacity", layer.opacity))
        scalar = self.unified_scene.scalar_layer(str(layer_id))
        if scalar is not None:
            requested_scalar = dict(payload.get("scalar_style") or {})
            requested_range = list(requested_scalar.get("color_range") or ())
            if len(requested_range) == 2 and requested_range[1] >= requested_range[0]:
                color_range = (float(requested_range[0]), float(requested_range[1]))
            else:
                color_range = None
            self.unified_scene.set_scalar_style(
                str(layer_id),
                color_ramp_name=str(requested_scalar.get("color_ramp") or "default"),
                color_range=color_range,
                gamma=float(requested_scalar.get("gamma", 1.0)),
                nodata=str(requested_scalar.get("nodata") or "transparent"),
            )
            self._presentation_dirty = True
            self._stage_composition_state()
            self._refresh_unified_composition()
            self._sync_save_enabled()
            self._emit_mapping_context()
            return
        style = self.unified_scene.vector_style(str(layer_id))
        requested_style = dict(payload.get("style") or {})
        for key in ("fill", "stroke"):
            if requested_style.get(key):
                style[key] = requested_style[key]
        for key in ("stroke_width", "marker_size"):
            if key in requested_style:
                style[key] = requested_style[key]
        for key in ("line_pattern", "marker"):
            if requested_style.get(key):
                style[key] = requested_style[key]
        for key in ("renderer", "field", "categories", "ranges"):
            if key in requested_style:
                style[key] = requested_style[key]
        style["labels"] = dict(requested_style.get("labels") or {})
        # The authoritative QGIS payload arrives outside the legacy dict; it
        # replaces any previous payload wholesale (native editor round-trip).
        if "qgis_style" in payload:
            qgis_payload = payload.get("qgis_style")
            if isinstance(qgis_payload, dict) and qgis_payload.get("renderer_xml"):
                style["qgis_style"] = dict(qgis_payload)
        if self.unified_scene.vector_features(str(layer_id)):
            self.unified_scene.set_vector_style(str(layer_id), style)
            authoring = self._authoring_document
            if authoring is not None:
                for kind in ("facies", "well", "line", "label"):
                    if authoring.layer(kind).id == layer_id:
                        authoring.layer(kind).style = dict(style)
                        authoring.layer(kind).labels = dict(style.get("labels") or {})
                        break
        self._presentation_dirty = True
        self._stage_composition_state()
        self._refresh_unified_composition()
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _on_unified_vertex_committed(
        self,
        feature_id: str,
        path: tuple[int, ...],
        origin: tuple[float, float],
        replacement: tuple[float, float],
    ) -> None:
        if self._authoring_document is None:
            return
        self._topology.propagate_shared_vertex(
            (self._authoring_document.active_layer,),
            origin=origin,
            replacement=replacement,
            skip=(self._authoring_document.active_layer.id, feature_id, path),
        )

    def _on_unified_tool_operation(self, edits_data: bool = True) -> None:
        """React to one unified-canvas tool operation.

        ``edits_data`` is False for pure pointer/selection feedback (measure
        hover, select clicks, zoom): overlays repaint from live state, so the
        document composition must not be recomposed (and rehashed) per event.
        """
        self._sync_attribute_table_from_authoring()
        if edits_data:
            self._refresh_unified_composition()
        else:
            self._sync_map_status()
        self._sync_action_state()
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _sync_attribute_table_from_authoring(self) -> None:
        authoring = self._authoring_document
        if authoring is None:
            self.attribute_table.set_layer_features(())
            return
        layer = authoring.active_layer
        session = layer.edit_session
        revision = (layer.data_revision << 32) + (session.revision if session is not None else 0)
        source = session.features() if session is not None else layer.features()
        cached = self._attribute_table_records
        if cached is None or cached[0] is not layer or cached[1] != revision:
            records = [
                feature_to_record(feature, kind=authoring.active_kind) for feature in source
            ]
            self._attribute_table_records = (layer, revision, records)
            self.attribute_table.set_layer_features(records, selected_ids=layer.selection)
            return
        self.attribute_table.set_selected_ids(layer.selection)

    def _on_attribute_feature_selected(self, feature_id: str) -> None:
        authoring = self._authoring_document
        if authoring is None:
            return
        layer = authoring.active_layer
        if feature_id:
            source = layer.edit_session if layer.edit_session is not None else layer
            try:
                source.feature(feature_id)
            except KeyError:
                return
        layer.set_selection((feature_id,) if feature_id else ())
        self._on_unified_tool_operation(edits_data=False)

    def _unified_overlay_state(self) -> dict[str, object]:
        authoring = self._authoring_document
        if authoring is None:
            return {}
        selected = []
        for layer in authoring.layers():
            source = layer.edit_session.features() if layer.edit_session is not None else layer.features()
            selected.extend(feature for feature in source if feature.feature_id in layer.selection)
        tool = self._map_tools.active_tool
        capture = list(getattr(tool, "points", ()) or ())
        snap = self._snapping.last_match.point if self._snapping.last_match is not None else None
        chrome = dict(getattr(self._active_document, "map_chrome", None) or {})
        # This runs inside QWidget::paintEvent via the canvas overlay provider.
        # Without the optional native scene modules (#1001 degradation)
        # unified_scene is None: an exception here aborts the painter mid-paint
        # ("QBackingStore::endPaint with active painter" → heap corruption,
        # observed as SIGSEGV under GC in the full suite). Degrade to an empty
        # legend instead.
        scene = self.unified_scene
        if scene is None:
            legend_items: list[dict[str, object]] = []
        else:
            legend_items = [
                {
                    "label": layer.name,
                    "color": (
                        (scene.vector_style(layer.id) or {}).get("fill")
                        or (scene.vector_style(layer.id) or {}).get("stroke")
                        or "#6c8ebf"
                    ),
                }
                for layer in scene.registry.layers()
                if layer.visible and layer.type.name != "Group"
            ]
        return {
            "selected_features": selected,
            "capture_points": capture,
            "snap_point": snap,
            "decorations": {
                "title": chrome.get("title") or getattr(self._active_document, "name", ""),
                "elements": list(chrome.get("elements") or ("图例", "指北针", "比例尺", "标题栏")),
                "legend_items": legend_items,
            },
        }

    def _sync_action_state(self) -> None:
        authoring = self._authoring_document
        if authoring is None:
            self.action_controller.update_state(MapActionState())
            return
        session = authoring.active_session
        selected = authoring.active_layer.selection
        # Newly digitized features live only in the edit session's working set;
        # VectorLayer.feature() sees committed features and raises KeyError for
        # them, which undercounted polygons and kept merge/split disabled.
        source = session if session is not None else authoring.active_layer
        polygon_count = 0
        for feature_id in selected:
            try:
                if source.feature(feature_id).geometry["type"] in {"Polygon", "MultiPolygon"}:
                    polygon_count += 1
            except KeyError:
                continue
        self.action_controller.update_state(
            MapActionState(
                has_active_vector_layer=True,
                vector_layer_writable=True,
                editing=session is not None,
                selected_count=len(selected),
                compatible_polygon_count=polygon_count,
                can_undo=bool(session and session.undo_stack),
                can_redo=bool(session and session.redo_stack),
                can_previous_extent=self.unified_canvas.can_previous_extent,
                can_next_extent=self.unified_canvas.can_next_extent,
            )
        )

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
        # The registry is authoritative (#1033): a legacy-tree toggle must
        # write through, or the next composition refresh would silently drop
        # it once a native layer exists for the kind.
        registry = (
            getattr(self.unified_scene, "registry", None)
            if self.unified_scene is not None
            else None
        )
        document = self._active_document
        if registry is not None and document is not None:
            layer = registry.get(
                f"{str(getattr(document, 'id', '') or '')}:{kind}"
            )
            if layer is not None:
                layer.visible = bool(visible)
        if self._active_document is not None:
            self._presentation_dirty = True
        self._refresh_unified_composition()
        self._stage_composition_state()
        self._sync_save_enabled()

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
        self._native_factor_scene = None
        self._show_legacy_layer_tree()
        if scene is not None:
            scene.load_document(document)
            self._restore_view_state_from_document(document)
            for key in ("facies", "well", "line", "label"):
                scene.set_layer_visible(key, self._kind_visibility(key))
        self._authoring_document = (
            MapAuthoringDocument.from_document(document, project_crs=self._project_crs)
            if document is not None
            else None
        )
        self._unified_authoring_mode = document is not None
        self._presentation_dirty = False
        state = dict(getattr(document, "layer_state", None) or {}) if document is not None else {}
        self._suppressed_layer_ids = {str(value) for value in state.get("removed_layer_ids") or ()}
        self._map_tools.set_active_tool(PanTool() if document is not None else None)
        self.attribute_table.set_feature(None)
        self.chrome_panel.update_state(document)
        self._publish_reference_layers(document)
        self._refresh_unified_composition()
        self._install_native_layer_tree(self.unified_scene)
        self._sync_undo_redo_enabled()
        self._sync_save_enabled()
        self._sync_action_state()
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
        merged["extent"] = [float(value) for value in self.unified_canvas.view_extent]
        doc.view_state = merged
        doc.map_crs = self._project_crs or getattr(doc, "map_crs", None)
        state = self._authoring_document.state() if self._authoring_document is not None else {}
        state["composition"] = self._layer_registry_state()
        state["removed_layer_ids"] = sorted(self._suppressed_layer_ids)
        doc.layer_state = state

    def _stage_composition_state(self) -> None:
        """Keep unsaved presentation edits stable across legacy-adapter refreshes."""
        doc = self._active_document
        if doc is None:
            return
        state = dict(getattr(doc, "layer_state", None) or {})
        state["composition"] = self._layer_registry_state()
        state["removed_layer_ids"] = sorted(self._suppressed_layer_ids)
        doc.layer_state = state

    def _layer_registry_state(self) -> list[dict[str, object]]:
        """Serialize LayerRegistry composition without making it a second authority."""
        state: list[dict[str, object]] = []
        for index, layer in enumerate(self.unified_scene.registry.layers()):
            layer_type = getattr(getattr(layer, "type", None), "name", None) or str(getattr(layer, "type", ""))
            state.append(
                {
                    "id": str(layer.id),
                    "name": str(layer.name),
                    "type": layer_type,
                    "order": index,
                    "parent_id": str(self.unified_scene.registry.parent_id(layer.id) or ""),
                    "visible": bool(layer.visible),
                    "opacity": float(layer.opacity),
                    "crs": str(layer.crs),
                    "source_ref": str(layer.source_ref),
                    "style": (
                        self.unified_scene.scalar_style(str(layer.id))
                        if self.unified_scene.scalar_layer(str(layer.id)) is not None
                        else self.unified_scene.vector_style(str(layer.id))
                    ),
                }
            )
        return state

    def _restore_view_state_from_document(self, document) -> None:
        """Apply saved center/scale when present; ignore pure provenance dicts."""
        if document is None:
            return
        vs = getattr(document, "view_state", None) or {}
        if "center" not in vs and "scale" not in vs:
            return
        self.edit_view.apply_view_state(vs)
        self.reference_panel.set_view_state(self.edit_view.view_state())

    def _restore_unified_composition_state(self, document) -> None:
        """Replay persisted presentation only after authoritative layers are rebuilt."""
        state = dict(getattr(document, "layer_state", None) or {}) if document else {}
        entries = [entry for entry in list(state.get("composition") or []) if isinstance(entry, dict)]
        for entry in entries:
            layer = self.unified_scene.registry.get(str(entry.get("id") or ""))
            if layer is None:
                continue
            if "name" in entry and str(entry["name"]):
                layer.name = str(entry["name"])
            if "crs" in entry:
                layer.crs = str(entry["crs"] or "")
            if "visible" in entry:
                layer.visible = bool(entry["visible"])
            if "opacity" in entry:
                layer.opacity = float(entry["opacity"])
            persisted_style = entry.get("style")
            if isinstance(persisted_style, dict):
                if self.unified_scene.scalar_layer(str(layer.id)) is not None:
                    raw_range = list(persisted_style.get("color_range") or ())
                    color_range = (
                        (float(raw_range[0]), float(raw_range[1]))
                        if len(raw_range) == 2 and float(raw_range[1]) >= float(raw_range[0])
                        else None
                    )
                    self.unified_scene.set_scalar_style(
                        str(layer.id),
                        color_ramp_name=str(persisted_style.get("color_ramp") or "default"),
                        color_range=color_range,
                        gamma=float(persisted_style.get("gamma", 1.0)),
                        nodata=str(persisted_style.get("nodata") or "transparent"),
                    )
                elif self.unified_scene.vector_features(str(layer.id)):
                    self.unified_scene.set_vector_style(str(layer.id), persisted_style)
        # Reapply hierarchy before flat order. The C++ registry validates group
        # parents/cycles, so stale legacy parent references remain harmless.
        for entry in entries:
            layer_id = str(entry.get("id") or "")
            parent_id = str(entry.get("parent_id") or "")
            if self.unified_scene.registry.get(layer_id) is not None:
                self.unified_scene.registry.set_parent(layer_id, parent_id)
        # Move one entry at a time to its persisted flat registry position.  Invalid
        # legacy references are ignored, leaving current authoritative layers intact.
        for entry in sorted(entries, key=lambda item: int(item.get("order", 0))):
            layer_id = str(entry.get("id") or "")
            if self.unified_scene.registry.get(layer_id) is not None:
                self.unified_scene.registry.move_layer(layer_id, max(0, int(entry.get("order", 0))))

    def _on_property_changed(self, feature_id: str, key: str, value: object) -> None:
        if (
            self._authoring_document is not None
            and self._unified_authoring_mode
            and self._authoring_document.change_attribute(feature_id, key, value)
        ):
            self._on_unified_tool_operation()
            return
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
            self._presentation_dirty = True
            self._refresh_unified_composition()
            self._stage_composition_state()
            self._sync_save_enabled()
            self._emit_mapping_context()

    def _on_reference_opacity_changed(self, layer_id: str, opacity: float) -> None:
        layer = self._reference_layer(layer_id)
        if layer is not None:
            layer.opacity = max(0.0, min(1.0, float(opacity)))
            self._presentation_dirty = True
            self._pending_opacity_refresh = True
            self._opacity_refresh.start()

    def _flush_reference_opacity(self) -> None:
        if not self._pending_opacity_refresh:
            return
        self._pending_opacity_refresh = False
        self._opacity_refresh.stop()
        self._refresh_unified_composition()
        self._stage_composition_state()
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _on_chrome_changed(self, chrome: dict) -> None:
        if self._active_document is None:
            return
        self._active_document.map_chrome = dict(chrome)
        self._presentation_dirty = True
        self.chrome_panel.update_state(self._active_document)
        # Decorations are a Qt overlay and must not schedule a QGIS data rebuild.
        self.unified_canvas.update()
        self._sync_save_enabled()
        self._emit_mapping_context()

    def _on_overlay_requested(self, resource_id: str) -> None:
        """Shared overlay path for the reference dock and the factor shelf.

        Resolves reference layers first. A completed factor-task id then follows the
        native FactorGridResult → ScalarGridLayer path without rerunning interpolation.
        """
        layer = self._reference_layer(str(resource_id))
        if layer is not None:
            layer.visible = True
            self._publish_reference_layers(self._active_document)
            self._emit_mapping_context()
            return
        task = self._factor_tasks_by_overlay_id.get(str(resource_id))
        if task is None:
            return
        try:
            from paleo_workbench.viz.native_factor_map import scene_from_factor_task

            drafts = [
                draft
                for draft in list(getattr(self._project, "contour_drafts", None) or [])
                if getattr(draft, "linked_factor_task_id", None) == getattr(task, "id", None)
            ]
            self._native_factor_scene = scene_from_factor_task(
                task,
                crs=self._project_crs,
                contour_drafts=drafts,
                scene=self.unified_scene,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.exception("Factor overlay failed for %s", resource_id)
            message = f"无法叠加参考图：{exc}"
            if getattr(self, "status_bar", None) is not None:
                self.status_bar.scale.setText(message)
            QMessageBox.warning(self, "参考叠加失败", message)
            return
        # Scalar rasters begin below the document's vector compatibility layers;
        # contours and samples remain above as separate registry entries.
        task_id = str(getattr(task, "id", "") or "")
        if task_id:
            self.unified_scene.registry.move_layer(task_id, 0)
        self.canvas_panel.load_native_scene(self._native_factor_scene)
        self._install_native_layer_tree(self._native_factor_scene)
        self._refresh_unified_composition()
        # A factor grid is an ordinary unified-map layer, not a mode change or a
        # second preview canvas.  The legacy panel stays populated for compatible
        # callers, while the visible authoring surface remains the same canvas.
        self.chrome_panel.update_state(self._active_document)
        self._emit_mapping_context()

    def export_native_factor_map(self, output_path, *, register: bool = True, format_label: str = "PNG"):
        """Export the active unified composition through the shared OUTPUT path.

        The scalar-layer ids are factor-task ids by construction, so they provide
        export lineage together with each layer's catalog provenance reference
        (DataVersion id) recorded on the render snapshot. Rendering runs on a
        worker; this slot only snapshots inputs and starts the job.
        """
        if self._native_factor_scene is None and not self.unified_scene.registry.layers():
            return None
        if self._export_job.is_running:
            return None

        task_ids = [
            layer.id
            for layer in self.unified_scene.registry.layers()
            if self.unified_scene.scalar_layer(layer.id) is not None
        ]
        lineage_ids = list(dict.fromkeys(task_ids + list(self.unified_canvas.snapshot_source_version_ids)))
        output = Path(output_path)
        spec = snapshot_map_export(self.unified_canvas, output)
        self._pending_export = {
            "path": output,
            "widget": self.unified_canvas,
            "project": self._project,
            "linked_id": lineage_ids[0] if lineage_ids else "factor_map",
            "register": register,
            "source_task_ids": lineage_ids,
        }
        self._begin_export_busy()
        start_map_export_job(
            self._export_job,
            spec,
            on_finished=self._on_map_export_finished,
            on_failed=self._on_map_export_failed,
            on_cancelled=self._on_map_export_cancelled,
        )
        return None

    def _begin_export_busy(self) -> None:
        if not self._export_busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._export_busy = True
        if getattr(self, "status_bar", None) is not None:
            self.status_bar.scale.setText("正在导出…")

    def _end_export_busy(self) -> None:
        if self._export_busy:
            QApplication.restoreOverrideCursor()
            self._export_busy = False

    def _on_export_job_released(self) -> None:
        if self._export_busy:
            self._end_export_busy()

    def _on_map_export_finished(self, path: str) -> None:
        pending = self._pending_export
        self._pending_export = None
        self._end_export_busy()
        if pending:
            from paleo_workbench.resources.export_service import register_exported_view

            register_exported_view(
                pending["widget"],
                pending["path"],
                "PNG",
                project=pending["project"],
                project_path=None,
                linked_id=pending["linked_id"],
                register=pending["register"],
                source_task_ids=pending["source_task_ids"],
            )
        if getattr(self, "status_bar", None) is not None:
            self.status_bar.scale.setText(f"已导出视图: {Path(path).name}")

    def _on_map_export_failed(self, message: str) -> None:
        self._pending_export = None
        self._end_export_busy()
        QMessageBox.warning(self, "导出失败", message)

    def _on_map_export_cancelled(self) -> None:
        self._pending_export = None
        self._end_export_busy()
        if getattr(self, "status_bar", None) is not None:
            self.status_bar.scale.setText("已取消导出")

    def _on_topology_locate_requested(self, feature_id: str) -> None:
        """Select the flagged feature and center the edit view on it."""
        scene = self._edit_scene()
        if scene is None:
            return
        item = scene.item_by_id(str(feature_id))
        if not isinstance(item, QGraphicsItem):
            return
        scene.clearSelection()
        item.setSelected(True)
        target = None
        for issue in scene.topology_issues():
            if issue.get("feature_id") != item.feature_id:
                continue
            location = issue.get("location")
            if isinstance(location, (list, tuple)) and len(location) >= 2:
                try:
                    target = QPointF(float(location[0]), float(location[1]))
                    break
                except (ValueError, TypeError):
                    continue
        if target is None:
            target = item.sceneBoundingRect().center()
        self.edit_view.centerOn(target)

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
        self._snapping.set_reference_points(points)

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
        self._sync_action_state()

    def _sync_save_enabled(self) -> None:
        can_save = self._active_document is not None and self.is_dirty()
        self.toolbar.save_draft_btn.setEnabled(can_save)
        self.chrome_panel.save_btn.setEnabled(can_save)
        self._sync_action_state()

    def _emit_mapping_context(self) -> None:
        self.mapping_context_changed.emit(self.mapping_context())
