from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.mapping_helpers import active_map_document, field_value


class MapDocumentPanel(QFrame):
    """Left-hand read-only summary of available paleogeographic map documents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapDocumentPanel")
        self.setFixedWidth(240)
        self.setStyleSheet(
            f"QFrame#MapDocumentPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel("古地理图文档")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.name_value = self._add_value(layout, "当前图件", "未选择古地理图")
        self.horizon_value = self._add_value(layout, "目标层位", "未设置")
        self.polygon_count_value = self._add_value(layout, "相带多边形", "0 个相带")
        self.well_count_value = self._add_value(layout, "井位叠加", "0 口井")

        list_label = QLabel("图件列表")
        list_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(list_label)
        self.document_list = QListWidget()
        self.document_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px; }}"
        )
        layout.addWidget(self.document_list, 1)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, map_documents: list | tuple | None) -> None:
        documents = list(map_documents or [])
        document = active_map_document(documents)
        name = field_value(document, "name", "") or "未选择古地理图"
        horizon = field_value(document, "linked_target_horizon", "") or "未设置"
        polygons = field_value(document, "facies_polygons", []) or []
        wells = field_value(document, "well_overlays", []) or []

        self.name_value.setText(name)
        self.horizon_value.setText(horizon)
        self.polygon_count_value.setText(f"{len(polygons)} 个相带")
        self.well_count_value.setText(f"{len(wells)} 口井")

        self.document_list.clear()
        for item in documents:
            item_name = field_value(item, "name", "") or "未命名图件"
            item_horizon = field_value(item, "linked_target_horizon", "") or "未设置"
            self.document_list.addItem(f"{item_name} · {item_horizon}")
