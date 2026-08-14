"""Full-chain lineage tests: get_lineage_chain / lineage_summaries (Core).

Covers the OUTPUT → Run → DERIVED → Run → INTERMEDIATE → Run → RAW walk the
Data Manager 血缘 tree renders, plus descendants, cycle safety, depth caps,
and the revision-cached summary map backing the table's 血缘 column.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import DataCatalogService, DataStage


def _project_file(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_project_file(tmp_path))
    yield svc
    svc.close()


def _chain(tmp_path: Path, svc: DataCatalogService):
    """RAW → factor_map INTERMEDIATE → prediction DERIVED → paleomap OUTPUT."""
    (tmp_path / "raw.sgy").write_bytes(b"seismic")
    (tmp_path / "g.npz").write_bytes(b"grid")
    (tmp_path / "p.json").write_bytes(b"pred")
    (tmp_path / "m.json").write_bytes(b"map")
    raw = svc.import_raw(tmp_path / "raw.sgy", name="seismic.sgy", type="seismic")
    inter = svc.create_derived(
        tmp_path / "g.npz",
        parent_version_ids=[raw.id],
        name="factor_grid",
        operation="factor_map",
        type="factor_map",
    )
    pred = svc.create_derived(
        tmp_path / "p.json",
        parent_version_ids=[inter.id],
        name="prediction",
        operation="prediction",
        type="prediction",
    )
    out = svc.create_derived(
        tmp_path / "m.json",
        parent_version_ids=[pred.id],
        name="paleomap",
        operation="map_compile",
        type="paleomap",
    )
    return raw, inter, pred, out


def test_ancestor_chain_walks_output_to_raw(service, tmp_path):
    raw, inter, pred, out = _chain(tmp_path, service)
    chain = service.get_lineage_chain(out.id)
    assert chain.direction == "ancestors"
    assert chain.root.version_id == out.id
    # Each hop is one parent, with the producing run interleaved on the node.
    hops = [chain.root, *chain.root.children]
    assert [n.asset_name for n in hops] == ["paleomap", "prediction"]
    assert hops[0].run_operation == "map_compile"
    assert hops[1].run_operation == "prediction"
    grand = chain.root.children[0].children
    assert [n.asset_name for n in grand] == ["factor_grid"]
    leaves = grand[0].children
    assert [n.asset_name for n in leaves] == ["seismic.sgy"]
    assert leaves[0].stage == DataStage.RAW
    assert leaves[0].run_operation is None  # imports have no producing run
    assert not chain.truncated


def _import_raw(service, path: Path, name: str):
    return service.import_raw(path, name=name, type=name)


def test_ancestor_chain_multi_input_fan_in(service, tmp_path):
    (tmp_path / "a.sgy").write_bytes(b"a")
    (tmp_path / "b.las").write_bytes(b"b")
    (tmp_path / "o.json").write_bytes(b"o")
    a = _import_raw(service, tmp_path / "a.sgy", "seismic")
    b = _import_raw(service, tmp_path / "b.las", "well")
    out = service.create_derived(
        tmp_path / "o.json",
        parent_version_ids=[a.id, b.id],
        name="merged",
        operation="merge",
    )
    chain = service.get_lineage_chain(out.id)
    parent_names = sorted(n.asset_name for n in chain.root.children)
    assert parent_names == ["seismic", "well"]


def test_descendant_chain_from_raw(service, tmp_path):
    raw, inter, pred, out = _chain(tmp_path, service)
    chain = service.get_lineage_chain(raw.id, direction="descendants")
    names = set()

    def collect(node):
        names.add(node.asset_name)
        for child in node.children:
            collect(child)

    collect(chain.root)
    assert {"factor_grid", "prediction", "paleomap"} <= names


def test_chain_rejects_unknown_direction(service, tmp_path):
    raw, _inter, _pred, _out = _chain(tmp_path, service)
    with pytest.raises(ValueError):
        service.get_lineage_chain(raw.id, direction="sideways")


def test_max_depth_truncates_and_flags(service, tmp_path):
    raw, inter, pred, out = _chain(tmp_path, service)
    chain = service.get_lineage_chain(out.id, max_depth=1)
    assert chain.truncated
    assert chain.root.children[0].asset_name == "prediction"
    assert chain.root.children[0].children == []


def test_cycle_walk_terminates(service, tmp_path):
    raw, inter, pred, out = _chain(tmp_path, service)
    (tmp_path / "x.json").write_bytes(b"x")
    extra = service.create_derived(
        tmp_path / "x.json",
        parent_version_ids=[out.id],
        name="extra",
        operation="x",
    )
    # Force a cycle out → ... → extra → out (write-time prevention only covers
    # self-loops; the walk must survive a corrupted document all the same).
    service._append_parent(out.id, extra.id)
    chain = service.get_lineage_chain(out.id)
    assert chain.node_count >= 5  # every version visited exactly once


def test_lineage_summaries_report_hops_to_raw(service, tmp_path):
    raw, inter, pred, out = _chain(tmp_path, service)
    summaries = service.lineage_summaries()
    assert summaries[raw.id] == {"to_raw": 0, "broken": False, "has_parents": False}
    assert summaries[inter.id]["to_raw"] == 1
    assert summaries[pred.id]["to_raw"] == 2
    assert summaries[out.id]["to_raw"] == 3


def test_lineage_summaries_flag_broken_parents(service, tmp_path):
    raw, _inter, _pred, out = _chain(tmp_path, service)
    out.parent_version_ids.append("ver-does-not-exist")
    service._save()
    summaries = service.lineage_summaries()
    assert summaries[out.id]["broken"] is True


def test_lineage_summaries_cached_per_revision(service, tmp_path):
    raw, inter, _pred, _out = _chain(tmp_path, service)
    first = service.lineage_summaries()
    second = service.lineage_summaries()
    assert first is second  # cached until the document revision advances
    (tmp_path / "n.json").write_bytes(b"n")
    service.create_derived(
        tmp_path / "n.json", parent_version_ids=[inter.id], name="new", operation="n"
    )
    third = service.lineage_summaries()
    assert third is not first


def test_unprovenanced_derived_reports_no_raw_reachable(service, tmp_path):
    (tmp_path / "lone.json").write_bytes(b"l")
    lone = service.create_derived(
        tmp_path / "lone.json",
        parent_version_ids=[],
        name="lone",
        operation="orphan_op",
    )
    summaries = service.lineage_summaries()
    assert summaries[lone.id]["to_raw"] is None
    assert summaries[lone.id]["has_parents"] is False
