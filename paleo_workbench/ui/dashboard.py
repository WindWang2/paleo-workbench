from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class WorkflowDashboard(QWidget):
    def __init__(self, state: dict[str, object], parent=None):
        super().__init__(parent)
        self.project_name_label = QLabel(str(state.get("project_name", "")))
        self.target_label = QLabel(f"目标层位: {state.get('active_target_horizon') or '未设置'}")
        self.status_label = QLabel(f"流程状态: {state.get('workflow_status', 'draft')}")
        self.summary = QLabel(
            f"资源 {sum(state.get('resource_counts', {}).values())} · "
            f"单因素图 {state.get('factor_map_count', 0)} · "
            f"预测 {state.get('prediction_count', 0)} · "
            f"QC问题 {state.get('qc_issue_count', 0)} · "
            f"导出 {state.get('export_count', 0)}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title_card = QFrame()
        title_card.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #d8dee6; border-radius: 12px; }")
        card_layout = QVBoxLayout(title_card)
        for widget in [self.project_name_label, self.target_label, self.status_label, self.summary]:
            card_layout.addWidget(widget)
        layout.addWidget(title_card)
        layout.addStretch()