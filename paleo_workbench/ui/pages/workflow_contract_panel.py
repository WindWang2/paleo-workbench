"""Compact professional Chinese workflow contract panel (Stage 11)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens
from paleo_workbench.workflow.contracts.models import ExpertQuestionStatus, ReadinessStatus
from paleo_workbench.workflow.contracts.readiness import evaluate_readiness
from paleo_workbench.workflow.contracts.registry import get_default_registry


STATUS_ZH = {
    ReadinessStatus.READY: "可执行",
    ReadinessStatus.PARTIAL: "部分就绪",
    ReadinessStatus.BLOCKED: "阻塞",
    ReadinessStatus.UNKNOWN: "未知",
}

IMPL_ZH = {
    "PRODUCTION": "生产",
    "PARTIAL": "部分实现",
    "DEMO": "演示",
    "PLACEHOLDER": "占位",
}


class WorkflowContractPanel(QFrame):
    """Shows 功能/输入/操作/输出/上下游/QC/就绪/待专家确认 for one module."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkflowContractPanel")
        self._project = None
        self._contract_id = "factor_interpolation"
        self._dev_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_2)

        header = QHBoxLayout()
        self.title = QLabel("专业工作流合同")
        self.title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;"
        )
        header.addWidget(self.title, 1)
        self.dev_btn = QPushButton("开发/咨询详情")
        self.dev_btn.setObjectName("WorkflowContractDevToggle")
        self.dev_btn.setCheckable(True)
        self.dev_btn.toggled.connect(self._on_dev_toggled)
        header.addWidget(self.dev_btn)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(tokens.SPACE_1)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)

        self._lines: list[QLabel] = []
        self.refresh()

    def set_project(self, project) -> None:
        self._project = project
        self.refresh()

    def set_contract_id(self, contract_id: str) -> None:
        self._contract_id = contract_id
        self.refresh()

    def _on_dev_toggled(self, on: bool) -> None:
        self._dev_mode = on
        self.refresh()

    def _clear(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._lines.clear()

    def _add(self, text: str, *, primary: bool = False, warn: bool = False) -> None:
        lab = QLabel(text)
        lab.setWordWrap(True)
        color = tokens.WARNING if warn else (
            tokens.TEXT_PRIMARY if primary else tokens.TEXT_SECONDARY
        )
        weight = "600" if primary else "400"
        lab.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: {weight};")
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body_layout.addWidget(lab)
        self._lines.append(lab)

    def refresh(self) -> None:
        self._clear()
        reg = get_default_registry()
        c = reg.get_contract(self._contract_id)
        if c is None:
            self._add(f"未知模块：{self._contract_id}", warn=True)
            return

        self.title.setText(c.name_zh or c.name)
        self._add(f"功能：{c.description_zh or c.description}", primary=True)
        self._add(
            f"实现状态：{IMPL_ZH.get(c.implementation_status.value, c.implementation_status.value)}"
        )

        # Readiness
        if self._project is not None:
            report = evaluate_readiness(self._project, c.id, registry=reg)
            self._add(
                f"当前状态：{STATUS_ZH.get(report.status, report.status.value)}",
                primary=True,
                warn=report.status is ReadinessStatus.BLOCKED,
            )
            for r in report.reasons:
                self._add(f"· {r.message_zh}", warn=r.severity == "block")
        else:
            self._add("当前状态：未绑定工程")

        self._add("输入", primary=True)
        for inp in c.inputs:
            tag = "必需" if inp.required else "可选"
            self._add(f"· {inp.name}（{tag}）")

        self._add("主要操作", primary=True)
        for i, op in enumerate(c.operations, 1):
            self._add(f"{i}. {op.user_action or op.name}")
            if op.software_action:
                self._add(f"   软件：{op.software_action}")

        if c.parameters:
            self._add("参数", primary=True)
            for p in c.parameters:
                cat = p.category.value
                self._add(f"· {p.name} [{cat}]")

        self._add("输出", primary=True)
        for out in c.outputs:
            self._add(f"· {out.name}（{out.output_class}）")

        self._add("上游", primary=True)
        self._add("· " + ("、".join(c.upstream_contract_ids) or "无"))
        self._add("下游", primary=True)
        self._add("· " + ("、".join(c.downstream_contract_ids) or "无"))

        self._add("QC", primary=True)
        if not c.qc_rules:
            self._add("· （未声明）")
        for qc in c.qc_rules:
            self._add(f"· {qc.name} [{qc.severity.value}]")

        self._add("待专家确认", primary=True)
        open_q = [
            q for q in c.expert_questions if q.status is ExpertQuestionStatus.OPEN
        ]
        if not open_q:
            self._add("· 无开放问题")
        for q in open_q:
            self._add(f"· [{q.priority.value}] {q.question}", warn=True)

        if self._dev_mode:
            self._add("开发/咨询详情", primary=True)
            self._add(f"contract id: {c.id}")
            self._add(f"DataRun ops: {', '.join(c.datarun_operations) or '—'}")
            for e in c.source_evidence[:8]:
                self._add(f"evidence: {e.path}.{e.symbol}".rstrip("."))
            for q in c.expert_questions:
                self._add(f"Q {q.id}: certainty={q.certainty.value}")

        self.body_layout.addStretch()
