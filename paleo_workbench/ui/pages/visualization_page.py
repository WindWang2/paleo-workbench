from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.export_service import (
    default_export_dir,
    export_widget_snapshot,
    view_export_capabilities,
)
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizRef


class VisualizationPage(QWidget):
    """Display-first 可视化 page combining geo-viz widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationPage")

        self._resources: list = []
        self._prediction_tasks: list = []
        self._map_documents: list = []
        self._project: ProjectDocument | None = None
        self._current_ref: VizRef | None = None
        self._adapter = VizAdapter()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        self.summary_panel = VisualizationSummaryPanel()
        self.summary_panel.setHidden(True)

        self.composite_panel = CompositeVisualizationPanel()
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

        self.summary_panel.update_state(
            self._resources, self._prediction_tasks, self._map_documents
        )
        self.trace_panel.update_state(self._prediction_tasks, self._map_documents)

        if self._current_ref is None:
            self.composite_panel.update_state(self._prediction_tasks)
        else:
            self.open_ref(self._current_ref)

    def open_ref(self, ref: VizRef | None) -> None:
        if ref is None:
            return
        self._current_ref = ref
        project = self._project_stub()
        payload = self._adapter.resolve(ref, project)
        self.composite_panel.load_payload(payload)
        self.trace_panel.update_ref(ref, payload)
        self._sync_export_capabilities()

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
