"""Renderer-neutral map-frame seam for the unified authoring canvas.

Project and editing code produce immutable snapshots. Render adapters consume those
snapshots and return copied RGBA frames; neither adapter is an authority for map data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

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


def _iter_coordinate_pairs(value: object) -> Iterable[tuple[float, float]]:
    """Yield leaf (x, y) pairs from nested GeoJSON coordinate arrays."""
    if isinstance(value, (list, tuple)) and len(value) >= 2 and not isinstance(value[0], (list, tuple)):
        try:
            yield float(value[0]), float(value[1])
        except (TypeError, ValueError):
            pass
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_coordinate_pairs(child)


class FallbackMapRenderBackend(MapRenderBackend):
    """Explicit minimal renderer for tests and hosts without a QGIS bridge.

    This adapter owns all direct QPainter feature painting so application pages never
    become a second rendering stack. It is intentionally limited to basic GeoJSON
    vector geometry; scalar-grid composition remains delegated to the existing native
    layer path until its QGIS mirror is introduced in the next vertical slice.

    Rendering is incremental: features are culled against the viewport (with cached
    per-feature bounds), and frames are reused across pan steps by blitting the
    previous frame and re-rasterizing only the newly exposed strips. A frame cache
    keyed by (layer revisions, viewport, size, dpi) short-circuits identical requests.
    """

    backend_name = "fallback"

    def __init__(self) -> None:
        super().__init__()
        # Per-layer feature bounds for viewport culling. Entries survive data
        # revision bumps: the stored geometry object is compared by value so an
        # edit only recomputes bounds for the features it actually changed.
        self._feature_bounds: dict[str, dict[str, tuple[object, tuple[float, float, float, float] | None]]] = {}
        # Last rendered frame plus its input key for pan-strip reuse.
        self._frame_cache: QImage | None = None
        self._frame_cache_key: tuple[object, ...] | None = None
        self._frame_cache_extent: tuple[float, float, float, float] | None = None
        self._frame_cache_scales: tuple[float, float] = (0.0, 0.0)
        self._rasterization_count = 0
        self._frame_cache_hits = 0
        self._strip_reuse_count = 0
        self._culled_feature_count = 0

    def fallback_diagnostics(self) -> dict[str, int]:
        """Structural counters for regression tests (never time thresholds)."""
        return {
            "rasterization_count": self._rasterization_count,
            "frame_cache_hits": self._frame_cache_hits,
            "strip_reuse_count": self._strip_reuse_count,
            "culled_feature_count": self._culled_feature_count,
        }

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
        # Exports at elevated DPI keep the same physical stroke/marker size as
        # the 96-dpi screen: cosmetic sizes scale by dpi/96 while geometry
        # positions stay in output pixels (fallback export DPI fix).
        dpi_scale = self._dpi / 96.0
        try:
            width = max(0.0, float(style.get("stroke_width", 1.0))) * dpi_scale
        except (TypeError, ValueError):
            width = 1.0 * dpi_scale
        painter.setPen(QPen(stroke, width))
        painter.setBrush(fill)

        if geometry_type == "Point":
            center = self._screen_point(coordinates)
            if center is None:
                return
            try:
                radius = max(1.0, float(style.get("marker_size", 6.0)) / 2.0) * dpi_scale
            except (TypeError, ValueError):
                radius = 3.0 * dpi_scale
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
        key = self._render_key()
        cached = self._frame_cache
        if cached is not None and key == self._frame_cache_key:
            # Identical input (layer revisions, viewport, size, dpi): the frame
            # is already current; serve it without re-rasterizing.
            self._frame_cache_hits += 1
            return self._frame_from_image(generation, cached)
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(_BACKGROUND)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        shift = self._reusable_shift() if cached is not None else None
        if shift is not None:
            # Pan at the same scale: blit the previous frame and rasterize only
            # the newly exposed strips (dirty-region reuse).
            self._strip_reuse_count += 1
            dx_px, dy_px = shift
            painter.drawImage(QPointF(-dx_px, -dy_px), cached)
            self._paint_scalar_grids(painter)
            self._paint_strips(painter, dx_px, dy_px)
        else:
            self._rasterization_count += 1
            self._paint_full(painter)
        painter.end()
        self._frame_cache = image
        self._frame_cache_key = key
        self._frame_cache_extent = self._extent
        self._frame_cache_scales = self._pixel_scales()
        return self._frame_from_image(generation, image)

    def _render_key(self) -> tuple[object, ...]:
        """Input key for the rendered-frame cache (excludes pure pan state)."""
        layers_key = tuple(
            (
                layer.id,
                layer.layer_type,
                int(layer.data_revision),
                int(layer.style_revision),
                bool(layer.visible),
                float(layer.opacity),
                tuple(float(value) for value in layer.extent),
                layer.name,
                layer.crs,
            )
            for layer in self._snapshot.layers
        )
        return (tuple(float(value) for value in self._extent), self._output_size, float(self._dpi), layers_key)

    def _pixel_scales(self) -> tuple[float, float]:
        xmin, ymin, xmax, ymax = self._extent
        width, height = self._output_size
        return (width / (xmax - xmin), height / (ymax - ymin))

    def _units_per_pixel(self) -> float:
        xmin, ymin, xmax, ymax = self._extent
        width, height = self._output_size
        return max((xmax - xmin) / max(1, width), (ymax - ymin) / max(1, height))

    def _reusable_shift(self) -> tuple[float, float] | None:
        """Pixel shift of the cached frame for a same-scale pan, or None."""
        if self._frame_cache is None or self._frame_cache_key is None:
            return None
        key = self._render_key()
        if key[1:] != self._frame_cache_key[1:]:
            # Layer revisions, output size or dpi changed: cache is stale.
            return None
        scales = self._pixel_scales()
        cached_scales = self._frame_cache_scales
        if scales[0] <= 0.0 or scales[1] <= 0.0 or cached_scales[0] <= 0.0 or cached_scales[1] <= 0.0:
            return None
        if abs(scales[0] - cached_scales[0]) > 1e-9 * max(1.0, cached_scales[0]) or (
            abs(scales[1] - cached_scales[1]) > 1e-9 * max(1.0, cached_scales[1])
        ):
            # Zoom changed the scale: full re-rasterization required.
            return None
        assert self._frame_cache_extent is not None
        xmin, ymin, _xmax, _ymax = self._extent
        c_xmin, c_ymin, _c_xmax, _c_ymax = self._frame_cache_extent
        dx_px = (xmin - c_xmin) * scales[0]
        dy_px = (ymin - c_ymin) * scales[1]
        dx, dy = round(dx_px), round(dy_px)
        if abs(dx_px - dx) > 0.05 or abs(dy_px - dy) > 0.05:
            # Non-pixel-aligned shift would blur the blit; render fresh instead.
            return None
        width, height = self._output_size
        if abs(dx) >= width or abs(dy) >= height:
            return None
        return float(dx), float(dy)

    def _layer_screen_margin(self, layer: MapLayerSnapshot) -> float:
        """Painted-pixel pad beyond a feature bbox (pen + marker + AA pad)."""
        style = dict(layer.style or {})
        try:
            stroke = max(0.0, float(style.get("stroke_width", 0.0) or 0.0))
        except (TypeError, ValueError):
            stroke = 0.0
        try:
            marker = max(0.0, float(style.get("marker_size", 0.0) or 0.0))
        except (TypeError, ValueError):
            marker = 0.0
        return stroke / 2.0 + marker / 2.0 + 2.0

    def _layer_margin_units(self, layer: MapLayerSnapshot) -> float:
        return self._layer_screen_margin(layer) * self._units_per_pixel()

    def _bounds_for_feature(
        self, layer: MapLayerSnapshot, feature: Mapping[str, Any],
    ) -> tuple[float, float, float, float] | None:
        """Cached per-feature bounds keyed by feature geometry (cull without rescan).

        The geometry object is the cache key by value, so bounds survive data
        revision bumps and are recomputed only for features an edit changed.
        """
        cache = self._feature_bounds.get(layer.id)
        if cache is None:
            cache = {}
            self._feature_bounds[layer.id] = cache
        feature_id = str(feature.get("id") or "")
        geometry = feature.get("geometry")
        cached = cache.get(feature_id)
        # Same snapshot object is the common case (identity beats deep equality).
        if cached is not None and (cached[0] is geometry or cached[0] == geometry):
            return cached[1]
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        pairs = tuple(_iter_coordinate_pairs(coordinates))
        if not pairs:
            bounds: tuple[float, float, float, float] | None = None
        else:
            xs = [pair[0] for pair in pairs]
            ys = [pair[1] for pair in pairs]
            bounds = (min(xs), min(ys), max(xs), max(ys))
        cache[feature_id] = (geometry, bounds)
        if len(cache) > 2 * max(1, len(layer.features)):
            current_ids = {str(feature.get("id") or "") for feature in layer.features}
            self._feature_bounds[layer.id] = {
                feature_id: entry for feature_id, entry in cache.items() if feature_id in current_ids
            }
        return bounds

    @staticmethod
    def _bounds_intersect(
        bounds: tuple[float, float, float, float] | None,
        view: tuple[float, float, float, float],
        margin: float,
    ) -> bool:
        if bounds is None:
            return True  # unmeasurable geometry is always painted
        xmin, ymin, xmax, ymax = view
        return not (
            bounds[2] < xmin - margin
            or bounds[0] > xmax + margin
            or bounds[3] < ymin - margin
            or bounds[1] > ymax + margin
        )

    def _paint_vector_layer(
        self,
        painter: QPainter,
        layer: MapLayerSnapshot,
        view: tuple[float, float, float, float],
        margin: float,
    ) -> None:
        for feature in layer.features:
            if not self._bounds_intersect(self._bounds_for_feature(layer, feature), view, margin):
                self._culled_feature_count += 1
                continue
            self._draw_geometry(painter, feature.get("geometry"), layer.style)

    def _paint_full(self, painter: QPainter) -> None:
        view = tuple(float(value) for value in self._extent)
        for layer in self._snapshot.layers:
            if not layer.visible or layer.opacity <= 0.0:
                continue
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
            if layer.layer_type == "scalar_grid":
                self._draw_scalar_grid(painter, layer)
            self._paint_vector_layer(painter, layer, view, self._layer_margin_units(layer))
            painter.restore()

    def _paint_scalar_grids(self, painter: QPainter) -> None:
        """Recomposite scalar rasters over a reused frame (idempotent source-over)."""
        for layer in self._snapshot.layers:
            if layer.layer_type != "scalar_grid" or not layer.visible or layer.opacity <= 0.0:
                continue
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
            self._draw_scalar_grid(painter, layer)
            painter.restore()

    def _paint_strips(self, painter: QPainter, dx_px: float, dy_px: float) -> None:
        """Rasterize only the viewport strips exposed by a same-scale pan."""
        width, height = self._output_size
        strips: list[QRectF] = []
        if dx_px > 0.0:
            strips.append(QRectF(width - dx_px, 0.0, dx_px, height))
        elif dx_px < 0.0:
            strips.append(QRectF(0.0, 0.0, -dx_px, height))
        if dy_px > 0.0:
            strips.append(QRectF(0.0, height - dy_px, width, dy_px))
        elif dy_px < 0.0:
            strips.append(QRectF(0.0, 0.0, width, -dy_px))
        if not strips:
            return
        xmin, ymin, xmax, ymax = self._extent
        sx, sy = self._pixel_scales()
        for strip in strips:
            strip_view = (
                xmin + strip.left() / sx,
                ymax - strip.bottom() / sy,
                xmin + strip.right() / sx,
                ymax - strip.top() / sy,
            )
            for layer in self._snapshot.layers:
                if not layer.visible or layer.opacity <= 0.0:
                    continue
                painter.save()
                painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
                self._paint_vector_layer(painter, layer, strip_view, self._layer_margin_units(layer))
                painter.restore()

    def _frame_from_image(self, generation: int, image: QImage) -> RenderFrame:
        rgba = image.constBits().tobytes()
        return RenderFrame(
            generation=generation,
            width=image.width(),
            height=image.height(),
            stride=image.bytesPerLine(),
            rgba=rgba,
            render_ms=0.0,
        )

    def shutdown(self) -> None:
        self._frame_cache = None
        self._frame_cache_key = None
        self._feature_bounds.clear()
        super().shutdown()


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
        # Snapshot arrived before the bridge existed (or after shutdown());
        # request_render must deliver it or the first async frame is blank.
        self._native_snapshot_pending = False
        self._scalar_raster_cache = None
        # Geometry payload is keyed to the host's data revision.  Style and
        # visibility changes can reuse it without re-walking every feature/WKT.
        self._vector_feature_payloads: dict[
            str, tuple[int, tuple[dict[str, object], ...]]
        ] = {}
        self._vector_feature_entries: dict[
            str, dict[str, tuple[object, object, dict[str, object]]]
        ] = {}
        self._feature_encoding_cache_hits = 0
        self._feature_encoding_cache_misses = 0
        self._feature_payload_reuse_hits = 0
        self._feature_payload_reencode_misses = 0

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

    def native_encoding_diagnostics(self) -> dict[str, int]:
        return {
            "cached_vector_layers": len(self._vector_feature_payloads),
            "feature_encoding_cache_hits": self._feature_encoding_cache_hits,
            "feature_encoding_cache_misses": self._feature_encoding_cache_misses,
            "feature_payload_reuse_hits": self._feature_payload_reuse_hits,
            "feature_payload_reencode_misses": self._feature_payload_reencode_misses,
        }

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
        else:
            # Bridge not created yet (or shut down): deliver on the next render
            # request, which initializes the bridge on the async path too.
            self._native_snapshot_pending = True

    def _native_snapshot(self, snapshot: MapRenderSnapshot) -> list[dict[str, object]]:
        if any(layer.layer_type == "scalar_grid" for layer in snapshot.layers):
            if self._scalar_raster_cache is None:
                from paleo_workbench.mapping.scalar_raster_mirror import ScalarRasterMirrorCache

                self._scalar_raster_cache = ScalarRasterMirrorCache()
        encoded = _qgis_snapshot(
            snapshot,
            scalar_raster_cache=self._scalar_raster_cache,
            vector_feature_payloads=self._vector_feature_payloads,
            vector_feature_entries=self._vector_feature_entries,
            encoding_stats=self,
        )
        active_vector_ids = {
            layer.id for layer in snapshot.layers if layer.layer_type == "vector"
        }
        self._vector_feature_payloads = {
            layer_id: payload
            for layer_id, payload in self._vector_feature_payloads.items()
            if layer_id in active_vector_ids
        }
        self._vector_feature_entries = {
            layer_id: entries
            for layer_id, entries in self._vector_feature_entries.items()
            if layer_id in active_vector_ids
        }
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
        if self._native_snapshot_pending:
            # A snapshot arrived before the bridge existed; push it now so the
            # first async render composes current layers instead of a blank frame.
            self._native_snapshot_pending = False
            self._set_native_snapshot(self._snapshot)
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
        self._native_snapshot_pending = False
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
        self._vector_feature_payloads.clear()
        self._vector_feature_entries.clear()
        super().shutdown()


def _qgis_snapshot(
    snapshot: MapRenderSnapshot,
    *,
    scalar_raster_cache=None,
    vector_feature_payloads: dict[str, tuple[int, tuple[dict[str, object], ...]]] | None = None,
    vector_feature_entries: dict[str, dict[str, tuple[object, object, dict[str, object]]]] | None = None,
    encoding_stats: object | None = None,
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
        cached = (
            vector_feature_payloads.get(layer.id)
            if vector_feature_payloads is not None
            else None
        )
        if cached is not None and cached[0] == int(layer.data_revision):
            features = cached[1]
            if encoding_stats is not None:
                encoding_stats._feature_encoding_cache_hits += 1
        else:
            encoded_features: list[dict[str, object]] = []
            previous_entries = (
                vector_feature_entries.get(layer.id, {})
                if vector_feature_entries is not None
                else {}
            )
            next_entries: dict[str, tuple[object, object, dict[str, object]]] = {}
            for feature in layer.features:
                feature_id = str(feature.get("id") or "")
                geometry = feature.get("geometry")
                properties = feature.get("properties") or {}
                cached_entry = previous_entries.get(feature_id)
                if (
                    cached_entry is not None
                    and cached_entry[0] == geometry
                    and cached_entry[1] == properties
                ):
                    encoded = cached_entry[2]
                    if encoding_stats is not None:
                        encoding_stats._feature_payload_reuse_hits += 1
                else:
                    wkt = _geometry_to_wkt(geometry)
                    if not wkt:
                        continue
                    attributes = dict(properties)
                    attributes["__pwb_id"] = str(feature.get("id") or "")
                    encoded = {
                        "id": feature_id,
                        "wkt": wkt,
                        "attributes": attributes,
                    }
                    if encoding_stats is not None:
                        encoding_stats._feature_payload_reencode_misses += 1
                encoded_features.append(encoded)
                next_entries[feature_id] = (geometry, properties, encoded)
            features = tuple(encoded_features)
            if vector_feature_payloads is not None:
                vector_feature_payloads[layer.id] = (int(layer.data_revision), features)
            if vector_feature_entries is not None:
                vector_feature_entries[layer.id] = next_entries
            if encoding_stats is not None:
                encoding_stats._feature_encoding_cache_misses += 1
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
