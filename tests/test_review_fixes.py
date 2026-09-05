"""Regression tests for the three-round review findings.

Each test pins one fixed defect so it cannot silently return.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.batch import BatchConversionService, ConversionJob
from paleo_workbench.interchange.contracts import CancelToken
from paleo_workbench.interchange.dependency_audit import (
    DependencyRecord,
    DependencyStatus,
    ExternalDependencyAuditor,
)
from paleo_workbench.interchange.executor import ExportExecutor, ImportExecutor
from paleo_workbench.interchange.package import verify_package
from paleo_workbench.interchange.package.manifest import (
    PackageEntry,
    PackageManifest,
)
from paleo_workbench.interchange.path_safety import UnsafePathError, safe_relative_path
from paleo_workbench.interchange.preflight import ImportPreflightService

from tests import interchange_fixtures as fx


def test_big_plain_csv_not_sniffed_as_segy(tmp_path):
    """R1-P1: any text >=3600B used to sniff as SEG-Y and block import."""
    csv_path = fx.write_csv(tmp_path / "big.csv", rows=400)
    assert csv_path.stat().st_size > 3600
    report = ImportPreflightService().inspect(csv_path)
    assert report.adapter_id == "csv", f"sniff={report.sniff}"
    assert report.ok
    assert report.recommendation == "managed_copy"


def test_advisory_sniff_does_not_veto_extension_adapter(tmp_path):
    """A non-high-confidence sniff must not hard-fail the extension adapter."""
    # npz whose descriptor lies beyond the probe window sniffs as generic zip
    import numpy as np

    npz = tmp_path / "grid.npz"
    np.savez(npz, data=np.zeros((4, 4)), other=np.zeros((4, 4)))
    report = ImportPreflightService().inspect(npz)
    # factor_grid is not an import adapter; the point is: no crash and an
    # honest report either way, never a bogus extension-content-mismatch error
    codes = {i.code for i in report.issues}
    assert "extension-content-mismatch" not in codes or report.sniff.confidence == "high"


def test_raster_dtype_converting_export_verifies(tmp_path):
    """R1-P1: float32->uint8 export must not fail its own pixel probe."""
    pytest.importorskip("rasterio")
    from paleo_workbench.interchange.adapters.raster_adapter import RasterAdapter
    from paleo_workbench.interchange.contracts import VerificationState

    src = fx.write_geotiff(tmp_path / "src.tif", width=32, height=24)
    target = tmp_path / "out.tif"
    adapter = RasterAdapter()
    plan = adapter.plan_export(src, target, options={"dtype": "uint8"})
    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.VERIFIED, verification.summary()


def test_tsv_to_csv_export_actually_converts_delimiter(tmp_path):
    """R1-P1: TSV->CSV must not keep tabs inside the first column."""
    from paleo_workbench.interchange.adapters.tabular_adapter import TsvAdapter
    from paleo_workbench.interchange.contracts import VerificationState

    source = fx.write_csv(tmp_path / "in.tsv", delimiter="\t", rows=4)
    target = tmp_path / "out.csv"
    adapter = TsvAdapter()
    plan = adapter.plan_export(source, target)
    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.VERIFIED
    content = target.read_text(encoding="utf-8")
    assert "\t" not in content
    assert content.count(",") >= 2


def test_zip_delivery_contains_reports(tmp_path):
    """R1-P1: zip-container delivery must ship its QA reports."""
    from paleo_workbench.interchange.delivery import DeliveryService, get_profile

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        data = get_profile("internal-archive").to_dict()
        data["container"] = "zip"
        from paleo_workbench.interchange.delivery import DeliveryProfile

        service = DeliveryService(project_path, catalog=catalog)
        result = service.build(DeliveryProfile.from_dict(data), tmp_path / "out")
        with zipfile.ZipFile(result.container_path) as bundle:
            names = set(bundle.namelist())
        assert "delivery-report.json" in names
        assert "delivery-report.md" in names
    finally:
        catalog.close()


def test_export_provenance_registered_through_record_export(tmp_path):
    """R-Arch-F1: verified exports land an OUTPUT version via the single
    export choke point, with lineage to the source version."""
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        from paleo_workbench.interchange.adapters.geojson_adapter import GeoJSONAdapter
        from paleo_workbench.interchange.preflight import ImportPreflightService

        source = fx.write_geojson(tmp_path / "in.geojson", features=2)
        plan = ImportPreflightService().plan(source, asset_name="in")
        import_result = ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)

        target = tmp_path / "out.geojson"
        adapter = GeoJSONAdapter()
        export_plan = adapter.plan_export(source, target)
        export_plan.source_version_ids = [import_result.version_id]
        _, verification = ExportExecutor(catalog=catalog).execute(export_plan)
        assert verification.ok

        runs = [r for r in catalog.list_runs() if r.operation == "export"]
        assert runs, "导出必须记录 export run"
        # register_output stores `kind` as the output asset's type
        export_assets = [a for a in catalog.list_assets() if a.type == "export"]
        assert export_assets, "导出必须注册 OUTPUT 资产"
        output_versions = [
            v for asset in export_assets for v in catalog.list_versions(asset.id)
        ]
        assert output_versions and all(
            v.stage.value == "output" for v in output_versions
        )
    finally:
        catalog.close()


def test_relink_refuses_when_no_identity_recorded():
    """R-Adv: no size and no hash → any file would "match"; refuse to guess."""
    auditor = ExternalDependencyAuditor(catalog=None)
    record = DependencyRecord(
        version_id="ver_x", asset_name="x", managed=False, path="/gone",
        status=DependencyStatus.MISSING, expected_size=None, expected_sha256=None,
    )
    assert auditor.find_relink_candidates(record, [Path("/tmp")]) == []


def test_path_safety_rejects_trailing_dots_and_spaces():
    """R-Adv: 'com1 ' / 'file.txt.' defeat NTFS reserved/overwrite defenses."""
    for name in ("com1 ", "file.txt.", "file ", "NUL."):
        with pytest.raises(UnsafePathError):
            safe_relative_path(name)


def test_manifest_duplicate_entries_rejected(tmp_path):
    """R-Adv: duplicate manifest entries must not verify ok with inflated counts."""
    manifest = PackageManifest(project_name="p", project_file="p.paleo.json",
                               total_size_bytes=10)
    manifest.entries.append(PackageEntry(
        path="a.txt", sha256="x", size_bytes=5, kind="artifact"))
    manifest.entries.append(PackageEntry(
        path="a.txt", sha256="x", size_bytes=5, kind="artifact"))
    with pytest.raises(Exception):
        manifest.validate_paths()


def test_batch_serial_job_cancel_is_isolated(tmp_path):
    """R-Adv: one job's internal CancelledError must not stop the batch when
    the shared token was never cancelled."""
    sources = [fx.write_geojson(tmp_path / f"g{i}.geojson", features=1) for i in range(3)]

    service = BatchConversionService(max_workers=1)
    executor_holder = {}

    real_execute = ExportExecutor.execute

    def flaky_execute(self, plan, **kwargs):
        if Path(plan.source_path).name.startswith("g1"):
            raise __import__(
                "paleo_workbench.interchange.contracts", fromlist=["CancelledError"]
            ).CancelledError("adapter-internal cancel")
        return real_execute(self, plan, **kwargs)

    ExportExecutor.execute = flaky_execute
    try:
        result = service.convert(
            [ConversionJob(source=s, target_format="geojson") for s in sources],
            output_dir=tmp_path / "out",
        )
    finally:
        ExportExecutor.execute = real_execute

    summary = result.summary()
    assert summary["converted"] == 2
    assert summary["cancelled"] == 1
    assert not result.cancelled  # shared token untouched


def test_batch_progress_exception_does_not_lose_result(tmp_path):
    sources = [fx.write_geojson(tmp_path / f"p{i}.geojson", features=1) for i in range(4)]

    def exploding_progress(done, total, current):
        raise ValueError("progress boom")

    service = BatchConversionService(max_workers=1)
    result = service.convert(
        [ConversionJob(source=s, target_format="geojson") for s in sources],
        output_dir=tmp_path / "out",
        progress=exploding_progress,
    )
    summary = result.summary()
    assert summary["total"] == 4
    assert summary["converted"] == 4


def test_verify_detects_lying_total_size(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "p.paleo.json").write_text("{}", encoding="utf-8")
    from paleo_workbench.interchange.package.manifest import write_manifest

    manifest = PackageManifest(
        project_name="p", project_file="p.paleo.json", total_size_bytes=10 ** 9
    )
    manifest.entries.append(PackageEntry(
        path="p.paleo.json",
        sha256=__import__("hashlib").sha256(b"{}").hexdigest(),
        size_bytes=2, kind="project",
    ))
    write_manifest(manifest, package)
    report = verify_package(package, deep=False)
    assert any(i.code == "total-size-mismatch" for i in report.issues)


def test_manifest_schema_version_must_be_int(tmp_path):
    from paleo_workbench.interchange.package.manifest import PackageManifest

    with pytest.raises(ValueError):
        PackageManifest.from_dict({"schema_version": 2.9})
    with pytest.raises(ValueError):
        PackageManifest.from_dict({"schema_version": True})


def test_directory_package_rejects_symlinks(tmp_path):
    package = tmp_path / "pkg"
    (package / "inner").mkdir(parents=True)
    (package / "p.paleo.json").write_text("{}", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    try:
        (package / "leak.txt").symlink_to(secret)
    except OSError:
        pytest.skip("symlink 不可用")
    from paleo_workbench.interchange.package import open_package

    with pytest.raises(UnsafePathError):
        open_package(package, tmp_path / "restore")
    # nothing was materialized
    assert not (tmp_path / "restore" / "pkg").exists()
