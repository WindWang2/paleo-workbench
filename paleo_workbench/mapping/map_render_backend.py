"""Renderer-neutral map-frame seam for the unified authoring canvas.

Project and editing code produce immutable snapshots. Render adapters consume those
snapshots and return copied RGBA frames; neither adapter is an authority for map data.

The fallback adapter owns all direct QPainter feature painting so application pages
never become a second rendering stack. It renders through one shared composition
pipeline (:meth:`FallbackMapRenderBackend._paint_composition`) for raster frames and
for vector export targets (SVG/PDF painters), keeping screen and export identical.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
import math
import os
import threading
import time
from typing import Any, Mapping
import weakref

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

from paleo_workbench.mapping.map_styles import MarkerSymbol, VectorStyle

__all__ = [
    "FallbackMapRenderBackend",
    "MapLayerSnapshot",
    "MapRenderBackend",
    "MapRenderSnapshot",
    "QgisMapRenderBackend",
    "RenderFrame",
    "create_map_render_backend",
    "shutdown_live_fallback_backends",
]


_BACKGROUND = QColor("#181c22")
_BASE_DPI = 96.0
# Beyond this many visible points, categorical grouping falls back to the
# single-symbol fill so the Python grouping loop cannot dominate a frame.
_CATEGORY_POINT_CAP = 50_000
# Threaded fallbacks that outlive a pytest case leave executor threads
# touching Qt after the widget is gone — Python 3.13 segfaults in
# pytestqt._process_events (PR #447). Weak so abandoned backends still GC.
_LIVE_FALLBACKS: weakref.WeakSet[FallbackMapRenderBackend] = weakref.WeakSet()


def shutdown_live_fallback_backends() -> None:
    """Join every live fallback executor. Safe to call from test teardown."""
    for backend in list(_LIVE_FALLBACKS):
        try:
            backend.shutdown()
        except Exception:  # noqa: BLE001 — teardown must not raise
            pass


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
    # Catalog provenance: the DataVersion id this layer was produced from, when
    # known. Carried through the seam so exports can record their inputs.
    source_version_id: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    # Optional 1:N scale-denominator visibility window (min, max); ``None``
    # means the layer renders at every scale.
    scale_range: tuple[float, float] | None = None


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


# ---------------------------------------------------------------------------
# Fallback renderer internals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LabelSpec:
    """Plain-data label placement collected during rasterisation (#822).

    The render worker paints GEOMETRY ONLY (QPainter on QImage is
    thread-safe for primitives, but Qt font engines are not - painting text
    off the GUI thread crashed Python 3.13 runs). Label specs are shipped
    back as values and painted on the GUI thread in the frame-finalisation
    step, so no QFont/drawText call ever happens off-thread.
    """

    x: float
    y: float
    text: str
    size: float
    bold: bool
    family: str
    color: str
    halo_color: str
    halo_width: float
    dpi_scale: float


class _PreparedFeature:
    """Viewport-independent parsed geometry for one feature."""

    __slots__ = ("feature_id", "kind", "parts", "bbox", "properties")

    def __init__(
        self,
        feature_id: str,
        kind: str,
        parts: tuple[np.ndarray, ...],
        bbox: tuple[float, float, float, float],
        properties: Mapping[str, Any],
    ) -> None:
        self.feature_id = feature_id
        self.kind = kind  # point | line | polygon
        self.parts = parts  # each (N, 2) float64 array; polygons keep ring order
        self.bbox = bbox
        self.properties = properties


class _PreparedLayer:
    """Parsed vector payload cached per layer data revision.

    Geometry is stored as flat concatenated arrays so a frame performs a handful
    of vectorised transforms over the whole layer instead of one Python-level
    transform/simplify pass per part. Feature order (and therefore draw order)
    is preserved by the index arrays.
    """

    __slots__ = (
        "revision",
        "features",
        "feature_kinds",
        "feature_bboxes",
        "point_xy",
        "point_feature",
        "path_xy",
        "path_offsets",
        "path_feature",
        "path_is_ring",
    )

    _KIND_IDS = {"point": 0, "line": 1, "polygon": 2}

    def __init__(self, features: tuple[_PreparedFeature, ...], revision: int) -> None:
        self.features = features
        self.revision = revision
        count = len(features)
        self.feature_kinds = np.fromiter(
            (self._KIND_IDS[feature.kind] for feature in features),
            dtype=np.int8,
            count=count,
        )
        self.feature_bboxes = np.array(
            [feature.bbox for feature in features], dtype=np.float64
        ).reshape(count, 4)
        point_coords: list[np.ndarray] = []
        point_feature: list[int] = []
        path_coords: list[np.ndarray] = []
        path_feature: list[int] = []
        path_is_ring: list[bool] = []
        for index, feature in enumerate(features):
            if feature.kind == "point":
                for part in feature.parts:
                    point_coords.append(part)
                    point_feature.append(index)
                continue
            for part in feature.parts:
                path_coords.append(part)
                path_feature.append(index)
                path_is_ring.append(feature.kind == "polygon")
        self.point_xy = (
            np.concatenate(point_coords).reshape(-1, 2) if point_coords else None
        )
        self.point_feature = (
            np.array(point_feature, dtype=np.int32) if point_feature else None
        )
        if path_coords:
            self.path_xy = np.concatenate(path_coords).reshape(-1, 2)
            self.path_offsets = np.zeros(len(path_coords) + 1, dtype=np.int64)
            np.cumsum([len(part) for part in path_coords], out=self.path_offsets[1:])
            self.path_feature = np.array(path_feature, dtype=np.int32)
            self.path_is_ring = np.array(path_is_ring, dtype=bool)
        else:
            self.path_xy = None
            self.path_offsets = np.zeros(1, dtype=np.int64)
            self.path_feature = np.zeros(0, dtype=np.int32)
            self.path_is_ring = np.zeros(0, dtype=bool)

    @property
    def vertex_count(self) -> int:
        total = 0 if self.path_xy is None else len(self.path_xy)
        if self.point_xy is not None:
            total += len(self.point_xy)
        return total


def _as_points(value: object) -> np.ndarray | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return np.asarray(value, dtype=np.float64).reshape(-1, 2)
    except (TypeError, ValueError):
        return None


def _prepare_geometry(geometry: object) -> tuple[str, tuple[np.ndarray, ...]] | None:
    """Classify a GeoJSON geometry into (kind, parts) with float64 arrays."""
    if not isinstance(geometry, Mapping):
        return None
    geometry_type = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        part = _as_points(coordinates)
        return ("point", (part,)) if part is not None else None
    if geometry_type == "MultiPoint":
        parts = tuple(point for point in (_as_points(value) for value in coordinates or ()) if point is not None)
        return ("point", parts) if parts else None
    if geometry_type == "LineString":
        part = _as_points(coordinates)
        return ("line", (part,)) if part is not None and len(part) >= 2 else None
    if geometry_type == "MultiLineString":
        parts = tuple(
            line
            for line in (_as_points(value) for value in coordinates or ())
            if line is not None and len(line) >= 2
        )
        return ("line", parts) if parts else None
    if geometry_type == "Polygon":
        parts = tuple(
            ring
            for ring in (_as_points(value) for value in coordinates or ())
            if ring is not None and len(ring) >= 3
        )
        return ("polygon", parts) if parts else None
    if geometry_type == "MultiPolygon":
        parts: list[np.ndarray] = []
        for polygon in coordinates or ():
            if not isinstance(polygon, (list, tuple)):
                continue
            parts.extend(
                ring
                for ring in (_as_points(value) for value in polygon)
                if ring is not None and len(ring) >= 3
            )
        return ("polygon", tuple(parts)) if parts else None
    return None


def _category_colors(style: VectorStyle) -> dict[str, str] | None:
    """Value→fill lookup from the (value, fill, label) category tuples."""
    if style.renderer != "categorized" or not style.categories:
        return None
    return {str(value): str(fill) for value, fill, _label in style.categories}


def _bbox_for(parts: tuple[np.ndarray, ...]) -> tuple[float, float, float, float]:
    stacked = np.concatenate(parts) if len(parts) > 1 else parts[0]
    mins = stacked.min(axis=0)
    maxs = stacked.max(axis=0)
    return (float(mins[0]), float(mins[1]), float(maxs[0]), float(maxs[1]))


def fit_extent_to_aspect(
    extent: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float]:
    """Letterbox the extent to the output aspect (#522).

    The world axis that would be compressed is EXPANDED (centered) so
    units-per-pixel is uniform in x and y — circles stay circles and the
    scale bar is valid for both axes. Extent unchanged for degenerate
    ranges or exact-aspect inputs.
    """
    xmin, ymin, xmax, ymax = (float(v) for v in extent)
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    world_w = xmax - xmin
    world_h = ymax - ymin
    if world_w <= 0 or world_h <= 0:
        return (xmin, ymin, xmax, ymax)
    # Units-per-pixel must be the LARGER of the two axes' requirements;
    # the other (shorter) world axis is expanded to fill, letterboxed.
    units_per_pixel = max(world_w / w, world_h / h)
    adj_w = units_per_pixel * w
    adj_h = units_per_pixel * h
    cx = (xmin + xmax) / 2.0
    cy = (ymin + ymax) / 2.0
    return (cx - adj_w / 2, cy - adj_h / 2, cx + adj_w / 2, cy + adj_h / 2)


class FallbackMapRenderBackend(MapRenderBackend):
    """Explicit QPainter renderer for tests and hosts without a QGIS bridge.

    This adapter owns all direct QPainter feature painting so application pages never
    become a second rendering stack. Vector geometry is parsed once per data revision
    into cached float64 parts; every frame then performs vectorised world→screen
    transforms, viewport culling, pixel-grid LOD simplification and batched draws.

    ``threaded=True`` moves per-frame rasterisation onto one background worker so
    first-time preparation of very large layers never blocks the UI thread. The
    latest-generation contract is identical to the QGIS adapter: stale frames are
    discarded, cancelled requests never surface.
    """

    backend_name = "fallback"

    #: Frame-level vertex budget for path rasterisation. Beyond this, geometry
    #: is stride-decimated (endpoints kept) so pan/zoom stays responsive on
    #: six-figure feature maps. Override with PALEO_RENDER_VERTEX_BUDGET.
    DEFAULT_VERTEX_BUDGET = 150_000

    def __init__(self, *, threaded: bool = False) -> None:
        super().__init__()
        self._threaded = bool(threaded)
        try:
            budget = int(os.environ.get("PALEO_RENDER_VERTEX_BUDGET", self.DEFAULT_VERTEX_BUDGET))
        except (TypeError, ValueError):
            budget = self.DEFAULT_VERTEX_BUDGET
        self._vertex_budget = max(1_000, budget)
        self._executor: ThreadPoolExecutor | None = None
        self._render_future: Future[None] | None = None
        self._render_generation: int | None = None
        self._render_pending = False
        self._prepared_lock = threading.Lock()
        self._prepared: dict[str, _PreparedLayer] = {}
        self._frame_cache: tuple[tuple, RenderFrame] | None = None
        _LIVE_FALLBACKS.add(self)
        self._diagnostics = {
            "prepared_layers": 0,
            "prepared_cache_hits": 0,
            "prepared_cache_misses": 0,
            "features_total": 0,
            "features_drawn": 0,
            "points_drawn": 0,
            "vertices_simplified": 0,
            "frames_rendered": 0,
            "frames_from_cache": 0,
            "render_errors": 0,
            "last_render_ms": 0.0,
        }

    # -- public API ---------------------------------------------------------

    def render_diagnostics(self) -> dict[str, Any]:
        """Return counters describing caches, culling and LOD for this backend."""
        result = dict(self._diagnostics)
        result["threaded"] = self._executor is not None
        result["render_active"] = self.render_active
        return result

    def fallback_diagnostics(self) -> dict[str, int]:
        """Legacy counter surface (map-perf #461 regression tests).

        The v2 renderer replaces strip composition with full-frame
        vectorised rasterisation, so `strip_reuse_count` is always 0 here;
        the pan-correctness guarantee lives in the pixel-identity
        assertions instead of a reuse counter.
        """
        d = self._diagnostics
        return {
            "rasterization_count": int(d["frames_rendered"]),
            "frame_cache_hits": int(d["frames_from_cache"]),
            "strip_reuse_count": 0,
            "culled_feature_count": max(0, int(d["features_total"]) - int(d["features_drawn"])),
        }

    def _ensure_executor(self) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="pwb-fallback-render"
            )

    def request_render(self) -> int:
        """Render the newest generation off the UI thread when threaded.

        Falls back to the synchronous base contract otherwise, which keeps
        tiny local/test maps immediately consistent. A request that arrives
        while a frame is still rendering supersedes it: the in-flight frame is
        discarded on arrival and at most one follow-up render is queued, so
        continuous pan/zoom never builds an unbounded backlog.
        """
        if not self._initialized:
            self.initialize()
        generation = self._next_generation()
        cached = self._cached_frame()
        if cached is not None:
            self._diagnostics["frames_from_cache"] += 1
            self._completed = replace(cached, generation=generation)
            return generation
        self._completed = None
        if not self._threaded:
            frame, key = self._render_frame(generation)
            self._completed = frame
            self._frame_cache = (key, frame)
            return generation
        future = self._render_future
        if future is not None and not future.done():
            self._render_pending = True
            # The in-flight generation no longer matches; it is discarded on
            # arrival and the newest state renders as soon as the worker frees.
            return self._next_generation()
        self._ensure_executor()
        # Worker: the FULL frame rasterisation minus text (#822). QPainter on
        # a privately-owned QImage is thread-safe for geometry primitives;
        # label placements travel back as plain data and paint on the GUI
        # thread during finalisation — no font engine is ever touched
        # off-thread (the Py3.13 constraint documented at _prepare_layers).
        self._render_future = self._executor.submit(self._rasterize_frame_offthread)
        self._render_generation = generation
        return generation

    def take_completed_frame(self) -> RenderFrame | None:
        frame = super().take_completed_frame()
        if frame is not None:
            return frame
        future = self._render_future
        if future is not None and future.done():
            self._render_future = None
            generation = self._render_generation
            self._render_generation = None
            try:
                image, key, specs, elapsed_ms = future.result()
            except Exception:  # noqa: BLE001 - a failed frame must never crash polling
                self._diagnostics["render_errors"] += 1
                self._maybe_submit_pending()
                return None
            if generation != self._generation:
                self._maybe_submit_pending()
                return None
            # Geometry rasterised off-thread; finalise on the GUI thread —
            # the only font work left, proportional to label count. A
            # painting failure must surface through render_errors exactly
            # like a worker-side failure did, never raise into the poller.
            try:
                frame = self._finalize_frame(image, key, generation, specs, elapsed_ms)
            except Exception:  # noqa: BLE001
                self._diagnostics["render_errors"] += 1
                self._maybe_submit_pending()
                return None
            self._frame_cache = (key, frame)
            return frame
        return None

    def _maybe_submit_pending(self) -> None:
        """Render the newest state after a superseded/failed worker frame."""
        if not self._render_pending or self._executor is None:
            return
        future = self._render_future
        if future is not None and not future.done():
            return
        self._render_pending = False
        self._render_generation = self._next_generation()
        self._render_future = self._executor.submit(self._rasterize_frame_offthread)

    @property
    def render_active(self) -> bool:
        future = self._render_future
        return future is not None and not future.done()

    def cancel_render(self) -> None:
        super().cancel_render()
        # Bump the generation so a still-running cancelled frame is discarded
        # on arrival; the worker itself is cooperative and cannot be interrupted.
        self._next_generation()
        self._render_future = None
        self._render_pending = False

    def shutdown(self) -> None:
        self._render_future = None
        self._render_pending = False
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        with self._prepared_lock:
            self._prepared.clear()
        self._frame_cache = None
        super().shutdown()

    def render_sync(self) -> RenderFrame:
        if not self._initialized:
            self.initialize()
        cached = self._cached_frame()
        if cached is not None:
            self._diagnostics["frames_from_cache"] += 1
            return replace(cached, generation=self._next_generation())
        frame, key = self._render_frame(self._next_generation())
        self._frame_cache = (key, frame)
        return frame

    def render_to_painter(self, painter: QPainter, width: int, height: int, *, dpi: float | None = None) -> None:
        """Paint the current composition into any QPaintDevice target.

        Used for vector exports (QSvgGenerator, QPdfWriter) so exported files are
        generated by the exact same pipeline that renders the screen frame,
        including the dark map background the screen frame is filled with.
        """
        if not self._initialized:
            self.initialize()
        painter.fillRect(QRectF(0.0, 0.0, float(width), float(height)), _BACKGROUND)
        self._paint_composition(painter, int(width), int(height), self._dpi if dpi is None else float(dpi))

    # -- frame cache --------------------------------------------------------

    def _frame_key(self) -> tuple:
        layers = tuple(
            (
                layer.id,
                layer.layer_type,
                int(layer.data_revision),
                int(layer.style_revision),
                bool(layer.visible),
                round(float(layer.opacity), 6),
                layer.scale_range,
            )
            for layer in self._snapshot.layers
        )
        return (self._extent, self._output_size, self._dpi, layers, self._snapshot.project_crs)

    def _cached_frame(self) -> RenderFrame | None:
        cached = self._frame_cache
        if cached is not None and cached[0] == self._frame_key():
            return cached[1]
        return None

    def _prepare_layers(self) -> None:
        """Parse every visible vector layer into the prepared cache.

        This is the expensive first-touch pass (per-layer numpy geometry
        parsing) and is thread-safe: the worker exists so THIS never blocks
        the UI thread. Rasterisation itself (QPainter + fonts) stays on the
        GUI thread — Qt font engines are not thread-safe, and painting label
        text off the GUI thread crashed Python 3.13 runs intermittently
        (full-suite segfault in pytestqt._process_events during a
        2000-polygon scene paint).
        """
        for layer in self._snapshot.layers:
            if not layer.visible or layer.opacity <= 0.0:
                continue
            if layer.layer_type == "vector" and layer.features:
                self._prepared_layer(layer)

    def _rasterize_frame_offthread(self) -> tuple[QImage, tuple, list, float]:
        """Rasterise the full frame WITHOUT text; worker-thread safe (#822).

        Geometry painting on a privately-owned QImage is thread-safe; label
        placements are collected as plain ``_LabelSpec`` values. The GUI
        thread finalises via :meth:`_finalize_frame` (fonts live there).
        """
        key = self._frame_key()
        self._prepare_layers()
        width, height = self._output_size
        image = QImage(width, height, QImage.Format.Format_RGBA8888)
        image.fill(_BACKGROUND)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        specs: list = []
        started = time.perf_counter()
        try:
            self._paint_composition(painter, width, height, self._dpi, label_specs=specs)
        finally:
            painter.end()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._diagnostics["frames_rendered"] += 1
        self._diagnostics["last_render_ms"] = elapsed_ms
        return image, key, specs, elapsed_ms

    def _finalize_frame(
        self, image: QImage, key: tuple, generation: int, specs: list, elapsed_ms: float
    ) -> RenderFrame:
        """GUI-thread finalisation: paint collected labels, extract bytes."""
        if specs:
            painter = QPainter(image)
            try:
                self._paint_label_specs(painter, specs)
            finally:
                painter.end()
        return RenderFrame(
            generation=generation,
            width=image.width(),
            height=image.height(),
            stride=image.bytesPerLine(),
            rgba=image.constBits().tobytes(),
            render_ms=elapsed_ms,
        )

    def _render_frame(self, generation: int) -> tuple[RenderFrame, tuple]:
        # Synchronous path (tests / unthreaded hosts): rasterise + collect on
        # the calling thread, finalise in the same order the threaded path
        # uses (geometry first, labels after) so both produce identical bytes.
        image, key, specs, elapsed_ms = self._rasterize_frame_offthread()
        return self._finalize_frame(image, key, generation, specs, elapsed_ms), key

    # -- composition pipeline ----------------------------------------------

    def _scale_denominator(self, width: int) -> float:
        """Approximate 1:N denominator assuming map units are metres."""
        xmin, _, xmax, _ = fit_extent_to_aspect(self._extent, width, self._output_size[1])
        units_per_pixel = (xmax - xmin) / max(1, width)
        # The denominator is units per physical inch: it must follow the
        # configured dpi, not the hard-coded base (#852) — scale_range
        # visibility was silently wrong on HiDPI/export otherwise.
        return units_per_pixel / (0.0254 / self._dpi)

    def _paint_composition(
        self, painter: QPainter, width: int, height: int, dpi: float,
        label_specs: list | None = None,
    ) -> None:
        """Paint the composition.

        ``label_specs`` non-None (worker path): label placements are
        COLLECTED as plain data instead of painted, so the pass never
        touches font engines off the GUI thread (#822). None (export /
        render_to_painter): labels paint inline as before.
        """
        xmin, ymin, xmax, ymax = fit_extent_to_aspect(self._extent, width, height)
        span_x = xmax - xmin
        span_y = ymax - ymin
        if span_x <= 0.0 or span_y <= 0.0:
            return
        scale_denominator = self._scale_denominator(width)
        dpi_scale = max(0.05, float(dpi) / _BASE_DPI)
        self._diagnostics["features_total"] = 0
        self._diagnostics["features_drawn"] = 0
        self._diagnostics["points_drawn"] = 0
        self._diagnostics["vertices_simplified"] = 0
        seen_layers: set[str] = set()
        for layer in self._snapshot.layers:
            seen_layers.add(layer.id)
            if not layer.visible or layer.opacity <= 0.0:
                continue
            scale_range = layer.scale_range
            if (
                scale_range is not None
                and not (scale_range[0] <= scale_denominator <= scale_range[1])
            ):
                continue
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
            try:
                if layer.layer_type == "scalar_grid":
                    self._draw_scalar_grid(painter, layer)
                elif layer.layer_type == "raster_source":
                    # Reference basemaps must survive the fallback pipeline
                    # too — the off-thread export worker renders through a
                    # throwaway fallback backend even on QGIS installs, and a
                    # missing branch silently dropped the raster (#832).
                    self._draw_raster_source(painter, layer)
                elif layer.layer_type == "vector" and layer.features:
                    self._paint_vector_layer(
                        painter, layer, xmin, ymin, span_x, span_y, width, height, dpi_scale,
                        label_specs=label_specs,
                    )
            finally:
                painter.restore()
        # Drop parsed payloads for layers that left the composition so document
        # switches do not accumulate stale prepared geometry.
        with self._prepared_lock:
            for layer_id in list(self._prepared):
                if layer_id not in seen_layers:
                    del self._prepared[layer_id]

    def _prepared_layer(self, layer: MapLayerSnapshot) -> _PreparedLayer:
        cached = self._prepared.get(layer.id)
        if cached is not None and cached.revision == int(layer.data_revision):
            self._diagnostics["prepared_cache_hits"] += 1
            return cached
        items: list[_PreparedFeature] = []
        for feature in layer.features:
            prepared = _prepare_geometry(feature.get("geometry"))
            if prepared is None:
                continue
            kind, parts = prepared
            items.append(
                _PreparedFeature(
                    str(feature.get("id") or ""),
                    kind,
                    parts,
                    _bbox_for(parts),
                    feature.get("properties") or {},
                )
            )
        prepared_layer = _PreparedLayer(tuple(items), int(layer.data_revision))
        with self._prepared_lock:
            existing = self._prepared.get(layer.id)
            if existing is not None and existing.revision == int(layer.data_revision):
                self._diagnostics["prepared_cache_hits"] += 1
                return existing
            self._prepared[layer.id] = prepared_layer
        self._diagnostics["prepared_cache_misses"] += 1
        self._diagnostics["prepared_layers"] = len(self._prepared)
        return prepared_layer

    def _paint_vector_layer(
        self,
        painter: QPainter,
        layer: MapLayerSnapshot,
        xmin: float,
        ymin: float,
        span_x: float,
        span_y: float,
        width: int,
        height: int,
        dpi_scale: float,
        label_specs: list | None = None,
    ) -> None:
        style = VectorStyle.from_dict(layer.style)
        scale_x = width / span_x
        scale_y = height / span_y
        marker_radius = max(0.5, style.marker_size * dpi_scale / 2.0)
        stroke_width = max(0.0, style.stroke_width * dpi_scale)
        pad_x = (marker_radius + stroke_width) / scale_x
        pad_y = (marker_radius + stroke_width) / scale_y
        view = (
            xmin - pad_x,
            ymin - pad_y,
            xmin + span_x + pad_x,
            ymin + span_y + pad_y,
        )
        pen = QPen(
            self._color(style.stroke, "#26364d"),
            max(0.5, stroke_width),
        )
        dash = style.line_pattern.dash_pattern(stroke_width)
        if dash:
            pen.setDashPattern(list(dash))
        elif stroke_width <= 0.0:
            pen.setStyle(Qt.PenStyle.NoPen)
        painter.setPen(pen)
        fill = self._color(style.fill, "#6c8ebf")
        transparent_fill = style.fill == "transparent" or fill.alpha() == 0
        painter.setBrush(Qt.BrushStyle.NoBrush if transparent_fill else fill)
        prepared = self._prepared_layer(layer)
        self._diagnostics["features_total"] += len(prepared.features)
        visible_features = self._cull_features(prepared, view)
        self._diagnostics["features_drawn"] += int(visible_features.sum())
        if not visible_features.any():
            return
        if prepared.path_xy is not None:
            self._paint_layer_paths(
                painter, prepared, visible_features, style, view,
                xmin, ymin, scale_x, scale_y, width, height,
                marker_radius, stroke_width, transparent_fill, fill,
            )
        if prepared.point_xy is not None:
            self._paint_layer_points(
                painter, prepared, visible_features, style, view,
                xmin, ymin, scale_x, scale_y, width, height,
                marker_radius, stroke_width, transparent_fill, fill, dpi_scale,
                label_specs=label_specs,
            )

    @staticmethod
    def _cull_features(prepared: _PreparedLayer, view: tuple[float, float, float, float]) -> np.ndarray:
        boxes = prepared.feature_bboxes
        if boxes.size == 0:
            return np.zeros(0, dtype=bool)
        vx0, vy0, vx1, vy1 = view
        return (
            (boxes[:, 2] >= vx0)
            & (boxes[:, 0] <= vx1)
            & (boxes[:, 3] >= vy0)
            & (boxes[:, 1] <= vy1)
        )

    def _paint_layer_paths(
        self,
        painter: QPainter,
        prepared: _PreparedLayer,
        visible_features: np.ndarray,
        style: VectorStyle,
        view: tuple[float, float, float, float],
        xmin: float,
        ymin: float,
        scale_x: float,
        scale_y: float,
        width: int,
        height: int,
        marker_radius: float,
        stroke_width: float,
        transparent_fill: bool,
        fill: QColor,
    ) -> None:
        xy = prepared.path_xy
        screen = np.empty_like(xy)
        screen[:, 0] = (xy[:, 0] - xmin) * scale_x
        screen[:, 1] = height - (xy[:, 1] - ymin) * scale_y
        offsets = prepared.path_offsets
        starts = offsets[:-1]
        lengths = np.diff(offsets)
        rings = prepared.path_is_ring
        part_visible = visible_features[prepared.path_feature]
        if not part_visible.any():
            return
        # Finer per-part culling in screen space (feature bboxes only bound a
        # feature's full extent; long lines crossing the viewport survive here).
        pad_px = marker_radius + stroke_width + 1.0
        min_x = np.minimum.reduceat(screen[:, 0], starts)
        max_x = np.maximum.reduceat(screen[:, 0], starts)
        min_y = np.minimum.reduceat(screen[:, 1], starts)
        max_y = np.maximum.reduceat(screen[:, 1], starts)
        in_view = (
            part_visible
            & (max_x >= -pad_px)
            & (min_x <= width + pad_px)
            & (max_y >= -pad_px)
            & (min_y <= height + pad_px)
        )
        part_indices = np.nonzero(in_view)[0]
        if part_indices.size == 0:
            return
        # Adaptive pixel-grid LOD: coarser quantisation only when the frame is
        # heavily oversampled, keeping pan/zoom responsive at six-figure counts.
        visible_vertices = int(lengths[part_indices].sum())
        tolerance = 1.0
        if visible_vertices > 400_000:
            tolerance = 2.0
        if visible_vertices > 1_200_000:
            tolerance = 3.0
        quantised = np.floor(screen / tolerance).astype(np.int64)
        # Keep a vertex only when its quantised pixel differs from a neighbour
        # (plus part endpoints), collapsing sub-pixel vertex runs.
        pixel_keep = np.zeros(len(screen), dtype=bool)
        if len(screen) > 2:
            differs = (quantised[1:] != quantised[:-1]).any(axis=1)
            pixel_keep[:-1] |= differs
            pixel_keep[1:] |= differs
        pixel_keep[starts] = True
        pixel_keep[offsets[1:] - 1] = True
        # Hard vertex budget: stride-decimate when a frame is still oversampled
        # (sub-pixel-dense geometry), bounding worst-case rasterisation time
        # independently of dataset size. Rings are exempt: a global stride can
        # drop a small ring to its two endpoints (deleting the polygon) and
        # cracks shared edges between neighbours, so filled areas keep the
        # pixel-grid result while lines carry the budget.
        keep = pixel_keep
        if visible_vertices > self._vertex_budget:
            line_budget = visible_vertices - int(
                lengths[part_indices][rings[part_indices]].sum()
            )
            stride = 1
            if line_budget > 0:
                stride = int(math.ceil(line_budget / self._vertex_budget))
            if stride > 1:
                positions = np.arange(len(screen))
                keep = np.where(
                    np.repeat(rings, lengths),
                    pixel_keep,
                    pixel_keep & (positions % stride == 0),
                )
                keep[starts] = True
                keep[offsets[1:] - 1] = True
        kept_index = np.nonzero(keep)[0]

        part_feature = prepared.path_feature
        drawn_vertices = 0
        categories = _category_colors(style)

        def kept_slice(part: int) -> np.ndarray:
            start, end = offsets[part], offsets[part + 1]
            return kept_index[np.searchsorted(kept_index, start):np.searchsorted(kept_index, end)]

        # Lines: stroke-only pass. Per-part QPainterPath built from float
        # moveTo/lineTo calls measured fastest; QPolygonF/QPointF construction
        # and multi-subpath mega-paths are both significantly slower.
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for part in part_indices:
            if rings[part]:
                continue
            kept = kept_slice(part)
            drawn_vertices += len(kept)
            if len(kept) < 2:
                continue
            coordinates = screen[kept].tolist()
            path = QPainterPath()
            path.moveTo(coordinates[0][0], coordinates[0][1])
            for x, y in coordinates[1:]:
                path.lineTo(x, y)
            painter.drawPath(path)
        painter.restore()

        # Polygons: rings of one feature share a path so OddEvenFill keeps
        # holes correct; category fills switch brushes between features.
        current_feature = -1
        path: QPainterPath | None = None

        def flush_polygon() -> None:
            nonlocal path, current_feature
            if path is not None and not path.isEmpty():
                if categories is not None and current_feature >= 0:
                    key = str(
                        prepared.features[current_feature].properties.get(style.field) or ""
                    )
                    color_name = categories.get(key)
                    if color_name is not None:
                        painter.save()
                        painter.setBrush(self._color(color_name, style.fill))
                        painter.drawPath(path)
                        painter.restore()
                        path = None
                        current_feature = -1
                        return
                painter.drawPath(path)
            path = None
            current_feature = -1

        for part in part_indices:
            if not rings[part]:
                continue
            kept = kept_slice(part)
            if len(kept) < 3:
                # A ring that collapsed below three kept vertices would vanish;
                # fall back to its unsimplified vertices rather than dropping
                # the polygon.
                start, end = offsets[part], offsets[part + 1]
                kept = np.arange(start, end)
            drawn_vertices += len(kept)
            feature = int(part_feature[part])
            if feature != current_feature:
                flush_polygon()
                current_feature = feature
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
            coordinates = screen[kept].tolist()
            assert path is not None
            path.moveTo(coordinates[0][0], coordinates[0][1])
            for x, y in coordinates[1:]:
                path.lineTo(x, y)
        flush_polygon()
        self._diagnostics["vertices_simplified"] += visible_vertices - drawn_vertices

    def _paint_layer_points(
        self,
        painter: QPainter,
        prepared: _PreparedLayer,
        visible_features: np.ndarray,
        style: VectorStyle,
        view: tuple[float, float, float, float],
        xmin: float,
        ymin: float,
        scale_x: float,
        scale_y: float,
        width: int,
        height: int,
        marker_radius: float,
        stroke_width: float,
        transparent_fill: bool,
        fill: QColor,
        dpi_scale: float,
        label_specs: list | None = None,
    ) -> None:
        xy = prepared.point_xy
        screen = np.empty_like(xy)
        screen[:, 0] = (xy[:, 0] - xmin) * scale_x
        screen[:, 1] = height - (xy[:, 1] - ymin) * scale_y
        pad_px = marker_radius + stroke_width + 1.0
        in_view = (
            visible_features[prepared.point_feature]
            & (screen[:, 0] >= -pad_px)
            & (screen[:, 0] <= width + pad_px)
            & (screen[:, 1] >= -pad_px)
            & (screen[:, 1] <= height + pad_px)
        )
        count = int(in_view.sum())
        if count == 0:
            return
        points = screen[in_view]
        feature_indices = prepared.point_feature[in_view]
        # Grid de-duplication LOD: when markers shrink below ~1.5 px, thousands
        # of coincident screen dots collapse to one draw each.
        if marker_radius < 1.5 and count > 4_000:
            quantised = np.floor(points).astype(np.int64)
            _, unique_at = np.unique(quantised, axis=0, return_index=True)
            points = points[np.sort(unique_at)]
            feature_indices = feature_indices[np.sort(unique_at)]
            count = len(points)
        self._diagnostics["points_drawn"] += count
        # Categorical grouping is a Python loop over visible points; past the
        # cap the layer degrades to its single-symbol fill instead.
        categorized = (
            _category_colors(style) if count <= _CATEGORY_POINT_CAP else None
        )
        batch_dots = marker_radius < 1.0 or (
            style.marker is MarkerSymbol.CIRCLE and marker_radius <= 4.0
        )
        # Complex per-point symbols stay affordable by capping them: beyond the
        # cap the layer degrades to batched dots (points still visible).
        symbol_loop = not batch_dots and count <= 5_000
        if categorized is not None and not transparent_fill:
            groups: dict[str, list[int]] = {}
            for position, feature_index in enumerate(feature_indices):
                key = str(prepared.features[feature_index].properties.get(style.field) or "")
                groups.setdefault(key, []).append(position)
            painter.save()
            symbol_pen = QPen(painter.pen())
            symbol_pen.setStyle(Qt.PenStyle.SolidLine)
            symbol_pen.setWidthF(max(1.0, stroke_width))
            painter.setPen(symbol_pen)
            for key, positions in groups.items():
                color_name = categorized.get(key)
                painter.setBrush(
                    self._color(color_name, style.fill)
                    if color_name
                    else (Qt.BrushStyle.NoBrush if transparent_fill else fill)
                )
                selected = points[positions]
                if symbol_loop:
                    for px, py in selected.tolist():
                        self._draw_point_symbol(painter, QPointF(px, py), marker_radius, style.marker)
                else:
                    self._draw_dots(painter, selected, marker_radius)
            painter.restore()
            return
        if symbol_loop:
            painter.save()
            symbol_pen = QPen(painter.pen())
            symbol_pen.setStyle(Qt.PenStyle.SolidLine)
            symbol_pen.setWidthF(max(1.0, stroke_width))
            painter.setPen(symbol_pen)
            for px, py in points.tolist():
                self._draw_point_symbol(painter, QPointF(px, py), marker_radius, style.marker)
            painter.restore()
        else:
            self._draw_dots(painter, points, marker_radius)
        labels = style.labels
        if labels is not None and labels.visible and labels.field and count <= 1_500:
            for position, (px, py) in enumerate(points.tolist()):
                feature = prepared.features[feature_indices[position]]
                anchor = QPointF(px, py)
                self._draw_label_text(
                    painter, anchor, feature, labels.field, style, dpi_scale,
                    label_specs=label_specs,
                )

    def _draw_dots(self, painter: QPainter, points: np.ndarray, radius: float) -> None:
        """One batched drawPoints call for any number of dot markers."""
        painter.save()
        dot_pen = QPen(painter.pen())
        dot_pen.setStyle(Qt.PenStyle.SolidLine)
        dot_pen.setWidthF(max(1.0, radius * 2.0))
        dot_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(dot_pen)
        painter.drawPoints(QPolygonF([QPointF(px, py) for px, py in points.tolist()]))
        painter.restore()

    def _draw_point_symbol(
        self, painter: QPainter, centre: QPointF, radius: float, marker: MarkerSymbol
    ) -> None:
        if marker is MarkerSymbol.SQUARE:
            painter.drawRect(QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2))
        elif marker is MarkerSymbol.TRIANGLE:
            tip = centre + QPointF(0, -radius * 1.2)
            left = centre + QPointF(-radius, radius)
            right = centre + QPointF(radius, radius)
            painter.drawPolygon(QPolygonF([tip, left, right]))
        elif marker is MarkerSymbol.DIAMOND:
            painter.drawPolygon(
                QPolygonF(
                    [
                        centre + QPointF(0, -radius),
                        centre + QPointF(radius, 0),
                        centre + QPointF(0, radius),
                        centre + QPointF(-radius, 0),
                    ]
                )
            )
        elif marker is MarkerSymbol.CROSS:
            painter.drawLine(centre + QPointF(-radius, -radius), centre + QPointF(radius, radius))
            painter.drawLine(centre + QPointF(radius, -radius), centre + QPointF(-radius, radius))
        elif marker is MarkerSymbol.STAR:
            star: list[QPointF] = []
            for index in range(10):
                angle = -math.pi / 2 + index * math.pi / 5
                length = radius if index % 2 == 0 else radius * 0.45
                star.append(centre + QPointF(length * math.cos(angle), length * math.sin(angle)))
            painter.drawPolygon(QPolygonF(star))
        elif marker is MarkerSymbol.WELL:
            # 井符号: ring plus centre dot on the standard pen.
            painter.drawEllipse(centre, radius, radius)
            painter.drawPoint(centre)
        else:
            painter.drawEllipse(centre, radius, radius)

    def _draw_label_text(
        self,
        painter: QPainter,
        anchor: QPointF,
        feature: _PreparedFeature,
        field: str,
        style: VectorStyle,
        dpi_scale: float,
        label_specs: list | None = None,
    ) -> None:
        text = str(
            feature.properties.get(field)
            or feature.properties.get("name")
            or feature.properties.get("text")
            or ""
        ).strip()
        if not text:
            return
        assert style.labels is not None
        position = anchor + QPointF(max(4.0, style.marker_size * dpi_scale / 2.0 + 2.0), -4.0 * dpi_scale)
        if label_specs is not None:
            # Deferred painting (#822): the rasterisation pass may run on a
            # worker thread where font engines must not be touched; collect
            # the placement as plain data for the GUI-thread finaliser.
            labels_cfg = style.labels
            label_specs.append(
                _LabelSpec(
                    x=float(position.x()),
                    y=float(position.y()),
                    text=text,
                    size=float(labels_cfg.size),
                    bold=bool(labels_cfg.bold),
                    family=str(labels_cfg.font_family or ""),
                    color=str(labels_cfg.color),
                    halo_color=str(labels_cfg.halo_color),
                    halo_width=float(labels_cfg.halo_width),
                    dpi_scale=float(dpi_scale),
                )
            )
            return
        painter.save()
        font = painter.font()
        font.setPointSizeF(max(6.0, style.labels.size * dpi_scale))
        font.setBold(style.labels.bold)
        if style.labels.font_family:
            font.setFamily(style.labels.font_family)
        painter.setFont(font)
        halo = QColor(style.labels.halo_color)
        if halo.alpha() > 0 and style.labels.halo_width > 0:
            offset = style.labels.halo_width * dpi_scale
            painter.setPen(halo)
            for dx, dy in ((-offset, 0), (offset, 0), (0, -offset), (0, offset)):
                painter.drawText(position + QPointF(dx, dy), text)
        painter.setPen(QColor(style.labels.color))
        painter.drawText(position, text)
        painter.restore()

    def _paint_label_specs(self, painter: QPainter, specs: list) -> None:
        """Paint collected label placements (GUI thread only, #822).

        The only font-engine work left on the frame path; proportional to
        the label count (capped at 1 500 per layer), never to vertex count.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()
        font = painter.font()
        for spec in specs:
            font.setPointSizeF(max(6.0, spec.size * spec.dpi_scale))
            font.setBold(spec.bold)
            if spec.family:
                font.setFamily(spec.family)
            painter.setFont(font)
            position = QPointF(spec.x, spec.y)
            halo = QColor(spec.halo_color)
            if halo.alpha() > 0 and spec.halo_width > 0:
                offset = spec.halo_width * spec.dpi_scale
                painter.setPen(halo)
                for dx, dy in ((-offset, 0), (offset, 0), (0, -offset), (0, offset)):
                    painter.drawText(position + QPointF(dx, dy), spec.text)
            painter.setPen(QColor(spec.color))
            painter.drawText(position, spec.text)
        painter.restore()

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

    def _draw_raster_source(self, painter: QPainter, layer: MapLayerSnapshot) -> None:
        """Composite a reference raster (``renderer_payload`` is the image path).

        Mirrors the scalar-grid mapping without interpolation: the image is
        stretched onto the layer's world extent. A missing/unreadable source
        is skipped silently, exactly like the QGIS `_qgis_snapshot` side skips
        raster sources without a path.
        """
        source = layer.renderer_payload
        if not source:
            return
        image = QImage(str(source))
        if image.isNull():
            return
        xmin, ymin, xmax, ymax = layer.extent
        top_left = self._screen_point((xmin, ymax))
        bottom_right = self._screen_point((xmax, ymin))
        if top_left is not None and bottom_right is not None:
            painter.drawImage(QRectF(top_left, bottom_right).normalized(), image)

    @staticmethod
    def _color(value: object, fallback: str) -> QColor:
        color = QColor(str(value or fallback))
        return color if color.isValid() else QColor(fallback)

    def _screen_point(self, point: object) -> QPointF | None:
        """World→screen helper kept for scalar mirroring and ad-hoc callers."""
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
        xmin, ymin, xmax, ymax = fit_extent_to_aspect(
            self._extent, *self._output_size
        )
        width, height = self._output_size
        return QPointF(
            (x - xmin) * width / (xmax - xmin),
            height - (y - ymin) * height / (ymax - ymin),
        )

    # NOTE: the pre-v2 shutdown override was dropped in the merge — it
    # cleared caches (_feature_bounds/_frame_cache_key) that only the old
    # per-feature backend defined, so calling it on the v2 backend raised
    # AttributeError during teardown and failed the threaded-render tests.
    # The v2 shutdown above (executor + prepared layers + frame cache)
    # already covers everything this class owns.


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
    """Select QGIS only when its optional native bridge is genuinely available.

    The fallback is threaded by default: the UI canvas must never block on the
    first preparation of a large vector layer. Tests construct it directly and
    keep the synchronous contract.
    """
    qgis = QgisMapRenderBackend()
    if prefer_qgis and qgis.is_available:
        return qgis
    return FallbackMapRenderBackend(threaded=True)
