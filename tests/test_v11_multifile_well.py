"""V11 multi-file well lifecycle (goal §18): one well, full data matrix.

Scenario: Well-A with 3 LAS files, trajectory, tops, time_depth, then a
derived prediction over the logs; verify view assembly, staleness after the
primary log evolves, working-copy edit producing a new version, and the
explain answers across the whole chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.edit_session import open_edit_session
from paleo_workbench.catalog.entity_views import EntityViewService
from paleo_workbench.catalog.explain import ExplainService
from paleo_workbench.catalog.impact import ImpactService
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import WellEntity, upsert_entity_asset_link
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.ingest_plan import build_ingest_plan, execute_ingest_plan


@pytest.fixture()
def env(tmp_path: Path):
    project_file = tmp_path / "site.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("site")
    well = WellEntity(name="Well-A", uwi="UWI-A")
    doc.wells.append(well)

    data = tmp_path / "Well-A"
    data.mkdir()
    (data / "Well-A.las").write_text("~W\nWELL: Well-A\n~C\nDT\n", encoding="utf-8")
    (data / "Well-A_dens.las").write_text("~W\nWELL: Well-A\n~C\nRHOB\n", encoding="utf-8")
    (data / "legacy_1998.las").write_text("~W\nWELL: Well-A\n~C\nOLD\n", encoding="utf-8")
    (data / "deviation.xlsx").write_bytes(b"dev")
    (data / "tops.csv").write_text("fm,md\nFm1,10\n", encoding="utf-8")
    (data / "checkshot.dat").write_text("t,d\n1,2\n", encoding="utf-8")
    yield service, doc, well, data, tmp_path
    service.close()


def _import_and_bind(env):
    service, doc, well, data, tmp_path = env
    plan = build_ingest_plan(data, doc, service=service)
    for item in plan.items:
        item.decision = "accept"
    report = execute_ingest_plan(plan, service, doc)
    assert len(report.imported_version_ids) == 6
    assert report.issues == []
    return report


def test_full_well_matrix_lifecycle(env):
    service, doc, well, data, tmp_path = env
    _import_and_bind(env)

    # ---- view: the well is a role matrix, not a file list ----------------
    views = EntityViewService(service, doc)
    view = views.well_view(well.id)
    slots = view.slots
    assert len(slots["well_log"].members) == 3
    assert len(slots["trajectory"].members) == 1
    assert len(slots["tops"].members) == 1
    assert len(slots["time_depth"].members) == 1
    assert sum(1 for m in slots["well_log"].members if m.is_primary) == 1

    # ---- derived prediction over the primary log -------------------------
    primary = slots["well_log"].primary
    primary_version = service.get_version(primary.current_version_id)
    run = service.register_run(
        "prediction",
        input_version_ids=[primary_version.id],
        input_ports=[{
            "role": "well_logs", "version_id": primary_version.id,
            "entity_type": "well", "entity_id": well.id,
        }],
    )
    result_src = tmp_path / "pred.json"
    result_src.write_text('{"pred": 1}', encoding="utf-8")
    result = service.register_result_asset(
        name="Well-A facies", type="prediction", format="json",
        asset_metadata=None, source_path=result_src, stage="derived",
        run_id=run.id,
    )

    # ---- staleness: evolve the primary log --------------------------------
    evolved = tmp_path / "Well-A_v2.las"
    evolved.write_text("~W\nWELL: Well-A\n~C\nDT corrected\n", encoding="utf-8")
    service.register_version(primary.asset_id, evolved, "raw")

    impact = ImpactService(service)
    stale = {i.version_id: i for i in impact.downstream_stale()}
    assert result.id in stale
    assert stale[result.id].direct is True
    scoped = impact.entity_staleness(doc, "well", well.id)
    assert {i.version_id for i in scoped} == {result.id}

    # ---- explain: the result answers the full question set ----------------
    explanation = ExplainService(service).explain_version(
        result.id, project=doc
    )
    assert explanation.typed_lineage is True
    assert explanation.input_ports[0]["role"] == "well_logs"
    assert explanation.entities == [{"entity_type": "well", "entity_id": well.id}]
    assert explanation.deletable is False
    assert explanation.stale is True

    # ---- edit session: revise the tops via working copy -------------------
    session = open_edit_session(service, doc, "well", well.id, "tops")
    tops_path = session.primary_path()
    tops_path.write_text("fm,md\nFm1,11\nFm2,22\n", encoding="utf-8")
    commit_report = session.commit(new_name="tops reviewed")
    assert len(commit_report.committed_version_ids) == 1
    new_tops = service.get_version(commit_report.committed_version_ids[0])
    assert new_tops.version_number == 2
    assert service.working_copy_state(tops_path) is None  # row cleaned

    # ---- view reflects the new current version ----------------------------
    view2 = views.well_view(well.id)
    assert (
        view2.slots["tops"].primary.current_version_id == new_tops.id
    )


def test_reimport_same_directory_is_stable(env):
    """Idempotency: re-running the same directory ingest binds nothing new."""
    service, doc, well, data, tmp_path = env
    _import_and_bind(env)
    wells_before = len(doc.wells)
    links_before = len(doc.entity_asset_links)

    plan = build_ingest_plan(data, doc, service=service)
    report = execute_ingest_plan(plan, service, doc)
    assert report.imported_version_ids == []
    assert all(i.decision == "skip" for i in plan.items)
    assert len(doc.wells) == wells_before
    assert len(doc.entity_asset_links) == links_before
