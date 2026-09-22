from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.modelview.reconcile import reconcile_widget_items
from paleo_workbench.viz.mapping_helpers import active_map_document, field_value


def _panel_qss() -> str:
    pal = style.palette()
    return (
        f"QFrame#MapDocumentPanel {{ background: {pal['BG_SIDEBAR']};"
        f" border: 1px solid {pal['BORDER']};"
        f" border-radius: {tokens.RADIUS_CARD}px; }}"
    )


def _title_qss() -> str:
    pal = style.palette()
    return (
        f"color: {pal['TEXT_PRIMARY']}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
        " border: none; background: transparent;"
    )


def _secondary_label_qss() -> str:
    pal = style.palette()
    return (
        f"color: {pal['TEXT_SECONDARY']}; font-size: 11px;"
        " border: none; background: transparent;"
    )


def _value_qss() -> str:
    pal = style.palette()
    return (
        f"color: {pal['TEXT_PRIMARY']}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
        " border: none; background: transparent;"
    )


def _list_qss() -> str:
    pal = style.palette()
    return (
        f"QListWidget {{ background: {pal['BG_SIDEBAR']};"
        f" border: 1px solid {pal['BORDER']};"
        f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px; }}"
    )


class MapDocumentPanel(QFrame):
    """Left-hand read-only summary of available paleogeographic map documents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapDocumentPanel")
        # V9：固定 240 → 最小 200 地板（可自由调整宽度）。
        self.setMinimumWidth(200)
        style.bind(self, _panel_qss)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel("古地理图文档")
        style.bind(title, _title_qss)
        layout.addWidget(title)

        self.name_value = self._add_value(layout, "当前图件", "未选择古地理图")
        self.horizon_value = self._add_value(layout, "目标层位", "未设置")
        self.polygon_count_value = self._add_value(layout, "相带多边形", "0 个相带")
        self.well_count_value = self._add_value(layout, "井位叠加", "0 口井")

        list_label = QLabel("图件列表")
        style.bind(list_label, _secondary_label_qss)
        layout.addWidget(list_label)
        self.document_list = QListWidget()
        style.bind(self.document_list, _list_qss)
        layout.addWidget(self.document_list, 1)
        # reconcile 回调按键回查文档对象（update_state 每次刷新）。
        self._documents: list = []

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        style.bind(label, _secondary_label_qss)
        layout.addWidget(label)
        value = QLabel(value_text)
        style.bind(value, _value_qss)
        layout.addWidget(value)
        return value

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        self._documents = documents
        document = active_map_document(documents)
        name = field_value(document, "name", "") or "未选择古地理图"
        horizon = field_value(document, "linked_target_horizon", "") or "未设置"
        polygons = field_value(document, "facies_polygons", []) or []
        wells = field_value(document, "well_overlays", []) or []

        self.name_value.setText(name)
        self.horizon_value.setText(horizon)
        self.polygon_count_value.setText(f"{len(polygons)} 个相带")
        self.well_count_value.setText(f"{len(wells)} 口井")

        # V11 D2 ⑮：clear+rebuild → 键差分（键 = 图档 id）——项身份/选中/
        # 滚动位置在状态刷新间保持，标签原地更新。
        reconcile_widget_items(
            self.document_list,
            [self._document_key(item) for item in documents],
            make_item=lambda _key: QListWidgetItem(""),
            update_item=self._update_document_list_item,
        )

    @staticmethod
    def _document_key(item) -> str:
        doc_id = str(field_value(item, "id", "") or "")
        return doc_id if doc_id else f"doc@{id(item)}"

    def _update_document_list_item(self, list_item: QListWidgetItem, key: str) -> None:
        source = next(
            (item for item in self._documents if self._document_key(item) == key),
            None,
        )
        if source is None:
            return
        item_name = field_value(source, "name", "") or "未命名图件"
        item_horizon = field_value(source, "linked_target_horizon", "") or "未设置"
        label = f"{item_name} · {item_horizon}"
        if list_item.text() != label:
            list_item.setText(label)
