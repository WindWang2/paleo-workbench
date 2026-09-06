"""I15/I16 — delivery profiles and QA reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.delivery import (
    BUILTIN_PROFILES,
    DeliveryProfile,
    DeliveryService,
    get_profile,
    render_report_markdown,
)
from paleo_workbench.interchange.executor import ImportExecutor
from paleo_workbench.interchange.package import verify_package
from paleo_workbench.interchange.package.builder import ExternalPolicy

from tests import interchange_fixtures as fx


@pytest.fixture()
def project_with_data(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text(json.dumps({
        "coordinate": {"project_crs": "EPSG:4326"}
    }), encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    preflight_work = tmp_path / "work"

    from paleo_workbench.interchange.preflight import ImportPreflightService

    preflight = ImportPreflightService()
    for name, source in (
        ("W-001", fx.write_valid_las(tmp_path / "w.las")),
        ("facies", fx.write_geojson(tmp_path / "f.geojson", features=2)),
    ):
        plan = preflight.plan(source, asset_name=name)
        ImportExecutor(catalog, work_dir=preflight_work).execute(plan)
    yield project_path, catalog
    catalog.close()


def test_builtin_profiles_serializable_and_org_free():
    assert len(BUILTIN_PROFILES) >= 5
    for profile_id, profile in BUILTIN_PROFILES.items():
        payload = json.dumps(profile.to_dict(), ensure_ascii=False)
        revived = DeliveryProfile.from_dict(profile.to_dict())
        assert revived.profile_id == profile_id
        assert "机构" not in payload and "acme" not in payload.lower()
    assert get_profile("internal-archive").external_policy is ExternalPolicy.KEEP
    assert get_profile("reviewer-package").include_outputs_only is True
    with pytest.raises(KeyError):
        get_profile("nope")


def test_delivery_internal_archive_builds_verified_package(project_with_data, tmp_path):
    project_path, catalog = project_with_data
    service = DeliveryService(project_path, catalog=catalog)
    result = service.build("internal-archive", tmp_path / "out")

    assert result.package_dir is not None
    assert result.verify_ok
    assert result.report["package"]["verify_state"] == "VERIFIED"
    assert result.report_path is not None and result.report_path.is_file()
    assert result.report_markdown_path is not None
    # reports live inside the package and re-verify cleanly
    reverify = verify_package(result.package_dir)
    assert reverify.ok
    markdown = result.report_markdown_path.read_text(encoding="utf-8")
    assert "VERIFIED" in markdown
    assert "EPSG:4326" in markdown  # CRS section from project + metadata


def test_delivery_reviewer_package_excludes_intermediate(project_with_data, tmp_path):
    project_path, catalog = project_with_data
    service = DeliveryService(project_path, catalog=catalog)
    result = service.build("reviewer-package", tmp_path / "out")
    # RAW inputs excluded by the outputs-only policy, but recorded — never silent
    counts = result.plan_summary["counts"]
    assert counts.get("excluded", 0) >= 1
    assert result.plan_summary["counts"].get("included", 0) >= 1


def test_delivery_zip_container(project_with_data, tmp_path):
    from paleo_workbench.interchange.delivery import DeliveryProfile

    project_path, catalog = project_with_data
    data = get_profile("internal-archive").to_dict()
    data["container"] = "zip"
    service = DeliveryService(project_path, catalog=catalog)
    result = service.build(DeliveryProfile.from_dict(data), tmp_path / "out")
    assert result.container_path is not None
    assert result.container_path.name.endswith(".paleopkg.zip")
    assert result.verify_ok


def test_report_is_honest_about_unverified():
    """UNVERIFIED must render as UNVERIFIED — never as Verified."""
    report = {
        "project": {"name": "x"},
        "application": {"name": "paleo-workbench", "version": "0"},
        "profile": {"profile_id": "p", "display_name": "P"},
        "package": {"verify_state": "UNVERIFIED", "total_size_bytes": 0, "checked_entries": 0},
        "assets": {"count": 0},
        "warnings": [],
    }
    markdown = render_report_markdown(report)
    assert "- 包校验状态: **UNVERIFIED**" in markdown
    assert "- 包校验状态: **VERIFIED**" not in markdown
    assert "- 包校验状态: **VERIFIED_WITH_WARNINGS**" not in markdown
