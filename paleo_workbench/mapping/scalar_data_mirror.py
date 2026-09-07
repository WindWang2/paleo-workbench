"""Scalar DATA mirrors (v7 §5): single-band float32 GeoTIFFs for QGIS.

Unlike the RGBA mirror (:mod:`scalar_raster_mirror`), which bakes the color
ramp into four Byte bands, the data mirror carries the scientific values
themselves so QGIS renders them with a real raster renderer
(single-band pseudocolor + color ramp shader).  Styling then lives entirely
in the renderer XML — restyling never rewrites the data file.

Keys are ``data_revision`` ONLY: two styles over one grid share one mirror.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence
from uuid import uuid4

import numpy as np

__all__ = ["ScalarDataMirror", "scalar_data_mirror_ready"]


def scalar_data_mirror_ready() -> dict[str, object]:
    """Honest probe for the scalar-data QGIS pipeline (GDAL half)."""
    try:
        from osgeo import gdal  # noqa: F401

        return {"gdal": True, "reason": ""}
    except ImportError as exc:
        return {"gdal": False, "reason": f"osgeo.gdal unavailable: {exc}"}


class ScalarDataMirror:
    """Revision-aware single-band float32 GeoTIFF mirrors in ``/vsimem``.

    Mirrors the lifecycle contract of ``ScalarRasterMirrorCache`` (ensure /
    retain_layer_ids / release_stale / clear with deferred unlink after the
    bridge stops referencing the source), but the payload is the raw grid
    with NaN nodata and a geotransform derived from the layer extent.
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        self._directory = Path(directory) if directory is not None else None
        self._virtual_prefix = f"/vsimem/paleo-scalar-data-{uuid4().hex}"
        self._entries: dict[str, tuple[int, str]] = {}
        self._owned_sources: set[str] = set()
        self._stale_sources: set[str] = set()
        self._serial = 0
        self._materialization_count = 0
        self._gdal = None

    @property
    def materialization_count(self) -> int:
        return self._materialization_count

    @property
    def uses_virtual_memory(self) -> bool:
        return self._directory is None

    def ensure(self, layer_id: str, grid: np.ndarray, extent: Sequence[float],
               crs: str | None, data_revision: int) -> str:
        """Return the float32 GeoTIFF path for (layer, data_revision)."""
        array = np.ascontiguousarray(np.asarray(grid, dtype=np.float32))
        if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
            raise ValueError("scalar data mirror needs a non-empty 2-D grid")
        xmin, ymin, xmax, ymax = (float(v) for v in extent)
        if not (xmax > xmin and ymax > ymin):
            raise ValueError("scalar data mirror requires a positive extent")
        revision = int(data_revision)
        existing = self._entries.get(str(layer_id))
        if existing is not None and existing[0] == revision and self._source_exists(existing[1]):
            return existing[1]

        source = self._next_source(layer_id, revision)
        try:
            self._write_geotiff(source, array, (xmin, ymin, xmax, ymax), crs)
        except Exception:
            self._remove_source(source)
            raise
        if existing is not None:
            self._stale_sources.add(existing[1])
        self._entries[str(layer_id)] = (revision, source)
        self._owned_sources.add(source)
        self._materialization_count += 1
        return source

    def retain_layer_ids(self, layer_ids: set[str]) -> None:
        for layer_id in tuple(self._entries):
            if layer_id not in layer_ids:
                _, source = self._entries.pop(layer_id)
                self._stale_sources.add(source)

    def release_stale(self) -> None:
        for source in tuple(self._stale_sources):
            self._remove_source(source)
            self._owned_sources.discard(source)
        self._stale_sources.clear()

    def clear(self) -> None:
        for source in tuple(self._owned_sources):
            self._remove_source(source)
        self._owned_sources.clear()
        self._stale_sources.clear()
        self._entries.clear()

    def _next_source(self, layer_id: str, revision: int) -> str:
        self._serial += 1
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(layer_id)).strip("_") or "scalar"
        filename = f"{safe_id}-data-{revision}-{self._serial}.tif"
        if self._directory is None:
            return f"{self._virtual_prefix}/{filename}"
        self._directory.mkdir(parents=True, exist_ok=True)
        return str(self._directory / filename)

    def _source_exists(self, source: str) -> bool:
        if source.startswith("/vsimem/"):
            return self._gdal_module().VSIStatL(source) is not None
        return Path(source).is_file()

    def _remove_source(self, source: str) -> None:
        if source.startswith("/vsimem/"):
            try:
                self._gdal_module().Unlink(source)
            except RuntimeError:
                pass
            return
        Path(source).unlink(missing_ok=True)

    def _gdal_module(self):
        try:
            if self._gdal is None:
                from osgeo import gdal

                self._gdal = gdal
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "scalar data mirrors require the GDAL Python binding"
            ) from exc
        return self._gdal

    def _write_geotiff(self, source: str, array: np.ndarray, extent,
                       crs: str | None) -> None:
        gdal = self._gdal_module()
        try:
            from osgeo import osr
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "scalar data mirrors require the GDAL Python binding"
            ) from exc
        height, width = array.shape
        xmin, ymin, xmax, ymax = extent
        driver = gdal.GetDriverByName("GTiff")
        if driver is None:  # pragma: no cover - installation defect
            raise RuntimeError("GDAL GeoTIFF driver is unavailable")
        options = ["TILED=YES"] if source.startswith("/vsimem/") else [
            "TILED=YES", "COMPRESS=DEFLATE"]
        dataset = driver.Create(source, width, height, 1, gdal.GDT_Float32,
                                options=options)
        if dataset is None:  # pragma: no cover - filesystem defect
            raise RuntimeError(f"could not create scalar data mirror {source}")
        try:
            dataset.SetGeoTransform((
                xmin, (xmax - xmin) / width, 0.0,
                ymax, 0.0, -(ymax - ymin) / height))
            if crs:
                reference = osr.SpatialReference()
                if reference.SetFromUserInput(crs) != 0:
                    raise ValueError(f"invalid scalar layer CRS {crs!r}")
                dataset.SetProjection(reference.ExportToWkt())
            band = dataset.GetRasterBand(1)
            # NaN is the FactorGridResult nodata convention; GDAL stores it
            # verbatim for float32 bands.
            band.SetNoDataValue(float("nan"))
            if not hasattr(gdal, "array"):
                # WriteRaster path keeps us independent of the optional
                # _gdal_array bridge (same policy as the RGBA mirror).
                status = dataset.WriteRaster(
                    0, 0, width, height,
                    memoryview(array),
                    buf_xsize=width, buf_ysize=height,
                    buf_type=gdal.GDT_Float32, band_list=[1],
                    buf_pixel_space=4, buf_line_space=width * 4,
                )
                if status not in (None, gdal.CE_None):  # pragma: no cover
                    raise RuntimeError("could not write scalar data mirror band")
            else:
                band.WriteArray(array)
            dataset.FlushCache()
        finally:
            dataset = None
