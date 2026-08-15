"""Persistent host-owned spatial candidates for legacy map-edit hit testing.

The graphics items remain the geometry authority.  This index only retains the
lightweight records already required by ``map_edit_api.hit_test`` plus their
bounds, so pointer queries do not serialize every item on every event.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Iterable, Mapping

__all__ = ["FeatureQueryIndex"]

Bounds = tuple[float, float, float, float]


def _point(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _points(value: object) -> Iterable[tuple[float, float]]:
    point = _point(value)
    if point is not None:
        yield point
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _points(child)


def _record_bounds(record: Mapping[str, Any]) -> Bounds:
    geometry = record.get("geometry")
    coordinates = geometry.get("coordinates") if isinstance(geometry, Mapping) else None
    if coordinates is None:
        coordinates = record.get("coordinates")
    vertices = tuple(_points(coordinates))
    if not vertices:
        return (0.0, 0.0, 0.0, 0.0)
    xs, ys = zip(*vertices)
    return (min(xs), min(ys), max(xs), max(ys))


def _intersects(left: Bounds, right: Bounds) -> bool:
    return not (
        left[2] < right[0]
        or left[0] > right[2]
        or left[3] < right[1]
        or left[1] > right[3]
    )


@dataclass(slots=True)
class _Entry:
    feature_id: str
    kind: str
    record: dict[str, Any]
    bounds: Bounds
    order: int
    cells: tuple[tuple[int, int], ...]
    overflow: bool = False


class FeatureQueryIndex:
    """Incrementally maintained cell index for ``MapEditScene`` records.

    Items are serialized only on load or on a feature-level create/delete/
    geometry edit.  Visibility remains a query-time predicate so toggling a
    layer cannot expose stale hidden geometry.
    """

    _MAX_CELLS_PER_ENTRY = 256
    _MAX_QUERY_CELLS = 4096

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._cells: dict[tuple[int, int], set[str]] = {}
        self._overflow: set[str] = set()
        self._cell_size = 1.0
        self._next_order = 0
        self._query_count = 0
        self._candidate_count = 0
        self._record_build_count = 0
        self._rebuild_count = 0

    def clear(self) -> None:
        self._entries.clear()
        self._cells.clear()
        self._overflow.clear()
        self._next_order = 0

    def rebuild(
        self,
        items: Iterable[object],
        *,
        record_for_item: Callable[[object], Mapping[str, Any]],
    ) -> None:
        materialized = [(item, dict(record_for_item(item))) for item in items]
        bounds = [_record_bounds(record) for _item, record in materialized]
        self.clear()
        if bounds:
            span = max(
                max(bound[2] for bound in bounds) - min(bound[0] for bound in bounds),
                max(bound[3] for bound in bounds) - min(bound[1] for bound in bounds),
            )
            self._cell_size = max(span / 64.0, 1e-9)
        else:
            self._cell_size = 1.0
        for item, record in materialized:
            self._insert(item, record, preserve_order=False)
        self._record_build_count += len(materialized)
        self._rebuild_count += 1

    def upsert(
        self,
        item: object,
        *,
        record_for_item: Callable[[object], Mapping[str, Any]],
    ) -> None:
        self._insert(item, dict(record_for_item(item)), preserve_order=True)
        self._record_build_count += 1

    def remove(self, feature_id: str) -> None:
        entry = self._entries.pop(str(feature_id), None)
        if entry is None:
            return
        self._overflow.discard(entry.feature_id)
        for cell in entry.cells:
            bucket = self._cells.get(cell)
            if bucket is None:
                continue
            bucket.discard(entry.feature_id)
            if not bucket:
                self._cells.pop(cell, None)

    def query(
        self,
        x: float,
        y: float,
        tolerance: float,
        *,
        visible: Callable[[str], bool],
    ) -> list[dict[str, Any]]:
        tolerance = max(0.0, float(tolerance))
        bounds = (x - tolerance, y - tolerance, x + tolerance, y + tolerance)
        ids = set(self._overflow)
        cell_range = self._cell_range(bounds)
        if self._cell_count(cell_range) > self._MAX_QUERY_CELLS:
            ids.update(self._entries)
        else:
            for cell in self._iter_cells(cell_range):
                ids.update(self._cells.get(cell, ()))
        candidates = [
            entry
            for feature_id in ids
            if (entry := self._entries.get(feature_id)) is not None
            and visible(entry.kind)
            and _intersects(entry.bounds, bounds)
        ]
        # Descending insertion order: the top-most (later-added) feature is
        # returned first, matching Qt item stacking and the unified canvas
        # (map_interaction.py), whose hit_test takes the first candidate.
        candidates.sort(key=lambda entry: entry.order, reverse=True)
        self._query_count += 1
        self._candidate_count += len(candidates)
        return [entry.record for entry in candidates]

    def diagnostics(self) -> dict[str, int]:
        return {
            "entries": len(self._entries),
            "cells": len(self._cells),
            "query_count": self._query_count,
            "candidate_count": self._candidate_count,
            "record_build_count": self._record_build_count,
            "rebuild_count": self._rebuild_count,
        }

    def _insert(self, item: object, record: dict[str, Any], *, preserve_order: bool) -> None:
        feature_id = str(getattr(item, "feature_id", record.get("id") or ""))
        if not feature_id:
            return
        previous = self._entries.get(feature_id)
        self.remove(feature_id)
        bounds = _record_bounds(record)
        cell_range = self._cell_range(bounds)
        overflow = self._cell_count(cell_range) > self._MAX_CELLS_PER_ENTRY
        cells = () if overflow else tuple(self._iter_cells(cell_range))
        if preserve_order and previous is not None:
            order = previous.order
        else:
            order = self._next_order
            self._next_order += 1
        entry = _Entry(
            feature_id=feature_id,
            kind=str(getattr(item, "kind", record.get("kind") or "")),
            record=record,
            bounds=bounds,
            order=order,
            cells=cells,
            overflow=overflow,
        )
        self._entries[feature_id] = entry
        if overflow:
            self._overflow.add(feature_id)
        else:
            for cell in cells:
                self._cells.setdefault(cell, set()).add(feature_id)

    def _cell_range(self, bounds: Bounds) -> tuple[int, int, int, int]:
        return (
            math.floor(bounds[0] / self._cell_size),
            math.floor(bounds[1] / self._cell_size),
            math.floor(bounds[2] / self._cell_size),
            math.floor(bounds[3] / self._cell_size),
        )

    @staticmethod
    def _cell_count(cell_range: tuple[int, int, int, int]) -> int:
        left, bottom, right, top = cell_range
        return (right - left + 1) * (top - bottom + 1)

    @staticmethod
    def _iter_cells(cell_range: tuple[int, int, int, int]) -> Iterable[tuple[int, int]]:
        left, bottom, right, top = cell_range
        for x in range(left, right + 1):
            for y in range(bottom, top + 1):
                yield (x, y)
