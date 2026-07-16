"""GDAL-backed reference layer import and coordinate normalization."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage
from osgeo import gdal, osr

from paleo_workbench.project.models import MapReferenceLayer


class ReferenceLayerError(ValueError):
    """Raised when a reference source cannot join the project coordinate system."""


def _read_band_as_array(band, *, width: int, height: int) -> np.ndarray:
    """Read a GDAL band into a float64 array without requiring gdal_array.

    Prefer ``ReadAsArray`` when the numpy bridge is available; otherwise use
    ``ReadRaster`` + numpy frombuffer. CI/dev installs of osgeo often ship
    without the ``_gdal_array`` extension when numpy was missing at build time.
    """
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


def _spatial_reference(crs: str) -> osr.SpatialReference:
    value = osr.SpatialReference()
    if value.SetFromUserInput(_normalize_crs_input(crs)) != 0:
        raise ReferenceLayerError(f"无法识别项目基准坐标：{crs}")
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
    """Reads GDAL sources and exposes normalized vector snap candidates."""

    def import_layer(self, path: str | Path, project_crs: str) -> MapReferenceLayer:
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

    def raster_preview(self, layer: MapReferenceLayer, max_size: int = 512) -> QImage:
        """Return a bounded grayscale overview for a GDAL raster reference."""
        if layer.source_kind != "raster":
            raise ReferenceLayerError("只有栅格参考图可以生成预览")
        self.refresh_status(layer)
        if layer.status != "ready":
            raise ReferenceLayerError(layer.error_message or "参考图不可用")
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
