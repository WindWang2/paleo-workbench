from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.export_service import (
    default_export_dir,
    export_widget_snapshot,
    view_export_capabilities,
)
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizRef


class VisualizationPage(QWidget):
    """Display-first 可视化 page combining geo-viz widgets."""

    def __init__(
        self,
        parent=None,
        *,
        well_state_store=None,
        preview_provider=None,
    ):
        super().__init__(parent)
        self.setObjectName("VisualizationPage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(100, 100)

        self._resources: list = []
        self._prediction_tasks: list = []
        self._map_documents: list = []
        self._project: ProjectDocument | None = None
        self._current_ref: VizRef | None = None
        self._adapter = VizAdapter()
        self._preview_controller = PreviewRequestController(
            preview_provider or LocalVisualizationProvider(),
            self,
            request_kind="visualization",
        )
        self._preview_controller.loading.connect(self._show_preview_loading)
        self._preview_controller.result_ready.connect(self._apply_preview_result)
        self._preview_controller.failed.connect(self._show_preview_error)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        # Top bar with asset selector dropdown + Coordinate System Toggle
        top_bar = QHBoxLayout()
        top_bar.setSpacing(tokens.SPACE_2)

        asset_label = QLabel("📊 选择数据资产:")
        asset_label.setStyleSheet(f"font-weight: bold; color: {tokens.TEXT_SECONDARY};")
        top_bar.addWidget(asset_label)

        self.asset_combo = QComboBox()
        self.asset_combo.setMinimumWidth(280)
        self.asset_combo.setStyleSheet(
            f"QComboBox {{ border: 1px solid {tokens.BORDER}; border-radius: 4px; padding: 4px 8px; background: {tokens.BG_SIDEBAR}; color: {tokens.TEXT_PRIMARY}; }}"
        )
        self.asset_combo.currentIndexChanged.connect(self._on_asset_combo_changed)
        top_bar.addWidget(self.asset_combo)

        # 1-Click Geographic / Grid coordinate toggle
        self.btn_coord = QPushButton("📍 网格(IL/XL)")
        self.btn_coord.setCheckable(True)
        self.btn_coord.setStyleSheet(
            f"QPushButton {{ border: 1px solid {tokens.BORDER}; border-radius: 4px; padding: 5px 14px; background: {tokens.BG_SIDEBAR}; color: {tokens.TEXT_PRIMARY}; font-weight: bold; }}"
            f"QPushButton:checked {{ background: {tokens.PRIMARY}; color: #ffffff; border-color: {tokens.PRIMARY_PRESSED}; }}"
        )
        self.btn_coord.clicked.connect(self._on_coord_toggle_clicked)
        top_bar.addWidget(self.btn_coord)

        top_bar.addStretch()

        outer.addLayout(top_bar)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        self.summary_panel = VisualizationSummaryPanel()
        self.summary_panel.setHidden(True)

        self.composite_panel = CompositeVisualizationPanel(
            well_state_store=well_state_store,
        )
        content.addWidget(self.composite_panel, 1)

        self.trace_panel = VisualizationTracePanel()
        content.addWidget(self.trace_panel, 0)

        outer.addLayout(content, 1)

        self.summary_panel.asset_selected.connect(self.open_ref)
        self.trace_panel.refresh_requested.connect(self._reload_current)
        self.trace_panel.export_requested.connect(self._export_current_view)
        self.composite_panel.tabs.currentChanged.connect(
            lambda _index: self._sync_export_capabilities()
        )
        self._sync_export_capabilities()

    def update_state(
        self,
        resources: list,
        prediction_tasks: list,
        map_documents: list,
        project: ProjectDocument | None = None,
    ) -> None:
        self._resources = list(resources or [])
        self._prediction_tasks = list(prediction_tasks or [])
        self._map_documents = list(map_documents or [])
        self._project = project
        comparison_crs = str(
            getattr(getattr(project, "coordinate", None), "project_crs", "") or ""
        )
        provider = self._preview_controller.provider
        if isinstance(provider, LocalVisualizationProvider):
            provider.comparison_crs = comparison_crs
        self._preview_controller.set_comparison_crs(comparison_crs or None)
        project_root = getattr(getattr(project, "meta", None), "project_root", None)
        project_root_text = str(project_root or "").strip()
        self._preview_controller.set_project_root(
            project_root_text if project_root_text and project_root_text != "." else None
        )

        self.summary_panel.update_state(
            self._resources, self._prediction_tasks, self._map_documents
        )
        self.trace_panel.update_state(self._prediction_tasks, self._map_documents)

        # Update asset combo dropdown
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        for res in self._resources:
            ref = self._adapter.ref_from_resource(res)
            if ref is not None:
                icon = "📋 " if ref.kind == "well_log" else "📈 "
                self.asset_combo.addItem(f"{icon}{ref.label}", ref)
        for doc in self._map_documents:
            ref = self._adapter.ref_from_map_document(doc)
            self.asset_combo.addItem(f"🗺️ {ref.label}", ref)
        self.asset_combo.blockSignals(False)

        self.composite_panel.update_state(self._prediction_tasks)

        if self._current_ref is None:
            first_ref = None
            for idx in range(self.asset_combo.count()):
                ref = self.asset_combo.itemData(idx)
                if ref is not None and getattr(ref, "kind", "") == "well_log":
                    if ref.path and Path(ref.path).is_file():
                        first_ref = ref
                        self.asset_combo.blockSignals(True)
                        self.asset_combo.setCurrentIndex(idx)
                        self.asset_combo.blockSignals(False)
                        break

            if first_ref is not None:
                self.open_ref(first_ref)
        else:
            self.open_ref(self._current_ref)

    def _on_asset_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        ref = self.asset_combo.itemData(index)
        if ref is not None:
            self.open_ref(ref)

    def open_ref(self, ref: VizRef | None) -> None:
        if ref is None:
            return
        self._current_ref = ref
        for idx in range(self.asset_combo.count()):
            item_ref = self.asset_combo.itemData(idx)
            if item_ref == ref or (
                isinstance(item_ref, VizRef)
                and isinstance(ref, VizRef)
                and item_ref.id == ref.id
                and item_ref.path == ref.path
            ):
                self.asset_combo.blockSignals(True)
                self.asset_combo.setCurrentIndex(idx)
                self.asset_combo.blockSignals(False)
                break

        project = self._project_stub()
        if ref.kind == "engine_preview":
            resource = self._adapter.engine_preview_resource(ref, project)
            if resource is None:
                self._show_preview_error("未找到对应的数据资产")
                return
            self.trace_panel.update_ref(ref, None)
            self._preview_controller.request(resource)
            return

        self._preview_controller.invalidate()
        payload = self._adapter.resolve(ref, project)
        self.composite_panel.load_payload(payload)
        self.trace_panel.update_ref(ref, payload)
        self._sync_export_capabilities()

    def _show_preview_loading(self) -> None:
        ref = self._current_ref
        label = ref.label if ref is not None else ""
        self.composite_panel.status_label.setText(f"正在加载: {label or '引擎预览'}")

    def _apply_preview_result(self, result) -> None:
        ref = self._current_ref
        if ref is None or ref.kind != "engine_preview":
            return
        payload = self._adapter.payload_from_engine_preview_result(ref, result)
        self.composite_panel.load_payload(payload)
        self.trace_panel.update_ref(ref, payload)
        self._sync_export_capabilities()

    def _show_preview_error(self, message: str) -> None:
        ref = self._current_ref
        if ref is None or ref.kind != "engine_preview":
            return
        from paleo_workbench.viz.models import VizPayload

        payload = VizPayload(
            kind="message",
            label=ref.label or ref.id or ref.kind,
            message=message or "引擎预览失败",
        )
        self.composite_panel.load_payload(payload)
        self.trace_panel.update_ref(ref, payload)
        self._sync_export_capabilities()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._preview_controller.shutdown()
        super().closeEvent(event)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.DeferredDelete and hasattr(
            self, "_preview_controller"
        ):
            self._preview_controller.shutdown()
        return super().event(event)

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Release async previews before a project-scoped shell is replaced."""

        return self._preview_controller.shutdown(wait_ms)

    def _reload_current(self) -> None:
        if self._current_ref is not None:
            self.open_ref(self._current_ref)
        else:
            self.composite_panel.update_state(self._prediction_tasks)
            self._sync_export_capabilities()

    def _sync_export_capabilities(self) -> None:
        """Gate SVG/PDF buttons by the active composite tab's export surface."""
        widget = self.composite_panel.tabs.currentWidget()
        self.trace_panel.set_export_capabilities(view_export_capabilities(widget))

    def _export_current_view(self, format_label: str = "PNG") -> None:
        """Export the active composite tab via engine helpers / grab()."""
        widget = self.composite_panel.tabs.currentWidget()
        if widget is None:
            QMessageBox.warning(self, "导出", "当前没有可导出的视图")
            return
        label = (format_label or "PNG").upper()
        caps = view_export_capabilities(widget)
        if label not in caps:
            supported = "、".join(sorted(caps)) or "无"
            QMessageBox.warning(
                self,
                "导出",
                f"当前 Tab 不支持 {label} 导出（可用: {supported}）。"
                "测井 / 连井 / 古地理支持矢量 SVG/PDF。",
            )
            return
        tab_name = self.composite_panel.tabs.tabText(
            self.composite_panel.tabs.currentIndex()
        )
        suffix = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf"}.get(label, ".png")
        stem = (self._current_ref.label if self._current_ref else tab_name) or "view"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:64]
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        suggested = str(start_dir / f"{safe}_{tab_name}{suffix}")
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出视图 ({label})",
            suggested,
            f"{label} (*{suffix})",
        )
        if not path:
            return
        result = export_widget_snapshot(
            widget,
            Path(path),
            label,
            project=self._project_stub() if self._project is not None else None,
            linked_id=(self._current_ref.id if self._current_ref else "viz_view"),
            register=self._project is not None,
        )
        if result.success:
            self.composite_panel.status_label.setText(result.message)
        else:
            QMessageBox.warning(self, "导出失败", result.message)

    def _project_stub(self) -> ProjectDocument:
        if self._project is not None:
            return self._project
        doc = ProjectDocument.new("_viz")
        doc.resources = list(self._resources)
        doc.prediction_tasks = list(self._prediction_tasks)
        doc.paleomap_documents = list(self._map_documents)
        return doc

    def _on_coord_toggle_clicked(self) -> None:
        """Toggle Geographic/Grid coordinate mode label.

        Note: the actual coordinate-mode propagation happens on the 3D
        geological-modeling page (which owns the GL widget's set_coord_mode).
        This button on the visualization page only relabels itself — the
        seismic view panel does not expose a coord-mode toggle (the dead
        hasattr(sv, "btn_coord") branch was removed).
        """
        is_geo = self.btn_coord.isChecked()
        self.btn_coord.setText("🌐 地理(X/Y)" if is_geo else "📍 网格(IL/XL)")
