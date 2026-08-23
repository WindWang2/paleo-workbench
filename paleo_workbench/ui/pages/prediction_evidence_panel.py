from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

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
        self._inferring = False

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
        self.class_distribution_value = self._add_value(layout, "预测相带", "—")
        # Async run outcome landing spot (#897): completions/failures arrive
        # on queued signals and must not open modal dialogs.
        self.status_value = self._add_value(layout, "状态", "—")
        self.waiting_label = QLabel("正在提交并等待线上推理结果…")
        self.waiting_label.setObjectName("WorkFieldLabel")
        self.waiting_label.setAccessibleName("线上测井预测等待状态")
        self.waiting_label.hide()
        layout.addWidget(self.waiting_label)
        # A 0..0 QProgressBar is Qt's native indeterminate animation.  It is
        # deliberately in the evidence panel (rather than a dialog), so the
        # user can continue to inspect the selected well and diagnostic log.
        self.waiting_indicator = QProgressBar()
        self.waiting_indicator.setObjectName("PredictionWaitIndicator")
        self.waiting_indicator.setRange(0, 0)
        self.waiting_indicator.setTextVisible(False)
        self.waiting_indicator.setFixedHeight(6)
        self.waiting_indicator.setAccessibleName("线上测井预测进行中")
        self.waiting_indicator.hide()
        layout.addWidget(self.waiting_indicator)

        evidence_label = QLabel("证据贡献")
        evidence_label.setObjectName("WorkFieldLabel")
        layout.addWidget(evidence_label)

        self.evidence_list = QListWidget()
        self.evidence_list.setObjectName("WorkListWidget")
        layout.addWidget(self.evidence_list, 1)

        diagnostic_label = QLabel("运行日志")
        diagnostic_label.setObjectName("WorkFieldLabel")
        layout.addWidget(diagnostic_label)
        self.diagnostic_log = QPlainTextEdit()
        self.diagnostic_log.setObjectName("PredictionDiagnosticLog")
        self.diagnostic_log.setReadOnly(True)
        self.diagnostic_log.setPlaceholderText("尚无运行日志")
        self.diagnostic_log.setMinimumHeight(100)
        self.diagnostic_log.setMaximumHeight(140)
        self.diagnostic_log.setMaximumBlockCount(200)
        layout.addWidget(self.diagnostic_log)
        self.copy_diagnostic_btn = QPushButton("复制运行日志")
        self.copy_diagnostic_btn.setObjectName("SecondaryButton")
        self.copy_diagnostic_btn.setEnabled(False)
        self.copy_diagnostic_btn.clicked.connect(self.copy_diagnostic_log)
        layout.addWidget(self.copy_diagnostic_btn)

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

        self.run_btn = QPushButton("运行线上测井预测")
        self.run_btn.setObjectName("SecondaryButton")
        self.run_btn.setToolTip(
            "将所选井的模型要求曲线记录发送到认证线上单井预测服务；"
            "结果将保存到数据管理"
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
        # #850-7: while an inference runs the run/demo actions stay disabled
        # instead of silently swallowing a second click.
        self.run_btn.setEnabled(not self._inferring)
        self.demo_btn.setEnabled(not self._inferring)

    def set_inferring(self, busy: bool) -> None:
        """Enable/disable the run/demo actions for the duration of a run."""
        self._inferring = bool(busy)
        self.run_btn.setEnabled(not self._inferring)
        self.demo_btn.setEnabled(not self._inferring)
        self.waiting_label.setVisible(self._inferring)
        self.waiting_indicator.setVisible(self._inferring)
        if busy:
            self.status_value.setText("推断中…")

    def set_status(self, text: str) -> None:
        """Show an async run outcome in-page (no modal dialogs, #897)."""
        self.status_value.setText(text)

    def set_diagnostic_log(self, text: str) -> None:
        """Display a redacted run diagnostic that a user can copy verbatim."""
        value = str(text or "").strip()
        self.diagnostic_log.setPlainText(value)
        self.copy_diagnostic_btn.setEnabled(bool(value))

    def copy_diagnostic_log(self) -> None:
        """Copy the whole diagnostic without requiring text selection first."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.diagnostic_log.toPlainText())

    def update_state(
        self,
        task,
        *,
        bound_las: bool = False,
        selected_source: bool = False,
    ) -> None:
        summary = field_value(task, "result_summary", {}) or {}
        meta = field_value(task, "model_metadata", {}) or {}
        if task is None:
            self.mock_value.setText("—")
            self.source_value.setText("数据管理井数据" if selected_source else "—")
            self.horizon_value.setText("—")
            self.facies_count_value.setText("—")
            self.class_distribution_value.setText("—")
            self.class_distribution_value.setToolTip("")
            self.evidence_list.clear()
            self.set_actions_enabled(
                can_export=bool(selected_source and bound_las), can_send=False
            )
            return

        # Honest output labeling (P2): random/mock output must never display
        # as 真实, and heuristic output is not a scientific prediction.
        if summary.get("model_type") in {"geoviz_online", "inference_api_online"}:
            nature = "线上测井预测"
        elif summary.get("is_mock"):
            nature = "Mock"
        elif not summary.get("final_scientific_prediction", False):
            nature = "启发式"
        else:
            nature = "科学预测"
        if summary.get("demo"):
            nature = f"Demo · {nature}"
        replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
        self.mock_value.setText(f"{nature} · {replaceable}")
        if summary.get("model_type") in {"geoviz_online", "inference_api_online"}:
            self.source_value.setText("认证线上推理服务")
        elif summary.get("demo") or summary.get("source") == "synthetic/demo":
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
        remote_summary = summary.get("remote_summary") or {}
        class_counts = remote_summary.get("classCounts") if isinstance(remote_summary, dict) else {}
        if isinstance(class_counts, dict) and class_counts:
            total = sum(
                float(value)
                for value in class_counts.values()
                if isinstance(value, (int, float))
            )
            ranked = sorted(
                (
                    (str(name), float(value))
                    for name, value in class_counts.items()
                    if isinstance(value, (int, float))
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            summary_text = "、".join(
                f"{name} {count / total:.1%}" if total else f"{name} {count:g}"
                for name, count in ranked[:2]
            )
            self.class_distribution_value.setText(summary_text)
            self.class_distribution_value.setToolTip(
                "\n".join(f"{name}: {count:g}" for name, count in ranked)
            )
        else:
            self.class_distribution_value.setText("—")
            self.class_distribution_value.setToolTip("")

        self.evidence_list.clear()
        for item in field_value(task, "evidence_contribution", []) or []:
            name = item.get("name", "未命名证据")
            weight = item.get("weight", 0)
            self.evidence_list.addItem(f"{name}: {weight:.0%}")
        self.set_actions_enabled(can_export=True, can_send=True)
