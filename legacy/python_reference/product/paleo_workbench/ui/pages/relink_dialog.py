"""RelinkSourcesDialog — 缺失源检查与重链接 (D9 closed loop).

Lists every live version whose payload no longer resolves
(:meth:`DataCatalogService.find_missing_sources`, stat-only scan on a
worker) and relinks EXTERNAL RAW entries:

* per-row 重新链接… — pick the relocated file; identity must be provable
  (sha256, else the recorded size+mtime fingerprint) or the relink is
  refused (fail-closed, never a silent basename rebinding);
* 目录重定向… — the "whole folder moved" case: every relinkable entry
  whose basename exists under the chosen directory is relinked through
  the same fail-closed identity proof; failures stay missing with a reason.

Scan AND relink batches run on an OwnedWorkerJob (cooperative cancel), so
hashing a relocated multi-GB file never freezes the GUI. The dialog NEVER
touches managed payloads (missing managed = corruption → re-import) and
never mutates the catalog beyond the explicit relink writes.

V11 Model/View 迁移（goal §8 / 01-ui-audit D2）：结果表改
``QTableView + ObjectTableModel``（此前 insertRow-per-row 逐格建 item）；
扫描/重链接的进行中状态改共享 :class:`PwbLoadingState`，无缺失源时表上
覆盖统一空态（词汇与任务中心一致）。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from paleo_workbench.catalog.sources import CatalogRelinkIdentityError
from paleo_workbench.ui import tokens
from paleo_workbench.ui.components.states import PwbEmptyState, PwbLoadingState
from paleo_workbench.ui.modelview import (
    ColumnSpec,
    ObjectTableModel,
    bind_table_defaults,
)
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

_STAGE_LABELS = {
    "raw": "RAW",
    "derived": "DERIVED",
    "intermediate": "INTERMEDIATE",
    "output": "OUTPUT",
}


def _entry_status(entry) -> str:
    if entry.relinkable:
        return "可重链接"
    if entry.managed:
        return "需重新导入"
    return "不支持重链接"


class _TaskWorker(QObject):
    """Generic task runner: emits ``finished``/``failed`` exactly once."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        try:
            result = self._task()
        except Exception as exc:  # pragma: no cover - defensive boundary
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
            return
        self.finished.emit(result)


class _RelinkCellProxy:
    """Test-facing cell handle: ``item(row, col).text()`` without QTableWidgetItem."""

    def __init__(self, model, row: int, column: int) -> None:
        self._model = model
        self._row = row
        self._column = column

    def text(self) -> str:
        value = self._model.data(self._model.index(self._row, self._column))
        return "" if value is None else str(value)


class _RelinkTableView(QTableView):
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
        return _RelinkCellProxy(model, row, column)


