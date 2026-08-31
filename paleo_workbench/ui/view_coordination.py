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
from pathlib import Path

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
        # Scenario sinks. Pages register callables; the controller owns no
        # page references it was not handed, and a missing sink is a no-op
        # (never an error) so views stay optional.
        self._seismic_sink = None            # (il, xl, twt|None) → locate/navigate
        self._spatial_cursor_sink = None     # (x, y) → map marker
        self._seismic_focus_sink = None      # (il, xl, twt) → 3D slice focus
        self._horizon_sink = None            # horizon id → highlight in views
        selection_context.selection_changed.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Project lifecycle (well registry / seismic geometry)
    # ------------------------------------------------------------------

    def bind_project(self, project) -> None:
        """Register the open project's wells and seismic geometry (#1029).

        Called when a project document is opened or switched. Re-binding is a
        full replacement: the previous project's wells are unregistered first
        so no well ever leaks across projects. Time-depth calibration assets
        (role ``time_depth``) are parsed and attached to their wells so the
        scenario-C depth→time route has a real production author.
        """
        self.clear_project()
        for well in list(getattr(project, "wells", None) or []):
            self._register_project_well(well)
        survey = self._first_seismic_survey(project)
        if survey is not None:
            self._configure_hub_seismic_geometry(survey)
        calibrations = self._register_time_depth_calibrations(project)
        logger.debug(
            "bind_project: registered %d well(s) and %d time-depth "
            "calibration(s) into the coordinate hub",
            len(self._bound_well_ids),
            calibrations,
        )

    def _register_time_depth_calibrations(self, project) -> int:
        """Parse time_depth assets into hub calibrations (scenario C author).

        Only assets carrying the ``time_depth`` role enter calibration — a
        plain file with a similar name is not an authority. Unparseable
        tables are skipped with a debug log, never guessed.
        """
        from paleo_workbench.viz.coordinate_hub import TimeDepthCalibration

        registered = 0
        td_assets = self._time_depth_assets(project)
        for well_name, path in td_assets:
            # Project-model paths arrive as str (ResourceItem.path is a str
            # deserialized straight from the project JSON, and the catalog
            # resolver also hands back str); normalize here so the Path
            # usage below (``path.name``) can never AttributeError on a
            # legacy/str-pathed project.
            path = Path(path)
            try:
                from paleo_workbench.viz.joint_well_parsers import parse_td_table

                table = parse_td_table(path, well_name=well_name)
            except Exception:
                logger.debug("time-depth table %s failed to parse", path, exc_info=True)
                continue
            if table is None:
                continue
            pairs = list(zip(table.md_m, table.time_ms))
            try:
                calibration = TimeDepthCalibration.from_pairs(
                    str(well_name), pairs, provenance=f"td-table:{path.name}"
                )
            except ValueError:
                logger.debug(
                    "time-depth table %s rejected (non-monotonic)", path
                )
                continue
            self.coordinate_hub.set_time_depth_calibration(calibration)
            registered += 1
        return registered

    @staticmethod
    def _time_depth_assets(project):
        """(well_name, path) pairs for time_depth assets, hub-keyed by well name.

        Resolution order: WorkArea EntityAssetLinks (well entity display name
        + role time_depth) falling back to legacy ResourceItems typed
        ``time_depth`` keyed by their own file stem.
        """
        results: list[tuple[str, str]] = []
        seen_paths: set[str] = set()
        for link in list(getattr(project, "entity_asset_links", None) or []):
            if str(getattr(link, "role", "")) != "time_depth":
                continue
            if getattr(link, "unresolved", False):
                continue
            well_name = ""
            for well in list(getattr(project, "wells", None) or []):
                if str(getattr(well, "id", "")) == str(getattr(link, "entity_id", "")):
                    well_name = str(getattr(well, "name", "") or "")
                    break
            # staticmethod body: reference the sibling helper through the
            # class (a bare ``self`` here has always been a NameError — any
            # project with time_depth entity links crashed bind_project).
            path = ViewCoordinationController._resolve_asset_path(
                project, getattr(link, "asset_id", "")
            )
            if path and well_name:
                key = str(path)
                if key not in seen_paths:
                    seen_paths.add(key)
                    results.append((well_name, path))
        for resource in list(getattr(project, "resources", None) or []):
            if str(getattr(resource, "type", "")) != "time_depth":
                continue
            path = str(getattr(resource, "path", "") or "")
            if not path:
                continue
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            name = str(getattr(resource, "name", "") or "") or Path(path).stem
            results.append((name, path))
        return results

    @staticmethod
    def _resolve_asset_path(project, asset_id: str) -> str | None:
        """Best-effort payload path for a catalog asset id via the catalog."""
        try:
            from paleo_workbench.catalog import get_catalog

            cat = get_catalog()
        except Exception:
            return None
        if cat is None:
            return None
        try:
            for asset in cat.document.assets:
                if str(asset.id) == str(asset_id):
                    version_id = asset.current_version_id
                    for version in cat.document.versions:
                        if version.id == version_id:
                            return str(cat.resolve_path(version))
        except Exception:
            return None
        return None

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
        # Cross-project bleed covers the geological slots too: a horizon or
        # interpretation selected in the closed project must not survive.
        self.selection_context.clear()
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
            previous_canvas = getattr(previous, "canvas_panel", None)
            previous_depth = getattr(previous_canvas, "depth_cursor_moved", None)
            if previous_depth is not None:
                try:
                    previous_depth.disconnect(self._on_well_depth_cursor)
                except (RuntimeError, TypeError):
                    pass
        self._well_log_page = page
        panel = getattr(page, "task_panel", None)
        if panel is not None and hasattr(panel, "task_selected"):
            panel.task_selected.connect(self._on_well_log_row_selected)
        # Scenario C producer: the canvas crosshair publishes MD; the page's
        # displayed well names it. publish_depth_cursor gates the seismic
        # time navigation on a real time-depth calibration.
        canvas_panel = getattr(page, "canvas_panel", None)
        depth_signal = getattr(canvas_panel, "depth_cursor_moved", None)
        if depth_signal is not None:
            try:
                depth_signal.connect(self._on_well_depth_cursor)
            except (RuntimeError, TypeError):
                pass

    def _on_well_depth_cursor(self, md: float) -> None:
        canvas_panel = getattr(self._well_log_page, "canvas_panel", None)
        well_name = getattr(canvas_panel, "current_well_name", lambda: "")()
        if not well_name:
            return
        self.publish_depth_cursor(str(well_name), float(md), source=self.SOURCE_WELL_LOG)

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
        """Publish an (IL, XL, TWT) cursor picked on a seismic view.

        The same update carries the resolved map-space position in
        ``spatial_cursor`` (scenario B): consumers read one consistent
        snapshot instead of each re-deriving the transform, and no second
        context update is needed (no re-entrant routing).
        """
        spatial = None
        try:
            x, y, _z = self.coordinate_hub.seismic_to_map(int(il), int(xl), float(twt))
            spatial = (float(x), float(y))
        except Exception:
            logger.debug("seismic cursor %s: map position unavailable", (il, xl, twt))
        self.selection_context.update(
            seismic_cursor=(int(il), int(xl), float(twt)),
            spatial_cursor=spatial,
            source_widget_id=self.SOURCE_SEISMIC,
        )

    def publish_horizon_selection(self, horizon_id: str, *, source: str) -> None:
        """Publish the active horizon's stable identity (scenario D)."""
        if not horizon_id:
            return
        self.selection_context.update(
            active_horizon_id=str(horizon_id), source_widget_id=source
        )

    def publish_fault_selection(self, fault_id: str, *, source: str) -> None:
        if not fault_id:
            return
        self.selection_context.update(
            active_fault_id=str(fault_id), source_widget_id=source
        )

    def publish_interpretation_selection(self, interpretation_id: str, *, source: str) -> None:
        if not interpretation_id:
            return
        self.selection_context.update(
            active_interpretation_id=str(interpretation_id), source_widget_id=source
        )

    def publish_depth_cursor(self, well_id: str, md: float, *, source: str) -> bool:
        """Publish a well-log depth cursor (scenario C), calibration-gated.

        The depth itself always lands in ``depth_cursor``. The seismic time
        navigation happens ONLY when the hub holds a valid time-depth
        calibration for this well — without one the route refuses (returns
        False) rather than guessing depth==time through a default velocity.
        """
        if not well_id:
            return False
        md_val = float(md)
        self.selection_context.update(
            depth_cursor=(str(well_id), md_val), source_widget_id=source
        )
        try:
            il, xl, twt = self.coordinate_hub.well_md_to_seismic_cursor(well_id, md_val)
        except Exception:
            logger.debug(
                "depth cursor %s@%s: calibrated seismic lookup failed",
                well_id,
                md_val,
                exc_info=True,
            )
            return False
        if il is None:
            cal = self.coordinate_hub.time_depth_calibration(well_id)
            logger.debug(
                "depth cursor %s@%s: refused — no valid time-depth calibration%s",
                well_id,
                md_val,
                f" ({cal.provenance} does not cover this depth)" if cal else "",
            )
            return False
        if source != self.SOURCE_SEISMIC and self._seismic_focus_sink is not None:
            self._seismic_focus_sink(il, xl, twt)
        return True

    # ------------------------------------------------------------------
    # Scenario sinks (views register interest)
    # ------------------------------------------------------------------

    def set_seismic_sink(self, sink) -> None:
        """Register the seismic locator: ``(il, xl, twt=None) → navigate``.

        Scenario A: a well selected elsewhere navigates the seismic view to
        the well's inline/crossline. ``twt`` stays None unless a calibration
        provided it — the locator must not invent a time.
        """
        self._seismic_sink = sink

    def set_spatial_cursor_sink(self, sink) -> None:
        """Register the map spatial-cursor marker: ``(x, y)``."""
        self._spatial_cursor_sink = sink

    def set_seismic_focus_sink(self, sink) -> None:
        """Register the 3D/section slice focus: ``(il, xl, twt)``."""
        self._seismic_focus_sink = sink

    def set_horizon_sink(self, sink) -> None:
        """Register the horizon highlight target: ``(horizon_id)``."""
        self._horizon_sink = sink

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

        horizon_id = getattr(selection, "active_horizon_id", None)
        horizon_changed = horizon_id != getattr(previous, "active_horizon_id", None)
        if horizon_id and horizon_changed:
            self._route_horizon_selection(str(horizon_id), source)

        spatial = getattr(selection, "spatial_cursor", None)
        spatial_changed = spatial != getattr(previous, "spatial_cursor", None)
        if spatial is not None and spatial_changed and source != self.SOURCE_MAP:
            if self._spatial_cursor_sink is not None:
                try:
                    self._spatial_cursor_sink(float(spatial[0]), float(spatial[1]))
                except Exception:
                    logger.debug("spatial cursor routing failed", exc_info=True)

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
        # Any view → Seismic (locate the well's inline/crossline; scenario A)
        if source != self.SOURCE_SEISMIC:
            self._locate_well_in_seismic(well_id)

    def _locate_well_in_seismic(self, well_id: str) -> bool:
        """Navigate the seismic view to a well through the hub geometry.

        TWT is passed only when the well has a time-depth calibration whose
        range covers its current depth reference; otherwise the locator gets
        (il, xl, None) and must not invent a time. Failures log at debug and
        stay non-fatal — the seismic view may simply not be open.
        """
        if self._seismic_sink is None:
            return False
        try:
            x, y, _tvd = self.coordinate_hub.well_depth_to_map(well_id, 0.0)
            il, xl, _twt = self.coordinate_hub.map_to_seismic(x, y, 0.0)
        except Exception:
            logger.debug(
                "seismic locate for well %r: geometry unavailable", well_id, exc_info=True
            )
            return False
        self._seismic_sink(int(il), int(xl), None)
        return True

    def _route_horizon_selection(self, horizon_id: str, source: str | None) -> None:
        """Scenario D: one stable horizon identity reaches every interested view."""
        if self._horizon_sink is not None:
            try:
                self._horizon_sink(horizon_id)
            except Exception:
                logger.debug("horizon routing failed for %r", horizon_id, exc_info=True)

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
        # ``seismic_well_md`` is a constant-velocity APPROXIMATION kept for
        # readout context only — calibrated depth↔time goes through
        # TimeDepthCalibration (publish_depth_cursor), never this value.
        self.selection_context.update(
            custom_attributes={
                "seismic_well_id": well_id,
                "seismic_well_md": md,
                "seismic_well_md_is_approximate": True,
            }
        )
        if self._well_log_page is not None:
            setter = getattr(self._well_log_page, "set_selected_well", None)
            if callable(setter):
                setter(well_id)
        # Scenario B: the same cursor focuses the 3D/section views. The
        # well-MD above is a constant-velocity approximation used only for
        # readout context; the 3D focus gets the raw (IL, XL, TWT) so no
        # approximate depth ever masquerades as a calibrated one.
        if self._seismic_focus_sink is not None:
            try:
                self._seismic_focus_sink(int(cursor[0]), int(cursor[1]), float(cursor[2]))
            except Exception:
                logger.debug("seismic cursor 3D focus failed", exc_info=True)
