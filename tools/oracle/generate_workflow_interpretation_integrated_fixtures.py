#!/usr/bin/env python3
"""Oracle fixture generator for the workflow_interpretation integrated
interpretation first-class results (CONV-32, I8).

Imports the REAL implementation (paleo_workbench.workflow.interpretation.
integrated_interpretation + revision) and freezes its outputs to JSON so the
C++ port in libs/workflow_interpretation can be verified against the Python
chain. Regenerate with:

    python3 tools/oracle/generate_workflow_interpretation_integrated_fixtures.py

Cases (see main()): duplicate create message + iint_ id shape, from_dict/
to_dict roundtrip with Python str() coercions + has_uncommitted_edits
transitions, commit guardrails (null catalog / empty geometry), commit happy
path first (register_result_asset branch: asset type/stage/op/generator/
parameters n_features+actor, doc gains committed_version_id/run_id/
committed_at, revision recorded base_kind "commit", last_committed ==
revision_ids[-1], summary status ok) + second commit (register_version
parents == [catalog current pointer]), failing repository in register_run
(re-raise, no run to fail) and in register_result_asset (run marked failed +
re-raise), summary missing exact dict, and the revision-link double-append
guard (pre-appended revision id appears exactly once).

Deterministic: uuid.uuid4 is patched with a sequential counter (the only id
source — create's "iint_" and record_interpretation_revision's "irev_" both
slice uuid4().hex[:12]) and the recording catalog fake assigns
RuntimeStore-style sequential ids (asset_000001 / ver_000001 / run_000001).
Every case freezes the id sequence in consumption order so the C++ replay
feeds the same ids through its IdGen seams.
"""
from __future__ import annotations

import json
import sys
import uuid as uuid_module
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.workflow.interpretation.integrated_interpretation import (  # noqa: E402
    IntegratedInterpretation,
    commit_integrated_interpretation,
    create_integrated_interpretation,
    find_by_layer,
    interpretation_summary,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_interpretation"
    / "workflow_interpretation_tests"
    / "fixtures"
    / "workflow_interpretation_integrated_oracle.json"
)


# ------------------------------------------------------------- deterministic ids

class SequentialUuid4:
    """uuid.uuid4() replacement with the counter in the FIRST 12 hex chars
    (UUID(int=n) would put it at the end — hex[:12] would collide on zeros).
    hex[:12] is "000000000001", "000000000002", ... in consumption order;
    decimal digits are valid hex, so ids match iint_[0-9a-f]{12}."""

    def __init__(self) -> None:
        self.counter = 0
        self.consumed: list[str] = []

    @staticmethod
    def _hex_for(counter: int) -> str:
        return f"{counter:012d}" + "0" * 20

    def uuid4(self):
        self.counter += 1
        value = uuid_module.UUID(hex=self._hex_for(self.counter))
        self.consumed.append(value.hex[:12])
        return value

    def peek_next(self) -> str:
        return self._hex_for(self.counter + 1)[:12]


SEQ = SequentialUuid4()
uuid_module.uuid4 = SEQ.uuid4  # generator-process-wide (module-level patch)


def reset_ids() -> list[str]:
    SEQ.counter = 0
    SEQ.consumed = []
    return SEQ.consumed


# ------------------------------------------------------------- recording catalog

