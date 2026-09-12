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
    SOURCE_WORKSTATION = "workstation_explorer"
    # V11 UIContext 槽位发布源（goal §6）
    SOURCE_DATA_PAGE = "data_page"
    SOURCE_INSPECTOR = "inspector"
    SOURCE_SEISMIC_PANEL = "seismic_panel"
    SOURCE_TASK = "task_panel"
    SOURCE_STAGE = "mapping_stage"

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
        # V11 井身份索引（01-ui-audit C1）：bus 的跨视图键是井**名**（#1029
        # 既有约定），但 Data 井位图 / 3D fence 路径发布的是实体 **id**。
        # 索引让 publish 侧把任意标识规范化成规范名，消费者不再静默失配。
        self._well_name_by_id: dict[str, str] = {}
        self._well_id_by_name: dict[str, str] = {}
        # Scenario sinks. Pages register callables; the controller owns no
        # page references it was not handed, and a missing sink is a no-op
        # (never an error) so views stay optional.
        self._seismic_sink = None            # (il, xl, twt|None) → locate/navigate
        self._spatial_cursor_sink = None     # (x, y) → map marker
        self._seismic_focus_sink = None      # (il, xl, twt) → 3D slice focus
        self._horizon_sink = None            # horizon id → highlight in views
        # L8 workstation sinks: the docked well/seismic panels participate as
        # first-class views. The well dock opens/focuses on any well selection
        # (case A); a calibrated seismic cursor drives the native link cursor
        # on the docked well view (case B, calibrated MD only).
        self._well_dock_sink = None          # (well_name) → open/focus dock
        self._link_cursor_sink = None        # (well_name, md_m|None) → engine crosshair
        self._link_cursor_set = False        # a link cursor is currently shown
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
            self._index_well_identity(well)
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
        tables are skipped with a debug log, never guessed. Entity-linked
        assets keep their catalog identity (version id / fingerprint /
        quality metadata) so a reopened calibration stays attributable.
        """
        from paleo_workbench.viz.coordinate_hub import TimeDepthCalibration

        registered = 0
        td_assets = self._time_depth_assets(project)
        for item in td_assets:
            # Entity links carry the catalog identity alongside the path;
            # legacy ResourceItems only have the path.
            if len(item) == 3:
                well_name, path, identity = item
                version_id = identity.get("version_id")
                fingerprint = identity.get("fingerprint")
                metadata = identity.get("metadata") or {}
            else:
                well_name, path = item
                version_id = fingerprint = None
                metadata = {}
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
                    str(well_name),
                    pairs,
                    provenance=f"td-table:{path.name}",
                    version_id=version_id,
                    fingerprint=fingerprint,
                    metadata=dict(metadata),
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
        """time_depth entries for calibration, hub-keyed by well name.

        Resolution order: WorkArea EntityAssetLinks (well entity display name
        + role time_depth, carrying the catalog version identity when the
        version metadata holds one) falling back to legacy ResourceItems
        typed ``time_depth`` keyed by their own file stem.

        Yields ``(well_name, path)`` for legacy entries and
        ``(well_name, path, identity_dict)`` for entity-linked entries.
        """
        results: list[tuple] = []
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
            resolved = ViewCoordinationController._resolve_asset_version(
                project, getattr(link, "asset_id", "")
            )
            if resolved is None:
                continue
            path, identity = resolved
            if path and well_name:
                key = str(path)
                if key not in seen_paths:
                    seen_paths.add(key)
                    results.append((well_name, path, identity))
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
    def _resolve_asset_version(project, asset_id: str) -> tuple[str, dict] | None:
        """Best-effort (payload path, identity) for a catalog asset id.

        The identity dict carries the version id plus any fingerprint /
        quality metadata stored on the version, so a registered calibration
        stays attributable to its catalog version after reopen.
        """
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
                            metadata = dict(getattr(version, "metadata", None) or {})
                            return (
                                str(cat.resolve_path(version)),
                                {
                                    "version_id": version_id,
                                    "fingerprint": metadata.get("fingerprint"),
                                    "metadata": metadata,
                                },
                            )
        except Exception:
            return None
        return None

    def clear_project(self) -> None:
        """Unregister every project-bound well and reset the seismic grid.

        The seismic grid is restored to hub defaults as well — geometry from
        a previous project is just as much cross-project residue as wells.
        """
        self._bound_well_ids.clear()
        self._well_name_by_id.clear()
        self._well_id_by_name.clear()
        removed = self.coordinate_hub.clear_all_wells()
        self._link_cursor_set = False
        try:
            self.coordinate_hub.configure_seismic_grid()
        except Exception:  # pragma: no cover - defaults are always valid
            logger.debug("clear_project: grid reset failed", exc_info=True)
        # Cross-project bleed covers the geological slots too: a horizon or
        # interpretation selected in the closed project must not survive.
        self.selection_context.clear()
        if removed:
            logger.debug("clear_project: unregistered %d well(s)", removed)

    def _index_well_identity(self, well) -> None:
        """登记 name↔entity_id 双向映射（bind_project 全量重建）。"""
        name = str(getattr(well, "name", "") or "").strip()
        entity_id = str(getattr(well, "id", "") or "").strip()
        if name and entity_id:
            self._well_name_by_id[entity_id] = name
            self._well_id_by_name[name] = entity_id

    def resolve_well_key(self, value: str) -> tuple[str | None, str | None]:
        """把任意井标识（名或实体 id）规范化为 ``(canonical_name, entity_id)``。

        * 名字命中 → ``(name, id)``；
        * 实体 id 命中 → ``(name, id)``（修复 id 发布者让名字消费者静默
          失配的问题）；
        * 都不命中 → ``(None, None)``（诚实未知，不猜）。
        """
        text = str(value or "").strip()
        if not text:
            return None, None
        if text in self._well_id_by_name:
            return text, self._well_id_by_name[text]
        if text in self._well_name_by_id:
            return self._well_name_by_id[text], text
        return None, None

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

        geo_page = getattr(shell, "geomodel_page", None)
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
        # V11 身份规范化：接受井名或实体 id（Data 井位图发布 id、其它视图
        # 发布名——C1）。规范化失败（未知标识）按原值发布，不吞选择。
        canonical, entity_id = self.resolve_well_key(well_id)
        key = canonical if canonical is not None else str(well_id)
        # Duplicate dispatch guard: selecting a task re-enters the row
        # signal once through the panel's own update_state loop, and echo
        # guards elsewhere rely on source tags — an identical (well, source)
        # publication carries no new information, so drop it instead of
        # fanning the same selection out twice.
        current = self.selection_context.snapshot()
        if (
            getattr(current, "active_well_id", None) == key
            and getattr(current, "source_widget_id", None) == source
        ):
            return
        attrs = dict(current.custom_attributes or {})
        if entity_id:
            attrs["well_entity_id"] = entity_id
        else:
            attrs.pop("well_entity_id", None)
        self.selection_context.update(
            active_well_id=key, source_widget_id=source, custom_attributes=attrs
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
            # Pure bin-grid geometry: the cursor's TWT is deliberately NOT
            # converted to a depth here (that needs an authority nobody on
            # this path has — see _route_seismic_cursor for the calibrated
            # well-MD route).
            x, y = self.coordinate_hub.seismic_to_map_xy(int(il), int(xl))
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

    def publish_layer_selection(self, layer_id: str, *, source: str) -> None:
        """Publish the layer the user highlighted in a tree (V11 语义修正)。

        V11 起该槽位写入 ``selected_layer_id``（注意力焦点），不再冒充
        「活动层」——active 层（工具作用对象，编辑控制器权威）经
        :meth:`publish_active_layer` 单独发布，两个概念禁止混写
        （01-ui-audit C3）。重复发布守卫保留。
        """
        if not layer_id:
            return
        current = self.selection_context.snapshot()
        if (
            getattr(current, "selected_layer_id", None) == layer_id
            and getattr(current, "source_widget_id", None) == source
        ):
            return
        self.selection_context.update(
            selected_layer_id=str(layer_id), source_widget_id=source
        )

    def publish_active_layer(self, layer_id: str | None, *, source: str) -> None:
        """Publish the true active layer (edit-controller authority, QGIS 语义)."""
        self.selection_context.update(
            active_layer_id=str(layer_id) if layer_id else None,
            source_widget_id=source,
        )

    def publish_edit_target(self, layer_id: str | None, *, source: str) -> None:
        """Publish the stage controller's edit-target layer (角色解析结果)."""
        self.selection_context.update(
            edit_target_layer_id=str(layer_id) if layer_id else None,
            source_widget_id=source,
        )

    def publish_asset_selection(
        self, asset_id: str | None, *, version_id: str | None = None, source: str
    ) -> None:
        """Publish the Data-page asset (and optional version) selection.

        V11 之前 DataPage 选择对全应用不可见（死信号 data_context_changed，
        01-ui-audit C2）；统一走总线后 Inspector / 状态条 / palette 适用性
        与 Data 页同源。带 (资产, 版本, 源) 重复守卫——摘要重算等触发的
        重发布不再风扇 selection_changed（评审 P2）。
        """
        current = self.selection_context.snapshot()
        if (
            getattr(current, "selected_asset_id", None) == asset_id
            and getattr(current, "selected_version_id", None) == version_id
            and getattr(current, "source_widget_id", None) == source
        ):
            return
        self.selection_context.update(
            selected_asset_id=str(asset_id) if asset_id else None,
            selected_version_id=str(version_id) if version_id else None,
            source_widget_id=source,
        )

    def publish_survey_selection(self, survey_id: str | None, *, source: str) -> None:
        """Publish the active seismic survey (stable resource id)."""
        self.selection_context.update(
            active_survey_id=str(survey_id) if survey_id else None,
            source_widget_id=source,
        )

    def publish_task_selection(self, task_id: str | None, *, source: str) -> None:
        """Publish the active prediction/computation task (stable id)."""
        self.selection_context.update(
            active_task_id=str(task_id) if task_id else None,
            source_widget_id=source,
        )

    def publish_stage(self, stage: str | None, *, source: str) -> None:
        """Publish the workflow stage (MappingStage.value)."""
        self.selection_context.update(
            workflow_stage=str(stage) if stage else None,
            source_widget_id=source,
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

    def set_well_dock_sink(self, sink) -> None:
        """Register the workstation well dock: ``(well_name) → open/focus``.

        Case A: a well selected anywhere (map/3D/well-log page) opens the
        docked well view on that well. The dock itself never publishes well
        selections, so there is no echo path to guard here.
        """
        self._well_dock_sink = sink

    def set_link_cursor_sink(self, sink) -> None:
        """Register the native link-cursor target: ``(well_name, md_m|None)``.

        Case B: a seismic cursor resolves to a CALIBRATED MD on the nearest
        well; when that well is the one the dock shows, the sink drives the
        engine crosshair. ``md=None`` clears a previously shown cursor — the
        sink must tolerate being called for a well it is not showing. Sink
        invocations are throttled to ≥30 ms apart (rapid inline drags bypass
        the producer-side il-jump gate; the native crosshair write must not
        amplify every mouse event).
        """
        self._link_cursor_sink = sink

    def attach_well_dock_panel(self, panel) -> None:
        """Wire the docked well panel as a depth-cursor producer (case C).

        NOTE (review R2-M3): the production case-C producer is
        ``LinkedInterpretationWorkspace._on_depth_cursor`` (link-gated,
        panel-side throttled). This controller-side hook exists for hosts
        that embed a WellLogCanvasPanel WITHOUT the workspace; do not wire
        both or the same signal publishes twice.
        """
        depth_signal = getattr(panel, "depth_cursor_moved", None)
        if depth_signal is None:
            return
        try:
            depth_signal.connect(
                lambda md, p=panel: self._on_dock_depth_cursor(p, float(md))
            )
        except (RuntimeError, TypeError):
            pass

    def _on_dock_depth_cursor(self, panel, md: float) -> None:
        # Defense-in-depth gate: producers pre-gate their own signals, but a
        # raw emitter (or a future producer) must not flood the bus either.
        import time as _time

        now_ms = _time.monotonic() * 1000.0
        last = getattr(self, "_dock_depth_last_pub_ms", None)
        if last is not None and now_ms - last < 120.0:
            return
        self._dock_depth_last_pub_ms = now_ms
        well_name = ""
        getter = getattr(panel, "current_well_name", None)
        if callable(getter):
            well_name = str(getter() or "")
        if not well_name:
            return
        self.publish_depth_cursor(well_name, md, source=self.SOURCE_WELL_LOG)

    def _throttled_link_cursor_write(self, well_id: str, md: float) -> None:
        """Rate-limited native crosshair write (see _route_seismic_cursor)."""
        import time as _time

        now_ms = _time.monotonic() * 1000.0
        last = getattr(self, "_link_cursor_last_write_ms", None)
        if last is not None and now_ms - last < 30.0:
            return
        self._link_cursor_last_write_ms = now_ms
        self._link_cursor_sink(well_id, md)  # type: ignore[misc]
        self._link_cursor_set = True

    def _clear_link_cursor_once(self, well_id: str | None = None) -> None:
        """Clear a shown link cursor exactly once; no-op afterwards."""
        if not self._link_cursor_set or self._link_cursor_sink is None:
            return
        try:
            self._link_cursor_sink(well_id, None)
        except Exception:
            logger.debug("link cursor clear failed", exc_info=True)
        finally:
            self._link_cursor_set = False

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
        # Any view → workstation well dock (case A: open + focus)
        if self._well_dock_sink is not None:
            try:
                self._well_dock_sink(str(well_id))
            except Exception:
                logger.debug("well dock routing failed for %r", well_id, exc_info=True)
        # Map/Well Log → 3D (highlight the trajectory)
        if source != self.SOURCE_3D and self._shell is not None:
            geo_page = getattr(self._shell, "geomodel_page", None)
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
            il, xl = self.coordinate_hub.map_to_seismic_xy(x, y)
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

        The MD resolution order is honest about its authority: a REAL
        time-depth calibration on the nearest well produces a calibrated MD
        (``seismic_well_md_is_approximate`` False, provenance recorded); a
        declared velocity assumption produces an approximate readout MD; no
        authority leaves the MD unavailable (None). Routing failures never
        crash the picker, and "why didn't the well-log page follow" stays
        diagnosable through the debug logs.
        """
        try:
            well_id, md = self.coordinate_hub.seismic_to_well(*cursor)
        except Exception:
            logger.debug(
                "seismic cursor %s: transform failed; no well-log routing",
                cursor,
                exc_info=True,
            )
            self._clear_link_cursor_once()
            return
        if not well_id:
            logger.debug(
                "seismic cursor %s: no registered well within radius "
                "(registry empty or pick off-radius); no well-log routing",
                cursor,
            )
            # No well in radius means no authority can produce an MD here:
            # a previously shown link cursor must not survive as a stale
            # depth hint on the docked well view (review R1-M3).
            self._clear_link_cursor_once()
            return
        # Calibrated first: TWT → MD through the well's own calibration.
        calibrated_md: float | None = None
        calibration_provenance: str | None = None
        try:
            cal = self.coordinate_hub.time_depth_calibration(well_id)
            if cal is not None:
                calibrated = cal.twt_to_md(float(cursor[2]))
                if calibrated is not None:
                    calibrated_md = float(calibrated)
                    calibration_provenance = cal.provenance
        except Exception:
            logger.debug(
                "seismic cursor %s: calibrated MD lookup failed",
                cursor,
                exc_info=True,
            )
        if calibrated_md is not None:
            self.selection_context.update(
                custom_attributes={
                    "seismic_well_id": well_id,
                    "seismic_well_md": calibrated_md,
                    "seismic_well_md_is_approximate": False,
                    "seismic_well_md_authority": f"time-depth:{calibration_provenance}",
                }
            )
        elif md is not None:
            # ``seismic_well_md`` is a constant-velocity APPROXIMATION kept
            # for readout context only — calibrated depth↔time goes through
            # TimeDepthCalibration (publish_depth_cursor), never this value.
            self.selection_context.update(
                custom_attributes={
                    "seismic_well_id": well_id,
                    "seismic_well_md": md,
                    "seismic_well_md_is_approximate": True,
                    "seismic_well_md_authority": (
                        f"velocity-assumption:"
                        f"{self.coordinate_hub.velocity_assumption():g} m/s"
                    ),
                }
            )
        else:
            self.selection_context.update(
                custom_attributes={
                    "seismic_well_id": well_id,
                    "seismic_well_md": None,
                    "seismic_well_md_is_approximate": None,
                    "seismic_well_md_authority": None,
                }
            )
        if self._well_log_page is not None:
            setter = getattr(self._well_log_page, "set_selected_well", None)
            if callable(setter):
                setter(well_id)
        # Case B well-view half: the calibrated MD drives the native link
        # cursor when the dock is showing this well; a previously shown
        # cursor is cleared once no authority produces an MD anymore. Sink
        # writes are throttled (≥30 ms): rapid inline drags bypass the
        # producer-side il-jump gate and each write is a native crosshair
        # document mutation (review R3-M5).
        if self._link_cursor_sink is not None:
            try:
                if calibrated_md is not None:
                    self._throttled_link_cursor_write(well_id, calibrated_md)
                else:
                    self._clear_link_cursor_once(well_id)
            except Exception:
                logger.debug("link cursor routing failed", exc_info=True)
        # Scenario B: the same cursor focuses the 3D/section views. The
        # 3D focus gets the raw (IL, XL, TWT) so no approximate depth ever
        # masquerades as a calibrated one.
        if self._seismic_focus_sink is not None:
            try:
                self._seismic_focus_sink(int(cursor[0]), int(cursor[1]), float(cursor[2]))
            except Exception:
                logger.debug("seismic cursor 3D focus failed", exc_info=True)
