"""Stage 12: multi-well correlation + fault interpretation lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import set_catalog, reset_catalog
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.correlation_artifact import (
    scientific_fingerprint_correlation,
    write_correlation_artifact,
)
from paleo_workbench.workflow.correlation_lifecycle import (
    detect_depth_domain_mismatch,
    draft_fingerprint,
    new_correlation_draft,
    open_draft_from_version,
    resolve_correlation_target_horizon,
    restore_draft_from_project_ref,
    save_correlation_draft,
    tops_from_imported_dict,
)
from paleo_workbench.workflow.fault_lifecycle import (
    draft_fingerprint as fault_fp,
    new_fault_draft,
    restore_fault_draft_from_project,
    save_fault_draft,
)
from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationLink,
    CorrelationMethod,
    DepthDomain,
    FaultTrace,
    FormationTop,
)
from tests.fakes.inmemory_catalog import InMemoryCatalog


@pytest.fixture
def catalog(tmp_path: Path):
    cat = InMemoryCatalog()
    set_catalog(cat)
    yield cat
    reset_catalog()


def _well_versions(cat: InMemoryCatalog, n: int = 3) -> list[str]:
    ids = []
    for i in range(n):
        ref = cat.register_input(
            name=f"W{i}.las",
            path=f"/tmp/W{i}.las",
            checksum=f"sha-w{i}",
            kind="well_log",
            format="las",
            legacy_resource_id=f"well-{i}",
        )
        ids.append(ref.version_id)
    return ids


def _proj_path(tmp_path: Path) -> Path:
    """Fake .paleo.json path so artifact_dir_for lands under tmp_path sibling."""
    return tmp_path / "demo.paleo.json"


def test_correlation_save_reopen_v2_parent(tmp_path: Path, catalog):
    project = ProjectDocument.new("Corr")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)
    wells = _well_versions(catalog, 3)
    for i, vid in enumerate(wells):
        project.resources.append(
            ResourceItem(
                id=f"well-{i}",
                name=f"W{i}.las",
                path=f"W{i}.las",
                type="well_log",
                format="las",
            )
        )

    tops = [
        FormationTop(
            well_id="well-0", well_name="W0", marker="H1", depth=100.0, depth_domain=DepthDomain.MD
        ),
        FormationTop(
            well_id="well-1", well_name="W1", marker="H1", depth=105.0, depth_domain=DepthDomain.MD
        ),
        FormationTop(
            well_id="well-2", well_name="W2", marker="H1", depth=110.0, depth_domain=DepthDomain.MD
        ),
    ]
    draft = new_correlation_draft(
        name="Section A",
        well_resource_ids=["well-0", "well-1", "well-2"],
        well_version_ids=wells,
        tops=tops,
        depth_domain=DepthDomain.MD,
        framework_ref="H1",
    )
    draft.payload.links.append(
        CorrelationLink(
            top_a_id=tops[0].id,
            top_b_id=tops[1].id,
            well_a_id="well-0",
            well_b_id="well-1",
            method=CorrelationMethod.MANUAL,
        )
    )
    ref1, msg1 = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg1 == "ok"
    assert ref1 is not None
    v1 = ref1.current_version_id
    fp1 = ref1.scientific_fingerprint

    # No-op save
    ref_noop, msg_noop = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg_noop == "noop_unchanged"
    assert ref_noop.current_version_id == v1
    assert len(project.correlation_interpretations) == 1

    # Edit one top → V2
    draft.payload.tops[0].depth = 101.5
    draft.bump()
    ref2, msg2 = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg2 == "ok"
    assert ref2.current_version_id != v1
    assert ref2.parent_version_id == v1
    assert ref2.scientific_fingerprint != fp1

    # Historical + current artifacts under *.artifacts
    arts_root = tmp_path / "demo.artifacts"
    arts = list(arts_root.rglob("*.correlation.json")) if arts_root.is_dir() else []
    if not arts:
        arts = list(tmp_path.parent.glob("**/demo.artifacts/**/*.correlation.json"))
    assert arts, "expected correlation artifacts"
    depths = []
    from paleo_workbench.workflow.correlation_artifact import read_correlation_artifact

    for a in arts:
        pl, _ = read_correlation_artifact(a)
        for t in pl.tops:
            if t.well_id == "well-0" and t.marker == "H1":
                depths.append(t.depth)
    assert 100.0 in depths  # historical V1
    assert 101.5 in depths  # V2

    # Reopen from project ref → working copy
    draft2 = restore_draft_from_project_ref(project, proj_path)
    assert draft2 is not None
    assert any(t.depth == 101.5 for t in draft2.payload.tops if t.well_id == "well-0")
    assert draft2.payload.parent_version_id == ref2.current_version_id


def test_correlation_lineage_inputs(tmp_path: Path, catalog):
    project = ProjectDocument.new("L")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)
    wells = _well_versions(catalog, 2)
    draft = new_correlation_draft(
        well_resource_ids=["a", "b"],
        well_version_ids=wells,
        tops=[
            FormationTop(well_id="a", well_name="A", marker="T", depth=1.0),
            FormationTop(well_id="b", well_name="B", marker="T", depth=2.0),
        ],
    )
    ref, msg = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg == "ok"
    runs = catalog.list_runs()
    corr_runs = [r for r in runs if r.operation == "stratigraphic_correlation"]
    assert corr_runs
    run = corr_runs[-1]
    for vid in wells:
        assert vid in run.input_version_ids
    assert run.domain_task_id == draft.interpretation_id


def test_artifact_does_not_embed_curves(tmp_path: Path, catalog):
    """Artifact size scales with tops/links, not giant curve samples."""
    project = ProjectDocument.new("S")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)
    wells = _well_versions(catalog, 2)
    giant = "x" * 500_000
    draft = new_correlation_draft(
        well_resource_ids=["w0", "w1"],
        well_version_ids=wells,
        tops=[
            FormationTop(well_id="w0", well_name="W0", marker="H", depth=10.0),
            FormationTop(well_id="w1", well_name="W1", marker="H", depth=12.0),
        ],
    )
    assert "samples" not in draft.payload.model_dump()
    ref, msg = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg == "ok"
    arts_root = tmp_path / "demo.artifacts"
    arts = list(arts_root.rglob("*.correlation.json"))
    assert arts
    size = max(a.stat().st_size for a in arts)
    assert size < 50_000, f"artifact too large: {size}"
    text = arts[0].read_text(encoding="utf-8")
    assert giant not in text
    assert "tops" in text


def test_depth_domain_mismatch_detection():
    tops = [
        FormationTop(well_name="A", marker="H", depth=1.0, depth_domain=DepthDomain.MD),
        FormationTop(well_name="B", marker="H", depth=2.0, depth_domain=DepthDomain.TVDSS),
    ]
    domains = detect_depth_domain_mismatch(tops)
    assert set(domains) == {"MD", "TVDSS"}


def test_fault_save_noop_and_v2(tmp_path: Path, catalog):
    project = ProjectDocument.new("F")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)
    draft = new_fault_draft(
        name="F1",
        traces=[
            FaultTrace(
                name="f-a",
                polyline=[[0.0, 0.0], [1.0, 1.0], [2.0, 0.5]],
                role="fault",
            )
        ],
        source_version_ids=[],
        crs="EPSG:4547",
    )
    ref1, m1 = save_fault_draft(draft, project, proj_path, catalog=catalog)
    assert m1 == "ok"
    v1 = ref1.current_version_id
    ref_n, mn = save_fault_draft(draft, project, proj_path, catalog=catalog)
    assert mn == "noop_unchanged"
    assert ref_n.current_version_id == v1

    draft.payload.traces[0].polyline.append([3.0, 0.0])
    draft.bump()
    ref2, m2 = save_fault_draft(draft, project, proj_path, catalog=catalog)
    assert m2 == "ok"
    assert ref2.current_version_id != v1
    assert ref2.parent_version_id == v1

    d2 = restore_fault_draft_from_project(project, proj_path)
    assert d2 is not None
    assert len(d2.payload.traces[0].polyline) == 4


def test_resolve_target_horizon_from_correlation():
    project = ProjectDocument.new("T")
    project.stratigraphy.target_horizon = ""
    from paleo_workbench.project.models import CorrelationInterpretationRef

    project.correlation_interpretations.append(
        CorrelationInterpretationRef(
            name="C", framework_ref="ZJ2", scientific_fingerprint="abc"
        )
    )
    assert resolve_correlation_target_horizon(project) == "ZJ2"
    project.stratigraphy.target_horizon = "H_PRIMARY"
    assert resolve_correlation_target_horizon(project) == "H_PRIMARY"


def test_well_correlation_readiness_needs_two_wells():
    from paleo_workbench.workflow.contracts.readiness import evaluate_readiness
    from paleo_workbench.workflow.contracts.registry import reset_default_registry
    from paleo_workbench.workflow.contracts.models import ReadinessStatus

    reset_default_registry()
    p = ProjectDocument.new("R")
    r = evaluate_readiness(p, "well_correlation")
    assert r.status is ReadinessStatus.BLOCKED
    p.resources.append(
        ResourceItem(name="a.las", path="a.las", type="well_log", format="las")
    )
    r1 = evaluate_readiness(p, "well_correlation")
    assert r1.status is ReadinessStatus.BLOCKED
    p.resources.append(
        ResourceItem(name="b.las", path="b.las", type="well_log", format="las")
    )
    r2 = evaluate_readiness(p, "well_correlation")
    assert r2.status is ReadinessStatus.READY


def test_contract_datarun_ops_include_stage12():
    from paleo_workbench.workflow.contracts.registry import get_default_registry, reset_default_registry
    from paleo_workbench.workflow.contracts.validation import KNOWN_DATARUN_OPERATIONS

    reset_default_registry()
    reg = get_default_registry()
    assert "stratigraphic_correlation" in KNOWN_DATARUN_OPERATIONS
    assert "fault_interpretation" in KNOWN_DATARUN_OPERATIONS
    wc = reg.get_contract("well_correlation")
    assert wc is not None
    assert "stratigraphic_correlation" in wc.datarun_operations
    assert wc.implementation_status.value == "PRODUCTION"
    fi = reg.get_contract("fault_interpretation")
    assert fi is not None
    assert "fault_interpretation" in fi.datarun_operations


def test_tops_from_imported_dict():
    tops = tops_from_imported_dict(
        {"W1": [("H1", 100.0), ("H2", 200.0)]},
        well_name_to_id={"W1": "id1"},
        depth_domain=DepthDomain.MD,
    )
    assert len(tops) == 2
    assert tops[0].well_id == "id1"
    assert tops[0].method is CorrelationMethod.IMPORTED


def test_fingerprint_stable():
    draft = new_correlation_draft(
        tops=[FormationTop(well_name="A", marker="H", depth=1.0)],
        well_version_ids=["v1"],
    )
    a = draft_fingerprint(draft)
    b = draft_fingerprint(draft)
    assert a == b
    draft.payload.tops[0].depth = 2.0
    assert draft_fingerprint(draft) != a


def test_correlation_stale_when_consumed_well_version_changes(tmp_path: Path, catalog):
    """Stage-9: correlation STALE when a consumed well current version advances."""
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.current_context import CurrentProjectVersionContext
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState

    project = ProjectDocument.new("Fresh")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)

    # Well A V1 and V2 same asset; Well B single
    a1 = catalog.register_input(
        name="A.las", path="/t/A.las", checksum="a1", kind="well_log", format="las",
        legacy_resource_id="well-A",
    )
    # Force second version same asset for A
    a2_run = catalog.begin_run(operation="derived_copy", input_version_ids=[a1.version_id])
    a2 = catalog.register_derived(
        run_id=a2_run.run_id,
        name="A v2",
        path="/t/A_v2.las",
        checksum="a2",
        kind="well_log",
        format="las",
    )
    catalog.complete_run(a2_run.run_id)
    a2.asset_id = a1.asset_id  # same logical well

    b1 = catalog.register_input(
        name="B.las", path="/t/B.las", checksum="b1", kind="well_log", format="las",
        legacy_resource_id="well-B",
    )
    # Unrelated well Z
    z1 = catalog.register_input(
        name="Z.las", path="/t/Z.las", checksum="z1", kind="well_log", format="las",
        legacy_resource_id="well-Z",
    )

    draft = new_correlation_draft(
        well_resource_ids=["well-A", "well-B"],
        well_version_ids=[a1.version_id, b1.version_id],
        tops=[
            FormationTop(well_id="well-A", well_name="A", marker="H1", depth=1.0),
            FormationTop(well_id="well-B", well_name="B", marker="H1", depth=2.0),
        ],
    )
    ref, msg = save_correlation_draft(draft, project, proj_path, catalog=catalog)
    assert msg == "ok"
    corr_vid = ref.current_version_id

    graph = DependencyGraph.from_catalog(catalog)
    # Current: A is still V1 → FRESH
    ctx = CurrentProjectVersionContext()
    for ver in catalog.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    ctx.select(a1.asset_id, a1.version_id)  # pin A to V1
    ctx.select(b1.asset_id, b1.version_id)
    svc = FreshnessService(graph, ctx, catalog=catalog)
    assert svc.evaluate_version(corr_vid).state is FreshnessState.FRESH

    # Advance A to V2 as current → correlation STALE
    ctx2 = CurrentProjectVersionContext()
    for ver in catalog.list_versions():
        ctx2.select(ver.asset_id, ver.version_id)
    ctx2.select(a1.asset_id, a2.version_id)
    ctx2.select(b1.asset_id, b1.version_id)
    svc2 = FreshnessService(graph, ctx2, catalog=catalog)
    rep = svc2.evaluate_version(corr_vid)
    assert rep.state is FreshnessState.STALE

    # Unrelated Z change alone: if only Z changes from its own tip, correlation
    # that never consumed Z stays FRESH when A/B still match
    ctx3 = CurrentProjectVersionContext()
    for ver in catalog.list_versions():
        ctx3.select(ver.asset_id, ver.version_id)
    ctx3.select(a1.asset_id, a1.version_id)
    ctx3.select(b1.asset_id, b1.version_id)
    # Z is selected at z1 which is its only version — no impact
    svc3 = FreshnessService(graph, ctx3, catalog=catalog)
    assert svc3.evaluate_version(corr_vid).state is FreshnessState.FRESH
    assert z1.version_id not in draft.payload.well_version_ids


def test_fault_stale_only_when_consumed_as_input(tmp_path: Path, catalog):
    """Fault product FRESH/STALE independent of unrelated correlation."""
    from paleo_workbench.workflow.dependency_graph import DependencyGraph
    from paleo_workbench.workflow.current_context import CurrentProjectVersionContext
    from paleo_workbench.workflow.freshness import FreshnessService, FreshnessState

    project = ProjectDocument.new("F")
    project.meta.project_root = str(tmp_path)
    proj_path = _proj_path(tmp_path)
    draft = new_fault_draft(
        traces=[FaultTrace(name="f", polyline=[[0, 0], [1, 1]], role="fault")],
    )
    ref, msg = save_fault_draft(draft, project, proj_path, catalog=catalog)
    assert msg == "ok"
    graph = DependencyGraph.from_catalog(catalog)
    ctx = CurrentProjectVersionContext()
    for ver in catalog.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    svc = FreshnessService(graph, ctx, catalog=catalog)
    assert svc.evaluate_version(ref.current_version_id).state is FreshnessState.FRESH


def test_ui_page_has_lifecycle_actions():
    """Structural check: correlation page exposes Stage-12 save/open/restore."""
    src = Path("paleo_workbench/ui/pages/stratigraphy_correlation_page.py").read_text(
        encoding="utf-8"
    )
    assert "save_interpretation_version" in src
    assert "open_saved_interpretation" in src
    assert "restore_saved_interpretation" in src
    assert "保存解释版本" in src
    assert "save_correlation_draft" in src
    assert "restore_draft_from_project_ref" in src
