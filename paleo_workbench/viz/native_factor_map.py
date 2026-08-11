"""Native factor-map scene assembled from immutable interpolation results.

Scientific interpolation produces :class:`FactorGridResult` exactly once. This module
only transfers the resulting grid into the C++ ``ScalarGridLayer`` and changes display
state thereafter; it deliberately contains no interpolation imports or calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import grid_render_core
import layer_model_core
import numpy as np

from paleo_workbench.catalog.grid_artifact import read_grid_artifact
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task
from paleo_workbench.viz.grid_render import default_rgba_lut
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "ContourGeometry",
    "MapScene",
    "NativeMapScene",
    "PointGeometry",
    "scene_from_factor_task",
]


def _rgba_lut(values: np.ndarray) -> np.ndarray:
    ramp = np.ascontiguousarray(values, dtype=np.uint8)
    if ramp.ndim != 2:
        raise ValueError("color_ramp must be a 2-D RGB or RGBA array")
    if ramp.shape[1] == 4 and ramp.shape[0] >= 1:
        return ramp
    if ramp.shape[1] == 3 and ramp.shape[0] >= 1:
        rgba = np.empty((ramp.shape[0], 4), dtype=np.uint8)
        rgba[:, :3] = ramp
        rgba[:, 3] = 255
        return rgba
    raise ValueError("color_ramp must be a non-empty (N, 3) or (N, 4) uint8 array")


@dataclass(frozen=True, slots=True)
class ContourGeometry:
    """Display-only contour geometry in the grid's declared coordinate space."""

    paths: tuple[tuple[tuple[float, float], ...], ...]
    color: tuple[int, int, int, int] = (230, 230, 230, 220)
    width: float = 1.0


@dataclass(frozen=True, slots=True)
class PointGeometry:
    """Display-only sample points in the grid's declared coordinate space."""

    points: tuple[tuple[float, float], ...]
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    radius: float = 3.0


