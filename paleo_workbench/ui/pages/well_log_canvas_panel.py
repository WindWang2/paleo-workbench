from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz_well_log import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import well_log_data_from_prediction


class WellLogCanvasPanel(QFrame):
    """Center panel embedding geo-viz-engine's WellLogCanvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WellLogCanvasPanel")
        self.well_log_data = None
        self.setStyleSheet(
            f"QFrame#WellLogCanvasPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.title_label = QLabel("测井预测剖面")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        outer.addWidget(self.title_label)

        host = QFrame()
        host.setStyleSheet(
            f"QFrame {{ background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; }}"
        )
        self.stack = QStackedLayout(host)
        self.stack.setContentsMargins(0, 0, 0, 0)

        self.empty_label = QLabel("未选择预测任务")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 13px;"
            " border: none; background: transparent;"
        )
        self.stack.addWidget(self.empty_label)

        self.canvas = WellLogCanvas()
        self.stack.addWidget(self.canvas)
        outer.addWidget(host, 1)

    def update_state(self, task) -> None:
        if task is None:
            self.well_log_data = None
            self.canvas.set_tracks([])
            self.empty_label.setText("未选择预测任务")
            self.empty_label.setHidden(False)
            self.stack.setCurrentWidget(self.empty_label)
            return

        self.well_log_data = well_log_data_from_prediction(task)
        self.canvas.set_tracks(build_qpainter_tracks(self.well_log_data))
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas)
