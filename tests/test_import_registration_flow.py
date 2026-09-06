"""Bulk import registration flow (D4) — chunked cancel consistency + receipt.

Pins:

* registration commits in chunks; a cooperative cancel between chunks
  leaves the catalog holding EXACTLY the registered assets — consistent
  after reopen, never half-registered;
* the progress callback tracks (done, total) per chunk;
* the import receipt text reports discovered/skipped/registered/failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.import_service import ImportReport
from paleo_workbench.ui.data_lifecycle_controller import DataLifecycleController


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(svc))
    yield svc
    reset_catalog()
    svc.close()


def _resources(tmp_path: Path, count: int) -> list[ResourceItem]:
    out = []
    for i in range(count):
        src = tmp_path / f"well_{i:03d}.las"
        src.write_text(f"curve-{i}", encoding="utf-8")
        item = ResourceItem(
            name=src.name,
            path=str(src),
            type="well_log",
            format="las",
        )
        out.append(item)
    return out


def test_chunked_registration_cancel_keeps_catalog_consistent(
    service, tmp_path, monkeypatch
):
    from paleo_workbench.catalog.lifecycle import register_resource_input

    monkeypatch.setattr(DataLifecycleController, "REGISTRATION_CHUNK", 10)
    controller = DataLifecycleController(page=None)
    resources = _resources(tmp_path, 50)
    seen: list[tuple[int, int]] = []
    checks = {"n": 0}

    def cancel_check() -> bool:
        # Cancel after ~2.5 chunks have been processed.
        checks["n"] += 1
        return checks["n"] > 25

    mapping = controller.register_imported_resources(
        resources,
        progress=lambda done, total: seen.append((done, total)),
        cancel_check=cancel_check,
    )
    assert 0 < len(mapping) < 50
    assert seen, "progress must be reported per completed chunk"
    assert seen[-1][0] == len(mapping)
    assert controller.last_registration_failures == []
    # The catalog holds EXACTLY the registered assets (no half-registered).
    assert len(service.list_assets()) == len(mapping)

    project_path = service.project_path
    service.close()
    reopened = DataCatalogService.open(project_path)
    try:
        assert len(reopened.list_assets()) == len(mapping)
    finally:
        reopened.close()
        # keep the fixture teardown happy
        service._flushed_revision = reopened._flushed_revision


def test_full_registration_reports_progress_and_registers_all(service, tmp_path, monkeypatch):
    monkeypatch.setattr(DataLifecycleController, "REGISTRATION_CHUNK", 7)
    controller = DataLifecycleController(page=None)
    resources = _resources(tmp_path, 20)
    seen: list[tuple[int, int]] = []
    mapping = controller.register_imported_resources(
        resources, progress=lambda done, total: seen.append((done, total))
    )
    assert len(mapping) == 20
    assert seen[-1] == (20, 20)
    assert len(service.list_assets()) == 20


def test_import_receipt_text(tmp_path, qtbot):
    """The receipt lists discovery, skips, registrations and failures."""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.pages.data_page import DataPage

    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    page._last_import_report = ImportReport(
        added=[],
        skipped_path=[Path("/dup/a.las"), Path("/dup/b.las")],
        warnings=["空文件已忽略"],
    )
    page._last_registered_asset_ids = {"r1": "asset-1", "r2": "asset-2"}
    receipt = page._build_import_receipt(
        page._last_import_report, failures=["bad.las: boom"], cancelled=False
    )
    assert "跳过 (重复路径): 2" in receipt
    assert "目录登记成功: 2" in receipt
    assert "目录登记失败: 1" in receipt
    assert "bad.las: boom" in receipt

    cancelled = page._build_import_receipt(
        page._last_import_report, failures=[], cancelled=True
    )
    assert "已取消" in cancelled
