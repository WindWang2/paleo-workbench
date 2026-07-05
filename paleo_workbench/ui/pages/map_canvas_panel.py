from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz_paleo_map import PaleoMapCanvas

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.mapping_helpers import field_value


class MapCanvasPanel(QFrame):
    """Center panel embedding the geo-viz-engine PaleoMapCanvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapCanvasPanel")
        self.setStyleSheet(
            f"QFrame#MapCanvasPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.title_label = QLabel("编图画布")
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

        self.empty_label = QLabel("未选择古地理图")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 13px;"
            " border: none; background: transparent;"
        )
        self.stack.addWidget(self.empty_label)

        self.canvas = PaleoMapCanvas()
        self.stack.addWidget(self.canvas)
        outer.addWidget(host, 1)

    def update_state(self, document) -> None:
        if document is None:
            self.canvas.load_features([], period_name="", wells=[])
            self.empty_label.setText("未选择古地理图")
            self.empty_label.setHidden(False)
            self.stack.setCurrentWidget(self.empty_label)
            return

        features = field_value(document, "facies_polygons", []) or []
        wells = field_value(document, "well_overlays", []) or []
        horizon = field_value(document, "linked_target_horizon", "") or ""
        self.canvas.load_features(features, period_name=horizon, wells=wells)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas)
