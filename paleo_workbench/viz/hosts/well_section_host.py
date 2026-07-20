"""Host for ``geoviz_well_log.WellSectionCanvas`` (Multi-Well Correlation Workbench)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
)

from geoviz import WellSectionCanvas

from paleo_workbench.ui import tokens
from paleo_workbench.viz.models import VizPayload


class WellSectionHost:
    """Host container for Multi-Well Stratigraphic Correlation Section Workbench.

    Embeds a top control bar for datum flattening, well spacing, facies fill toggle,
    and high-resolution export.
    """

    tab_title = "多井对比剖面"

    def __init__(self) -> None:
        self.widget = QFrame()
        self.widget.setObjectName("WellSectionHostContainer")
        self.widget.setStyleSheet("QFrame#WellSectionHostContainer { background-color: #ffffff; }")
        self.widget.setAutoFillBackground(True)

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_2)

        # Top Control Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(tokens.SPACE_3)

        # 1. Datum Flattening Selector
        datum_lbl = QLabel("拉平基准面:")
        datum_lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-weight: 500;")
        toolbar.addWidget(datum_lbl)

        self.datum_combo = QComboBox()
        self.datum_combo.addItem("绝对海拔深度 (TVD)", "absolute")
        self.datum_combo.currentIndexChanged.connect(self._on_datum_changed)
        toolbar.addWidget(self.datum_combo)

        # 2. Inter-Well Spacing SpinBox
        spacing_lbl = QLabel("井间距(px):")
        spacing_lbl.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-weight: 500;")
        toolbar.addWidget(spacing_lbl)

        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(80, 600)
        self.spacing_spin.setValue(180)
        self.spacing_spin.valueChanged.connect(self._on_spacing_changed)
        toolbar.addWidget(self.spacing_spin)

        # 3. Facies Fill Toggle
        self.facies_chk = QCheckBox("显示沉积相充填")
        self.facies_chk.setChecked(True)
        self.facies_chk.toggled.connect(self._on_facies_toggled)
        toolbar.addWidget(self.facies_chk)

        toolbar.addStretch(1)

        # 4. High-Res PNG Export Button
        self.export_btn = QPushButton("🖼️ 导出剖面图件")
        self.export_btn.setStyleSheet(
            f"QPushButton {{ background: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px;"
            f" padding: 6px 12px;"
            f" color: {tokens.TEXT_PRIMARY};"
            f" font-weight: 600; }}"
            f"QPushButton:hover {{ background: {tokens.BG_SEARCH}; border-color: {tokens.PRIMARY}; }}"
        )
        self.export_btn.clicked.connect(self._on_export_clicked)
        toolbar.addWidget(self.export_btn)

        layout.addLayout(toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("WellSectionScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            f"QScrollArea#WellSectionScrollArea {{ border: 1px solid {tokens.BORDER};"
            f" background-color: #ffffff; }}"
        )
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Main 2D QPainter Section Canvas
        self.canvas = WellSectionCanvas()
        self.widget.canvas = self.canvas
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, 1)

    def _on_datum_changed(self) -> None:
        idx = self.datum_combo.currentIndex()
        if idx == 0:
            self.canvas.set_datum_mode("absolute")
        else:
            datum_name = self.datum_combo.currentData()
            self.canvas.set_datum_mode("datum_shift", datum_name=str(datum_name))

    def _on_spacing_changed(self, val: int) -> None:
        self.canvas.set_inter_well_spacing(val)

    def _on_facies_toggled(self, checked: bool) -> None:
        self.canvas.set_show_facies_fills(checked)

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.widget,
            "导出多井对比剖面图件",
            "MultiWell_Correlation_Section.png",
            "PNG Image (*.png);;All Files (*)",
        )
        if path:
            pixmap = self.canvas.grab()
            if pixmap.save(path):
                QMessageBox.information(self.widget, "导出成功", f"剖面图件已成功保存至:\n{path}")
            else:
                QMessageBox.warning(self.widget, "导出失败", "图像保存失败，请检查文件写入权限。")

    def clear(self) -> None:
        self.canvas.set_wells([])

    def apply(self, payload: VizPayload) -> bool:
        wells = []
        if payload.well_log:
            wells.append(payload.well_log)
        if payload.well_logs:
            for w in payload.well_logs:
                if w not in wells:
                    wells.append(w)

        if not wells:
            self.clear()
            return False

        self.canvas.set_wells(wells)

        # Update datum combo items based on available horizon tops
        self.datum_combo.blockSignals(True)
        self.datum_combo.clear()
        self.datum_combo.addItem("绝对海拔深度 (TVD)", "absolute")

        # Collect all horizon names
        datum_names = set()
        for w in wells:
            if hasattr(w, "stratigraphy") and w.stratigraphy:
                for s in w.stratigraphy:
                    datum_names.add(s.name)

        for name in sorted(datum_names):
            self.datum_combo.addItem(f"⚓ 按【{name}】顶界拉平", name)

        self.datum_combo.blockSignals(False)
        return True
