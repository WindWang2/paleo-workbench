from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QSignalBlocker,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QToolButton,
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
_METADATA_PROVENANCE_LABELS = {
    "asset": "资产",
    "file": "文件",
    "asset+file": "资产与文件",
}


@dataclass(frozen=True)
class _WellListEntry:
    point_index: int
    name: str
    label: str


class _WellListModel(QAbstractListModel):
    """Lightweight rows; QListView creates delegates only for visible wells."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: tuple[_WellListEntry, ...] = ()
        self._row_by_point_index: dict[int, int] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return entry.label
        if role == _POINT_INDEX_ROLE:
            return entry.point_index
        if role == _WELL_NAME_ROLE:
            return entry.name
        return None

    def set_payload(self, payload: XYPreviewPayload) -> None:
        duplicate_counts = Counter(payload.names)
        coordinate_counts = Counter(
            (
                name,
                float(payload.x[index]),
                float(payload.y[index]),
            )
            for index, name in enumerate(payload.names)
        )
        entries = []
        for point_index, name in enumerate(payload.names):
            label = _well_list_label(
                payload,
                point_index,
                name,
                duplicate_counts[name],
                coordinate_counts[
                    (
                        name,
                        float(payload.x[point_index]),
                        float(payload.y[point_index]),
                    )
                ],
            )
            entries.append(_WellListEntry(point_index, name, label))
        entries.sort(key=lambda entry: _natural_name_key(entry.name))
        self.beginResetModel()
        self._entries = tuple(entries)
        self._row_by_point_index = {
            entry.point_index: row
            for row, entry in enumerate(self._entries)
        }
        self.endResetModel()

    def index_for_point(self, point_index: int) -> QModelIndex:
        row = self._row_by_point_index.get(point_index)
        return QModelIndex() if row is None else self.index(row, 0)


class _WellFilterProxyModel(QSortFilterProxyModel):
    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex,
    ) -> bool:
        source = self.sourceModel()
        if source is None:
            return False
        name = source.data(
            source.index(source_row, 0, source_parent),
            _WELL_NAME_ROLE,
        )
        return self.filterRegularExpression().match(str(name)).hasMatch()


@dataclass(frozen=True)
class WellLocationId:
    """Stable identity for one source record in one asset version."""

    resource_id: str
    source_version: str
    record_id: int


@dataclass(frozen=True)
class ActiveWell:
    """The selected well record for the lifetime of one prepared preview."""

    identity: WellLocationId
    point_index: int
    source_row: int | None
    name: str
    x: float
    y: float

    @property
    def resource_id(self) -> str:
        return self.identity.resource_id

    @property
    def record_id(self) -> int:
        return self.identity.record_id


@dataclass(frozen=True)
class WellLocationPreviewState:
    active_well_id: WellLocationId | None = None
    search_text: str = ""
    list_scroll_position: int = 0
    viewport: tuple[float, float, float, float] | None = None


class WellLocationPreviewStateStore:
    """Session state keyed by resource and immutable source version."""

    def __init__(self) -> None:
        self._states: dict[
            tuple[str, str], WellLocationPreviewState
        ] = {}
        self._active_versions: dict[str, str] = {}

    def activate_version(self, resource_id: str, source_version: str) -> None:
        """Make one immutable source version authoritative for an asset.

        A temporary widget for an older preview can finish after a newer
        version rendered. Its later save must not resurrect stale identity or
        viewport state, so only rendering a version may advance this boundary.
        """
        previous = self._active_versions.get(resource_id)
        if previous == source_version:
            return
        self._states = {
            key: state
            for key, state in self._states.items()
            if key[0] != resource_id
        }
        self._active_versions[resource_id] = source_version

    def load(
        self,
        resource_id: str,
        source_version: str,
    ) -> WellLocationPreviewState | None:
        if self._active_versions.get(resource_id) != source_version:
            return None
        return self._states.get((resource_id, source_version))

    def save(
        self,
        resource_id: str,
        source_version: str,
        state: WellLocationPreviewState,
    ) -> None:
        if resource_id not in self._active_versions:
            self.activate_version(resource_id, source_version)
        if self._active_versions.get(resource_id) != source_version:
            return
        self._states[(resource_id, source_version)] = state

    def clear(self) -> None:
        self._states.clear()
        self._active_versions.clear()


class WellLocationPreview(QWidget):
    """Workbench-owned well-location interaction around a generic XY plot."""

    active_well_changed = Signal(object)

    def __init__(
        self,
        engine: GeoVizEngine | None = None,
        parent: QWidget | None = None,
        *,
        state_store: WellLocationPreviewStateStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine or GeoVizEngine.default()
        plot = self.engine.create_widget(PreviewKind.XY_SCATTER, self)
        if not isinstance(plot, PlotWidget):
            raise TypeError("XY scatter backend must create a PlotWidget")
        self.plot = plot
        self._state_changes_suspended = False
        self.plot.set_equal_aspect(True)
        self.plot.point_hovered.connect(self._show_hovered_well)
        self.plot.point_hover_cleared.connect(self._clear_hover_tooltip)
        self.plot.point_clicked.connect(self._activate_clicked_well)
        self.plot.reset_requested.connect(self.reset_view)
        self.plot.view_changed.connect(
            lambda *_bounds: self._save_state()
        )

        self.well_panel = QFrame(self)
        self.well_panel.setObjectName("WellLocationListPanel")
        self.well_panel.setFixedWidth(240)
        panel_layout = QVBoxLayout(self.well_panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)
        panel_title = QLabel("井名", self.well_panel)
        panel_title.setObjectName("MapDockTitle")
        panel_layout.addWidget(panel_title)
        self.source_status = QLabel(self.well_panel)
        self.source_status.setAccessibleName("井位源坐标与解析诊断")
        self.source_status.setWordWrap(True)
        self.source_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        panel_layout.addWidget(self.source_status)
        self.diagnostic_toggle = QToolButton(self.well_panel)
        self.diagnostic_toggle.setObjectName("WellLocationDiagnosticToggle")
        self.diagnostic_toggle.setAccessibleName("展开井位行级诊断")
        self.diagnostic_toggle.setCheckable(True)
        self.diagnostic_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.diagnostic_toggle.toggled.connect(
            self._set_diagnostic_details_visible
        )
        self.diagnostic_toggle.hide()
        panel_layout.addWidget(self.diagnostic_toggle)
        self.diagnostic_details = QLabel(self.well_panel)
        self.diagnostic_details.setAccessibleName("井位行级诊断详情")
        self.diagnostic_details.setWordWrap(True)
        self.diagnostic_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.diagnostic_details.hide()
        panel_layout.addWidget(self.diagnostic_details)
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
        self.well_list = QListView(self.well_panel)
        self.well_list.setAccessibleName("井名列表")
        self.well_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._well_model = _WellListModel(self.well_list)
        self._well_filter = _WellFilterProxyModel(self.well_list)
        self._well_filter.setSourceModel(self._well_model)
        self._well_filter.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive
        )
        self.well_list.setModel(self._well_filter)
        self.well_list.selectionModel().currentChanged.connect(
            self._activate_current_list_well
        )
        self.well_list.clicked.connect(self._activate_list_well)
        self.well_list.activated.connect(self._activate_list_well)
        self.well_list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._save_state()
        )
        panel_layout.addWidget(self.well_list, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.well_panel)

        self.setFocusPolicy(Qt.StrongFocus)
        self._preview: PreparedPreview | None = None
        self._payload: XYPreviewPayload | None = None
        self._state_store = state_store or WellLocationPreviewStateStore()
        self.active_well: ActiveWell | None = None
        self._released = False
        self._scroll_restore_timer: QTimer | None = None

    def render(self, preview: PreparedPreview) -> None:
        if preview.kind is not PreviewKind.XY_SCATTER or not isinstance(
            preview.payload,
            XYPreviewPayload,
        ):
            raise TypeError("WellLocationPreview requires an XY well preview")
        if self._released:
            raise RuntimeError("cannot render a released WellLocationPreview")

        self._save_state()
        self._state_changes_suspended = True
        try:
            self._preview = preview
            self._payload = preview.payload
            if (
                preview.payload.resource_id
                and preview.payload.source_version
            ):
                self._state_store.activate_version(
                    preview.payload.resource_id,
                    preview.payload.source_version,
                )
            self.active_well = None
            self.plot.setToolTip("")
            self.engine.render(self.plot, preview)
            self._populate_well_list(preview.payload)
            self._update_source_status(preview.payload)
            self._restore_state()
            self._update_filter_status()
        finally:
            self._state_changes_suspended = False
        self._save_state()

    def release(self) -> None:
        if self._released:
            return
        self._save_state()
        self._released = True
        if self._scroll_restore_timer is not None:
            self._scroll_restore_timer.stop()
            self._scroll_restore_timer = None
        self.engine.release(self.plot)

    def reset_view(self) -> None:
        had_active_well = self.active_well is not None
        self.active_well = None
        self.plot.clear_selected_point()
        self.plot.reset_view()
        self.well_list.clearSelection()
        self.well_list.setCurrentIndex(QModelIndex())
        self._update_filter_status()
        self._save_state()
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
        self._well_model.set_payload(payload)

    def _update_source_status(self, payload: XYPreviewPayload) -> None:
        diagnostics = payload.diagnostics
        status = payload.coordinate_status
        total_records = diagnostics.total_records or len(payload.names)
        valid_records = diagnostics.valid_records or len(payload.names)
        skipped_count = max(0, total_records - valid_records)
        crs_provenance = _METADATA_PROVENANCE_LABELS.get(
            status.source_crs_provenance,
            "",
        )
        unit_provenance = _METADATA_PROVENANCE_LABELS.get(
            status.coordinate_units_provenance,
            "",
        )
        lines = [
            " · ".join(
                (
                    (
                        f"SourceCRS: {payload.source_crs or '未声明'}"
                        f"（{crs_provenance}）"
                        if crs_provenance
                        else f"SourceCRS: {payload.source_crs or '未声明'}"
                    ),
                    (
                        f"坐标单位: {payload.coordinate_units or '未知'}"
                        f"（{unit_provenance}）"
                        if unit_provenance
                        else f"坐标单位: {payload.coordinate_units or '未知'}"
                    ),
                )
            ),
            (
                f"有效 {valid_records}/"
                f"{total_records}，"
                f"跳过 {skipped_count}"
            ),
        ]
        if total_records and valid_records / total_records <= 0.1:
            lines.append(
                "严重数据质量问题：可预览井位比例极低，请核对源文件。"
            )
        duplicate_group_count = sum(
            count > 1 for count in Counter(payload.names).values()
        )
        if duplicate_group_count:
            lines.append(
                f"{duplicate_group_count} 个重名井名组，"
                "已用 X/Y 或源行消歧。"
            )
        self.source_status.setText("\n".join(lines))

        detail_lines = [
            f"源行 {issue.source_row}: {issue.reason}"
            for issue in diagnostics.issues
        ]
        if diagnostics.omitted_issue_count:
            detail_lines.append(
                f"另有 {diagnostics.omitted_issue_count} 条诊断未展开"
            )
        self.diagnostic_details.setText("\n".join(detail_lines))
        has_details = bool(detail_lines)
        self.diagnostic_toggle.setVisible(has_details)
        if not has_details:
            self.diagnostic_toggle.setChecked(False)
            self.diagnostic_details.hide()
            return
        self.diagnostic_toggle.setText(
            f"查看 {len(diagnostics.issues)} 条行级诊断"
        )
        self._set_diagnostic_details_visible(
            self.diagnostic_toggle.isChecked()
        )

    def _set_diagnostic_details_visible(self, visible: bool) -> None:
        self.diagnostic_details.setVisible(
            visible and self.diagnostic_toggle.isVisible()
        )

    def _filter_well_list(self, search_text: str) -> None:
        blocker = QSignalBlocker(self.well_list.selectionModel())
        self._well_filter.setFilterFixedString(search_text)
        if self.active_well is not None:
            active_index = self._list_index_for_point_index(
                self.active_well.point_index
            )
            self.well_list.setCurrentIndex(active_index)
            if not active_index.isValid():
                self.well_list.clearSelection()
        del blocker
        self._update_filter_status()
        self._save_state()

    def _activate_list_well(
        self,
        index: QModelIndex,
    ) -> None:
        preview = self._preview
        if preview is None or not index.isValid():
            return
        point_index = int(index.data(_POINT_INDEX_ROLE))
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
        index: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        if index.isValid():
            self._activate_list_well(index)

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
            identity=WellLocationId(
                resource_id=payload.resource_id,
                source_version=payload.source_version,
                record_id=(
                    payload.record_ids[index]
                    if index < len(payload.record_ids)
                    else index
                ),
            ),
            point_index=index,
            source_row=(
                payload.source_rows[index]
                if index < len(payload.source_rows)
                else None
            ),
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
        self._save_state()
        self.active_well_changed.emit(active_well)

    def _save_state(self) -> None:
        if self._state_changes_suspended:
            return
        payload = self._payload
        if (
            payload is None
            or not payload.resource_id
            or not payload.source_version
        ):
            return
        self._state_store.save(
            payload.resource_id,
            payload.source_version,
            WellLocationPreviewState(
                active_well_id=(
                    self.active_well.identity
                    if self.active_well is not None
                    else None
                ),
                search_text=self.well_search.text(),
                list_scroll_position=(
                    self.well_list.verticalScrollBar().value()
                ),
                viewport=self.plot.view_bounds(),
            ),
        )

    def _restore_state(self) -> None:
        payload = self._payload
        if (
            payload is None
            or not payload.resource_id
            or not payload.source_version
        ):
            self.well_search.clear()
            return
        state = self._state_store.load(
            payload.resource_id,
            payload.source_version,
        )
        if state is None:
            self.well_search.clear()
            return
        self.well_search.setText(state.search_text)
        identity = state.active_well_id
        if identity is not None:
            try:
                point_index = payload.record_ids.index(identity.record_id)
            except ValueError:
                point_index = -1
            if point_index >= 0:
                assert self._preview is not None
                self._activate_well(point_index, self._preview.title)
        if state.viewport is not None:
            self.plot.set_view_bounds(state.viewport)
        resource_id = payload.resource_id
        source_version = payload.source_version
        if self._scroll_restore_timer is not None:
            self._scroll_restore_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda: self._restore_list_scroll(
                resource_id,
                source_version,
                state.list_scroll_position,
            )
        )
        self._scroll_restore_timer = timer
        timer.start(0)

    def _restore_list_scroll(
        self,
        resource_id: str,
        source_version: str,
        position: int,
    ) -> None:
        self._scroll_restore_timer = None
        payload = self._payload
        if (
            self._released
            or payload is None
            or payload.resource_id != resource_id
            or payload.source_version != source_version
        ):
            return
        self.well_list.verticalScrollBar().setValue(position)

    def _sync_list_selection(self, point_index: int) -> None:
        index = self._list_index_for_point_index(point_index)
        if not index.isValid():
            return
        blocker = QSignalBlocker(self.well_list)
        self.well_list.setCurrentIndex(index)
        self.well_list.scrollTo(
            index,
            QAbstractItemView.ScrollHint.EnsureVisible,
        )
        del blocker

    def _list_index_for_point_index(
        self,
        point_index: int,
    ) -> QModelIndex:
        return self._well_filter.mapFromSource(
            self._well_model.index_for_point(point_index)
        )

    def _update_filter_status(self) -> None:
        index = (
            self._list_index_for_point_index(self.active_well.point_index)
            if self.active_well is not None
            else QModelIndex()
        )
        if self.active_well is None or index.isValid():
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


def _well_list_label(
    payload: XYPreviewPayload,
    point_index: int,
    name: str,
    duplicate_count: int,
    coordinate_count: int,
) -> str:
    if duplicate_count <= 1:
        return name
    x = float(payload.x[point_index])
    y = float(payload.y[point_index])
    if coordinate_count == 1:
        return f"{name} · X {x:g}, Y {y:g}"
    source_row = (
        payload.source_rows[point_index]
        if point_index < len(payload.source_rows)
        else point_index + 1
    )
    return f"{name} · 源行 {source_row}"


__all__ = [
    "ActiveWell",
    "WellLocationId",
    "WellLocationPreview",
    "WellLocationPreviewState",
    "WellLocationPreviewStateStore",
]
