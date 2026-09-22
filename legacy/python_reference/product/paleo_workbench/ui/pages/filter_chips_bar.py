"""Filter chips bar for the Data Explorer (D5) — visible filter state.

Renders the active :class:`FilterQuery` as removable chips (view, text,
stage, type, tags+operator), so a filter is never invisible state:

* removing a chip re-issues the query WITHOUT that dimension through
  :attr:`chip_removed` (the table owns the query, the bar only reflects
  and edits it);
* 「清除全部」 resets to the unfiltered view;
* saved filters persist NAMED queries in QSettings (user settings — never
  a second data authority); applying one emits :attr:`filter_applied`.

At catalog scale nothing here touches data: the table routes every change
through the query layer (SQL in paged mode).
"""

from __future__ import annotations

import json

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from paleo_workbench.ui import style, tokens
from paleo_workbench.ui.pages.filter_index import FilterQuery

SAVED_FILTERS_KEY = "data_explorer/saved_filters"

_NODE_LABELS = {
    "all": "全部",
    "trash": "回收站",
    "review_status": "审查",
    "integrity": "完整性",
}
# Chip dimension keys understood by :meth:`_remove_dimension`.
_DIM_VIEW = "view"
_DIM_TEXT = "text"
_DIM_STAGE = "stage"
_DIM_TYPE = "type"
_DIM_TAG = "tag:"
_DIM_OPERATOR = "tag_operator"


def _settings() -> QSettings:
    return QSettings()


def _chip_qss() -> str:
    pal = style.palette()
    return (
        f"QLabel#FilterChip {{ background: {pal['BG_SIDEBAR']};"
        f" border: 1px solid {pal['BORDER']}; border-radius: 9px;"
        f" padding: 1px 8px; color: {pal['TEXT_PRIMARY']};"
        f" font-size: {tokens.FONT_SIZE_MINOR}; }}"
    )


