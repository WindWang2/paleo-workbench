from __future__ import annotations

from typing import Any

from geoviz import PaleoMapCanvas

from paleo_workbench.viz.facies_hierarchy_service import (
    AUTO_LEVEL,
    build_facies_hierarchy,
    hierarchy_levels_present,
    is_hierarchical_feature_set,
)
from paleo_workbench.viz.models import VizPayload


class PaleoMapHost:
    """Host for ``geoviz_paleo_map.PaleoMapCanvas`` (read-only product view).

    Full topology editing stays on MappingPage (workbench map_edit_*); this host
    mirrors engine preview chrome used by geo-viz map pages.

    Multiscale support: when the map payload's facies features carry hierarchy
    metadata (``level`` + ``parent_id``), the canvas switches to geo-viz-engine's
    zoom-driven 相/亚相/微相 level display (``load_hierarchy``); flat data keeps
    the original ``load_features`` path. See :mod:`facies_hierarchy_service`.
    """

    tab_title = "古地理"

    def __init__(self) -> None:
        self.widget = PaleoMapCanvas()
        self._hierarchy_active: bool = False
        self._current_features: list[dict[str, Any]] = []

    def clear(self) -> None:
        self.widget.load_features([], period_name="", wells=[])
        self._hierarchy_active = False
        self._current_features = []

    def apply(self, payload: VizPayload) -> bool:
        # Reject payloads that are neither map/prediction nor carry any map
        # data. (The original nested check was redundant: "kind not in
        # {map,prediction}" already implies "kind != map".)
        if payload.kind not in {"map", "prediction"} and not (
            payload.map_features or payload.map_wells
        ):
            return False
        feats = payload.map_features or []
        wells = payload.map_wells or []
        period = payload.period_name or ""
        self._current_features = list(feats)
        if is_hierarchical_feature_set(feats):
            # Multiscale path: build a FaciesHierarchy and let the canvas switch
            # the visible level by map scale (or via set_level below).
            hierarchy = build_facies_hierarchy(feats)
            self.widget.load_hierarchy(hierarchy, period_name=period, wells=wells)
            self._hierarchy_active = True
        else:
            self.widget.load_features(feats, period_name=period, wells=wells)
            self._hierarchy_active = False
        return True

    # ------------------------------------------------------------------ #
    # Level control (used by the composite-panel level selector)
    # ------------------------------------------------------------------ #

    @property
    def hierarchy_active(self) -> bool:
        """Whether the current map is displayed via the hierarchy path."""
        return self._hierarchy_active

    def available_levels(self) -> list[str]:
        """Hierarchy levels present in the current map (coarse → fine)."""
        return hierarchy_levels_present(self._current_features)

    def set_level(self, level: str | None) -> bool:
        """Lock the canvas to *level*, or release to auto (scale-driven).

        Returns True if applied (hierarchy active), False otherwise. ``None`` or
        :data:`AUTO_LEVEL` releases the lock so zoom chooses the level.
        """
        if not self._hierarchy_active:
            return False
        if level is None or level == AUTO_LEVEL:
            # Release any manual lock → scale-driven resolution. The engine
            # treats an empty locked level as "auto" (_resolve_level_name).
            self.widget.set_locked_level("")
            return True
        if level in self.available_levels():
            self.widget.set_locked_level(level)
            return True
        return False
