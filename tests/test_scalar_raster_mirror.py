"""QGIS scalar mirror cache tests (uses GDAL only when locally available)."""

from __future__ import annotations

import builtins

import numpy as np
import pytest

from paleo_workbench.mapping.scalar_raster_mirror import ScalarRasterMirrorCache
from paleo_workbench.viz.native_factor_map import MapScene
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


gdal = pytest.importorskip("osgeo.gdal")


def _scalar_snapshot():
    result = FactorGridResult.from_engine_dict(
        {
            "grid_x": [100.0, 120.0],
            "grid_y": [30.0, 50.0],
            "grid_z": [[0.0, 1.0], [0.5, None]],
            "backend": "idw",
            "n_points": 4,
        },
        factor_name="Porosity",
        crs="EPSG:3857",
    )
    scene = MapScene()
    scene.add_factor_grid(result, layer_id="porosity")
    return scene, scene.render_snapshot(project_crs="EPSG:3857").layers[0]


def test_scalar_raster_mirror_reuses_native_raster_until_a_revision_changes(tmp_path) -> None:
    scene, layer = _scalar_snapshot()
    scalar = scene.scalar_layer("porosity")
    cache = ScalarRasterMirrorCache(tmp_path)

    first = cache.ensure(layer)
    second = cache.ensure(layer)
    dataset = gdal.Open(first)

    assert first == second
    assert scalar.rasterize_count == 1
    assert dataset.RasterCount == 4
    assert dataset.GetGeoTransform() == pytest.approx((100.0, 10.0, 0.0, 50.0, 0.0, -10.0))
    assert "3857" in dataset.GetProjection()
    raw = dataset.ReadRaster(
        0, 0, dataset.RasterXSize, dataset.RasterYSize,
        buf_xsize=dataset.RasterXSize,
        buf_ysize=dataset.RasterYSize,
        buf_type=gdal.GDT_Byte,
        band_list=[1, 2, 3, 4],
        buf_pixel_space=4,
        buf_line_space=dataset.RasterXSize * 4,
        buf_band_space=1,
    )
    actual = np.frombuffer(raw, dtype=np.uint8).reshape(dataset.RasterYSize, dataset.RasterXSize, 4)
    np.testing.assert_array_equal(actual, scalar.rasterize())
    dataset = None

    scene.set_scalar_style("porosity", gamma=1.2)
    styled = scene.render_snapshot(project_crs="EPSG:3857").layers[0]
    assert cache.ensure(styled) != first
    assert scalar.rasterize_count == 2
    cache.clear()


def test_scalar_raster_mirror_does_not_require_optional_gdal_array(tmp_path, monkeypatch) -> None:
    """CI's GDAL wheel lacks ``_gdal_array`` but still supports raw band bytes."""
    scene, layer = _scalar_snapshot()
    scalar = scene.scalar_layer("porosity")
    cache = ScalarRasterMirrorCache(tmp_path)
    original_import = builtins.__import__

    def reject_gdal_array(name, *args, **kwargs):
        if name in {"osgeo.gdal_array", "_gdal_array"}:
            raise ImportError("simulated missing optional GDAL NumPy bridge")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_gdal_array)

    path = cache.ensure(layer)

    assert path.endswith(".tif")
    assert scalar.rasterize_count == 1


def test_scalar_raster_mirror_defaults_to_gdal_virtual_memory_and_reclaims_stale_versions() -> None:
    scene, layer = _scalar_snapshot()
    cache = ScalarRasterMirrorCache()

    first = cache.ensure(layer)
    assert first.startswith("/vsimem/")
    assert cache.uses_virtual_memory
    assert cache.disk_materialization_count == 0
    assert gdal.VSIStatL(first) is not None

    scene.set_scalar_style("porosity", gamma=1.2)
    styled = scene.render_snapshot(project_crs="EPSG:3857").layers[0]
    second = cache.ensure(styled)

    assert second != first
    assert cache.materialization_count == 2
    # The older source remains readable until the QGIS bridge confirms it no
    # longer owns a raster layer/job using that path.
    assert gdal.VSIStatL(first) is not None
    cache.release_stale()
    assert gdal.VSIStatL(first) is None
    assert gdal.VSIStatL(second) is not None
    cache.clear()
    assert gdal.VSIStatL(second) is None
