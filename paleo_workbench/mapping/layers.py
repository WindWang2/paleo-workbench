"""Mapping Engine 2.0: Polymorphic layer hierarchy and unified MapDocument model.

Data models remain UI-independent, deterministic, and serializable.
"""

from __future__ import annotations

from abc import ABC
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

import numpy as np

from paleo_workbench.mapping.color_ramps import ColorRamp, get_color_ramp

try:
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot, MapRenderSnapshot
except (ImportError, Exception):  # pragma: no cover
    MapLayerSnapshot = Any  # type: ignore[assignment,misc]
    MapRenderSnapshot = Any  # type: ignore[assignment,misc]

from paleo_workbench.mapping.map_styles import (
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    default_style_for,
    style_dict_revision,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult, NODATA


class LayerType(str, Enum):
    VECTOR = "vector"
    GRID = "grid"
    CONTOUR = "contour"
    WELL_POINT = "well_point"
    POLYGON = "polygon"
    FACIES = "facies"
    RASTER = "raster"
    SCALAR_GRID = "scalar_grid"
    RASTER_SOURCE = "raster_source"
    ANNOTATION = "annotation"


def _generate_layer_id(prefix: str = "layer") -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


@dataclass
class MapLayer(ABC):
    """Base class for all GIS and cartographic layers in Mapping Engine 2.0."""

    id: str = field(default_factory=lambda: _generate_layer_id("lyr"))
    name: str = "Untitled Layer"
    layer_type: str = "vector"
    extent: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    crs: str = ""
    data_revision: int = 1
    style_revision: int = 1
    visible: bool = True
    opacity: float = 1.0
    scale_range: tuple[float, float] | None = None
    style: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_version_id: str = ""

    def bump_data_revision(self) -> int:
        self.data_revision += 1
        return self.data_revision

    def bump_style_revision(self) -> int:
        self.style_revision += 1
        return self.style_revision

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        self.bump_style_revision()

    def set_opacity(self, opacity: float) -> None:
        self.opacity = max(0.0, min(1.0, float(opacity)))
        self.bump_style_revision()

    def to_snapshot(self) -> MapLayerSnapshot:
        """Convert layer into the immutable renderer-facing MapLayerSnapshot."""
        return MapLayerSnapshot(
            id=self.id,
            name=self.name,
            layer_type=self.layer_type,
            extent=self.extent,
            crs=self.crs,
            data_revision=self.data_revision,
            style_revision=self.style_revision,
            features=(),
            style=dict(self.style),
            visible=self.visible,
            opacity=self.opacity,
            source_version_id=self.source_version_id,
            metadata=dict(self.metadata),
            scale_range=self.scale_range,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "layer_type": self.layer_type,
            "extent": list(self.extent),
            "crs": self.crs,
            "data_revision": self.data_revision,
            "style_revision": self.style_revision,
            "visible": self.visible,
            "opacity": self.opacity,
            "scale_range": list(self.scale_range) if self.scale_range is not None else None,
            "style": dict(self.style),
            "metadata": dict(self.metadata),
            "source_version_id": self.source_version_id,
        }


@dataclass
class VectorMapLayer(MapLayer):
    """Generic vector feature layer supporting Points, Lines, and Polygons."""

    layer_type: str = "vector"
    features: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.style:
            self.style = default_style_for("line").to_dict()
        if self.features and self.extent == (0.0, 0.0, 1.0, 1.0):
            self.recompute_extent()

    def set_features(self, features: Iterable[Mapping[str, Any]]) -> None:
        self.features = tuple(features)
        self.recompute_extent()
        self.bump_data_revision()

    def recompute_extent(self) -> tuple[float, float, float, float]:
        coords: list[tuple[float, float]] = []

        def extract_pts(geom: object) -> None:
            if isinstance(geom, Mapping):
                extract_pts(geom.get("coordinates"))
            elif isinstance(geom, (list, tuple)):
                if len(geom) >= 2 and isinstance(geom[0], (int, float)) and isinstance(geom[1], (int, float)):
                    coords.append((float(geom[0]), float(geom[1])))
                else:
                    for item in geom:
                        extract_pts(item)

        for f in self.features:
            geom = f.get("geometry") if isinstance(f, Mapping) else None
            if geom:
                extract_pts(geom)

        if not coords:
            self.extent = (0.0, 0.0, 1.0, 1.0)
            return self.extent
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        pad = max(1.0, abs(xmin), abs(ymin), abs(xmax), abs(ymax)) * 1e-6
        if math.isclose(xmin, xmax):
            xmin -= pad
            xmax += pad
        if math.isclose(ymin, ymax):
            ymin -= pad
            ymax += pad
        self.extent = (xmin, ymin, xmax, ymax)
        return self.extent

    def to_snapshot(self) -> MapLayerSnapshot:
        return MapLayerSnapshot(
            id=self.id,
            name=self.name,
            layer_type=self.layer_type,
            extent=self.extent,
            crs=self.crs,
            data_revision=self.data_revision,
            style_revision=self.style_revision,
            features=self.features,
            style=dict(self.style),
            visible=self.visible,
            opacity=self.opacity,
            source_version_id=self.source_version_id,
            metadata=dict(self.metadata),
            scale_range=self.scale_range,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["features"] = [dict(f) for f in self.features]
        return d


@dataclass
class GridMapLayer(MapLayer):
    """Continuous scalar raster / grid layer produced by spatial interpolation."""

    layer_type: str = "grid"
    grid_result: FactorGridResult | None = None
    grid_z: np.ndarray | None = None
    grid_x: np.ndarray | None = None
    grid_y: np.ndarray | None = None
    color_ramp_name: str = "viridis"
    value_range: tuple[float, float] | None = None
    unit: str = ""
    nodata: float = NODATA

    def __post_init__(self) -> None:
        if self.grid_result is not None:
            self._sync_from_grid_result()
        elif self.grid_z is not None and self.grid_x is not None and self.grid_y is not None:
            self.extent = (
                float(np.min(self.grid_x)),
                float(np.min(self.grid_y)),
                float(np.max(self.grid_x)),
                float(np.max(self.grid_y)),
            )
            if self.value_range is None:
                finite = self.grid_z[np.isfinite(self.grid_z)]
                if finite.size > 0:
                    self.value_range = (float(np.min(finite)), float(np.max(finite)))

        if not self.style:
            self.style = {
                "color_ramp": self.color_ramp_name,
                "value_range": list(self.value_range) if self.value_range is not None else None,
                "unit": self.unit,
                "opacity": self.opacity,
            }

    def _sync_from_grid_result(self) -> None:
        assert self.grid_result is not None
        self.grid_z = self.grid_result.grid_z
        self.grid_x = self.grid_result.grid_x
        self.grid_y = self.grid_result.grid_y
        self.extent = self.grid_result.extent
        self.crs = self.grid_result.crs or self.crs
        self.unit = self.grid_result.unit or self.unit
        stats = self.grid_result.statistics
        if math.isfinite(stats.min) and math.isfinite(stats.max):
            self.value_range = (stats.min, stats.max)

    def set_grid_result(self, result: FactorGridResult) -> None:
        self.grid_result = result
        self._sync_from_grid_result()
        self.bump_data_revision()

    def set_color_ramp(self, ramp_name: str) -> None:
        self.color_ramp_name = str(ramp_name)
        self.style["color_ramp"] = self.color_ramp_name
        self.bump_style_revision()

    def set_value_range(self, vmin: float, vmax: float) -> None:
        self.value_range = (float(vmin), float(vmax))
        self.style["value_range"] = [float(vmin), float(vmax)]
        self.bump_style_revision()

    def rasterize_rgba(self) -> np.ndarray:
        """Rasterize the scalar grid to an (H, W, 4) uint8 RGBA buffer using the color ramp."""
        if self.grid_z is None:
            return np.zeros((1, 1, 4), dtype=np.uint8)
        h, w = self.grid_z.shape
        ramp = get_color_ramp(self.color_ramp_name)
        vmin, vmax = self.value_range if self.value_range is not None else (0.0, 1.0)
        span = vmax - vmin if (vmax > vmin) else 1.0

        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        # Fast lookup table
        table = np.array(ramp.sample_table(256), dtype=np.uint8)  # (256, 4)

        finite = np.isfinite(self.grid_z)
        if not finite.any():
            return rgba

        norm = np.zeros_like(self.grid_z)
        if finite.any():
            norm[finite] = np.clip((self.grid_z[finite] - vmin) / span, 0.0, 1.0)
        indices = (norm * 255.0).astype(np.int32)
        indices[~finite] = 0

        rgba[finite] = table[indices[finite]]
        return rgba

    def to_snapshot(self) -> MapLayerSnapshot:
        # Provide a duck-typed scalar raster mirror payload
        class _ScalarPayload:
            def __init__(self, layer: GridMapLayer):
                self._layer = layer
            def rasterize(self) -> np.ndarray:
                return self._layer.rasterize_rgba()

        return MapLayerSnapshot(
            id=self.id,
            name=self.name,
            layer_type="scalar_grid",
            extent=self.extent,
            crs=self.crs,
            data_revision=self.data_revision,
            style_revision=self.style_revision,
            features=(),
            style=dict(self.style),
            visible=self.visible,
            opacity=self.opacity,
            renderer_payload=_ScalarPayload(self),
            source_version_id=self.source_version_id,
            metadata=dict(self.metadata),
            scale_range=self.scale_range,
        )


@dataclass
class ContourMapLayer(VectorMapLayer):
    """Contour lines generated from a scalar grid."""

    layer_type: str = "contour"
    levels: list[float] = field(default_factory=list)
    contour_interval: float | None = None
    show_labels: bool = True

    def __post_init__(self) -> None:
        if not self.style:
            self.style = default_style_for("contour").to_dict()
            if not self.style.get("labels"):
                self.style["labels"] = TextStyle(field="level", size=8.0, color="#f8f9fa").to_dict()
        super().__post_init__()


@dataclass
class WellPointMapLayer(VectorMapLayer):
    """Point layer representing well locations and attribute values."""

    layer_type: str = "well_point"
    factor_name: str = ""
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.style:
            self.style = VectorStyle(
                fill="#22b8a7",
                stroke="#182431",
                stroke_width=1.0,
                marker=MarkerSymbol.WELL,
                marker_size=8.0,
                labels=TextStyle(field="name", size=9.0, color="#ffffff"),
            ).to_dict()
        super().__post_init__()


@dataclass
class PolygonMapLayer(VectorMapLayer):
    """Polygon zone or geological facies classification layer."""

    layer_type: str = "polygon"
    categories: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.style:
            self.style = default_style_for("facies").to_dict()
        super().__post_init__()


@dataclass
class AnnotationMapLayer(VectorMapLayer):
    """Text labels, coordinate annotations, and cartographic callouts."""

    layer_type: str = "annotation"
    annotations: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.style:
            self.style = default_style_for("annotation").to_dict()
        if self.annotations and not self.features:
            self._sync_features_from_annotations()
        super().__post_init__()

    def _sync_features_from_annotations(self) -> None:
        feat_list: list[dict[str, Any]] = []
        for idx, ann in enumerate(self.annotations):
            x = float(ann.get("x", ann.get("longitude", 0.0)))
            y = float(ann.get("y", ann.get("latitude", 0.0)))
            text = str(ann.get("text", ann.get("label", "")))
            props = dict(ann)
            props.setdefault("text", text)
            feat_list.append({
                "type": "Feature",
                "id": str(ann.get("id", f"ann_{idx}")),
                "geometry": {
                    "type": "Point",
                    "coordinates": [x, y],
                },
                "properties": props,
            })
        self.features = tuple(feat_list)

    def add_annotation(
        self,
        text: str,
        x: float,
        y: float,
        font_size: float = 10.0,
        color: str = "#f8f9fa",
        rotation: float = 0.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Add an annotation text item with coordinates, style and rotation."""
        ann_item: dict[str, Any] = {
            "id": f"ann_{uuid4().hex[:6]}",
            "text": str(text),
            "x": float(x),
            "y": float(y),
            "font_size": float(font_size),
            "color": str(color),
            "rotation": float(rotation),
            **kwargs,
        }
        self.annotations = (*self.annotations, ann_item)
        self._sync_features_from_annotations()
        self.recompute_extent()
        self.bump_data_revision()
        return ann_item

    def set_annotations(self, annotations: Iterable[Mapping[str, Any]]) -> None:
        """Replace all annotations."""
        self.annotations = tuple(dict(a) for a in annotations)
        self._sync_features_from_annotations()
        self.recompute_extent()
        self.bump_data_revision()

    def clear_annotations(self) -> None:
        """Clear all annotations."""
        self.annotations = ()
        self.features = ()
        self.recompute_extent()
        self.bump_data_revision()

    def to_snapshot(self) -> MapLayerSnapshot:
        if self.annotations and not self.features:
            self._sync_features_from_annotations()
        return MapLayerSnapshot(
            id=self.id,
            name=self.name,
            layer_type="annotation",
            extent=self.extent,
            crs=self.crs,
            data_revision=self.data_revision,
            style_revision=self.style_revision,
            features=self.features,
            style=dict(self.style),
            visible=self.visible,
            opacity=self.opacity,
            source_version_id=self.source_version_id,
            metadata=dict(self.metadata),
            scale_range=self.scale_range,
        )

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["annotations"] = [dict(a) for a in self.annotations]
        return d


@dataclass
class RasterMapLayer(MapLayer):
    """External or georeferenced raster image layer."""

    layer_type: str = "raster_source"
    source_path: str = ""

    def to_snapshot(self) -> MapLayerSnapshot:
        return MapLayerSnapshot(
            id=self.id,
            name=self.name,
            layer_type="raster_source",
            extent=self.extent,
            crs=self.crs,
            data_revision=self.data_revision,
            style_revision=self.style_revision,
            features=(),
            style=dict(self.style),
            visible=self.visible,
            opacity=self.opacity,
            renderer_payload=self.source_path,
            source_version_id=self.source_version_id,
            metadata=dict(self.metadata),
            scale_range=self.scale_range,
        )


@dataclass
class MapDocument:
    """Mapping Engine 2.0: Canonical Map Document.
    
    Represents the full multi-layer map, coordinate system, extent, and metadata.
    Shared across Map Canvas, Layer Manager, and Map Composer.
    """

    id: str = field(default_factory=lambda: f"map_{uuid4().hex[:8]}")
    title: str = "Paleogeographic Map"
    crs: str = "EPSG:4326"
    extent: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    layers: list[MapLayer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    active_layer_id: str | None = None

    @property
    def input_version_ids(self) -> list[str]:
        """Aggregate input version IDs from metadata and individual layer sources."""
        vids: list[str] = list(self.metadata.get("input_version_ids") or [])
        for lyr in self.layers:
            if lyr.source_version_id and lyr.source_version_id not in vids:
                vids.append(lyr.source_version_id)
        return vids

    @input_version_ids.setter
    def input_version_ids(self, ids: list[str]) -> None:
        self.metadata["input_version_ids"] = list(ids)

    @property
    def run_id(self) -> str | None:
        """Producing DataRun ID stored in metadata, if available."""
        return self.metadata.get("run_id")

    @run_id.setter
    def run_id(self, val: str | None) -> None:
        self.metadata["run_id"] = val

    def add_layer(self, layer: MapLayer, position: int | None = None) -> MapLayer:
        """Add a layer to the document."""
        if position is not None and 0 <= position <= len(self.layers):
            self.layers.insert(position, layer)
        else:
            self.layers.append(layer)
        if not self.active_layer_id:
            self.active_layer_id = layer.id
        self.recompute_extent()
        return layer

    def remove_layer(self, layer_id: str) -> MapLayer | None:
        """Remove a layer by id."""
        for idx, lyr in enumerate(self.layers):
            if lyr.id == layer_id:
                removed = self.layers.pop(idx)
                if self.active_layer_id == layer_id:
                    self.active_layer_id = self.layers[0].id if self.layers else None
                self.recompute_extent()
                return removed
        return None

    def get_layer(self, layer_id: str) -> MapLayer | None:
        """Find a layer by id."""
        for lyr in self.layers:
            if lyr.id == layer_id:
                return lyr
        return None

    def reorder_layers(self, layer_ids: Sequence[str]) -> None:
        """Reorder layers to match the given sequence of layer IDs."""
        id_to_layer = {lyr.id: lyr for lyr in self.layers}
        new_layers = []
        for lid in layer_ids:
            if lid in id_to_layer:
                new_layers.append(id_to_layer.pop(lid))
        # Append any remaining layers not in the sequence
        new_layers.extend(id_to_layer.values())
        self.layers = new_layers

    def recompute_extent(self) -> tuple[float, float, float, float]:
        """Aggregate visible layer extents."""
        valid_extents = [
            lyr.extent for lyr in self.layers
            if lyr.visible and lyr.extent and len(lyr.extent) == 4 and lyr.extent != (0.0, 0.0, 1.0, 1.0)
        ]
        if not valid_extents:
            return self.extent
        xmins = [e[0] for e in valid_extents]
        ymins = [e[1] for e in valid_extents]
        xmaxs = [e[2] for e in valid_extents]
        ymaxs = [e[3] for e in valid_extents]
        self.extent = (min(xmins), min(ymins), max(xmaxs), max(ymaxs))
        return self.extent

    def to_snapshot(self) -> MapRenderSnapshot:
        """Generate immutable snapshot for render backends."""
        snapshots = tuple(lyr.to_snapshot() for lyr in self.layers)
        return MapRenderSnapshot(project_crs=self.crs, layers=snapshots)

    @classmethod
    def from_snapshot(cls, snapshot: MapRenderSnapshot, title: str = "Map") -> "MapDocument":
        doc = cls(title=title, crs=snapshot.project_crs)
        for s in snapshot.layers:
            if s.layer_type in ("scalar_grid", "grid"):
                lyr = GridMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                )
            elif s.layer_type == "annotation":
                lyr = AnnotationMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    features=s.features,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            elif s.layer_type == "contour":
                lyr = ContourMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    features=s.features,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            elif s.layer_type in ("well_point", "well"):
                lyr = WellPointMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    features=s.features,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            elif s.layer_type in ("polygon", "facies"):
                lyr = PolygonMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    features=s.features,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            elif s.layer_type == "raster_source":
                lyr = RasterMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    source_path=str(s.renderer_payload or ""),
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            else:
                lyr = VectorMapLayer(
                    id=s.id,
                    name=s.name,
                    extent=s.extent,
                    crs=s.crs,
                    data_revision=s.data_revision,
                    style_revision=s.style_revision,
                    visible=s.visible,
                    opacity=s.opacity,
                    features=s.features,
                    style=dict(s.style),
                    metadata=dict(s.metadata),
                    scale_range=s.scale_range,
                )
            doc.layers.append(lyr)
        doc.recompute_extent()
        return doc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "crs": self.crs,
            "extent": list(self.extent),
            "layers": [lyr.to_dict() for lyr in self.layers],
            "metadata": dict(self.metadata),
            "active_layer_id": self.active_layer_id,
        }
