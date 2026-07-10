from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.mapping_helpers import active_map_document
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, field_value
from paleo_workbench.viz.models import VizPayload, VizRef


class VisualizationTracePanel(QFrame):
    """Right-hand traceability summary for the composite visualization."""

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationTracePanel")
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"QFrame#VisualizationTracePanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("视图追踪")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.task_value = self._add_value(layout, "预测任务", "未选择预测任务")
        self.map_value = self._add_value(layout, "古地理图", "未选择古地理图")
        self.source_value = self._add_value(layout, "来源", "—")
        self.label_value = self._add_value(layout, "标签", "—")
        self.kind_value = self._add_value(layout, "类型", "—")
        self.path_value = self._add_value(layout, "路径/消息", "—")

        layout.addStretch()
        self.refresh_btn = QPushButton("刷新视图")
        self.refresh_btn.setObjectName("SecondaryButton")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self.refresh_btn)
        self.export_btn = QPushButton("导出组合视图")
        self.export_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.export_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setWordWrap(True)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, prediction_tasks: list | tuple | None, map_documents: list | tuple | None) -> None:
        task = active_prediction_task(prediction_tasks)
        document = active_map_document(map_documents)
        self.task_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.map_value.setText(field_value(document, "name", "") or "未选择古地理图")

    def update_ref(self, ref: VizRef | None, payload: VizPayload | None) -> None:
        if ref is None:
            self.source_value.setText("—")
            self.label_value.setText("—")
            self.kind_value.setText("—")
            self.path_value.setText("—")
            return

        self.source_value.setText(ref.source or "—")
        self.label_value.setText(ref.label or (payload.label if payload else "") or "—")
        self.kind_value.setText(ref.kind or "—")

        path_or_message = ref.path or ""
        if payload is not None:
            if payload.message:
                path_or_message = payload.message if not path_or_message else f"{path_or_message}\n{payload.message}"
            elif payload.warning and not path_or_message:
                path_or_message = payload.warning
            elif not path_or_message and payload.label:
                path_or_message = payload.label
        self.path_value.setText(path_or_message or "—")
