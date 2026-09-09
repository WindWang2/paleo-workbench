"""I5/I6 — GeoJSON, raster and GDAL vector adapters."""

from __future__ import annotations

import pytest

from paleo_workbench.interchange.adapters.geojson_adapter import GeoJSONAdapter
from paleo_workbench.interchange.contracts import FormatNotSupportedError, VerificationState
from paleo_workbench.interchange.executor import ExportExecutor

from tests import interchange_fixtures as fx


@pytest.fixture()
def adapter():
    return GeoJSONAdapter()


def test_inspect_geojson_counts_features_and_bounds(tmp_path, adapter):
    gj = fx.write_geojson(tmp_path / "a.geojson", features=6, crs="EPSG:4326")
    inspection = adapter.inspect(gj)
    assert inspection.ok
    assert inspection.metadata["feature_count"] == 6
    assert inspection.crs == "EPSG:4326"
    assert inspection.dataset_bounds is not None
    assert inspection.metadata["geometry_types"] == ["Point"]
    assert inspection.warnings == []


def test_inspect_geojson_flags_mixed_geometry_and_missing_crs(tmp_path, adapter):
    gj = fx.write_geojson(tmp_path / "a.geojson", features=4, mixed=True)
    inspection = adapter.inspect(gj)
    assert any("混合几何类型" in w for w in inspection.warnings)
    assert any("CRS" in w for w in inspection.warnings)


def test_inspect_truncated_geojson_fails(tmp_path, adapter):
    gj = fx.write_truncated_geojson(tmp_path / "cut.geojson")
    inspection = adapter.inspect(gj)
    assert not inspection.ok
    assert any("截断" in e or "解析失败" in e for e in inspection.errors)


def test_geojson_export_roundtrip_preserves_count_and_bounds(tmp_path, adapter):
    gj = fx.write_geojson(tmp_path / "src.geojson", features=8, crs="EPSG:4326")
    inspection = adapter.inspect(gj)
    plan = adapter.plan_export(gj, tmp_path / "out.geojson", options={})
    plan.options["feature_count"] = inspection.metadata["feature_count"]
    plan.options["bounds"] = list(inspection.dataset_bounds)
    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.VERIFIED


def test_geojson_export_verify_catches_count_mismatch(tmp_path, adapter):
    gj = fx.write_geojson(tmp_path / "src.geojson", features=3)
    plan = adapter.plan_export(gj, tmp_path / "out.geojson")
    plan.options["feature_count"] = 99  # tampered expectation
    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.FAILED
    assert any(c.name == "feature_count" and not c.passed for c in verification.checks)


def test_geojson_plan_export_rejects_non_geojson_target(tmp_path, adapter):
    gj = fx.write_geojson(tmp_path / "src.geojson")
    with pytest.raises(FormatNotSupportedError):
        adapter.plan_export(gj, tmp_path / "out.shp")


def test_geojson_import_registers_version(tmp_path, adapter):
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.interchange.executor import ImportExecutor

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        gj = fx.write_geojson(tmp_path / "facies.geojson", features=3)
        plan = adapter.plan_import(gj, adapter.inspect(gj))
        result = ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)
        version = catalog.get_version(result.version_id)
        assert version.managed and version.sha256
        assert catalog.get_asset(result.asset_id).metadata.get("feature_count") == 3
    finally:
        catalog.close()


# ---------------------------------------------------------------------------
# Raster (rasterio is a hard dependency; guard anyway)
# ---------------------------------------------------------------------------


@pytest.fixture()
def raster_adapter():
    pytest.importorskip("rasterio")
    from paleo_workbench.interchange.adapters.raster_adapter import RasterAdapter

    return RasterAdapter()


def test_raster_inspect_reports_crs_nodata_bounds(tmp_path, raster_adapter):
    tif = fx.write_geotiff(tmp_path / "r.tif")
    inspection = raster_adapter.inspect(tif)
    assert inspection.ok
    assert inspection.crs == "EPSG:4326"
    assert inspection.metadata["nodata"] == pytest.approx(-9999.0)
    assert inspection.dataset_bounds is not None
    assert inspection.metadata["width"] == 32
    assert inspection.metadata["finite_ratio"] > 0.9


def test_raster_inspect_missing_crs_warns(tmp_path, raster_adapter):
    tif = fx.write_geotiff(tmp_path / "r.tif", epsg=None)
    inspection = raster_adapter.inspect(tif)
    assert any("CRS" in w for w in inspection.warnings)


