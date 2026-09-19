#!/usr/bin/env python3
"""Generate the frozen map-product oracle for cpp-close-02.

Drives the REAL Python implementation (paleo_workbench.workflow.map_product)
against a deterministic in-memory catalog double and freezes every
observable: scientific fingerprints (exact sha256 hex over the sorted
payload), the assembled run/asset/version registration state (RUNNING
booking → complete, #1219), the appended MapProductRecord, staleness /
compare / lifecycle / publish gates with their verbatim messages, and the
fail-closed refusal matrix (empty factors / unknown task / mock source /
missing grid / missing catalog / missing payload).

The catalog double records register_run / register_result_asset /
update_run_status calls with deterministic ids and timestamps; its state
is frozen as plain JSON for the C++ replay. Determinism: project model
ids/timestamps are patched to sequential/frozen values; payloads carry no
wall-clock data. Re-runs are byte-identical.
"""

from __future__ import annotations

import hashlib
import json
import sys
import datetime
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import paleo_workbench.project.models as pm  # noqa: E402
from paleo_workbench.workflow.map_product import (  # noqa: E402
    MapProductAssembly,
    assemble_map_product,
    clone_map_product,
    compare_map_products,
    effective_lifecycle,
    find_map_product,
    freeze_map_product,
    product_staleness,
    rerun_map_product,
    review_map_product,
    supersede_map_product,
)

FIXTURE = (
    ROOT
    / "libs/closure_workflow/closure_workflow_tests/fixtures/"
    "closure_map_product_oracle.json"
)

FROZEN_NOW = "2026-01-01T00:00:00+00:00"


@dataclass
class FakeRunRef:
    id: str


@dataclass
class FakeVersionRef:
    id: str


@dataclass
class FakeCatalog:
    runs: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    seq: int = 0
    fail_output: bool = False

    def register_run(self, operation, input_version_ids, parameters,
                     generator=None, status="running"):
        self.seq += 1
        run_id = f"run_{self.seq:06d}"
        self.runs.append({
            "id": run_id,
            "operation": operation,
            "input_version_ids": list(input_version_ids),
            "parameters": parameters,
            "generator": generator,
            "status": status,
        })
        return FakeRunRef(run_id)

    def register_result_asset(self, name, type, format, asset_metadata,
                              source_path, stage, run_id, version_metadata):
        if self.fail_output:
            raise RuntimeError("catalog write refused")
        self.seq += 1
        asset_id = f"asset_{self.seq:06d}"
        version_id = f"ver_{self.seq:06d}"
        self.assets.append({
            "id": asset_id,
            "name": name,
            "type": type,
            "format": format,
            "asset_metadata": asset_metadata,
        })
        # Hash the staged file CONTENT (the real catalog copies the file
        # and checksums the bytes) — content, not path, so the frozen
        # sha256 is path-independent.
        payload_sha = hashlib.sha256(
            Path(source_path).read_bytes()).hexdigest()
        self.versions.append({
            "id": version_id,
            "asset_id": asset_id,
            "name": name,
            "stage": str(getattr(stage, "value", stage)),
            "run_id": run_id,
            "sha256": payload_sha,
            "version_metadata": version_metadata,
        })
        return FakeVersionRef(version_id)

    def update_run_status(self, run_id, status, extra_parameters=None):
        for run in self.runs:
            if run["id"] == run_id:
                run["status"] = status
                if extra_parameters:
                    run["extra_parameters"] = extra_parameters
                return
        raise KeyError(run_id)

    def get_run(self, run_id):
        for run in self.runs:
            if run["id"] == run_id:
                return run
        raise KeyError(run_id)

    def get_version(self, version_id):
        for version in self.versions:
            if version["id"] == version_id:
                return version
        raise KeyError(version_id)

    def resolve_version(self, version_id):
        try:
            return self.get_version(version_id)
        except KeyError:
            return None


def register_grid_versions(cat: FakeCatalog, version_ids: list[str]) -> None:
    """Pre-register the factor grid versions a product consumes (the real
    catalog holds them as DERIVED versions of interpolation runs)."""
    for vid in version_ids:
        cat.seq += 1
        asset_id = f"asset_{cat.seq:06d}"
        cat.seq += 1
        cat.assets.append({
            "id": asset_id, "name": f"grid-{vid}", "type": "factor_grid",
            "format": "npz", "asset_metadata": {},
        })
        cat.versions.append({
            "id": vid, "asset_id": asset_id, "name": f"grid-{vid}",
            "stage": "derived", "run_id": "", "sha256": "grid-" + vid,
            "version_metadata": {},
        })


def stage_payload(name: str, text: str) -> Path:
    path = Path(f"/tmp/pwb-closure-oracle-{name}.json")
    path.write_text(text, encoding="utf-8")
    return path


