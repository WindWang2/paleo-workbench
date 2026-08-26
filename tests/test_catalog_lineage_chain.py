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


def test_e2e_geological_pipeline_lineage_chain_traversal(service, tmp_path):
    """Full E2E geological workflow lineage tracking:
    RAW Well data -> Factor Extraction & Kriging/IDW Interpolation (INTERMEDIATE)
    -> Facies Polygons & Contours -> Compiled MapDocument (OUTPUT).
    """
    import json
    from paleo_workbench.catalog.grid_artifact import write_grid_artifact
    from paleo_workbench.mapping.geological_pipeline.models import (
        GeologicalFactorDataset,
        InterpolationOptions,
    )
    from paleo_workbench.mapping.geological_pipeline.pipeline import GeologicalMappingPipeline

    # Step 1: RAW well logs/picks dataset
    raw_well_file = tmp_path / "wells_data.json"
    raw_well_file.write_text(
        json.dumps([
            {"well_id": "W1", "x": 100.0, "y": 200.0, "porosity": 15.2, "target_horizon": "T1"},
            {"well_id": "W2", "x": 150.0, "y": 220.0, "porosity": 18.5, "target_horizon": "T1"},
            {"well_id": "W3", "x": 200.0, "y": 180.0, "porosity": 12.0, "target_horizon": "T1"},
            {"well_id": "W4", "x": 120.0, "y": 160.0, "porosity": 22.1, "target_horizon": "T1"},
        ]),
        encoding="utf-8",
    )
    raw_well_ver = service.import_raw(
        raw_well_file,
        name="well_porosity_t1.json",
        type="well_table",
    )
    assert raw_well_ver.stage == DataStage.RAW

    # Step 2: Geological Pipeline extraction + interpolation
    pipeline = GeologicalMappingPipeline()
    records = json.loads(raw_well_file.read_text(encoding="utf-8"))
    dataset = pipeline.extract_factors(records, "porosity", target_horizon="T1")
    assert len(dataset.valid_points) == 4

    opts = InterpolationOptions(
        method="idw",
        grid_n=20,
        crs="EPSG:4326",
    )
    grid_result = pipeline.interpolate(dataset, opts)
    # Check property aliases on FactorGridResult
    grid_result.input_version_ids = [raw_well_ver.id]
    assert grid_result.source_refs == [raw_well_ver.id]
    assert grid_result.input_version_ids == [raw_well_ver.id]

    interp_run = service.register_run(
        operation="factor_interpolation",
        input_version_ids=[raw_well_ver.id],
        output_version_ids=[],
        parameters={"algorithm_id": grid_result.algorithm_id, "factor": "porosity"},
        generator="GeologicalMappingPipeline",
    )
    grid_result.run_id = interp_run.id
    assert grid_result.run_ref == interp_run.id
    assert grid_result.run_id == interp_run.id

    desc = grid_result.to_descriptor()
    assert desc["input_version_ids"] == [raw_well_ver.id]
    assert desc["run_id"] == interp_run.id

    # Persist intermediate grid artifact
    grid_artifact_path = write_grid_artifact(grid_result, tmp_path, "porosity_t1")

    grid_version = service.register_result_asset(
        name="porosity_grid_t1",
        type="factor_grid",
        format="npz",
        asset_metadata={"factor_name": "porosity", "target_horizon": "T1"},
        source_path=grid_artifact_path,
        stage=DataStage.INTERMEDIATE,
        run_id=interp_run.id,
        version_metadata={"descriptor": desc},
    )
    assert grid_version.stage == DataStage.INTERMEDIATE
    assert grid_version.parent_version_ids == [raw_well_ver.id]

    # Step 3 & 4: Build MapDocument with Contours, Polygons, and Wells
    map_compile_run = service.register_run(
        operation="map_compile",
        input_version_ids=[grid_version.id],
        output_version_ids=[],
        parameters={"title": "T1 Porosity Distribution", "include_contours": True},
        generator="GeologicalMappingPipeline",
    )

    map_doc = pipeline.build_factor_map_document(
        dataset,
        opts,
        include_grid=True,
        include_contours=True,
        include_wells=True,
        include_polygons=True,
        run_id=map_compile_run.id,
        input_version_ids=[grid_version.id],
    )
    assert map_doc.run_id == map_compile_run.id
    assert grid_version.id in map_doc.input_version_ids

    # Persist MapDocument as OUTPUT asset
    map_file = tmp_path / "porosity_map_t1.map.json"
    map_file.write_text(json.dumps(map_doc.to_dict()), encoding="utf-8")

    map_version = service.register_result_asset(
        name="porosity_map_t1",
        type="map_document",
        format="json",
        asset_metadata={"title": map_doc.title},
        source_path=map_file,
        stage=DataStage.OUTPUT,
        run_id=map_compile_run.id,
        version_metadata={"layers_count": len(map_doc.layers)},
    )
    assert map_version.stage == DataStage.OUTPUT
    assert map_version.parent_version_ids == [grid_version.id]

    # Step 5: Ancestor lineage traversal
    ancestors_chain = service.get_lineage_chain(map_version.id, direction="ancestors")
    assert ancestors_chain.direction == "ancestors"
    assert not ancestors_chain.truncated
    assert ancestors_chain.root.version_id == map_version.id
    assert ancestors_chain.root.run_operation == "map_compile"

    # 1st hop: Intermediate factor grid
    assert len(ancestors_chain.root.children) == 1
    grid_node = ancestors_chain.root.children[0]
    assert grid_node.version_id == grid_version.id
    assert grid_node.stage == DataStage.INTERMEDIATE
    assert grid_node.run_operation == "factor_interpolation"

    # 2nd hop: RAW Well data
    assert len(grid_node.children) == 1
    raw_node = grid_node.children[0]
    assert raw_node.version_id == raw_well_ver.id
    assert raw_node.stage == DataStage.RAW
    assert raw_node.run_operation is None  # RAW import has no producing run
    assert raw_node.children == []

    # Step 6: Descendant lineage traversal from RAW Well
    desc_chain = service.get_lineage_chain(raw_well_ver.id, direction="descendants")
    assert desc_chain.direction == "descendants"
    assert desc_chain.root.version_id == raw_well_ver.id
    assert len(desc_chain.root.children) == 1
    assert desc_chain.root.children[0].version_id == grid_version.id
    assert desc_chain.root.children[0].children[0].version_id == map_version.id

    # Step 7: Lineage summary status
    summaries = service.lineage_summaries()
    assert summaries[raw_well_ver.id] == {"to_raw": 0, "broken": False, "has_parents": False}
    assert summaries[grid_version.id] == {"to_raw": 1, "broken": False, "has_parents": True}
    assert summaries[map_version.id] == {"to_raw": 2, "broken": False, "has_parents": True}