class FilterChipsBar(QWidget):
    """Chips for the active filter + saved-filter apply/save/remove."""

    chip_removed = Signal(str)  # dimension key ("view"|"text"|"stage"|"type"|"tag:<name>"|"tag_operator")
    clear_all = Signal()
    filter_applied = Signal(object)  # FilterQuery

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterChipsBar")
        self._query = FilterQuery(node_type="all")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_1)

        self._chips_layout = QHBoxLayout()
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(tokens.SPACE_1)
        layout.addLayout(self._chips_layout, 1)

        self.clear_btn = QPushButton("清除全部")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.setToolTip("移除全部过滤条件")
        self.clear_btn.clicked.connect(self.clear_all.emit)
        layout.addWidget(self.clear_btn)

        self.saved_combo = QComboBox()
        self.saved_combo.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.saved_combo.setToolTip("应用已保存的过滤器（用户设置）")
        self.saved_combo.addItem("已保存过滤器…")
        self.saved_combo.activated.connect(self._apply_saved)
        layout.addWidget(self.saved_combo)
        self.save_btn = QPushButton("保存过滤器…")
        self.save_btn.setObjectName("SecondaryButton")
        self.save_btn.clicked.connect(self._save_current)
        layout.addWidget(self.save_btn)
        self.delete_saved_btn = QPushButton("删除")
        self.delete_saved_btn.setObjectName("SecondaryButton")
        self.delete_saved_btn.setToolTip("删除当前选择的已保存过滤器")
        self.delete_saved_btn.clicked.connect(self._delete_saved)
        layout.addWidget(self.delete_saved_btn)

        self.reload_saved()
        self.set_query(self._query)

    # -- query rendering -----------------------------------------------------

    def set_query(self, query: FilterQuery) -> None:
        """Re-render the chips for *query* (no signals emitted)."""
        self._query = query
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for key, label in self._dimensions(query):
            self._add_chip(key, label)
        self.clear_btn.setVisible(bool(self._dimensions(query)))

    def _dimensions(self, query: FilterQuery) -> list[tuple[str, str]]:
        dims: list[tuple[str, str]] = []
        node_type = str(query.node_type or "all")
        if node_type != "all":
            value = query.node_value or ""
            label = _NODE_LABELS.get(node_type, node_type)
            dims.append((_DIM_VIEW, f"视图: {label}{(' · ' + value) if value else ''}"))
        if query.search_text:
            dims.append((_DIM_TEXT, f"搜索: {query.search_text}"))
        if query.stage:
            dims.append((_DIM_STAGE, f"阶段: {query.stage}"))
        if query.data_type:
            dims.append((_DIM_TYPE, f"类型: {query.data_type}"))
        for tag in query.tags or ():
            dims.append((_DIM_TAG + tag, f"标签: {tag}"))
        if query.tags and len(query.tags) > 1:
            dims.append(
                (_DIM_OPERATOR, "全部满足" if query.tag_operator == "and" else "任一满足")
            )
        if query.asset_id:
            dims.append((_DIM_VIEW, f"资产: {query.asset_id[:16]}…"))
        return dims

    def _add_chip(self, key: str, label: str) -> None:
        chip = FilterChip(key, f"{label}  ✕")
        chip.clicked.connect(self.chip_removed.emit)
        self._chips_layout.addWidget(chip)

    # -- saved filters (QSettings — user preference, not project data) ---------

    def reload_saved(self) -> None:
        current = self.saved_combo.currentText()
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("已保存过滤器…")
        for name in sorted(self._stored_filters(), key=str.casefold):
            self.saved_combo.addItem(name)
        if current:
            index = self.saved_combo.findText(current)
            if index >= 0:
                self.saved_combo.setCurrentIndex(index)
        self.saved_combo.blockSignals(False)

    def _stored_filters(self) -> dict[str, dict]:
        raw = _settings().value(SAVED_FILTERS_KEY, "")
        try:
            value = json.loads(str(raw)) if raw else []
        except (TypeError, ValueError):
            return {}
        return {entry["name"]: entry["query"] for entry in value if isinstance(entry, dict)}

    def _apply_saved(self, index: int) -> None:
        name = self.saved_combo.itemText(index)
        stored = self._stored_filters().get(name)
        self.saved_combo.setCurrentIndex(0)
        if not stored:
            return
        try:
            query = FilterQuery(
                node_type=stored.get("node_type", "all"),
                node_value=stored.get("node_value"),
                search_text=stored.get("search_text", ""),
                stage=stored.get("stage"),
                data_type=stored.get("data_type"),
                tags=list(stored.get("tags") or ()),
                tag_operator=stored.get("tag_operator", "and"),
            )
        except Exception:
            QMessageBox.warning(self, "应用过滤器", "该保存的过滤器无法解析")
            return
        self.filter_applied.emit(query)

    def _save_current(self) -> None:
        name, ok = QInputDialog.getText(self, "保存过滤器", "名称:")
        if not ok or not str(name or "").strip():
            return
        name = str(name).strip()
        filters = self._stored_filters()
        filters[name] = {
            "node_type": self._query.node_type,
            "node_value": self._query.node_value,
            "search_text": self._query.search_text,
            "stage": self._query.stage,
            "data_type": self._query.data_type,
            "tags": list(self._query.tags or ()),
            "tag_operator": self._query.tag_operator,
        }
        payload = [{"name": k, "query": v} for k, v in filters.items()]
        _settings().setValue(SAVED_FILTERS_KEY, json.dumps(payload, ensure_ascii=False))
        self.reload_saved()
        self.saved_combo.setCurrentIndex(self.saved_combo.findText(name))

    def _delete_saved(self) -> None:
        name = self.saved_combo.currentText()
        if not name or name == "已保存过滤器…":
            return
        filters = self._stored_filters()
        filters.pop(name, None)
        payload = [{"name": k, "query": v} for k, v in filters.items()]
        _settings().setValue(SAVED_FILTERS_KEY, json.dumps(payload, ensure_ascii=False))
        self.reload_saved()


class FilterChip(QLabel):
    """One removable filter chip; clicks emit :attr:`clicked`(dimension)."""

    clicked = Signal(str)

    def __init__(self, key: str, text: str) -> None:
        super().__init__(text)
        self._key = key
        self.setObjectName("FilterChip")
        self.setToolTip("点击移除该过滤条件")
        # E1：构造期不再快照 light 值——经 style.bind 在主题切换时重渲染。
        style.bind(self, _chip_qss)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.MouseButtonPress:
            self.clicked.emit(self._key)
            return True
        return super().mousePressEvent(event)