class RecordingCatalog:
    """CatalogRepository-shaped fake mirroring the C++ replay recorder:
    deterministic RuntimeStore-style ids, every call logged with the exact
    argument dict the C++ side will produce (payload as TEXT — the bytes are
    the identity, the temp-file location is incidental)."""

    def __init__(self, fail_at: str | None = None) -> None:
        self.assets: list[SimpleNamespace] = []
        self.log: list[dict] = []
        self.counters = {"asset": 0, "version": 0, "run": 0}
        self.fail_at = fail_at

    def _next(self, kind: str) -> str:
        self.counters[kind] += 1
        return f"{kind}_{self.counters[kind]:06d}"

    def list_assets(self):
        self.log.append({"method": "list_assets"})
        return list(self.assets)

    def register_run(self, operation, *, input_version_ids=(),
                     parameters=None, generator="", status="running",
                     **_kw):
        self.log.append({
            "method": "register_run",
            "operation": operation,
            "input_version_ids": list(input_version_ids),
            "parameters": dict(parameters or {}),
            "generator": generator,
            "status": status,
        })
        if self.fail_at == "register_run":
            raise RuntimeError("catalog down")
        return SimpleNamespace(id=self._next("run"))

    def register_result_asset(self, *, name, type=None, format=None,
                              asset_metadata=None, source_path=None,
                              stage=None, run_id=None, version_metadata=None,
                              **_kw):
        payload_text = Path(source_path).read_text(encoding="utf-8")
        self.log.append({
            "method": "register_result_asset",
            "name": name,
            "type": type,
            "format": format,
            "asset_metadata": dict(asset_metadata or {}),
            "payload_text": payload_text,
            "stage": getattr(stage, "value", str(stage)),
            "run_id": run_id,
            "version_metadata": dict(version_metadata or {}),
        })
        if self.fail_at == "register_result_asset":
            raise RuntimeError("catalog down")
        asset_id = self._next("asset")
        version_id = self._next("version")
        self.assets.append(SimpleNamespace(
            id=asset_id, type=type, current_version_id=version_id,
            metadata=dict(asset_metadata or {})))
        self.log[-1]["version_id"] = version_id
        return SimpleNamespace(id=version_id)

    def register_version(self, asset_id, source_path, stage, *,
                         parent_version_ids=(), run_id=None, metadata=None,
                         **_kw):
        payload_text = Path(source_path).read_text(encoding="utf-8")
        self.log.append({
            "method": "register_version",
            "asset_id": asset_id,
            "payload_text": payload_text,
            "stage": getattr(stage, "value", str(stage)),
            "parent_version_ids": list(parent_version_ids),
            "run_id": run_id,
            "metadata": dict(metadata or {}),
        })
        if self.fail_at == "register_version":
            raise RuntimeError("catalog down")
        version_id = self._next("version")
        for asset in self.assets:
            if asset.id == asset_id:
                asset.current_version_id = version_id
        self.log[-1]["version_id"] = version_id
        return SimpleNamespace(id=version_id)

    def update_run_status(self, run_id, status, **_kw):
        self.log.append({"method": "update_run_status",
                         "run_id": run_id, "status": status})


class NullCatalog:
    """_NullCatalog from the Python tests: list_assets only, empty."""

    def list_assets(self):
        return []


# ------------------------------------------------------------- layer seam

def build_layer(layer_dict: dict) -> SimpleNamespace:
    """Json layer {"features": [...]} -> the UserVectorLayer-shaped object
    the Python code paths read (attributes set ONLY when the Json feature
    carries the key, so getattr() falls through exactly like the C++ port)."""
    features = []
    for f in layer_dict.get("features") or []:
        kwargs = {}
        if "feature_id" in f:
            kwargs["feature_id"] = f["feature_id"]
        if "id" in f:
            kwargs["id"] = f["id"]
        if "geometry" in f:
            kwargs["geometry"] = f["geometry"]
        if "attributes" in f:
            kwargs["attributes"] = dict(f["attributes"] or {})
        if "properties" in f:
            kwargs["properties"] = dict(f["properties"] or {})
        features.append(SimpleNamespace(**kwargs))
    return SimpleNamespace(features=features)


def capture_error(exc: Exception) -> dict:
    return {"python_class": type(exc).__name__, "message": str(exc)}


# ------------------------------------------------------------- cases

def roundtrip_case() -> dict:
    source = {
        "interpretation_id": "iint_round0001",
        "name": None,               # -> ""
        "input_set_id": 0,          # falsy -> ""
        "layer_id": "L2",
        "fusion_version_id": "ver_fusion_7",
        "latest_fusion_version_id": "ver_fusion_8",
        "run_id": False,            # falsy -> ""
        "committed_version_id": "ver_committed_c1",
        "class_schema": ["三角洲", 3, None, True, 2.5],
        "confidence_summary": {"low_confidence_fraction": 0.25},
        "uncertainty_summary": {},
        "conflicts": {"high_conflict_fraction": 0.02,
                      "mean_conflict_fraction": 1e-05},
        "revision_ids": ["irev_r1", "irev_r2"],
        "last_committed_revision_id": "irev_r1",
        "qa_report_ref": "",
        "maturity": "",             # -> "draft"
        "created_at": "2026-09-01T00:00:00",
        "created_by": "geologist-a",
        "committed_at": "",
        "active": False,            # ignored by from_dict, to_dict -> true
        "unknown_extra": {"k": [1, 2]},
    }
    transitions = []
    # B — committed + trailing revision != anchor -> True.
    transitions.append({"input": dict(source), "has_uncommitted_edits": True})
    # A — never committed -> False.
    transitions.append({"input": dict(source, committed_version_id=None),
                        "has_uncommitted_edits": False})
    # C — anchor caught up with the chain tail -> False.
    transitions.append({"input": dict(source,
                                      last_committed_revision_id="irev_r2"),
                        "has_uncommitted_edits": False})
    # D — committed but no revisions recorded -> False.
    transitions.append({"input": dict(source, revision_ids=[]),
                        "has_uncommitted_edits": False})
    for entry in transitions:
        value = IntegratedInterpretation.from_dict(entry["input"])
        entry["has_uncommitted_edits"] = value.has_uncommitted_edits
        assert isinstance(entry["has_uncommitted_edits"], bool)
    return {
        "id": "roundtrip_and_uncommitted_edits",
        "input": source,
        "to_dict": IntegratedInterpretation.from_dict(source).to_dict(),
        "transitions": transitions,
    }


