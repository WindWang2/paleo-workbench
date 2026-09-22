"""Harness 2.0 acceptance workflows A/B/C as REAL end-to-end DAG runs.

Every node is a registered professional action executed through the
engine + HarnessExecutor guard pipeline over synthetic input data and
real production services; every completed node carries a scientific
execution receipt. No mocks, no fake success paths.

A. 单因素图: data.search → factor map compile → composition → QC →
   contour → export (contained PNG + catalog OUTPUT).
B. 测井处理: well list → real well-table QC (process) → derived factor
   grid → catalog integrity verify of the derived artifact.
C. MapProduct reproduction: run A once → save recipe → describe
   reproduction → rebind + rerun → compare receipts/outputs.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GEN_PATH = _REPO_ROOT / "benchmarks" / "generate_synthetic_segy.py"
_spec = importlib.util.spec_from_file_location("generate_synthetic_segy", _GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("generate_synthetic_segy", gen)
_spec.loader.exec_module(gen)

from paleo_workbench.harness import (  # noqa: E402
    DEFAULT_PERMISSIONS,
    ActionContext,
    ActionRegistry,
    ActionRisk,
    SelectionSnapshot,
)
from paleo_workbench.harness.actions import register_all  # noqa: E402
from paleo_workbench.workflow.dag import (  # noqa: E402
    NodeSpec,
    WorkflowEngine,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.store import WorkflowRunStore  # noqa: E402

_WELL_NAMES = ["W1", "W7", "W15", "W23", "W31", "W42"]


def _write_las(path: Path, well: str, samples: int = 120) -> None:
    import numpy as np

    depth = np.linspace(1000.0, 2000.0, samples)
    rng = np.random.default_rng(hash(well) % (2**32))
    gr = 40 + 60 * rng.random(samples)
    rt = np.clip(1 + 10 * rng.random(samples), 0.01, None)
    ac = 60 + 30 * rng.random(samples)
    lines = [
        "~VERSION INFORMATION",
        "VERS. 2.0:",
        "WRAP. NO:",
        "~WELL INFORMATION",
        f"WELL. {well}:",
        "NULL. -999.25:",
        "~CURVE INFORMATION",
        "DEPT.M: Depth",
        "GR.GAPI: Gamma Ray",
        "RT.OHMM: Resistivity",
        "AC.US/M: Sonic",
        "~PARAMETER INFORMATION",
        "~OTHER",
        "~A DEPT GR RT AC",
    ]
    for d, g, r, a in zip(depth, gr, rt, ac):
        lines.append(f"{d:10.2f} {g:10.4f} {r:10.4f} {a:10.4f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_project(tmp_path_factory):
    """Project + catalog + wells + one seeded well table (real files)."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument, WellTableRow, WellTable
    from paleo_workbench.resources.scanner import scan_resources

    root = tmp_path_factory.mktemp("harness2-e2e")
    project_path = root / "wf.paleo.json"
    project_path.write_text("{}", encoding="utf-8")
    wells_dir = root / "wells"
    wells_dir.mkdir()
    for i, name in enumerate(_WELL_NAMES):
        _write_las(wells_dir / f"{name}.las", name)

    document = ProjectDocument.new(name="Harness2-E2E", region="测试")
    document.meta.project_root = str(root)
    document.resources = scan_resources(root)
    for i, name in enumerate(_WELL_NAMES):
        document.wells.append(
            WellEntity(
                name=name,
                surface_x=500_000.0 + i * 800.0,
                surface_y=4_400_000.0 + i * 600.0,
                source_crs="EPSG:32650",
                td=2000.0,
                metadata={"thickness": 12.0 + 3.0 * i},
            )
        )
    document.stratigraphy.target_horizon = "T2"

    # A REAL well table (thickness rows with one planted outlier) for B.
    rows = []
    for i, name in enumerate(_WELL_NAMES):
        thickness = 12.0 + 3.0 * i
        rows.append(
            WellTableRow(
                name=name,
                x=500_000.0 + i * 800.0,
                y=4_400_000.0 + i * 600.0,
                z=thickness,
                attributes={"thickness": thickness},
            )
        )
    rows.append(
        WellTableRow(
            name="W-OUTLIER",
            x=505_000.0,
            y=4_403_500.0,
            z=900.0,
            attributes={"thickness": 900.0},
        )
    )
    document.well_tables.append(
        WellTable(name="厚度表", target_horizon="T2", factor_type="thickness", rows=rows)
    )

    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)

    context = ActionContext(
        workspace_id="Harness2-E2E",
        project_path=str(project_path),
        catalog=adapter,
        project=document,
        selection=SelectionSnapshot(active_well_id="W1"),
        permissions=DEFAULT_PERMISSIONS | {ActionRisk.WRITE},
    )
    yield {
        "root": root,
        "document": document,
        "context": context,
        "service": service,
        "catalog": adapter,
    }
    service.close()


