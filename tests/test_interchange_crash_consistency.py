"""I20 — save/reopen/crash consistency for import/batch/export/package.

Pins the guarantees:
- failures and cancellation never leave half-written artifacts (temp files
  are cleaned, previous content untouched);
- the catalog is never polluted: a failed or cancelled flow leaves no asset,
  and a reopen after every failure finds a consistent state;
- package builds publish with a single atomic rename — an interrupted build
  never leaves a half package under the final name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.batch import BatchConversionService, ConversionJob
from paleo_workbench.interchange.contracts import CancelToken, CancelledError
from paleo_workbench.interchange.executor import ExportExecutor, ImportExecutor
from paleo_workbench.interchange.package import PackageBuilder, verify_package
from paleo_workbench.interchange.preflight import ImportPreflightService

from tests import interchange_fixtures as fx


def _make_catalog(tmp_path: Path) -> tuple[Path, DataCatalogService]:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path, DataCatalogService.open(project_path)


def _reopen_is_consistent(project_path: Path) -> DataCatalogService:
    """Reopen from disk: whatever is registered must be complete."""
    service = DataCatalogService.open(project_path)
    for asset in service.list_assets():
        for version in service.list_versions(asset.id):
            if version.managed:
                resolved = service.resolve_path(version)
                assert resolved.is_file(), f"悬空 managed 版本: {version.path}"
                assert version.sha256, "managed 版本缺少校验和"
    return service


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_import_disk_full_mid_copy_leaves_no_version(tmp_path, monkeypatch):
    """Simulate ENOSPC while the catalog copies the payload."""
    project_path, catalog = _make_catalog(tmp_path)
    try:
        las = fx.write_valid_las(tmp_path / "w.las")
        plan = ImportPreflightService().plan(las, asset_name="W")
        executor = ImportExecutor(catalog, work_dir=tmp_path / "work")

        from paleo_workbench.catalog import storage

        real_fdopen = storage.os.fdopen

        def failing_fdopen(fd, *args, **kwargs):
            stream = real_fdopen(fd, *args, **kwargs)
            real_write = stream.write

            def write(data):
                raise OSError(28, "No space left on device")

            stream.write = write
            return stream

        monkeypatch.setattr(storage.os, "fdopen", failing_fdopen)
        with pytest.raises(OSError):
            executor.execute(plan)
        monkeypatch.undo()

        assert catalog.list_assets() == []
        reopened = _reopen_is_consistent(project_path)
        assert reopened.list_assets() == []
        reopened.close()
    finally:
        catalog.close()


def test_import_failure_mid_transform_cleans_staging(tmp_path, monkeypatch):
    project_path, catalog = _make_catalog(tmp_path)
    try:
        csv_source = tmp_path / "semicolon.csv"
        csv_source.write_bytes(b"Well;Depth\nW-1;1.5\n")
        preflight = ImportPreflightService()
        plan = preflight.plan(csv_source)
        plan.options["normalize"] = True
        work = tmp_path / "work"
        executor = ImportExecutor(catalog, work_dir=work)

        from paleo_workbench.interchange.adapters import tabular_adapter

        def failing_verify(self, target, preset):
            raise RuntimeError("verify exploded")

        monkeypatch.setattr(tabular_adapter.CsvLikeAdapter, "_verify_normalized_csv", failing_verify)
        with pytest.raises(RuntimeError):
            executor.execute(plan)
        monkeypatch.undo()

        # staging temp removed, no asset, reopen clean
        assert list(work.glob("*.normalized.csv")) == []
        assert catalog.list_assets() == []
        reopened = _reopen_is_consistent(project_path)
        assert reopened.list_assets() == []
        reopened.close()
    finally:
        catalog.close()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_failure_mid_write_keeps_target_absent_or_previous(tmp_path):
    """A converter crash leaves no partial file at the destination."""
    from paleo_workbench.interchange.adapters.geojson_adapter import GeoJSONAdapter

    source = fx.write_geojson(tmp_path / "in.geojson", features=3)
    target = tmp_path / "out.geojson"
    adapter = GeoJSONAdapter()
    plan = adapter.plan_export(source, target)

    from paleo_workbench.resources import exporters

    real_replace = Path.replace

    def failing_replace(self, target_path):
        raise OSError(28, "No space left on device")

    monkeypatched = False
    try:
        Path.replace = failing_replace  # atomic_output's final replace
        with pytest.raises(OSError):
            ExportExecutor().execute(plan)
        monkeypatched = True
    finally:
        Path.replace = real_replace
    assert monkeypatched
    assert not target.exists()
    # no temp litter beside the target
    assert [p for p in tmp_path.glob(".*out.geojson*") if p.is_file()] == []


def test_export_cancel_mid_write_leaves_previous_output_intact(tmp_path):
    """Cancel during a rewrite keeps the previous verified output."""
    from paleo_workbench.interchange.adapters.geojson_adapter import GeoJSONAdapter

    source = fx.write_geojson(tmp_path / "in.geojson", features=3)
    target = tmp_path / "out.geojson"
    adapter = GeoJSONAdapter()
    plan = adapter.plan_export(source, target)
    ExportExecutor().execute(plan)
    first = target.read_bytes()

    token = CancelToken()
    executor = ExportExecutor()
    adapter = executor.registry().get("geojson")
    real_export = adapter.export_data

    def cancel_then_export(source_path, plan, **kwargs):
        token.cancel("mid rewrite")
        return real_export(source_path, plan, **kwargs)

    adapter.export_data = cancel_then_export
    with pytest.raises(CancelledError):
        executor.execute(plan, cancel=token)
    assert target.read_bytes() == first


# ---------------------------------------------------------------------------
# Package
# ---------------------------------------------------------------------------


def test_package_crash_mid_build_leaves_no_half_package(tmp_path, monkeypatch):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        las = fx.write_valid_las(tmp_path / "w.las")
        plan = ImportPreflightService().plan(las, asset_name="W")
        ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)

        from paleo_workbench.interchange.package import builder as builder_module

        calls = {"n": 0}
        real_sha = builder_module.sha256_file

        def crashing_sha(path):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("crash mid-build")
            return real_sha(path)

        monkeypatch.setattr(builder_module, "sha256_file", crashing_sha)
        builder = PackageBuilder(project_path, catalog=catalog)
        out = tmp_path / "out"
        with pytest.raises(RuntimeError):
            builder.build(out)
        monkeypatch.undo()

        # no package dir under the final name, staging cleaned
        assert not (out / "demo").exists()
        assert not any(p.name.endswith(".staging") for p in out.iterdir() if p.is_dir())

        # a later build succeeds and verifies
        build = PackageBuilder(project_path, catalog=catalog).build(out)
        assert verify_package(build.package_dir).ok
    finally:
        catalog.close()


def test_reopen_after_all_failures_is_clean(tmp_path, monkeypatch):
    """Interleave every failure mode, then reopen: consistent, queryable."""
    project_path, catalog = _make_catalog(tmp_path)
    try:
        # one successful import first
        good = fx.write_valid_las(tmp_path / "good.las")
        ImportPreflightService()
        ImportExecutor(catalog, work_dir=tmp_path / "work").execute(
            ImportPreflightService().plan(good, asset_name="GOOD")
        )
        # a failing import (disk full)
        broken = fx.write_valid_las(tmp_path / "bad.las")
        from paleo_workbench.catalog import storage

        def failing_fdopen(fd, *args, **kwargs):
            stream = storage.os.fdopen.__wrapped__(fd, *args, **kwargs) if hasattr(
                storage.os.fdopen, "__wrapped__"
            ) else None
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(storage.os, "fdopen", failing_fdopen)
        with pytest.raises(OSError):
            ImportExecutor(catalog, work_dir=tmp_path / "work").execute(
                ImportPreflightService().plan(broken, asset_name="BAD")
            )
        monkeypatch.undo()

        reopened = _reopen_is_consistent(project_path)
        try:
            assets = reopened.list_assets()
            assert len(assets) == 1
            assert assets[0].name == "GOOD"
            assert reopened.list_runs()  # provenance recorded for the success
        finally:
            reopened.close()
    finally:
        catalog.close()


def test_batch_item_failure_does_not_corrupt_sibling_outputs(tmp_path):
    """One item failing mid-run must not affect another item's output bytes."""
    ok_source = fx.write_geojson(tmp_path / "ok.geojson", features=2)
    broken = tmp_path / "broken.geojson"
    broken.write_text("{", encoding="utf-8")

    service = BatchConversionService(max_workers=1)
    result = service.convert(
        [ConversionJob(source=ok_source, target_format="geojson"),
         ConversionJob(source=broken, target_format="geojson")],
        output_dir=tmp_path / "out",
    )
    summary = result.summary()
    assert summary["converted"] == 1 and summary.get("failed", 0) == 1
    output = tmp_path / "out" / "ok.geojson"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
