"""Adversarial stress testing for Milestone 5 (F21 Lineage Graph & F22 Project Persistence).

Targeted stress dimensions:
1. Synthetic circular lineage graphs (self-loops, 2-cycles, 3-cycles, figure-8, interlocking cycles,
   mixed cycles with legitimate DAG branches).
2. Deep lineage DAGs (1500+ nodes linear chains, 1000+ node dense diamond lattices) verifying
   max_nodes/max_depth bounds, iterative DFS recursion-safety, and memoized performance.
3. Corrupted *.paleo.json files (truncated JSON, syntax corruption, schema/field validation failure)
   verifying disaster recovery from *.paleo.json.bak and concurrency guards (ProjectStaleWriteError).
4. Full geological pipeline provenance traversal (multi-well factors -> Kriging/IDW grids ->
   Marching Squares contours/polygons -> MapDocuments) with descriptor verification and spanning-tree semantics.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import pytest

from paleo_workbench.catalog import DataCatalogService, DataStage
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataVersion,
)
from paleo_workbench.catalog.lineage_graph import (
    DEFAULT_MAX_NODES,
    build_lineage_chain,
    compute_summaries,
)
from paleo_workbench.project.manager import (
    ProjectManager,
    ProjectStaleWriteError,
    project_backup_path,
)
from paleo_workbench.project.models import ProjectDocument


# ============================================================================
# Helpers & Fixtures
# ============================================================================

def _create_project_file(tmp_path: Path, name: str = "stress_proj") -> Path:
    proj_dir = tmp_path / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    proj_file = proj_dir / f"{name}.paleo.json"
    proj_file.write_text("{}", encoding="utf-8")
    return proj_file


@pytest.fixture
def catalog_service(tmp_path: Path):
    proj_file = _create_project_file(tmp_path)
    svc = DataCatalogService.open(proj_file)
    yield svc
    svc.close()


# ============================================================================
# 1. Synthetic Circular Lineage Graphs & Topology Stress
# ============================================================================

class TestCircularLineageStress:
    """Stress test cycle tolerance, termination bounds, and summary calculations."""

    def test_lineage_direct_self_loop(self, catalog_service, tmp_path: Path):
        """Self loop: A -> A. Both traversal directions and summaries must terminate in bounded time."""
        (tmp_path / "a.dat").write_bytes(b"a")
        raw = catalog_service.import_raw(tmp_path / "a.dat", name="a_raw", type="raw")
        (tmp_path / "b.dat").write_bytes(b"b")
        v = catalog_service.create_derived(
            tmp_path / "b.dat",
            parent_version_ids=[raw.id],
            name="v_loop",
            operation="op",
        )
        # Force self-loop
        catalog_service._append_parent(v.id, v.id)

        t0 = time.perf_counter()
        anc_chain = catalog_service.get_lineage_chain(v.id, direction="ancestors")
        desc_chain = catalog_service.get_lineage_chain(v.id, direction="descendants")
        summaries = catalog_service.lineage_summaries()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.2, f"Self-loop operations took too long: {elapsed}s"
        assert anc_chain.node_count >= 2
        assert desc_chain.node_count >= 1
        assert summaries[v.id]["to_raw"] == 1  # Reaches raw via raw parent
        assert summaries[raw.id]["to_raw"] == 0

    def test_lineage_2_cycle_and_3_cycle(self, catalog_service, tmp_path: Path):
        """2-cycle (A <-> B) and 3-cycle (A -> B -> C -> A) must terminate boundedly."""
        # Setup 3 nodes: A -> B -> C
        f_a = tmp_path / "node_a.dat"
        f_b = tmp_path / "node_b.dat"
        f_c = tmp_path / "node_c.dat"
        f_a.write_bytes(b"a")
        f_b.write_bytes(b"b")
        f_c.write_bytes(b"c")

        ver_a = catalog_service.create_derived(f_a, parent_version_ids=[], name="node_a", operation="op_a")
        ver_b = catalog_service.create_derived(f_b, parent_version_ids=[ver_a.id], name="node_b", operation="op_b")
        ver_c = catalog_service.create_derived(f_c, parent_version_ids=[ver_b.id], name="node_c", operation="op_c")

        # Close the 3-cycle: A -> parent is C (so A -> C -> B -> A)
        catalog_service._append_parent(ver_a.id, ver_c.id)

        t0 = time.perf_counter()
        anc_a = catalog_service.get_lineage_chain(ver_a.id, direction="ancestors")
        anc_b = catalog_service.get_lineage_chain(ver_b.id, direction="ancestors")
        anc_c = catalog_service.get_lineage_chain(ver_c.id, direction="ancestors")
        desc_a = catalog_service.get_lineage_chain(ver_a.id, direction="descendants")
        summaries = catalog_service.lineage_summaries()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.3
        assert anc_a.node_count == 3
        assert anc_b.node_count == 3
        assert anc_c.node_count == 3
        assert desc_a.node_count == 3
        # Since none of A, B, C are RAW, to_raw must be None
        assert summaries[ver_a.id]["to_raw"] is None
        assert summaries[ver_b.id]["to_raw"] is None
        assert summaries[ver_c.id]["to_raw"] is None

    def test_lineage_figure_eight_and_interlocking_cycles(self, catalog_service, tmp_path: Path):
        """Interlocking figure-8 cycles: (A <-> B) and (B <-> C <-> D)."""
        nodes = {}
        for name in ["A", "B", "C", "D", "E"]:
            p = tmp_path / f"fig8_{name}.dat"
            p.write_bytes(name.encode())
            nodes[name] = catalog_service.create_derived(p, parent_version_ids=[], name=name, operation=f"op_{name}")

        # Cycle 1: A -> B -> A
        catalog_service._append_parent(nodes["A"].id, nodes["B"].id)
        catalog_service._append_parent(nodes["B"].id, nodes["A"].id)
        # Cycle 2: B -> C -> D -> B
        catalog_service._append_parent(nodes["C"].id, nodes["B"].id)
        catalog_service._append_parent(nodes["D"].id, nodes["C"].id)
        catalog_service._append_parent(nodes["B"].id, nodes["D"].id)
        # Branch out to E: E -> D
        catalog_service._append_parent(nodes["E"].id, nodes["D"].id)

        t0 = time.perf_counter()
        chain = catalog_service.get_lineage_chain(nodes["E"].id, direction="ancestors")
        summaries = catalog_service.lineage_summaries()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.3
        assert chain.node_count == 5
        assert not chain.truncated
        assert summaries[nodes["E"].id]["to_raw"] is None

    def test_lineage_cycle_chain_walk_terminates_with_all_nodes(self, catalog_service, tmp_path: Path):
        """RAW -> A -> (Cycle B <-> C) -> D -> Output.
        get_lineage_chain walk must terminate and discover all 6 nodes without infinite loop.
        """
        f_raw = tmp_path / "field_raw.dat"
        f_raw.write_bytes(b"raw")
        raw = catalog_service.import_raw(f_raw, name="field_raw", type="raw_seismic")

        f_a = tmp_path / "m_a.dat"; f_a.write_bytes(b"a")
        f_b = tmp_path / "m_b.dat"; f_b.write_bytes(b"b")
        f_c = tmp_path / "m_c.dat"; f_c.write_bytes(b"c")
        f_d = tmp_path / "m_d.dat"; f_d.write_bytes(b"d")
        f_out = tmp_path / "m_out.dat"; f_out.write_bytes(b"out")

        ver_a = catalog_service.create_derived(f_a, parent_version_ids=[raw.id], name="a", operation="op_a")
        ver_b = catalog_service.create_derived(f_b, parent_version_ids=[ver_a.id], name="b", operation="op_b")
        ver_c = catalog_service.create_derived(f_c, parent_version_ids=[ver_b.id], name="c", operation="op_c")
        # Introduce cycle B -> C -> B
        catalog_service._append_parent(ver_b.id, ver_c.id)

        ver_d = catalog_service.create_derived(f_d, parent_version_ids=[ver_c.id], name="d", operation="op_d")
        ver_out = catalog_service.create_derived(f_out, parent_version_ids=[ver_d.id], name="out", operation="op_out")

        t0 = time.perf_counter()
        chain = catalog_service.get_lineage_chain(ver_out.id, direction="ancestors")
        summaries = catalog_service.lineage_summaries()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.3
        # Graph walk visits all 6 connected nodes
        assert chain.node_count == 6  # out, d, c, b, a, raw
        assert summaries[raw.id]["to_raw"] == 0
        assert summaries[ver_a.id]["to_raw"] == 1

    def test_lineage_summaries_with_dangling_broken_references_in_cycle(self, catalog_service, tmp_path: Path):
        """Lineage graph containing both cycles and dangling/missing version IDs."""
        f1 = tmp_path / "d1.dat"; f1.write_bytes(b"1")
        f2 = tmp_path / "d2.dat"; f2.write_bytes(b"2")
        v1 = catalog_service.create_derived(f1, parent_version_ids=[], name="v1", operation="op1")
        v2 = catalog_service.create_derived(f2, parent_version_ids=[v1.id], name="v2", operation="op2")

        # Add dangling parent to v1 and cycle v1 -> v2 -> v1
        catalog_service._append_parent(v1.id, "nonexistent-parent-9999")
        catalog_service._append_parent(v1.id, v2.id)

        summaries = catalog_service.lineage_summaries()
        assert summaries[v1.id]["broken"] is True
        assert summaries[v1.id]["to_raw"] is None


# ============================================================================
# 2. Deep Lineage DAGs (1000+ nodes) & Truncation Bounds
# ============================================================================

class TestDeepLineageDAGStress:
    """Stress test deep linear chains (1500+ nodes) and dense diamond DAGs in memory."""

    def test_deep_linear_chain_1500_nodes(self, catalog_service):
        """1500-level deep lineage chain. Tests recursion safety (no RecursionError) and bounds."""
        depth = 1500
        # Build synthetic in-memory catalog document to test walk & DFS performance directly
        raw_asset = DataAsset(id="ast_raw", name="raw_asset", type="raw")
        raw_ver = DataVersion(id="ver_0", asset_id=raw_asset.id, stage=DataStage.RAW, version_number=1)
        catalog_service.document.assets.append(raw_asset)
        catalog_service.document.versions.append(raw_ver)

        prev_id = raw_ver.id
        for i in range(1, depth + 1):
            ast = DataAsset(id=f"ast_{i}", name=f"asset_{i}", type="derived")
            ver = DataVersion(
                id=f"ver_{i}",
                asset_id=ast.id,
                stage=DataStage.DERIVED,
                version_number=1,
                parent_version_ids=[prev_id],
                run_id=f"run_{i}",
            )
            run = DataRun(
                id=f"run_{i}",
                operation=f"op_{i}",
                input_version_ids=[prev_id],
                output_version_ids=[ver.id],
            )
            catalog_service.document.assets.append(ast)
            catalog_service.document.versions.append(ver)
            catalog_service.document.runs.append(run)
            prev_id = ver.id

        leaf_id = prev_id
        catalog_service._invalidate_maps()

        # 1. Full ancestor traversal with max_nodes=2000
        t0 = time.perf_counter()
        full_chain = build_lineage_chain(catalog_service, leaf_id, direction="ancestors", max_nodes=2000)
        t_full = time.perf_counter() - t0
        assert not full_chain.truncated
        assert full_chain.node_count == depth + 1
        assert t_full < 0.2, f"1500-node full ancestor walk took {t_full}s"

        # 2. Truncated ancestor traversal with max_nodes=100
        chain_100 = build_lineage_chain(catalog_service, leaf_id, direction="ancestors", max_nodes=100)
        assert chain_100.truncated
        assert chain_100.node_count == 100

        # 3. Truncated ancestor traversal with max_depth=50
        chain_depth_50 = build_lineage_chain(catalog_service, leaf_id, direction="ancestors", max_depth=50)
        assert chain_depth_50.truncated
        assert chain_depth_50.node_count == 51

        # 4. Descendant traversal from RAW with max_nodes=250
        desc_chain = build_lineage_chain(catalog_service, raw_ver.id, direction="descendants", max_nodes=250)
        assert desc_chain.truncated
        assert desc_chain.node_count == 250

        # 5. Lineage summaries across all 1501 versions (Must not hit RecursionError)
        t0 = time.perf_counter()
        summaries = compute_summaries(catalog_service)
        t_sum = time.perf_counter() - t0

        assert t_sum < 0.5, f"1500-node lineage summaries took {t_sum}s"
        assert summaries[raw_ver.id]["to_raw"] == 0
        assert summaries[leaf_id]["to_raw"] == depth

    def test_dense_diamond_lattice_dag_1000_nodes(self, catalog_service):
        """Dense multi-parent DAG (20 layers x 50 nodes = 1000 nodes).
        Tests that memoization avoids exponential path explosion (2^20).
        """
        layers = 20
        width = 50

        # Layer 0: 2 RAW roots
        r1_ast = DataAsset(id="ast_r1", name="raw_1", type="raw")
        r1_ver = DataVersion(id="ver_r1", asset_id=r1_ast.id, stage=DataStage.RAW, version_number=1)
        r2_ast = DataAsset(id="ast_r2", name="raw_2", type="raw")
        r2_ver = DataVersion(id="ver_r2", asset_id=r2_ast.id, stage=DataStage.RAW, version_number=1)
        catalog_service.document.assets.extend([r1_ast, r2_ast])
        catalog_service.document.versions.extend([r1_ver, r2_ver])

        prev_layer = [r1_ver.id, r2_ver.id]

        for layer_idx in range(1, layers + 1):
            current_layer = []
            for node_idx in range(width):
                vid = f"ver_L{layer_idx}_N{node_idx}"
                ast_id = f"ast_L{layer_idx}_N{node_idx}"
                p1 = prev_layer[node_idx % len(prev_layer)]
                p2 = prev_layer[(node_idx + 1) % len(prev_layer)]

                ast = DataAsset(id=ast_id, name=f"L{layer_idx}_N{node_idx}", type="derived")
                ver = DataVersion(
                    id=vid,
                    asset_id=ast_id,
                    stage=DataStage.DERIVED,
                    version_number=1,
                    parent_version_ids=[p1, p2],
                )
                catalog_service.document.assets.append(ast)
                catalog_service.document.versions.append(ver)
                current_layer.append(vid)
            prev_layer = current_layer

        last_node_id = prev_layer[0]
        catalog_service._invalidate_maps()

        # Traversal with max_nodes bound
        t0 = time.perf_counter()
        chain = build_lineage_chain(catalog_service, last_node_id, direction="ancestors", max_nodes=500)
        t_chain = time.perf_counter() - t0
        assert t_chain < 0.2
        assert chain.node_count <= 500

        # Summaries on 1002 nodes with dense cross-connections
        t0 = time.perf_counter()
        summaries = compute_summaries(catalog_service)
        t_sum = time.perf_counter() - t0

        assert t_sum < 0.3, f"Dense diamond DAG summaries took {t_sum}s (must be polynomial, not exponential)"
        assert summaries[last_node_id]["to_raw"] == layers


# ============================================================================
# 3. Corrupted *.paleo.json Persistence & Disaster Recovery
# ============================================================================

class TestProjectDisasterRecoveryAndPersistenceStress:
    """Stress test file corruptions, syntax errors, missing fields, and concurrency."""

    def test_corrupted_json_truncated_file(self, tmp_path: Path):
        """Truncated JSON in *.paleo.json automatically recovers from *.paleo.json.bak."""
        proj_path = tmp_path / "corrupt_trunc.paleo.json"
        mgr = ProjectManager(proj_path)

        # 1. Save valid initial revision (Revision 1)
        doc1 = ProjectDocument.new("Version 1 (Good Baseline)")
        mgr.save(doc1)

        # 2. Save second revision (Revision 2), creating .bak containing Revision 1
        doc1.meta.name = "Version 2 (Updated State)"
        mgr.save(doc1)

        bak_path = project_backup_path(proj_path)
        assert bak_path.is_file()

        # 3. Simulate sudden crash / power outage truncating the main JSON file
        proj_path.write_text('{"meta": {"name": "Version 3 (Incom', encoding="utf-8")

        # 4. Reload should recover from .bak (which preserves the previous valid snapshot)
        reloaded_mgr = ProjectManager(proj_path)
        recovered_doc = reloaded_mgr.load()

        assert recovered_doc.meta.name == "Version 1 (Good Baseline)"
        assert reloaded_mgr.last_recovery_message is not None
        assert "已恢复" in reloaded_mgr.last_recovery_message
        # Verify the file on disk is restored and valid JSON
        assert json.loads(proj_path.read_text(encoding="utf-8"))["meta"]["name"] == "Version 1 (Good Baseline)"

    def test_corrupted_json_syntax_error(self, tmp_path: Path):
        """Malformed syntax / garbage bytes in *.paleo.json recovers from *.paleo.json.bak."""
        proj_path = tmp_path / "corrupt_syntax.paleo.json"
        mgr = ProjectManager(proj_path)

        doc = ProjectDocument.new("Valid Base Project")
        mgr.save(doc)
        doc.meta.name = "Updated Project"
        mgr.save(doc)

        # Corrupt primary project file with garbage bytes
        proj_path.write_bytes(b"\x00\xff\xfe\x01<<<NON_JSON_CORRUPT_HEADER>>>\x00")

        recovered_doc = ProjectManager(proj_path).load()
        assert recovered_doc.meta.name == "Valid Base Project"

    def test_corrupted_json_missing_required_schema_fields(self, tmp_path: Path):
        """Valid JSON but invalid schema (Pydantic ValidationError) recovers from *.paleo.json.bak."""
        proj_path = tmp_path / "corrupt_schema.paleo.json"
        mgr = ProjectManager(proj_path)

        doc = ProjectDocument.new("Schema Test Good")
        mgr.save(doc)
        doc.meta.name = "Schema Test Updated"
        mgr.save(doc)

        # Write valid JSON that violates ProjectDocument schema (missing meta, resources as integer)
        invalid_schema = {"invalid_key": 123, "meta": "not_a_meta_dict", "resources": 999}
        proj_path.write_text(json.dumps(invalid_schema), encoding="utf-8")

        recovered_doc = ProjectManager(proj_path).load()
        assert recovered_doc.meta.name == "Schema Test Good"

    def test_corrupted_both_main_and_backup_raises_cleanly(self, tmp_path: Path):
        """When both the primary project file and *.bak are corrupt, load() raises cleanly."""
        proj_path = tmp_path / "corrupt_both.paleo.json"
        mgr = ProjectManager(proj_path)

        doc = ProjectDocument.new("Test")
        mgr.save(doc)
        doc.meta.name = "Test 2"
        mgr.save(doc)

        bak_path = project_backup_path(proj_path)
        proj_path.write_text("{ broken main", encoding="utf-8")
        bak_path.write_text("{ broken bak", encoding="utf-8")

        with pytest.raises((json.JSONDecodeError, Exception)):
            ProjectManager(proj_path).load()

    def test_concurrency_stale_write_protection(self, tmp_path: Path):
        """Concurrent modifications across multiple ProjectManager instances trigger ProjectStaleWriteError."""
        proj_path = tmp_path / "concurrent.paleo.json"
        mgr_a = ProjectManager(proj_path)
        mgr_b = ProjectManager(proj_path)

        # Initial save by process A
        doc_a = ProjectDocument.new("Base Name")
        mgr_a.save(doc_a)

        # Process B loads the project
        doc_b = mgr_b.load()

        # Process A makes changes and saves
        doc_a.meta.name = "Process A Modification"
        mgr_a.save(doc_a)

        # Process B attempts to save its stale state -> must raise ProjectStaleWriteError
        doc_b.meta.name = "Process B Conflict"
        with pytest.raises(ProjectStaleWriteError, match="已被其他实例修改"):
            mgr_b.save(doc_b)

    def test_clean_session_teardown_cleans_temporary_swap_files(self, tmp_path: Path):
        """Load cleans up orphaned interrupted temp files while preserving unrelated user files."""
        proj_path = tmp_path / "orphan_cleanup.paleo.json"
        mgr = ProjectManager(proj_path)
        mgr.save(ProjectDocument.new("Orphan Test"))

        owned_temp1 = tmp_path / f".{proj_path.name}.12345.tmp"
        owned_temp2 = tmp_path / f".{proj_path.name}.interrupted.tmp"
        foreign_temp = tmp_path / ".other_unrelated_project.tmp"

        owned_temp1.write_text("partial", encoding="utf-8")
        owned_temp2.write_text("partial", encoding="utf-8")
        foreign_temp.write_text("keep me", encoding="utf-8")

        mgr.load()

        assert not owned_temp1.exists()
        assert not owned_temp2.exists()
        assert foreign_temp.exists()


# ============================================================================
# 4. Full Geological Pipeline Provenance Chain Traversal
# ============================================================================

class TestGeologicalPipelineProvenanceStress:
    """Stress test multi-factor, multi-algorithm geological pipeline provenance traversal."""

    def test_full_multi_factor_kriging_and_idw_pipeline_provenance(self, catalog_service, tmp_path: Path):
        """Multi-well RAW dataset -> Kriging (Porosity) & IDW (Permeability) -> MapDocument.
        Verifies dual-parent provenance tracking, property aliases, and descriptor serialization.
        """
        from paleo_workbench.catalog.grid_artifact import write_grid_artifact
        from paleo_workbench.mapping.geological_pipeline.models import (
            GeologicalFactorDataset,
            InterpolationOptions,
        )
        from paleo_workbench.mapping.geological_pipeline.pipeline import GeologicalMappingPipeline

        # 1. Create RAW Multi-Well Survey Dataset
        raw_wells_file = tmp_path / "survey_wells.json"
        well_data = [
            {"well_id": f"W_{i}", "x": 100.0 + i * 25.0, "y": 200.0 + (i % 3) * 30.0, "porosity": 10.0 + i * 1.5, "permeability": 50.0 + i * 12.0, "target_horizon": "H_SAND"}
            for i in range(10)
        ]
        raw_wells_file.write_text(json.dumps(well_data), encoding="utf-8")
        raw_version = catalog_service.import_raw(
            raw_wells_file,
            name="survey_wells_2026.json",
            type="well_table",
        )
        assert raw_version.stage == DataStage.RAW

        pipeline = GeologicalMappingPipeline()
        records = json.loads(raw_wells_file.read_text(encoding="utf-8"))

        # 2. Factor 1: Porosity via Ordinary Kriging
        porosity_ds = pipeline.extract_factors(records, "porosity", target_horizon="H_SAND")
        poro_opts = InterpolationOptions(method="kriging", grid_n=25, crs="EPSG:3857")
        poro_grid = pipeline.interpolate(porosity_ds, poro_opts)
        poro_grid.input_version_ids = [raw_version.id]

        poro_run = catalog_service.register_run(
            operation="factor_kriging",
            input_version_ids=[raw_version.id],
            output_version_ids=[],
            parameters={"factor": "porosity", "algorithm": "kriging"},
            generator="GeologicalMappingPipeline",
        )
        poro_grid.run_id = poro_run.id
        poro_desc = poro_grid.to_descriptor()
        assert poro_desc["input_version_ids"] == [raw_version.id]
        assert poro_desc["run_id"] == poro_run.id

        poro_art_path = write_grid_artifact(poro_grid, tmp_path, "porosity_kriging")
        poro_version = catalog_service.register_result_asset(
            name="porosity_grid_kriging",
            type="factor_grid",
            format="npz",
            asset_metadata={"factor_name": "porosity"},
            source_path=poro_art_path,
            stage=DataStage.INTERMEDIATE,
            run_id=poro_run.id,
            version_metadata={"descriptor": poro_desc},
        )

        # 3. Factor 2: Permeability via IDW
        perm_ds = pipeline.extract_factors(records, "permeability", target_horizon="H_SAND")
        perm_opts = InterpolationOptions(method="idw", grid_n=25, crs="EPSG:3857")
        perm_grid = pipeline.interpolate(perm_ds, perm_opts)
        perm_grid.input_version_ids = [raw_version.id]

        perm_run = catalog_service.register_run(
            operation="factor_idw",
            input_version_ids=[raw_version.id],
            output_version_ids=[],
            parameters={"factor": "permeability", "algorithm": "idw"},
            generator="GeologicalMappingPipeline",
        )
        perm_grid.run_id = perm_run.id
        perm_desc = perm_grid.to_descriptor()

        perm_art_path = write_grid_artifact(perm_grid, tmp_path, "permeability_idw")
        perm_version = catalog_service.register_result_asset(
            name="permeability_grid_idw",
            type="factor_grid",
            format="npz",
            asset_metadata={"factor_name": "permeability"},
            source_path=perm_art_path,
            stage=DataStage.INTERMEDIATE,
            run_id=perm_run.id,
            version_metadata={"descriptor": perm_desc},
        )

        # 4. Composite Geological Map Document (combining both factor grids + contours + wells)
        map_run = catalog_service.register_run(
            operation="composite_map_compile",
            input_version_ids=[poro_version.id, perm_version.id],
            output_version_ids=[],
            parameters={"title": "H_SAND Composite Reservoir Map"},
            generator="GeologicalMappingPipeline",
        )

        map_doc = pipeline.build_factor_map_document(
            porosity_ds,
            poro_opts,
            include_grid=True,
            include_contours=True,
            include_wells=True,
            include_polygons=True,
            run_id=map_run.id,
            input_version_ids=[poro_version.id, perm_version.id],
        )

        # Validate MapDocument property getters and contract compliance
        assert map_doc.run_id == map_run.id
        assert poro_version.id in map_doc.input_version_ids
        assert perm_version.id in map_doc.input_version_ids

        map_file = tmp_path / "composite_reservoir_map.json"
        map_file.write_text(json.dumps(map_doc.to_dict()), encoding="utf-8")

        map_version = catalog_service.register_result_asset(
            name="composite_reservoir_map",
            type="map_document",
            format="json",
            asset_metadata={"title": map_doc.title},
            source_path=map_file,
            stage=DataStage.OUTPUT,
            run_id=map_run.id,
            version_metadata={"layer_count": len(map_doc.layers)},
        )

        # 5. Verify Ancestor Lineage Walk from MapDocument
        anc_chain = catalog_service.get_lineage_chain(map_version.id, direction="ancestors")
        assert anc_chain.direction == "ancestors"
        assert not anc_chain.truncated
        assert anc_chain.root.version_id == map_version.id
        assert anc_chain.root.run_operation == "composite_map_compile"

        # Children of map_doc should be the 2 intermediate factor grids
        parent_vids = {child.version_id for child in anc_chain.root.children}
        assert parent_vids == {poro_version.id, perm_version.id}

        # Spanning tree reaches RAW Well version from the factor grids
        all_visited_vids = set()
        def collect_vids(node):
            all_visited_vids.add(node.version_id)
            for c in node.children:
                collect_vids(c)
        collect_vids(anc_chain.root)
        assert raw_version.id in all_visited_vids

        # 6. Verify Descendant Lineage Walk from RAW Well Dataset
        desc_chain = catalog_service.get_lineage_chain(raw_version.id, direction="descendants")
        assert desc_chain.direction == "descendants"
        assert not desc_chain.truncated
        assert desc_chain.root.version_id == raw_version.id

        desc_vids = {c.version_id for c in desc_chain.root.children}
        assert desc_vids == {poro_version.id, perm_version.id}

        # 7. Verify Lineage Summaries
        summaries = catalog_service.lineage_summaries()
        assert summaries[raw_version.id] == {"to_raw": 0, "broken": False, "has_parents": False}
        assert summaries[poro_version.id] == {"to_raw": 1, "broken": False, "has_parents": True}
        assert summaries[perm_version.id] == {"to_raw": 1, "broken": False, "has_parents": True}
        assert summaries[map_version.id] == {"to_raw": 2, "broken": False, "has_parents": True}

    def test_lineage_with_trashed_intermediate_asset(self, catalog_service, tmp_path: Path):
        """Trashed intermediate asset is flagged with trashed=True in lineage chain."""
        f_raw = tmp_path / "raw.dat"; f_raw.write_bytes(b"raw")
        raw = catalog_service.import_raw(f_raw, name="raw", type="raw")

        f_inter = tmp_path / "inter.dat"; f_inter.write_bytes(b"inter")
        inter = catalog_service.create_derived(
            f_inter, parent_version_ids=[raw.id], name="inter", operation="op"
        )
        f_out = tmp_path / "out.dat"; f_out.write_bytes(b"out")
        out = catalog_service.create_derived(
            f_out, parent_version_ids=[inter.id], name="out", operation="op_out"
        )

        # Move intermediate asset to trash
        catalog_service.trash_asset(inter.asset_id)

        chain = catalog_service.get_lineage_chain(out.id, direction="ancestors")
        assert not chain.truncated
        assert chain.root.children[0].version_id == inter.id
        assert chain.root.children[0].trashed is True


def test_legacy_absolute_paths_portablized_and_unknown_sections_kept(tmp_path, caplog):
    """#1170: legacy absolute resource paths migrate to portable form;
    unknown (newer-schema) sections survive a load/save round-trip."""
    import logging

    from paleo_workbench.project.manager import ProjectManager

    data_file = tmp_path / "data" / "A.Las"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_bytes(b"las")
    proj_path = tmp_path / "legacy.paleo.json"
    doc = ProjectDocument.new("Legacy")
    payload = doc.model_dump(mode="json")
    payload["resources"] = [{
        "id": "res-1", "name": "A.Las",
        "path": str(data_file),
        "type": "well_log", "format": "las",
    }]
    payload["future_section"] = {"x": 1}
    proj_path.write_text(json.dumps(payload), encoding="utf-8")

    mgr = ProjectManager(proj_path)
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.project.manager"):
        project = mgr.load()
    assert any("future_section" in r.message for r in caplog.records)

    mgr.save(project)
    round_tripped = json.loads(proj_path.read_text(encoding="utf-8"))
    assert round_tripped["future_section"] == {"x": 1}
    stored = round_tripped["resources"][0]["path"]
    assert not Path(stored).is_absolute(), stored
    assert round_tripped["resources"][0]["external"] is False
