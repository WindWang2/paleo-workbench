from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz_seismic import SeismicView

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.seismic_prediction_helpers import seismic_volume_from_prediction


class SeismicViewPanel(QFrame):
    """Center panel embedding geo-viz-engine's SeismicView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicViewPanel")
        self.volume_shape: tuple[int, int, int] | None = None
        self.setStyleSheet(
            f"QFrame#SeismicViewPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.title_label = QLabel("地震预测体")
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

        self.view = SeismicView(auto_load=False)
        self.stack.addWidget(self.view)
        outer.addWidget(host, 1)

    def update_state(self, task) -> None:
        if task is None:
            self.volume_shape = None
            self.empty_label.setText("未选择预测任务")
            self.empty_label.setHidden(False)
            self.stack.setCurrentWidget(self.empty_label)
            return

        volume = seismic_volume_from_prediction(task)
        self.volume_shape = tuple(int(value) for value in volume.shape)
        self.view.load_demo(volume)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.view)
