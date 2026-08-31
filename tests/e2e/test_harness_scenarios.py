"""P2-C end-to-end harness scenarios A–E (production paths, no mocks).

A. 显示当前工区所有井位并标注井名 — well location map with labels + components + validation.
B. 打开 W23，显示 GR、RT、AC — resolve well → curves → display doc → template.
C. 对当前地震体计算 coherence — open_volume → attribute provider → derived store + provenance.
D. 用当前厚度数据生成克里金单因素图，并加图例、色标、比例尺和指北针。
E. 导出当前图 — validation gate → export provider → catalog OUTPUT version.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GEN_PATH = _REPO_ROOT / "benchmarks" / "generate_synthetic_segy.py"
_spec = importlib.util.spec_from_file_location("generate_synthetic_segy", _GEN_PATH)
gen = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("generate_synthetic_segy", gen)
_spec.loader.exec_module(gen)

from paleo_workbench.harness import ActionContext, HarnessExecutor, SelectionSnapshot  # noqa: E402

segyio = pytest.importorskip("segyio")

_WELL_NAMES = ["W1", "W7", "W15", "W23", "W31", "W42"]
_CURVES = ["GR", "RT", "AC"]


def _write_las(path: Path, well: str, samples: int = 120) -> None:
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
def harness_project(tmp_path_factory):
    """Project + catalog + zarr volume over synthetic production loaders."""
    from paleo_workbench.catalog.adapter import CoreCatalogAdapter
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.resources.scanner import scan_resources

    root = tmp_path_factory.mktemp("p2-e2e")
    project_path = root / "demo.paleo.json"
    project_path.write_text("{}", encoding="utf-8")
    wells_dir = root / "wells"
    wells_dir.mkdir()
    for i, name in enumerate(_WELL_NAMES):
        _write_las(wells_dir / f"{name}.las", name)
    segy = root / "tiny.segy"
    spec = gen.PRESETS["tiny"]
    gen.generate_volume(type(spec)(spec.nil, spec.nxl, spec.nt, seed=5), segy, progress=False)

    document = ProjectDocument.new(name="P2-E2E", region="测试")
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

    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)

    # Transcode the SEG-Y once (production transcoder) for scenario C.
    from paleo_workbench.seismic_transcode import TranscodeParams, transcode_segy_to_zarr

    zarr_store = root / "tiny.zarr"
    transcode_segy_to_zarr(segy, zarr_store, params=TranscodeParams())

    from paleo_workbench.harness.spec import DEFAULT_PERMISSIONS, ActionRisk

    context = ActionContext(
        workspace_id="P2-E2E",
        project_path=str(project_path),
        catalog=adapter,
        project=document,
        selection=SelectionSnapshot(active_well_id=None),
        # App-level session semantics: WRITE granted (headless default is
        # READ+COMPUTE; from_app grants WRITE the same way).
        permissions=DEFAULT_PERMISSIONS | {ActionRisk.WRITE},
    )
    yield {
        "root": root,
        "document": document,
        "context": context,
        "service": service,
        "segy": segy,
        "zarr": zarr_store,
    }
    service.close()


@pytest.fixture(scope="module")
def executor() -> HarnessExecutor:
    return HarnessExecutor()


# ------------------------------------------------------------- Scenario A
def test_scenario_a_well_location_map_with_labels(executor, harness_project, qapp):
    ctx = harness_project["context"]
    listing = executor.execute("well.list", {}, ctx)
    assert listing.ok and listing.outputs["count"] == len(_WELL_NAMES)

    created = executor.execute(
        "map.create_well_location_map", {"title": "井位图", "label_wells": True}, ctx
    )
    assert created.ok, created.error
    assert created.outputs["well_count"] == len(_WELL_NAMES)
    assert created.outputs["extent"] is not None
    document = created.outputs["map_document"]
    layer = document.layers[0]
    assert layer.features, "well layer must carry features"
    assert (layer.style or {}).get("labels", {}).get("field") == "name", "labels bound to well name"

    for component in ("legend", "scale_bar", "north_arrow", "title"):
        added = executor.execute("map.add_component", {"component": component, "text": "井位图"}, ctx)
        assert added.ok, added.error

    validated = executor.execute("map.validate", {"require_components": True}, ctx)
    assert validated.ok
    assert validated.outputs["report"]["verdict"] == "pass", validated.outputs["report"]["reasons"]


# ------------------------------------------------------------- Scenario B
def test_scenario_b_open_w23_display_gr_rt_ac(executor, harness_project):
    ctx = harness_project["context"]
    opened = executor.execute("well.open", {"well": "W23"}, ctx)
    assert opened.ok, opened.error
    assert opened.outputs["name"] == "W23"
    for curve in _CURVES:
        assert curve in opened.outputs["curves"]

    curves = executor.execute("well.list_curves", {}, ctx)
    assert curves.ok
    names = {c["name"] for c in curves.outputs["curves"]}
    assert {"GR", "RT", "AC"} <= names

    display = executor.execute("well.create_display", {"curves": ["GR", "RT", "AC"]}, ctx)
    assert display.ok, display.error
    doc = display.outputs["display"]
    assert doc["well_name"] == "W23"
    displayed = {c["name"] for t in doc["tracks"] for c in t["curves"]}
    assert {"GR", "RT", "AC"} <= displayed
    assert doc["depth_range"][0] < doc["depth_range"][1]

    templated = executor.execute("well.apply_template", {"template_id": "tight-3track"}, ctx)
    assert templated.ok
    assert templated.outputs["template"]["template_id"] == "tight-3track"


# ------------------------------------------------------------- Scenario C
def test_scenario_c_coherence_on_active_volume(executor, harness_project, tmp_path):
    ctx = harness_project["context"]
    opened = executor.execute(
        "seismic.open_volume", {"path": str(harness_project["zarr"])}, ctx
    )
    assert opened.ok, opened.error
    assert opened.outputs["volume"]["store_kind"] == "zarr"

    first_slice = executor.execute(
        "seismic.get_slice", {"slice_type": "inline", "index": 1}, ctx
    )
    assert first_slice.ok, first_slice.error
    assert first_slice.outputs["finite_ratio"] > 0.99

    computed = executor.execute(
        "seismic.compute_attribute",
        {"attribute": "c3", "output_dir": "artifacts/attr-c3.zarr"},
        ctx,
    )
    out_dir = harness_project["root"] / "artifacts" / "attr-c3.zarr"
    assert computed.ok, computed.error
    assert computed.outputs["artifacts"], "derived store artifact expected"
    artifact = computed.outputs["artifacts"][0]
    assert artifact["kind"] == "derived_store"
    artifact_path = Path(artifact["path"])
    if not artifact_path.is_absolute():
        artifact_path = harness_project["root"] / artifact_path
    assert artifact_path.exists()
    # Provenance: the run + derived version landed in the catalog.
    provenance = computed.outputs["provenance"]
    assert provenance["provider_id"] == "seismic.attribute.c3"
    lineage = executor.execute(
        "workspace.get_lineage",
        {"version_id": artifact["version"]["version_id"], "direction": "ancestors"},
        ctx,
    )
    assert lineage.ok, lineage.error


# ------------------------------------------------------------- Scenario D
def test_scenario_d_kriging_factor_map_with_components(executor, harness_project):
    ctx = harness_project["context"]
    created = executor.execute(
        "map.create_factor_map",
        {"factor_name": "thickness", "method": "kriging", "grid_n": 32, "title": "厚度克里金图"},
        ctx,
    )
    assert created.ok, created.error
    assert created.outputs["layer_count"] >= 1
    # Scientific verification ran on the interpolated grid and passed.
    assert created.outputs.get("values"), "grid payload expected for verification"
    assert created.verification.get("verdict") in ("pass", "warning"), created.verification

    for component in ("legend", "colorbar", "scale_bar", "north_arrow", "title"):
        added = executor.execute(
            "map.add_component", {"component": component, "text": "厚度克里金图"}, ctx
        )
        assert added.ok, added.error
    components = executor.execute("map.validate", {"require_components": True}, ctx)
    assert components.ok
    report = components.outputs["report"]
    assert report["verdict"] == "pass", report["reasons"]


# ------------------------------------------------------------- Scenario E
def test_scenario_e_export_map_product(executor, harness_project, tmp_path, qapp):
    ctx = harness_project["context"]
    # Re-create a complete map (module-scoped context may have moved on).
    created = executor.execute(
        "map.create_factor_map", {"factor_name": "thickness", "method": "kriging", "grid_n": 24}, ctx
    )
    assert created.ok, created.error
    for component in ("legend", "scale_bar", "north_arrow", "title"):
        executor.execute("map.add_component", {"component": component, "text": "导出图"}, ctx)

    # Export paths are confined to the project workspace: a relative path
    # resolves under the project root (agent cannot write outside it).
    out_rel = "exports/map.png"
    exported = executor.execute(
        "map.export", {"output_path": out_rel, "width": 800, "height": 600}, ctx
    )
    assert exported.ok, exported.error
    assert exported.outputs["exported"] is True, exported.outputs
    out_path = harness_project["root"] / out_rel
    assert out_path.exists() and out_path.stat().st_size > 0
    artifact = exported.outputs["artifacts"][0]
    assert artifact["kind"] == "file"
    # Catalog OUTPUT version registered (production export path).
    assert artifact["version"], "catalog OUTPUT version expected"

    # An invalid map must NOT export (fail-closed validation gate): the
    # action FAILS with the verification reasons — never a success-shaped
    # refusal.
    ctx.map_documents[ctx.current_map_id].layers.clear()
    rejected = executor.execute(
        "map.export", {"output_path": "exports/bad.png"}, ctx
    )
    assert rejected.status == "fail"
    assert "validation" in rejected.error

    # Boundary checks need a VALID map (the validation gate short-circuits first).
    rebuilt = executor.execute(
        "map.create_factor_map", {"factor_name": "thickness", "method": "idw", "grid_n": 16}, ctx
    )
    assert rebuilt.ok
    for component in ("legend", "scale_bar", "north_arrow", "title"):
        executor.execute("map.add_component", {"component": component, "text": "边界测试"}, ctx)
    # Absolute paths outside the workspace are refused outright.
    outside = executor.execute(
        "map.export", {"output_path": "/definitely-outside.png"}, ctx
    )
    assert outside.status == "fail", outside.error
    assert "workspace" in outside.error
    # Overwriting an existing file is refused (no destructive export).
    again = executor.execute(
        "map.export", {"output_path": out_rel, "width": 640, "height": 480}, ctx
    )
    assert again.status == "fail"
    assert "overwrite" in again.error


# ------------------------------------------------- context awareness check
def test_context_awareness_active_well_shortcut(executor, harness_project):
    """User says "当前井" — the harness context carries ActiveWell so the
    agent doesn't re-search all wells."""
    ctx = harness_project["context"]
    ctx.active_well_id = None
    opened = executor.execute("well.open", {"well": "W31"}, ctx)
    assert opened.ok
    assert ctx.active_well_id is not None  # open sets the active well
    curves = executor.execute("well.list_curves", {}, ctx)  # no well arg → active
    assert curves.ok
    assert curves.outputs["well_id"] == ctx.active_well_id

    described = executor.execute("workspace.describe_context", {}, ctx)
    snapshot = described.outputs["context"]
    assert snapshot["active_well_id"] == ctx.active_well_id
    assert json.dumps(snapshot)  # agent-prompt-ready JSON


def test_tool_schemas_cover_actions_with_json_schemas():
    from paleo_workbench.harness.registry import get_action_registry

    registry = get_action_registry()
    try:
        schemas = registry.tool_schemas()
        assert len(schemas) == len(registry.specs())
        for schema in schemas:
            json.dumps(schema)  # machine-readable
            assert schema["function"]["parameters"]["type"] == "object"
    finally:
        from paleo_workbench.harness import set_action_registry

        set_action_registry(None)
