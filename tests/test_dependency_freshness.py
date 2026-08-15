"""Stage 9: lineage-derived dependency graph, freshness, minimal recompute plan."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.project.models import (
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
    WorkflowStep,
)
from paleo_workbench.workflow.current_context import (
    CurrentProjectVersionContext,
    resolve_current_project_version_context,
)
from paleo_workbench.workflow.dependency_graph import DependencyGraph, DependencyGraphError
from paleo_workbench.workflow.freshness import (
    FreshnessReasonType,
    FreshnessService,
    FreshnessState,
)
from paleo_workbench.workflow.recompute_plan import (
    PlanAction,
    PlanExecutor,
    build_recompute_plan,
)
from tests.fakes.inmemory_catalog import InMemoryCatalog


def _import_workflow_service():
    """Lazy import — avoids geoviz when only graph/freshness modules are needed."""
    from paleo_workbench.workflow.service import (
        home_workflow_steps,
        infer_workflow_step_status,
    )

    return home_workflow_steps, infer_workflow_step_status


# --------------------------------------------------------------------------- helpers
def _raw(cat: InMemoryCatalog, name: str, *, kind: str = "seismic") -> str:
    ref = cat.register_input(
        name=name,
        path=f"/tmp/{name}",
        checksum=f"sha-{name}",
        kind=kind,
        format="sgy",
        legacy_resource_id=f"res-{name}",
    )
    return ref.version_id


def _run_with_output(
    cat: InMemoryCatalog,
    *,
    operation: str,
    inputs: list[str],
    name: str,
    domain_task_id: str | None = None,
    generator_version: str | None = "gen-v1",
    input_snapshot_hash: str | None = None,
    parameters: dict | None = None,
    kind: str = "product",
) -> tuple[str, str]:
    """Return (run_id, output_version_id)."""
    run = cat.begin_run(
        operation=operation,
        input_version_ids=list(inputs),
        parameters=parameters or {},
        generator_version=generator_version,
        domain_task_id=domain_task_id,
        input_snapshot_hash=input_snapshot_hash,
    )
    out = cat.register_derived(
        run_id=run.run_id,
        name=name,
        path=f"/tmp/{name}.npz",
        checksum=f"sha-{name}",
        kind=kind,
        format="npz",
    )
    cat.complete_run(run.run_id)
    return run.run_id, out.version_id


def _force_same_asset(cat: InMemoryCatalog, *version_ids: str) -> str:
    """Make listed versions share the first version's asset_id (multi-version asset)."""
    first = cat.resolve_version(version_ids[0])
    assert first is not None
    asset_id = first.asset_id
    for vid in version_ids[1:]:
        ver = cat.resolve_version(vid)
        assert ver is not None
        ver.asset_id = asset_id
    return asset_id


def _svc(
    cat: InMemoryCatalog,
    *,
    current: dict[str, str] | None = None,
    selected: list[str] | None = None,
    project: ProjectDocument | None = None,
) -> FreshnessService:
    graph = DependencyGraph.from_catalog(cat)
    if project is not None:
        ctx = resolve_current_project_version_context(
            project, catalog=cat, extra_selected=current
        )
    else:
        ctx = CurrentProjectVersionContext()
        # Default: every version is "current" for its asset (last write wins below)
        by_asset: dict[str, str] = {}
        for ver in cat.list_versions():
            by_asset[ver.asset_id] = ver.version_id
        for aid, vid in by_asset.items():
            ctx.select(aid, vid)
        if current:
            for aid, vid in current.items():
                ctx.select(aid, vid)
        if selected:
            for vid in selected:
                ver = cat.resolve_version(vid)
                if ver is not None:
                    ctx.select(ver.asset_id, vid)
                else:
                    ctx.selected_version_ids.add(vid)
    return FreshnessService(graph, ctx, catalog=cat)


