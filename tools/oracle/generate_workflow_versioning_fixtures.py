#!/usr/bin/env python3
"""Oracle fixture generator for workflow versioning (CONV-33 route A2).

Imports the REAL implementation (paleo_workbench.workflow.versioning +
paleo_workbench.project.models) and freezes its outputs so the C++ port in
libs/workflow_runtime can be verified against the Python chain.
Regenerate with:

    python3 tools/oracle/generate_workflow_versioning_fixtures.py

Deterministic (a re-run must be byte-identical):
  * ids:   paleo_workbench.project.models._id monkeypatched to a counter
           "{prefix}_{n:012d}" — pydantic id factories are lambdas that
           resolve the module global at CALL time, so the patch reaches
           model construction.
  * now:   every _now_iso default_factory (captured function object, NOT
           reached via the module attribute) is replaced on the FieldInfo
           + model_rebuild(force=True); versioning.py's direct _now_iso
           binding is patched separately. Counter stamps
           "2020-01-01T00:00:{n:02d}+00:00".
  * the C++ replay seeds its ModelClock counters from each case's
    "clock" = {id_consumed, now_consumed} so make_id/now_iso fire in the
    SAME order the Python call did (pydantic factories fire in
    field-declaration order — frozen by these fixtures).

25 cases (see main()): build_snapshot (rich / no qc+no draft / empty
horizon → all tasks), finalize happy path (fresh set, review_required →
export_ready, qc linked), supersede chain (two finalizes, same horizon),
six gate rejections (unknown map / demo draft / untracked lineage /
non-production / qc not run / qc failed status with ORIGINAL status in
the message), require_qc_pass with passing qc (no runs / no draft),
existing-open-set reuse (+ multi-set supersede, H2 final untouched),
active_final_snapshot (last final / horizon hit with active-id
resolution / miss / blank + dangling active id 末位 fallback / no
snapshots / empty project), version_set_summary (mixed / empty), DTO
roundtrips (five models, None → null, key sets), fingerprint bytes
(rich float repr + nested sort_keys + ensure_ascii=False / empty /
minimal). Generator self-checks: fingerprint replica == the real
content_fingerprint for every produced snapshot; get_catalog() is None
(sink path genuinely skipped, ≙ finalize_sink nullptr).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({ROOT}) — oracle must import the real tree"
)

# -- determinism patches (before any model instantiation) --------------------

from paleo_workbench.project import models as pm  # noqa: E402

_ORIG_NOW = pm._now_iso
_STATE = {"id": 0, "now": 0}


def _fake_now() -> str:
    _STATE["now"] += 1
    return f"2020-01-01T00:00:{_STATE['now']:02d}+00:00"


def _fake_id(prefix: str) -> str:
    _STATE["id"] += 1
    return f"{prefix}_{_STATE['id']:012d}"


pm._now_iso = _fake_now
pm._id = _fake_id

_REBUILT: list[str] = []
for _name, _model in list(vars(pm).items()):
    if (
        isinstance(_model, type)
        and issubclass(_model, pm.BaseModel)
        and _model.__module__ == pm.__name__
    ):
        _changed = False
        for _field in _model.model_fields.values():
            if _field.default_factory is _ORIG_NOW:
                _field.default_factory = _fake_now
                _changed = True
        if _changed:
            _model.model_rebuild(force=True)
            _REBUILT.append(_name)

from paleo_workbench.workflow import versioning as _versioning  # noqa: E402

_versioning._now_iso = _fake_now

from paleo_workbench.catalog import get_catalog  # noqa: E402
from paleo_workbench.workflow.versioning import (  # noqa: E402
    active_final_snapshot,
    build_snapshot,
    finalize_map_version,
    version_set_summary,
)

assert get_catalog() is None, (
    "a runtime catalog is configured — the finalize sink path would not "
    "be the nullptr-skip path this fixture freezes"
)

OUT = (
    ROOT
    / "libs"
    / "workflow_runtime"
    / "workflow_runtime_tests"
    / "fixtures"
    / "workflow_versioning_oracle.json"
)
T0 = "2020-01-01T00:00:00+00:00"

CASES: list[dict] = []


def reset_clock() -> None:
    _STATE["id"] = 0
    _STATE["now"] = 0


def clock() -> dict:
    return {"id_consumed": _STATE["id"], "now_consumed": _STATE["now"]}


# Pre-call counter state (what the C++ ModelClock must be seeded with).
# mark_seed() is called right BEFORE each frozen operation; inputs are
# built with explicit ids/timestamps so the seed is the reset state, but
# this stays correct even if a future case consumes factories in setup.
_SEED = {"id_consumed": 0, "now_consumed": 0}


def mark_seed() -> None:
    global _SEED
    _SEED = clock()


def add(case_id: str, fn: str, input_view: dict, expect: dict) -> None:
    CASES.append(
        {"id": case_id, "fn": fn, "clock": dict(_SEED), "input": input_view,
         "expect": expect}
    )


def fingerprint_raw(doc) -> str:
    """Replica of versioning._fingerprint_map's dumps input (self-checked
    against the real content_fingerprint for every produced snapshot)."""
    payload = {
        "id": doc.id,
        "horizon": doc.linked_target_horizon,
        "facies": doc.facies_polygons,
        "lines": doc.line_features,
        "wells": doc.well_overlays,
        "labels": doc.label_features,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def check_fingerprint(doc, fingerprint: str) -> None:
    raw = fingerprint_raw(doc)
    fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    assert fp == fingerprint, (
        f"fingerprint replica diverged: {fp} != {fingerprint}"
    )


def base_project(**sections) -> pm.ProjectDocument:
    return pm.ProjectDocument(
        meta=pm.ProjectMeta(
            name="oracle", created_at=T0, updated_at=T0
        ),
        **sections,
    )


def prod_map(
    mid: str = "map_fix1",
    horizon: str = "H1",
    draft_id: str | None = "cd_fix1",
    rich: bool = False,
    view_state: dict | None = None,
) -> pm.PaleoMapDocument:
    extra: dict = {}
    if rich:
        extra = rich_features()
    if view_state is not None:
        extra["view_state"] = view_state
    else:
        extra["view_state"] = {"production": True, "lineage": "catalog"}
    return pm.PaleoMapDocument(
        id=mid,
        name=f"{horizon or '总'} 沉积相图",
        linked_target_horizon=horizon,
        linked_contour_draft_id=draft_id,
        **extra,
    )


def rich_features() -> dict:
    """Feature payloads that pin the fingerprint byte format: nested
    sort_keys, Python float repr edge cases, int/bool/None mixing, raw
    UTF-8 (ensure_ascii=False), escaped quote."""
    return {
        "facies_polygons": [
            # key order deliberately unsorted at depth 2 and 3
            {"zeta": 1, "alpha": 2.5,
             "nested": {"k2": [0.5], "k1": {"b": True, "a": None}}},
            {"id": "facies-2", "name": "辫状河", "active": False,
             "area_km2": 12.5},
        ],
        "line_features": [
            {"type": "Feature",
             "properties": {"role": "断层线", "置信度": 0.30000000000000004},
             "geometry": {"type": "LineString",
                          "coordinates": [[0.5, 1.5], [2.5, -0.5],
                                          [1e16, 1.5e-05]]}},
            {"type": "Feature",
             "properties": {"长度": 3, "备注": "引号\"测试"},
             "geometry": {"type": "LineString",
                          "coordinates": [[1, 2], [3, 4]]}},
        ],
        "well_overlays": [
            {"id": "well-1", "visible": True, "q": 1.0, "notes": None},
            {"id": "well-2", "visible": False, "depth_m": -0.0},
        ],
        "label_features": [
            {"text": "盆地相带：A", "x": -0.0, "y": 5e-324, "level": 0},
            {"text": "", "empty_list": [], "empty_dict": {}},
        ],
    }


def qc_report(rid: str, map_id: str, status: str) -> pm.QualityReport:
    return pm.QualityReport(
        id=rid, linked_map_document_id=map_id, rules=["basic"], issues=[],
        status=status, generated_at=T0,
    )


def contour_draft(did: str = "cd_fix1", segments: int = 2) -> pm.ContourDraft:
    return pm.ContourDraft(
        id=did, name="draft", target_horizon="H1", factor_type="sand",
        linked_factor_task_id="factor_fix1", linked_map_document_id=None,
        levels=[10.0, 20.5],
        segments=[
            pm.ContourSegment(
                id=f"cseg_fix{i}", level=10.0 + i * 10.5,
                coordinates=[[float(i), 0.5], [2.5, -0.5]], closed=(i % 2 == 0),
            )
            for i in range(segments)
        ],
        source_grid_n=64, source_backend="numpy",
        source_value_range=[-12.5, 30.25],
        created_at=T0, updated_at=T0,
    )


def compilation_run(status: str = "review_required") -> pm.CompilationRun:
    return pm.CompilationRun(
        id="run_fix1", name="编图 run", target_horizon="H1",
        sequence_scheme_ref="LST/TST/HST", status=status,
        workflow_steps=[
            pm.WorkflowStep(id="step_fix1", step_type="map_compile",
                            status="complete"),
        ],
        active_factor_map_task_ids=["factor_fix1"],
        created_at=T0, updated_at=T0,
    )


def factor_task(tid: str, horizon: str) -> pm.FactorMapTask:
    return pm.FactorMapTask(
        id=tid, name=f"task-{tid}", target_horizon=horizon,
        factor_type="sand", method="idw",
    )


def seeded_snap(sid: str, note: str = "seed") -> pm.VersionSnapshot:
    return pm.VersionSnapshot(
        id=sid, map_document_id="map_seed", note=note,
        content_fingerprint="seed00000000000f", created_at=T0,
    )


def seeded_vset(vid: str, horizon: str, status: str,
                snaps: list[pm.VersionSnapshot] | None = None,
                active: str | None = None,
                finalized_at: str | None = None) -> pm.VersionSet:
    return pm.VersionSet(
        id=vid, name=f"{horizon or '未指定层位'} 定稿版本集",
        target_horizon=horizon, status=status, snapshots=snaps or [],
        active_snapshot_id=active, finalized_by="",
        finalized_at=finalized_at, linked_compilation_run_id=None,
        created_at=T0, updated_at=T0,
    )


def capture_finalize(project, map_id, *, note="", operator="expert",
                     require_qc_pass=False):
    try:
        vset = finalize_map_version(
            project, map_id, note=note, operator=operator,
            require_qc_pass=require_qc_pass,
        )
        return {"ok": True, "version_set": vset.model_dump()}
    except ValueError as exc:
        return {"ok": False, "raise": {"python_class": "ValueError",
                                       "message": str(exc)}}


def main() -> None:
    # -- 1-3: build_snapshot ------------------------------------------------
    reset_clock()
    doc = prod_map(rich=True)
    qc_old = qc_report("qc_fixA", "map_fix1", "warning")
    qc_other = qc_report("qc_fixB", "map_other", "failed")
    qc_last = qc_report("qc_fixC", "map_fix1", "passed")
    proj = base_project(
        paleomap_documents=[doc], contour_drafts=[contour_draft()],
        quality_reports=[qc_old, qc_other, qc_last],
        factor_map_tasks=[factor_task("factor_fix1", "H1"),
                          factor_task("factor_fix2", "H2"),
                          factor_task("factor_fix3", "H1")],
    )
    input_view = proj.model_dump()
    mark_seed()
    snap = build_snapshot(proj, doc, note="初版定稿", created_by="李专家")
    check_fingerprint(doc, snap.content_fingerprint)
    assert snap.qc_status == "passed" and snap.quality_report_id == "qc_fixC"
    assert snap.contour_segment_count == 2
    assert snap.factor_task_ids == ["factor_fix1", "factor_fix3"]
    add("build_snapshot_rich", "build_snapshot",
        {"project": input_view, "map_doc": doc.model_dump(),
         "note": "初版定稿", "created_by": "李专家"},
        {"snapshot": snap.model_dump()})

    reset_clock()
    doc = prod_map(draft_id=None, horizon="H2")
    proj = base_project(paleomap_documents=[doc])
    input_view = proj.model_dump()
    mark_seed()
    snap = build_snapshot(proj, doc)
    check_fingerprint(doc, snap.content_fingerprint)
    assert snap.qc_status == "unchecked" and snap.quality_report_id is None
    assert snap.contour_draft_id is None and snap.contour_segment_count == 0
    add("build_snapshot_unchecked_no_draft", "build_snapshot",
        {"project": input_view, "map_doc": doc.model_dump(),
         "note": "", "created_by": ""},
        {"snapshot": snap.model_dump()})

    reset_clock()
    doc = prod_map(horizon="", draft_id=None)
    proj = base_project(
        paleomap_documents=[doc],
        factor_map_tasks=[factor_task("factor_fix1", "H1"),
                          factor_task("factor_fix2", ""),
                          factor_task("factor_fix3", "H2")],
    )
    input_view = proj.model_dump()
    mark_seed()
    snap = build_snapshot(proj, doc, note="全部任务", created_by="q")
    check_fingerprint(doc, snap.content_fingerprint)
    assert snap.factor_task_ids == ["factor_fix1", "factor_fix2", "factor_fix3"]
    add("build_snapshot_empty_horizon_all_tasks", "build_snapshot",
        {"project": input_view, "map_doc": doc.model_dump(),
         "note": "全部任务", "created_by": "q"},
        {"snapshot": snap.model_dump()})

    # -- 4: finalize happy path (fresh set) ----------------------------------
    reset_clock()
    doc = prod_map(rich=True)
    qc = qc_report("qc_fix1", "map_fix1", "passed")
    proj = base_project(
        paleomap_documents=[doc], contour_drafts=[contour_draft()],
        compilation_runs=[compilation_run("review_required")],
        quality_reports=[qc],
        factor_map_tasks=[factor_task("factor_fix1", "H1"),
                          factor_task("factor_fix2", "H2")],
    )
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", note="初版定稿",
                           operator="李专家")
    assert out["ok"]
    check_fingerprint(doc, out["version_set"]["snapshots"][0]["content_fingerprint"])
    assert proj.contour_drafts[0].status == "final"
    assert proj.compilation_runs[0].status == "export_ready"
    assert proj.compilation_runs[0].active_paleomap_document_id == "map_fix1"
    assert proj.compilation_runs[0].active_quality_report_id == "qc_fix1"
    add("finalize_happy_fresh_set", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "初版定稿", "operator": "李专家",
                     "require_qc_pass": False}},
        {"version_set": out["version_set"], "project": proj.model_dump()})

    # -- 5: supersede chain (two finalizes, same horizon) --------------------
    reset_clock()
    doc1 = prod_map(mid="map_fix1", rich=True)
    doc2 = prod_map(mid="map_fix2")
    qc = qc_report("qc_fix1", "map_fix1", "passed")  # linked to map1 only
    proj = base_project(
        paleomap_documents=[doc1, doc2],
        contour_drafts=[contour_draft()],
        compilation_runs=[compilation_run("draft")],
        quality_reports=[qc],
        factor_map_tasks=[factor_task("factor_fix1", "H1")],
    )
    input_view = proj.model_dump()
    steps = []
    mark_seed()
    out1 = capture_finalize(proj, "map_fix1", note="一签",
                            operator="专家A")
    assert out1["ok"]
    steps.append({"version_set": out1["version_set"],
                  "project": proj.model_dump()})
    out2 = capture_finalize(proj, "map_fix2", note="二签",
                            operator="专家B")
    assert out2["ok"]
    steps.append({"version_set": out2["version_set"],
                  "project": proj.model_dump()})
    check_fingerprint(doc1, steps[0]["version_set"]["snapshots"][0]["content_fingerprint"])
    check_fingerprint(doc2, steps[1]["version_set"]["snapshots"][0]["content_fingerprint"])
    statuses = [(v.id, v.status) for v in proj.version_sets]
    assert statuses == [("vset_000000000001", "superseded"),
                        ("vset_000000000003", "final")], statuses
    run = proj.compilation_runs[0]
    assert run.active_paleomap_document_id == "map_fix2"
    assert run.active_quality_report_id == "qc_fix1"  # map2 has no qc → kept
    add("finalize_supersede_chain", "finalize_map_version_steps",
        {"project": input_view,
         "steps": [
             {"map_document_id": "map_fix1",
              "options": {"note": "一签", "operator": "专家A",
                          "require_qc_pass": False}},
             {"map_document_id": "map_fix2",
              "options": {"note": "二签", "operator": "专家B",
                          "require_qc_pass": False}},
         ]},
        {"steps": steps})

    # -- 6-9: gate rejections (project must stay unchanged) ------------------
    def gate_case(case_id: str, view_state: dict, expect_message: str) -> None:
        reset_clock()
        doc = prod_map(mid="map_fix1", view_state=view_state)
        proj = base_project(
            paleomap_documents=[doc], contour_drafts=[contour_draft()],
            compilation_runs=[compilation_run()],
            factor_map_tasks=[factor_task("factor_fix1", "H1")],
        )
        input_view = proj.model_dump()
        mark_seed()
        out = capture_finalize(proj, "map_fix1")
        assert not out["ok"]
        assert out["raise"]["message"] == expect_message, out["raise"]
        assert proj.model_dump() == input_view
        add(case_id, "finalize_map_version",
            {"project": input_view, "map_document_id": "map_fix1",
             "options": {"note": "", "operator": "expert",
                         "require_qc_pass": False}},
            {"raise": out["raise"], "project_unchanged": True})

    gate_case(
        "finalize_gate_demo_draft",
        {"is_demo_draft": True, "production": True},
        "演示草稿图不能专家定稿为生产成果；请先通过生产编图路径生成正式图件",
    )
    gate_case(
        "finalize_gate_untracked_lineage",
        {"production": False, "lineage": "untracked"},
        "该成果的 lineage 未登记（无目录），不能专家定稿；请重新打开目录后通过生产编图生成",
    )
    gate_case(
        "finalize_gate_non_production",
        {"production": False, "lineage": "catalog"},
        "非生产成果不能专家定稿为正式图件",
    )

    # unknown map id (gate 0)
    reset_clock()
    doc = prod_map()
    proj = base_project(paleomap_documents=[doc])
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_nope")
    assert not out["ok"]
    assert out["raise"]["message"] == "unknown map document: map_nope"
    assert proj.model_dump() == input_view
    add("finalize_gate_unknown_map", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_nope",
         "options": {"note": "", "operator": "expert",
                     "require_qc_pass": False}},
        {"raise": out["raise"], "project_unchanged": True})

    # production: 0 is NOT False — gate must NOT trip (strict `is False`)
    reset_clock()
    doc = prod_map(mid="map_fix1",
                   view_state={"production": 0, "lineage": "catalog"})
    proj = base_project(
        paleomap_documents=[doc], contour_drafts=[contour_draft()],
        factor_map_tasks=[factor_task("factor_fix1", "H1")],
    )
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", note="零值不拦")
    assert out["ok"], out
    add("finalize_production_int_zero_passes", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "零值不拦", "operator": "expert",
                     "require_qc_pass": False}},
        {"version_set": out["version_set"], "project": proj.model_dump()})

    # -- 10-11: require_qc_pass gates ----------------------------------------
    reset_clock()
    doc = prod_map()
    proj = base_project(paleomap_documents=[doc])
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", require_qc_pass=True)
    assert not out["ok"]
    assert out["raise"]["message"] == "定稿前需先运行质检"
    assert proj.model_dump() == input_view
    add("finalize_gate_qc_not_run", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "", "operator": "expert",
                     "require_qc_pass": True}},
        {"raise": out["raise"], "project_unchanged": True})

    reset_clock()
    doc = prod_map()
    # status "Error" pins the .lower() membership + ORIGINAL interpolation
    qc = qc_report("qc_fix1", "map_fix1", "Error")
    proj = base_project(paleomap_documents=[doc], quality_reports=[qc])
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", require_qc_pass=True)
    assert not out["ok"]
    assert out["raise"]["message"] == "质检未通过（status=Error），不能定稿"
    assert proj.model_dump() == input_view
    add("finalize_gate_qc_failed_status", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "", "operator": "expert",
                     "require_qc_pass": True}},
        {"raise": out["raise"], "project_unchanged": True})

    # -- 12: require_qc_pass ok (no runs / no draft path) --------------------
    reset_clock()
    doc = prod_map(draft_id=None, rich=True)
    qc = qc_report("qc_fix1", "map_fix1", "passed")
    proj = base_project(paleomap_documents=[doc], quality_reports=[qc],
                        factor_map_tasks=[factor_task("factor_fix1", "H1")])
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", note="质检通过后定稿",
                           operator="专家C", require_qc_pass=True)
    assert out["ok"]
    vset = out["version_set"]
    check_fingerprint(doc, vset["snapshots"][0]["content_fingerprint"])
    assert vset["linked_compilation_run_id"] is None
    add("finalize_require_qc_pass_ok", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "质检通过后定稿", "operator": "专家C",
                     "require_qc_pass": True}},
        {"version_set": vset, "project": proj.model_dump()})

    # -- 13: existing open set reuse + multi-set supersede -------------------
    reset_clock()
    doc = prod_map()
    open_set = seeded_vset("vset_seed1", "H1", "open",
                           snaps=[seeded_snap("vsnap_seed1")],
                           active="vsnap_seed1")
    old_final_1 = seeded_vset("vset_seed2", "H1", "final",
                              snaps=[seeded_snap("vsnap_seed2")],
                              active="vsnap_seed2", finalized_at=T0)
    old_final_2 = seeded_vset("vset_seed3", "H1", "final",
                              snaps=[seeded_snap("vsnap_seed3")],
                              active="vsnap_seed3", finalized_at=T0)
    other_horizon = seeded_vset("vset_seed4", "H2", "final",
                                snaps=[seeded_snap("vsnap_seed4")],
                                active="vsnap_seed4", finalized_at=T0)
    proj = base_project(
        paleomap_documents=[doc], contour_drafts=[contour_draft()],
        compilation_runs=[compilation_run("running")],
        version_sets=[open_set, old_final_1, old_final_2, other_horizon],
        factor_map_tasks=[factor_task("factor_fix1", "H1")],
    )
    input_view = proj.model_dump()
    mark_seed()
    out = capture_finalize(proj, "map_fix1", note="复用开放集",
                           operator="专家D")
    assert out["ok"]
    assert out["version_set"]["id"] == "vset_seed1"
    assert out["version_set"]["linked_compilation_run_id"] is None  # kept
    by_id = {v.id: v.status for v in proj.version_sets}
    assert by_id == {"vset_seed1": "final", "vset_seed2": "superseded",
                     "vset_seed3": "superseded",
                     "vset_seed4": "final"}, by_id
    assert len(out["version_set"]["snapshots"]) == 2
    add("finalize_existing_open_set", "finalize_map_version",
        {"project": input_view, "map_document_id": "map_fix1",
         "options": {"note": "复用开放集", "operator": "专家D",
                     "require_qc_pass": False}},
        {"version_set": out["version_set"], "project": proj.model_dump()})

    # -- 14-19: active_final_snapshot -----------------------------------------
    def snap_view(sid: str, note: str) -> pm.VersionSnapshot:
        return seeded_snap(sid, note=note)

    reset_clock()
    sets = [
        seeded_vset("vset_a", "H0", "open", snaps=[snap_view("s0", "n0")],
                    active="s0"),
        seeded_vset("vset_b", "H1", "final",
                    snaps=[snap_view("s1", "n1"), snap_view("s2", "n2")],
                    active="s1", finalized_at=T0),
        seeded_vset("vset_c", "H3", "final",
                    snaps=[snap_view("s3", "n3"), snap_view("s4", "n4")],
                    active="s3", finalized_at=T0),
        seeded_vset("vset_d", "H2", "superseded",
                    snaps=[snap_view("s5", "n5")], active="s5"),
    ]
    proj = base_project(version_sets=sets)
    input_view = proj.model_dump()
    mark_seed()
    got = active_final_snapshot(proj)
    assert got is not None and got.id == "s3"  # last FINAL set, its active id
    add("active_final_snapshot_last_final_wins", "active_final_snapshot",
        {"project": input_view, "target_horizon": None},
        {"snapshot": got.model_dump()})

    reset_clock()
    mark_seed()
    got = active_final_snapshot(proj, target_horizon="H1")
    assert got is not None and got.id == "s1"  # active id ≠ 末位
    add("active_final_snapshot_horizon_hit", "active_final_snapshot",
        {"project": input_view, "target_horizon": "H1"},
        {"snapshot": got.model_dump()})

    reset_clock()
    mark_seed()
    got = active_final_snapshot(proj, target_horizon="H9")
    assert got is None
    add("active_final_snapshot_horizon_miss", "active_final_snapshot",
        {"project": input_view, "target_horizon": "H9"},
        {"snapshot": None})

    reset_clock()
    blank = seeded_vset("vset_blank", "H7", "final",
                        snaps=[snap_view("s6", "n6"), snap_view("s7", "n7")],
                        active=None, finalized_at=T0)
    proj2 = base_project(version_sets=[blank])
    input2 = proj2.model_dump()
    mark_seed()
    got = active_final_snapshot(proj2)
    assert got is not None and got.id == "s7"  # 末位 fallback
    add("active_final_snapshot_blank_active_id", "active_final_snapshot",
        {"project": input2, "target_horizon": None},
        {"snapshot": got.model_dump()})

    reset_clock()
    dangling = seeded_vset("vset_dang", "H7", "final",
                           snaps=[snap_view("s8", "n8"), snap_view("s9", "n9")],
                           active="vsnap_ghost", finalized_at=T0)
    proj3 = base_project(version_sets=[dangling])
    input3 = proj3.model_dump()
    mark_seed()
    got = active_final_snapshot(proj3)
    assert got is not None and got.id == "s9"  # dangling id → 末位
    add("active_final_snapshot_dangling_active_id", "active_final_snapshot",
        {"project": input3, "target_horizon": None},
        {"snapshot": got.model_dump()})

    reset_clock()
    empty_final = seeded_vset("vset_empty", "H8", "final", snaps=[],
                              active=None, finalized_at=T0)
    proj4 = base_project(version_sets=[empty_final])
    input4 = proj4.model_dump()
    mark_seed()
    got = active_final_snapshot(proj4)
    assert got is None
    add("active_final_snapshot_no_snapshots", "active_final_snapshot",
        {"project": input4, "target_horizon": None}, {"snapshot": None})

    reset_clock()
    proj5 = base_project()
    input5 = proj5.model_dump()
    mark_seed()
    got = active_final_snapshot(proj5)
    assert got is None
    add("active_final_snapshot_empty_project", "active_final_snapshot",
        {"project": input5, "target_horizon": None}, {"snapshot": None})

    # -- 20-21: version_set_summary -------------------------------------------
    reset_clock()
    mark_seed()
    got = version_set_summary(proj)
    assert got == {"version_set_count": 4, "final_count": 2, "open_count": 1,
                   "latest_final_horizon": "H3", "latest_final_at": T0}, got
    add("version_set_summary_mixed", "version_set_summary",
        {"project": input_view}, {"summary": got})

    reset_clock()
    mark_seed()
    got = version_set_summary(proj5)
    assert got == {"version_set_count": 0, "final_count": 0, "open_count": 0,
                   "latest_final_horizon": "", "latest_final_at": None}, got
    add("version_set_summary_empty", "version_set_summary",
        {"project": input5}, {"summary": got})

    # -- 22: DTO roundtrips (model_dump frozen for from_dict→to_dict) --------
    reset_clock()
    dtos = [
        ("VersionSet",
         pm.VersionSet(
             id="vset_dto1", name="H1 定稿版本集", target_horizon="H1",
             status="final",
             snapshots=[
                 pm.VersionSnapshot(
                     id="vsnap_dto1", map_document_id="map_dto1",
                     contour_draft_id=None, quality_report_id="qc_dto1",
                     factor_task_ids=["factor_dto1", "factor_dto2"],
                     map_name="dto 图", target_horizon="H1",
                     line_feature_count=3, facies_count=0,
                     contour_segment_count=7, qc_status="passed",
                     note="备注", content_fingerprint="abc123def4560123",
                     created_at=T0, created_by="dto",
                 ),
             ],
             active_snapshot_id="vsnap_dto1", finalized_by="dto",
             finalized_at=T0, linked_compilation_run_id=None,
             created_at=T0, updated_at=T0,
         ).model_dump()),
        ("VersionSnapshot",
         pm.VersionSnapshot(
             id="vsnap_dto2", map_document_id="map_dto2",
             contour_draft_id="cdraft_dto2", quality_report_id=None,
             map_name="", target_horizon="", qc_status="unchecked",
         ).model_dump()),
        ("ContourDraft", contour_draft("cdraft_dto3", segments=2).model_dump()),
        ("CompilationRun", compilation_run("exported").model_dump()),
        ("QualityReport",
         pm.QualityReport(
             id="qc_dto5", linked_map_document_id="map_dto1",
             rules=["basic", "extended"],
             issues=[{"rule": "r1", "severity": "WARNING", "count": 2}],
             status="warning", generated_at=T0, provenance_registered=False,
             rule_status={"r1": {"evaluated": True, "reason": ""},
                          "r2": {"evaluated": False,
                                 "reason": "无等值线数据"}},
             coverage={"r1": 1, "r2": 0},
         ).model_dump()),
    ]
    mark_seed()
    add("dto_roundtrip_models", "dto_roundtrip", {"models": dtos},
        {"dumps": [d for _, d in dtos]})

    # -- 23-25: fingerprint byte streams --------------------------------------
    def fingerprint_case(case_id: str, doc) -> None:
        mark_seed()
        raw = fingerprint_raw(doc)
        fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        add(case_id, "fingerprint_bytes", {"map_doc": doc.model_dump()},
            {"raw": raw, "fingerprint": fp})

    reset_clock()
    fingerprint_case("fingerprint_bytes_rich", prod_map(rich=True))
    reset_clock()
    fingerprint_case(
        "fingerprint_bytes_empty",
        pm.PaleoMapDocument(id="map_empty", name="空图",
                            linked_target_horizon=""),
    )
    reset_clock()
    fingerprint_case(
        "fingerprint_bytes_minimal",
        pm.PaleoMapDocument(
            id="map_mini", name="m", linked_target_horizon="层位A",
            line_features=[{"a": 1, "b": [1.5, -2.5, 0]}],
        ),
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "generator": "tools/oracle/generate_workflow_versioning_fixtures.py",
                "source": "paleo_workbench/workflow/versioning.py + project/models.py (real)",
                "determinism": {
                    "id": "{prefix}_{n:012d} shared counter",
                    "now": "2020-01-01T00:00:{n:02d}+00:00 shared counter",
                    "clock_order": "pydantic default factories fire in "
                    "field-declaration order; C++ replays via per-case "
                    "consumed counters",
                },
                "cases": CASES,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    raises = sum(1 for c in CASES if "raise" in c["expect"])
    prints = (
        f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(CASES)} cases, "
        f"{raises} frozen raise outcomes, models rebuilt: "
        f"{', '.join(_REBUILT)})"
    )
    print(prints)


if __name__ == "__main__":
    main()