@pytest.fixture()
def engine(workflow_project):
    reg = ActionRegistry()
    register_all(reg)
    eng = WorkflowEngine(
        registry=reg,
        store=WorkflowRunStore(str(workflow_project["root"] / "wf-runs")),
        catalog=workflow_project["catalog"],
    )
    return eng


def _assert_receipts(done):
    for node_id, nr in done.node_runs.items():
        if nr.state.value in ("skipped",):
            continue
        assert nr.state.value == "succeeded", f"{node_id}: {nr.state} {nr.error}"
        receipt = nr.receipt
        assert receipt, f"{node_id} lacks a receipt"
        assert receipt["status"] in ("success", "degraded")
        assert receipt["action_id"]
        assert receipt["action_version"]
        assert receipt["environment"]["python"]
        assert "duration_ms" in receipt


def test_workflow_a_single_factor_map(engine, workflow_project, qapp):
    ctx = workflow_project["context"]
    spec = WorkflowSpec(
        workflow_id="wf.single-factor-map",
        name="单因素图工作流",
        max_concurrency=1,  # the map document is shared in-process state
        nodes=(
            NodeSpec(node_id="search", action_id="data.search", description="数据检索",
                     parameters={"stage": "raw"}),
            NodeSpec(node_id="factor_map", action_id="map.create_factor_map",
                     description="因素插值与编图", depends_on=("search",),
                     parameters={"factor_name": "thickness", "method": "kriging",
                                 "grid_n": 24, "target_horizon": "T2"}),
            NodeSpec(node_id="compose", action_id="map.apply_template",
                     description="套合成模板", depends_on=("factor_map",),
                     parameters={"template": "standard"}),
            NodeSpec(node_id="legend", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "legend"}),
            NodeSpec(node_id="scale", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "scale_bar"}),
            NodeSpec(node_id="north", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "north_arrow"}),
            NodeSpec(node_id="qc", action_id="map.qc", description="图件 QC",
                     depends_on=("legend", "scale", "north"),
                     parameters={"require_components": True}),
            NodeSpec(node_id="contour", action_id="map.contour", description="等值线",
                     depends_on=("factor_map",), parameters={"n_levels": 8}),
            NodeSpec(node_id="export", action_id="map.export", description="导出",
                     depends_on=("qc",),
                     parameters={"output_path": "artifacts/export/factor-map.png"}),
        ),
    )
    run = engine.create_run(spec, context=ctx)
    done = engine.run(run.run_id, context=ctx)
    assert done.state.value == "completed", {
        k: (v.state.value, v.error) for k, v in done.node_runs.items()
    }
    _assert_receipts(done)

    # Real artifacts on disk.
    exported = workflow_project["root"] / "artifacts" / "export" / "factor-map.png"
    assert exported.exists() and exported.stat().st_size > 0
    with open(exported, "rb") as fh:
        assert fh.read(8).startswith(b"\x89PNG")
    # The exported product entered the catalog.
    export_node = done.node_runs["export"]
    assert export_node.output_version_ids, "export must register a catalog OUTPUT"
    ref = workflow_project["catalog"].resolve_version(export_node.output_version_ids[0])
    assert ref is not None and not ref.trashed
    # The QC receipt records a pass.
    assert done.node_runs["qc"].receipt["outputs_summary"].get("passed") is True


def test_workflow_b_well_processing(engine, workflow_project):
    ctx = workflow_project["context"]
    spec = WorkflowSpec(
        workflow_id="wf.well-processing",
        name="测井处理工作流",
        max_concurrency=1,
        nodes=(
            NodeSpec(node_id="list", action_id="well.list", description="井输入"),
            NodeSpec(node_id="process", action_id="well.process", description="QC+处理",
                     depends_on=("list",),
                     parameters={"value_key": "z", "mad_threshold": 3.5}),
            NodeSpec(node_id="derived", action_id="map.create_factor_map",
                     description="生成派生网格", depends_on=("process",),
                     parameters={"factor_name": "thickness", "method": "idw",
                                 "grid_n": 20, "target_horizon": "T2"}),
            NodeSpec(node_id="verify", action_id="data.verify", description="完整性校验",
                     depends_on=("derived",),
                     parameters={"version_id": {"$ref": "derived", "key": "version_id"}}),
        ),
    )
    run = engine.create_run(spec, context=ctx)
    done = engine.run(run.run_id, context=ctx)
    assert done.state.value == "completed", {
        k: (v.state.value, v.error) for k, v in done.node_runs.items()
    }
    _assert_receipts(done)
    # The QC really flagged the planted outlier.
    qc = done.node_runs["process"].outputs["qc"]
    assert qc["total"] == 7 and qc["outlier"] >= 1
    # The derived grid version resolves and integrity-verifies.
    version_id = done.node_runs["derived"].output_version_ids[0]
    assert done.node_runs["verify"].outputs["integrity"] == "verified"
    ref = workflow_project["catalog"].resolve_version(version_id)
    assert ref is not None


