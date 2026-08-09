from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.viz.prediction_helpers import active_prediction_task
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.workflow.well_log_prediction import (
    export_well_canvas,
    run_well_log_facies_prediction,
)


class WellLogPredictionPage(QWidget):
    """测井预测 page: LAS-bound well + lithology/facies tracks + export."""

    prediction_updated = Signal()
    send_to_preparation_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogPredictionPage")
        self._project = None
        self._tasks: list = []
        self._selected_index: int | None = None

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

        self.task_panel = PredictionTaskPanel()
        content.addWidget(self.task_panel, 0)

        self.canvas_panel = WellLogCanvasPanel()
        content.addWidget(self.canvas_panel, 1)

        self.evidence_panel = PredictionEvidencePanel()
        content.addWidget(self.evidence_panel, 0)

        outer.addLayout(content, 1)

        self.task_panel.task_selected.connect(self._on_task_selected)
        self.evidence_panel.run_requested.connect(self._on_run)
        self.evidence_panel.send_requested.connect(self.send_to_preparation_requested.emit)
        self.evidence_panel.export_requested.connect(self._on_export)

    def set_project(self, project) -> None:
        self._project = project

    def update_state(self, prediction_tasks: list | tuple | None, project=None) -> None:
        if project is not None:
            self._project = project
        self._tasks = list(prediction_tasks or [])
        if self._selected_index is not None and not (
            0 <= self._selected_index < len(self._tasks)
        ):
            self._selected_index = None
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=self._selected_index)
        self.canvas_panel.update_state(task, project=self._project)
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def _current_task(self):
        if self._selected_index is not None and 0 <= self._selected_index < len(
            self._tasks
        ):
            return self._tasks[self._selected_index]
        return active_prediction_task(self._tasks)

    def _on_task_selected(self, index: int) -> None:
        self._selected_index = index
        task = self._current_task()
        self.task_panel.update_state(self._tasks, selected_index=index)
        self.canvas_panel.update_state(task, project=self._project)
        self.evidence_panel.update_state(
            task, bound_las=self.canvas_panel.has_bound_las()
        )

    def set_selected_well(self, well_name: str) -> bool:
        """Cross-page seam: select the prediction task whose name matches *well_name*.

        Returns True when a matching task was found and selected. Used by the
        workflow controller to sync a well picked on the 3D page into this page.
        """
        if not well_name:
            return False
        for index, task in enumerate(self._tasks):
            if getattr(task, "name", None) == well_name:
                # Set the list selection synchronously: reset to -1 first so the
                # target row change always fires (QListWidget won't emit
                # currentRowChanged for a no-op set), then select the item.
                lst = self.task_panel.task_list
                item = lst.item(index)
                lst.setCurrentRow(-1)
                if item is not None:
                    lst.setCurrentItem(item)
                self._selected_index = index
                task = self._current_task()
                self.canvas_panel.update_state(task, project=self._project)
                self.evidence_panel.update_state(
                    task, bound_las=self.canvas_panel.has_bound_las()
                )
                return True
        return False

    def _on_run(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "测井预测", "未绑定工程，无法运行")
            return
        try:
            run_well_log_facies_prediction(self._project, seed=len(self._tasks))
        except Exception as exc:
            QMessageBox.warning(
                self,
                "测井预测失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        self._tasks = list(self._project.prediction_tasks)
        self._selected_index = len(self._tasks) - 1
        self.update_state(self._tasks, project=self._project)
        self.prediction_updated.emit()

    def _on_export(self, format_label: str = "PNG") -> None:
        if not self.canvas_panel.is_canvas_ready():
            QMessageBox.warning(self, "导出", "当前没有可导出的测井剖面")
            return
        label = (format_label or "PNG").upper()
        suffix = {"PNG": ".png", "SVG": ".svg", "PDF": ".pdf"}.get(label, ".png")
        data = self.canvas_panel.well_log_data
        stem = getattr(data, "well_name", None) or "well_log"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(stem))[:64]
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"导出单井剖面 ({label})",
            str(start_dir / f"{safe}_well{suffix}"),
            f"{label} (*{suffix})",
        )
        if not path:
            return
        try:
            if (
                self.canvas_panel.backend() == "engine"
                and self.canvas_panel._engine_view is not None
            ):
                # Engine binding currently exposes curve submit + OpenGL view;
                # vector export stays on the Legacy canvas path. PNG uses a
                # widget grab so Feature Flag users still get a graphic export.
                if label != "PNG":
                    raise RuntimeError(
                        "WellLogEngine 路径暂仅支持 PNG 抓屏导出；"
                        "请切换到 Legacy 导出 SVG/PDF"
                    )
                view = self.canvas_panel._engine_view
                if view is None:
                    raise RuntimeError("WellLogEngine 视图不可用")
                pixmap = view.grab()
                if pixmap.isNull():
                    raise RuntimeError("WellLogEngine 抓屏失败")
                if not pixmap.save(path, "PNG"):
                    raise RuntimeError("PNG 写入失败")
            else:
                export_well_canvas(self.canvas_panel.canvas, path, label)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "导出失败",
                f"{exc.__class__.__name__}: {exc}",
            )
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")
