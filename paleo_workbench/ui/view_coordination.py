"""View coordination: SelectionContext routing for the running UI (#1029).

``SelectionContext`` and ``CoordinateTransformHub`` existed as engines but
were never wired into the application — pages synced through ad-hoc
``page.well_selected → other_page.slot`` point-to-point connections. This
controller is the single mediation point:

* pages (or their legacy signals) PUBLISH domain selections with a source
  tag; the controller SUBSCRIBES views to :class:`SelectionContext` events
  and routes them, skipping the publishing view so selections never echo;
* the seismic cursor route resolves (IL, XL, TWT) through the
  :class:`CoordinateTransformHub` to the nearest well and its MD before
  reaching the well-log page.

No page ever connects directly to another page for selection sync anymore.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
from paleo_workbench.viz.selection_context import SelectionContext

logger = logging.getLogger(__name__)


def _survey_axis_range(values) -> tuple[float | None, float | None, float | None]:
    """Parse a survey ``[start, stop, step]`` axis range, Nones when unusable."""
    try:
        start, stop, step = float(values[0]), float(values[1]), float(values[2])
    except (TypeError, ValueError, IndexError):
        return None, None, None
    if step == 0.0:
        return None, None, None
    return start, stop, step


class ViewCoordinationController(QObject):
    """Route SelectionContext events into the live pages (#1029)."""

    SOURCE_MAP = "project_well_map"
    SOURCE_3D = "geomodel_3d"
    SOURCE_WELL_LOG = "well_log_prediction"
    SOURCE_SEISMIC = "seismic_cursor"

    def __init__(
        self,
        selection_context: SelectionContext,
        coordinate_hub: CoordinateTransformHub,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.selection_context = selection_context
        self.coordinate_hub = coordinate_hub
        self._shell = None
        self._well_log_page = None
        self._last_snapshot = None
        self._bound_well_ids: set[str] = set()
        selection_context.selection_changed.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Project lifecycle (well registry / seismic geometry)
    # ------------------------------------------------------------------

    def bind_project(self, project) -> None:
        """Register the open project's wells and seismic geometry (#1029).

        Called when a project document is opened or switched. Re-binding is a
        full replacement: the previous project's wells are unregistered first
        so no well ever leaks across projects.
        """
        self.clear_project()
        for well in list(getattr(project, "wells", None) or []):
            self._register_project_well(well)
        survey = self._first_seismic_survey(project)
        if survey is not None:
            self._configure_hub_seismic_geometry(survey)
        logger.debug(
            "bind_project: registered %d well(s) into the coordinate hub",
            len(self._bound_well_ids),
        )

    def clear_project(self) -> None:
        """Unregister every project-bound well and reset the seismic grid.

        The seismic grid is restored to hub defaults as well — geometry from
        a previous project is just as much cross-project residue as wells.
        """
        self._bound_well_ids.clear()
        removed = self.coordinate_hub.clear_all_wells()
        try:
            self.coordinate_hub.configure_seismic_grid()
        except Exception:  # pragma: no cover - defaults are always valid
            logger.debug("clear_project: grid reset failed", exc_info=True)
        if removed:
            logger.debug("clear_project: unregistered %d well(s)", removed)

    def _register_project_well(self, well) -> None:
        """Register one ``WellEntity`` (surface coords, KB, TD, optional stations).

        The cross-view selection key is the well NAME (map/3D/well-log pages
        all publish names); the entity id stays internal to the project store.
        Projected coordinates win over raw source coordinates; wells without
        any usable pair are skipped (flagged in debug, never fabricated).
        """
        well_id = str(getattr(well, "name", "") or "").strip()
        x = getattr(well, "project_x", None)
        y = getattr(well, "project_y", None)
        if x is None or y is None:
            x = getattr(well, "surface_x", None)
            y = getattr(well, "surface_y", None)
        if x is None or y is None:
            logger.debug(
                "bind_project: well %r has no usable coordinates; skipped", well_id
            )
            return
        kb = float(getattr(well, "kb", None) or 0.0)
        td = float(getattr(well, "td", None) or 0.0)
        stations = self._well_survey_stations(well)
        try:
            self.coordinate_hub.register_well(
                well_id,
                float(x),
                float(y),
                elevation=kb,
                total_depth_m=td,
                stations=stations,
            )
        except Exception:
            logger.debug(
                "bind_project: registering well %r failed", well_id, exc_info=True
            )
            return
        self._bound_well_ids.add(well_id)

    @staticmethod
    def _well_survey_stations(well) -> list[tuple[float, float, float]] | None:
        """Optional (MD, inc, az) survey stations for deviated wells.

        ``ProjectDocument`` has no first-class trajectory model yet (the
        ``trajectory`` asset role exists but no loader binds it to wells);
        stations are read leniently from ``well.metadata["survey_stations"]``
        so a deviated well registers its real geometry the day a writer
        starts populating that key.
        """
        raw = (getattr(well, "metadata", None) or {}).get("survey_stations")
        if not raw:
            return None
        stations: list[tuple[float, float, float]] = []
        for station in raw:
            try:
                md, inc, az = (float(v) for v in station[:3])
            except (TypeError, ValueError, IndexError):
                return None
            stations.append((md, inc, az))
        return stations or None

    @staticmethod
    def _first_seismic_survey(project):
        """First survey entity with parseable bin-grid geometry, else None."""
        for survey in list(getattr(project, "seismic_surveys", None) or []):
            try:
                extent = [(float(c[0]), float(c[1])) for c in (survey.extent or [])]
            except (TypeError, ValueError, IndexError):
                continue
            if len(extent) < 3:
                continue
            il_start, il_stop, il_step = _survey_axis_range(survey.inline_range)
            xl_start, xl_stop, xl_step = _survey_axis_range(survey.crossline_range)
            if il_step is None or xl_step is None:
                continue
            if il_stop == il_start or xl_stop == xl_start:
                continue
            return survey
        return None

    def _configure_hub_seismic_geometry(self, survey) -> None:
        """Push one survey's bin grid into the hub.

        Corner convention (engine ``survey_from_corners``, the same source
        that populated ``extent``): extent[0] is the (il0, xl0) origin,
        extent[1] the opposite CROSSLINE corner (same inline), extent[2] the
        opposite INLINE corner. Axis vectors span the line-number range, so
        hub steps are per inline/crossline NUMBER, exactly what
        ``seismic_to_map`` expects.
        """
        extent = [(float(c[0]), float(c[1])) for c in (survey.extent or [])]
        il_start, il_stop, _ = _survey_axis_range(survey.inline_range)
        xl_start, xl_stop, _ = _survey_axis_range(survey.crossline_range)
        if len(extent) < 3 or il_start is None or xl_start is None:
            return
        dil = float(il_stop) - float(il_start)
        dxl = float(xl_stop) - float(xl_start)
        if dil == 0.0 or dxl == 0.0:
            logger.debug("bind_project: degenerate survey ranges on %r; skipped", survey)
            return
        # p2->p3 edge spans the inline axis; p1->p2 edge spans the crossline axis.
        il_vec = (extent[2][0] - extent[1][0], extent[2][1] - extent[1][1])
        xl_vec = (extent[1][0] - extent[0][0], extent[1][1] - extent[0][1])
        try:
            self.coordinate_hub.configure_seismic_grid(
                origin=extent[0],
                il_step=(il_vec[0] / dil, il_vec[1] / dil),
                xl_step=(xl_vec[0] / dxl, xl_vec[1] / dxl),
                il_min=int(round(float(il_start))),
                xl_min=int(round(float(xl_start))),
            )
        except Exception:
            logger.debug(
                "bind_project: seismic geometry rejected for %r", survey, exc_info=True
            )

    # ------------------------------------------------------------------
    # Attachment
    # ------------------------------------------------------------------

    def attach_app_shell(self, shell) -> None:
        """Bridge every page's selection surfaces onto the context."""
        if self._shell is shell:
            return  # idempotent: never double-connect the bridges
        self._shell = shell
        shell.selection_context = self.selection_context
        shell.coordinate_hub = self.coordinate_hub

        data_page = getattr(shell, "data_page", None)
        if data_page is not None:
            data_page.selection_context = self.selection_context
            data_page.coordinate_hub = self.coordinate_hub
            map_page = getattr(getattr(data_page, "well_map_panel", None), "map_page", None)
            if map_page is not None:
                if hasattr(map_page, "well_selected"):
                    map_page.well_selected.connect(
                        lambda well_id: self.publish_well_selection(well_id, source=self.SOURCE_MAP)
                    )
                if hasattr(map_page, "well_activated"):
                    map_page.well_activated.connect(
                        lambda well_id: self.publish_well_selection(well_id, source=self.SOURCE_MAP)
                    )

        from paleo_workbench.ui.navigation import PAGE_INDEX_GEOMODEL

        geo_page = shell.page_stack.widget(PAGE_INDEX_GEOMODEL)
        if geo_page is not None and hasattr(geo_page, "well_selected"):
            geo_page.well_selected.connect(
                lambda well_id: self.publish_well_selection(well_id, source=self.SOURCE_3D)
            )

        well_log_page = shell.well_log_prediction_page_widget()
        if well_log_page is not None:
            self.attach_well_log_page(well_log_page)

    def attach_well_log_page(self, page) -> None:
        """Wire the well-log page as both subscriber and publisher.

        Publishing subscribes to the panel's semantic ``task_selected``
        signal — NOT the raw ``currentRowChanged``, which also fires for
        every programmatic list rebuild (``update_state`` clear/reselect on
        refreshes): those are not user selections and must not fan out to
        the map/3D views (review BLOCKER). ``task_selected`` is explicitly
        suppressed during refreshes by the panel itself.
        """
        if self._well_log_page is page:
            return  # idempotent: never connect the same panel twice
        previous = self._well_log_page
        if previous is not None:
            previous_panel = getattr(previous, "task_panel", None)
            if previous_panel is not None and hasattr(previous_panel, "task_selected"):
                try:
                    previous_panel.task_selected.disconnect(self._on_well_log_row_selected)
                except (RuntimeError, TypeError):
                    pass
        self._well_log_page = page
        panel = getattr(page, "task_panel", None)
        if panel is not None and hasattr(panel, "task_selected"):
            panel.task_selected.connect(self._on_well_log_row_selected)

    def _on_well_log_row_selected(self, row: int) -> None:
        """User picked a task on the well-log page → publish its well name."""
        if self._well_log_page is None or row < 0:
            return
        page = self._well_log_page
        tasks = getattr(page, "_tasks", None) or []
        if row >= len(tasks):
            return
        name = getattr(tasks[row], "name", None)
        if name:
            self.publish_well_selection(str(name), source=self.SOURCE_WELL_LOG)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_well_selection(self, well_id: str, *, source: str) -> None:
        if not well_id:
            return
        # Duplicate dispatch guard: selecting a task re-enters the row
        # signal once through the panel's own update_state loop, and echo
        # guards elsewhere rely on source tags — an identical (well, source)
        # publication carries no new information, so drop it instead of
        # fanning the same selection out twice.
        current = self.selection_context.snapshot()
        if (
            getattr(current, "active_well_id", None) == well_id
            and getattr(current, "source_widget_id", None) == source
        ):
            return
        self.selection_context.update(
            active_well_id=str(well_id), source_widget_id=source
        )

    def publish_seismic_cursor(self, il: int, xl: int, twt: float) -> None:
        """Publish an (IL, XL, TWT) cursor picked on a seismic view."""
        self.selection_context.update(
            seismic_cursor=(int(il), int(xl), float(twt)),
            source_widget_id=self.SOURCE_SEISMIC,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _on_selection_changed(self, selection) -> None:
        """Route only the fields that CHANGED in this update.

        SelectionContext emits its whole state on every update; routing
        unchanged fields re-dispatched stale selections (a cursor publish
        used to re-run set_selected_well for the previous well — review
        MAJOR).
        """
        previous = self._last_snapshot
        self._last_snapshot = selection.snapshot()

        source = getattr(selection, "source_widget_id", None)

        well_id = getattr(selection, "active_well_id", None)
        well_changed = well_id != getattr(previous, "active_well_id", None)
        if well_id and well_changed:
            self._route_well_selection(str(well_id), source)

        cursor = getattr(selection, "seismic_cursor", None)
        cursor_changed = cursor != getattr(previous, "seismic_cursor", None)
        if cursor is not None and cursor_changed:
            self._route_seismic_cursor(cursor)

    def _route_well_selection(self, well_id: str, source: str | None) -> None:
        # Map → Well Log (auto-switch the log page to the picked well)
        if source != self.SOURCE_WELL_LOG and self._well_log_page is not None:
            setter = getattr(self._well_log_page, "set_selected_well", None)
            if callable(setter):
                setter(well_id)
        # Map/Well Log → 3D (highlight the trajectory)
        if source != self.SOURCE_3D and self._shell is not None:
            from paleo_workbench.ui.navigation import PAGE_INDEX_GEOMODEL

            geo_page = self._shell.page_stack.widget(PAGE_INDEX_GEOMODEL)
            highlight = getattr(geo_page, "highlight_well", None)
            if callable(highlight):
                highlight(well_id)
        # 3D/Well Log → Map (highlight the well location)
        if source != self.SOURCE_MAP and self._shell is not None:
            data_page = getattr(self._shell, "data_page", None)
            map_page = getattr(getattr(data_page, "well_map_panel", None), "map_page", None)
            if map_page is not None and hasattr(map_page, "select_well"):
                # emit=False: the map must not re-publish its own highlight
                map_page.select_well(well_id, emit=False)

    def _route_seismic_cursor(self, cursor: tuple[int, int, float]) -> None:
        """Seismic → Well: resolve the cursor to the nearest well + MD.

        The resolved MD travels in ``custom_attributes`` so depth-cursor
        consumers can read it without a second transform. Routing failures
        never crash the picker, but they are no longer SILENT: an empty
        registry, an out-of-radius pick or a transform error logs at debug
        so "why didn't the well-log page follow" stays diagnosable.
        """
        try:
            well_id, md = self.coordinate_hub.seismic_to_well(*cursor)
        except Exception:
            logger.debug(
                "seismic cursor %s: transform failed; no well-log routing",
                cursor,
                exc_info=True,
            )
            return
        if not well_id:
            logger.debug(
                "seismic cursor %s: no registered well within radius "
                "(registry empty or pick off-radius); no well-log routing",
                cursor,
            )
            return
        self.selection_context.update(
            custom_attributes={"seismic_well_id": well_id, "seismic_well_md": md}
        )
        if self._well_log_page is not None:
            setter = getattr(self._well_log_page, "set_selected_well", None)
            if callable(setter):
                setter(well_id)
