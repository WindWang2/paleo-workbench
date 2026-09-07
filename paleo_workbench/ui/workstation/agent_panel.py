from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

_ENV_ALLOW_WRITE = "PALEO_AGENT_ALLOW_WRITE"


def _env_allows_write_actions() -> bool:
    """``PALEO_AGENT_ALLOW_WRITE=1`` opts the agent panel into WRITE actions.

    Explicit opt-in only (P1, #1186 follow-up): the panel's default grant
    stays READ+COMPUTE, so WRITE-risk actions (map export / factor map /
    derived seismic stores) are unreachable unless the operator raised the
    grant through the environment or the constructor.
    """
    return str(os.environ.get(_ENV_ALLOW_WRITE, "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


@dataclass(frozen=True)
class AgentPlan:
    action_id: str
    parameters: dict
    gui_action: str
    summary: str
    followup_action: tuple[str, dict] | None = None
    kind: str = "interactive.query"


# 每个动作的最小权限需求（与 harness ActionSpec 的 risk 对齐；B12/#1186：
# 面板不再无条件携带 WRITE——权限面=计划动作面，不超配）。
_ACTION_RISKS: dict[str, frozenset] = {
    "well.list": frozenset({"read"}),
    "well.open": frozenset({"read", "compute"}),
    "well.create_display": frozenset({"read", "compute"}),
    "workflow.status": frozenset({"read"}),
    "workspace.describe_context": frozenset({"read"}),
    # Harness 2.0: workflow/recipe surface (risk mirrors the specs).
    "workflow.run": frozenset({"compute"}),
    "workflow.resume": frozenset({"compute"}),
    "workflow.cancel": frozenset({"compute"}),
    "workflow.describe": frozenset({"read"}),
    "workflow.describe_reproduction": frozenset({"read"}),
    "workflow.validate": frozenset({"read"}),
    "recipe.save": frozenset({"write"}),
    "recipe.load": frozenset({"read"}),
    "recipe.clone": frozenset({"compute"}),
}

_RISK_LABELS = {"read": "只读", "compute": "计算", "write": "写入"}


def _plan_risks(plan: AgentPlan) -> frozenset:
    """The registry is the risk authority; the static table is only the
    fallback for actions whose spec cannot be looked up."""

    def _risk_of(action_id: str) -> set:
        try:
            from paleo_workbench.harness import get_action_registry

            return {get_action_registry().get(action_id).risk.value}
        except Exception:
            return set(_ACTION_RISKS.get(action_id, {"read"}))

    risks: set = set(_risk_of(plan.action_id))
    if plan.followup_action is not None:
        risks |= _risk_of(plan.followup_action[0])
    return frozenset(risks)


def _risk_label(plan: AgentPlan) -> str:
    order = ("write", "compute", "read")
    risks = _plan_risks(plan)
    top = next((r for r in order if r in risks), "read")
    return _RISK_LABELS.get(top, top)


class _TaskCancelAdapter:
    """Adapts the scheduler TaskContext (``.cancelled`` Event) to the
    harness cancel protocol (``is_cancelled`` / ``raise_if_cancelled``)."""

    def __init__(self, task_context) -> None:
        self._task_context = task_context

    @property
    def is_cancelled(self) -> bool:
        return self._task_context.cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        from paleo_workbench.runtime.task_scheduler import TaskCancelled

        if self.is_cancelled:
            raise TaskCancelled("agent task cancelled")


class _AgentBridge(QObject):
    completed = Signal(object)
    # H11: workflow node progress streams from the engine (worker thread)
    # into the panel through this queued signal — widgets are never touched
    # off the GUI thread.
    progress_changed = Signal(float, str)


class AgentWorkspace(QFrame):
    """A Qt-native surface over the typed geological action harness."""

    open_well_requested = Signal(str)
    show_wells_requested = Signal()
    focus_joint_requested = Signal()
    undo_requested = Signal(object)
    #: V6 §4/§11：会话 WRITE 授权集合变化（UIContext write_granted 消费）。
    write_grant_changed = Signal()

    def __init__(self, project=None, parent=None, *, allow_write_actions: bool | None = None):
        super().__init__(parent)
        self.setObjectName("WorkstationAgentWorkspace")
        self._project = project
        self._last_gui_action: str | None = None
        self._active_well_id: str = ""
        self._gui_history: list[dict] = []
        self._current_task_id = None
        # #1186: WRITE confirmation hook. None → modal QMessageBox; tests
        # inject a stub returning bool. Per-plan, never latched.
        self.confirm_write: Callable[[list[str]], bool] | None = None
        # V6 §11：会话级 WRITE 授权（显式「记住」才生效；精确动作集合语义，
        # 绝不是空白支票）。
        self._session_write_grants: frozenset[str] = frozenset()
        # P1: WRITE elevation is an explicit opt-in — constructor flag wins
        # over the environment; default (None) reads PALEO_AGENT_ALLOW_WRITE.
        self._allow_write_actions = (
            _env_allows_write_actions()
            if allow_write_actions is None
            else bool(allow_write_actions)
        )
        self._bridge = _AgentBridge(self)
        self._bridge.completed.connect(self._on_completed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Agent", self)
        title.setObjectName("WorkstationPanelTitle")
        header.addWidget(title)
        self.context_label = QLabel("工程未绑定", self)
        self.context_label.setObjectName("WorkstationAgentContext")
        header.addWidget(self.context_label)
        header.addStretch(1)
        self.undo_button = QPushButton("撤销 GUI 变更", self)
        self.undo_button.setObjectName("WorkstationTertiaryButton")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo)
        header.addWidget(self.undo_button)
        outer.addLayout(header)

        consent = QLabel(self._consent_text(), self)
        consent.setObjectName("WorkstationAgentConsent")
        consent.setWordWrap(True)
        outer.addWidget(consent)
        self.consent_label = consent

        self.history = QTextBrowser(self)
        self.history.setObjectName("WorkstationAgentHistory")
        self.history.setOpenExternalLinks(False)
        outer.addWidget(self.history, 1)

        self.progress_label = QLabel("", self)
        self.progress_label.setObjectName("WorkstationAgentProgress")
        self.progress_label.setVisible(False)
        outer.addWidget(self.progress_label)
        self._bridge.progress_changed.connect(self._on_progress_changed)

        command_row = QHBoxLayout()
        self.command_input = QLineEdit(self)
        self.command_input.setObjectName("WorkstationAgentInput")
        self.command_input.setPlaceholderText("输入指令，例如：打开井 A12")
        self.command_input.returnPressed.connect(self.submit_current)
        command_row.addWidget(self.command_input, 1)
        self.stop_button = QPushButton("停止", self)
        self.stop_button.setObjectName("WorkstationTertiaryButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.cancel_current)
        command_row.addWidget(self.stop_button)
        self.run_button = QPushButton("执行", self)
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.submit_current)
        command_row.addWidget(self.run_button)
        outer.addLayout(command_row)

        self.set_project(project)

    def set_project(self, project, project_path: str | None = None) -> None:
        self._project = project
        self._project_path = str(project_path) if project_path else None
        self._refresh_context_label()
        if project is not None and not self.history.toPlainText():
            self.history.setHtml(
                "<b>已绑定工作站上下文</b><br>"
                "动作会通过 HarnessExecutor 完成参数校验、权限检查和结果验证。"
            )

    def set_active_well(self, well_id: str) -> None:
        """宿主把当前选择井推给 Agent（真实上下文，不再写死井名）。"""
        well_id = str(well_id or "").strip()
        if well_id == self._active_well_id:
            return
        self._active_well_id = well_id
        self._refresh_context_label()

    def _refresh_context_label(self) -> None:
        meta = getattr(self._project, "meta", None)
        name = str(getattr(meta, "name", "") or "未绑定工程")
        parts = [f"工程 {name}"]
        horizon = str(
            getattr(getattr(self._project, "stratigraphy", None), "target_horizon", "")
            or ""
        ).strip()
        parts.append(f"目标层位 {horizon}" if horizon else "目标层位未设")
        if self._active_well_id:
            parts.append(f"井 {self._active_well_id}")
        self.context_label.setText("上下文: " + " · ".join(parts))

    @staticmethod
    def _muted_html_color() -> str:
        from paleo_workbench.ui import style

        return str(style.palette()["TEXT_SECONDARY"])

    @staticmethod
    def _success_html_color() -> str:
        from paleo_workbench.ui import style

        return str(style.palette()["SUCCESS"])

    @staticmethod
    def _warn_html_color() -> str:
        from paleo_workbench.ui import style

        return str(style.palette()["WARNING"])

    def submit(self, text: str) -> None:
        command = str(text or "").strip()
        if not command or self._project is None or self._current_task_id is not None:
            return
        plan = self._plan(command)
        if not str(plan.parameters.get("well") or "").strip() and self._active_well_id:
            plan.parameters["well"] = self._active_well_id
        receipt_id = uuid.uuid4().hex[:8]
        risks = "、".join(
            _RISK_LABELS.get(r, r) for r in sorted(_plan_risks(plan))
        )
        self.history.append(
            f"<hr><b>用户</b> · {command}<br>"
            f"<b>执行计划</b> · {plan.summary}<br>"
            f"<span style='color:{self._muted_html_color()}'>动作 {plan.action_id} "
            f"[{risks}] · 回执 {receipt_id}</span>"
        )
        write_actions = self._write_actions_in_plan(plan)
        if write_actions and not self._confirm_write_actions(write_actions):
            self.history.append(
                "<b>已取消</b> · 写动作需逐次确认，未获授权本次不执行。"
            )
            return
        self._run_plan(plan, receipt_id, write_allowed=bool(write_actions))

    @staticmethod
    def _write_actions_in_plan(plan: AgentPlan) -> list[str]:
        """Action ids in the plan whose spec risk is WRITE (#1186).

        Unknown actions fail closed (treated as WRITE): the registry is
        the authority on risk, and an unassessable action must not run on
        default permissions.
        """
        from paleo_workbench.harness import ActionRisk, get_action_registry

        ids = [plan.action_id]
        if plan.followup_action is not None:
            ids.append(plan.followup_action[0])
        write: list[str] = []
        try:
            registry = get_action_registry()
        except Exception:
            return ids
        for action_id in ids:
            try:
                risk = registry.get(action_id).risk
            except Exception:
                risk = ActionRisk.WRITE
            if risk == ActionRisk.WRITE:
                write.append(action_id)
        return write

    def _write_granted_for(self, action_ids: list[str]) -> bool:
        """会话授权是否已覆盖**精确**动作集合（子集语义，非空白支票）。"""
        return frozenset(action_ids) <= self._session_write_grants

    @property
    def write_granted_actions(self) -> frozenset:
        """会话内已授权的 WRITE 动作集合（精确集合；UIContext 只读）。"""
        return self._session_write_grants

    def _grant_write_session(self, action_ids: list[str]) -> None:
        self._session_write_grants |= frozenset(action_ids)
        self.write_grant_changed.emit()

    def _build_write_grant_dialog(self, action_ids: list[str]):
        """专业 WRITE 授权对话框（V6 §11）：动作卡 + 范围 + 会话粒度。

        安全默认：拒绝按钮为 default；「记住授权」是显式勾选，不预选。
        动作描述来自 ActionSpec（注册表权威）；未知动作诚实标注。
        """
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFrame,
            QLabel,
            QScrollArea,
            QVBoxLayout,
        )

        dialog = QDialog(self)
        dialog.setObjectName("WriteGrantDialog")
        dialog.setWindowTitle("写入授权")
        dialog.setModal(True)
        dialog.granted = False
        dialog.remember = False

        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "以下 Agent 动作将执行写入（WRITE）——修改工程数据或写盘。"
            "逐项核对后授权；拒绝不会执行任何动作。", dialog)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        cards = QFrame(dialog)
        cards.setObjectName("WriteGrantActionList")
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(6, 6, 6, 6)
        specs = {}
        try:
            from paleo_workbench.harness.registry import get_action_registry

            registry = get_action_registry()
            for action_id in action_ids:
                try:
                    specs[action_id] = registry.get(action_id)
                except Exception:
                    specs[action_id] = None
        except Exception:
            pass
        for action_id in action_ids:
            spec = specs.get(action_id)
            title = QLabel(f"▣ {action_id}", cards)
            title.setObjectName("WriteGrantActionTitle")
            cards_layout.addWidget(title)
            if spec is not None:
                detail = QLabel(str(getattr(spec, "description", "") or ""), cards)
                detail.setWordWrap(True)
                cards_layout.addWidget(detail)
            else:
                unknown = QLabel("（注册表中无此动作描述——按 WRITE 对待）", cards)
                unknown.setWordWrap(True)
                cards_layout.addWidget(unknown)
        scroll = QScrollArea(dialog)
        scroll.setWidget(cards)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        remember_box = QCheckBox("本会话内记住该授权（同一动作集合不再询问）", dialog)
        layout.addWidget(remember_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.No).setText("拒绝")
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("授权")
        buttons.button(QDialogButtonBox.StandardButton.No).setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.No).setFocus()
        buttons.accepted.connect(
            lambda: (_setattr_grant(dialog, True, remember_box.isChecked())))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog

    def _confirm_write_actions(self, action_ids: list[str]) -> bool:
        # V6：会话授权命中（精确集合）→ 不再打扰；否则专业授权对话框。
        if self._write_granted_for(action_ids):
            return True
        if callable(self.confirm_write):
            try:
                granted = bool(self.confirm_write(action_ids))
            except Exception:
                return False
            if granted:
                # confirm_write 钩子授权视为一次性行为（不记住会话）。
                return True
            return False
        dialog = self._build_write_grant_dialog(action_ids)
        dialog.exec()
        if getattr(dialog, "granted", False):
            if getattr(dialog, "remember", False):
                self._grant_write_session(action_ids)
            return True
        return False

    def submit_current(self) -> None:
        text = self.command_input.text().strip()
        if not text:
            return
        self.command_input.clear()
        self.submit(text)

    def cancel_current(self) -> None:
        if self._current_task_id is None:
            return
        from paleo_workbench.runtime.task_scheduler import get_scheduler

        if get_scheduler().cancel(self._current_task_id):
            self.history.append("<b>取消请求已发送</b> · 将在安全点停止。")

    def _consent_text(self) -> str:
        """Consent line; visibly flags an elevated WRITE grant (P1)."""
        base = "当前工程、活动文档、选择与参数会作为本次受控动作的上下文。"
        if self._allow_write_actions:
            return (
                base
                + "已显式开启 WRITE 权限（PALEO_AGENT_ALLOW_WRITE）——"
                "写入/导出类动作将可执行。"
            )
        return base

    def _run_plan(self, plan: AgentPlan, receipt_id: str, *, write_allowed: bool = False) -> None:
        from paleo_workbench.harness import ActionContext, ActionRisk, HarnessExecutor
        from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler

        write_ok = write_allowed or self._allow_write_actions
        requested = _plan_risks(plan)
        allowed_risks = {ActionRisk.READ, ActionRisk.COMPUTE}
        if write_ok:
            allowed_risks.add(ActionRisk.WRITE)
        permissions = frozenset(
            risk
            for label, risk in (
                ("read", ActionRisk.READ),
                ("compute", ActionRisk.COMPUTE),
                ("write", ActionRisk.WRITE),
            )
            if label in requested and risk in allowed_risks
        )
        try:
            from paleo_workbench.catalog.runtime import get_catalog

            catalog = get_catalog()
        except Exception:
            catalog = None
        context = ActionContext(
            workspace_id=str(getattr(getattr(self._project, "meta", None), "name", "") or ""),
            project_path=self._project_path,
            project=self._project,
            catalog=catalog,
            active_well_id=self._well_from_parameters(plan.parameters),
            permissions=permissions,
            progress=self._on_workflow_progress,
        )
        executor = HarnessExecutor()

        def run(task_context):
            # Scheduler cancellation reaches workflow actions through the
            # session cancel token (cooperative, same protocol as engines).
            context.cancel = _TaskCancelAdapter(task_context)
            results = [executor.execute(plan.action_id, plan.parameters, context)]
            if results[0].ok and plan.followup_action is not None:
                action_id, parameters = plan.followup_action
                results.append(executor.execute(action_id, parameters, context))
            return {
                "plan": plan,
                "receipt_id": receipt_id,
                "results": results,
            }

        handle = get_scheduler().submit(
            TaskSpec(
                callable=run,
                kind=plan.kind,
                title=f"Agent · {plan.summary}",
                priority=25,
                on_done=self._bridge.completed.emit,
                on_fail=lambda exc: self._bridge.completed.emit(
                    {
                        "plan": plan,
                        "receipt_id": receipt_id,
                        "failed_exception": str(exc),
                        "results": [],
                    }
                ),
                on_cancel=lambda: self._bridge.completed.emit(
                    {"plan": plan, "receipt_id": receipt_id, "cancelled": True, "results": []}
                ),
            )
        )
        self._current_task_id = handle.task_id
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def _on_workflow_progress(self, ratio: float, message: str) -> None:
        """Worker-thread safe: forward through the queued bridge signal."""
        self._bridge.progress_changed.emit(float(ratio), str(message))

    def _on_progress_changed(self, ratio: float, message: str) -> None:
        percent = int(round(max(0.0, min(1.0, ratio)) * 100))
        self.progress_label.setText(f"工作流进度 {percent}% · {message}")
        self.progress_label.setVisible(True)

    def _workflow_checklist_html(self, outputs: dict) -> str | None:
        """Render the WorkflowPlanView checklist from a run summary."""
        try:
            from paleo_workbench.workflow.dag.plan_view import WorkflowPlanView

            view = WorkflowPlanView.from_summary(dict(outputs or {}))
            rows = view.checklist()
            if not rows:
                return None
            muted = self._muted_html_color()
            lines = []
            for row in rows:
                detail = str(row.get("detail") or "")
                suffix = f" <span style='color:{muted}'>{detail}</span>" if detail else ""
                cache_note = "（缓存复用）" if row.get("from_cache") else ""
                lines.append(
                    f"{row['symbol']} {row['label']}{cache_note}{suffix}"
                )
            header = (
                f"工作流 {view.name} · {view.state_label()} · "
                f"{int(round(view.progress * 100))}%"
            )
            self.progress_label.setVisible(False)
            return f"<b>{header}</b><br>" + "<br>".join(lines)
        except Exception:
            return None

    def _on_completed(self, payload) -> None:
        self._current_task_id = None
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_label.setVisible(False)
        if payload.get("cancelled"):
            self.history.append("<b>已取消</b> · 未应用 GUI 变更。")
            return
        if payload.get("failed_exception"):
            self.history.append(
                f"<b>执行失败</b> · {payload['failed_exception']}<br>"
                "可继续使用手动工作流，当前 GUI 状态未被改变。"
            )
            return
        plan: AgentPlan = payload["plan"]
        results = list(payload.get("results") or [])
        failed = [result for result in results if not result.ok]
        if failed:
            self.history.append(
                f"<b>执行失败</b> · {failed[0].error or '动作未完成'}<br>"
                "可继续使用手动工作流，当前 GUI 状态未被改变。"
            )
            return

        summary = self._result_summary(plan, results)
        workflow_outputs = next(
            (
                r.outputs
                for r in results
                if r.action_id in ("workflow.run", "workflow.resume") and r.outputs.get("run_id")
            ),
            None,
        )
        if workflow_outputs is not None:
            checklist = self._workflow_checklist_html(workflow_outputs)
            if checklist:
                self.history.append(checklist)
                return
        gui_note = (
            f"GUI 同步：{plan.gui_action}" if plan.gui_action else "无 GUI 变更"
        )
        # V6（F-P0-1）：DEGRADED 不是「校验通过」——warnings 必须可见。
        degraded = [r for r in results if r.degraded]
        if degraded:
            warning_lines = "<br>".join(
                f"· {w}" for r in degraded for w in (r.warnings or ())
            ) or "· （执行器未提供降级原因）"
            self.history.append(
                f"<b>降级完成</b> · {summary}<br>"
                f"<span style='color:{self._warn_html_color()}'>"
                f"结果带警告，请核对后采信：<br>{warning_lines}</span><br>"
                f"{gui_note}。"
            )
            self._apply_gui_action(plan)
            return
        self.history.append(
            f"<b>执行完成</b> · {summary}<br>"
            f"<span style='color:{self._success_html_color()}'>校验通过 · {gui_note}。</span>"
        )
        self._apply_gui_action(plan)

    def _apply_gui_action(self, plan: AgentPlan) -> None:
        if not plan.gui_action:
            return
        if plan.gui_action == "show_wells":
            self.show_wells_requested.emit()
        elif plan.gui_action == "open_well":
            self.open_well_requested.emit(self._well_from_parameters(plan.parameters))
        elif plan.gui_action == "focus_joint":
            self.focus_joint_requested.emit()
        self._gui_history.append(
            {
                "gui_action": plan.gui_action,
                "parameters": dict(plan.parameters),
                "summary": plan.summary,
            }
        )
        self.undo_button.setEnabled(True)

    def _undo(self) -> None:
        if not self._gui_history:
            return
        entry = self._gui_history.pop()
        self.undo_requested.emit(entry)
        self.history.append(
            f"<b>撤销请求</b> · {entry['summary']}（结果见状态栏/工作区）"
        )
        self.undo_button.setEnabled(bool(self._gui_history))

    def _well_from_parameters(self, parameters: dict) -> str:
        well = str(parameters.get("well") or "").strip()
        if well:
            return well
        return self._active_well_id

    @staticmethod
    def _plan(command: str) -> AgentPlan:
        normalized = command.strip()
        well_match = re.search(r"\b([A-Za-z]{1,4}\d+(?:[-_]\d+)*)\b", normalized)
        well = well_match.group(1).upper() if well_match else ""
        # 工作流入口（H11）：`运行工作流 <recipe 路径>` 计划为 workflow.run，
        # 完成后经 WorkflowPlanView 渲染节点清单。
        recipe_match = re.search(r"运行工作流\s+(\S+\.paleo-workflow\.json)", normalized)
        if recipe_match:
            return AgentPlan(
                "workflow.run",
                {"recipe_path": recipe_match.group(1)},
                None,
                f"运行工作流 {recipe_match.group(1)}",
                kind="background.compute",
            )
        # 规划期不虚构井名：缺井时留给执行期解析活动井，解析失败则动作
        # 校验诚实失败（参数校验拒绝空井），绝不静默换成示例井。
        if "显示" in normalized and "井" in normalized and any(word in normalized for word in ("所有", "全部", "平面")):
            return AgentPlan(
                "well.list",
                {"include_reference": False},
                "show_wells",
                "读取工区井清单，并将地图缩放到全部井位",
            )
        if "GR" in normalized.upper() and any(word in normalized for word in ("放", "轨", "道", "曲线")):
            return AgentPlan(
                "well.open",
                {"well": well},
                "open_well",
                f"打开井 {well}，校验 GR 曲线并生成第一轨显示文档",
                followup_action=("well.create_display", {"well": well, "curves": ["GR"]}),
                kind="background.io",
            )
        if "打开" in normalized and "井" in normalized:
            return AgentPlan(
                "well.open",
                {"well": well},
                "open_well",
                f"解析并打开井 {well}，随后联动地图、测井和检查器",
                kind="background.io",
            )
        if "井震" in normalized or "联合剖面" in normalized:
            return AgentPlan(
                "workflow.status",
                {},
                "focus_joint",
                "读取工作流状态并聚焦井震联合解释工作区",
            )
        return AgentPlan(
            "workspace.describe_context",
            {},
            "focus_joint",
            "读取当前工程、文档、选择和视图上下文",
        )

    @staticmethod
    def _result_summary(plan: AgentPlan, results: list) -> str:
        outputs = results[-1].outputs if results else {}
        if plan.action_id == "well.list":
            return f"已读取 {outputs.get('count', 0)} 口井并显示平面位置"
        if plan.action_id == "well.open":
            primary = results[0].outputs if results else {}
            if plan.followup_action:
                return f"{primary.get('name', '井')} 已打开，GR 显示文档已生成"
            return f"{primary.get('name', '井')} 已打开，共 {primary.get('curve_count', 0)} 条曲线"
        if plan.action_id == "workflow.status":
            return "井震联合工作流已聚焦，当前选择保持联动"
        return "上下文已刷新，工作区保持可操作"


def _setattr_grant(dialog, granted: bool, remember: bool) -> None:
    """授权按钮回调：记录结果并关闭（模块级小助手，避免闭包晚绑定）。"""
    dialog.granted = granted
    dialog.remember = remember
    dialog.accept()