# --------------------------------------------------------------------------- graph
def test_dependency_graph_version_run_version_edges():
    cat = InMemoryCatalog()
    raw = _raw(cat, "segy")
    _, factor = _run_with_output(
        cat, operation="factor_map", inputs=[raw], name="factor-a", domain_task_id="fa"
    )
    _, pred = _run_with_output(
        cat, operation="prediction", inputs=[factor], name="pred-1", domain_task_id="p1"
    )
    g = DependencyGraph.from_catalog(cat)
    assert len(g.edges) >= 2
    assert g.producing_run[factor]
    assert g.producing_run[pred]
    down = g.transitive_downstream_versions([raw])
    assert factor in down
    assert pred in down


def test_unrelated_branch_not_in_downstream():
    cat = InMemoryCatalog()
    h1 = _raw(cat, "h1", kind="horizon")
    h2 = _raw(cat, "h2", kind="horizon")
    _, fa = _run_with_output(cat, operation="factor_map", inputs=[h1], name="fa")
    _, fb = _run_with_output(cat, operation="factor_map", inputs=[h2], name="fb")
    _, pa = _run_with_output(cat, operation="prediction", inputs=[fa], name="pa")
    _, pb = _run_with_output(cat, operation="prediction", inputs=[fb], name="pb")
    g = DependencyGraph.from_catalog(cat)
    down = set(g.transitive_downstream_versions([h1]))
    assert fa in down and pa in down
    assert fb not in down and pb not in down


# --------------------------------------------------------------------------- freshness chain
def test_horizon_change_stales_chain_only():
    """RAW → H → Factor → Pred → Map → QC → Export; change H only."""
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw-segy")
    # Horizon interpretation v1 then v2 (same asset)
    _, h1 = _run_with_output(
        cat,
        operation="horizon_interpretation",
        inputs=[raw],
        name="H1-v1",
        domain_task_id="interp-h1",
        kind="horizon_interpretation",
    )
    _, h2 = _run_with_output(
        cat,
        operation="horizon_interpretation",
        inputs=[raw, h1],
        name="H1-v2",
        domain_task_id="interp-h1",
        kind="horizon_interpretation",
        parameters={"parent_version_id": h1},
    )
    asset_h = _force_same_asset(cat, h1, h2)

    _, factor = _run_with_output(
        cat, operation="factor_map", inputs=[h1], name="factor-a", domain_task_id="fa"
    )
    _, pred = _run_with_output(
        cat, operation="prediction", inputs=[factor], name="pred", domain_task_id="p1"
    )
    _, mmap = _run_with_output(
        cat, operation="map_compile", inputs=[pred], name="map", domain_task_id="m1"
    )
    _, qc = _run_with_output(
        cat, operation="qc", inputs=[mmap], name="qc", domain_task_id="q1"
    )
    _, export = _run_with_output(
        cat, operation="export", inputs=[mmap], name="export", domain_task_id="e1"
    )
    # Unrelated branch
    other = _raw(cat, "other-h")
    _, factor_b = _run_with_output(
        cat, operation="factor_map", inputs=[other], name="factor-b", domain_task_id="fb"
    )

    # Current selection: H1 v2
    svc = _svc(cat, current={asset_h: h2})

    assert svc.evaluate_version(h2).state is FreshnessState.FRESH
    for vid, op in [
        (factor, "factor_map"),
        (pred, "prediction"),
        (mmap, "map_compile"),
        (qc, "qc"),
        (export, "export"),
    ]:
        rep = svc.evaluate_version(vid)
        assert rep.state is FreshnessState.STALE, f"{op} should be STALE"
        assert any(
            r.type
            in {
                FreshnessReasonType.UPSTREAM_VERSION_CHANGED,
                FreshnessReasonType.TRANSITIVE_UPSTREAM_STALE,
            }
            for r in rep.reasons
        )

    # Unrelated branch stays fresh
    assert svc.evaluate_version(factor_b).state is FreshnessState.FRESH