class MapScene:
    """Generic composition state backed by C++ registry and native grid payloads.

    ``LayerRegistry`` owns membership, hierarchy, ordering, visibility, opacity and
    metadata. Each native ``ScalarGridLayer`` owns the transferred float32 payload,
    native raster cache, and grid-specific colour style. Contours and sample points are
    lightweight vector geometry consumed by the Qt host canvas.
    """

    def __init__(self, registry=None):
        self.registry = registry or layer_model_core.LayerRegistry()
        self._scalars: dict[str, grid_render_core.ScalarGridLayer] = {}
        self._contours: dict[str, ContourGeometry] = {}
        self._points: dict[str, PointGeometry] = {}
        self._vectors: dict[str, tuple[dict, ...]] = {}
        self._vector_styles: dict[str, dict] = {}
        self._change_listeners: list[Callable[[], None]] = []

    def add_change_listener(self, listener: Callable[[], None]) -> None:
        if listener not in self._change_listeners:
            self._change_listeners.append(listener)

    def remove_change_listener(self, listener: Callable[[], None]) -> None:
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)

    def _emit_changed(self) -> None:
        for listener in tuple(self._change_listeners):
            listener()

    def add_factor_grid(
        self,
        result: FactorGridResult,
        *,
        layer_id: str,
        name: str | None = None,
        source_ref: str = "",
        parent_id: str = "",
        color_ramp: np.ndarray | None = None,
        color_range: tuple[float, float] | None = None,
        gamma: float = 1.0,
    ):
        """Transfer a finished factor grid into a native scalar layer.

        This consumes a completed result only. It cannot invoke or schedule
        interpolation, which makes style/viewport operations scientifically inert.
        """
        if not isinstance(result, FactorGridResult):
            raise TypeError("result must be a FactorGridResult")
        native_layer = grid_render_core.ScalarGridLayer(result.grid_z, result.mask)
        ramp = _rgba_lut(default_rgba_lut() if color_ramp is None else color_ramp)
        native_layer.set_color_ramp(ramp)
        if color_range is None:
            lo, hi = result.statistics.min, result.statistics.max
            if not (np.isfinite(lo) and np.isfinite(hi) and hi >= lo):
                # An all-nodata grid stays transparent, but the native style must
                # still have a finite deterministic range for later data replacement.
                lo, hi = 0.0, 1.0
        else:
            lo, hi = color_range
        native_layer.set_color_range(float(lo), float(hi))
        native_layer.set_gamma(float(gamma))

        map_layer = self.registry.add_layer(
            layer_id,
            name or result.factor_name or layer_id,
            layer_model_core.LayerType.ScalarGrid,
            parent_id,
        )
        map_layer.extent = result.extent
        map_layer.crs = result.crs or ""
        map_layer.source_ref = source_ref
        map_layer.set_provenance_ref(result.run_ref or "")
        map_layer.set_metadata("algorithm_id", result.algorithm_id)
        self._scalars[layer_id] = native_layer
        self._emit_changed()
        return map_layer

    def add_vector_layer(
        self,
        layer_id: str,
        features: Iterable[dict],
        *,
        name: str = "Vector",
        extent: tuple[float, float, float, float],
        crs: str = "",
        source_ref: str = "",
        parent_id: str = "",
        style: dict | None = None,
    ):
        """Add host-owned vector features while keeping hierarchy in LayerRegistry.

        The feature payload is deliberately separate from the registry metadata just
        like scalar-grid data. It is a short-lived render mirror until Phase 3's
        authoritative VectorLayer/EditSession replaces legacy document records.
        """
        layer = self.registry.add_layer(
            layer_id, name, layer_model_core.LayerType.Vector, parent_id
        )
        layer.extent = extent
        layer.crs = crs
        layer.source_ref = source_ref
        self._vectors[layer_id] = tuple(dict(feature) for feature in features)
        self._vector_styles[layer_id] = dict(style or {})
        self._emit_changed()
        return layer

    def vector_features(self, layer_id: str) -> tuple[dict, ...]:
        return self._vectors.get(layer_id, ())

    def vector_style(self, layer_id: str) -> dict:
        return dict(self._vector_styles.get(layer_id, {}))

    def set_vector_features(
        self,
        layer_id: str,
        features: Iterable[dict],
        *,
        extent: tuple[float, float, float, float] | None = None,
    ) -> bool:
        layer = self.registry.get(layer_id)
        if layer is None or layer_id not in self._vectors:
            return False
        next_features = tuple(dict(feature) for feature in features)
        if next_features == self._vectors[layer_id] and extent is None:
            return False
        self._vectors[layer_id] = next_features
        if extent is not None:
            layer.extent = extent
        layer.bump_data_revision()
        self._emit_changed()
        return True

    def set_vector_style(self, layer_id: str, style: dict) -> bool:
        layer = self.registry.get(layer_id)
        if layer is None or layer_id not in self._vectors:
            return False
        next_style = dict(style)
        if next_style == self._vector_styles.get(layer_id, {}):
            return False
        self._vector_styles[layer_id] = next_style
        layer.bump_style_revision()
        self._emit_changed()
        return True

    def add_factor_grid_artifact(
        self,
        artifact_path: Path | str,
        *,
        layer_id: str,
        name: str | None = None,
        parent_id: str = "",
        color_ramp: np.ndarray | None = None,
        color_range: tuple[float, float] | None = None,
        gamma: float = 1.0,
    ):
        """Read a managed artifact and transfer it directly into a scalar layer."""
        path = Path(artifact_path)
        result = read_grid_artifact(path)
        return self.add_factor_grid(
            result,
            layer_id=layer_id,
            name=name,
            source_ref=str(path),
            parent_id=parent_id,
            color_ramp=color_ramp,
            color_range=color_range,
            gamma=gamma,
        )

    def scalar_layer(self, layer_id: str):
        return self._scalars.get(layer_id)

    def raster_rgba(self, layer_id: str) -> np.ndarray:
        scalar = self._scalars.get(layer_id)
        if scalar is None:
            raise KeyError(f"no scalar grid payload for layer {layer_id!r}")
        return scalar.rasterize()

    def scalar_raster_key(self, layer_id: str) -> tuple[int, int]:
        scalar = self._scalars.get(layer_id)
        if scalar is None:
            raise KeyError(f"no scalar grid payload for layer {layer_id!r}")
        return (scalar.data_revision, scalar.style_revision)

    def set_scalar_style(
        self,
        layer_id: str,
        *,
        color_ramp: np.ndarray | None = None,
        color_range: tuple[float, float] | None = None,
        gamma: float | None = None,
    ) -> bool:
        """Apply native display style without changing any scientific input."""
        scalar = self._scalars.get(layer_id)
        map_layer = self.registry.get(layer_id)
        if scalar is None or map_layer is None:
            return False
        before = scalar.style_revision
        if color_ramp is not None:
            scalar.set_color_ramp(_rgba_lut(color_ramp))
        if color_range is not None:
            scalar.set_color_range(float(color_range[0]), float(color_range[1]))
        if gamma is not None:
            scalar.set_gamma(float(gamma))
        if scalar.style_revision == before:
            return False
        # Record a single metadata-layer style change for composition/cache clients.
        map_layer.bump_style_revision()
        self._emit_changed()
        return True

    def set_scalar_data(
        self,
        layer_id: str,
        grid_z: np.ndarray,
        *,
        mask: np.ndarray | None = None,
    ) -> bool:
        """Replace an already-computed grid payload; this is a data change, not interpolation."""
        scalar = self._scalars.get(layer_id)
        map_layer = self.registry.get(layer_id)
        if scalar is None or map_layer is None:
            return False
        before = scalar.data_revision
        scalar.set_grid(np.ascontiguousarray(grid_z, dtype=np.float32))
        if mask is not None:
            scalar.set_mask(np.ascontiguousarray(mask, dtype=np.uint8))
        if scalar.data_revision == before:
            return False
        map_layer.bump_data_revision()
        self._emit_changed()
        return True

    def set_layer_opacity(self, layer_id: str, opacity: float) -> bool:
        layer = self.registry.get(layer_id)
        if layer is None:
            return False
        before = layer.style_revision
        layer.opacity = float(opacity)
        changed = layer.style_revision != before
        if changed:
            self._emit_changed()
        return changed

    def add_contours(
        self,
        layer_id: str,
        paths: Iterable[Iterable[tuple[float, float]]],
        *,
        name: str = "等值线",
        extent: tuple[float, float, float, float],
        crs: str = "",
        parent_id: str = "",
        color: tuple[int, int, int, int] = (230, 230, 230, 220),
        width: float = 1.0,
    ):
        geometry = ContourGeometry(
            paths=tuple(tuple((float(x), float(y)) for x, y in path) for path in paths),
            color=tuple(int(value) for value in color),
            width=float(width),
        )
        layer = self.registry.add_layer(
            layer_id, name, layer_model_core.LayerType.Contour, parent_id
        )
        layer.extent = extent
        layer.crs = crs
        self._contours[layer_id] = geometry
        self._emit_changed()
        return layer

    def add_contour_draft(
        self,
        draft,
        *,
        source_layer_id: str,
        layer_id: str | None = None,
        parent_id: str = "",
    ):
        """Attach already-generated contour geometry; never recompute contours or grids."""
        source = self.registry.get(source_layer_id)
        if source is None:
            raise KeyError(f"source scalar layer {source_layer_id!r} does not exist")
        paths = [
            segment.coordinates
            for segment in list(getattr(draft, "segments", None) or [])
            if len(getattr(segment, "coordinates", None) or []) >= 2
        ]
        return self.add_contours(
            layer_id or str(getattr(draft, "id", "") or f"{source_layer_id}:contours"),
            paths,
            name=str(getattr(draft, "name", "") or "等值线"),
            extent=source.extent,
            crs=source.crs,
            parent_id=parent_id,
        )

    def add_sample_points(
        self,
        layer_id: str,
        points: Iterable[tuple[float, float]],
        *,
        name: str = "样点",
        extent: tuple[float, float, float, float],
        crs: str = "",
        parent_id: str = "",
        color: tuple[int, int, int, int] = (255, 255, 255, 255),
        radius: float = 3.0,
    ):
        geometry = PointGeometry(
            points=tuple((float(x), float(y)) for x, y in points),
            color=tuple(int(value) for value in color),
            radius=float(radius),
        )
        layer = self.registry.add_layer(
            layer_id, name, layer_model_core.LayerType.Point, parent_id
        )
        layer.extent = extent
        layer.crs = crs
        self._points[layer_id] = geometry
        self._emit_changed()
        return layer

    def contour_geometry(self, layer_id: str) -> ContourGeometry | None:
        return self._contours.get(layer_id)

    def point_geometry(self, layer_id: str) -> PointGeometry | None:
        return self._points.get(layer_id)

    def render_snapshot(self, *, project_crs: str = "") -> MapRenderSnapshot:
        """Export the authoritative composition order as an immutable render input."""
        layers: list[MapLayerSnapshot] = []
        for map_layer in self.registry.layers():
            layer_id = map_layer.id
            if map_layer.type == layer_model_core.LayerType.Group:
                continue
            features: tuple[dict, ...] = ()
            style: dict = {}
            layer_type = "scalar_grid" if layer_id in self._scalars else "vector"
            if layer_id in self._vectors:
                features = self._vectors[layer_id]
                style = self._vector_styles.get(layer_id, {})
            elif layer_id in self._contours:
                contour = self._contours[layer_id]
                features = tuple(
                    {
                        "id": f"{layer_id}:{index}",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [list(point) for point in path],
                        },
                        "properties": {},
                    }
                    for index, path in enumerate(contour.paths)
                    if len(path) >= 2
                )
                style = {
                    "fill": "transparent",
                    "stroke": "#%02x%02x%02x" % contour.color[:3],
                    "stroke_width": contour.width,
                }
            elif layer_id in self._points:
                points = self._points[layer_id]
                features = tuple(
                    {
                        "id": f"{layer_id}:{index}",
                        "geometry": {"type": "Point", "coordinates": list(point)},
                        "properties": {},
                    }
                    for index, point in enumerate(points.points)
                )
                style = {
                    "fill": "#%02x%02x%02x" % points.color[:3],
                    "marker_size": points.radius * 2.0,
                }
            layers.append(
                MapLayerSnapshot(
                    id=layer_id,
                    name=map_layer.name,
                    layer_type=layer_type,
                    extent=tuple(map_layer.extent),
                    crs=map_layer.crs,
                    data_revision=map_layer.data_revision,
                    style_revision=map_layer.style_revision,
                    features=features,
                    style=style,
                    visible=map_layer.visible,
                    opacity=map_layer.opacity,
                )
            )
        return MapRenderSnapshot(project_crs=project_crs, layers=tuple(layers))

    def remove_layer(self, layer_id: str) -> bool:
        removed = self.registry.remove_layer(layer_id)
        if removed:
            self._scalars.pop(layer_id, None)
            self._contours.pop(layer_id, None)
            self._points.pop(layer_id, None)
            self._vectors.pop(layer_id, None)
            self._vector_styles.pop(layer_id, None)
            self._emit_changed()
        return removed

    def extent(self) -> tuple[float, float, float, float]:
        extents = [
            layer.extent
            for layer in self.registry.layers()
            if layer.extent[0] < layer.extent[2] and layer.extent[1] < layer.extent[3]
        ]
        if not extents:
            return (0.0, 0.0, 1.0, 1.0)
        return (
            min(extent[0] for extent in extents),
            min(extent[1] for extent in extents),
            max(extent[2] for extent in extents),
            max(extent[3] for extent in extents),
        )