class _FrozenDatetime(datetime.datetime):
    """models._now_iso() reads the module-global ``datetime`` at call time
    (the qc generator's trick) — default_factory bound it at class
    definition time, so patching the function alone is not enough."""

    @classmethod
    def now(cls, tz=None):
        return datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def install_id_factory() -> None:
    seq = {"n": 0}

    def fake_id(prefix: str) -> str:
        seq["n"] += 1
        return f"{prefix}_frozen{seq['n']:03d}"

    pm._id = fake_id
    pm._now_iso = lambda: FROZEN_NOW
    pm.datetime = _FrozenDatetime


def make_project() -> pm.ProjectDocument:
    doc = pm.ProjectDocument.new("P", "R")
    doc.factor_map_tasks = [
        pm.FactorMapTask(
            id="factor_1", name="物源综合", target_horizon="H1",
            factor_type="重矿物ZTR", method="idw", source_kind="real",
            parameters={"power": 2, "unit": "ratio"},
            quality_metrics={"unit": "ratio", "variance_min": 0.01},
            grid_artifact_version_id="ver_grid1"),
        pm.FactorMapTask(
            id="factor_2", name="古流向", target_horizon="H1",
            factor_type="古流向", method="kriging", source_kind="real",
            parameters={"unit": "deg"},
            quality_metrics={"unit": "deg"},
            grid_artifact_version_id="ver_grid2"),
        pm.FactorMapTask(
            id="factor_mock", name="模拟因子", target_horizon="H1",
            factor_type="mock", method="idw", source_kind="mock",
            grid_artifact_version_id="ver_mock"),
        pm.FactorMapTask(
            id="factor_nogrid", name="无网格因子", target_horizon="H1",
            factor_type="x", method="idw", source_kind="real"),
    ]
    return doc


def snapshot_catalog(cat: FakeCatalog) -> dict:
    return {
        "runs": cat.runs,
        "assets": cat.assets,
        "versions": cat.versions,
    }


def record_to_json(record) -> dict:
    return json.loads(record.model_dump_json())


def case_fingerprint() -> dict:
    doc = make_project()
    assembly = MapProductAssembly(
        product_name="古地理图 A",
        factor_task_ids=["factor_1", "factor_2"],
        interpretation_refs=["b-interp", "a-interp"],
        composition_ref="comp-1",
        manual_adjustments=[
            {"author": "张", "what": "调整边界", "why": "专家判读"},
            {"author": "李", "what": "补充标注", "why": "专家判读"},
        ],
        fusion_version_id="ver_fusion1",
        integrated_interpretation_id="ii_1",
        input_set_id="set_1",
    )
    return {
        "id": "fingerprint",
        "input": {"assembly": assembly.__dict__ | {"composition_ref": assembly.composition_ref},
                  "project": doc.model_dump()},
        "expected": {"scientific_fingerprint": assembly.scientific_fingerprint(doc)},
    }


def case_assemble() -> dict:
    doc = make_project()
    cat = FakeCatalog()
    assembly = MapProductAssembly(
        product_name="古地理图 A",
        factor_task_ids=["factor_1", "factor_2"],
        interpretation_refs=["interp_1"],
        manual_adjustments=[{"author": "张", "what": "调整边界"}],
    )
    payload_text = json.dumps({"manifest": True, "product": "古地理图 A"},
                              ensure_ascii=False)
    payload = stage_payload("assemble", payload_text)
    # Freeze the PRE-state tree: the C++ replay assembles into the same
    # starting document (the post-state dump would carry the record).
    project_before = doc.model_dump()
    result = assemble_map_product(doc, assembly=assembly, catalog=cat,
                                  payload_path=payload)
    return {
        "id": "assemble",
        "input": {"assembly": vars(assembly), "project": project_before,
                  "payload": payload_text},
        "expected": {
            "result": {
                "product_name": result.product_name,
                "record_id": result.record_id,
                "output_version_id": result.output_version_id,
                "run_id": result.run_id,
                "scientific_fingerprint": result.scientific_fingerprint,
                "superseded_record_id": result.superseded_record_id,
            },
            "catalog": snapshot_catalog(cat),
            "map_products": [record_to_json(r) for r in doc.map_products],
        },
    }


def refusal_case(case_id: str, doc: pm.ProjectDocument, assembly_kwargs: dict,
                 message: str, catalog=None, payload=None) -> dict:
    assembly = MapProductAssembly(**assembly_kwargs)
    if isinstance(payload, str):
        payload = stage_payload(case_id, payload)
    try:
        assemble_map_product(doc, assembly=assembly, catalog=catalog,
                             payload_path=payload)
        raise AssertionError(f"case {case_id} did not refuse")
    except ValueError as exc:
        frozen_message = str(exc)
    assert frozen_message == message, (frozen_message, message)
    return {
        "id": case_id,
        "input": {"assembly": assembly_kwargs,
                  "project": doc.model_dump(),
                  "payload": payload},
        "expected": {"error": {"type": "ValueError", "message": message}},
    }