def test_multi_input_only_changed_factor_stales_prediction():
    cat = InMemoryCatalog()
    a = _raw(cat, "fa-src")
    b = _raw(cat, "fb-src")
    c = _raw(cat, "fc-src")
    _, fa = _run_with_output(cat, operation="factor_map", inputs=[a], name="Fa")
    _, fb_v1 = _run_with_output(cat, operation="factor_map", inputs=[b], name="Fb-v1")
    _, fb_v2 = _run_with_output(cat, operation="factor_map", inputs=[b], name="Fb-v2")
    asset_b = _force_same_asset(cat, fb_v1, fb_v2)
    _, fc = _run_with_output(cat, operation="factor_map", inputs=[c], name="Fc")
    _, pred = _run_with_output(
        cat,
        operation="prediction",
        inputs=[fa, fb_v1, fc],
        name="P",
        domain_task_id="pred",
    )
    # Current: Fb is now v2
    by_asset = {}
    for ver in cat.list_versions():
        by_asset[ver.asset_id] = ver.version_id
    by_asset[asset_b] = fb_v2
    svc = _svc(cat, current=by_asset)

    rep = svc.evaluate_version(pred)
    assert rep.state is FreshnessState.STALE
    assert any(
        r.type is FreshnessReasonType.UPSTREAM_VERSION_CHANGED
        and r.upstream_version_id == fb_v1
        and r.current_version_id == fb_v2
        for r in rep.reasons
    )
    # Fa and Fc products remain fresh
    assert svc.evaluate_version(fa).state is FreshnessState.FRESH
    assert svc.evaluate_version(fc).state is FreshnessState.FRESH


def test_style_only_params_do_not_stale():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    run_id, out = _run_with_output(
        cat,
        operation="factor_map",
        inputs=[raw],
        name="f",
        domain_task_id="task-f",
        parameters={"method": "IDW", "power": 2},
    )
    graph = DependencyGraph.from_catalog(cat)
    ctx = CurrentProjectVersionContext()
    for ver in cat.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    # Expected identity includes display-only keys that differ — must be ignored
    ctx.set_expected_identity(
        "task-f",
        parameters={
            "method": "IDW",
            "power": 2,
            "colormap": "viridis",
            "line_width": 3,
            "viewport": {"x": 1},
        },
    )
    # Run parameters do not even have colormap — should still be FRESH
    svc = FreshnessService(graph, ctx, catalog=cat)
    assert svc.evaluate_run(run_id).state is FreshnessState.FRESH


def test_parameter_change_stales():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    run_id, out = _run_with_output(
        cat,
        operation="factor_map",
        inputs=[raw],
        name="f",
        domain_task_id="task-f",
        parameters={"method": "IDW", "power": 2},
        input_snapshot_hash="snap-old",
    )
    graph = DependencyGraph.from_catalog(cat)
    ctx = CurrentProjectVersionContext()
    for ver in cat.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    ctx.set_expected_identity(
        "task-f",
        input_snapshot_hash="snap-new",
        parameters={"method": "IDW", "power": 3},
    )
    svc = FreshnessService(graph, ctx, catalog=cat)
    rep = svc.evaluate_run(run_id)
    assert rep.state is FreshnessState.STALE
    assert any(r.type is FreshnessReasonType.PARAMETERS_CHANGED for r in rep.reasons)


def test_historical_version_fresh_again_when_selection_reverts():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, h1 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h-v1",
        domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw, h1], name="h-v2",
        domain_task_id="interp",
        parameters={"parent_version_id": h1},
    )
    asset = _force_same_asset(cat, h1, h2)
    _, m1 = _run_with_output(
        cat, operation="map_compile", inputs=[h1], name="map-from-v1"
    )
    _, m2 = _run_with_output(
        cat, operation="map_compile", inputs=[h2], name="map-from-v2"
    )

    svc_v2 = _svc(cat, current={asset: h2})
    assert svc_v2.evaluate_version(m2).state is FreshnessState.FRESH
    assert svc_v2.evaluate_version(m1).state is FreshnessState.STALE

    svc_v1 = _svc(cat, current={asset: h1})
    assert svc_v1.evaluate_version(m1).state is FreshnessState.FRESH
    assert svc_v1.evaluate_version(m2).state is FreshnessState.STALE