def duplicate_create_case() -> dict:
    consumed = reset_ids()
    doc = SimpleNamespace(integrated_interpretations=[],
                          interpretation_revisions=[])
    created = create_integrated_interpretation(
        doc, name="综合解释 v1", layer_id="L9", input_set_id="ciset_1",
        fusion_version_id="ver_f1", class_schema=["低", "中", "高"],
        conflicts={"high_conflict_fraction": 0.12},
        created_by="expert", created_at="2026-09-10T08:00:00")
    try:
        create_integrated_interpretation(doc, name="dup", layer_id="L9")
        raise AssertionError("duplicate create must raise")
    except ValueError as exc:
        error = capture_error(exc)
    return {
        "id": "duplicate_create",
        "create": {
            "name": "综合解释 v1", "layer_id": "L9", "input_set_id": "ciset_1",
            "fusion_version_id": "ver_f1", "class_schema": ["低", "中", "高"],
            "confidence_summary": {}, "conflicts": {"high_conflict_fraction": 0.12},
            "created_by": "expert", "created_at": "2026-09-10T08:00:00",
        },
        "ids": list(consumed),
        "record": created.to_dict(),
        "duplicate_error": error,
        "records": list(doc.integrated_interpretations),
    }


def guardrails_case() -> dict:
    consumed = reset_ids()
    doc = SimpleNamespace(integrated_interpretations=[],
                          interpretation_revisions=[])
    interpretation = create_integrated_interpretation(
        doc, name="空解释", layer_id="L0")
    empty_layer = build_layer({"features": []})
    try:
        commit_integrated_interpretation(doc, interpretation, empty_layer,
                                         None)
        raise AssertionError("null catalog must raise")
    except ValueError as exc:
        null_catalog_error = capture_error(exc)
    try:
        commit_integrated_interpretation(doc, interpretation, empty_layer,
                                         NullCatalog())
        raise AssertionError("empty geometry must raise")
    except ValueError as exc:
        empty_features_error = capture_error(exc)
    try:
        commit_integrated_interpretation(
            doc, interpretation, build_layer({}), NullCatalog())
        raise AssertionError("missing features must raise")
    except ValueError as exc:
        missing_features_error = capture_error(exc)
    return {
        "id": "commit_guardrails",
        "create": {"name": "空解释", "layer_id": "L0", "input_set_id": "",
                   "fusion_version_id": "", "class_schema": [],
                   "confidence_summary": {}, "conflicts": {},
                   "created_by": "", "created_at": ""},
        "ids": list(consumed),
        "null_catalog_error": null_catalog_error,
        "empty_features_error": empty_features_error,
        "missing_features_error": missing_features_error,
        "records": list(doc.integrated_interpretations),
        "revisions": list(doc.interpretation_revisions),
    }


BASE_CREATE = {
    "name": "综合解释",
    "layer_id": "L5",
    "input_set_id": "ciset_1",
    "fusion_version_id": "ver_seed",
    "class_schema": ["低", "中", "高"],
    "confidence_summary": {"low_confidence_fraction": 0.18},
    "conflicts": {"high_conflict_fraction": 0.12},
    "created_by": "expert",
    "created_at": "2026-09-10T11:00:00",
}