def case_refusals() -> list[dict]:
    doc = make_project()
    payload = "{}"
    cat = FakeCatalog()
    return [
        refusal_case(
            "refuse_no_factors", doc,
            {"product_name": "X", "factor_task_ids": []},
            "map product needs at least one factor task",
            catalog=cat, payload=payload),
        refusal_case(
            "refuse_unknown_task", doc,
            {"product_name": "X", "factor_task_ids": ["nope"]},
            "unknown factor task 'nope'",
            catalog=cat, payload=payload),
        refusal_case(
            "refuse_mock_source", doc,
            {"product_name": "X", "factor_task_ids": ["factor_mock"]},
            "factor task 'factor_mock' is mock; synthetic factors cannot "
            "enter a product",
            catalog=cat, payload=payload),
        refusal_case(
            "refuse_no_grid", doc,
            {"product_name": "X", "factor_task_ids": ["factor_nogrid"]},
            "factor task 'factor_nogrid' has no persisted grid version; "
            "re-run its interpolation before assembling a product",
            catalog=cat, payload=payload),
        refusal_case(
            "refuse_no_catalog", doc,
            {"product_name": "X", "factor_task_ids": ["factor_1"]},
            "map product assembly requires the data catalog",
            catalog=None, payload=payload),
        refusal_case(
            "refuse_no_payload", doc,
            {"product_name": "X", "factor_task_ids": ["factor_1"]},
            "map product assembly needs a staged payload file",
            catalog=cat, payload=None),
    ]


def case_failed_output() -> dict:
    doc = make_project()
    cat = FakeCatalog(fail_output=True)
    assembly = MapProductAssembly(product_name="X",
                                  factor_task_ids=["factor_1"])
    try:
        assemble_map_product(doc, assembly=assembly, catalog=cat,
                             payload_path=stage_payload("failout", "{}"))
        raise AssertionError("failed output case did not raise")
    except RuntimeError as exc:
        error = f"RuntimeError: {exc}"
    return {
        "id": "failed_output_registration",
        "input": {"assembly": vars(assembly), "project": doc.model_dump(),
                  "payload": "{}"},
        "expected": {"error": error, "catalog": snapshot_catalog(cat),
                     "map_products": [record_to_json(r)
                                      for r in doc.map_products]},
    }


def case_lifecycle() -> dict:
    doc = make_project()
    cat = FakeCatalog()
    register_grid_versions(cat, ["ver_grid1", "ver_grid2"])
    # Freeze the PRE-state: the C++ replay starts from the same tree
    # before this case's mutations.
    project_before = doc.model_dump()
    assembly = MapProductAssembly(product_name="X",
                                  factor_task_ids=["factor_1", "factor_2"])
    assemble_map_product(doc, assembly=assembly, catalog=cat,
                         payload_path=stage_payload("lifecycle", "{}"))
    record = doc.map_products[0]
    clone = clone_map_product(record, doc)
    review_map_product(record, doc, catalog=cat)
    freeze_map_product(record)
    lifecycle = {
        "record": effective_lifecycle(record),
        "clone": effective_lifecycle(clone),
    }
    # staleness BEFORE any change
    stale_before = product_staleness(record, doc)
    # change a factor grid → stale
    doc.factor_map_tasks[0].grid_artifact_version_id = "ver_grid9"
    stale_after = product_staleness(record, doc)
    compare = compare_map_products(record, clone, doc, catalog=cat)
    try:
        supersede_map_product(record, doc, successor=clone)
        supersede_error = None
    except ValueError as exc:
        supersede_error = str(exc)
    return {
        "id": "lifecycle",
        "input": {"project": project_before},
        "expected": {
            "lifecycle": lifecycle,
            "stale_before": stale_before,
            "stale_after": stale_after,
            "compare": compare,
            "supersede_error_on_frozen": supersede_error,
            "map_products": [record_to_json(r) for r in doc.map_products],
        },
    }


def case_rerun() -> dict:
    doc = make_project()
    cat = FakeCatalog()
    project_before = doc.model_dump()
    assembly = MapProductAssembly(product_name="X",
                                  factor_task_ids=["factor_1"])
    assemble_map_product(doc, assembly=assembly, catalog=cat,
                         payload_path=stage_payload("rerun1", "{}"))
    record = doc.map_products[0]
    result = rerun_map_product(doc, record=record, catalog=cat,
                               payload_path=stage_payload("rerun2", "{}"))
    return {
        "id": "rerun",
        "input": {"project": project_before},
        "expected": {
            "result": {
                "record_id": result.record_id,
                "superseded_record_id": result.superseded_record_id,
            },
            "map_products": [record_to_json(r) for r in doc.map_products],
            "catalog": snapshot_catalog(cat),
        },
    }


def main() -> int:
    install_id_factory()
    cases = [
        case_fingerprint(),
        case_assemble(),
        *case_refusals(),
        case_failed_output(),
        case_lifecycle(),
        case_rerun(),
    ]
    fixture = {
        "generator": "tools/oracle/generate_closure_map_product_fixtures.py",
        "frozen_from": "paleo_workbench.workflow.map_product",
        "cases": cases,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fixture, ensure_ascii=False, indent=1, sort_keys=True,
                      default=str)
    FIXTURE.write_text(text + "\n", encoding="utf-8")
    print(f"frozen {len(cases)} cases -> {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
