"""Project-level Well Location GIS (工程井位地图).

A true spatial view fed by the WorkArea Well Registry — NOT the single-file
well_head XY preview.  One canonical coordinate model
(:class:`~paleo_workbench.project.domain.WellEntity`: source coords +
project-CRS projection) drives both this map and the Data Manager tree.

Performance contract (§24): wells render as ONE batched ScatterSeries per
status class; the well list is a model/view QListView; pan/wheel-zoom are
engine-level viewport operations that never rebuild the arrays.  50k wells
cost one numpy build per domain change and zero per-frame Python.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import (
    QAbstractListModel,
    QSortFilterProxyModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.domain import CoordinateStatus
from paleo_workbench.ui import tokens

_WELL_ID_ROLE = Qt.ItemDataRole.UserRole + 1

_COLOR_OK = "#409cff"
_COLOR_FLAGGED = "#f59e0b"
_COLOR_SELECTED = "#e11d48"
_COLOR_BOUNDARY = "#64748b"
_COLOR_SURVEY = "#0d9488"


class WellListModel(QAbstractListModel):
    """Flat name/status model over the registry (row order = registry order)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._names: list[str] = []
        self._flags: list[str] = []
        self._ids: list[str] = []

    def set_rows(self, ids: list[str], names: list[str], flags: list[str]) -> None:
        self.beginResetModel()
        self._ids, self._names, self._flags = ids, names, flags
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if not (0 <= row < len(self._ids)):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{self._names[row]}{self._flags[row]}"
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._names[row]
        if role == _WELL_ID_ROLE:
            return self._ids[row]
        return None

    def well_id_at(self, row: int) -> str | None:
        if 0 <= row < len(self._ids):
            return self._ids[row]
        return None

    def row_for_well(self, well_id: str) -> int | None:
        try:
            return self._ids.index(well_id)
        except ValueError:
            return None


