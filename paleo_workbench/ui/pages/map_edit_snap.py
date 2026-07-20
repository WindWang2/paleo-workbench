from __future__ import annotations

from typing import Any, Iterable

from paleo_workbench.mapping import map_edit_api as api
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    LabelItem,
    LineItem,
    WellPointItem,
)

_DEFAULT_SNAP_TOL = 0.5


class MapSnapManager:
    """Manages snap state, candidate point extraction, caching, and point snapping."""

    def __init__(self, snap_tolerance: float = _DEFAULT_SNAP_TOL) -> None:
        self._snap_enabled = False
        self._snap_tolerance = snap_tolerance
        self._snap_candidate_cache: list[tuple[float, float]] | None = None
        self._snap_candidate_builds = 0
        self._reference_snap_points: list[tuple[float, float]] = []

    @property
    def enabled(self) -> bool:
        return self._snap_enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._snap_enabled = bool(value)

    @property
    def tolerance(self) -> float:
        return self._snap_tolerance

    @tolerance.setter
    def tolerance(self, value: float) -> None:
        self._snap_tolerance = max(0.0, float(value))

    @property
    def reference_points(self) -> list[tuple[float, float]]:
        return self._reference_snap_points

    def set_reference_points(self, points: list[tuple[float, float]]) -> None:
        self._reference_snap_points = [(float(x), float(y)) for x, y in points]
        self.invalidate_candidates()

    def invalidate_candidates(self) -> None:
        self._snap_candidate_cache = None

    def build_count(self) -> int:
        return self._snap_candidate_builds

    def snap_xy(
        self,
        x: float,
        y: float,
        items: Iterable[Any],
        is_layer_visible_fn,
        draft_points: list[list[float]] | None = None,
    ) -> tuple[float, float]:
        if not self._snap_enabled:
            return float(x), float(y)
        candidates = self.get_candidates(items, is_layer_visible_fn, draft_points)
        return api.snap_point(candidates, float(x), float(y), tol=self._snap_tolerance)

    def get_candidates(
        self,
        items: Iterable[Any],
        is_layer_visible_fn,
        draft_points: list[list[float]] | None = None,
    ) -> list[tuple[float, float]]:
        extra = [tuple(p) for p in draft_points] if draft_points else []
        if self._snap_candidate_cache is not None:
            return [*self._snap_candidate_cache, *extra]

        pts: list[tuple[float, float]] = []
        for item in items:
            if not is_layer_visible_fn(getattr(item, "kind", "")):
                continue
            if isinstance(item, FaciesPolygonItem):
                for ring in item.all_rings():
                    for p in ring:
                        pts.append((float(p[0]), float(p[1])))
            elif isinstance(item, LineItem):
                for p in item.coordinates():
                    pts.append((float(p[0]), float(p[1])))
            elif isinstance(item, (WellPointItem, LabelItem)):
                rec = item.to_record()
                c = rec.get("coordinates") or [0, 0]
                pts.append((float(c[0]), float(c[1])))
        pts.extend(self._reference_snap_points)
        self._snap_candidate_cache = pts
        self._snap_candidate_builds += 1
        return [*pts, *extra]
