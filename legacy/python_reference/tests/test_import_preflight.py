"""I2 — unified import preflight and executor against the real catalog.

Pins the fail-closed guarantee: a rejected preflight never creates a catalog
asset, and a cancelled execution never lands a half-registered version.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.interchange.contracts import (
    CancelToken,
    CancelledError,
    PreflightFailedError,
)
from paleo_workbench.interchange.executor import ImportExecutor
from paleo_workbench.interchange.preflight import ImportPreflightService

from tests import interchange_fixtures as fx


@pytest.fixture()
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    yield service
    service.close()


@pytest.fixture()
def preflight():
    return ImportPreflightService()


def test_preflight_happy_path_reports_recommendation(tmp_path, preflight):
    las = fx.write_valid_las(tmp_path / "w.las")
    report = preflight.inspect(las)
    assert report.ok
    assert report.adapter_id == "las"
    assert report.recommendation == "managed_copy"
    assert report.estimated_disk_bytes == las.stat().st_size
    assert report.sniff.evidence == "las-version-section"
    payload = report.to_dict()
    assert payload["inspection"]["metadata"]["well_name"] == "W-001"


def test_preflight_unknown_format_is_error_not_guess(tmp_path, preflight):
    mystery = tmp_path / "mystery.bin"
    mystery.write_bytes(b"\x00\x01\x02" * 64)
    report = preflight.inspect(mystery)
    assert not report.ok
    assert report.recommendation == "unavailable"


def test_preflight_missing_file(tmp_path, preflight):
    report = preflight.inspect(tmp_path / "nope.las")
    assert not report.ok
    assert report.issues[0].code == "missing-file"


def test_preflight_wrong_extension_fails_closed(tmp_path, preflight):
    """LAS bytes named .tif: content wins, extension disagreement is an error
    for the extension-claimed adapter (geo TIFF would fail inspection anyway),
    but the file is importable under the sniffed format."""
    masquerade = fx.write_valid_las(tmp_path / "surprise.tif")
    report = preflight.inspect(masquerade)
    assert report.adapter_id == "las"
    assert any(i.code == "extension-mismatch" for i in report.issues)
    assert report.ok


def test_preflight_failure_creates_no_catalog_asset(tmp_path, preflight, catalog):
    """The key fail-closed invariant."""
    before = len(catalog.list_assets())
    mystery = tmp_path / "mystery.dat"
    mystery.write_bytes(b"\x01\x02\x03")
    with pytest.raises(PreflightFailedError):
        preflight.plan(mystery)
    assert len(catalog.list_assets()) == before


def test_plan_is_serializable(tmp_path, preflight):
    import json

    las = fx.write_valid_las(tmp_path / "w.las")
    plan = preflight.plan(las, asset_name="W-1")
    payload = json.dumps(plan.to_dict(), ensure_ascii=False)
    assert "managed_copy" in payload


def test_executor_registers_managed_version(tmp_path, preflight, catalog):
    las = fx.write_valid_las(tmp_path / "w.las")
    plan = preflight.plan(las, asset_name="W-001")
    executor = ImportExecutor(catalog, work_dir=tmp_path / "work")
    result = executor.execute(plan)
    version = catalog.get_version(result.version_id)
    assert version.managed is True
    assert version.sha256  # managed copies are hashed
    resolved = catalog.resolve_path(version)
    assert resolved.is_file()
    asset = catalog.get_asset(result.asset_id)
    assert asset.name == "W-001"
    assert asset.metadata.get("well_name") == "W-001"


def test_executor_link_external_recommendation(tmp_path, preflight, catalog):
    """Oversized SEG-Y is linked, not copied (100GB stays out of scope)."""
    from paleo_workbench.interchange.adapters.segy_adapter import MANAGED_COPY_MAX_BYTES
    from paleo_workbench.interchange.contracts import InspectionResult

    segy_path = tmp_path / "big.segy"
    segy_path.write_bytes(b"\x00" * 4096)
    adapter = preflight.registry().get("segy")
    inspection = InspectionResult(format_id="segy", ok=True, size_bytes=MANAGED_COPY_MAX_BYTES + 1)
    plan = adapter.plan_import(segy_path, inspection)
    assert plan.action == "link_external"
    assert any("转码管线" in w for w in plan.warnings)


def test_cancel_before_execute_registers_nothing(tmp_path, preflight, catalog):
    las = fx.write_valid_las(tmp_path / "w.las")
    plan = preflight.plan(las)
    token = CancelToken()
    token.cancel("user asked")
    executor = ImportExecutor(catalog, work_dir=tmp_path / "work")
    with pytest.raises(CancelledError):
        executor.execute(plan, cancel=token)
    assert catalog.list_assets() == []


def test_cancel_during_import_yields_complete_state(tmp_path, preflight, catalog):
    """Cancel firing between executor start and the catalog copy leaves no
    partial state: the checkpoint before the irreversible step raises and the
    catalog stays empty. Once the copy completes there is no later checkpoint
    that could lie about a half-registered version.
    """
    las = fx.write_valid_las(tmp_path / "w.las")
    plan = preflight.plan(las)
    token = CancelToken()
    executor = ImportExecutor(catalog, work_dir=tmp_path / "work")

    adapter = executor.registry().get("las")
    real_import = adapter.import_data

    def import_cancel_midway(path, plan, **kwargs):
        kwargs["cancel"].cancel("before copy")
        return real_import(path, plan, **kwargs)

    adapter.import_data = import_cancel_midway
    with pytest.raises(CancelledError):
        executor.execute(plan, cancel=token)
    assert catalog.list_assets() == []
