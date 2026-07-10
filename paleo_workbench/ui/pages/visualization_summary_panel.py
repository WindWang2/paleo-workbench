from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizRef


class VisualizationSummaryPanel(QFrame):
    """Left-hand project-slice summary for composite visualization."""

    asset_selected = Signal(object)  # VizRef

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationSummaryPanel")
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"QFrame#VisualizationSummaryPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        self._adapter = VizAdapter()
        self._resources: list = []
        self._map_documents: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("可视化总览")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.prediction_count_value = self._add_value(layout, "预测任务", "0 个")
        self.map_count_value = self._add_value(layout, "古地理图", "0 幅")
        self.resource_count_value = self._add_value(layout, "资源项", "0 项")

        list_label = QLabel("可打开资产")
        list_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(list_label)
        self.asset_list = QListWidget()
        self.asset_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px; }}"
        )
        self.asset_list.itemActivated.connect(self._on_item_activated)
        self.asset_list.itemClicked.connect(self._on_item_activated)
        layout.addWidget(self.asset_list, 1)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, resources: list, prediction_tasks: list, map_documents: list) -> None:
        self._resources = list(resources or [])
        self._map_documents = list(map_documents or [])
        self.prediction_count_value.setText(f"{len(prediction_tasks or [])} 个")
        self.map_count_value.setText(f"{len(map_documents or [])} 幅")
        self.resource_count_value.setText(f"{len(resources or [])} 项")
        self._rebuild_asset_list()

    def _rebuild_asset_list(self) -> None:
        self.asset_list.clear()
        for resource in self._resources:
            ref = self._adapter.ref_from_resource(resource)
            if ref is None:
                continue
            name = str(getattr(resource, "name", "") or ref.label or ref.id or "未命名")
            kind_label = "测井" if ref.kind == "well_log" else "地震"
            item = QListWidgetItem(f"{kind_label} · {name}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

        for doc in self._map_documents:
            ref = self._adapter.ref_from_map_document(doc)
            name = str(getattr(doc, "name", "") or ref.label or "未命名图件")
            item = QListWidgetItem(f"古地理 · {name}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

    def _on_item_activated(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        ref = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(ref, VizRef):
            self.asset_selected.emit(ref)