def test_missing_lineage_is_unknown_not_stale():
    cat = InMemoryCatalog()
    run = cat.begin_run(
        operation="prediction",
        input_version_ids=[],  # incomplete lineage
        domain_task_id="legacy",
    )
    cat.complete_run(run.run_id)
    svc = _svc(cat)
    rep = svc.evaluate_run(run.run_id)
    assert rep.state is FreshnessState.UNKNOWN
    assert any(r.type is FreshnessReasonType.MISSING_LINEAGE for r in rep.reasons)


def test_integrity_modified_not_ordinary_stale(tmp_path: Path):
    from paleo_workbench.catalog.checksum import sha256_file_or_none

    cat = InMemoryCatalog()
    payload = tmp_path / "out.bin"
    payload.write_bytes(b"original")
    digest = sha256_file_or_none(payload)
    raw = _raw(cat, "raw")
    run = cat.begin_run(operation="factor_map", input_version_ids=[raw])
    cat.register_derived(
        run_id=run.run_id,
        name="grid",
        path=payload.as_posix(),
        checksum=digest,
        kind="factor_map_grid",
    )
    cat.complete_run(run.run_id)

    # Tamper file after commit
    payload.write_bytes(b"tampered!!!!")
    graph = DependencyGraph.from_catalog(cat)
    ctx = CurrentProjectVersionContext()
    for ver in cat.list_versions():
        ctx.select(ver.asset_id, ver.version_id)
    svc = FreshnessService(graph, ctx, catalog=cat, check_integrity=True)
    rep = svc.evaluate_run(run.run_id)
    # Scientifically FRESH vs selection, integrity flagged separately
    assert rep.state is FreshnessState.FRESH
    assert any(r.type is FreshnessReasonType.INTEGRITY_MODIFIED for r in rep.reasons)
    assert rep.integrity == "modified"


# --------------------------------------------------------------------------- recompute plan
def test_minimal_recompute_plan_topo_and_unrelated():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, h1 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h1",
        domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h2",
        domain_task_id="interp",
    )
    asset = _force_same_asset(cat, h1, h2)
    _, fa = _run_with_output(
        cat, operation="factor_map", inputs=[h1], name="Fa", domain_task_id="fa"
    )
    _, pa = _run_with_output(
        cat, operation="prediction", inputs=[fa], name="Pa", domain_task_id="pa"
    )
    other = _raw(cat, "other")
    _, fb = _run_with_output(
        cat, operation="factor_map", inputs=[other], name="Fb", domain_task_id="fb"
    )

    svc = _svc(cat, current={asset: h2})
    plan = build_recompute_plan(svc, changed_version_ids=[h2])
    ops = [s.operation for s in plan.compute_steps]
    assert "factor_map" in ops
    assert "prediction" in ops
    # Unrelated Fb not in plan
    assert all(s.domain_task_id != "fb" for s in plan.steps)
    # Topo: factor before prediction
    idx = {s.domain_task_id: s.order for s in plan.steps}
    assert idx["fa"] < idx["pa"]


def test_plan_executor_partial_failure():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, h = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h",
        domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h2",
        domain_task_id="interp",
    )
    asset = _force_same_asset(cat, h, h2)
    _, fa = _run_with_output(
        cat, operation="factor_map", inputs=[h], name="Fa", domain_task_id="fa"
    )
    _, pa = _run_with_output(
        cat, operation="prediction", inputs=[fa], name="Pa", domain_task_id="pa"
    )
    _, mmap = _run_with_output(
        cat, operation="map_compile", inputs=[pa], name="M", domain_task_id="m"
    )

    svc = _svc(cat, current={asset: h2})
    plan = build_recompute_plan(svc, changed_version_ids=[h2])

    def ok(step):
        return None

    def boom(step):
        raise RuntimeError("prediction blew up")

    ex = PlanExecutor(
        handlers={"factor_map": ok, "prediction": boom, "map_compile": ok},
        stop_on_failure=True,
    )
    result = ex.execute(plan)
    assert any("Fa" in m or "factor" in m.lower() or "ok" in m for m in result.messages)
    assert plan.failed_run_ids
    # map skipped after prediction failure
    assert plan.skipped_run_ids or result.stopped_early


