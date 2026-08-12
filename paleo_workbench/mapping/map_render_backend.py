"""Renderer-neutral map-frame seam for the unified authoring canvas.

Project and editing code produce immutable snapshots. Render adapters consume those
snapshots and return copied RGBA frames; neither adapter is an authority for map data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Any, Mapping

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

__all__ = [
    "FallbackMapRenderBackend",
    "MapLayerSnapshot",
    "MapRenderBackend",
    "MapRenderSnapshot",
    "QgisMapRenderBackend",
    "RenderFrame",
    "create_map_render_backend",
]


_BACKGROUND = QColor("#181c22")


@dataclass(frozen=True, slots=True)
class MapLayerSnapshot:
    """One immutable host-owned render layer.

    ``features`` use GeoJSON-compatible geometry dictionaries at the Python boundary.
    The narrow, explicit form lets render mirrors rebuild only when either revision
    changes while leaving viewport requests free of data conversion.
    """

    id: str
    name: str
    layer_type: str
    extent: tuple[float, float, float, float]
    crs: str
    data_revision: int
    style_revision: int
    features: tuple[Mapping[str, Any], ...] = ()
    style: Mapping[str, Any] = field(default_factory=dict)
    visible: bool = True
    opacity: float = 1.0
    # Renderer-only payload (for example an existing native ScalarGridLayer).
    # It is never serialized into project state or treated as scientific data.
    renderer_payload: object | None = None


@dataclass(frozen=True, slots=True)
class MapRenderSnapshot:
    """Immutable composition input from LayerRegistry/project state."""

    project_crs: str
    layers: tuple[MapLayerSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderFrame:
    """Copied RGBA output shared by QGIS and fallback adapters."""

    generation: int
    width: int
    height: int
    stride: int
    rgba: bytes
    render_ms: float


class MapRenderBackend(ABC):
    """Deep render module interface consumed by :class:`UnifiedMapCanvas`."""

    backend_name = "unknown"

    def __init__(self) -> None:
        self._initialized = False
        self._snapshot = MapRenderSnapshot(project_crs="")
        self._extent = (0.0, 0.0, 1.0, 1.0)
        self._output_size = (1, 1)
        self._dpi = 96.0
        self._generation = 0
        self._completed: RenderFrame | None = None

    @property
    def is_available(self) -> bool:
        return True

    @property
    def status(self) -> str:
        return "ready" if self._initialized else "not initialized"

    def initialize(self) -> None:
        if not self.is_available:
            raise RuntimeError(f"{self.backend_name} renderer is unavailable: {self.status}")
        self._initialized = True

    def set_layer_snapshot(self, snapshot: MapRenderSnapshot) -> None:
        if not isinstance(snapshot, MapRenderSnapshot):
            raise TypeError("snapshot must be a MapRenderSnapshot")
        self._snapshot = snapshot

    def set_extent(self, extent: tuple[float, float, float, float]) -> None:
        values = tuple(float(value) for value in extent)
        if len(values) != 4 or not all(math.isfinite(value) for value in values):
            raise ValueError("extent must contain four finite values")
        if values[2] <= values[0] or values[3] <= values[1]:
            raise ValueError("extent must have positive width and height")
        self._extent = values

    def set_output_size(self, width: int, height: int) -> None:
        if int(width) < 1 or int(height) < 1:
            raise ValueError("output size must be positive")
        self._output_size = (int(width), int(height))

    def set_dpi(self, dpi: float) -> None:
        value = float(dpi)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("dpi must be finite and positive")
        self._dpi = value

    def request_render(self) -> int:
        """Render the newest generation and discard any preceding completed frame.

        The fallback is intentionally synchronous for tiny/local test maps. The QGIS
        adapter overrides this once its native parallel job is available. In both
        cases callers observe the same latest-generation contract.
        """
        frame = self.render_sync()
        self._completed = frame
        return frame.generation

    def take_completed_frame(self) -> RenderFrame | None:
        frame = self._completed
        self._completed = None
        return frame

    @property
    def render_active(self) -> bool:
        """Whether a later poll can still produce a frame for this backend."""
        return False

    def cancel_render(self) -> None:
        self._completed = None

    @abstractmethod
    def render_sync(self) -> RenderFrame:
        """Render the current snapshot exactly once into an owned RGBA frame."""

    def identify(self, _x: float, _y: float) -> object | None:
        """Optional backend-assisted identify hook; host selection remains authoritative."""
        return None

    def shutdown(self) -> None:
        self.cancel_render()
        self._initialized = False

    def _next_generation(self) -> int:
        self._generation += 1
        return self._generation


class FallbackMapRenderBackend(MapRenderBackend):
    """Explicit minimal renderer for tests and hosts without a QGIS bridge.

    This adapter owns all direct QPainter feature painting so application pages never
    become a second rendering stack. It is intentionally limited to basic GeoJSON
    vector geometry; scalar-grid composition remains delegated to the existing native
    layer path until its QGIS mirror is introduced in the next vertical slice.
    """

    backend_name = "fallback"

    @staticmethod
    def _color(value: object, fallback: str) -> QColor:
        color = QColor(str(value or fallback))
        return color if color.isValid() else QColor(fallback)

    def _screen_point(self, point: object) -> QPointF | None:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
        xmin, ymin, xmax, ymax = self._extent
        width, height = self._output_size
        return QPointF(
            (x - xmin) * width / (xmax - xmin),
            height - (y - ymin) * height / (ymax - ymin),
        )

    def _path(self, rings: object) -> QPainterPath:
        path = QPainterPath()
        if not isinstance(rings, (list, tuple)):
            return path
        for ring in rings:
            if not isinstance(ring, (list, tuple)):
                continue
            polygon = QPolygonF()
            for point in ring:
                screen = self._screen_point(point)
                if screen is not None:
                    polygon.append(screen)
            if len(polygon) >= 3:
                path.addPolygon(polygon)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        return path

    def _draw_geometry(self, painter: QPainter, geometry: object, style: Mapping[str, Any]) -> None:
        if not isinstance(geometry, Mapping):
            return
        geometry_type = str(geometry.get("type") or "")
        coordinates = geometry.get("coordinates")
        fill = self._color(style.get("fill"), "#6c8ebf")
        stroke = self._color(style.get("stroke"), "#26364d")
        try:
            width = max(0.0, float(style.get("stroke_width", 1.0)))
        except (TypeError, ValueError):
            width = 1.0
        painter.setPen(QPen(stroke, width))
        painter.setBrush(fill)

        if geometry_type == "Point":
            center = self._screen_point(coordinates)
            if center is None:
                return
            try:
                radius = max(1.0, float(style.get("marker_size", 6.0)) / 2.0)
            except (TypeError, ValueError):
                radius = 3.0
            painter.drawEllipse(center, radius, radius)
            return
        if geometry_type == "MultiPoint" and isinstance(coordinates, (list, tuple)):
            for point in coordinates:
                self._draw_geometry(
                    painter, {"type": "Point", "coordinates": point}, style
                )
            return
        if geometry_type == "LineString":
            points = [self._screen_point(point) for point in coordinates or ()]
            valid = [point for point in points if point is not None]
            if len(valid) >= 2:
                path = QPainterPath(valid[0])
                for point in valid[1:]:
                    path.lineTo(point)
                painter.drawPath(path)
            return
        if geometry_type == "MultiLineString" and isinstance(coordinates, (list, tuple)):
            for line in coordinates:
                self._draw_geometry(
                    painter, {"type": "LineString", "coordinates": line}, style
                )
            return
        if geometry_type == "Polygon":
            painter.drawPath(self._path(coordinates))
            return
        if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
            for polygon in coordinates:
                painter.drawPath(self._path(polygon))

    def _draw_scalar_grid(self, painter: QPainter, layer: MapLayerSnapshot) -> None:
        """Composite the existing native scalar-raster cache without interpolation."""
        scalar = layer.renderer_payload
        if scalar is None or not hasattr(scalar, "rasterize"):
            return
        rgba = scalar.rasterize()
        try:
            height, width = int(rgba.shape[0]), int(rgba.shape[1])
        except (AttributeError, IndexError, TypeError, ValueError):
            return
        if height < 1 or width < 1:
            return
        image = QImage(
            rgba.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        xmin, ymin, xmax, ymax = layer.extent
        top_left = self._screen_point((xmin, ymax))
        bottom_right = self._screen_point((xmax, ymin))
        if top_left is not None and bottom_right is not None:
            painter.drawImage(QRectF(top_left, bottom_right).normalized(), image)

    def render_sync(self) -> RenderFrame:
        if not self._initialized:
            self.initialize()
        generation = self._next_generation()
        width, height = self._output_size
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(_BACKGROUND)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for layer in self._snapshot.layers:
            if not layer.visible or layer.opacity <= 0.0:
                continue
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
            if layer.layer_type == "scalar_grid":
                self._draw_scalar_grid(painter, layer)
            for feature in layer.features:
                self._draw_geometry(painter, feature.get("geometry"), layer.style)
            painter.restore()
        painter.end()
        rgba = image.constBits().tobytes()
        return RenderFrame(
            generation=generation,
            width=image.width(),
            height=image.height(),
            stride=image.bytesPerLine(),
            rgba=rgba,
            render_ms=0.0,
        )


class QgisMapRenderBackend(MapRenderBackend):
    """Optional native QGIS adapter with the same host-oriented frame contract."""

    backend_name = "qgis"

    def __init__(self) -> None:
        super().__init__()
        try:
            import qgis_render_bridge as native_bridge
        except ImportError:
            native_bridge = None
        self._native_module = native_bridge
        self._bridge = None
        self._scalar_raster_cache = None

    @property
    def is_available(self) -> bool:
        return self._native_module is not None

    @property
    def status(self) -> str:
        if self._native_module is None:
            return "unavailable: optional qgis_render_bridge is not installed"
        if self._bridge is None:
            return "available"
        return f"ready ({self._bridge.version})"

    def initialize(self) -> None:
        if self._native_module is None:
            super().initialize()
            return
        if self._bridge is None:
            self._bridge = self._native_module.QgisRenderBridge()
            self._bridge.initialize()
        self._initialized = True

    def set_layer_snapshot(self, snapshot: MapRenderSnapshot) -> None:
        super().set_layer_snapshot(snapshot)
        if self._bridge is not None:
            self._set_native_snapshot(snapshot)

    def _native_snapshot(self, snapshot: MapRenderSnapshot) -> list[dict[str, object]]:
        if any(layer.layer_type == "scalar_grid" for layer in snapshot.layers):
            if self._scalar_raster_cache is None:
                from paleo_workbench.mapping.scalar_raster_mirror import ScalarRasterMirrorCache

                self._scalar_raster_cache = ScalarRasterMirrorCache()
        encoded = _qgis_snapshot(snapshot, scalar_raster_cache=self._scalar_raster_cache)
        if self._scalar_raster_cache is not None:
            self._scalar_raster_cache.retain_layer_ids(
                {layer.id for layer in snapshot.layers if layer.layer_type == "scalar_grid"}
            )
        return encoded

    def _set_native_snapshot(self, snapshot: MapRenderSnapshot) -> None:
        assert self._bridge is not None
        self._bridge.set_layer_snapshot(self._native_snapshot(snapshot), snapshot.project_crs)
        # A replacement can arrive while QGIS still renders an old raster source.
        # It is only safe to unlink deferred /vsimem or disk sources once the bridge
        # has no active job and has applied the replacement snapshot.
        if self._scalar_raster_cache is not None and not self._bridge.render_active:
            self._scalar_raster_cache.release_stale()

    def request_render(self) -> int:
        """Request native parallel rendering; native code coalesces stale frames."""
        if not self._initialized:
            self.initialize()
        assert self._bridge is not None
        generation = self._next_generation()
        self._completed = None
        self._bridge.request_render(
            self._extent,
            self._output_size[0],
            self._output_size[1],
            self._dpi,
            generation,
        )
        return generation

    def take_completed_frame(self) -> RenderFrame | None:
        if self._bridge is None:
            return None
        payload = self._bridge.take_completed_frame()
        if self._scalar_raster_cache is not None and not self._bridge.render_active:
            self._scalar_raster_cache.release_stale()
        if payload is None:
            return None
        generation = int(payload["generation"])
        # The native bridge normally rejects stale output itself. Keep the host
        # guard too: a delayed result can never paint over a newer viewport.
        if generation != self._generation:
            return None
        return RenderFrame(
            generation=generation,
            width=int(payload["width"]),
            height=int(payload["height"]),
            stride=int(payload["stride"]),
            rgba=bytes(payload["rgba"]),
            render_ms=float(payload.get("render_ms", 0.0)),
        )

    def cancel_render(self) -> None:
        self._completed = None
        if self._bridge is not None:
            self._bridge.cancel_render()

    @property
    def render_active(self) -> bool:
        return bool(self._bridge is not None and self._bridge.render_active)

    def render_sync(self) -> RenderFrame:
        if not self._initialized:
            self.initialize()
        assert self._bridge is not None
        self._set_native_snapshot(self._snapshot)
        generation = self._next_generation()
        payload = self._bridge.render_sync(
            self._extent, self._output_size[0], self._output_size[1], self._dpi
        )
        return RenderFrame(
            generation=generation,
            width=int(payload["width"]),
            height=int(payload["height"]),
            stride=int(payload["stride"]),
            rgba=bytes(payload["rgba"]),
            render_ms=float(payload.get("render_ms", 0.0)),
        )

    def shutdown(self) -> None:
        if self._bridge is not None:
            self._bridge.shutdown()
            self._bridge = None
        if self._scalar_raster_cache is not None:
            self._scalar_raster_cache.clear()
            self._scalar_raster_cache = None
        super().shutdown()


def _qgis_snapshot(
    snapshot: MapRenderSnapshot,
    *,
    scalar_raster_cache=None,
) -> list[dict[str, object]]:
    """Encode host snapshots into the small native bridge payload."""
    layers: list[dict[str, object]] = []
    for layer in snapshot.layers:
        if layer.layer_type == "scalar_grid":
            if scalar_raster_cache is None:
                raise RuntimeError("QGIS scalar-grid rendering requires a raster mirror cache")
            layers.append(
                {
                    "id": layer.id,
                    "name": layer.name,
                    "crs": layer.crs or snapshot.project_crs,
                    "kind": "raster",
                    "source_path": scalar_raster_cache.ensure(layer),
                    "data_revision": int(layer.data_revision),
                    "style_revision": int(layer.style_revision),
                    "visible": bool(layer.visible),
                    "opacity": float(layer.opacity),
                    "features": [],
                }
            )
            continue
        if layer.layer_type == "raster_source":
            source_path = str(layer.renderer_payload or "")
            if not source_path:
                continue
            layers.append(
                {
                    "id": layer.id,
                    "name": layer.name,
                    "crs": layer.crs or snapshot.project_crs,
                    "kind": "raster",
                    "source_path": source_path,
                    "data_revision": int(layer.data_revision),
                    "style_revision": int(layer.style_revision),
                    "visible": bool(layer.visible),
                    "opacity": float(layer.opacity),
                    "features": [],
                }
            )
            continue
        if layer.layer_type != "vector":
            continue
        features = []
        for feature in layer.features:
            geometry = feature.get("geometry")
            wkt = _geometry_to_wkt(geometry)
            if wkt:
                attributes = dict(feature.get("properties") or {})
                attributes["__pwb_id"] = str(feature.get("id") or "")
                features.append(
                    {
                        "id": str(feature.get("id") or ""),
                        "wkt": wkt,
                        "attributes": attributes,
                    }
                )
        # QGIS' memory provider has no valid geometry URI for an empty generic
        # layer. Empty host categories still remain in LayerRegistry/the tree;
        # they simply need no render mirror until their first feature arrives.
        if not features:
            continue
        layers.append(
            {
                "id": layer.id,
                "name": layer.name,
                "crs": layer.crs or snapshot.project_crs,
                "data_revision": int(layer.data_revision),
                "style_revision": int(layer.style_revision),
                "visible": bool(layer.visible),
                "opacity": float(layer.opacity),
                "style": dict(layer.style),
                "features": features,
            }
        )
    return layers


def _geometry_to_wkt(geometry: object) -> str:
    """Convert supported GeoJSON geometry without introducing another geometry DTO."""
    if not isinstance(geometry, Mapping):
        return ""
    geometry_type = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")

    def point(value: object) -> str:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return ""
        try:
            return f"{float(value[0]):.17g} {float(value[1]):.17g}"
        except (TypeError, ValueError):
            return ""

    def ring(values: object) -> str:
        if not isinstance(values, (list, tuple)):
            return ""
        points = [point(value) for value in values]
        return ", ".join(value for value in points if value)

    if geometry_type == "Point":
        value = point(coordinates)
        return f"POINT ({value})" if value else ""
    if geometry_type == "MultiPoint" and isinstance(coordinates, (list, tuple)):
        values = [point(value) for value in coordinates]
        values = [value for value in values if value]
        return f"MULTIPOINT ({', '.join(values)})" if values else ""
    if geometry_type == "LineString":
        value = ring(coordinates)
        return f"LINESTRING ({value})" if value else ""
    if geometry_type == "MultiLineString" and isinstance(coordinates, (list, tuple)):
        values = [ring(value) for value in coordinates]
        values = [f"({value})" for value in values if value]
        return f"MULTILINESTRING ({', '.join(values)})" if values else ""
    if geometry_type == "Polygon" and isinstance(coordinates, (list, tuple)):
        values = [ring(value) for value in coordinates]
        values = [f"({value})" for value in values if value]
        return f"POLYGON ({', '.join(values)})" if values else ""
    if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        polygons = []
        for polygon in coordinates:
            if not isinstance(polygon, (list, tuple)):
                continue
            rings = [ring(value) for value in polygon]
            rings = [f"({value})" for value in rings if value]
            if rings:
                polygons.append(f"({', '.join(rings)})")
        return f"MULTIPOLYGON ({', '.join(polygons)})" if polygons else ""
    return ""


def create_map_render_backend(*, prefer_qgis: bool = True) -> MapRenderBackend:
    """Select QGIS only when its optional native bridge is genuinely available."""
    qgis = QgisMapRenderBackend()
    return qgis if prefer_qgis and qgis.is_available else FallbackMapRenderBackend()
