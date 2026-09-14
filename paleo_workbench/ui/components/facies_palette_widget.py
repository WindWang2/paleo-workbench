"""沉浸式相带编绘调色板（M2）——网格化相带画刷 + 装备状态呈现。

数据与颜色单一真源：词表 = :class:`FaciesTaxonomy`（工程覆盖优先），
颜色 = :func:`stage_actions.facies_category_color`（与分类渲染器同款），
花纹 = ``facies_patterns``（有 SVG 映射的相才有）。装备状态写入宿主注入
的 :class:`~paleo_workbench.ui.workstation.facies_selector.FaciesBrushContext`
（本部件不私藏状态）。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.facies_patterns import (
    pattern_id_for_facies,
    pattern_path_for_facies,
)
from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy

#: 常用相带快捷键位数（1-9 数字键装备；00-decisions D6/D11）。
FAVORITE_KEY_COUNT = 9


def facies_color(name: str) -> str:
    """相名 → 分类渲染器同款颜色（单一取色真源，D11 三处一致）。"""
    from paleo_workbench.ui.workstation.stage_actions import facies_category_color

    return facies_category_color(name)


def _swatch_icon(color_hex: str, pattern_name: str | None) -> QIcon:
    """纯色底 + （有 SVG 时）花纹角标的调色板缩略图。"""
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.fillRect(1, 1, 16, 16, QColor(str(color_hex)))
    painter.setPen(QColor("#26364d"))
    painter.drawRect(0, 0, 17, 17)
    painter.end()
    return QIcon(pixmap)


class FaciesPaletteWidget(QWidget):
    """相带画刷调色板：相分区 + 亚相格 + 吸色管开关 + 装备栏。"""

    eyedropper_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FaciesPalette")
        self._taxonomy: FaciesTaxonomy | None = None
        self._brush: Any = None
        self._swatches: list[dict] = []  # {button, selection, top, sub}
        self._favorites: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(4)
        self.eyedropper_button = QToolButton(self)
        self.eyedropper_button.setObjectName("FaciesEyedropperButton")
        self.eyedropper_button.setText("💡 吸色管")
        self.eyedropper_button.setToolTip(
            "激活后在地图上点击已有相带，一键吸取其相带属性/颜色/花纹")
        self.eyedropper_button.setCheckable(True)
        self.eyedropper_button.toggled.connect(self.eyedropper_toggled.emit)
        self._summary_label = QLabel("—", self)
        self._summary_label.setObjectName("FaciesPaletteSummary")
        top_row.addWidget(self.eyedropper_button)
        top_row.addStretch(1)
        top_row.addWidget(self._summary_label)
        layout.addLayout(top_row)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget(self._scroll)
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(8)
        self._host_layout.addStretch(1)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)

        self.equip_label = QLabel("未装备 — 点击格装备画刷", self)
        self.equip_label.setObjectName("FaciesEquipLabel")
        layout.addWidget(self.equip_label)

    # -- 数据装配 -------------------------------------------------------------

    def set_taxonomy(self, taxonomy: FaciesTaxonomy) -> None:
        self._taxonomy = taxonomy
        self._rebuild()

    def set_brush(self, brush: Any) -> None:
        """注入装备上下文（FaciesBrushContext；本部件只读+equip 写入）。"""
        if self._brush is not None:
            try:
                self._brush.equipped_changed.disconnect(self._on_equipped)
            except (TypeError, RuntimeError):
                pass
        self._brush = brush
        if brush is not None:
            brush.equipped_changed.connect(self._on_equipped)
        self._on_equipped(brush.selection() if brush is not None else {})

    def _rebuild(self) -> None:
        while self._host_layout.count() > 1:
            item = self._host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._swatches = []
        self._favorites = []
        if self._taxonomy is None:
            return
        for top in self._taxonomy.names("facies"):
            section = QFrame(self._host)
            section.setObjectName("FaciesPaletteSection")
            section.setProperty("faciesName", top)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(4, 4, 4, 4)
            section_layout.setSpacing(4)
            header = QHBoxLayout()
            header_label = QLabel(top, section)
            header_label.setObjectName("FaciesPaletteSectionHeader")
            pattern = pattern_path_for_facies(top)
            if pattern is not None:
                header_icon = QLabel(section)
                header_icon.setPixmap(
                    QIcon(str(pattern)).pixmap(QSize(20, 20)))
                header.addWidget(header_icon)
            color_chip = QLabel(section)
            chip = QPixmap(12, 12)
            chip.fill(QColor(facies_color(top)))
            color_chip.setPixmap(chip)
            header.addWidget(color_chip)
            header.addWidget(header_label)
            header.addStretch(1)
            section_layout.addLayout(header)

            grid = QGridLayout()
            grid.setSpacing(3)
            column = 0
            for sub in self._taxonomy.names("sub_facies", (top,)):
                selection = {
                    "facies": top, "sub_facies": sub, "micro_facies": "",
                }
                button = QToolButton(section)
                button.setObjectName("FaciesSwatchButton")
                button.setCheckable(True)
                button.setText(sub)
                button.setToolTip(f"{top} / {sub}")
                button.setIcon(_swatch_icon(facies_color(top),
                                            pattern_id_for_facies(top)))
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                button.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.clicked.connect(
                    lambda _checked=False, sel=dict(selection):
                    self.equip_by_selection(sel))
                entry = {
                    "button": button, "selection": selection, "top": top,
                    "sub": sub,
                }
                self._swatches.append(entry)
                if len(self._favorites) < FAVORITE_KEY_COUNT:
                    self._favorites.append(entry)
                grid.addWidget(button, len(self._favorites) // 3,
                               column)
                column = (column + 1) % 3
            section_layout.addLayout(grid)
            self._host_layout.insertWidget(self._host_layout.count() - 1,
                                           section)
        self._refresh_key_hints()
        n_f, n_s, n_m = self._taxonomy.counts()
        self._summary_label.setText(f"相 {n_f} · 亚相 {n_s} · 微相 {n_m}")

    def _refresh_key_hints(self) -> None:
        for index, entry in enumerate(self._favorites, start=1):
            entry["button"].setText(f"{index} {entry['sub']}")

    # -- 装备 -----------------------------------------------------------------

    def favorites(self) -> list[dict]:
        return [
            {"selection": dict(entry["selection"]),
             "label": f"{entry['top']} / {entry['sub']}"}
            for entry in self._favorites
        ]

    def equip_by_selection(self, selection: dict) -> None:
        if self._brush is not None:
            self._brush.equip(selection)

    def equip_by_index(self, index: int) -> None:
        if 0 <= index < len(self._favorites):
            self.equip_by_selection(dict(self._favorites[index]["selection"]))

    def _on_equipped(self, selection: dict) -> None:
        armed = bool(selection.get("facies"))
        if armed:
            parts = [selection.get("facies", ""),
                     selection.get("sub_facies", ""),
                     selection.get("micro_facies", "")]
            label = " / ".join(p for p in parts if p)
            self.equip_label.setText(f"装备：{label}")
        else:
            self.equip_label.setText("未装备 — 点击格装备画刷")
        current = self._current_swatch_key(selection)
        for entry in self._swatches:
            checked = self._swatch_key(entry) == current if armed else False
            entry["button"].setChecked(checked)

    @staticmethod
    def _swatch_key(entry: dict) -> tuple[str, str]:
        return entry["top"], entry["sub"]

    @staticmethod
    def _current_swatch_key(selection: dict) -> tuple[str, str]:
        return (str(selection.get("facies") or ""),
                str(selection.get("sub_facies") or ""))

    # -- 计数（测试/视觉回归 ------------------------------------------------------

    def section_count(self) -> int:
        return sum(
            1
            for i in range(self._host_layout.count())
            if self._host_layout.itemAt(i).widget() is not None
            and self._host_layout.itemAt(i).widget().objectName()
            == "FaciesPaletteSection"
        )

    def swatch_count(self) -> int:
        return len(self._swatches)

    def set_eyedropper_active(self, active: bool) -> None:
        """外部（吸色管控制器）回同步按钮态（抑制再广播）。"""
        self.eyedropper_button.blockSignals(True)
        self.eyedropper_button.setChecked(active)
        self.eyedropper_button.blockSignals(False)
