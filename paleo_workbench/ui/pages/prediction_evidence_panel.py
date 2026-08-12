from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QListWidget, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import field_value


class PredictionEvidencePanel(QFrame):
    """Right-hand evidence and action summary for prediction output."""

    run_requested = Signal()
    demo_requested = Signal()
    send_requested = Signal()
    export_requested = Signal(str)  # PNG | SVG | PDF

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PredictionEvidencePanel")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("预测证据")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.mock_value = self._add_value(layout, "输出性质", "—")
        self.source_value = self._add_value(layout, "数据来源", "—")
        self.horizon_value = self._add_value(layout, "目标层位", "—")
        self.facies_count_value = self._add_value(layout, "相带段数", "—")

        evidence_label = QLabel("证据贡献")
        evidence_label.setObjectName("WorkFieldLabel")
        layout.addWidget(evidence_label)

        self.evidence_list = QListWidget()
        self.evidence_list.setObjectName("WorkListWidget")
        layout.addWidget(self.evidence_list, 1)

        export_label = QLabel("导出格式")
        export_label.setObjectName("WorkFieldLabel")
        layout.addWidget(export_label)
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItems(["PNG", "SVG", "PDF"])
        layout.addWidget(self.export_format_combo)

        self.export_btn = QPushButton("导出单井剖面")
        self.export_btn.setObjectName("SecondaryButton")
        self.export_btn.clicked.connect(
            lambda: self.export_requested.emit(self.export_format_combo.currentText())
        )
        layout.addWidget(self.export_btn)

        self.run_btn = QPushButton("运行测井预测")
        self.run_btn.setObjectName("SecondaryButton")
        self.run_btn.setToolTip(
            "通过 ModelRegistry 解析生产模型后运行科学预测；"
            "未配置生产模型时不会自动运行 mock"
        )
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)
        self.demo_btn = QPushButton("运行演示预测")
        self.demo_btn.setObjectName("SecondaryButton")
        self.demo_btn.setToolTip(
            "显式演示模式：运行 DemoModelProvider（合成数据，非科学预测）"
        )
        self.demo_btn.clicked.connect(self.demo_requested.emit)
        layout.addWidget(self.demo_btn)
        self.send_btn = QPushButton("发送制备")
        self.send_btn.setObjectName("PrimaryButton")
        self.send_btn.clicked.connect(self.send_requested.emit)
        layout.addWidget(self.send_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def set_actions_enabled(self, *, can_export: bool, can_send: bool) -> None:
        self.export_btn.setEnabled(can_export)
        self.send_btn.setEnabled(can_send)
        self.run_btn.setEnabled(True)
        self.demo_btn.setEnabled(True)

    def update_state(self, task, *, bound_las: bool = False) -> None:
        summary = field_value(task, "result_summary", {}) or {}
        meta = field_value(task, "model_metadata", {}) or {}
        if task is None:
            self.mock_value.setText("—")
            self.source_value.setText("—")
            self.horizon_value.setText("—")
            self.facies_count_value.setText("—")
            self.evidence_list.clear()
            self.set_actions_enabled(can_export=False, can_send=False)
            return

        # Honest output labeling (P2): random/mock output must never display
        # as 真实, and heuristic output is not a scientific prediction.
        if summary.get("is_mock"):
            nature = "Mock"
        elif not summary.get("final_scientific_prediction", False):
            nature = "启发式"
        else:
            nature = "科学预测"
        if summary.get("demo"):
            nature = f"Demo · {nature}"
        replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
        self.mock_value.setText(f"{nature} · {replaceable}")
        if summary.get("demo") or summary.get("source") == "synthetic/demo":
            self.source_value.setText("合成演示数据")
        elif bound_las:
            self.source_value.setText("绑定 LAS")
        else:
            self.source_value.setText("合成曲线")
        horizon = ""
        if isinstance(meta, dict):
            horizon = str(meta.get("target_horizon") or "")
        if not horizon and isinstance(summary, dict):
            horizon = str(summary.get("target_horizon") or "")
        self.horizon_value.setText(horizon or "—")
        regions = summary.get("predicted_regions") or []
        self.facies_count_value.setText(str(len(regions)))

        self.evidence_list.clear()
        for item in field_value(task, "evidence_contribution", []) or []:
            name = item.get("name", "未命名证据")
            weight = item.get("weight", 0)
            self.evidence_list.addItem(f"{name}: {weight:.0%}")
        self.set_actions_enabled(can_export=True, can_send=True)
