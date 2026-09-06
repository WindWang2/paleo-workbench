"""I18 — compatibility fixture matrix: normal / damaged / cross-root.

Every fixture is generated in-process and tiny. The matrix pins the
preflight/adapter behavior contract: damaged inputs are diagnosed (warnings
or errors), never crash, and never leave catalog state behind.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.executor import ImportExecutor
from paleo_workbench.interchange.package import verify_package
from paleo_workbench.interchange.preflight import ImportPreflightService

from tests import interchange_fixtures as fx


# ---------------------------------------------------------------------------
# Normal cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", [
    "minimal.las",
    "中文名_测井.las",
    "W-001_井位.las",
])
def test_normal_las_variants(tmp_path, filename):
    las = fx.write_valid_las(tmp_path / filename, rows=5)
    preflight = ImportPreflightService()
    report = preflight.inspect(las)
    assert report.ok, report.to_dict()
    assert report.adapter_id == "las"


def test_normal_geojson_empty_optional_fields(tmp_path):
    path = tmp_path / "稀相.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": None},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    report = ImportPreflightService().inspect(path)
    assert report.ok
    assert report.inspection.metadata["feature_count"] == 1


def test_normal_multi_layer_gpkg(tmp_path):
    if not fx.ogr_available():
        pytest.skip("osgeo.gdal 不可用")
    from osgeo import ogr, osr

    gpkg = tmp_path / "多层.gpkg"
    datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(gpkg))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(4326)
    for name in ("zone_a", "zone_b"):
        datasource.CreateLayer(name, spatial_ref, ogr.wkbPoint)
    datasource = None
    report = ImportPreflightService().inspect(gpkg)
    assert report.ok
    assert len(report.inspection.metadata["layers"]) == 2


# ---------------------------------------------------------------------------
# Damaged cases — diagnosed, never crash, never register
# ---------------------------------------------------------------------------


DAMAGED_CASES = {
    "truncated_las": ("cut.las", lambda p: fx.write_truncated_las(p)),
    "truncated_geojson": ("cut.geojson", lambda p: fx.write_truncated_geojson(p)),
    "corrupt_xlsx": ("book.xlsx", lambda p: p.write_bytes(b"not an excel file" * 8)),
    "wrong_extension": ("photo.tif", lambda p: fx.write_valid_las(p, rows=2)),
    "empty_file": ("empty.las", lambda p: p.write_bytes(b"")),
    "binary_garbage": ("noise.dat", lambda p: p.write_bytes(bytes(range(256)) * 4)),
}


@pytest.mark.parametrize("case", sorted(DAMAGED_CASES))
def test_damaged_inputs_are_diagnosed(tmp_path, case):
    filename, builder = DAMAGED_CASES[case]
    path = tmp_path / filename
    builder(path)
    preflight = ImportPreflightService()
    report = preflight.inspect(path)
    payload = report.to_dict()  # must be serializable (UI-facing)
    # a damaged input either passes with explicit warnings, or fails with
    # errors — but SOMETHING must be said
    assert report.issues, f"{case}: 损坏输入未产生任何诊断"
    if not report.ok:
        assert report.recommendation == "unavailable"


@pytest.mark.parametrize("case", sorted(DAMAGED_CASES))
def test_damaged_inputs_never_pollute_catalog(tmp_path, case):
    filename, builder = DAMAGED_CASES[case]
    path = tmp_path / filename
    builder(path)
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        preflight = ImportPreflightService()
        before = len(catalog.list_assets())
        try:
            plan = preflight.plan(path)
            if plan.action != "unsupported":
                ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)
        except Exception:
            pass
        # only genuinely importable damaged inputs (warnings, not errors) may
        # add assets; everything rejected must leave zero traces
        if not report_ok(preflight, path):
            assert len(catalog.list_assets()) == before, f"{case}: 被拒输入留下了资产"
    finally:
        catalog.close()


def report_ok(preflight, path) -> bool:
    return preflight.inspect(path).ok


def test_damaged_shapefile_missing_sidecar_fails_closed(tmp_path):
    if not fx.ogr_available():
        pytest.skip("osgeo.gdal 不可用")
    shp = fx.write_point_shapefile(tmp_path / "pts.shp")
    shp.with_suffix(".dbf").unlink()
    report = ImportPreflightService().inspect(shp)
    assert not report.ok
    assert report.recommendation == "unavailable"


def test_checksum_mismatch_detected_by_package_verify(tmp_path):
    """The damaged-package case: bytes flip after packaging."""
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    from paleo_workbench.interchange.package import PackageBuilder

    result = PackageBuilder(project_path).build(tmp_path / "out")
    target = result.package_dir / "demo.paleo.json"
    target.write_bytes(bytes([b ^ 0x01 for b in target.read_bytes()]))
    report = verify_package(result.package_dir)
    assert not report.ok
    assert any(i.code == "checksum-mismatch" for i in report.issues)


# ---------------------------------------------------------------------------
# Cross-root cases — package survives relocation; externals stay explicit
# ---------------------------------------------------------------------------


def test_cross_root_package_with_changed_external(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        outside = tmp_path / "outside"
        outside.mkdir()
        external = fx.write_valid_las(outside / "ext.las", rows=4)
        catalog.link_external(external, name="ext", type="well_log", format="las")

        from paleo_workbench.interchange.package import PackageBuilder

        build = PackageBuilder(project_path, catalog=catalog).build(tmp_path / "out")

        # relocate the package to a brand-new root
        new_root = tmp_path / "newroot"
        new_root.mkdir()
        relocated = new_root / "demo"
        shutil.copytree(build.package_dir, relocated)
        # the external source has vanished in this scenario
        shutil.rmtree(outside)

        reopened = DataCatalogService.open(relocated / "demo.paleo.json")
        try:
            from paleo_workbench.interchange.dependency_audit import (
                DependencyStatus,
                ExternalDependencyAuditor,
            )

            audit = ExternalDependencyAuditor(reopened).audit()
            externals = [r for r in audit.records if not r.managed]
            assert externals, "外部引用必须在新根仍显式存在"
            assert all(r.status is DependencyStatus.MISSING for r in externals)
            # managed content (project file) survives
            assert (relocated / "demo.paleo.json").is_file()
        finally:
            reopened.close()
    finally:
        catalog.close()


def test_cross_root_relative_path_resolution(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        las = fx.write_valid_las(tmp_path / "w.las")
        plan = ImportPreflightService().plan(las, asset_name="W")
        ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)

        from paleo_workbench.interchange.package import PackageBuilder

        build = PackageBuilder(project_path, catalog=catalog).build(tmp_path / "out")
        relocated = tmp_path / "moved"
        shutil.copytree(build.package_dir, relocated)
        reopened = DataCatalogService.open(relocated / "demo.paleo.json")
        try:
            for asset in reopened.list_assets():
                for version in reopened.list_versions(asset.id):
                    # managed paths are project-relative and must resolve
                    resolved = reopened.resolve_path(version)
                    assert resolved.is_file()
                    assert str(relocated) in str(resolved)  # truly the new root
        finally:
            reopened.close()
    finally:
        catalog.close()
