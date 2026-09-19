#!/usr/bin/env python3
"""Oracle fixture generator for workflow_interpretation compilation input
sets (CONV-32, task I7).

Imports the REAL implementation (paleo_workbench.workflow.interpretation.
compilation + the evidence/constraint_versions chain it calls) and freezes
its outputs to JSON so the C++ port in libs/workflow_interpretation can
be verified against the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_interpretation_compilation_fixtures.py

Deterministic (re-run must be byte-identical):
  * project-model ids are monkeypatched to "{prefix}_{n:012x}" counters
    (paleo_workbench.project.models._id — resolved at Field-call time);
  * uuid4 is monkeypatched to dead{n:08x} hex (compilation's internal
    uuid4().hex[:12] for the legacy-shell migration id);
  * create_input_set ids/timestamps are injected via set_id/now;
  * the fake constraint catalog service uses the same deterministic id
    scheme as the C++ RuntimeStore (asset_/ver_/run_ %06d, fixed clock)
    so the C++ replay rebuilds the identical committed state.

15 cases (see main()): honest create snapshots (resolved/unknown/
unpinned), malformed-selector ValueError, validate blocked (factor
missing + constraints:current unknown) / degraded (prediction unpinned)
/ ready, freeze factor pin + selector rewrite, freeze refusal with FULL
atomic rollback, floating refusal message byte-exact (label prefix
地质约束（当前内容）), multi-group floating refusal (two committed groups),
single-group floating success (constraints:g1:ver_000001), double freeze
message, persist/active flip + legacy null document, evidence_view
structured + legacy fallback + shell migration (skips bad selector,
status_at_add ""), STALE freeze-through (pins ver_f1).
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({ROOT}) — oracle must import the real tree"
)

# -- determinism patches (before any model instantiation) -------------------

_ID_N = 0
_UUID_N = 0


def _fake_model_id(prefix: str) -> str:
    global _ID_N
    _ID_N += 1
    return f"{prefix}_{_ID_N:012x}"


def _fake_uuid4():
    global _UUID_N
    _UUID_N += 1
    return types.SimpleNamespace(hex=f"dead{_UUID_N:08x}")


from paleo_workbench.project import models as _models  # noqa: E402

import uuid as _uuid  # noqa: E402

_models._id = _fake_model_id
_uuid.uuid4 = _fake_uuid4

from paleo_workbench.project.models import (  # noqa: E402
    ConstraintLine,
    ConstraintLayers,
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
)
from paleo_workbench.workflow.constraint_versions import (  # noqa: E402
    commit_constraint_group,
)
from paleo_workbench.workflow.interpretation.compilation import (  # noqa: E402
    CompilationInputSet,
    active_input_set,
    create_input_set,
    create_input_set_shell_from_legacy,
    evidence_view,
    freeze_input_set,
    input_sets_for_document,
    persist_input_set,
    validate_input_set,
)

OUT = (
    ROOT
    / "libs"
    / "workflow_interpretation"
    / "workflow_interpretation_tests"
    / "fixtures"
    / "workflow_interpretation_compilation_oracle.json"
)

cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def capture(fn, *args, **kwargs):
    try:
        return {"result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 — freeze class + message verbatim
        return {"raise": {"python_class": type(exc).__name__,
                          "message": str(exc)}}


# ------------------------------------------------------------- catalog fakes


class _FakeVersion:
    """DataVersion-shaped record for evidence resolution (tests' fake)."""

    def __init__(self, version_id, asset_id="asset"):
        self.id = version_id
        self.asset_id = asset_id


class _FakeCatalog:
    """Evidence-only catalog: resolve_version (tests' _FakeCatalog)."""

    def __init__(self, versions=None):
        self._versions = versions or {}

    def resolve_version(self, version_id):
        return self._versions.get(version_id)

    def fixture(self) -> dict:
        return {"versions": {v: info.asset_id
                             for v, info in self._versions.items()}}


class FakeCatalogService:
    """Deterministic fake DataCatalogService (constraint lifecycle) — the
    same id scheme the C++ RuntimeStore uses (asset_/ver_/run_ %06d, 1s
    ticks). Verbatim from generate_workflow_runtime_fixtures.py."""

    def __init__(self):
        self.assets: list[types.SimpleNamespace] = []
        self.versions: list[types.SimpleNamespace] = []
        self.runs: list[types.SimpleNamespace] = []
        self._n_asset = 0
        self._n_ver = 0
        self._n_run = 0
        self._tick = 0
        self._tmp = Path(tempfile.mkdtemp(prefix="constraint-oracle-"))

    def list_assets(self):
        return list(self.assets)

    def list_versions(self, asset_id=None, **kwargs):
        if asset_id is None:
            return list(self.versions)
        return [v for v in self.versions if v.asset_id == asset_id]

    def list_runs(self):
        return list(self.runs)

    def get_version(self, version_id):
        for v in self.versions:
            if v.id == version_id:
                return v
        return None

    def register_run(self, operation, input_version_ids=None,
                     parameters=None, generator=None, status="running"):
        self._n_run += 1
        run = types.SimpleNamespace(
            id=f"run_{self._n_run:06d}", operation=operation,
            input_version_ids=list(input_version_ids or []),
            output_version_ids=[],
            parameters=dict(parameters or {}),
            generator=generator, status=status)
        self.runs.append(run)
        return run

    def register_result_asset(self, *, name, type, format, asset_metadata,
                              source_path, stage, run_id, version_metadata):
        self._n_asset += 1
        asset = types.SimpleNamespace(
            id=f"asset_{self._n_asset:06d}", name=name, type=type,
            format=format, current_version_id=None,
            metadata=dict(asset_metadata or {}))
        self.assets.append(asset)
        payload = Path(source_path).read_text(encoding="utf-8")
        version = self._make_version(asset, payload, version_metadata, run_id)
        asset.current_version_id = version.id
        run = next(r for r in self.runs if r.id == run_id)
        run.output_version_ids.append(version.id)
        return version

    def register_version(self, asset_id, source_path, stage,
                         parent_version_ids=None, run_id=None, metadata=None):
        asset = next(a for a in self.assets if a.id == asset_id)
        payload = Path(source_path).read_text(encoding="utf-8")
        version = self._make_version(asset, payload, metadata or {}, run_id)
        if run_id:
            run = next(r for r in self.runs if r.id == run_id)
            run.output_version_ids.append(version.id)
        return version

    def update_run_status(self, run_id, status):
        run = next(r for r in self.runs if r.id == run_id)
        run.status = status

    def _make_version(self, asset, payload, metadata, run_id):
        self._n_ver += 1
        self._tick += 1
        digest = hashlib.sha256(payload.encode()).hexdigest()
        path = self._tmp / f"v{self._n_ver}.json"
        path.write_text(payload, encoding="utf-8")
        version = types.SimpleNamespace(
            id=f"ver_{self._n_ver:06d}",
            asset_id=asset.id,
            name=asset.name,
            producing_run_id=run_id,
            checksum=digest,
            trashed=False,
            path="",
            created_at=f"2026-01-01T00:00:{self._tick:02d}",
            metadata=dict(metadata or {}),
            source_uri=str(path),
            payload=payload,
        )
        self.versions.append(version)
        return version


class OracleCatalog:
    """ONE catalog object for the whole Python flow, mirroring production:
    evidence resolve_version directly + the constraint lifecycle through
    the embedded fake service (constraint_versions._as_service unwraps
    the .service attribute)."""

    def __init__(self, versions=None):
        self._versions = {v: _FakeVersion(v, a)
                          for v, a in (versions or {}).items()}
        self.service = FakeCatalogService()

    def resolve_version(self, version_id):
        return self._versions.get(version_id)

    def fixture(self) -> dict:
        return {"versions": {v: info.asset_id
                             for v, info in self._versions.items()}}


# ----------------------------------------------------------- document fakes

# Exactly the attributes the evidence resolution reads off the document —
# this is the Json-object seam handed to the C++ port.
FACTOR_FIELDS = ("id", "name", "status", "grid_artifact_version_id",
                 "quality_metrics", "source_kind")
PRED_FIELDS = ("id", "name", "status", "adapter_kind", "probability_summary")


def document_view(doc) -> dict:
    return {
        "factor_map_tasks": [
            {k: getattr(t, k) for k in FACTOR_FIELDS}
            for t in doc.factor_map_tasks
        ],
        "prediction_tasks": [
            {k: getattr(p, k) for k in PRED_FIELDS}
            for p in doc.prediction_tasks
        ],
        "constraint_layers": [g.model_dump() for g in doc.constraint_layers],
    }


def base_document(grid_version: str = "ver_f1",
                  with_prediction: bool = True) -> ProjectDocument:
    """tests/test_interpretation_v9_compilation.py _document()."""
    doc = ProjectDocument.new("t")
    task = FactorMapTask(
        name="砂厚", target_horizon="T1", factor_type="砂岩厚度",
        method="idw", status="complete", source_kind="real")
    task.grid_artifact_version_id = grid_version
    doc.factor_map_tasks.append(task)
    if with_prediction:
        doc.prediction_tasks.append(PredictionTask(name="地震相预测",
                                                   status="complete"))
    return doc


GROUP_G1 = {
    "id": "g1", "name": "断层约束A", "target_horizon": "T1", "crs": None,
    "lines": [
        {"id": "l1", "name": "F1", "role": "break", "active": True,
         "target_horizon": "T1", "coordinates": [[0.0, 0.0], [10.0, 0.0]]},
        {"id": "l2", "name": "D1", "role": "direction", "active": True,
         "target_horizon": "T1", "coordinates": [[0.0, 0.0], [0.0, 8.0]]},
    ],
}
GROUP_G2 = {
    "id": "g2", "name": "边界约束B", "target_horizon": "T1", "crs": None,
    "lines": [
        {"id": "l3", "name": "B1", "role": "break", "active": True,
         "target_horizon": "T1", "coordinates": [[5.0, 5.0], [6.0, 6.0]]},
    ],
}


def make_group(g: dict) -> ConstraintLayers:
    return ConstraintLayers(
        id=g["id"], name=g.get("name", ""),
        target_horizon=g.get("target_horizon", ""), crs=g.get("crs"),
        lines=[
            ConstraintLine(
                id=l["id"], name=l.get("name", ""),
                role=l.get("role", "other"), active=l.get("active", True),
                target_horizon=l.get("target_horizon", ""),
                coordinates=[list(c) for c in l.get("coordinates", [])],
                properties=l.get("properties", {}) or {})
            for l in g.get("lines", [])
        ],
    )


NOW = "2026-09-10T00:00:00"


def create_opts(set_id: str, **kw) -> dict:
    opts = {"set_id": set_id, "now": NOW, "created_by": "tester", "name": ""}
    opts.update(kw)
    return opts


def run_create(document, selectors, *, catalog=None, set_id="ciset_fixed0001",
               now=NOW, name="", created_by="tester"):
    return create_input_set(
        document, selectors, name=name, created_by=created_by,
        catalog=catalog, set_id=set_id, now=now)


def post_state(input_set) -> dict:
    return {
        "frozen": input_set.frozen,
        "selectors": [e.selector for e in input_set.entries],
        "pins": [e.pinned_version_id for e in input_set.entries],
    }


def run_freeze(input_set, document, *, catalog=None, now=""):
    """freeze_input_set returns the mutated set; freeze its to_dict."""
    return freeze_input_set(input_set, document, catalog=catalog,
                            now=now).to_dict()


# ------------------------------------------------------------------- cases


def main() -> None:
    # 1 — honest snapshots: resolved factor / unknown constraints:current /
    #     unpinned prediction (tests' test_create_input_set_...).
    doc = base_document()
    task = doc.factor_map_tasks[0]
    pred = doc.prediction_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    selectors = [f"factor:{task.id}:ver_f1", "constraints:current",
                 f"prediction:{pred.id}"]
    input_set = run_create(doc, selectors, catalog=catalog)
    statuses = {e.selector: e.status_at_add for e in input_set.entries}
    assert statuses[f"factor:{task.id}:ver_f1"] == "resolved"
    assert statuses["constraints:current"] == "unknown"  # 未提交不猜
    assert statuses[f"prediction:{pred.id}"] == "unpinned"
    add("create_honest_snapshots", "create_input_set",
        {"document": document_view(doc), "selectors": selectors,
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0001",
         "now": NOW, "catalog": catalog.fixture()},
        capture(lambda: input_set.to_dict()))

    # 2 — malformed selector → ValueError (message from the evidence
    #     module, verbatim).
    doc = base_document()
    outcome = capture(run_create, doc, ["bogus-selector"])
    assert "raise" in outcome
    assert outcome["raise"]["python_class"] == "ValueError"
    assert outcome["raise"]["message"] == (
        "unrecognized evidence selector: 'bogus-selector'")
    add("create_malformed_selector", "create_input_set",
        {"document": document_view(doc), "selectors": ["bogus-selector"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0002",
         "now": NOW, "catalog": None},
        outcome)

    # 3/4/5/6 — validate verdicts (blocked missing factor / blocked
    #     unknown constraints / degraded unpinned prediction / ready).
    doc = base_document()
    task = doc.factor_map_tasks[0]
    pred = doc.prediction_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})

    def validate_case(cid, sels, set_id):
        s = run_create(doc, sels, catalog=catalog, set_id=set_id)
        validation = validate_input_set(s, doc, catalog=catalog)
        add(cid, "create_and_validate",
            {"document": document_view(doc), "selectors": sels,
             "name": "", "created_by": "tester", "set_id": set_id,
             "now": NOW, "catalog": catalog.fixture()},
            {"created": s.to_dict(), "validation": validation.to_dict()})
        return validation

    blocked = validate_case("validate_blocked_factor_missing",
                            ["factor:nope:ver_x"], "ciset_fixed0003")
    assert blocked.verdict == "blocked"
    unknown = validate_case("validate_blocked_constraints_unknown",
                            ["constraints:current"], "ciset_fixed0004")
    assert unknown.verdict == "blocked"
    degraded = validate_case(
        "validate_degraded_prediction_unpinned",
        [f"prediction:{pred.id}"], "ciset_fixed0005")
    assert degraded.verdict == "degraded"
    ready = validate_case("validate_ready",
                          [f"factor:{task.id}:ver_f1"], "ciset_fixed0006")
    assert ready.verdict == "ready" and ready.detail == ""

    # 7 — freeze pins RESOLVED factor and rewrites the version-less
    #     selector to its explicit versioned form.
    doc = base_document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    s = run_create(doc, [f"factor:{task.id}"], catalog=catalog,
                   set_id="ciset_fixed0007")
    created = s.to_dict()
    outcome = capture(run_freeze, s, doc, catalog=catalog, now="t0")
    assert s.frozen and s.frozen_at == "t0"
    assert s.entries[0].pinned_version_id == "ver_f1"
    assert s.entries[0].selector == f"factor:{task.id}:ver_f1"
    add("freeze_factor_pin_rewrite", "freeze",
        {"document": document_view(doc), "selectors": [f"factor:{task.id}"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0007",
         "now": NOW, "catalog": catalog.fixture(), "repo_setup": None,
         "freeze_now": "t0", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    # 8 — freeze refusal + FULL rollback (missing factor refuses; the
    #     resolved sibling's pin must not survive).
    doc = base_document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    sels = [f"factor:{task.id}:ver_f1", "factor:missing_task:v"]
    s = run_create(doc, sels, catalog=catalog, set_id="ciset_fixed0008")
    created = s.to_dict()
    outcome = capture(run_freeze, s, doc, catalog=catalog)
    assert "raise" in outcome and "无法钉住版本" in outcome["raise"]["message"]
    assert all(e.pinned_version_id == "" for e in s.entries)  # 原子回滚
    assert not s.frozen
    assert [e.selector for e in s.entries] == sels  # 选择器不变
    add("freeze_refusal_full_rollback", "freeze",
        {"document": document_view(doc), "selectors": sels,
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0008",
         "now": NOW, "catalog": catalog.fixture(), "repo_setup": None,
         "freeze_now": "", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    # 9 — floating refusal, message byte-exact (no catalog / no commits →
    #     the entry resolves UNKNOWN at freeze time → generic refusal with
    #     the 地质约束（当前内容） label prefix; tests'
    #     test_freeze_floating_constraints_requires_commit).
    doc = base_document()
    s = run_create(doc, ["constraints:current"], catalog=None,
                   set_id="ciset_fixed0009")
    created = s.to_dict()
    outcome = capture(run_freeze, s, doc)
    assert "raise" in outcome and "无法钉住版本" in outcome["raise"]["message"]
    assert outcome["raise"]["message"] == (
        "输入集冻结被拒绝——以下证据无法钉住版本："
        "地质约束（当前内容）：unknown（no constraints）")
    assert all(e.pinned_version_id == "" for e in s.entries)
    assert not s.frozen
    add("freeze_floating_refusal_message", "freeze",
        {"document": document_view(doc), "selectors": ["constraints:current"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0009",
         "now": NOW, "catalog": None, "repo_setup": None,
         "freeze_now": "", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    # 10 — multi-group floating refusal: two committed groups, each with
    #      its own commit → pinning one leaves dark holes → refuse.
    doc = base_document()
    doc.constraint_layers.append(make_group(GROUP_G1))
    doc.constraint_layers.append(make_group(GROUP_G2))
    catalog = OracleCatalog({})
    view = document_view(doc)
    for group in doc.constraint_layers:
        commit_constraint_group(doc, catalog.service, group,
                                actor="oracle-setup")
    s = run_create(doc, ["constraints:current"], catalog=catalog,
                   set_id="ciset_fixed0010")
    created = s.to_dict()
    assert s.entries[0].status_at_add == "floating"
    outcome = capture(run_freeze, s, doc, catalog=catalog)
    assert "raise" in outcome and "无法钉住版本" in outcome["raise"]["message"]
    assert all(e.pinned_version_id == "" for e in s.entries)
    assert not s.frozen
    assert s.entries[0].selector == "constraints:current"
    add("freeze_floating_multi_group_refusal", "freeze",
        {"document": view, "selectors": ["constraints:current"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0010",
         "now": NOW, "catalog": catalog.fixture(),
         "repo_setup": view["constraint_layers"],
         "freeze_now": "", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    # 11 — single-group floating success: exactly one committed group →
    #      pin its version and rewrite to constraints:g1:ver_000001.
    doc = base_document()
    doc.constraint_layers.append(make_group(GROUP_G1))
    catalog = OracleCatalog({})
    view = document_view(doc)
    commit_constraint_group(doc, catalog.service, doc.constraint_layers[0],
                            actor="oracle-setup")
    s = run_create(doc, ["constraints:current"], catalog=catalog,
                   set_id="ciset_fixed0011")
    created = s.to_dict()
    assert s.entries[0].status_at_add == "floating"
    outcome = capture(run_freeze, s, doc, catalog=catalog, now="t1")
    assert s.frozen and s.frozen_at == "t1"
    assert s.entries[0].selector == "constraints:g1:ver_000001"
    assert s.entries[0].pinned_version_id == "ver_000001"
    add("freeze_floating_single_group_success", "freeze",
        {"document": view, "selectors": ["constraints:current"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0011",
         "now": NOW, "catalog": catalog.fixture(),
         "repo_setup": view["constraint_layers"],
         "freeze_now": "t1", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    # 12 — double freeze → 输入集已冻结（不可重复冻结——新建输入集替代）.
    doc = base_document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    s = run_create(doc, [f"factor:{task.id}:ver_f1"], catalog=catalog,
                   set_id="ciset_fixed0012")
    created = s.to_dict()
    first = capture(run_freeze, s, doc, catalog=catalog, now="t0")
    second = capture(run_freeze, s, doc, catalog=catalog)
    assert "raise" in second and "已冻结" in second["raise"]["message"]
    add("freeze_double_freeze_message", "freeze",
        {"document": document_view(doc),
         "selectors": [f"factor:{task.id}:ver_f1"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0012",
         "now": NOW, "catalog": catalog.fixture(), "repo_setup": None,
         "freeze_now": "t0", "second_freeze": True},
        {"created": created, "outcome": first, "post": post_state(s),
         "second": second})

    # 13 — persist + active flip + list + legacy document (no field).
    doc = base_document()
    task = doc.factor_map_tasks[0]
    view = document_view(doc)
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    first = run_create(doc, [f"factor:{task.id}:ver_f1"], catalog=catalog,
                       set_id="ciset_fixed0013")
    persist_input_set(doc, first)
    loaded = active_input_set(doc)
    assert loaded is not None and loaded.id == first.id
    assert loaded.entries[0].selector == f"factor:{task.id}:ver_f1"
    second = CompilationInputSet(id="ciset_2", name="v2")
    persist_input_set(doc, second)
    active_after = active_input_set(doc)
    assert active_after is not None and active_after.id == "ciset_2"
    all_sets = input_sets_for_document(doc)
    assert len(all_sets) == 2
    legacy_active = active_input_set(types.SimpleNamespace())
    assert legacy_active is None
    add("persist_active_flip_and_legacy", "persist_and_query",
        {"document": view,
         "first": {"selectors": [f"factor:{task.id}:ver_f1"],
                   "set_id": "ciset_fixed0013", "now": NOW,
                   "created_by": "tester", "catalog": catalog.fixture()},
         "second": {"id": "ciset_2", "name": "v2"}},
        {"document_sets": list(doc.compilation_input_sets),
         "active": active_after.to_dict(),
         "all_ids": [s.id for s in all_sets],
         "legacy_active": None})

    # 14 — evidence_view: structured legacy_view, legacy dict fallback,
    #      empty, and the shell migration (skips bad selector).
    doc = base_document()
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1")})
    sels = [f"factor:{task.id}:ver_f1", "constraints:current"]
    s = run_create(doc, sels, catalog=catalog, set_id="ciset_fixed0014")
    persist_input_set(doc, s)
    structured = evidence_view(doc)
    assert structured == {e.label: e.selector for e in s.entries}
    assert len(structured) == 2

    fallback_pairs = {"单因素：砂厚": f"factor:{task.id}:ver_f1",
                      "地质约束": "constraints:current"}
    empty_holder = types.SimpleNamespace(compilation_input_sets=[])
    fallback = evidence_view(
        empty_holder,
        types.SimpleNamespace(compilation_input_set=dict(fallback_pairs)))
    assert fallback == fallback_pairs
    empty = evidence_view(empty_holder, None)
    assert empty == {}

    shell_doc = base_document()
    shell_ws_pairs = {"旧标签A": f"factor:{task.id}:ver_f1",
                      "坏的": "bogus-selector",
                      "地质约束": "constraints:current"}
    shell = create_input_set_shell_from_legacy(
        shell_doc,
        types.SimpleNamespace(compilation_input_set=dict(shell_ws_pairs)),
        created_by="migrator")
    assert shell is not None
    assert shell.name == "综合编图输入集"
    assert [e.label for e in shell.entries] == ["旧标签A", "地质约束"]
    assert all(e.status_at_add == "" for e in shell.entries)  # 空快照
    assert "bogus-selector" not in {e.selector for e in shell.entries}
    add("evidence_view_structured_legacy_shell", "evidence_view_and_shell",
        {"structured": {"document": document_view(doc), "selectors": sels,
                        "set_id": "ciset_fixed0014", "now": NOW,
                        "created_by": "tester",
                        "catalog": catalog.fixture()},
         "fallback": {"document": document_view(base_document()),
                      "workspace_state": {"compilation_input_set":
                                          fallback_pairs}},
         "shell": {"document": document_view(shell_doc),
                   "workspace_state": {"compilation_input_set":
                                       shell_ws_pairs},
                   "created_by": "migrator",
                   "id_suffix": shell.id[len("ciset_"):]}},
        {"structured": [[k, v] for k, v in structured.items()],
         "fallback": [[k, v] for k, v in fallback.items()],
         "empty": [[k, v] for k, v in empty.items()],
         "shell": shell.to_dict(),
         "shell_document_sets": list(shell_doc.compilation_input_sets)})

    # 15 — STALE freeze-through: pinned ver_f1, task current ver_f2 →
    #      still freezes at the pinned version (stale is an assessment,
    #      never blocks freeze).
    doc = base_document(grid_version="ver_f2")
    task = doc.factor_map_tasks[0]
    catalog = _FakeCatalog({"ver_f1": _FakeVersion("ver_f1", "asset_f1"),
                            "ver_f2": _FakeVersion("ver_f2", "asset_f2")})
    s = run_create(doc, [f"factor:{task.id}:ver_f1"], catalog=catalog,
                   set_id="ciset_fixed0015")
    created = s.to_dict()
    assert s.entries[0].status_at_add == "stale"
    outcome = capture(run_freeze, s, doc, catalog=catalog, now="t2")
    assert s.frozen
    assert s.entries[0].pinned_version_id == "ver_f1"
    assert s.entries[0].selector == f"factor:{task.id}:ver_f1"
    add("freeze_stale_freeze_through", "freeze",
        {"document": document_view(doc),
         "selectors": [f"factor:{task.id}:ver_f1"],
         "name": "", "created_by": "tester", "set_id": "ciset_fixed0015",
         "now": NOW, "catalog": catalog.fixture(), "repo_setup": None,
         "freeze_now": "t2", "second_freeze": False},
        {"created": created, "outcome": outcome, "post": post_state(s),
         "second": None})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1)
                   + "\n", encoding="utf-8")
    raises = sum(
        1 for c in cases
        if "raise" in c["expect"]
        or "raise" in c["expect"].get("outcome", {})
        or "raise" in (c["expect"].get("second") or {}))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(cases)} cases, "
          f"{raises} frozen raise outcomes)")


if __name__ == "__main__":
    main()
