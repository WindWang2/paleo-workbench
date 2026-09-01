from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui import tokens
from paleo_workbench.ui.dock_manager import dock_manager
from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.panel_float_controller import FloatController
from paleo_workbench.ui.pages.action_header import ActionHeader
from paleo_workbench.ui.pages.qc_issue_table import QCIssueTable
from paleo_workbench.ui.pages.result_summary import ResultSummary
from paleo_workbench.workflow.qc import active_quality_reports, run_basic_qc
from paleo_workbench.workflow.qc_report_export import export_quality_report_json
from paleo_workbench.workflow.versioning import finalize_map_version

# QWIDGETSIZE_MAX: lifts a side panel's setFixedWidth upper bound (the
# designed width stays as the minimum) so the splitter handle can resize it.
_PANEL_MAX_WIDTH = 16_777_215

#: Delay before a splitter drag is persisted (avoid a QSettings sync per tick).
_DOCKED_SIZES_DELAY_MS = 400


class PanelFloatButton(QToolButton):
    """Corner button floating one side panel via a FloatController.

    Docked side of the FloatingPanel ⇲ dock-back chrome: pinned to the
    panel's top-right corner through an event filter and hidden while the
    panel is afloat (the floating window carries its own dock-back button).
    """

    def __init__(self, key: str, panel: QWidget, controller: FloatController):
        super().__init__(panel)
        self._key = key
        self._panel = panel
        self._controller = controller
        self.setObjectName("PanelFloatButton")
        self.setText("⇱")
        self.setToolTip("浮动面板 (Float panel)")
        self.setFixedSize(18, 18)
        self.clicked.connect(lambda: self._controller.toggle(self._key))
        panel.installEventFilter(self)
        controller.float_changed.connect(self._on_float_changed)
        self._reposition()

    def _reposition(self) -> None:
        self.move(self._panel.width() - self.width() - 4, 2)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if obj is self._panel and event.type() == QEvent.Type.Resize:
            self._reposition()
        return False

    def _on_float_changed(self, key: str, floating: bool) -> None:
        if key == self._key:
            self.setVisible(not floating)


