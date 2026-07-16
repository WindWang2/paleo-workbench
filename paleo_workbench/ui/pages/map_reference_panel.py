from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSlider, QVBoxLayout

from paleo_workbench.project.models import MapReferenceLayer
from paleo_workbench.ui import tokens


class MapReferencePanel(QFrame):
    """Right-side controls for CRS-normalized map reference layers."""

    reference_visibility_changed = Signal(str, bool)
    reference_opacity_changed = Signal(str, float)
    overlay_requested = Signal(str)
    _unchecked = Qt.CheckState.Unchecked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapReferencePanel")
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PANEL_PADDING, tokens.PANEL_PADDING, tokens.PANEL_PADDING, tokens.PANEL_PADDING)
        layout.setSpacing(tokens.SPACE_2)
        title = QLabel("参考地图")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)
        self.status_label = QLabel("暂无参考图")
        layout.addWidget(self.status_label)
        self.layer_list = QListWidget()
        self.layer_list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.layer_list, 1)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        controls.addWidget(self.opacity_slider, 1)
        layout.addLayout(controls)
        self._layers: dict[str, MapReferenceLayer] = {}
        self._suppress = False
        self._view_state: dict = {"center": (0.0, 0.0), "scale": 1.0}

    def set_view_state(self, state: dict) -> None:
        self._view_state = dict(state)

    def set_layers(self, layers: list[MapReferenceLayer]) -> None:
        self._suppress = True
        self._layers = {layer.id: layer for layer in layers}
        self.layer_list.clear()
        for layer in layers:
            item = QListWidgetItem(self._layer_label(layer))
            item.setData(Qt.ItemDataRole.UserRole, layer.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
            if layer.status != "ready":
                item.setToolTip(layer.error_message or layer.status)
            self.layer_list.addItem(item)
        self.status_label.setText(self._status_summary(layers))
        if layers:
            self.layer_list.setCurrentRow(0)
            self.opacity_slider.setValue(round(layers[0].opacity * 100))
        self._suppress = False

    @staticmethod
    def _layer_label(layer: MapReferenceLayer) -> str:
        label = layer.name
        if layer.status == "offline":
            label = f"{label} (离线)"
        elif layer.status == "failed":
            label = f"{label} (失败)"
        if layer.external:
            label = f"{label} [外部]"
        return label

    @staticmethod
    def _status_summary(layers: list[MapReferenceLayer]) -> str:
        if not layers:
            return "暂无参考图"
        offline = sum(1 for layer in layers if layer.status == "offline")
        failed = sum(1 for layer in layers if layer.status == "failed")
        external = sum(1 for layer in layers if layer.external)
        parts = ["坐标已对齐"]
        if offline:
            parts.append(f"{offline} 层离线")
        if failed:
            parts.append(f"{failed} 层失败")
        if external:
            parts.append(f"{external} 外部")
        return " · ".join(parts)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if not self._suppress:
            self.reference_visibility_changed.emit(str(item.data(Qt.ItemDataRole.UserRole)), item.checkState() == Qt.CheckState.Checked)

    def _on_opacity_changed(self, value: int) -> None:
        item = self.layer_list.currentItem()
        if item is not None and not self._suppress:
            self.reference_opacity_changed.emit(str(item.data(Qt.ItemDataRole.UserRole)), float(value) / 100.0)