LAYER_V1 = {"features": [
    {"id": "f0",
     "geometry": {"type": "Polygon", "coordinates": [
         [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
     "properties": {"class": "三角洲", "rank": 2, "ratio": 0.25}},
    # feature_id wins over id; attributes wins over properties.
    {"feature_id": "pf1", "id": "f1",
     "geometry": {"type": "Polygon", "coordinates": [
         [[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 2.0]]]},
     "attributes": {"class": "湖泊"}, "properties": {"class": "河道"}},
    # no geometry -> {} (empty-geometry feature still commits).
    {"id": "f2", "properties": {"note": "无几何要素"}},
]}

LAYER_V2 = {"features": LAYER_V1["features"] + [
    {"id": "fx",
     "geometry": {"type": "Polygon", "coordinates": [
         [[5.0, 5.0], [6.0, 5.0], [6.0, 6.0], [5.0, 5.0]]]},
     "properties": {}},
]}


def commit_case(case_id: str, commits: list[dict], *, fail_at=None,
                pre_append_revision: bool = False) -> dict:
    consumed = reset_ids()
    doc = SimpleNamespace(integrated_interpretations=[],
                          interpretation_revisions=[])
    catalog = RecordingCatalog(fail_at=fail_at)
    interpretation = create_integrated_interpretation(
        doc, name=BASE_CREATE["name"], layer_id=BASE_CREATE["layer_id"],
        input_set_id=BASE_CREATE["input_set_id"],
        fusion_version_id=BASE_CREATE["fusion_version_id"],
        class_schema=list(BASE_CREATE["class_schema"]),
        confidence_summary=dict(BASE_CREATE["confidence_summary"]),
        conflicts=dict(BASE_CREATE["conflicts"]),
        created_by=BASE_CREATE["created_by"],
        created_at=BASE_CREATE["created_at"])
    if pre_append_revision:
        # Case 22: the would-be revision id pre-appended into the stored
        # record — the domain link + commit guard must not double-append.
        doc.integrated_interpretations[0]["revision_ids"].append(
            f"irev_{SEQ.peek_next()}")
    error = None
    last_version = ""
    for step in commits:
        try:
            last_version = commit_integrated_interpretation(
                doc, interpretation, build_layer(step["layer"]), catalog,
                actor=step.get("actor", ""),
                now=step.get("now", ""),
                evidence_refs=step.get("evidence_refs"))
            interpretation = find_by_layer(
                doc, BASE_CREATE["layer_id"]) or interpretation
        except Exception as exc:  # noqa: BLE001 — freeze class + message
            error = capture_error(exc)
            break
    expect = {
        "log": catalog.log,
        "final_interpretations": list(doc.integrated_interpretations),
        "final_revisions": list(doc.interpretation_revisions),
        "last_version_id": last_version,
        "raise": error,
    }
    if error is None:
        expect["final_summary"] = interpretation_summary(
            doc, BASE_CREATE["layer_id"])
    return {
        "id": case_id,
        "create": dict(BASE_CREATE),
        "commits": commits,
        "fail_at": fail_at,
        "pre_append_revision": pre_append_revision,
        "ids": list(consumed),
        "expect": expect,
    }


def summary_missing_case() -> dict:
    doc = SimpleNamespace(integrated_interpretations=[],
                          interpretation_revisions=[])
    return {
        "id": "summary_missing",
        "layer_id": "nope",
        "expect": interpretation_summary(doc, "nope"),
    }


def main() -> None:
    doc = {
        "roundtrip": roundtrip_case(),
        "duplicate_create": duplicate_create_case(),
        "guardrails": guardrails_case(),
        "commit_cases": [
            commit_case("commit_first", [
                {"layer": LAYER_V1, "actor": "expert",
                 "now": "2026-09-10T12:00:00",
                 "evidence_refs": ["factor:t:ver_1"]},
            ]),
            commit_case("commit_second", [
                {"layer": LAYER_V1, "actor": "expert",
                 "now": "2026-09-10T12:00:00",
                 "evidence_refs": ["factor:t:ver_1"]},
                {"layer": LAYER_V2, "actor": "expert-li", "now": "t2"},
            ]),
            commit_case("commit_fail_register_run", [
                {"layer": LAYER_V1, "actor": "expert", "now": "t0"},
            ], fail_at="register_run"),
            commit_case("commit_fail_after_run", [
                {"layer": LAYER_V1, "actor": "expert", "now": "t0"},
            ], fail_at="register_result_asset"),
            commit_case("revision_link_double_append_guard", [
                {"layer": LAYER_V1, "actor": "expert", "now": "t1",
                 "evidence_refs": ["factor:t1:ver_2"]},
            ], pre_append_revision=True),
        ],
        "summary_missing": summary_missing_case(),
    }
    target = OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    n_log = sum(len(c["expect"]["log"]) for c in doc["commit_cases"])
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(doc['commit_cases'])} commit cases, {n_log} catalog calls)")


if __name__ == "__main__":
    main()
