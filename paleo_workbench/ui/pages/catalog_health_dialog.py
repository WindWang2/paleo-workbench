"""CatalogHealthDialog — Data Manager's 数据健康检查 entry.

Shows the structured audit report (:func:`paleo_workbench.catalog.audit.
audit_catalog`): entity statistics, issue counts per severity, and the issue
list. 快速检查 (structural + payload existence) runs on a worker thread; 深度检查
additionally re-hashes every managed payload. The catalog is NEVER mutated by
an audit — findings are reported for the user to act on.

V11 Model/View 迁移（goal §8 / 01-ui-audit D2）：问题表改
``QTableView + ObjectTableModel``（此前 setRowCount+setItem 逐格重建），
页内手写表格 QSS 移除（统一走全局 QSS + :func:`bind_table_defaults`）；
级别着色经 ``ColumnSpec.foreground_role`` 返回 token 名（高→ERROR_RED、
中→WARNING），无问题时表上覆盖统一空态。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens
from paleo_workbench.ui.components.states import PwbEmptyState, PwbLoadingState
from paleo_workbench.ui.modelview import (
    ColumnSpec,
    ObjectTableModel,
    bind_table_defaults,
)
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

_SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
_SEVERITY_TOKENS = {"high": "ERROR_RED", "medium": "WARNING"}


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


class _IssueCellProxy:
    """Test-facing cell handle: ``item(row, col).text()`` without QTableWidgetItem."""

    def __init__(self, model, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column

    def text(self) -> str:
        value = self._model.data(self._model.index(self._row, self._column))
        return "" if value is None else str(value)


class _IssueTableView(QTableView):
    """QTableView + QTableWidget 兼容访问器（差分测试沿用 widget 式断言）。"""

    def rowCount(self) -> int:  # noqa: N802
        model = self.model()
        return 0 if model is None else model.rowCount()

    def item(self, row: int, column: int):
        model = self.model()
        if model is None:
            return None
        if row < 0 or column < 0 or row >= model.rowCount() or column >= model.columnCount():
            return None
        return _IssueCellProxy(model, row, column)


class CatalogHealthDialog(QDialog):
    """数据健康检查: audit statistics + issues for the active catalog."""

    # D9: emitted when the user asks for the 缺失源/重链接 flow; the host
    # opens RelinkSourcesDialog (keeps this dialog free of relink logic).
    relink_requested = Signal()

    def __init__(self, parent=None, *, service_provider):
        super().__init__(parent)
        self.setWindowTitle("数据健康检查 (Catalog Health)")
        self.resize(760, 520)
        self._service_provider = service_provider
        self._job = OwnedWorkerJob(self)
        self._cancel_event: threading.Event | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        self.summary_label = QLabel("尚未运行检查")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("WorkstationPanelTitle")
        layout.addWidget(self.summary_label)

        self._model = ObjectTableModel(
            columns=[
                ColumnSpec(
                    "severity",
                    "级别",
                    lambda pair: (
                        f"{_SEVERITY_LABELS.get(pair[1].severity, pair[1].severity)}"
                        f" ({pair[1].severity})"
                    ),
                    foreground_role=lambda pair: _SEVERITY_TOKENS.get(pair[1].severity),
                ),
                ColumnSpec("kind", "类型", lambda pair: pair[1].kind),
                ColumnSpec("ref", "对象", lambda pair: pair[1].ref_id),
                ColumnSpec("detail", "详情", lambda pair: pair[1].detail),
            ],
            key_of=lambda pair: pair[0],
            parent=self,
        )
        self.issues_table = _IssueTableView()
        self.issues_table.setModel(self._model)
        bind_table_defaults(self.issues_table)
        self.issues_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.issues_table, 1)

        # 无问题时的统一空态（覆盖在表上，词汇与任务中心一致）。
        self._empty_state = PwbEmptyState("未发现目录健康问题", "可定期运行深度检查复核数据校验和。", parent=self)
        self._empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_state.setParent(self.issues_table)
        self._empty_state.hide()
        self._model.modelReset.connect(self._update_empty_state)
        self._model.rowsInserted.connect(self._update_empty_state)
        self._model.rowsRemoved.connect(self._update_empty_state)

        # 共享加载态（indeterminate）：快速/深度检查期间统一进行中面。
        self.progress = PwbLoadingState("正在检查…", parent=self)
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
        # D9: 缺失源扫描 + fail-closed relink，紧邻健康检查入口保证可发现性。
        self.relink_btn = QPushButton("缺失源与重链接…")
        self.relink_btn.setObjectName("SecondaryButton")
        self.relink_btn.clicked.connect(self.relink_requested)
        buttons.addWidget(self.relink_btn)
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
        # Cooperative cancellation token: the dialog hands a set() callable
        # to the job (fired by shutdown()/cancel()) and the is_set probe to
        # the audit itself, which checks it between payload hashes (#1056 —
        # closing the dialog must abort the worker, not adopt it forever).
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_running(True)
        self.progress.set_text(
            "正在深度检查全部数据校验和..." if deep else "正在检查目录结构与数据完整性..."
        )
        self.summary_label.setText(
            "正在深度检查全部数据校验和..." if deep else "正在检查目录结构与数据完整性..."
        )
        worker = _AuditWorker(lambda: service.audit(deep=deep, cancel=cancel_event.is_set))
        self._job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_audit_finished),
                (worker.failed, self._on_audit_failed),
            ),
            cancel=cancel_event.set,
        )

    def _cancel_running_audit(self) -> None:
        """Stop an in-flight audit cooperatively (deep hashing checks the
        event between payloads), then tear the job down.

        Without this, closing the dialog adopted the hashing worker into
        ``detached_job_keeper`` where it kept running to completion —
        blocking project switching for the whole audit (#1056).
        """
        self._cancel_event = None
        job = self._job
        if job is not None and job.is_running:
            # Bounded join on the GUI thread: the cooperative cancel makes
            # the worker return between payload checks; if a single huge
            # payload overshoots the wait, the job detaches to the keeper
            # with the cancel token already set, so it still stops promptly.
            job.shutdown(wait_ms=3_000)

    def closeEvent(self, event) -> None:
        self._cancel_running_audit()
        super().closeEvent(event)

    def reject(self) -> None:
        self._cancel_running_audit()
        super().reject()

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
            f"问题 {len(report.issues)} 项: 高 {stats.get('issues_high', 0)} / "
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
        # 行对象包一层 (稳定键, issue)：AuditIssue 无业务 id，键由
        # 确定性序号+内容构成，重复审计同一目录时走 set_rows 差分路径。
        self._model.set_rows(
            [(f"{i}:{issue.kind}:{issue.ref_id}", issue) for i, issue in enumerate(issues)]
        )

    # -- empty state overlay ------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._empty_state.isVisible():
            self._empty_state.setGeometry(self.issues_table.viewport().rect())

    def _update_empty_state(self, *_args) -> None:
        if self._model.rowCount() == 0:
            self._empty_state.setGeometry(self.issues_table.viewport().rect())
            self._empty_state.show()
            self._empty_state.raise_()
        else:
            self._empty_state.hide()