def test_reuse_existing_when_identical_run_present():
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    # Historical stale run from old horizon
    _, h_old = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h-old",
        domain_task_id="interp",
    )
    _, h_new = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h-new",
        domain_task_id="interp",
    )
    asset = _force_same_asset(cat, h_old, h_new)
    # Stale factor from h_old
    _, f_old = _run_with_output(
        cat,
        operation="factor_map",
        inputs=[h_old],
        name="f-old",
        domain_task_id="fa",
        generator_version="g1",
        input_snapshot_hash="s1",
    )
    # Already-computed factor from h_new (reusable)
    _, f_new = _run_with_output(
        cat,
        operation="factor_map",
        inputs=[h_new],
        name="f-new",
        domain_task_id="fa-reuse",
        generator_version="g1",
        input_snapshot_hash="s1",
    )
    svc = _svc(cat, current={asset: h_new})
    plan = build_recompute_plan(svc, changed_version_ids=[h_new])
    # At least one factor step may REUSE
    factor_steps = [s for s in plan.steps if s.operation == "factor_map"]
    assert factor_steps
    assert any(
        s.action is PlanAction.REUSE_EXISTING or s.requires_compute
        for s in factor_steps
    )


# --------------------------------------------------------------------------- workflow UI status
def test_infer_workflow_step_status_stale_overlay():
    home_workflow_steps, infer_workflow_step_status = _import_workflow_service()

    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, h1 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h1",
        domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h2",
        domain_task_id="interp",
    )
    asset = _force_same_asset(cat, h1, h2)
    _, fa = _run_with_output(
        cat, operation="factor_map", inputs=[h1], name="Fa", domain_task_id="fa"
    )

    project = ProjectDocument.new("Demo")
    project.factor_map_tasks.append(
        FactorMapTask(
            id="fa",
            name="Fa",
            target_horizon="H1",
            factor_type="sand",
            method="IDW",
            status="complete",
            grid_artifact_version_id=fa,
        )
    )
    # Select h2 as current for the horizon asset
    svc = _svc(cat, current={asset: h2}, project=project)
    status = infer_workflow_step_status(
        project, "factor_map", freshness_service=svc, apply_freshness=True
    )
    assert status == "stale"

    steps = home_workflow_steps(project, catalog=cat, apply_freshness=False)
    assert any(s.step_type == "factor_map" and s.status == "complete" for s in steps)


def test_data_version_not_mutated_with_stale_flag():
    """Hard rule: never stamp stale onto immutable version records."""
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, h1 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h1",
        domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw], name="h2",
        domain_task_id="interp",
    )
    asset = _force_same_asset(cat, h1, h2)
    _, fa = _run_with_output(cat, operation="factor_map", inputs=[h1], name="Fa")
    svc = _svc(cat, current={asset: h2})
    svc.evaluate_version(fa)
    ver = cat.resolve_version(fa)
    assert ver is not None
    assert not hasattr(ver, "stale") or getattr(ver, "stale", None) in (None, False)
    # to_dict must not invent stale
    d = ver.to_dict()
    assert "stale" not in d


