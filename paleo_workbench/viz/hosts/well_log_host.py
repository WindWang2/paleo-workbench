from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.ui import tokens
from paleo_workbench.viz.models import VizPayload


class WellLogHost:
    """Host for ``geoviz_well_log.WellLogCanvas`` (aligns with WellLogPage).

    Embeds a top track summary bar displaying all loaded well log tracks (测井道列表)
    alongside the 2D QPainter canvas.
    """

    tab_title = "测井"

    def __init__(self) -> None:
        self.widget = QFrame()
        self.widget.setObjectName("WellLogHostContainer")
        self.widget.setStyleSheet("QFrame#WellLogHostContainer { background-color: #ffffff; }")
        self.widget.setAutoFillBackground(True)

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.track_bar = QLabel("测井道列表: 未加载数据")
        self.track_bar.setObjectName("WellLogTrackBar")
        self.track_bar.setStyleSheet(
            f"QLabel {{ background: {tokens.BG_SEARCH};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px;"
            f" padding: 6px 12px;"
            f" color: {tokens.TEXT_SECONDARY};"
            f" font-size: {tokens.FONT_SIZE_BASE};"
            f" font-weight: 500; }}"
        )
        self.track_bar.setWordWrap(True)
        layout.addWidget(self.track_bar)

        self.canvas = WellLogCanvas()
        self.widget.canvas = self.canvas
        layout.addWidget(self.canvas, 1)

    def clear(self) -> None:
        self.canvas.set_tracks([])
        self.track_bar.setText("测井道列表: 未加载数据")

    def apply(self, payload: VizPayload) -> bool:
        data = payload.well_log
        if data is None and payload.well_logs:
            data = payload.well_logs[0]
        if data is None:
            self.clear()
            return False

        tracks = build_qpainter_tracks(data)
        self.canvas.set_tracks(tracks)

        track_names = [getattr(t, "label", str(t)) for t in tracks if getattr(t, "label", None)]
        if track_names:
            names_str = "  |  ".join(track_names)
            self.track_bar.setText(f"📋 测井道列表 ({len(track_names)} 道):  {names_str}")
        else:
            self.track_bar.setText("测井道列表: 无有效测井道")

        return True
