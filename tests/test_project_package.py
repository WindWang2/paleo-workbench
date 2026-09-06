"""I10/I11/I12 — portable package build, manifest V2, verify and reopen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.executor import ImportExecutor
from paleo_workbench.interchange.package import (
    ExternalPolicy,
    PackageBuilder,
    PackageOptions,
    open_package,
    verify_package,
)

from tests import interchange_fixtures as fx


def _make_project(tmp_path: Path) -> tuple[Path, DataCatalogService]:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    return project_path, catalog


def _import_fixture(catalog: DataCatalogService, source: Path, work: Path, name: str) -> str:
    from paleo_workbench.interchange.preflight import ImportPreflightService

    preflight = ImportPreflightService()
    plan = preflight.plan(source, asset_name=name)
    result = ImportExecutor(catalog, work_dir=work).execute(plan)
    return result.version_id


@pytest.fixture()
def populated_project(tmp_path):
    project_path, catalog = _make_project(tmp_path)
    work = tmp_path / "work"
    las = fx.write_valid_las(tmp_path / "w1.las")
    gj = fx.write_geojson(tmp_path / "facies.geojson", features=3)
    _import_fixture(catalog, las, work, "W-001")
    _import_fixture(catalog, gj, work, "facies")
    yield project_path, catalog
    catalog.close()


def test_build_package_with_managed_artifacts(populated_project, tmp_path):
    project_path, catalog = populated_project
    builder = PackageBuilder(project_path, catalog=catalog)
    plan = builder.plan()
    summary = plan.summary()
    assert summary["counts"]["included"] >= 3  # project + 2 managed payloads
    result = builder.build(tmp_path / "out")

    assert result.package_dir.name == "demo"
    assert (result.package_dir / "demo.paleo.json").is_file()
    assert (result.package_dir / "demo.artifacts" / "metadata" / "catalog.json").is_file()
    manifest = result.manifest
    assert manifest.schema_version == 2
    assert manifest.project_name == "demo"
    assert manifest.total_size_bytes > 0
    # manifest paths are relative and cover what was shipped
    for entry in manifest.entries:
        assert not Path(entry.path).is_absolute()
        assert ".." not in entry.path.split("/")
        assert (result.package_dir / entry.path).is_file()
    # managed payload paths survived as project-relative (catalog semantics)
    las_versions = [
        v for asset in catalog.list_assets() for v in catalog.list_versions(asset.id)
        if v.format == "las"
    ]
    assert las_versions
    for version in las_versions:
        packaged = result.package_dir / version.path
        assert packaged.is_file()


def test_manifest_records_provenance_and_outputs(populated_project, tmp_path):
    project_path, catalog = populated_project
    builder = PackageBuilder(project_path, catalog=catalog)
    result = builder.build(tmp_path / "out")
    assert result.manifest.provenance.get("run_count", 0) >= 1
    reread = verify_package(result.package_dir)
    assert reread.ok


def test_verify_detects_checksum_mismatch(populated_project, tmp_path):
    project_path, catalog = populated_project
    builder = PackageBuilder(project_path, catalog=catalog)
    result = builder.build(tmp_path / "out")
    # tamper with a packaged artifact, keeping size identical so the hash
    # check (not the earlier size gate) catches it
    las_versions = [
        v for asset in catalog.list_assets() for v in catalog.list_versions(asset.id)
        if v.format == "las"
    ]
    payload = result.package_dir / las_versions[0].path
    payload.chmod(0o644)
    original = payload.read_bytes()
    payload.write_bytes(bytes([b ^ 0xFF for b in original]))
    report = verify_package(result.package_dir)
    assert not report.ok
    assert any(i.code == "checksum-mismatch" for i in report.issues)


def test_verify_detects_missing_and_unknown_entries(populated_project, tmp_path):
    project_path, catalog = populated_project
    result = PackageBuilder(project_path, catalog=catalog).build(tmp_path / "out")
    entries = list(result.manifest.entries)
    victim = result.package_dir / entries[-1].path
    victim.unlink()
    (result.package_dir / "rogue.txt").write_text("?", encoding="utf-8")
    report = verify_package(result.package_dir)
    assert any(i.code == "missing-entry" for i in report.issues)
    assert any(i.code == "unknown-file" and i.severity == "warning" for i in report.issues)
    assert not report.ok  # missing entry is an error


def test_verify_rejects_unsupported_schema(populated_project, tmp_path):
    project_path, catalog = populated_project
    result = PackageBuilder(project_path, catalog=catalog).build(tmp_path / "out")
    manifest_path = result.package_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 999
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    report = verify_package(result.package_dir)
    assert not report.ok
    assert any(i.code == "unsupported-schema" for i in report.issues)


def test_package_reopens_at_new_root(populated_project, tmp_path):
    """Copy to a brand-new root and reopen: managed artifacts resolve, catalog
    is queryable, provenance intact."""
    project_path, catalog = populated_project
    result = PackageBuilder(project_path, catalog=catalog).build(tmp_path / "out")

    new_root = tmp_path / "elsewhere"
    new_root.mkdir()
    shutil_copytree = __import__("shutil").copytree
    relocated = new_root / "copy"
    shutil_copytree(result.package_dir, relocated)

    reopened = DataCatalogService.open(relocated / "demo.paleo.json")
    try:
        assets = reopened.list_assets()
        assert len(assets) == 2
        for asset in assets:
            for version in reopened.list_versions(asset.id):
                resolved = reopened.resolve_path(version)
                assert resolved.is_file(), f"{version.path} 未解析到新根"
                # content integrity across the move
                assert sha256_file(resolved) == version.sha256
    finally:
        reopened.close()


def test_zip_container_roundtrip(populated_project, tmp_path):
    project_path, catalog = populated_project
    builder = PackageBuilder(project_path, catalog=catalog)
    zip_path = builder.build_zip(tmp_path / "out")
    assert zip_path.name == "demo.paleopkg.zip"
    report = verify_package(zip_path)
    assert report.ok

    package_dir, open_report = open_package(zip_path, tmp_path / "restore")
    assert open_report.ok
    assert (package_dir / "demo.paleo.json").is_file()
    reopened = DataCatalogService.open(package_dir / "demo.paleo.json")
    try:
        assert len(reopened.list_assets()) == 2
    finally:
        reopened.close()


def test_external_dependency_policies(tmp_path):
    """keep / vendor / exclude all leave explicit manifest records."""
    project_path, catalog = _make_project(tmp_path)
    try:
        outside = tmp_path / "outside"
        outside.mkdir()
        big = fx.write_valid_las(outside / "ext.w.las")
        version = catalog.link_external(big, name="ext-las", type="well_log", format="las")

        for policy, expect_packaged in (
            (ExternalPolicy.KEEP, False),
            (ExternalPolicy.VENDOR, True),
            (ExternalPolicy.EXCLUDE, False),
        ):
            out = tmp_path / f"out-{policy.value}"
            result = PackageBuilder(
                project_path, catalog=catalog, options=PackageOptions(external_policy=policy)
            ).build(out)
            deps = result.manifest.external_dependencies
            assert len(deps) == 1 and deps[0]["policy"] == policy.value
            vendored = (
                out / "demo" / "artifacts" / "external" / "ext-las" / version.id / "ext.w.las"
            )
            assert vendored.is_file() is expect_packaged
    finally:
        catalog.close()


def test_builder_refuses_non_project_file(tmp_path):
    with pytest.raises(ValueError):
        PackageBuilder(tmp_path / "notaproject.json")


def test_build_refuses_existing_package_dir(populated_project, tmp_path):
    project_path, catalog = populated_project
    builder = PackageBuilder(project_path, catalog=catalog)
    builder.build(tmp_path / "out")
    with pytest.raises(FileExistsError):
        builder.build(tmp_path / "out")