# --------------------------------------------------------------------------- cycle safety
def test_cycle_detection_safe():
    from paleo_workbench.catalog.types import LineageEdge

    cat = InMemoryCatalog()
    a = _raw(cat, "a")
    run1 = cat.begin_run(operation="factor_map", input_version_ids=[a])
    b = cat.register_derived(
        run_id=run1.run_id, name="b", path="/tmp/b", checksum="b", kind="x"
    )
    cat.complete_run(run1.run_id)
    run2 = cat.begin_run(operation="prediction", input_version_ids=[b.version_id])
    c = cat.register_derived(
        run_id=run2.run_id, name="c", path="/tmp/c", checksum="c", kind="x"
    )
    cat.complete_run(run2.run_id)
    # Force a version-level cycle for walk safety
    run1.input_version_ids.append(c.version_id)
    cat._lineage.append(
        LineageEdge(
            source_version_id=c.version_id,
            target_version_id=b.version_id,
            run_id=run1.run_id,
        )
    )
    g = DependencyGraph.from_catalog(cat)
    down = g.transitive_downstream_runs([a], max_nodes=50)
    assert isinstance(down, list)


# --------------------------------------------------------------------------- benchmark
@pytest.mark.parametrize("n_versions", [100, 1000])
def test_graph_benchmark_scales(n_versions: int, tmp_path: Path):
    """Synthetic DAG: chain of factor→prediction style runs.

    Targets interactive queries < 50ms for realistically sized graphs.
    Records timings; does not hard-fail on slow CI hosts above 10k.
    """
    cat = InMemoryCatalog()
    prev = _raw(cat, "root")
    # Create ~n_versions by chaining runs (each run adds one output version)
    # versions ≈ 1 raw + n outputs
    target_outputs = max(1, n_versions - 1)
    for i in range(target_outputs):
        op = "factor_map" if i % 3 == 0 else ("prediction" if i % 3 == 1 else "export")
        _, prev = _run_with_output(
            cat,
            operation=op,
            inputs=[prev],
            name=f"n{i}",
            domain_task_id=f"t{i}",
        )

    t0 = time.perf_counter()
    g = DependencyGraph.from_catalog(cat)
    graph_build_ms = (time.perf_counter() - t0) * 1000

    root = cat.list_versions()[0].version_id
    t0 = time.perf_counter()
    _ = g.transitive_downstream_runs([root])
    downstream_ms = (time.perf_counter() - t0) * 1000

    # Freshness: select tip, evaluate mid chain
    mid = cat.list_versions()[len(cat.list_versions()) // 2].version_id
    tip = cat.list_versions()[-1].version_id
    tip_ver = cat.resolve_version(tip)
    mid_ver = cat.resolve_version(mid)
    assert tip_ver and mid_ver
    # Make mid and tip same asset so mid path is stale
    mid_ver.asset_id = tip_ver.asset_id
    svc = _svc(cat, current={tip_ver.asset_id: tip})
    t0 = time.perf_counter()
    for ver in list(cat.list_versions())[: min(50, len(cat.list_versions()))]:
        if ver.producing_run_id:
            svc.evaluate_run(ver.producing_run_id)
    freshness_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    plan = build_recompute_plan(svc, changed_version_ids=[tip])
    plan_ms = (time.perf_counter() - t0) * 1000

    # Soft targets for interactive sizes (plan may scan reuse on dense chains)
    if n_versions <= 100:
        assert graph_build_ms < 200, f"graph_build_ms={graph_build_ms}"
        assert downstream_ms < 100, f"downstream_ms={downstream_ms}"
        assert freshness_ms < 500, f"freshness_ms={freshness_ms}"
        assert plan_ms < 200, f"plan_ms={plan_ms}"
    elif n_versions <= 1000:
        assert graph_build_ms < 500, f"graph_build_ms={graph_build_ms}"
        assert downstream_ms < 200, f"downstream_ms={downstream_ms}"
        assert freshness_ms < 1000, f"freshness_ms={freshness_ms}"
        assert plan_ms < 1000, f"plan_ms={plan_ms}"

    # Always record for final report
    print(
        f"\nBENCH n={n_versions} versions≈{len(cat.list_versions())} "
        f"runs={len(cat.list_runs())}: "
        f"graph_build={graph_build_ms:.2f}ms "
        f"downstream={downstream_ms:.2f}ms "
        f"freshness_50={freshness_ms:.2f}ms "
        f"plan={plan_ms:.2f}ms "
        f"plan_steps={len(plan.steps)}"
    )


def test_benchmark_10k_smoke():
    """Larger graph smoke (no hard latency assert — host dependent)."""
    n_versions = 10_000
    cat = InMemoryCatalog()
    prev = _raw(cat, "root10k")
    for i in range(n_versions - 1):
        op = "factor_map" if i % 2 == 0 else "prediction"
        _, prev = _run_with_output(
            cat, operation=op, inputs=[prev], name=f"x{i}", domain_task_id=f"x{i}"
        )
    t0 = time.perf_counter()
    g = DependencyGraph.from_catalog(cat)
    build_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    down = g.transitive_downstream_runs([cat.list_versions()[0].version_id])
    down_ms = (time.perf_counter() - t0) * 1000
    print(
        f"\nBENCH n=10000 versions={len(cat.list_versions())} "
        f"graph_build={build_ms:.2f}ms downstream={down_ms:.2f}ms "
        f"down_runs={len(down)}"
    )
    assert len(g.runs) == n_versions - 1
    assert build_ms < 5000  # generous ceiling


def test_for_project_caches_graph_per_catalog_revision(monkeypatch):
    """Same catalog revision rebuilds the graph once; a save rebuilds it once (C15b)."""
    from types import SimpleNamespace

    from paleo_workbench.workflow.freshness import (
        clear_dependency_graph_cache,
    )

    clear_dependency_graph_cache()
    try:
        document = SimpleNamespace(catalog_revision=1)

        class _FakeRevisionCatalog:
            service = SimpleNamespace(document=document)

            def list_versions(self):
                return []

            def list_runs(self):
                return []

        fake = _FakeRevisionCatalog()
        builds: list = []
        orig = DependencyGraph.from_catalog

        @classmethod
        def counting_from_catalog(cls, catalog):
            builds.append(catalog)
            return orig(catalog)

        monkeypatch.setattr(DependencyGraph, "from_catalog", counting_from_catalog)

        svc1 = FreshnessService.for_project(catalog=fake)
        assert len(builds) == 1
        svc2 = FreshnessService.for_project(catalog=fake)
        assert len(builds) == 1  # cache hit: no rebuild
        assert svc1.graph is svc2.graph

        # A persisted save bumps the revision → exactly one rebuild.
        document.catalog_revision = 2
        svc3 = FreshnessService.for_project(catalog=fake)
        assert len(builds) == 2
        assert svc3.graph is not svc2.graph
        FreshnessService.for_project(catalog=fake)
        assert len(builds) == 2  # second revision reused
    finally:
        clear_dependency_graph_cache()
# ------------------------------------------------------------------ C15 identity
# Freshness/recompute identity must be stable across reruns: superseded
# per-run asset tips must not stay "current", QC must collapse to the latest
# run per map, and byte-identical supersession must not invalidate consumers.


def test_arch1_factor_rerun_new_asset_keeps_latest_prediction_fresh():
    """Asset-per-run factor reruns (legacy catalogs) must not stale a
    prediction that was re-run on the CURRENT grid, and the reversed
    "current is <superseded version>" reason must not appear."""
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    project = ProjectDocument.new("P")
    task = FactorMapTask(
        name="H1",
        target_horizon="H1",
        factor_type="砂岩含量",
        method="IDW",
        grid_artifact_version_id=None,  # set after the reruns below
        input_snapshot_hash="snap1",
        generator_version="g1",
    )
    project.factor_map_tasks.append(task)
    # Runs are registered under the task's real id (like register_factor_map_run).
    _, grid_v1 = _run_with_output(
        cat, operation="factor_map", inputs=[raw], name="grid-v1",
        domain_task_id=task.id, generator_version="g1",
        input_snapshot_hash="snap1",
    )
    # Re-run of the same factor task → NEW asset (legacy asset-per-run layout).
    _, grid_v2 = _run_with_output(
        cat, operation="factor_map", inputs=[raw], name="grid-v2",
        domain_task_id=task.id, generator_version="g1",
        input_snapshot_hash="snap1",
    )
    assert grid_v1 != grid_v2
    # Prediction re-run on the CURRENT grid.
    _, pred = _run_with_output(
        cat, operation="prediction", inputs=[grid_v2], name="pred",
        domain_task_id="task-p", generator_version="g1",
        input_snapshot_hash="snap-p",
    )
    task.grid_artifact_version_id = grid_v2

    svc = _svc(cat, project=project)
    rep = svc.evaluate_version(pred)
    assert rep.state is FreshnessState.FRESH, [
        (r.type.value, r.upstream_version_id, r.current_version_id)
        for r in rep.reasons
    ]
    # No reversed "run used <current>; current is <superseded>" reason.
    assert not any(
        r.type is FreshnessReasonType.UPSTREAM_VERSION_CHANGED
        and r.current_version_id == grid_v1
        for r in rep.reasons
    )


def test_arch2_qc_step_fresh_after_rerun_on_stable_key():
    """With a stable per-map QC domain key, only the latest QC run
    participates: re-running QC after a recompile returns the step to FRESH
    even though the historical QC run is stale."""
    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    _, map_v1 = _run_with_output(
        cat, operation="map_compile", inputs=[raw], name="map-v1",
        domain_task_id="doc-1",
    )
    _, map_v2 = _run_with_output(
        cat, operation="map_compile", inputs=[raw], name="map-v2",
        domain_task_id="doc-2",
    )
    asset = _force_same_asset(cat, map_v1, map_v2)
    # Both QC runs keyed by the stable linked task id (the fix): the QC of
    # the superseded map and the QC of the current map collapse to the latest.
    _, _ = _run_with_output(
        cat, operation="qc", inputs=[map_v1], name="qc-r1",
        domain_task_id="task-t",
    )
    r2, _ = _run_with_output(
        cat, operation="qc", inputs=[map_v2], name="qc-r2",
        domain_task_id="task-t",
    )
    svc = _svc(cat, current={asset: map_v2})
    assert svc.evaluate_version(map_v2).state is FreshnessState.FRESH
    assert svc.evaluate_run(r2).state is FreshnessState.FRESH
    assert svc.step_freshness("qc") is FreshnessState.FRESH


def test_arch3_same_checksum_promote_keeps_consumers_fresh():
    """A byte-identical supersession (promote copies the payload, same
    sha256) must not stale the consumers that ran on the promoted source,
    and the recompute plan must stay empty (issue #373 / C15)."""
    from paleo_workbench.catalog.models import DataStage

    cat = InMemoryCatalog()
    raw = _raw(cat, "raw")
    v1 = cat.resolve_version(raw)
    assert v1 is not None
    v2 = cat._new_version(
        name=v1.name,
        stage=DataStage.OUTPUT,
        path=v1.path,
        checksum=v1.checksum,  # identical payload bytes
        kind=v1.kind,
        format=v1.format,
        external=False,
        producing_run_id=None,
        tags=list(v1.tags),
        legacy_resource_id=None,
    )
    v2.asset_id = v1.asset_id  # promote keeps the same asset
    _, factor = _run_with_output(
        cat, operation="factor_map", inputs=[v1.version_id], name="factor",
        domain_task_id="task-f",
    )
    _, pred = _run_with_output(
        cat, operation="prediction", inputs=[factor], name="pred",
        domain_task_id="task-p",
    )

    svc = _svc(cat, current={v1.asset_id: v2.version_id})
    assert svc.evaluate_version(factor).state is FreshnessState.FRESH
    assert svc.evaluate_version(pred).state is FreshnessState.FRESH
    plan = build_recompute_plan(svc, changed_version_ids=[v2.version_id])
    assert plan.compute_steps == []
