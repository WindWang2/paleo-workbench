"""Revision-keyed GDAL raster mirrors for the optional QGIS renderer.

The cache consumes an already-rasterized ``ScalarGridLayer`` RGBA image. It has no
interpolation imports and never touches the managed ``.factor_grid.npz`` artifact.
"""

from __future__ import annotations

from pathlib import Path
import re
from uuid import uuid4

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

__all__ = ["ScalarRasterMirrorCache"]


class ScalarRasterMirrorCache:
    """Own revision-aware GeoTIFF mirrors for QGIS raster layers.

    The production path uses GDAL's process-local ``/vsimem`` filesystem so a
    scalar update does not synchronously write a full RGBA GeoTIFF to disk.
    Supplying *directory* retains a disk-backed mode for diagnostics and callers
    which explicitly need a pathname outside GDAL's virtual filesystem.
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        self._directory = Path(directory) if directory is not None else None
        self._virtual_prefix = f"/vsimem/paleo-qgis-scalar-{uuid4().hex}"
        self._entries: dict[str, tuple[tuple[int, int, int, int], str]] = {}
        self._owned_sources: set[str] = set()
        self._stale_sources: set[str] = set()
        self._serial = 0
        self._materialization_count = 0
        self._disk_materialization_count = 0
        self._gdal = None

    @property
    def materialization_count(self) -> int:
        """Number of full RGBA GeoTIFF materializations performed by this cache."""
        return self._materialization_count

    @property
    def disk_materialization_count(self) -> int:
        """Number of materializations that wrote a host filesystem GeoTIFF."""
        return self._disk_materialization_count

    @property
    def uses_virtual_memory(self) -> bool:
        return self._directory is None

    def ensure(self, layer: MapLayerSnapshot) -> str:
        """Return a georeferenced RGBA mirror for an existing scalar cache."""
        scalar = layer.renderer_payload
        if layer.layer_type != "scalar_grid" or scalar is None or not hasattr(scalar, "rasterize"):
            raise TypeError("scalar raster mirrors require a native scalar-grid render payload")
        key = (
            int(layer.data_revision),
            int(layer.style_revision),
            int(getattr(scalar, "data_revision", 0)),
            int(getattr(scalar, "style_revision", 0)),
        )
        existing = self._entries.get(layer.id)
        if existing is not None and existing[0] == key and self._source_exists(existing[1]):
            return existing[1]

        source = self._next_source(layer.id, key)
        try:
            self._write_geotiff(source, layer)
        except Exception:
            self._remove_source(source)
            raise
        if existing is not None:
            self._stale_sources.add(existing[1])
        self._entries[layer.id] = (key, source)
        self._owned_sources.add(source)
        self._materialization_count += 1
        if self._directory is not None:
            self._disk_materialization_count += 1
        return source

    def retain_layer_ids(self, layer_ids: set[str]) -> None:
        """Mark mirrors for removed scalar layers for deferred, safe cleanup."""
        for layer_id in tuple(self._entries):
            if layer_id not in layer_ids:
                _, source = self._entries.pop(layer_id)
                self._stale_sources.add(source)

    def release_stale(self) -> None:
        """Release superseded mirrors only after QGIS no longer references them."""
        for source in tuple(self._stale_sources):
            self._remove_source(source)
            self._owned_sources.discard(source)
        self._stale_sources.clear()

    def clear(self) -> None:
        """Remove only temporary GDAL sources this cache created."""
        for source in tuple(self._owned_sources):
            self._remove_source(source)
        self._owned_sources.clear()
        self._stale_sources.clear()
        self._entries.clear()

    def _next_source(self, layer_id: str, key: tuple[int, int, int, int]) -> str:
        self._serial += 1
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", layer_id).strip("_") or "scalar"
        filename = f"{safe_id}-{key[0]}-{key[1]}-{key[2]}-{key[3]}-{self._serial}.tif"
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
            except RuntimeError:  # The source was never created because GDAL was unavailable.
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
                "QGIS scalar rendering requires the project's GDAL Python binding"
            ) from exc
        return self._gdal

    def _write_geotiff(self, source: str, layer: MapLayerSnapshot) -> None:
        gdal = self._gdal_module()
        try:
            from osgeo import osr
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "QGIS scalar rendering requires the project's GDAL Python binding"
            ) from exc
        rgba = layer.renderer_payload.rasterize()
        try:
            height, width, channels = map(int, rgba.shape)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("native scalar raster must be an H×W×4 RGBA array") from exc
        if height < 1 or width < 1 or channels != 4:
            raise ValueError("native scalar raster must be a non-empty H×W×4 RGBA array")
        xmin, ymin, xmax, ymax = (float(value) for value in layer.extent)
        if not (xmax > xmin and ymax > ymin):
            raise ValueError("scalar raster mirror requires a positive layer extent")
        driver = gdal.GetDriverByName("GTiff")
        if driver is None:  # pragma: no cover - installation defect
            raise RuntimeError("GDAL GeoTIFF driver is unavailable")
        # Compression helps an on-disk diagnostic mirror, but for ``/vsimem``
        # it only adds a full-frame CPU pass and latency. QGIS reads the same
        # four bands and georeferencing from either representation.
        options = ["TILED=YES"] if source.startswith("/vsimem/") else [
            "TILED=YES", "COMPRESS=DEFLATE"
        ]
        dataset = driver.Create(source, width, height, 4, gdal.GDT_Byte, options=options)
        if dataset is None:  # pragma: no cover - filesystem defect
            raise RuntimeError(f"could not create QGIS scalar mirror {source}")
        try:
            dataset.SetGeoTransform((xmin, (xmax - xmin) / width, 0.0, ymax, 0.0, -(ymax - ymin) / height))
            if layer.crs:
                reference = osr.SpatialReference()
                if reference.SetFromUserInput(layer.crs) != 0:
                    raise ValueError(f"invalid scalar layer CRS {layer.crs!r}")
                dataset.SetProjection(reference.ExportToWkt())
            # Do not use ``WriteArray`` here: a valid GDAL Python binding may not
            # ship its optional ``_gdal_array`` bridge. A single interleaved buffer
            # submission accepts the native C-contiguous RGBA array directly, avoiding
            # four channel slices and four full-frame ``tobytes`` temporaries.
            status = dataset.WriteRaster(
                0,
                0,
                width,
                height,
                memoryview(rgba),
                buf_xsize=width,
                buf_ysize=height,
                buf_type=gdal.GDT_Byte,
                band_list=[1, 2, 3, 4],
                buf_pixel_space=4,
                buf_line_space=width * 4,
                buf_band_space=1,
            )
            if status not in (None, gdal.CE_None):  # pragma: no cover - I/O defect
                raise RuntimeError("could not write QGIS scalar mirror RGBA bands")
            colors = (gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand, gdal.GCI_AlphaBand)
            for index, color in enumerate(colors, start=1):
                band = dataset.GetRasterBand(index)
                band.SetColorInterpretation(color)
            dataset.FlushCache()
        finally:
            dataset = None
