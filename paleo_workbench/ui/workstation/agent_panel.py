from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
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
}

_RISK_LABELS = {"read": "只读", "compute": "计算", "write": "写入"}


def _plan_risks(plan: AgentPlan) -> frozenset:
    risks: set = set(_ACTION_RISKS.get(plan.action_id, {"read"}))
    if plan.followup_action is not None:
        risks |= set(_ACTION_RISKS.get(plan.followup_action[0], {"read"}))
    return frozenset(risks)


def _risk_label(plan: AgentPlan) -> str:
    order = ("write", "compute", "read")
    risks = _plan_risks(plan)
    top = next((r for r in order if r in risks), "read")
    return _RISK_LABELS.get(top, top)


class _AgentBridge(QObject):
    completed = Signal(object)


class AgentWorkspace(QFrame):
    """A Qt-native surface over the typed geological action harness."""

    open_well_requested = Signal(str)
    show_wells_requested = Signal()
    focus_joint_requested = Signal()
    undo_requested = Signal(object)

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationAgentWorkspace")
        self._project = project
        self._project_path: str | None = None
        self._current_task_id: str | None = None
        self._active_well_id: str = ""
        self._gui_history: list[dict] = []
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

        consent = QLabel("当前工程、活动文档、选择与参数会作为本次受控动作的上下文。", self)
        consent.setObjectName("WorkstationAgentConsent")
        consent.setWordWrap(True)
        outer.addWidget(consent)

        self.history = QTextBrowser(self)
        self.history.setObjectName("WorkstationAgentHistory")
        self.history.setOpenExternalLinks(False)
        outer.addWidget(self.history, 1)

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

        return str(style.palette().get("TEXT_SECONDARY", "#53616c"))

    @staticmethod
    def _success_html_color() -> str:
        from paleo_workbench.ui import style

        return str(style.palette().get("SUCCESS", "#15803d"))

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
        self._run_plan(plan, receipt_id)

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

    def _run_plan(self, plan: AgentPlan, receipt_id: str) -> None:
        from paleo_workbench.harness import ActionContext, ActionRisk, HarnessExecutor
        from paleo_workbench.runtime.task_scheduler import TaskSpec, get_scheduler

        # 最小权限：只授予计划动作实际需要的 risk（#1186）。当前动作表
        # 全部是读/计算；出现写动作时必须在 _ACTION_RISKS 显式登记才会
        # 携带 WRITE，UI 上同步显示 risk 标签。
        requested = _plan_risks(plan)
        permissions = frozenset(
            risk
            for label, risk in (
                ("read", ActionRisk.READ),
                ("compute", ActionRisk.COMPUTE),
                ("write", ActionRisk.WRITE),
            )
            if label in requested
        )
        context = ActionContext(
            workspace_id=str(getattr(getattr(self._project, "meta", None), "name", "") or ""),
            project_path=self._project_path,
            project=self._project,
            active_well_id=self._well_from_parameters(plan.parameters),
            permissions=permissions,
        )
        executor = HarnessExecutor()

        def run(_task_context):
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

    def _on_completed(self, payload) -> None:
        self._current_task_id = None
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
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
        gui_note = (
            f"GUI 同步：{plan.gui_action}" if plan.gui_action else "无 GUI 变更"
        )
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