def test_workflow_c_map_product_reproduction(engine, workflow_project, qapp):
    ctx = workflow_project["context"]
    from paleo_workbench.workflow.dag import SlotSpec

    spec = WorkflowSpec(
        workflow_id="wf.reproducible-map",
        name="可复现编图",
        max_concurrency=1,
        slots=(
            SlotSpec(
                name="export_path",
                schema={"type": "string"},
                default="artifacts/export/repro-v1.png",
            ),
        ),
        nodes=(
            NodeSpec(node_id="factor_map", action_id="map.create_factor_map",
                     description="因素编图",
                     parameters={"factor_name": "thickness", "method": "kriging",
                                 "grid_n": 16, "target_horizon": "T2"}),
            NodeSpec(node_id="compose", action_id="map.apply_template",
                     description="套合成模板", depends_on=("factor_map",),
                     parameters={"template": "standard"}),
            NodeSpec(node_id="legend", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "legend"}),
            NodeSpec(node_id="scale", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "scale_bar"}),
            NodeSpec(node_id="north", action_id="map.add_component",
                     depends_on=("compose",), parameters={"component": "north_arrow"}),
            NodeSpec(node_id="export", action_id="map.export", description="导出",
                     depends_on=("legend", "scale", "north"),
                     parameters={"output_path": {"$slot": "export_path"}}),
        ),
    )
    first = engine.create_run(spec, context=ctx)
    done = engine.run(first.run_id, context=ctx)
    assert done.state.value == "completed", {
        k: (v.state.value, v.error) for k, v in done.node_runs.items()
    }

    # Save the successful run as a portable recipe and describe reproduction.
    from paleo_workbench.workflow.recipe import (
        clone_recipe,
        load_recipe,
        recipe_from_run,
        save_recipe,
    )

    recipe = recipe_from_run(engine.store_for(ctx).load(first.run_id))
    path = save_recipe(
        recipe, workflow_project["root"] / "wf-runs" / "repro.paleo-workflow.json",
        registry=engine.registry,
    )
    loaded = load_recipe(path)
    assert loaded.source_run_id == first.run_id
    # The recipe reproduces the run's graph faithfully.
    assert [n.node_id for n in loaded.workflow.nodes] == [
        n.node_id for n in done.workflow.nodes
    ]
    assert loaded.workflow.node("factor_map").parameters["factor_name"] == "thickness"

    from paleo_workbench.workflow.dag.reproduction import describe_reproduction

    repro = describe_reproduction(engine.store_for(ctx).load(first.run_id))
    assert repro["spec_hash"] == done.spec_hash
    executed = [n for n in repro["nodes"] if n["executed"]]
    assert {n["node_id"] for n in executed} == {
        "factor_map", "compose", "legend", "scale", "north", "export",
    }

    # Rerun from the export: everything upstream is provably unchanged
    # (identical identities) → carried over; the export re-executes because
    # its identity changed with the fresh output path requirement.
    second = engine.rerun(
        first.run_id,
        from_nodes=["export"],
        slot_overrides={"export_path": "artifacts/export/repro-v2.png"},
        context=ctx,
    )
    assert second.state.value == "completed", {
        k: (v.state.value, v.error) for k, v in second.node_runs.items()
    }
    assert second.node_runs["factor_map"].from_cache is True
    assert second.node_runs["export"].from_cache is False
    # Compare receipts: the carried node keeps identical output identity.
    assert (
        second.node_runs["factor_map"].output_version_ids
        == done.node_runs["factor_map"].output_version_ids
    )
    assert (
        second.node_runs["export"].output_version_ids
        != done.node_runs["export"].output_version_ids
    )
    # The rebound export produced a REAL new artifact and catalog version.
    assert (workflow_project["root"] / "artifacts" / "export" / "repro-v2.png").exists()
    fresh_export = workflow_project["catalog"].resolve_version(
        second.node_runs["export"].output_version_ids[0]
    )
    assert fresh_export is not None


@pytest.fixture()
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
