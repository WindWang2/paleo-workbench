"""GDAL-backed reference layer import and coordinate normalization."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from osgeo import gdal, osr

from paleo_workbench.project.models import MapReferenceLayer


class ReferenceLayerError(ValueError):
    """Raised when a reference source cannot join the project coordinate system."""


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


def _spatial_reference(crs: str) -> osr.SpatialReference:
    value = osr.SpatialReference()
    if value.SetFromUserInput(str(crs)) != 0:
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
            source_path=str(source_path),
            source_kind=source_kind,
            source_crs=source_crs,
            project_crs=_canonical_crs(target_srs),
            transform_wkt=target_srs.ExportToWkt(),
            cache_key=_cache_key(source_path, source_crs, _canonical_crs(target_srs), source_kind),
        )

    def vector_snap_points(self, layer: MapReferenceLayer) -> list[tuple[float, float]]:
        if layer.source_kind != "vector":
            return []
        dataset = gdal.OpenEx(layer.source_path, gdal.OF_VECTOR)
        if dataset is None:
            return []
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