def scene_from_factor_task(
    task,
    *,
    crs: str | None = None,
    contour_drafts: Iterable[object] = (),
) -> NativeMapScene:
    """Create a native scene from a completed task without rerunning interpolation.

    A task-side managed artifact reference is preferred automatically.  The inline-grid
    adapter remains only for opening legacy projects before their next save migrates it.
    """
    params = dict(getattr(task, "parameters", None) or {})
    result = factor_grid_result_for_task(task, crs=crs)
    scene = NativeMapScene()
    task_id = str(getattr(task, "id", "") or "factor_grid")
    outputs = list(getattr(task, "output_resource_ids", None) or [])
    group_id = f"{task_id}:group"
    scene.registry.add_layer(
        group_id,
        str(getattr(task, "name", "") or result.factor_name),
        layer_model_core.LayerType.Group,
    )
    scene.add_factor_grid(
        result,
        layer_id=task_id,
        name=str(getattr(task, "name", "") or result.factor_name),
        source_ref=(
            str(getattr(task, "grid_artifact_version_id", "") or "")
            or str(getattr(task, "grid_artifact_path", "") or "")
            or (str(outputs[0]) if outputs else task_id)
        ),
        parent_id=group_id,
    )
    points = []
    for sample in params.get("sample_points") or []:
        try:
            points.append((float(sample["x"]), float(sample["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    if points:
        scene.add_sample_points(
            f"{task_id}:samples",
            points,
            extent=result.extent,
            crs=crs or "",
            parent_id=group_id,
        )
    for draft in contour_drafts:
        if getattr(draft, "linked_factor_task_id", None) == task_id:
            scene.add_contour_draft(draft, source_layer_id=task_id, parent_id=group_id)
    return scene


# Backward-compatible import name from PR #357.  The former name described only its
# first producer; MapScene is now the generic composition boundary.
NativeMapScene = MapScene
