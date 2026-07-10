from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout

from geoviz_paleo_map import PaleoMapCanvas

from paleo_workbench.ui import tokens


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

    def load_preview(
        self,
        features: list | None,
        *,
        wells: list | None = None,
        period_name: str = "",
    ) -> None:
        """Load pre-normalized GeoJSON facies + lng/lat wells for chrome preview."""
        feats = list(features or [])
        well_list = list(wells or [])
        if not feats and not well_list:
            self.canvas.load_features([], period_name="", wells=[])
            self.empty_label.setText("未选择古地理图" if not period_name else "暂无图面要素")
            self.empty_label.setHidden(False)
            self.stack.setCurrentWidget(self.empty_label)
            return
        self.canvas.load_features(feats, period_name=period_name, wells=well_list)
        self.empty_label.setHidden(True)
        self.stack.setCurrentWidget(self.canvas)

    def update_state(self, document) -> None:
        if document is None:
            self.load_preview([], wells=[], period_name="")
            self.empty_label.setText("未选择古地理图")
            return

        from paleo_workbench.ui.pages.mapping_helpers import preview_payload_from_document

        features, wells, horizon = preview_payload_from_document(document)
        self.load_preview(features, wells=wells, period_name=horizon)
