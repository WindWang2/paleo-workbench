"""V11 ingest planning: scan/classify/family/identity/duplicate → plan → execute."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import WellEntity, links_for_entity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.ingest_plan import (
    build_ingest_plan,
    execute_ingest_plan,
)


@pytest.fixture()
def env(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("demo")
    yield service, doc, tmp_path
    service.close()


def _make_well_dir(tmp_path: Path) -> Path:
    root = tmp_path / "import_root"
    well_a = root / "Well-A"
    well_a.mkdir(parents=True)
    (well_a / "A.las").write_text("~W\nWELL: Well-A\n~C\nDT 1 1\n", encoding="utf-8")
    (well_a / "A2.las").write_text("~W\nWELL: Well-A\n~C\nRHOB 1 1\n", encoding="utf-8")
    (well_a / "deviation.xlsx").write_bytes(b"xlsx-bytes")
    (well_a / "tops.csv").write_text("fm,md\nF1,100\n", encoding="utf-8")
    (well_a / "checkshot.dat").write_text("td pairs\n", encoding="utf-8")
    return root


def test_plan_classifies_roles_and_families(env):
    service, doc, tmp_path = env
    doc.wells.append(WellEntity(name="Well-A"))
    root = _make_well_dir(tmp_path)
    plan = build_ingest_plan(root, doc, service=service)
    by_suffix = {item.path.suffix.lower(): item for item in plan.items}
    assert by_suffix[".las"].type == "well_log"
    assert by_suffix[".las"].role == "well_log"
    assert by_suffix[".xlsx"].role == "trajectory"
    assert by_suffix[".csv"].role == "tops"
    assert by_suffix[".dat"].role == "time_depth"
    # identity matched the pre-registered well by directory hint or stem
    las_identity = by_suffix[".las"].identity
    assert las_identity.entity_type == "well"
    # first member of each (entity, role) proposed primary; the second LAS is not
    las_items = sorted(
        (i for i in plan.items if i.path.suffix.lower() == ".las"),
        key=lambda i: i.path.name,
    )
    assert sum(1 for i in las_items if i.primary) == 1


def test_plan_shapefile_family(env):
    service, doc, tmp_path = env
    fam = tmp_path / "import_root" / "map"
    fam.mkdir(parents=True)
    for ext, required in ((".shp", True), (".shx", True), (".dbf", True), (".prj", False)):
        (fam / f"layer{ext}").write_bytes(f"content{ext}".encode())
    plan = build_ingest_plan(fam, doc, service=service)
    with_bundle = [i for i in plan.items if i.bundle is not None]
    assert len(with_bundle) == 4
    assert all(i.bundle.kind == "shapefile_family" for i in with_bundle)
    primary = [i for i in with_bundle if i.bundle.primary_path == i.path]
    assert len(primary) == 1 and primary[0].path.suffix == ".shp"


def test_plan_duplicate_detection(env):
    service, doc, tmp_path = env
    src = tmp_path / "import_root"
    src.mkdir(parents=True)
    (src / "A.las").write_text("~W\nWELL: W1\n~C\nDT 1 1\n", encoding="utf-8")
    service.import_raw(src / "A.las", name="A.las", type="well_log")
    plan = build_ingest_plan(src, doc, service=service)
    item = plan.items[0]
    assert item.duplicate_of_version is not None
    assert item.decision == "skip"


def test_execute_imports_binds_and_is_idempotent(env):
    service, doc, tmp_path = env
    doc.wells.append(WellEntity(name="Well-A"))
    root = _make_well_dir(tmp_path)
    plan = build_ingest_plan(root, doc, service=service)
    for item in plan.items:
        item.decision = "accept"
    report = execute_ingest_plan(plan, service, doc)
    assert len(report.imported_version_ids) == 5
    assert report.issues == []
    well = doc.wells[0]
    links = links_for_entity(doc, "well", well.id)
    roles = {link.role for link in links}
    assert "well_log" in roles
    log_links = [l for l in links if l.role == "well_log"]
    assert len(log_links) == 2  # 一井多 LAS：两个成员都绑定
    assert sum(1 for l in log_links if l.is_primary) == 1

    # idempotent re-run: everything now duplicates → skipped, nothing new
    plan2 = build_ingest_plan(root, doc, service=service)
    report2 = execute_ingest_plan(plan2, service, doc)
    assert report2.imported_version_ids == []
    assert len(report2.skipped) == 5


def test_execute_unmatched_identity_creates_no_silent_binding(env):
    service, doc, tmp_path = env
    doc.wells.append(WellEntity(name="Completely-Different"))
    root = _make_well_dir(tmp_path)
    plan = build_ingest_plan(root, doc, service=service)
    for item in plan.items:
        item.decision = "accept"
    report = execute_ingest_plan(plan, service, doc)
    well = doc.wells[0]
    links = links_for_entity(doc, "well", well.id)
    # nothing silently binds to the unrelated well
    assert links == []
    # and a new well entity is created for the imported data
    assert len(doc.wells) == 2


def test_execute_cancel_stops_early(env):
    service, doc, tmp_path = env
    doc.wells.append(WellEntity(name="Well-A"))
    root = _make_well_dir(tmp_path)
    plan = build_ingest_plan(root, doc, service=service)
    for item in plan.items:
        item.decision = "accept"
    report = execute_ingest_plan(plan, service, doc, cancel=lambda: True)
    assert report.cancelled is True
    assert report.imported_version_ids == []