class _WellFilterProxy(QSortFilterProxyModel):
    """Case-insensitive substring filter (same UX as the preview well list)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        needle = self.filterRegularExpression()
        if not needle.pattern():
            return True
        name = self.sourceModel().data(
            self.sourceModel().index(source_row, 0), Qt.ItemDataRole.DisplayRole
        )
        return bool(name and needle.match(str(name)).hasMatch())


class ProjectWellMapPage(QWidget):
    """工程井位地图: all project wells in the workarea CRS with full GIS UX."""

    # Map → Data: canonical Well.id of the clicked well.
    well_selected = Signal(str)
    # Double-click / Enter → locate the well in the Data Manager tree.
    well_activated = Signal(str)

    def __init__(self, parent=None, *, engine: Any | None = None):
        super().__init__(parent)
        self.setObjectName("ProjectWellMapPage")
        self.project = None
        # Array caches (rebuilt only when the registry changes):
        self._well_ids: list[str] = []          # registry order
        self._display_names: list[str] = []     # registry order
        self._array_rows: list[int] = []        # array index → registry row
        self._coord_x: np.ndarray = np.array([], dtype=np.float64)
        self._coord_y: np.ndarray = np.array([], dtype=np.float64)
        self._ok_count = 0                      # first `_ok_count` points are OK
        self._selected_well_ids: set[str] = set()
        self._engine = engine
        self._signature_cache: tuple | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(
            tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN
        )
        root.setSpacing(tokens.SPACE_3)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("WellMapSplitter")
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        # ---- left: search + model/view list ---------------------------
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(tokens.SPACE_2)
        self._list_model = WellListModel(self)
        self._proxy = _WellFilterProxy(self)
        self._proxy.setSourceModel(self._list_model)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索井名 / UWI…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._proxy.setFilterFixedString)
        side_layout.addWidget(self.search_box)
        self.well_list = QListView()
        self.well_list.setModel(self._proxy)
        self.well_list.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.well_list.setSelectionBehavior(QListView.SelectionBehavior.SelectRows)
        # 50k-well contract: uniform sizes + lazy layout keep the view O(1)
        # per interaction instead of laying out every row up front.
        self.well_list.setUniformItemSizes(True)
        self.well_list.selectionModel().selectionChanged.connect(
            self._on_list_selection_changed
        )
        self.well_list.doubleClicked.connect(
            lambda index: self._emit_activated(index)
        )
        side_layout.addWidget(self.well_list, 1)
        splitter.addWidget(side)

        # ---- center: toolbar + map canvas ------------------------------
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(tokens.SPACE_2)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(tokens.SPACE_2)
        self.btn_zoom_all = QPushButton("缩放全部")
        self.btn_zoom_selection = QPushButton("缩放选中")
        self.btn_reset = QPushButton("复位")
        for btn in (self.btn_zoom_all, self.btn_zoom_selection, self.btn_reset):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        self.crs_label = QLabel("")
        self.crs_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        toolbar.addWidget(self.crs_label)
        self.coord_label = QLabel("")
        self.coord_label.setMinimumWidth(220)
        self.coord_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.coord_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        toolbar.addWidget(self.coord_label)
        center_layout.addLayout(toolbar)

        self.plot = self._create_plot()
        if self.plot is not None:
            self.plot.point_hovered.connect(self._on_point_hovered)
            self.plot.point_clicked.connect(self._on_point_clicked)
            self.btn_zoom_all.clicked.connect(self.zoom_to_all)
            self.btn_reset.clicked.connect(self.plot.reset_view)
        else:
            from PySide6.QtWidgets import QLabel as _QLabel

            fallback = _QLabel("geo-viz-engine 不可用，无法渲染地图")
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.plot = fallback
        self.btn_zoom_selection.clicked.connect(self.zoom_to_selection)
        center_layout.addWidget(self.plot, 1)

        self.empty_label = QLabel("暂无井。在数据页导入井位文件后自动识别并显示。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        self.empty_label.setVisible(True)
        center_layout.addWidget(self.empty_label)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 760])

    # ------------------------------------------------------------------
    # engine / series setup
    # ------------------------------------------------------------------

    def _create_plot(self):
        try:
            from geoviz import GeoVizEngine, PreviewKind
            from geoviz_plots.chart.series import LineSeries, ScatterSeries
        except Exception:
            self._series_wells = None
            return None
        try:
            engine = self._engine or GeoVizEngine.default()
            plot = engine.create_widget(PreviewKind.XY_SCATTER, self)
        except Exception:
            self._series_wells = None
            return None
        plot.set_equal_aspect(True)
        self._series_wells = ScatterSeries(name="wells", color=QColor(_COLOR_OK), size=6.0)
        self._series_flagged = ScatterSeries(
            name="wells_flagged", color=QColor(_COLOR_FLAGGED), size=6.0
        )
        self._series_selected = ScatterSeries(
            name="wells_selected", color=QColor(_COLOR_SELECTED), size=9.0
        )
        self._series_boundary = LineSeries(
            name="boundary",
            color=QColor(_COLOR_BOUNDARY),
            width=1.2,
            style=Qt.PenStyle.DashLine,
        )
        self._series_surveys = LineSeries(
            name="survey_extents",
            color=QColor(_COLOR_SURVEY),
            width=1.0,
            style=Qt.PenStyle.DotLine,
        )
        for series in (
            self._series_boundary,
            self._series_surveys,
            self._series_wells,
            self._series_flagged,
            self._series_selected,
        ):
            plot.add_series(series)
        return plot

    # ------------------------------------------------------------------
    # data binding
    # ------------------------------------------------------------------

    def set_project(self, project: Any) -> None:
        """Rebind to the WorkArea document."""
        self.project = project
        self.refresh_domain(project)

    def refresh_domain(self, project: Any) -> None:
        """Domain entities changed → rebuild cached arrays + series."""
        signature = self._signature(project)
        if signature == self._signature_cache:
            return
        self._signature_cache = signature
        self.project = project
        self._rebuild_cache()
        self._render_all()

    @staticmethod
    def _signature(project: Any) -> tuple:
        wells = getattr(project, "wells", None) or []
        surveys = getattr(project, "seismic_surveys", None) or []
        workarea = getattr(project, "workarea", None)
        return (
            len(wells),
            tuple((w.id, w.name, w.coordinate_status, w.project_x, w.project_y) for w in wells),
            tuple(s.id for s in surveys),
            str(getattr(getattr(project, "coordinate", None), "project_crs", "")),
            bool(getattr(workarea, "boundary", None)),
        )

    def _rebuild_cache(self) -> None:
        wells = list(getattr(self.project, "wells", None) or []) if self.project else []
        ids: list[str] = []
        names: list[str] = []
        flags: list[str] = []
        ok_x: list[float] = []
        ok_y: list[float] = []
        flagged_x: list[float] = []
        flagged_y: list[float] = []
        array_rows: list[int] = []
        ok_flagged_split_marker: list[bool] = []

        for reg_row, well in enumerate(wells):
            ids.append(well.id)
            names.append(well.name or "(未命名井)")
            status = well.coordinate_status
            if status == CoordinateStatus.UNTRANSFORMED:
                flags.append(" ⚠坐标未转换")
            elif status == CoordinateStatus.INVALID:
                flags.append(" ⚠坐标无效")
            elif status == CoordinateStatus.MISSING:
                flags.append(" ⚠无坐标")
            else:
                flags.append("")
            px, py = well.project_x, well.project_y
            x, y = (px, py) if px is not None and py is not None else (well.surface_x, well.surface_y)
            if x is None or y is None or x != x or y != y:
                continue
            is_ok = status == CoordinateStatus.OK and px is not None and py is not None
            if is_ok:
                ok_x.append(float(x))
                ok_y.append(float(y))
            else:
                flagged_x.append(float(x))
                flagged_y.append(float(y))
            ok_flagged_split_marker.append(is_ok)
            array_rows.append(reg_row)

        self._well_ids = ids
        self._display_names = names
        self._array_rows = array_rows
        # Stable layout: OK block first, then flagged block.
        ok_indices = [i for i, ok in enumerate(ok_flagged_split_marker) if ok]
        flagged_indices = [i for i, ok in enumerate(ok_flagged_split_marker) if not ok]
        ordered = ok_indices + flagged_indices
        all_x = ok_x + flagged_x
        all_y = ok_y + flagged_y
        self._coord_x = np.asarray([all_x[i] for i in ordered], dtype=np.float64)
        self._coord_y = np.asarray([all_y[i] for i in ordered], dtype=np.float64)
        self._ok_count = len(ok_indices)
        self._ordered_array_rows = [array_rows[i] for i in ordered]
        self._row_to_array = {
            reg_row: arr_idx for arr_idx, reg_row in enumerate(self._ordered_array_rows)
        }
        self._flagged_array_set = frozenset(range(self._ok_count, len(ordered)))

        self._list_model.set_rows(ids, names, flags)
        self.empty_label.setVisible(not wells)

    def _render_all(self) -> None:
        coordinate = getattr(self.project, "coordinate", None) if self.project else None
        crs = str(getattr(coordinate, "project_crs", "") or "")
        self.crs_label.setText(f"工程 CRS: {crs or '未设置'}")
        if self.plot is None or self._series_wells is None:
            return
        split = self._ok_count
        total = len(self._coord_x)
        self._series_wells.x = self._coord_x[:split]
        self._series_wells.y = self._coord_y[:split]
        self._series_flagged.x = self._coord_x[split:total]
        self._series_flagged.y = self._coord_y[split:total]
        self._render_boundary()
        self._render_survey_extents()
        self._update_selected_series()
        self.plot.autofit()

    def _render_boundary(self) -> None:
        points = []
        workarea = getattr(self.project, "workarea", None) if self.project else None
        boundary = list(getattr(workarea, "boundary", None) or []) if workarea else []
        for point in boundary:
            try:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
        if len(points) > 1 and points[0] != points[-1]:
            points.append(points[0])
        self._series_boundary.x = np.asarray([p[0] for p in points], dtype=np.float64)
        self._series_boundary.y = np.asarray([p[1] for p in points], dtype=np.float64)
        self._series_boundary.visible = bool(points)

    def _render_survey_extents(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        surveys = getattr(self.project, "seismic_surveys", None) if self.project else None
        for survey in surveys or []:
            corners = []
            for corner in getattr(survey, "extent", None) or []:
                try:
                    if len(corner) >= 2:
                        corners.append((float(corner[0]), float(corner[1])))
                except (TypeError, ValueError):
                    continue
            if len(corners) >= 3:
                if corners[0] != corners[-1]:
                    corners.append(corners[0])
                xs.extend([c[0] for c in corners])
                ys.extend([c[1] for c in corners])
                xs.append(np.nan)
                ys.append(np.nan)
        self._series_surveys.x = np.asarray(xs, dtype=np.float64)
        self._series_surveys.y = np.asarray(ys, dtype=np.float64)
        self._series_surveys.visible = bool(xs)

    def _update_selected_series(self) -> None:
        array_indices = sorted(
            self._row_to_array[row]
            for wid in self._selected_well_ids
            if (row := self._list_model.row_for_well(wid)) is not None
            and row in self._row_to_array
        )
        if array_indices and len(self._coord_x):
            idx = np.asarray(array_indices, dtype=np.intp)
            self._series_selected.x = self._coord_x[idx]
            self._series_selected.y = self._coord_y[idx]
        elif self._series_selected is not None:
            self._series_selected.x = np.array([], dtype=np.float64)
            self._series_selected.y = np.array([], dtype=np.float64)

    # ------------------------------------------------------------------
    # interactions
    # ------------------------------------------------------------------

    def _on_point_hovered(self, series_name: str, index: int, x: float, y: float) -> None:
        well_id = self._well_id_for(series_name, index)
        name = self._display_name_for(series_name, index)
        suffix = ""
        if series_name == "wells_flagged":
            suffix = "（源坐标显示）"
        self.coord_label.setText(f"{name}  X: {x:.2f}  Y: {y:.2f}{suffix}")
        if well_id is not None:
            self.well_list.setToolTip(f"{name}\nX: {x:.2f}\nY: {y:.2f}")

    def _on_point_clicked(self, series_name: str, index: int, x: float, y: float) -> None:
        well_id = self._well_id_for(series_name, index)
        if well_id is None:
            return
        self.select_well(well_id, zoom=False, emit=True)

    def _well_id_for(self, series_name: str, index: int) -> str | None:
        offset = self._ok_count if series_name == "wells_flagged" else 0
        if series_name not in ("wells", "wells_flagged"):
            return None
        array_idx = offset + index
        if 0 <= array_idx < len(self._ordered_array_rows):
            reg_row = self._ordered_array_rows[array_idx]
            if 0 <= reg_row < len(self._well_ids):
                return self._well_ids[reg_row]
        return None

    def _display_name_for(self, series_name: str, index: int) -> str:
        offset = self._ok_count if series_name == "wells_flagged" else 0
        array_idx = offset + index
        if 0 <= array_idx < len(self._ordered_array_rows):
            reg_row = self._ordered_array_rows[array_idx]
            if 0 <= reg_row < len(self._display_names):
                return self._display_names[reg_row]
        return ""

    def _emit_activated(self, proxy_index) -> None:
        source_index = self._proxy.mapToSource(proxy_index)
        well_id = self._list_model.data(source_index, _WELL_ID_ROLE)
        if well_id:
            self.well_activated.emit(str(well_id))

    # -- selection -----------------------------------------------------

    def select_well(self, well_id: str, *, zoom: bool = False, emit: bool = False) -> None:
        """Single-select a well (map highlight + optional focus)."""
        self.select_wells([well_id], zoom=zoom, emit_single=emit)

    def select_wells(
        self, well_ids: list[str], *, zoom: bool = False, emit_single: bool = False
    ) -> None:
        self._selected_well_ids = {wid for wid in well_ids if self._list_model.row_for_well(wid) is not None}
        self._sync_list_selection()
        self._update_selected_series()
        if emit_single and len(self._selected_well_ids) == 1:
            self.well_selected.emit(next(iter(self._selected_well_ids)))
        if zoom:
            self.zoom_to_selection()

    def selected_well_ids(self) -> list[str]:
        return sorted(self._selected_well_ids)

    def clear_selection(self) -> None:
        self._selected_well_ids.clear()
        self._sync_list_selection()
        self._update_selected_series()

    def _sync_list_selection(self) -> None:
        selection = self.well_list.selectionModel()
        if selection is None:
            return
        selection.selectionChanged.disconnect(self._on_list_selection_changed)
        try:
            from PySide6.QtCore import QItemSelection, QItemSelectionModel

            new_selection = QItemSelection()
            first_proxy_index = None
            for wid in sorted(self._selected_well_ids):
                row = self._list_model.row_for_well(wid)
                if row is None:
                    continue
                proxy_index = self._proxy.mapFromSource(self._list_model.index(row, 0))
                if proxy_index.isValid():
                    new_selection.select(proxy_index, proxy_index)
                    if first_proxy_index is None:
                        first_proxy_index = proxy_index
            selection.select(
                new_selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
            if first_proxy_index is not None:
                from PySide6.QtWidgets import QAbstractItemView  # noqa: PLC0415

                self.well_list.scrollTo(
                    first_proxy_index, QAbstractItemView.ScrollHint.EnsureVisible
                )
        finally:
            selection.selectionChanged.connect(self._on_list_selection_changed)

    def _on_list_selection_changed(self, *_args) -> None:
        selected_ids: list[str] = []
        for proxy_index in self.well_list.selectedIndexes():
            source_index = self._proxy.mapToSource(proxy_index)
            well_id = self._list_model.data(source_index, _WELL_ID_ROLE)
            if well_id:
                selected_ids.append(str(well_id))
        if not selected_ids:
            return
        self._selected_well_ids = set(selected_ids)
        self._update_selected_series()
        if len(selected_ids) == 1:
            self.well_selected.emit(selected_ids[0])

    # -- zoom helpers ---------------------------------------------------

    def zoom_to_well(self, well_id: str, *, zoom_factor: float = 8.0) -> None:
        row = self._list_model.row_for_well(well_id)
        if row is None or not len(self._coord_x) or not hasattr(self.plot, "focus_point"):
            return
        array_idx = self._row_to_array.get(row)
        if array_idx is None:
            return
        x = float(self._coord_x[array_idx])
        y = float(self._coord_y[array_idx])
        self.plot.focus_point(x, y, zoom_factor=zoom_factor)

    def zoom_to_selection(self) -> None:
        indices = [
            self._row_to_array[row]
            for wid in self._selected_well_ids
            if (row := self._list_model.row_for_well(wid)) is not None
            and row in self._row_to_array
        ]
        if not indices:
            return
        idx = np.asarray(sorted(indices), dtype=np.intp)
        self._set_bounds(self._coord_x[idx], self._coord_y[idx])

    def zoom_to_all(self) -> None:
        if hasattr(self.plot, "autofit"):
            self.plot.autofit()

    def focus_well(self, well_id: str) -> None:
        """Data → Map entry point: highlight + center on the well."""
        self.select_well(well_id)
        self.zoom_to_well(well_id)

    def _set_bounds(self, xs: np.ndarray, ys: np.ndarray, margin_ratio: float = 0.15) -> None:
        if not hasattr(self.plot, "set_view_bounds"):
            return
        finite = np.isfinite(xs) & np.isfinite(ys)
        if not finite.any():
            return
        xmin, xmax = float(xs[finite].min()), float(xs[finite].max())
        ymin, ymax = float(ys[finite].min()), float(ys[finite].max())
        dx = max(xmax - xmin, abs(xmin) * 1e-3, 1e-6) * margin_ratio
        dy = max(ymax - ymin, abs(ymin) * 1e-3, 1e-6) * margin_ratio
        self.plot.set_view_bounds(xmin - dx, xmax + dx, ymin - dy, ymax + dy)
