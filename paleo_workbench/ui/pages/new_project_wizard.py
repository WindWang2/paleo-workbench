"""新建工程向导对话框 — 两步向导（设置→分析与预览）。

New project wizard: step 1 validates inputs, step 2 runs
:func:`paleo_workbench.project.onboarding.analyze_data_folder` on a worker
thread via :class:`paleo_workbench.ui.owned_worker_job.OwnedWorkerJob`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QCheckBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.onboarding import analyze_data_folder
from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.well_map_panel import WellMapPanel


class _AnalyzeWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, data_dir: Path, project_name: str, engine=None) -> None:
        super().__init__()
        self._data_dir = data_dir
        self._project_name = project_name
        self._engine = engine

    def run(self) -> None:
        try:
            result = analyze_data_folder(
                self._data_dir, project_name=self._project_name, engine=self._engine
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        self.finished.emit(result)


class NewProjectWizardDialog(QDialog):
    """两步新建工程向导对话框."""

    def __init__(self, parent=None, *, engine=None) -> None:
        super().__init__(parent)
        self.setObjectName("NewProjectWizard")
        self.setWindowTitle("新建工程")
        self.setMinimumWidth(640)
        self.resize(720, 560)
        self._engine = engine
        self._result_document: ProjectDocument | None = None
        self._report: dict[str, Any] | None = None
        self._analysis_state: str = "idle"  # idle | running | success | failed
        self._job = OwnedWorkerJob(self)
        self._well_map_panel: WellMapPanel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        root.setSpacing(tokens.SPACE_2)

        # Stacked pages
        self._stack = QStackedWidget(self)
        root.addWidget(self._stack, 1)

        # ---- Page 0 : 设置 ----
        self._page0 = QWidget()
        page0_layout = QVBoxLayout(self._page0)
        page0_layout.setContentsMargins(0, 0, 0, 0)
        page0_layout.setSpacing(tokens.SPACE_2)
        form = QFormLayout()
        form.setSpacing(tokens.SPACE_2)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit(self._page0)
        self._name_edit.setObjectName("WizardNameEdit")
        self._name_edit.setPlaceholderText("请输入工程名称")
        form.addRow("工程名称：", self._name_edit)

        # 数据文件夹行
        data_row = QWidget(self._page0)
        data_row_layout = QHBoxLayout(data_row)
        data_row_layout.setContentsMargins(0, 0, 0, 0)
        data_row_layout.setSpacing(tokens.SPACE_2)
        self._data_dir_edit = QLineEdit(data_row)
        self._data_dir_edit.setReadOnly(True)
        self._data_dir_edit.setPlaceholderText("请选择原始数据文件夹")
        self._data_browse_btn = QPushButton("浏览…", data_row)
        self._data_browse_btn.setObjectName("SecondaryButton")
        self._data_browse_btn.clicked.connect(self._browse_data_dir)
        data_row_layout.addWidget(self._data_dir_edit, 1)
        data_row_layout.addWidget(self._data_browse_btn)
        form.addRow("原始数据文件夹：", data_row)

        # 同目录复选框
        self._same_dir_check = QCheckBox("中间文件与原始数据同目录", self._page0)
        self._same_dir_check.setChecked(True)
        self._same_dir_check.toggled.connect(self._on_same_dir_toggled)
        form.addRow("", self._same_dir_check)

        # 中间目录行（默认隐藏）
        self._intermediate_row = QWidget(self._page0)
        inter_layout = QHBoxLayout(self._intermediate_row)
        inter_layout.setContentsMargins(0, 0, 0, 0)
        inter_layout.setSpacing(tokens.SPACE_2)
        self._intermediate_edit = QLineEdit(self._intermediate_row)
        self._intermediate_edit.setReadOnly(True)
        self._intermediate_edit.setPlaceholderText("请选择中间文件目录")
        self._intermediate_browse_btn = QPushButton("浏览…", self._intermediate_row)
        self._intermediate_browse_btn.setObjectName("SecondaryButton")
        self._intermediate_browse_btn.clicked.connect(self._browse_intermediate_dir)
        inter_layout.addWidget(self._intermediate_edit, 1)
        inter_layout.addWidget(self._intermediate_browse_btn)
        self._intermediate_label = QLabel("中间文件目录：", self._page0)
        form.addRow(self._intermediate_label, self._intermediate_row)
        self._intermediate_label.setVisible(False)
        self._intermediate_row.setVisible(False)

        page0_layout.addLayout(form)

        self._error_label = QLabel("", self._page0)
        self._error_label.setObjectName("WizardErrorLabel")
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(f"color: {tokens.ERROR_RED}; font-size: 11px;")
        self._error_label.hide()
        page0_layout.addWidget(self._error_label)
        page0_layout.addStretch(1)

        self._stack.addWidget(self._page0)

        # ---- Page 1 : 分析与预览 ----
        self._page1 = QWidget()
        self._step2_layout = QVBoxLayout(self._page1)
        self._step2_layout.setContentsMargins(0, 0, 0, 0)
        self._step2_layout.setSpacing(tokens.SPACE_2)

        self._progress = QProgressBar(self._page1)
        self._progress.setRange(0, 0)
        self._progress.hide()
        self._step2_layout.addWidget(self._progress)

        self._status_label = QLabel("", self._page1)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        self._status_label.hide()
        self._step2_layout.addWidget(self._status_label)

        self._summary_label = QLabel("", self._page1)
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(f"font-weight: 600; color: {tokens.TEXT_PRIMARY};")
        self._summary_label.hide()
        self._step2_layout.addWidget(self._summary_label)

        self._inventory_table = QTableWidget(0, 2, self._page1)
        self._inventory_table.setObjectName("WizardInventoryTable")
        self._inventory_table.setHorizontalHeaderLabels(["数据类型", "数量"])
        header = self._inventory_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._inventory_table.verticalHeader().setVisible(False)
        self._inventory_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._inventory_table.setAlternatingRowColors(True)
        self._inventory_table.hide()
        self._step2_layout.addWidget(self._inventory_table)

        self._issues_browser = QTextBrowser(self._page1)
        self._issues_browser.setReadOnly(True)
        self._issues_browser.setMaximumHeight(120)
        self._issues_browser.hide()
        self._step2_layout.addWidget(self._issues_browser)

        self._step2_error = QLabel("", self._page1)
        self._step2_error.setObjectName("WizardStep2ErrorLabel")
        self._step2_error.setWordWrap(True)
        self._step2_error.setStyleSheet(f"color: {tokens.ERROR_RED}; font-size: 11px;")
        self._step2_error.hide()
        self._step2_layout.addWidget(self._step2_error)

        self._step2_layout.addStretch(1)

        self._stack.addWidget(self._page1)

        # ---- Buttons ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(tokens.SPACE_2)
        self._cancel_btn = QPushButton("取消", self)
        self._cancel_btn.setObjectName("SecondaryButton")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch(1)
        self._back_btn = QPushButton("上一步", self)
        self._back_btn.setObjectName("SecondaryButton")
        self._back_btn.clicked.connect(self._on_back_clicked)
        self._back_btn.setEnabled(False)
        btn_row.addWidget(self._back_btn)
        self._next_btn = QPushButton("下一步", self)
        self._next_btn.setObjectName("PrimaryButton")
        self._next_btn.clicked.connect(self._on_next_clicked)
        btn_row.addWidget(self._next_btn)
        self._finish_btn = QPushButton("完成", self)
        self._finish_btn.setObjectName("PrimaryButton")
        self._finish_btn.setEnabled(False)
        self._finish_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._finish_btn)
        root.addLayout(btn_row)

        self._stack.setCurrentIndex(0)
        self._update_buttons()

    # -- properties -------------------------------------------------------
    @property
    def result_document(self) -> ProjectDocument | None:
        return self._result_document

    @property
    def project_name(self) -> str:
        return self._name_edit.text().strip()

    @property
    def data_dir(self) -> Path | None:
        text = self._data_dir_edit.text().strip()
        return Path(text) if text else None

    @property
    def intermediate_dir(self) -> Path | None:
        if self._same_dir_check.isChecked():
            return self.data_dir
        text = self._intermediate_edit.text().strip()
        return Path(text) if text else None

    # -- browsing ---------------------------------------------------------
    def _browse_data_dir(self) -> None:
        start = self._data_dir_edit.text().strip() or ""
        dir_path = QFileDialog.getExistingDirectory(self, "选择数据文件夹", start)
        if dir_path:
            self._data_dir_edit.setText(dir_path)
            if not self._name_edit.text().strip():
                try:
                    self._name_edit.setText(Path(dir_path).name)
                except Exception:
                    pass
            self._clear_error()

    def _browse_intermediate_dir(self) -> None:
        start = self._intermediate_edit.text().strip() or self._data_dir_edit.text().strip() or ""
        dir_path = QFileDialog.getExistingDirectory(self, "选择中间文件目录", start)
        if dir_path:
            self._intermediate_edit.setText(dir_path)
            self._clear_error()

    def _on_same_dir_toggled(self, checked: bool) -> None:
        self._intermediate_label.setVisible(not checked)
        self._intermediate_row.setVisible(not checked)
        self._clear_error()

    # -- validation -------------------------------------------------------
    def _show_error(self, msg: str) -> None:
        self._error_label.setText(msg)
        self._error_label.show()

    def _clear_error(self) -> None:
        self._error_label.hide()
        self._error_label.setText("")

    def _validate_step1(self) -> bool:
        name = self._name_edit.text().strip()
        if not name:
            self._show_error("请输入工程名称")
            return False
        data_text = self._data_dir_edit.text().strip()
        if not data_text:
            self._show_error("请选择原始数据文件夹")
            return False
        data_path = Path(data_text)
        if not data_path.exists() or not data_path.is_dir():
            self._show_error("数据目录不存在")
            return False
        if self._same_dir_check.isChecked():
            inter_path = data_path
        else:
            inter_text = self._intermediate_edit.text().strip()
            if not inter_text:
                self._show_error("请选择中间文件目录")
                return False
            inter_path = Path(inter_text)
            if not inter_path.exists() or not inter_path.is_dir():
                self._show_error("中间目录不存在")
                return False
        target = inter_path / f"{name}.paleo.json"
        if target.exists():
            self._show_error("工程文件已存在")
            return False
        return True

    # -- navigation -------------------------------------------------------
    def _on_next_clicked(self) -> None:
        if not self._validate_step1():
            return
        self._clear_error()
        self._stack.setCurrentIndex(1)
        self._update_buttons()
        self._start_analysis()

    def _on_back_clicked(self) -> None:
        if getattr(self._job, "is_running", False):
            try:
                self._job.shutdown(wait_ms=0)
            except Exception:
                pass
        self._stack.setCurrentIndex(0)
        self._reset_step2()
        self._update_buttons()
        self._clear_error()

    def _update_buttons(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 0:
            self._back_btn.setEnabled(False)
            self._next_btn.setEnabled(True)
            self._next_btn.setVisible(True)
            self._finish_btn.setEnabled(False)
        else:
            # step 1
            self._back_btn.setEnabled(True)
            self._next_btn.setEnabled(False)
            self._next_btn.setVisible(False)
            # finish enabled only on success
            if self._analysis_state == "success":
                self._finish_btn.setEnabled(True)
            else:
                self._finish_btn.setEnabled(False)

    def _reset_step2(self) -> None:
        self._analysis_state = "idle"
        self._progress.hide()
        self._status_label.hide()
        self._status_label.setText("")
        self._summary_label.hide()
        self._summary_label.setText("")
        self._inventory_table.clearContents()
        self._inventory_table.setRowCount(0)
        self._inventory_table.hide()
        self._issues_browser.clear()
        self._issues_browser.hide()
        self._step2_error.hide()
        self._step2_error.setText("")
        if self._well_map_panel is not None:
            self._well_map_panel.hide()
        # keep _result_document None after reset
        self._result_document = None
        self._report = None

    # -- analysis ---------------------------------------------------------
    def _start_analysis(self) -> None:
        self._analysis_state = "running"
        self._result_document = None
        self._report = None
        self._progress.setRange(0, 0)
        self._progress.show()
        self._status_label.setText("正在分析数据文件夹…")
        self._status_label.show()
        self._summary_label.hide()
        self._inventory_table.hide()
        self._issues_browser.hide()
        self._step2_error.hide()
        if self._well_map_panel is not None:
            self._well_map_panel.hide()
        self._update_buttons()
        # ensure previous job not running
        if getattr(self._job, "is_running", False):
            try:
                self._job.shutdown(wait_ms=0)
            except Exception:
                pass
        data_dir = self.data_dir
        name = self.project_name
        # data_dir validated non-None
        assert data_dir is not None
        worker = _AnalyzeWorker(data_dir, name, self._engine)
        self._job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_analysis_finished),
                (worker.failed, self._on_analysis_failed),
            ),
        )

    def _on_analysis_finished(self, result) -> None:
        self._analysis_state = "success"
        self._result_document = result.document
        self._report = result.report
        self._progress.hide()
        self._status_label.hide()
        report = result.report if isinstance(result.report, dict) else {}
        imported = report.get("imported_count", getattr(result, "imported", 0))
        wells_total = report.get("wells_total", 0)
        wells_with = report.get("wells_with_coords", 0)
        surveys = report.get("surveys", 0)
        entities = report.get("entities", 0)
        self._summary_label.setText(
            f"导入 {imported} 项 · 井 {wells_total} 口（{wells_with} 有坐标） · 地震 {surveys} 个 · 地质实体 {entities} 个"
        )
        self._summary_label.show()
        by_type = report.get("by_type", {}) or {}
        self._inventory_table.setRowCount(len(by_type))
        for row, (k, v) in enumerate(by_type.items()):
            self._inventory_table.setItem(row, 0, QTableWidgetItem(str(k)))
            self._inventory_table.setItem(row, 1, QTableWidgetItem(str(v)))
        self._inventory_table.show()
        issues = list(report.get("issues", []) or [])
        warnings = list(report.get("warnings", []) or [])
        combined = issues + warnings
        if combined:
            text = "\n".join(str(x) for x in combined[:20])
            self._issues_browser.setText(text)
            self._issues_browser.show()
        else:
            self._issues_browser.hide()
        # WellMapPanel
        if self._well_map_panel is None:
            self._well_map_panel = WellMapPanel(self._page1)
            self._step2_layout.addWidget(self._well_map_panel, 1)
        self._well_map_panel.set_collapsed(False)
        try:
            self._well_map_panel.refresh_domain(result.document)
        except Exception:
            pass
        self._well_map_panel.show()
        self._update_buttons()

    def _on_analysis_failed(self, msg: str) -> None:
        self._analysis_state = "failed"
        self._progress.hide()
        self._status_label.hide()
        self._step2_error.setText(f"分析失败: {msg}")
        self._step2_error.show()
        self._finish_btn.setEnabled(False)
        self._back_btn.setEnabled(True)

    # -- dialog close -----------------------------------------------------
    def reject(self) -> None:
        if getattr(self._job, "is_running", False):
            try:
                self._job.shutdown(wait_ms=0)
            except Exception:
                pass
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if getattr(self._job, "is_running", False):
            try:
                self._job.shutdown(wait_ms=0)
            except Exception:
                pass
        super().closeEvent(event)
