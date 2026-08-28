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

from PySide6.QtCore import QObject

from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
from paleo_workbench.viz.selection_context import SelectionContext


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
        selection_context.selection_changed.connect(self._on_selection_changed)

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
        consumers can read it without a second transform.
        """
        try:
            well_id, md = self.coordinate_hub.seismic_to_well(*cursor)
        except Exception:
            return
        if well_id:
            self.selection_context.update(
                custom_attributes={"seismic_well_id": well_id, "seismic_well_md": md}
            )
            if self._well_log_page is not None:
                setter = getattr(self._well_log_page, "set_selected_well", None)
                if callable(setter):
                    setter(well_id)
