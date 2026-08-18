"""GDAL-backed reference layer import and coordinate normalization."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage

try:
    from osgeo import gdal, osr
except ImportError:  # pragma: no cover — dev machines without GDAL
    gdal = None  # type: ignore[assignment]
    osr = None  # type: ignore[assignment]

from paleo_workbench.project.models import MapReferenceLayer


class ReferenceLayerError(ValueError):
    """Raised when a reference source cannot join the project coordinate system."""


def _require_gdal() -> None:
    """Fail an operation with an actionable error when GDAL is unavailable.

    The module must stay importable when ``osgeo`` is missing or its wheel and
    system libgdal mismatch (#851): a hard module-level ``from osgeo import
    gdal`` made every importer of ``mapping_page`` un-collectable on such
    machines, silently dropping ~470 tests (including the #662 export
    regressions) instead of failing loudly with a usable message.
    """
    if gdal is None or osr is None:
        raise ReferenceLayerError(
            "参考图功能需要 GDAL（osgeo）；请安装/修复 GDAL 后重试"
        )


def _read_band_as_array(band, *, width: int, height: int) -> np.ndarray:
    """Read a GDAL band into a float64 array without requiring gdal_array.

    Prefer ``ReadAsArray`` when the numpy bridge is available; otherwise use
    ``ReadRaster`` + numpy frombuffer. CI/dev installs of osgeo often ship
    without the ``_gdal_array`` extension when numpy was missing at build time.
    """
    _require_gdal()
    try:
        return np.asarray(
            band.ReadAsArray(buf_xsize=width, buf_ysize=height),
            dtype=np.float64,
        )
    except ImportError:
        pass

    gdal_type = band.DataType
    type_map = {
        gdal.GDT_Byte: np.uint8,
        gdal.GDT_UInt16: np.uint16,
        gdal.GDT_Int16: np.int16,
        gdal.GDT_UInt32: np.uint32,
        gdal.GDT_Int32: np.int32,
        gdal.GDT_Float32: np.float32,
        gdal.GDT_Float64: np.float64,
    }
    dtype = type_map.get(gdal_type, np.float32)
    raw = band.ReadRaster(
        0,
        0,
        band.XSize,
        band.YSize,
        buf_xsize=width,
        buf_ysize=height,
        buf_type=gdal_type,
    )
    if raw is None:
        return np.zeros((height, width), dtype=np.float64)
    return np.frombuffer(raw, dtype=dtype).reshape(height, width).astype(np.float64)


def _canonical_crs(srs: osr.SpatialReference) -> str:
    copy = srs.Clone()
    copy.AutoIdentifyEPSG()
    authority = copy.GetAuthorityCode(None)
    if authority:
        return f"EPSG:{authority}"
    value = copy.ExportToWkt()
    if not value:
        raise ReferenceLayerError("参考图缺少可识别的坐标系")
    return value


def _normalize_crs_input(crs: str) -> str:
    """Strip human-readable suffixes like ``EPSG:4326 / WGS84`` → ``EPSG:4326``."""
    text = str(crs).strip()
    if "EPSG:" in text.upper():
        # Prefer the first EPSG token for GDAL SetFromUserInput reliability.
        upper = text.upper()
        start = upper.index("EPSG:")
        token = text[start:]
        for sep in (" ", "/", ","):
            if sep in token:
                token = token.split(sep, 1)[0]
        return token.strip()
    return text


def _pin_traditional_axis_order(srs: osr.SpatialReference | None) -> None:
    """Force traditional GIS (x=longitude, y=latitude) ordering on an SRS.

    GDAL ≥ 3 defaults user-created geographic SRSs to authority-compliant axis
    order (e.g. EPSG:4326 → lat, long), while every workbench consumer — layer
    extents, GeoJSON render payloads, snap points — speaks traditional GIS
    order. Both transform sides are pinned explicitly so reference layers never
    come back mirrored across the diagonal.
    """
    if srs is not None:
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)


def _spatial_reference(crs: str) -> osr.SpatialReference:
    value = osr.SpatialReference()
    if value.SetFromUserInput(_normalize_crs_input(crs)) != 0:
        raise ReferenceLayerError(f"无法识别项目基准坐标：{crs}")
    _pin_traditional_axis_order(value)
    return value


def _cache_key(path: Path, source_crs: str, project_crs: str, source_kind: str) -> str:
    stat = path.stat()
    payload = "|".join((str(path.resolve()), str(stat.st_mtime_ns), source_crs, project_crs, source_kind))
    return sha256(payload.encode("utf-8")).hexdigest()


def _geometry_points(geometry) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in range(geometry.GetPointCount()):
        x, y, *_ = geometry.GetPoint(index)
        points.append((float(x), float(y)))
    for index in range(geometry.GetGeometryCount()):
        child = geometry.GetGeometryRef(index)
        if child is not None:
            points.extend(_geometry_points(child))
    return points


class ReferenceLayerService:
    """Reads immutable GDAL sources for reference rendering and snapping.

    Vector source decoding is cached by the external source revision.  It is an
    import-time/changed-source operation, never part of navigation or mouse-move
    rendering, and its result is only a renderer mirror of ``MapReferenceLayer``.
    """

    def __init__(self) -> None:
        self._vector_render_cache: dict[
            str, tuple[str, tuple[dict[str, Any], ...], tuple[float, float, float, float]]
        ] = {}
        self._raster_extent_cache: dict[str, tuple[str, tuple[float, float, float, float]]] = {}

    @staticmethod
    def _source_revision(layer: MapReferenceLayer) -> str:
        return _cache_key(
            Path(layer.source_path), layer.source_crs, layer.project_crs, layer.source_kind
        )

    def import_layer(self, path: str | Path, project_crs: str) -> MapReferenceLayer:
        _require_gdal()
        source_path = Path(path)
        if not source_path.is_file():
            raise ReferenceLayerError(f"参考图文件不存在：{source_path}")
        dataset = gdal.OpenEx(str(source_path), gdal.OF_RASTER | gdal.OF_VECTOR)
        if dataset is None:
            raise ReferenceLayerError(f"无法读取参考图：{source_path.name}")
        try:
            if dataset.RasterCount:
                source_kind = "raster"
                source_srs = dataset.GetSpatialRef()
            else:
                source_kind = "vector"
                source_layer = dataset.GetLayer(0)
                source_srs = source_layer.GetSpatialRef() if source_layer is not None else None
            if source_srs is None:
                raise ReferenceLayerError("参考图缺少坐标系，无法转换到项目基准坐标")

            source_crs = _canonical_crs(source_srs)
            target_srs = _spatial_reference(project_crs)
            # Construct once at import time to fail early for incompatible CRSs.
            _pin_traditional_axis_order(source_srs)
            osr.CoordinateTransformation(source_srs, target_srs)
            return MapReferenceLayer(
                name=source_path.stem,
                source_path=str(source_path.resolve()),
                source_kind=source_kind,
                source_crs=source_crs,
                project_crs=_canonical_crs(target_srs),
                transform_wkt=target_srs.ExportToWkt(),
                cache_key=_cache_key(source_path, source_crs, _canonical_crs(target_srs), source_kind),
                status="ready",
                error_message="",
            )
        finally:
            dataset = None

    @staticmethod
    def refresh_status(layer: MapReferenceLayer) -> MapReferenceLayer:
        """Mark layer offline when the source file is missing; restore ready when present.

        Does not clear an existing ``failed`` status unless the file is simply gone
        (missing → offline takes precedence for path I/O), or the file reappears
        and was only offline.
        """
        path = Path(layer.source_path) if layer.source_path else None
        if path is None or not path.is_file():
            layer.status = "offline"
            layer.error_message = layer.error_message or "参考图源文件不可用"
            return layer
        if layer.status == "offline":
            layer.status = "ready"
            if layer.error_message == "参考图源文件不可用":
                layer.error_message = ""
        return layer

    def vector_snap_points(self, layer: MapReferenceLayer) -> list[tuple[float, float]]:
        if layer.source_kind != "vector":
            return []
        self.refresh_status(layer)
        if layer.status != "ready":
            return []
        _require_gdal()
        dataset = gdal.OpenEx(layer.source_path, gdal.OF_VECTOR)
        if dataset is None:
            layer.status = "failed"
            layer.error_message = "无法打开矢量参考图"
            return []
        try:
            source = dataset.GetLayer(0)
            if source is None or source.GetSpatialRef() is None:
                return []
            target_srs = _spatial_reference(layer.project_crs)
            _pin_traditional_axis_order(source.GetSpatialRef())
            transform = osr.CoordinateTransformation(source.GetSpatialRef(), target_srs)
            points: list[tuple[float, float]] = []
            source.ResetReading()
            for feature in source:
                geometry = feature.GetGeometryRef()
                if geometry is None:
                    continue
                normalized = geometry.Clone()
                if normalized.Transform(transform) != 0:
                    continue
                points.extend(_geometry_points(normalized))
            return points
        finally:
            dataset = None

    def vector_render_payload(
        self, layer: MapReferenceLayer
    ) -> tuple[tuple[dict[str, Any], ...], tuple[float, float, float, float]]:
        """Return project-CRS GeoJSON-compatible features for one vector mirror.

        The raw file remains external and untouched.  Feature materialization is
        keyed by its mtime-based source revision so viewport redraws only consume
        the cached tuple.
        """
        if layer.source_kind != "vector":
            raise ReferenceLayerError("只有矢量参考图可以生成渲染要素")
        self.refresh_status(layer)
        if layer.status != "ready":
            raise ReferenceLayerError(layer.error_message or "参考图不可用")
        _require_gdal()
        path = Path(layer.source_path)
        try:
            cache_key = self._source_revision(layer)
        except OSError as exc:
            layer.status = "offline"
            layer.error_message = "参考图源文件不可用"
            raise ReferenceLayerError(layer.error_message) from exc
        cached = self._vector_render_cache.get(layer.id)
        if cached is not None and cached[0] == cache_key:
            return cached[1], cached[2]

        dataset = gdal.OpenEx(layer.source_path, gdal.OF_VECTOR)
        if dataset is None:
            layer.status = "failed"
            layer.error_message = "无法打开矢量参考图"
            raise ReferenceLayerError(layer.error_message)
        try:
            source = dataset.GetLayer(0)
            if source is None or source.GetSpatialRef() is None:
                layer.status = "failed"
                layer.error_message = "矢量参考图缺少坐标系"
                raise ReferenceLayerError(layer.error_message)
            _pin_traditional_axis_order(source.GetSpatialRef())
            transform = osr.CoordinateTransformation(source.GetSpatialRef(), _spatial_reference(layer.project_crs))
            definition = source.GetLayerDefn()
            field_names = [
                definition.GetFieldDefn(index).GetName()
                for index in range(definition.GetFieldCount())
            ]
            features: list[dict[str, Any]] = []
            xmin = ymin = float("inf")
            xmax = ymax = float("-inf")
            source.ResetReading()
            for ordinal, feature in enumerate(source):
                geometry = feature.GetGeometryRef()
                if geometry is None:
                    continue
                normalized = geometry.Clone()
                if normalized.Transform(transform) != 0:
                    continue
                try:
                    geojson = json.loads(normalized.ExportToJson())
                except (TypeError, ValueError):
                    continue
                properties: dict[str, Any] = {}
                for index, name in enumerate(field_names):
                    value = feature.GetField(index)
                    if value is None:
                        continue
                    properties[str(name)] = value if isinstance(value, (str, int, float, bool)) else str(value)
                envelope = normalized.GetEnvelope()
                if envelope:
                    xmin = min(xmin, float(envelope[0]))
                    xmax = max(xmax, float(envelope[1]))
                    ymin = min(ymin, float(envelope[2]))
                    ymax = max(ymax, float(envelope[3]))
                fid = feature.GetFID()
                features.append(
                    {
                        "id": f"{layer.id}:{fid if fid is not None and fid >= 0 else ordinal}",
                        "geometry": geojson,
                        "properties": properties,
                    }
                )
            extent = (
                (xmin, ymin, xmax, ymax)
                if xmin < xmax and ymin < ymax
                else (0.0, 0.0, 1.0, 1.0)
            )
            payload = tuple(features)
            # Record the observed source revision; this is metadata on the
            # reference descriptor, not a mutation of the source file.
            layer.cache_key = cache_key
            self._vector_render_cache[layer.id] = (cache_key, payload, extent)
            return payload, extent
        finally:
            dataset = None

    def raster_render_extent(self, layer: MapReferenceLayer) -> tuple[float, float, float, float]:
        """Return the source raster's project-CRS footprint for map navigation."""
        if layer.source_kind != "raster":
            raise ReferenceLayerError("只有栅格参考图具有栅格范围")
        self.refresh_status(layer)
        if layer.status != "ready":
            raise ReferenceLayerError(layer.error_message or "参考图不可用")
        _require_gdal()
        try:
            cache_key = self._source_revision(layer)
        except OSError as exc:
            layer.status = "offline"
            layer.error_message = "参考图源文件不可用"
            raise ReferenceLayerError(layer.error_message) from exc
        cached = self._raster_extent_cache.get(layer.id)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        dataset = gdal.OpenEx(layer.source_path, gdal.OF_RASTER)
        if dataset is None or dataset.RasterXSize < 1 or dataset.RasterYSize < 1:
            layer.status = "failed"
            layer.error_message = "无法读取栅格参考图"
            raise ReferenceLayerError(layer.error_message)
        try:
            try:
                transform = dataset.GetGeoTransform(can_return_null=True)
            except TypeError:  # Older GDAL Python bindings lack the keyword.
                transform = dataset.GetGeoTransform()
            if transform is None:
                raise ReferenceLayerError("栅格参考图缺少地理变换")
            source_srs = dataset.GetSpatialRef()
            if source_srs is None:
                raise ReferenceLayerError("栅格参考图缺少坐标系")
            _pin_traditional_axis_order(source_srs)
            coordinate_transform = osr.CoordinateTransformation(source_srs, _spatial_reference(layer.project_crs))
            corners = []
            for px, py in (
                (0.0, 0.0), (float(dataset.RasterXSize), 0.0),
                (0.0, float(dataset.RasterYSize)),
                (float(dataset.RasterXSize), float(dataset.RasterYSize)),
            ):
                x = transform[0] + px * transform[1] + py * transform[2]
                y = transform[3] + px * transform[4] + py * transform[5]
                tx, ty, *_ = coordinate_transform.TransformPoint(x, y)
                corners.append((float(tx), float(ty)))
            xs, ys = zip(*corners)
            extent = (min(xs), min(ys), max(xs), max(ys))
            if not extent[0] < extent[2] or not extent[1] < extent[3]:
                raise ReferenceLayerError("栅格参考图范围无效")
            layer.cache_key = cache_key
            self._raster_extent_cache[layer.id] = (cache_key, extent)
            return extent
        finally:
            dataset = None

    def raster_preview(self, layer: MapReferenceLayer, max_size: int = 512) -> QImage:
        """Return a bounded grayscale overview for a GDAL raster reference."""
        if layer.source_kind != "raster":
            raise ReferenceLayerError("只有栅格参考图可以生成预览")
        self.refresh_status(layer)
        if layer.status != "ready":
            raise ReferenceLayerError(layer.error_message or "参考图不可用")
        _require_gdal()
        dataset = gdal.OpenEx(layer.source_path, gdal.OF_RASTER)
        if dataset is None or dataset.RasterXSize <= 0 or dataset.RasterYSize <= 0:
            layer.status = "failed"
            layer.error_message = "无法读取栅格参考图"
            raise ReferenceLayerError("无法读取栅格参考图")
        try:
            limit = max(1, int(max_size))
            scale = min(1.0, limit / max(dataset.RasterXSize, dataset.RasterYSize))
            width = max(1, round(dataset.RasterXSize * scale))
            height = max(1, round(dataset.RasterYSize * scale))
            values = _read_band_as_array(
                dataset.GetRasterBand(1), width=width, height=height
            )
            finite = values[np.isfinite(values)]
            if finite.size == 0 or float(finite.max()) == float(finite.min()):
                pixels = np.zeros((height, width), dtype=np.uint8)
            else:
                pixels = np.clip(
                    (values - finite.min()) * 255.0 / (finite.max() - finite.min()),
                    0,
                    255,
                ).astype(np.uint8)
            return QImage(
                pixels.tobytes(), width, height, width, QImage.Format.Format_Grayscale8
            ).copy()
        finally:
            dataset = None
