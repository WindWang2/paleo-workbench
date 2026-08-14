"""CatalogHealthDialog — Data Manager's 数据健康检查 entry.

Shows the structured audit report (:func:`paleo_workbench.catalog.audit.
audit_catalog`): entity statistics, issue counts per severity, and the issue
list. 快速检查 (structural + payload existence) runs on a worker thread; 深度检查
additionally re-hashes every managed payload. The catalog is NEVER mutated by
an audit — findings are reported for the user to act on.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

_SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}


class _AuditWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            report = self._task()
        except Exception as exc:  # pragma: no cover - defensive boundary
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        self.finished.emit(report)


class CatalogHealthDialog(QDialog):
    """数据健康检查: audit statistics + issues for the active catalog."""

    def __init__(self, parent=None, *, service_provider):
        super().__init__(parent)
        self.setWindowTitle("数据健康检查 (Catalog Health)")
        self.resize(760, 520)
        self._service_provider = service_provider
        self._job = OwnedWorkerJob(self)

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        self.summary_label = QLabel("尚未运行检查")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {tokens.TEXT_PRIMARY};"
        )
        layout.addWidget(self.summary_label)

        self.issues_table = QTableWidget(0, 4)
        self.issues_table.setHorizontalHeaderLabels(["级别", "类型", "对象", "详情"])
        self.issues_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.issues_table.verticalHeader().setVisible(False)
        self.issues_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.issues_table.setAlternatingRowColors(True)
        layout.addWidget(self.issues_table, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("快速检查")
        self.refresh_btn.setObjectName("PrimaryButton")
        self.refresh_btn.clicked.connect(lambda: self.run_audit(deep=False))
        buttons.addWidget(self.refresh_btn)
        self.deep_btn = QPushButton("深度检查 (含 SHA-256 重哈希)")
        self.deep_btn.setObjectName("SecondaryButton")
        self.deep_btn.clicked.connect(lambda: self.run_audit(deep=True))
        buttons.addWidget(self.deep_btn)
        buttons.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    # -- audit execution -------------------------------------------------------

    def run_audit(self, *, deep: bool = False) -> None:
        service = self._service_provider()
        if service is None:
            self.summary_label.setText("未连接数据目录（请先打开项目）")
            return
        if getattr(self._job, "is_running", False):
            return
        self._set_running(True)
        self.summary_label.setText(
            "正在深度检查全部数据校验和..." if deep else "正在检查目录结构与数据完整性..."
        )
        worker = _AuditWorker(lambda: service.audit(deep=deep))
        self._job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_audit_finished),
                (worker.failed, self._on_audit_failed),
            ),
        )

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        self.refresh_btn.setEnabled(not running)
        self.deep_btn.setEnabled(not running)

    def _on_audit_finished(self, report) -> None:
        self._set_running(False)
        self.update_report(report)

    def _on_audit_failed(self, message: str) -> None:
        self._set_running(False)
        self.summary_label.setText(f"检查失败: {message}")

    # -- report rendering ------------------------------------------------------

    def update_report(self, report) -> None:
        stats = report.statistics
        checked = report.checked
        summary = (
            f"资产 {checked.get('assets', 0)} · 版本 {checked.get('versions', 0)} · "
            f"运行 {checked.get('runs', 0)} · 标签 {checked.get('tags', 0)}　|　"
            f"问题: 高 {stats.get('issues_high', 0)} / "
            f"中 {stats.get('issues_medium', 0)} / "
            f"低 {stats.get('issues_low', 0)}"
        )
        ok = report.ok
        verdict = "✅ 目录结构健康（低级别问题仅供参考）" if ok else "⚠️ 发现需要处理的健康问题"
        self.summary_label.setText(f"{summary}\n{verdict}")

        issues = sorted(
            report.issues,
            key=lambda i: ("high", "medium", "low").index(i.severity),
        )
        self.issues_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            severity = QTableWidgetItem(
                f"{_SEVERITY_LABELS.get(issue.severity, issue.severity)} ({issue.severity})"
            )
            if issue.severity == "high":
                severity.setForeground(Qt.GlobalColor.red)
            elif issue.severity == "medium":
                severity.setForeground(Qt.GlobalColor.darkYellow)
            self.issues_table.setItem(row, 0, severity)
            self.issues_table.setItem(row, 1, QTableWidgetItem(issue.kind))
            self.issues_table.setItem(row, 2, QTableWidgetItem(issue.ref_id))
            self.issues_table.setItem(row, 3, QTableWidgetItem(issue.detail))
