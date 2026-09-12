"""V11 read-side services: entity views, impact/staleness, explain, edit session."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.edit_session import open_edit_session
from paleo_workbench.catalog.entity_views import EntityViewService
from paleo_workbench.catalog.explain import ExplainService
from paleo_workbench.catalog.impact import ImpactService
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import (
    WellEntity,
    upsert_entity_asset_link,
)
from paleo_workbench.project.models import ProjectDocument


@pytest.fixture()
def env(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("demo")
    well = WellEntity(name="Well-A", uwi="UWI-001")
    doc.wells.append(well)
    yield service, doc, well, tmp_path
    service.close()


def _import_well_log(service, tmp_path, name, content):
    src = tmp_path / name
    src.write_text(content, encoding="utf-8")
    return service.import_raw(src, name=name, type="well_log")


def _mkderived(service, tmp_path, parent_ids, name, op="demo_op"):
    run = service.register_run(op, input_version_ids=list(parent_ids))
    src = tmp_path / f"{name}.out"
    src.write_text(f"derived-{name}", encoding="utf-8")
    version = service.register_result_asset(
        name=name, type="derived", format="txt", asset_metadata=None,
        source_path=src, stage="derived", run_id=run.id,
    )
    return version, run


# ---------------------------------------------------------------------------
# entity views
# ---------------------------------------------------------------------------


def test_well_view_groups_roles_and_primary(env):
    service, doc, well, tmp_path = env
    v1 = _import_well_log(service, tmp_path, "a.las", "las-a")
    v2 = _import_well_log(service, tmp_path, "b.las", "las-b")
    top_src = tmp_path / "tops.csv"
    top_src.write_text("fm,md\nF1,100\n", encoding="utf-8")
    tops = service.import_raw(top_src, name="tops.csv", type="well_stratification")
    for vid in (v1.id, v2.id, tops.id):
        asset = service.get_asset(service.get_version(vid).asset_id)
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id=well.id, asset_id=asset.id,
            role="well_log" if vid != tops.id else "tops",
            is_primary=(vid == v1.id),
        )
    views = EntityViewService(service, doc)
    view = views.well_view(well.id)
    assert view is not None
    log_slot = view.slots["well_log"]
    assert len(log_slot.members) == 2
    assert log_slot.primary.asset_id == service.get_version(v1.id).asset_id
    assert log_slot.members[0].is_primary
    assert view.slots["tops"].members[0].current_version_id == tops.id
    # empty roles still present (missing-source visibility)
    assert "trajectory" in view.slots
    assert view.slots["trajectory"].members == []


def test_well_index_counts_and_stale(env):
    service, doc, well, tmp_path = env
    v1 = _import_well_log(service, tmp_path, "a.las", "las-a")
    asset = service.get_asset(service.get_version(v1.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset.id,
        role="well_log", is_primary=True,
    )
    # evolve: import v2 of the same asset
    src2 = tmp_path / "a2.las"
    src2.write_text("las-a-evolved", encoding="utf-8")
    service.register_version(asset.id, src2, "raw")
    views = EntityViewService(service, doc)
    index = views.well_index(with_stale=False)
    assert index[0].role_fill.get("well_log") == 1
    index2 = views.well_index(with_stale=True)
    assert index2[0].stale_count == 0  # no downstream yet → nothing stale


# ---------------------------------------------------------------------------
# impact / staleness
# ---------------------------------------------------------------------------


def test_downstream_stale_direct_transitive_and_pinned(env):
    service, doc, well, tmp_path = env
    a1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    c, run_c = _mkderived(service, tmp_path, [a1.id], "C")
    d, run_d = _mkderived(service, tmp_path, [c.id], "D")
    impact = ImpactService(service)

    # nothing changed yet → nothing stale
    assert impact.downstream_stale() == []

    # evolve A: v2
    asset_a = service.get_asset(service.get_version(a1.id).asset_id)
    src2 = tmp_path / "a2.las"
    src2.write_text("content-2", encoding="utf-8")
    service.register_version(asset_a.id, src2, "raw")

    stale = impact.downstream_stale()
    ids = {item.version_id for item in stale}
    assert ids == {c.id, d.id}
    by_id = {item.version_id: item for item in stale}
    assert by_id[c.id].direct is True
    assert by_id[d.id].direct is False
    assert by_id[c.id].nearest_changed_ancestor[1] == a1.id
    assert by_id[c.id].reproducible is True
    assert by_id[c.id].classification == "stale"

    # pin D → classified pinned, still reported
    service.pin_version(d.id, reason="freeze")
    stale2 = impact.downstream_stale()
    by_id2 = {item.version_id: item for item in stale2}
    assert by_id2[d.id].classification == "pinned"
    assert by_id2[c.id].classification == "stale"

    # hypothetical mode: fresh chain, no evolution, pass old ids explicitly
    x = _import_well_log(service, tmp_path, "x.las", "content-x")
    y, _ = _mkderived(service, tmp_path, [x.id], "Y")
    hyp = impact.downstream_stale(changed_version_ids=[x.id])
    assert {item.version_id for item in hyp} == {y.id}


def test_trashed_ancestor_makes_downstream_stale(env):
    service, doc, well, tmp_path = env
    a1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    c, _ = _mkderived(service, tmp_path, [a1.id], "C")
    service.trash_version(a1.id, reason="cleanup")
    impact = ImpactService(service)
    stale = {item.version_id: item for item in impact.downstream_stale()}
    assert c.id in stale
    assert "回收站" in stale[c.id].reason or "删除" in stale[c.id].reason


def test_upstream_and_delete_impact(env):
    service, doc, well, tmp_path = env
    a1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    b1 = _import_well_log(service, tmp_path, "b.las", "content-b")
    c, _ = _mkderived(service, tmp_path, [a1.id, b1.id], "C")
    d, _ = _mkderived(service, tmp_path, [c.id], "D")

    impact = ImpactService(service)
    up = impact.upstream_impact(d.id)
    assert set(up.ancestor_version_ids) == {a1.id, b1.id, c.id}
    assert len(up.runs_involved) == 2

    # link A to the well → delete impact reports the entity
    asset_a = service.get_asset(service.get_version(a1.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset_a.id,
        role="well_log", is_primary=True,
    )
    dele = impact.delete_impact(version_id=a1.id, project=doc)
    assert {item.version_id for item in dele.live_descendants} == {c.id, d.id}
    # run_c consumes a1; nothing produces it (RAW import has no run)
    assert (len(dele.runs_consuming), len(dele.runs_producing)) == (1, 0)
    assert ("well", well.id) in dele.linked_entities
    assert dele.cascade_advice  # actionable advice present


def test_entity_staleness_scopes_to_well(env):
    service, doc, well, tmp_path = env
    a1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    other = _import_well_log(service, tmp_path, "z.las", "content-z")
    c, _ = _mkderived(service, tmp_path, [a1.id], "C")
    d, _ = _mkderived(service, tmp_path, [other.id], "D")
    asset_a = service.get_asset(service.get_version(a1.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset_a.id,
        role="well_log", is_primary=True,
    )
    src2 = tmp_path / "a2.las"
    src2.write_text("content-2-evolved", encoding="utf-8")
    service.register_version(asset_a.id, src2, "raw")
    impact = ImpactService(service)
    scoped = impact.entity_staleness(doc, "well", well.id)
    assert {item.version_id for item in scoped} == {c.id}


# ---------------------------------------------------------------------------
# explain
# ---------------------------------------------------------------------------


def test_explain_version_answers_the_question_set(env):
    service, doc, well, tmp_path = env
    a1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    c, run = _mkderived(service, tmp_path, [a1.id], "C")
    asset_a = service.get_asset(service.get_version(a1.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset_a.id,
        role="well_log", is_primary=True,
    )
    # downstream of a1 = c
    e = ExplainService(service).explain_version(a1.id, project=doc)
    assert e.downstream_version_ids == [c.id]
    assert e.regenerable is False  # RAW import has no run
    assert e.deletable is False  # downstream blocks
    assert any("downstream" in b for b in e.delete_blockers)
    assert e.entities == [{"entity_type": "well", "entity_id": well.id}]

    ec = ExplainService(service).explain_version(c.id, project=doc)
    assert ec.producing_run_id == run.id
    assert ec.operation == "demo_op"
    assert ec.input_ports and ec.input_ports[0]["version_id"] == a1.id
    assert ec.typed_lineage is False  # anonymous until ports are set

    # typed ports upgrade the explanation
    from paleo_workbench.catalog.models import RunPort

    service.set_run_ports(
        run.id, input_ports=[RunPort(role="well_logs", version_id=a1.id)]
    )
    ec2 = ExplainService(service).explain_version(c.id, project=doc)
    assert ec2.typed_lineage is True
    assert ec2.input_ports[0]["role"] == "well_logs"


# ---------------------------------------------------------------------------
# edit session
# ---------------------------------------------------------------------------


def test_edit_session_commit_and_cancel(env):
    service, doc, well, tmp_path = env
    v1 = _import_well_log(service, tmp_path, "a.las", "content-1")
    asset = service.get_asset(service.get_version(v1.id).asset_id)
    upsert_entity_asset_link(
        doc, entity_type="well", entity_id=well.id, asset_id=asset.id,
        role="well_log", is_primary=True,
    )
    session = open_edit_session(service, doc, "well", well.id, "well_log")
    path = session.primary_path()
    path.write_text("content-1-edited", encoding="utf-8")
    report = session.commit(new_name="edited log")
    assert len(report.committed_version_ids) == 1
    new_version = service.get_version(report.committed_version_ids[0])
    assert new_version.parent_version_ids == [v1.id]
    assert service.get_version(v1.id).sha256  # original untouched
    assert not path.exists()

    # cancel path
    session2 = open_edit_session(service, doc, "well", well.id, "well_log")
    p2 = session2.primary_path()
    assert p2.is_file()
    cancel_report = session2.cancel()
    assert cancel_report.cancelled
    assert not p2.exists()


def test_edit_session_missing_role_raises(env):
    service, doc, well, tmp_path = env
    with pytest.raises(Exception):
        open_edit_session(service, doc, "well", well.id, "trajectory")