class ReviewExportPage(QWidget):
    """成图审核 page: run QC, review issues, export report JSON, expert finalize."""

    reports_updated = Signal()
    version_finalized = Signal()

    def __init__(self, parent=None, *, persistence: LayoutPersistence | None = None):
        super().__init__(parent)
        self.setObjectName("ReviewExportPage")
        self._project = None
        self._project_path: Path | None = None
        self._reports: list = []
        self._map_documents: list = []
        self._artifacts: list = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        self.action_header = ActionHeader()
        outer.addWidget(self.action_header, 0)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("ReviewExportSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.qc_table = QCIssueTable()
        # 质检问题表 stays the stretchy center; the summary is the resizable
        # side panel.
        self.content_splitter.addWidget(self.qc_table)

        self.result_summary = ResultSummary()
        self.result_summary.setMaximumWidth(_PANEL_MAX_WIDTH)
        self.content_splitter.addWidget(self.result_summary)

        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([1000, 260])

        outer.addWidget(self.content_splitter, 1)

        # M6: the QC summary floats through the shared FloatController; the
        # issue table stays the docked center.
        self._float_persistence = (
            persistence if persistence is not None else LayoutPersistence()
        )
        self._floatable: dict[str, QWidget] = {}
        self.float_controller = FloatController(
            resolver=self._floatable.get,
            persistence=self._float_persistence,
            parent=self,
        )
        self._make_floatable("review:summary", self.result_summary, "结果摘要")
        self._float_sizes_timer = QTimer(self)
        self._float_sizes_timer.setSingleShot(True)
        self._float_sizes_timer.setInterval(_DOCKED_SIZES_DELAY_MS)
        self._float_sizes_timer.timeout.connect(self._persist_docked_sizes)
        self.content_splitter.splitterMoved.connect(self._on_splitter_moved)
        for key in self._floatable:
            self.float_controller.restore_saved(key)

        self.action_header.run_requested.connect(self.run_qc)
        self.action_header.export_requested.connect(self.export_report)
        self.action_header.config_requested.connect(self._on_config)
        self.action_header.finalize_requested.connect(self.finalize_version)


    def ribbon_panel_entries(self) -> list[dict]:
        """Ribbon 右键面板菜单：本页可浮动面板的显隐/浮动管理。"""
        from paleo_workbench.ui.panel_float_controller import floatable_panel_entries

        return floatable_panel_entries(self.float_controller, self._floatable)

    def _make_floatable(self, key: str, panel: QWidget, title: str) -> None:
        """Register a side panel for float/dock and give it a float button."""
        dock_manager.register_panel(key, title)
        self._floatable[key] = panel
        PanelFloatButton(key, panel, self.float_controller)

    def _on_splitter_moved(self, *_pos: int) -> None:
        self._float_sizes_timer.start()

    def _persist_docked_sizes(self) -> None:
        """Persist the splitter distribution for every docked side panel."""
        sizes = list(self.content_splitter.sizes())
        for key, panel in self._floatable.items():
            if panel.parentWidget() is self.content_splitter:
                self._float_persistence.save_docked_sizes(key, sizes)

    def set_project(self, project) -> None:
        self._project = project

    def set_project_path(self, path) -> None:
        """Bind the real ``*.paleo.json`` path for export/artifact routing."""
        self._project_path = Path(path) if path else None

    def update_state(self, reports: list, map_documents: list, artifacts: list) -> None:
        self._reports = list(reports or [])
        self._map_documents = list(map_documents or [])
        self._artifacts = list(artifacts or [])
        self.action_header.update_state(self._reports, self._map_documents)
        self.qc_table.update_state(self._reports)
        self.result_summary.update_state(self._reports, self._artifacts)

    def run_qc(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "质检", "未绑定工程")
            return
        docs = list(self._project.paleomap_documents or [])
        if not docs:
            QMessageBox.information(self, "质检", "工程中尚无古地理图草稿，请先编图或生成演示草稿")
            return
        ran = 0
        for doc in docs:
            run_basic_qc(self._project, doc.id)
            ran += 1
        self._refresh_from_project()
        self.reports_updated.emit()
        QMessageBox.information(self, "质检完成", f"已检查 {ran} 幅图件")

    def export_report(self) -> None:
        reports = active_quality_reports(self._project) if self._project is not None else self._reports
        if not reports:
            QMessageBox.information(self, "导出", "暂无质检报告可导出，请先运行检查")
            return
        report = reports[0]
        start_dir = default_export_dir(self._project_path)
        suggested = start_dir / f"qc_{report.linked_map_document_id or report.id}.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出质检报告",
            str(suggested),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            export_quality_report_json(
                report,
                path,
                project=self._project,
                register=self._project is not None,
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        self._refresh_from_project()
        self.reports_updated.emit()
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")

    def _on_config(self) -> None:
        rules = " · ".join(tokens.DEFAULT_QC_RULES)
        QMessageBox.information(
            self,
            "质检规则",
            f"当前内置规则：\n{rules}\n\n规则编辑器将在后续版本提供。",
        )

    def finalize_version(self) -> None:
        """Expert sign-off: write VersionSet snapshot for the active / last map."""
        if self._project is None:
            QMessageBox.warning(self, "专家定稿", "未绑定工程")
            return
        docs = list(self._project.paleomap_documents or [])
        if not docs:
            QMessageBox.information(self, "专家定稿", "工程中尚无古地理图可定稿")
            return
        # Prefer map linked by latest QC report, else last document.
        doc = docs[-1]
        reports = active_quality_reports(self._project)
        if reports:
            linked = reports[0].linked_map_document_id
            for d in docs:
                if d.id == linked:
                    doc = d
                    break
        try:
            vset = finalize_map_version(
                self._project,
                doc.id,
                note="审核页专家定稿",
                operator="expert",
                require_qc_pass=False,
            )
        except Exception as exc:
            QMessageBox.warning(self, "定稿失败", f"{exc.__class__.__name__}: {exc}")
            return
        self._refresh_from_project()
        self.version_finalized.emit()
        self.reports_updated.emit()
        QMessageBox.information(
            self,
            "定稿完成",
            f"已定稿图件「{doc.name}」\n"
            f"VersionSet: {vset.name}\n"
            f"状态: {vset.status} · 快照数: {len(vset.snapshots)}",
        )

    def _refresh_from_project(self) -> None:
        if self._project is None:
            return
        self.update_state(
            active_quality_reports(self._project),
            self._project.paleomap_documents,
            self._project.export_artifacts,
        )
