"""Revision-keyed GDAL raster mirrors for the optional QGIS renderer.

The cache consumes an already-rasterized ``ScalarGridLayer`` RGBA image. It has no
interpolation imports and never touches the managed ``.factor_grid.npz`` artifact.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile

from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

__all__ = ["ScalarRasterMirrorCache"]


class ScalarRasterMirrorCache:
    """Own temporary, revision-aware GeoTIFF mirrors for QGIS raster layers."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self._directory = Path(directory) if directory is not None else Path(tempfile.mkdtemp(
            prefix="paleo-qgis-scalar-"
        ))
        self._entries: dict[str, tuple[tuple[int, int, int, int], Path]] = {}
        self._owned_paths: set[Path] = set()

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
        if existing is not None and existing[0] == key and existing[1].is_file():
            return str(existing[1])

        self._directory.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", layer.id).strip("_") or "scalar"
        path = self._directory / f"{safe_id}-{key[0]}-{key[1]}-{key[2]}-{key[3]}.tif"
        self._write_geotiff(path, layer)
        if existing is not None and existing[1] != path:
            existing[1].unlink(missing_ok=True)
            self._owned_paths.discard(existing[1])
        self._entries[layer.id] = (key, path)
        self._owned_paths.add(path)
        return str(path)

    def clear(self) -> None:
        """Remove only temporary mirror files this cache created."""
        for path in tuple(self._owned_paths):
            path.unlink(missing_ok=True)
        self._owned_paths.clear()
        self._entries.clear()
        try:
            self._directory.rmdir()
        except OSError:
            pass

    @staticmethod
    def _write_geotiff(path: Path, layer: MapLayerSnapshot) -> None:
        try:
            from osgeo import gdal, osr
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
        dataset = driver.Create(
            str(path), width, height, 4, gdal.GDT_Byte,
            options=["TILED=YES", "COMPRESS=DEFLATE"],
        )
        if dataset is None:  # pragma: no cover - filesystem defect
            raise RuntimeError(f"could not create QGIS scalar mirror {path}")
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
