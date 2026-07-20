from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench import tokens
from paleo_workbench.viz.models import VizPayload


class TrackVisibilityDialog(QDialog):
    """Modal dialog for customizing visible well log tracks."""

    def __init__(self, tracks: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ 设置显示井道")
        self.resize(360, 480)
        self._tracks = tracks

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_3)

        info_lbl = QLabel("请勾选需要在绘图画布中显示的井道：")
        info_lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-weight: 500;")
        layout.addWidget(info_lbl)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        container = QWidget()
        box_layout = QVBoxLayout(container)
        box_layout.setSpacing(tokens.SPACE_2)

        self._checkboxes: list[tuple[object, QCheckBox]] = []
        for track in tracks:
            label = getattr(track, "label", "未命名井道")
            cb = QCheckBox(label, container)
            cb.setChecked(getattr(track, "_visible", True))
            box_layout.addWidget(cb)
            self._checkboxes.append((track, cb))

        box_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选", self)
        select_none_btn = QPushButton("反选", self)

        select_all_btn.clicked.connect(self._select_all)
        select_none_btn.clicked.connect(self._invert_selection)

        btn_layout.addWidget(select_all_btn)
        btn_layout.addWidget(select_none_btn)
        btn_layout.addStretch()

        ok_btn = QPushButton("确定", self)
        ok_btn.setStyleSheet(f"background: {tokens.PRIMARY}; color: white; font-weight: bold;")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _select_all(self) -> None:
        for _, cb in self._checkboxes:
            cb.setChecked(True)

    def _invert_selection(self) -> None:
        for _, cb in self._checkboxes:
            cb.setChecked(not cb.isChecked())

    def apply_visibility(self) -> None:
        for track, cb in self._checkboxes:
            track._visible = cb.isChecked()


class WellLogHost:
    """Host for ``geoviz_well_log.WellLogCanvas`` (aligns with WellLogPage).

    Embeds a top track summary bar displaying all loaded well log tracks (测井道列表)
    alongside a track visibility settings button and the interactive 2D QPainter canvas.
    """

    tab_title = "测井"

    def __init__(self) -> None:
        self.widget = QFrame()
        self.widget.setObjectName("WellLogHostContainer")
        self.widget.setStyleSheet("QFrame#WellLogHostContainer { background-color: #ffffff; }")
        self.widget.setAutoFillBackground(True)
        self.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.widget.setMinimumSize(100, 100)

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_2)

        # Header toolbar with track summary and settings button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(tokens.SPACE_2)

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
        header_layout.addWidget(self.track_bar, 1)

        self.settings_btn = QPushButton("⚙️ 设置显示井道")
        self.settings_btn.setStyleSheet(
            f"QPushButton {{ background: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px;"
            f" padding: 6px 12px;"
            f" color: {tokens.TEXT_PRIMARY};"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {tokens.BG_SEARCH}; border-color: {tokens.PRIMARY}; }}"
        )
        self.settings_btn.clicked.connect(self._open_track_settings)
        header_layout.addWidget(self.settings_btn)

        layout.addLayout(header_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("WellLogScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll_area.setMinimumSize(100, 100)
        self.scroll_area.setStyleSheet(
            f"QScrollArea#WellLogScrollArea {{ border: 1px solid {tokens.BORDER};"
            f" background-color: #ffffff; }}"
        )
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.canvas = WellLogCanvas()
        self.widget.canvas = self.canvas
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, 1)

    def _open_track_settings(self) -> None:
        if not self.canvas.tracks:
            QMessageBox.information(self.widget, "设置显示井道", "当前未加载测井道数据")
            return
        dialog = TrackVisibilityDialog(self.canvas.tracks, self.widget)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_visibility()
            self.canvas._cache_dirty = True
            self.canvas.update()
            self._update_track_bar()

    def _update_track_bar(self) -> None:
        visible_tracks = [
            t for t in self.canvas.tracks if getattr(t, "_visible", True)
        ]
        track_names = [getattr(t, "label", str(t)) for t in visible_tracks if getattr(t, "label", None)]
        if track_names:
            names_str = "  |  ".join(track_names)
            self.track_bar.setText(f"📋 显示中井道 ({len(track_names)}/{len(self.canvas.tracks)} 道):  {names_str}")
        else:
            self.track_bar.setText("📋 显示中井道 (0 道): 已隐藏全部井道")

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
        self._update_track_bar()

        return True