class RelinkSourcesDialog(QDialog):
    """缺失源列表 + 单个 / 目录批量重链接 (fail-closed)."""

    sources_relinked = Signal(int)

    def __init__(self, parent=None, *, service_provider):
        super().__init__(parent)
        self.setWindowTitle("缺失源与重新链接 (Relink)")
        self.resize(880, 540)
        self._service_provider = service_provider
        # One job per role (the DataPage discipline): a job is never torn
        # down and immediately reused mid-session — shutdown() deletes its
        # thread, and racing that teardown aborts native code. Shutdown
        # happens ONLY on dialog close.
        self._scan_job = OwnedWorkerJob(self)
        self._relink_job = OwnedWorkerJob(self)
        self._cancel_event: threading.Event | None = None
        self._entries = []
        # Explicit busy flags instead of ``job.is_running``: the thread can
        # still be draining when a queued result slot fires, which would
        # leave the buttons stuck disabled.
        self._busy = False

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        self.summary_label = QLabel("正在扫描缺失源…")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("WorkstationPanelTitle")
        layout.addWidget(self.summary_label)

        self._model = ObjectTableModel(
            columns=[
                ColumnSpec("data", "数据", lambda e: str(getattr(e, "asset_name", "") or "")),
                ColumnSpec(
                    "stage",
                    "阶段",
                    lambda e: _STAGE_LABELS.get(
                        getattr(getattr(e, "stage", None), "value", ""),
                        str(getattr(getattr(e, "stage", None), "value", "") or ""),
                    ),
                ),
                ColumnSpec("kind", "类别", lambda e: "托管" if e.managed else "外部"),
                ColumnSpec("path", "记录路径", lambda e: str(getattr(e, "recorded_path", "") or "")),
                ColumnSpec("status", "状态", _entry_status),
            ],
            key_of=lambda e: str(getattr(e, "version_id", "") or id(e)),
            parent=self,
        )
        self.table = _RelinkTableView()
        self.table.setModel(self._model)
        bind_table_defaults(self.table)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        # 空态覆盖：扫描完成且无缺失源时表上明示（不再只靠 summary 行）。
        self._empty_state = PwbEmptyState("未发现缺失源", "全部版本的数据源均可正常解析。", parent=self)
        self._empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._empty_state.setParent(self.table)
        self._empty_state.hide()
        self._model.modelReset.connect(self._update_empty_state)
        self._model.rowsInserted.connect(self._update_empty_state)
        self._model.rowsRemoved.connect(self._update_empty_state)

        # 共享加载态：扫描 / 重链接批处理期间统一进行中面（indeterminate）。
        self.progress = PwbLoadingState("正在扫描缺失源…", parent=self)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.detail_label = QLabel(
            "重新链接仅在能证明身份时进行（sha256 或 记录的 size+mtime 指纹）；"
            "无法证明将拒绝，绝不按文件名静默错绑。托管载荷缺失请重新导入。"
        )
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("WorkstationPanelFootnote")
        layout.addWidget(self.detail_label)

        buttons = QHBoxLayout()
        self.relink_btn = QPushButton("重新链接…")
        self.relink_btn.setObjectName("PrimaryButton")
        self.relink_btn.setEnabled(False)
        self.relink_btn.clicked.connect(self._relink_selected)
        buttons.addWidget(self.relink_btn)
        self.folder_btn = QPushButton("目录重定向…")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self._relink_folder)
        buttons.addWidget(self.folder_btn)
        self.rescan_btn = QPushButton("重新扫描")
        self.rescan_btn.clicked.connect(self.start_scan)
        buttons.addWidget(self.rescan_btn)
        buttons.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.setObjectName("SecondaryButton")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.table.selectionModel().selectionChanged.connect(self._sync_buttons)
        self.start_scan()

    # -- worker plumbing --------------------------------------------------------

    def _start_task(self, job, task, on_finished, on_failed, *, busy_text="", cancel_event=None) -> None:
        if self._busy or job.is_running:
            return  # one task at a time; buttons already reflect this
        if cancel_event is None:
            cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._busy = True
        self._sync_buttons()
        worker = _TaskWorker(task)
        self.progress.set_text(busy_text or "正在处理…")
        self.progress.setVisible(True)
        job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, on_finished),
                (worker.failed, on_failed),
            ),
            cancel=cancel_event.set,
        )

    def _cancel_running(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._cancel_event = None
        # Close-time teardown only (see job discipline above). The workers
        # poll the cancel token between items, so they stop promptly; the
        # bounded join covers the item in flight.
        self._scan_job.shutdown(wait_ms=3_000)
        self._relink_job.shutdown(wait_ms=3_000)
        self._busy = False

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_running()
        super().closeEvent(event)

    def reject(self) -> None:
        self._cancel_running()
        super().reject()

    # -- scan -----------------------------------------------------------------

    def start_scan(self) -> None:
        service = self._service_provider()
        if service is None:
            self.summary_label.setText("数据目录不可用")
            return
        self.summary_label.setText("正在扫描缺失源…")
        cancel_event = threading.Event()
        self._start_task(
            self._scan_job,
            lambda: service.find_missing_sources(cancel=cancel_event.is_set),
            self._on_scan_finished,
            self._on_scan_failed,
            busy_text="正在扫描缺失源…",
            cancel_event=cancel_event,
        )

    def _on_scan_finished(self, report) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self._entries = list(report.entries)
        relinkable = report.relinkable
        if not self._entries:
            summary = f"共扫描 {report.scanned} 个版本，未发现缺失源"
        else:
            summary = (
                f"共扫描 {report.scanned} 个版本，缺失 {len(self._entries)} 个，"
                f"其中可重链接（外部 RAW）{len(relinkable)} 个"
            )
        self.summary_label.setText(summary)
        self._model.set_rows(self._entries)
        self._sync_buttons()

    def _on_scan_failed(self, message: str) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self._sync_buttons()
        self.summary_label.setText(f"扫描失败：{message}")

    # -- relink -----------------------------------------------------------------

    def _selected_entry(self):
        rows = self.table.selectionModel().selectedRows()
        if len(rows) != 1:
            return None
        row = rows[0].row()
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def _sync_buttons(self, *_args) -> None:
        idle = not self._busy
        entry = self._selected_entry()
        self.relink_btn.setEnabled(idle and entry is not None and entry.relinkable)
        has_relinkable = any(e.relinkable for e in self._entries)
        self.folder_btn.setEnabled(idle and has_relinkable)
        self.rescan_btn.setEnabled(idle)

    def _relink_selected(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        new_path, _selected = QFileDialog.getOpenFileName(
            self, "选择新位置的文件", entry.recorded_path or ""
        )
        if not new_path:
            return
        self._apply_relinks([(entry, new_path)])

    def _relink_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择迁移后的目录")
        if not directory:
            return
        from pathlib import Path

        root = Path(directory)
        pending = []
        for entry in self._entries:
            if not entry.relinkable:
                continue
            basename = Path(entry.recorded_path).name
            candidate = root / basename
            if candidate.is_file():
                pending.append((entry, candidate))
        if not pending:
            QMessageBox.information(
                self,
                "目录重定向",
                "所选目录中没有与缺失源同名的文件；未做任何改动。",
            )
            return
        self._apply_relinks(pending)

    def _apply_relinks(self, pending) -> None:
        """Relink (entry, candidate) pairs off-thread; proof failures surface
        per row and the entry stays missing (fail-closed)."""
        service = self._service_provider()
        if service is None:
            return
        pairs = [
            (entry.version_id, str(candidate), entry.asset_name)
            for entry, candidate in pending
        ]

        def task():
            ok = 0
            cancelled = False
            reasons: list[str] = []
            for version_id, candidate, label in pairs:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                try:
                    service.relink_external_source(version_id, candidate)
                    ok += 1
                except CatalogRelinkIdentityError as exc:
                    reasons.append(f"{label}: {exc}")
                except Exception as exc:  # noqa: BLE001 — surfaced per row
                    reasons.append(f"{label}: {exc.__class__.__name__}: {exc}")
            return {"ok": ok, "reasons": reasons, "cancelled": cancelled}

        cancel_event = threading.Event()
        self._start_task(
            self._relink_job,
            task,
            self._on_relink_finished,
            self._on_relink_failed,
            busy_text="正在验证并重链接…",
            cancel_event=cancel_event,
        )

    def _on_relink_finished(self, result) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self._sync_buttons()
        ok = int(result.get("ok", 0))
        reasons = list(result.get("reasons") or [])
        message = f"成功重链接 {ok} 个"
        if reasons:
            message += f"，拒绝 {len(reasons)} 个（身份无法证明或发生错误）\n" + "\n".join(
                reasons[:8]
            )
        if len(reasons) > 8:
            message += f"\n… 共 {len(reasons)} 条"
        if ok:
            self.sources_relinked.emit(ok)
        QMessageBox.information(self, "重链接结果", message)
        self.start_scan()

    def _on_relink_failed(self, message: str) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self._sync_buttons()
        QMessageBox.warning(self, "重链接失败", message)
        self.start_scan()

    # -- empty state overlay ------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._empty_state.isVisible():
            self._empty_state.setGeometry(self.table.viewport().rect())

    def _update_empty_state(self, *_args) -> None:
        # 扫描进行中不算空态（加载面已占位）。
        if not self._busy and self._model.rowCount() == 0:
            self._empty_state.setGeometry(self.table.viewport().rect())
            self._empty_state.show()
            self._empty_state.raise_()
        else:
            self._empty_state.hide()
