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

from paleo_workbench.project.domain import (
    CoordinateStatus,
    coordinate_status_flag,
    crs_equivalent,
)
from paleo_workbench.ui import tokens

_WELL_ID_ROLE = Qt.ItemDataRole.UserRole + 1

_COLOR_OK = "#409cff"
_COLOR_FLAGGED = "#f59e0b"
_COLOR_SELECTED = "#e11d48"
_COLOR_BOUNDARY = "#64748b"
_COLOR_SURVEY = "#0d9488"
_COLOR_SPATIAL_CURSOR = "#7c3aed"


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


def _geometry_rings(geometry: dict[str, Any]) -> list[list[tuple[Any, Any]]]:
    """Extract drawable line rings from a GeoJSON geometry (project CRS)."""
    gtype = str(geometry.get("type", ""))
    coords = geometry.get("coordinates")
    if coords is None:
        return []
    if gtype == "Polygon":
        return [list(coords[0])] if coords else []
    if gtype == "MultiPolygon":
        return [list(polygon[0]) for polygon in coords if polygon]
    if gtype == "LineString":
        return [list(coords)]
    if gtype == "MultiLineString":
        return [list(line) for line in coords]
    return []  # Points carry no line work for this view


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
        self._ordered_labels: list[str] = []    # array index → display name
        self._engine = engine
        self._signature_cache: tuple | None = None
        # Cross-view spatial cursor (scenario B) — None until the engine plot
        # exists; the API degrades to a no-op instead of crashing.
        self._series_spatial_cursor = None
        self._spatial_cursor_xy: tuple[float, float] | None = None

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
        self.btn_reference = QPushButton("参考图层")
        self.btn_reference.setCheckable(True)
        self.btn_reference.setToolTip(
            "叠加编图工程中的矢量参考图层（GDAL 重投影到工程 CRS）；栅格图层无法在此视图渲染"
        )
        self.btn_reference.toggled.connect(lambda _on: self._render_all())
        self.btn_labels = QPushButton("井名标注")
        self.btn_labels.setCheckable(True)
        self.btn_labels.setChecked(True)
        self.btn_labels.setToolTip("在地图上显示井名标注")
        self.btn_labels.toggled.connect(lambda _on: self._apply_labels())
        for btn in (
            self.btn_zoom_all,
            self.btn_zoom_selection,
            self.btn_reset,
            self.btn_reference,
            self.btn_labels,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch(1)
        self.crs_label = QLabel("")
        self.crs_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        toolbar.addWidget(self.crs_label)
        # ⚠ banner for withheld overlays (CRS frames that don't match the
        # project) — skipping silently would hide a real problem (§20).
        self.crs_warning_label = QLabel("")
        self.crs_warning_label.setWordWrap(True)
        self.crs_warning_label.setStyleSheet(
            f"color: {tokens.WARNING}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        self.crs_warning_label.setVisible(False)
        center_layout.addWidget(self.crs_warning_label)
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

        self.empty_label = QLabel("暂无测区井。在数据页导入井位文件后自动识别；其他参考井在数据树中单独管理。")
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
        # Engine default is a dark chart theme; the workbench is light.
        plot.bg_color = QColor(tokens.BG_HEADER)
        plot.plot_bg_color = QColor("#f8fafc")
        plot.grid_color = QColor(tokens.BORDER)
        plot.axis_color = QColor(tokens.BORDER_STRONG)
        plot.text_color = QColor(tokens.TEXT_SECONDARY)
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
        self._series_reference = LineSeries(
            name="reference_layers",
            color=QColor(_COLOR_BOUNDARY),
            width=0.8,
        )
        # Cross-view spatial cursor (scenario B): one clearly-styled marker
        # moved by the coordination controller when a seismic pick happens.
        # Lives outside the well series so well selection never rebuilds it.
        self._series_spatial_cursor = ScatterSeries(
            name="spatial_cursor",
            color=QColor(_COLOR_SPATIAL_CURSOR),
            size=11.0,
        )
        self._spatial_cursor_xy: tuple[float, float] | None = None

        for series in (
            self._series_boundary,
            self._series_surveys,
            self._series_reference,
            self._series_wells,
            self._series_flagged,
            self._series_selected,
            self._series_spatial_cursor,
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
        from paleo_workbench.project.domain import domain_signature

        signature = domain_signature(project)
        if signature == self._signature_cache:
            return
        self._signature_cache = signature
        self.project = project
        self._rebuild_cache()
        self._render_all()

    def _rebuild_cache(self) -> None:
        from paleo_workbench.project.domain import is_reference_well

        all_wells = list(getattr(self.project, "wells", None) or []) if self.project else []
        # Reference wells remain governed project data but are deliberately
        # withheld from the WorkArea map and its autofit extent.
        wells = [well for well in all_wells if not is_reference_well(well)]
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
            flags.append(coordinate_status_flag(well.coordinate_status))
            px, py = well.project_x, well.project_y
            x, y = (px, py) if px is not None and py is not None else (well.surface_x, well.surface_y)
            if x is None or y is None or x != x or y != y:
                continue
            is_ok = (
                well.coordinate_status == CoordinateStatus.OK
                and px is not None
                and py is not None
            )
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
        self._ordered_labels = [names[row] for row in self._ordered_array_rows]

        self._list_model.set_rows(ids, names, flags)
        self.empty_label.setVisible(not wells)

    def _render_all(self) -> None:
        coordinate = getattr(self.project, "coordinate", None) if self.project else None
        crs = str(getattr(coordinate, "project_crs", "") or "")
        self.crs_label.setText(f"工程 CRS: {crs or '未设置'}")
        self._refresh_crs_warnings(crs)
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
        self._render_reference_layers()
        self._update_selected_series()
        self._apply_labels()
        self.plot.autofit()

    def _apply_labels(self) -> None:
        """Push per-point well-name labels into the scatter series."""
        if self._series_wells is None:
            return
        split = self._ok_count
        if self.btn_labels.isChecked():
            self._series_wells.labels = list(self._ordered_labels[:split])
            self._series_flagged.labels = list(self._ordered_labels[split:])
        else:
            self._series_wells.labels = None
            self._series_flagged.labels = None
        update = getattr(self.plot, "update", None)
        if callable(update):
            update()

    # Reference-layer geometry cap (§24): the map stays interactive; huge
    # cadastre files degrade to their first N vertices rather than freezing.
    MAX_REFERENCE_VERTICES = 20_000

    def _reference_layers(self) -> list[Any]:
        """Vector reference layers declared by the project's 编图 documents."""
        layers: dict[str, Any] = {}
        for document in getattr(self.project, "paleomap_documents", None) or []:
            for layer in getattr(document, "reference_layers", None) or []:
                if getattr(layer, "source_kind", "") != "vector":
                    continue
                layers.setdefault(str(getattr(layer, "id", "")), layer)
        return list(layers.values())

    def _render_reference_layers(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        self._reference_errors: list[str] = getattr(self, "_reference_errors", [])
        self._reference_errors.clear()
        enabled = self.btn_reference.isChecked()
        budget = self.MAX_REFERENCE_VERTICES
        if enabled and budget > 0:
            from paleo_workbench.mapping.reference_layers import (
                ReferenceLayerService,
            )

            service = ReferenceLayerService()
            for layer in self._reference_layers():
                if budget <= 0:
                    break
                try:
                    features, _extent = service.vector_render_payload(layer)
                except Exception as exc:  # noqa: BLE001 - view must not die
                    # Keep the reason inspectable (tests/diagnostics); the UI
                    # treats an unreadable layer as simply not drawn.
                    self._reference_errors.append(
                        f"{getattr(layer, 'name', layer)}: {exc.__class__.__name__}"
                    )
                    continue
                for feature in features:
                    if budget <= 0:
                        break
                    for ring in _geometry_rings(feature.get("geometry") or {}):
                        for x, y in ring:
                            if budget <= 0:
                                break
                            try:
                                xs.append(float(x))
                                ys.append(float(y))
                                budget -= 1
                            except (TypeError, ValueError):
                                continue
                        xs.append(np.nan)
                        ys.append(np.nan)
        self._series_reference.x = np.asarray(xs, dtype=np.float64)
        self._series_reference.y = np.asarray(ys, dtype=np.float64)
        self._series_reference.visible = enabled and bool(xs)

    def _refresh_crs_warnings(self, project_crs: str) -> None:
        """Surface (not hide) frames that don't match the project CRS.

        Mismatched survey/boundary overlays are withheld from the canvas —
        plotting incompatible coordinate systems together is never correct —
        but the withholding must be VISIBLE (§20), so every skipped frame
        becomes a ⚠ banner entry.
        """
        warnings: list[str] = []
        workarea = getattr(self.project, "workarea", None) if self.project else None
        boundary_crs = str(getattr(workarea, "boundary_crs", "") or "") if workarea else ""
        has_boundary = bool(getattr(workarea, "boundary", None)) if workarea else False
        if boundary_crs and has_boundary and not crs_equivalent(boundary_crs, project_crs):
            warnings.append(f"工区边界坐标系 {boundary_crs} 与工程不一致，未叠加")
        surveys = getattr(self.project, "seismic_surveys", None) if self.project else None
        for survey in surveys or []:
            survey_crs = str(getattr(survey, "crs", "") or "")
            if (
                survey_crs
                and getattr(survey, "extent", None)
                and not crs_equivalent(survey_crs, project_crs)
            ):
                warnings.append(
                    f"地震工区「{survey.name}」坐标系 {survey_crs} 与工程不一致，未叠加"
                )
        self.crs_warning_label.setText("⚠ " + "；".join(warnings) if warnings else "")
        self.crs_warning_label.setVisible(bool(warnings))

    def _render_boundary(self) -> None:
        points = []
        workarea = getattr(self.project, "workarea", None) if self.project else None
        boundary = list(getattr(workarea, "boundary", None) or []) if workarea else []
        # Only draw when the boundary frame matches the project frame —
        # never silently overlay incompatible coordinate systems (§20).
        boundary_crs = str(getattr(workarea, "boundary_crs", "") or "") if workarea else ""
        project_crs = str(
            getattr(getattr(self.project, "coordinate", None), "project_crs", "") or ""
        )
        frame_ok = (not boundary_crs) or crs_equivalent(boundary_crs, project_crs)
        if boundary and frame_ok:
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
        project_crs = str(
            getattr(getattr(self.project, "coordinate", None), "project_crs", "") or ""
        )
        for survey in surveys or []:
            survey_crs = str(getattr(survey, "crs", "") or "")
            # Survey corners live in the SURVEY frame; skip frames that don't
            # match the project instead of mis-aligning them silently.
            if survey_crs and not crs_equivalent(survey_crs, project_crs):
                continue
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

    # -- cross-view spatial cursor (scenario B) ------------------------

    def show_spatial_cursor(self, x: float, y: float) -> None:
        """Move the cross-view spatial cursor marker to map coordinates."""
        if self._series_spatial_cursor is None:
            return
        self._spatial_cursor_xy = (float(x), float(y))
        self._series_spatial_cursor.x = np.array([float(x)], dtype=np.float64)
        self._series_spatial_cursor.y = np.array([float(y)], dtype=np.float64)
        self.coord_label.setText(f"地震光标  X: {x:.2f}  Y: {y:.2f}")

    def clear_spatial_cursor(self) -> None:
        """Hide the spatial cursor marker (does not touch well selection)."""
        if self._series_spatial_cursor is None:
            return
        self._spatial_cursor_xy = None
        self._series_spatial_cursor.x = np.array([], dtype=np.float64)
        self._series_spatial_cursor.y = np.array([], dtype=np.float64)

    def spatial_cursor_position(self) -> tuple[float, float] | None:
        return self._spatial_cursor_xy

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
