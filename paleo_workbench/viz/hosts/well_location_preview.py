from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoviz import (
    GeoVizEngine,
    PlotWidget,
    PreparedPreview,
    PreviewKind,
    XYPreviewPayload,
)

_POINT_INDEX_ROLE = Qt.ItemDataRole.UserRole
_WELL_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1


@dataclass(frozen=True)
class ActiveWell:
    """The selected well record for the lifetime of one prepared preview."""

    resource_id: str
    record_id: int
    point_index: int
    name: str
    x: float
    y: float


class WellLocationPreview(QWidget):
    """Workbench-owned well-location interaction around a generic XY plot."""

    active_well_changed = Signal(object)

    def __init__(
        self,
        engine: GeoVizEngine | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine or GeoVizEngine.default()
        plot = self.engine.create_widget(PreviewKind.XY_SCATTER, self)
        if not isinstance(plot, PlotWidget):
            raise TypeError("XY scatter backend must create a PlotWidget")
        self.plot = plot
        self.plot.set_equal_aspect(True)
        self.plot.point_hovered.connect(self._show_hovered_well)
        self.plot.point_hover_cleared.connect(self._clear_hover_tooltip)
        self.plot.point_clicked.connect(self._activate_clicked_well)
        self.plot.reset_requested.connect(self.reset_view)

        self.well_panel = QFrame(self)
        self.well_panel.setObjectName("WellLocationListPanel")
        self.well_panel.setFixedWidth(240)
        panel_layout = QVBoxLayout(self.well_panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)
        panel_title = QLabel("井名", self.well_panel)
        panel_title.setObjectName("MapDockTitle")
        panel_layout.addWidget(panel_title)
        self.well_search = QLineEdit(self.well_panel)
        self.well_search.setAccessibleName("搜索井名")
        self.well_search.setPlaceholderText("搜索井名…")
        self.well_search.setClearButtonEnabled(True)
        self.well_search.textChanged.connect(self._filter_well_list)
        panel_layout.addWidget(self.well_search)
        self.filter_status = QLabel(self.well_panel)
        self.filter_status.setAccessibleName("当前井筛选状态")
        self.filter_status.setWordWrap(True)
        self.filter_status.hide()
        panel_layout.addWidget(self.filter_status)
        self.well_list = QListWidget(self.well_panel)
        self.well_list.setAccessibleName("井名列表")
        self.well_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.well_list.currentItemChanged.connect(
            self._activate_current_list_well
        )
        self.well_list.itemClicked.connect(self._activate_list_well)
        self.well_list.itemActivated.connect(self._activate_list_well)
        panel_layout.addWidget(self.well_list, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.well_panel)

        self.setFocusPolicy(Qt.StrongFocus)
        self._preview: PreparedPreview | None = None
        self._payload: XYPreviewPayload | None = None
        self.active_well: ActiveWell | None = None
        self._released = False

    def render(self, preview: PreparedPreview) -> None:
        if preview.kind is not PreviewKind.XY_SCATTER or not isinstance(
            preview.payload,
            XYPreviewPayload,
        ):
            raise TypeError("WellLocationPreview requires an XY well preview")
        if self._released:
            raise RuntimeError("cannot render a released WellLocationPreview")

        had_active_well = self.active_well is not None
        self._preview = preview
        self._payload = preview.payload
        self.active_well = None
        self.plot.setToolTip("")
        self.engine.render(self.plot, preview)
        self.well_search.clear()
        self._populate_well_list(preview.payload)
        self._update_filter_status()
        if had_active_well:
            self.active_well_changed.emit(None)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self.engine.release(self.plot)

    def reset_view(self) -> None:
        had_active_well = self.active_well is not None
        self.active_well = None
        self.plot.clear_selected_point()
        self.plot.reset_view()
        self.well_list.clearSelection()
        self.well_list.setCurrentItem(None)
        self._update_filter_status()
        if had_active_well:
            self.active_well_changed.emit(None)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.reset_view()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_hovered_well(
        self,
        _series_name: str,
        index: int,
        x: float,
        y: float,
    ) -> None:
        payload = self._payload
        if payload is None or index < 0 or index >= len(payload.names):
            self.plot.setToolTip("")
            return
        self.plot.setToolTip(
            f"{payload.names[index]}\nX {x:.3f}\nY {y:.3f}"
        )

    def _clear_hover_tooltip(self) -> None:
        self.plot.setToolTip("")

    def _populate_well_list(self, payload: XYPreviewPayload) -> None:
        duplicate_counts = Counter(payload.names)
        indexed_names = sorted(
            enumerate(payload.names),
            key=lambda item: _natural_name_key(item[1]),
        )
        self.well_list.clear()
        for point_index, name in indexed_names:
            label = name
            if duplicate_counts[name] > 1:
                record_id = (
                    payload.record_ids[point_index]
                    if point_index < len(payload.record_ids)
                    else point_index
                )
                label = f"{name} · 记录 {record_id}"
            item = QListWidgetItem(label)
            item.setData(_POINT_INDEX_ROLE, point_index)
            item.setData(_WELL_NAME_ROLE, name)
            self.well_list.addItem(item)

    def _filter_well_list(self, search_text: str) -> None:
        query = search_text.casefold()
        for row in range(self.well_list.count()):
            item = self.well_list.item(row)
            well_name = str(item.data(_WELL_NAME_ROLE))
            item.setHidden(query not in well_name.casefold())
        self._update_filter_status()

    def _activate_list_well(
        self,
        item: QListWidgetItem,
    ) -> None:
        preview = self._preview
        if preview is None:
            return
        point_index = int(item.data(_POINT_INDEX_ROLE))
        if (
            self.active_well is not None
            and self.active_well.point_index == point_index
        ):
            self.plot.focus_point(
                self.active_well.x,
                self.active_well.y,
                zoom_factor=4.0,
            )
            return
        self._activate_well(point_index, preview.title)

    def _activate_current_list_well(
        self,
        item: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if item is not None:
            self._activate_list_well(item)

    def _activate_clicked_well(
        self,
        series_name: str,
        index: int,
        _x: float,
        _y: float,
    ) -> None:
        self._activate_well(index, series_name)

    def _activate_well(self, index: int, series_name: str) -> None:
        preview = self._preview
        payload = self._payload
        if (
            preview is None
            or payload is None
            or index < 0
            or index >= len(payload.names)
        ):
            return
        active_well = ActiveWell(
            resource_id=payload.resource_id or preview.title,
            record_id=(
                payload.record_ids[index]
                if index < len(payload.record_ids)
                else index
            ),
            point_index=index,
            name=payload.names[index],
            x=float(payload.x[index]),
            y=float(payload.y[index]),
        )
        self.active_well = active_well
        self.plot.set_selected_point(
            series_name,
            index,
            label=active_well.name,
        )
        self.plot.focus_point(
            active_well.x,
            active_well.y,
            zoom_factor=4.0,
        )
        self._sync_list_selection(index)
        self._update_filter_status()
        self.active_well_changed.emit(active_well)

    def _sync_list_selection(self, point_index: int) -> None:
        item = self._list_item_for_point_index(point_index)
        if item is None:
            return
        blocker = QSignalBlocker(self.well_list)
        self.well_list.setCurrentItem(item)
        del blocker

    def _list_item_for_point_index(
        self,
        point_index: int,
    ) -> QListWidgetItem | None:
        for row in range(self.well_list.count()):
            item = self.well_list.item(row)
            if int(item.data(_POINT_INDEX_ROLE)) == point_index:
                return item
        return None

    def _update_filter_status(self) -> None:
        item = (
            self._list_item_for_point_index(self.active_well.point_index)
            if self.active_well is not None
            else None
        )
        if (
            self.active_well is None
            or item is None
            or not item.isHidden()
        ):
            self.filter_status.clear()
            self.filter_status.hide()
            return
        self.filter_status.setText(
            f"当前井 {self.active_well.name} 已被筛选隐藏，仍在图中高亮。"
        )
        self.filter_status.show()


def _natural_name_key(name: str) -> tuple[tuple[int, str | int], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", name.casefold())
    )


__all__ = ["ActiveWell", "WellLocationPreview"]
