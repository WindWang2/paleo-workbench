"""规划导入对话框（V13 W-G）——``resources/ingest_plan.py`` 的正式 UI。

两阶段零副作用契约在 UI 侧的落点：

1. **构建**（worker 线程）：``build_ingest_plan`` 扫描/分类/家族分组/
   身份匹配/角色推断/查重 → 可编辑计划表；
2. **确认**：用户逐项或批量修改 decision / role / 实体 / primary；
3. **执行**（worker 线程，可取消）：``execute_ingest_plan`` 分块登记 +
   实体绑定 + primary 选择，幂等可重跑。

与 harness ingest 动作共用同一 service 函数——UI 导入和 Agent 导入不是
两套实现（goal W-G/W-S）。模型层遵守 V11 model/view 契约：ObjectTableModel
虚拟行，零 item-per-cell。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.resources.ingest_plan import (
    IngestExecuteReport,
    IngestPlan,
    PlannedItem,
    build_ingest_plan,
    execute_ingest_plan,
)
from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.modelview.object_table import ColumnSpec, ObjectTableModel

_DECISION_LABELS = [
    ("pending", "待定"),
    ("accept", "接受"),
    ("skip", "跳过"),
    ("as_new_version", "作为新版本"),
]


def _decision_display(item: PlannedItem) -> str:
    return dict(_DECISION_LABELS).get(item.decision, item.decision)


def _status_display(item: PlannedItem) -> str:
    if item.duplicate_of_version:
        return "⚠ 重复"
    if item.identity.strategy == "ambiguous":
        return "? 待确认"
    if item.decision == "skip":
        return "跳过"
    return "✓"


class _PlanWorker(QObject):
    """计划构建/执行 worker（一次一事；经 QThread moveToThread）。"""

    plan_ready = Signal(object)          # IngestPlan
    execute_done = Signal(object)        # IngestExecuteReport
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, service: Any, project: Any, root: Path) -> None:
        super().__init__()
        self._service = service
        self._project = project
        self._root = root
        self._plan: IngestPlan | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # slots（QThread 事件循环驱动；无装饰器——connect 按名字解析）
    def build(self) -> None:  # pragma: no cover - thin wrapper
        try:
            plan = build_ingest_plan(
                self._root, self._project, service=self._service,
                progress=lambda done, total: self.progress.emit(done, total),
                cancel=lambda: self._cancelled,
            )
            self._plan = plan
            self.plan_ready.emit(plan)
        except Exception as exc:  # noqa: BLE001 - worker 边界如实上报
            self.failed.emit(f"构建导入计划失败: {exc}")

    def execute(self) -> None:  # pragma: no cover - thin wrapper
        if self._plan is None:
            self.failed.emit("内部错误：计划未构建")
            return
        try:
            report = execute_ingest_plan(
                self._plan, self._service, self._project,
                bind=True,
                progress=lambda done, total: self.progress.emit(done, total),
                cancel=lambda: self._cancelled,
            )
            self.execute_done.emit(report)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"执行导入失败: {exc}")


class IngestPlanDialog(QDialog):
    """呈现 + 编辑 + 执行一个 IngestPlan（宿主 DataPage 提供 service/project）。"""

    #: 执行成功（无论新增多少）后发射，宿主刷新资产表/导航树。
    ingest_finished = Signal()

    def __init__(
        self,
        parent=None,
        *,
        service: Any,
        project: Any,
        root: Path,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("规划导入 (Ingest Plan)")
        self.resize(1000, 640)
        self._service = service
        self._project = project
        self._root = Path(root)
        self._plan: IngestPlan | None = None
        self._worker: _PlanWorker | None = None
        self._thread: QThread | None = None
        self._report: IngestExecuteReport | None = None
        self._suppress_detail_sync = False

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        # -- 头部：根路径 + 摘要 ------------------------------------------
        self.header_label = QLabel(f"扫描目标：{self._root}")
        self.header_label.setWordWrap(True)
        style.bind(
            self.header_label,
            lambda: (
                f"font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
                f" color: {style.palette()['TEXT_PRIMARY']};"
            ),
        )
        layout.addWidget(self.header_label)
        self.summary_label = QLabel("正在构建导入计划…")
        style.bind(
            self.summary_label,
            lambda: f"color: {style.palette()['TEXT_SECONDARY']};",
        )
        layout.addWidget(self.summary_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # -- 计划表（虚拟行模型）------------------------------------------
        self._model = ObjectTableModel(
            columns=self._columns(),
            key_of=lambda item: str(item.path),
            parent=self,
        )
        self.table = QTableView(self)
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.selectionModel().selectionChanged.connect(
            self._on_selection_changed)
        layout.addWidget(self.table, 1)

        # -- 选中项编辑面板 -------------------------------------------------
        self.detail = _ItemDetailPanel(self)
        self.detail.item_edited.connect(self._on_item_edited)
        layout.addWidget(self.detail)

        # -- 按钮行 ----------------------------------------------------------
        buttons = QHBoxLayout()
        self.accept_all_btn = QPushButton("全部接受")
        self.accept_all_btn.setObjectName("SecondaryButton")
        style.track_control_height(self.accept_all_btn)
        self.accept_all_btn.clicked.connect(self._accept_all)
        buttons.addWidget(self.accept_all_btn)

        self.skip_unresolved_btn = QPushButton("待确认项设为跳过")
        self.skip_unresolved_btn.setObjectName("SecondaryButton")
        style.track_control_height(self.skip_unresolved_btn)
        self.skip_unresolved_btn.clicked.connect(self._skip_unresolved)
        buttons.addWidget(self.skip_unresolved_btn)

        buttons.addStretch(1)

        self.cancel_run_btn = QPushButton("取消执行")
        self.cancel_run_btn.setObjectName("SecondaryButton")
        style.track_control_height(self.cancel_run_btn)
        self.cancel_run_btn.clicked.connect(self._cancel_run)
        self.cancel_run_btn.setVisible(False)
        buttons.addWidget(self.cancel_run_btn)

        self.execute_btn = QPushButton("执行导入")
        self.execute_btn.setObjectName("PrimaryButton")
        self.execute_btn.setMinimumHeight(tokens.CONTROL_HEIGHT_LG)
        self.execute_btn.setEnabled(False)
        self.execute_btn.clicked.connect(self._execute)
        buttons.addWidget(self.execute_btn)

        self.close_btn = QPushButton("关闭")
        self.close_btn.setObjectName("SecondaryButton")
        style.track_control_height(self.close_btn)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self._start_build()

    # ------------------------------------------------------------------
    def _columns(self) -> list[ColumnSpec]:
        return [
            ColumnSpec("status", "状态", _status_display),
            ColumnSpec(
                "file", "文件",
                lambda item: item.path.name,
                tooltip=lambda item: str(item.path),
            ),
            ColumnSpec("type", "类型", lambda item: item.type),
            ColumnSpec(
                "entity", "实体（推断）",
                lambda item: _entity_display(item),
            ),
            ColumnSpec(
                "confidence", "置信度",
                lambda item: item.identity.confidence
                if item.identity.strategy else "",
            ),
            ColumnSpec("role", "角色", lambda item: item.role),
            ColumnSpec("primary", "主用",
                       lambda item: "✓" if item.primary else ""),
            ColumnSpec("decision", "决策", _decision_display),
            ColumnSpec(
                "note", "备注",
                lambda item: item.note
                or ("重复: " + (item.duplicate_of_asset or "")[:12]
                    if item.duplicate_of_version else ""),
            ),
        ]

    # -- worker -----------------------------------------------------------
    def _start_build(self) -> None:
        self._teardown_worker()
        self._thread = QThread(self)
        self._worker = _PlanWorker(self._service, self._project, self._root)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.build)
        self._worker.plan_ready.connect(self._on_plan_ready)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.progress.connect(self._on_progress)
        self._thread.start()

    def _execute(self) -> None:
        if self._plan is None:
            return
        if self._plan.unresolved and not self._unresolved_skipped():
            from PySide6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                self, "存在待确认项",
                "仍有身份待确认的文件（将按当前决策执行，未确认项默认跳过）。"
                "继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        # 构建完成后残留的空闲 build worker 在此协作回收（cancel+quit）。
        if self._thread is not None:
            self._teardown_worker()
        self._thread = QThread(self)
        self._worker = _PlanWorker(self._service, self._project, self._root)
        self._worker._plan = self._plan  # noqa: SLF001 - 同包协作
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.execute)
        self._worker.execute_done.connect(self._on_execute_done)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.progress.connect(self._on_progress)
        self.execute_btn.setEnabled(False)
        self.accept_all_btn.setEnabled(False)
        self.skip_unresolved_btn.setEnabled(False)
        self.detail.setEnabled(False)  # 执行期间计划只读（防中途改决策）
        self.cancel_run_btn.setVisible(True)
        self.cancel_run_btn.setEnabled(True)
        self._thread.start()

    def _cancel_run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_run_btn.setEnabled(False)

    def _teardown_worker(self) -> None:
        """协作停止 worker（先 cancel 再等线程退出；超时不销毁线程——
        销毁运行中的 QThread 是 UB，由 finished→deleteLater 兜底回收）。"""
        if self._thread is None:
            return
        thread, worker = self._thread, self._worker
        self._thread, self._worker = None, None
        if worker is not None:
            worker.cancel()
        thread.quit()
        finished_now = thread.wait(5000)
        if finished_now:
            # 事件循环已停：deleteLater 不会再被线程处理，直接安全销毁。
            if worker is not None:
                worker.deleteLater()
            thread.deleteLater()
        else:
            # 线程仍在跑：延迟到真正退出后回收（连接仍有意义——quit 已
            # 请求，当前槽返回后事件循环退出并发射 finished）。
            if worker is not None:
                thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._cancel_run()
        self._teardown_worker()
        super().closeEvent(event)

    # -- 回调 ---------------------------------------------------------------
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def _on_plan_ready(self, plan: IngestPlan) -> None:
        self._plan = plan
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._model.set_rows(list(plan.items))
        self._refresh_summary()
        self.execute_btn.setEnabled(bool(plan.items))
        self.detail.set_item(None, project=self._project)

    def _on_execute_done(self, report: IngestExecuteReport) -> None:
        self._report = report
        self._teardown_worker()
        self._set_running(False)
        created = len(report.imported_version_ids)
        skipped = len(report.skipped)
        bound = report.bound_links
        entities = report.created_entities
        text = (f"导入完成：登记 {created}，跳过 {skipped}，"
                f"绑定 {bound}，新建实体 {entities}，问题 {len(report.issues)}")
        if report.cancelled:
            text += "（已取消——已完成分块保持一致，可重新执行）"
        self.summary_label.setText(text)
        self.ingest_finished.emit()

    def _on_worker_failed(self, message: str) -> None:
        self._teardown_worker()
        self._set_running(False)
        self.summary_label.setText(message)

    def _set_running(self, running: bool) -> None:
        self.cancel_run_btn.setVisible(running)
        self.execute_btn.setEnabled(not running and self._plan is not None)
        self.accept_all_btn.setEnabled(not running)
        self.skip_unresolved_btn.setEnabled(not running)
        self.detail.setEnabled(
            not running and self.detail._item is not None)

    # -- 计划编辑 -------------------------------------------------------------
    def _on_selection_changed(self, *_args) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            self.detail.set_item(None, project=self._project)
            return
        row = indexes[0].row()
        rows = list(self._model._rows)  # noqa: SLF001 - 只读
        if 0 <= row < len(rows):
            self.detail.set_item(rows[row], project=self._project)

    def _on_item_edited(self) -> None:
        self._model.set_rows(list(self._plan.items) if self._plan else [])
        self._refresh_summary()

    def _accept_all(self) -> None:
        if self._plan is None:
            return
        for item in self._plan.items:
            if not item.duplicate_of_version:
                item.decision = "accept"
        self._on_item_edited()

    def _skip_unresolved(self) -> None:
        if self._plan is None:
            return
        for item in self._plan.unresolved:
            item.decision = "skip"
        self._on_item_edited()

    def _unresolved_skipped(self) -> bool:
        return all(item.decision == "skip" for item in self._plan.unresolved)

    def _refresh_summary(self) -> None:
        if self._plan is None:
            return
        s = self._plan.summary()
        accepted = len(self._plan.accepted())
        self.summary_label.setText(
            f"共 {s['total']} 个数据项：接受 {accepted}，"
            f"重复 {s['duplicates']}，待确认 {s['unresolved']}，"
            f"文件族 {s['bundles']}——选中行可在下方修改决策/角色/实体/主用")


def _entity_display(item: PlannedItem) -> str:
    proposal = item.identity
    if not proposal.strategy:
        return "—"
    label = proposal.entity_name or (proposal.entity_id or "")
    prefix = "新建 " if proposal.new_entity else ""
    return f"{prefix}{label} ({proposal.confidence})" if label else "—"


class _ItemDetailPanel(QFrame):
    """选中计划项的编辑面板（决策/角色/实体/主用）。"""

    item_edited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("IngestItemDetail")
        self._item: PlannedItem | None = None
        self._project: Any = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1,
                                  tokens.SPACE_2, tokens.SPACE_1)

        self.titleLabel = QLabel("未选中")
        style.bind(
            self.titleLabel,
            lambda: (
                f"font-weight: 600; color: {style.palette()['TEXT_PRIMARY']};"
            ),
        )
        layout.addWidget(self.titleLabel)

        layout.addWidget(QLabel("决策"))
        self.decision_combo = QComboBox()
        for value, label in _DECISION_LABELS:
            self.decision_combo.addItem(label, value)
        self.decision_combo.currentIndexChanged.connect(self._apply)
        layout.addWidget(self.decision_combo)

        layout.addWidget(QLabel("角色"))
        self.role_combo = QComboBox()
        self.role_combo.currentIndexChanged.connect(self._apply)
        layout.addWidget(self.role_combo)

        layout.addWidget(QLabel("实体"))
        self.entity_combo = QComboBox()
        self.entity_combo.currentIndexChanged.connect(self._apply)
        layout.addWidget(self.entity_combo)

        self.primary_check = QCheckBox("主用")
        self.primary_check.toggled.connect(self._apply)
        layout.addWidget(self.primary_check)
        layout.addStretch(1)

    def set_item(self, item: PlannedItem | None, *, project: Any) -> None:
        self._item = item
        self._project = project
        self._suppress_detail_sync = True
        try:
            self.titleLabel.setText(
                item.path.name if item is not None else "未选中")
            self.setEnabled(item is not None)
            if item is None:
                return
            self.decision_combo.setCurrentIndex(
                max(0, [v for v, _ in _DECISION_LABELS].index(item.decision)
                    if item.decision in [v for v, _ in _DECISION_LABELS] else 0))
            self._reload_roles(item)
            self._reload_entities(item)
            self.primary_check.setChecked(bool(item.primary))
        finally:
            self._suppress_detail_sync = False

    def _reload_roles(self, item: PlannedItem) -> None:
        from paleo_workbench.project.roles import roles_for_entity_type

        entity_type = _entity_type_for(item)
        roles = list(roles_for_entity_type(entity_type))
        if item.role and item.role not in roles:
            roles.append(item.role)
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        for role in roles:
            self.role_combo.addItem(role, role)
        index = self.role_combo.findData(item.role)
        self.role_combo.setCurrentIndex(max(0, index))
        self.role_combo.blockSignals(False)

    def _reload_entities(self, item: PlannedItem) -> None:
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        proposal = item.identity
        self.entity_combo.addItem("（不绑定）", ("", None))
        if proposal.entity_type == "well":
            for well in getattr(self._project, "wells", None) or []:
                label = f"{well.name}" + (
                    f" / {well.uwi}" if getattr(well, "uwi", "") else "")
                self.entity_combo.addItem(
                    f"井 {label}", ("well", well.id))
            for cand in proposal.candidates:
                cid = str(cand.get("id") or cand.get("entity_id") or "")
                cname = str(cand.get("name") or "")
                if cid:
                    self.entity_combo.addItem(
                        f"候选 {cname or cid}", ("well", cid))
        elif proposal.entity_type == "seismic_survey":
            for survey in getattr(self._project, "seismic_surveys", None) or []:
                self.entity_combo.addItem(
                    f"调查 {survey.name}", ("seismic_survey", survey.id))
        if proposal.entity_name or proposal.new_entity:
            self.entity_combo.addItem(
                f"新建 {proposal.entity_name or '…'}",
                (proposal.entity_type or "well", "__new__"))
        current = ("", None)
        if proposal.entity_id and not proposal.new_entity:
            current = (proposal.entity_type, proposal.entity_id)
        index = self.entity_combo.findData(current)
        if index >= 0:
            self.entity_combo.setCurrentIndex(index)
        else:
            self.entity_combo.setCurrentIndex(0)
        self.entity_combo.blockSignals(False)

    def _apply(self) -> None:
        if self._item is None or self._suppress_detail_sync:
            return
        item = self._item
        item.decision = self.decision_combo.currentData() or item.decision
        role = self.role_combo.currentData()
        if role:
            item.role = str(role)
        entity_kind, entity_value = self.entity_combo.currentData() or (
            "", None)
        if entity_value == "__new__":
            item.identity.new_entity = True
            item.identity.strategy = item.identity.strategy or "manual"
            item.identity.confidence = "manual"
        elif entity_value:
            item.identity.entity_type = entity_kind
            item.identity.entity_id = entity_value
            item.identity.new_entity = False
            item.identity.strategy = "manual"
            item.identity.confidence = "manual"
        item.primary = bool(self.primary_check.isChecked())
        self.item_edited.emit()


def _entity_type_for(item: PlannedItem) -> str:
    from paleo_workbench.resources.ingest_plan import (
        SURVEY_BOUND_TYPES,
        WELL_BOUND_TYPES,
    )

    if item.type in WELL_BOUND_TYPES or item.identity.entity_type == "well":
        return "well"
    if item.type in SURVEY_BOUND_TYPES or (
            item.identity.entity_type == "seismic_survey"):
        return "seismic_survey"
    return "geological_entity"


def choose_ingest_root(parent: QWidget) -> Path | None:
    """目录/文件选择（返回 None = 用户取消）。"""
    from PySide6.QtWidgets import QFileDialog

    path = QFileDialog.getExistingDirectory(
        parent, "选择导入根目录（规划导入）")
    return Path(path) if path else None
