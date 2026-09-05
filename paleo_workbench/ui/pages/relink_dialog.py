"""RelinkSourcesDialog — 缺失源检查与重链接 (D9 closed loop).

Lists every live version whose payload no longer resolves
(:meth:`DataCatalogService.find_missing_sources`, stat-only scan on a
worker) and relinks EXTERNAL RAW entries:

* per-row 重新链接… — pick the relocated file; identity must be provable
  (sha256, else the recorded size+mtime fingerprint) or the relink is
  refused (fail-closed, never a silent basename rebinding);
* 目录重定向… — the "whole folder moved" case: every relinkable entry
  whose basename exists under the chosen directory is relinked through the
  same fail-closed identity proof; failures stay missing with a reason.

Scan AND relink batches run on an OwnedWorkerJob (cooperative cancel), so
hashing a relocated multi-GB file never freezes the GUI. The dialog NEVER
touches managed payloads (missing managed = corruption → re-import) and
never mutates the catalog beyond the explicit relink writes.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.catalog.sources import CatalogRelinkIdentityError
from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

_STAGE_LABELS = {
    "raw": "RAW",
    "derived": "DERIVED",
    "intermediate": "INTERMEDIATE",
    "output": "OUTPUT",
}


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
        self.summary_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {tokens.TEXT_PRIMARY};"
        )
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["数据", "阶段", "类别", "记录路径", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.detail_label = QLabel(
            "重新链接仅在能证明身份时进行（sha256 或 记录的 size+mtime 指纹）；"
            "无法证明将拒绝，绝不按文件名静默错绑。托管载荷缺失请重新导入。"
        )
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
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

        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.start_scan()

    # -- worker plumbing --------------------------------------------------------

    def _start_task(self, job, task, on_finished, on_failed, *, cancel_event=None) -> None:
        if self._busy or job.is_running:
            return  # one task at a time; buttons already reflect this
        if cancel_event is None:
            cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._busy = True
        self._sync_buttons()
        worker = _TaskWorker(task)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
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
        self.table.setRowCount(0)
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            kind = "托管" if entry.managed else "外部"
            if entry.relinkable:
                status = "可重链接"
            elif entry.managed:
                status = "需重新导入"
            else:
                status = "不支持重链接"
            values = [
                entry.asset_name,
                _STAGE_LABELS.get(entry.stage.value, entry.stage.value),
                kind,
                entry.recorded_path,
                status,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
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

    def _sync_buttons(self) -> None:
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
