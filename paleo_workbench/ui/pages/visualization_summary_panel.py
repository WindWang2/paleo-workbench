from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizRef

_KIND_LABELS = {
    "well_log": "测井",
    "seismic": "地震",
    "map": "古地理",
    "cross_well": "连井",
    "engine_preview": "引擎",
    "prediction": "预测",
}


class VisualizationSummaryPanel(QFrame):
    """Left-hand project-slice summary for composite visualization."""

    asset_selected = Signal(object)  # VizRef

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationSummaryPanel")
        self.setFixedWidth(220)

        self._adapter = VizAdapter()
        self._resources: list = []
        self._map_documents: list = []
        self._prediction_tasks: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)
        title = QLabel("可视化总览")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.prediction_count_value = self._add_value(layout, "预测任务", "0 个")
        self.map_count_value = self._add_value(layout, "古地理图", "0 幅")
        self.resource_count_value = self._add_value(layout, "资源项", "0 项")

        list_label = QLabel("可打开资产")
        list_label.setObjectName("WorkFieldLabel")
        layout.addWidget(list_label)
        self.asset_list = QListWidget()
        self.asset_list.setObjectName("WorkListWidget")
        self.asset_list.itemActivated.connect(self._on_item_activated)
        self.asset_list.itemClicked.connect(self._on_item_activated)
        layout.addWidget(self.asset_list, 1)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def update_state(self, resources: list, prediction_tasks: list, map_documents: list) -> None:
        self._resources = list(resources or [])
        self._map_documents = list(map_documents or [])
        self._prediction_tasks = list(prediction_tasks or [])
        self.prediction_count_value.setText(f"{len(self._prediction_tasks)} 个")
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
            kind_label = _KIND_LABELS.get(ref.kind, ref.kind)
            item = QListWidgetItem(f"{kind_label} · {name}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

        for doc in self._map_documents:
            ref = self._adapter.ref_from_map_document(doc)
            name = str(getattr(doc, "name", "") or ref.label or "未命名图件")
            item = QListWidgetItem(f"古地理 · {name}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

        for task in self._prediction_tasks:
            ref = self._adapter.ref_from_prediction(task)
            name = str(getattr(task, "name", "") or ref.label or "预测任务")
            item = QListWidgetItem(f"预测 · {name}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

        # Virtual multi-well section when ≥2 LAS resources exist.
        well_ids = [
            str(getattr(r, "id", ""))
            for r in self._resources
            if str(getattr(r, "type", "")).lower() == "well_log"
            and str(getattr(r, "format", "")).lower().lstrip(".") == "las"
            and getattr(r, "id", None)
        ]
        if len(well_ids) >= 2:
            ref = VizRef(
                kind="cross_well",
                id=well_ids[0],
                label=f"连井剖面 ({len(well_ids)} 口井)",
                related_ids=tuple(well_ids[:8]),
            )
            item = QListWidgetItem(f"连井 · {ref.label}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            self.asset_list.addItem(item)

    def _on_item_activated(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        ref = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(ref, VizRef):
            self.asset_selected.emit(ref)