def test_raster_export_roundtrip_grid_and_nodata(tmp_path, raster_adapter):
    tif = fx.write_geotiff(tmp_path / "src.tif", width=64, height=48)
    target = tmp_path / "out.tif"
    plan = raster_adapter.plan_export(tif, target)
    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.VERIFIED
    names = {c.name: c.passed for c in verification.checks}
    assert names["grid_shape"] and names["crs_preserved"] and names["nodata_preserved"]
    assert names["bounds_preserved"] and names["pixel_probe"]


def test_raster_export_verify_detects_grid_mismatch(tmp_path, raster_adapter):
    tif = fx.write_geotiff(tmp_path / "src.tif")
    plan = raster_adapter.plan_export(tif, tmp_path / "out.tif")
    # Export something else at the target, then verify against the plan.
    fx.write_geotiff(plan.target_path and tmp_path / "other.tif", width=8, height=8)
    import shutil

    shutil.copy(tmp_path / "other.tif", plan.target_path)
    verification = raster_adapter.verify_output(plan.target_path, plan)
    assert verification.state is VerificationState.FAILED


def test_raster_rejects_non_tiff_target(tmp_path, raster_adapter):
    tif = fx.write_geotiff(tmp_path / "src.tif")
    with pytest.raises(FormatNotSupportedError):
        raster_adapter.plan_export(tif, tmp_path / "out.png")


# ---------------------------------------------------------------------------
# GDAL vector
# ---------------------------------------------------------------------------


@pytest.fixture()
def vector_adapter():
    if not fx.ogr_available():
        pytest.skip("osgeo.gdal 不可用（vendored 构建未安装）")
    from paleo_workbench.interchange.adapters.vector_adapter import VectorAdapter

    return VectorAdapter()


def test_vector_inspect_shapefile_with_sidecars(tmp_path, vector_adapter):
    shp = fx.write_point_shapefile(tmp_path / "pts.shp")
    inspection = vector_adapter.inspect(shp)
    assert inspection.ok
    layer = inspection.metadata["layers"][0]
    assert layer["feature_count"] == 6
    assert layer["crs"] == "EPSG:4326"
    assert inspection.warnings == []


def test_vector_inspect_flags_missing_sidecars(tmp_path, vector_adapter):
    shp = fx.write_point_shapefile(tmp_path / "pts.shp")
    shp.with_suffix(".dbf").unlink()
    shp.with_suffix(".shx").unlink()
    inspection = vector_adapter.inspect(shp)
    assert not inspection.ok
    assert any("sidecar" in e for e in inspection.errors)


def test_vector_inspect_flags_missing_prj(tmp_path, vector_adapter):
    shp = fx.write_point_shapefile(tmp_path / "pts.shp", with_prj=False)
    inspection = vector_adapter.inspect(shp)
    assert any(".prj" in w for w in inspection.warnings)


def test_vector_shapefile_managed_import_bundles_sidecars(tmp_path, vector_adapter):
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.interchange.executor import ImportExecutor
    import zipfile

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        shp = fx.write_point_shapefile(tmp_path / "pts.shp")
        report_plan = vector_adapter.plan_import(shp, vector_adapter.inspect(shp))
        assert report_plan.action == "transform_import"
        result = ImportExecutor(catalog, work_dir=tmp_path / "work").execute(report_plan)
        version = catalog.get_version(result.version_id)
        registered = catalog.resolve_path(version)
        assert version.format == "shp_bundle"
        with zipfile.ZipFile(registered) as bundle:
            names = set(bundle.namelist())
        assert {"pts.shp", "pts.shx", "pts.dbf", "pts.prj"} <= names
    finally:
        catalog.close()


def test_vector_gpkg_inspect(tmp_path, vector_adapter):
    from osgeo import ogr, osr

    if ogr.GetDriverByName("GPKG") is None:
        pytest.skip("GPKG driver unavailable (vendored GDAL build lacks it)")
    gpkg = tmp_path / "layers.gpkg"
    driver = ogr.GetDriverByName("GPKG")
    datasource = driver.CreateDataSource(str(gpkg))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(4326)
    layer = datasource.CreateLayer("zone_a", spatial_ref, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("相", ogr.OFTString))
    datasource = None

    inspection = vector_adapter.inspect(gpkg)
    assert inspection.ok
    assert inspection.metadata["layers"][0]["name"] == "zone_a"
    assert inspection.metadata["layers"][0]["crs"] == "EPSG:4326"
