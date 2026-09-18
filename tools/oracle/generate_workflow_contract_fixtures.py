#!/usr/bin/env python3
"""Generate the frozen workflow/contracts oracle for CONV-23.

Drives the REAL Python implementation (paleo_workbench.workflow.contracts)
and freezes: contract model_dumps, completeness maps, registry semantics,
validation issues, metadata-readiness reports (three production-model probe
paths included), and both report texts. Also emits
``libs/workflow_contracts/src/modules_data.inc`` — the declaration table the
C++ build embeds (same generated-data precedent as lower_map.inc /
word_char_ranges.inc).

Deterministic: re-run must be byte-identical (CI checks the diff).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paleo_workbench.workflow.contracts.models import (  # noqa: E402
    DomainWorkflowContract,
    WorkflowInputSpec,
)
from paleo_workbench.workflow.contracts.readiness import (  # noqa: E402
    evaluate_contract_readiness,
    evaluate_readiness,
)
from paleo_workbench.workflow.contracts.registry import (  # noqa: E402
    WorkflowContractRegistry,
)
from paleo_workbench.workflow.contracts.report import (  # noqa: E402
    generate_consultation_report,
    generate_gap_report,
)
from paleo_workbench.workflow.contracts.modules import (  # noqa: E402
    build_all_contracts,
)

FIXTURE = (
    ROOT
    / "libs/workflow_contracts/workflow_contracts_tests/fixtures/workflow_contract_oracle.json"
)
INC = ROOT / "libs/workflow_contracts/src/modules_data.inc"

cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def dump(c: DomainWorkflowContract) -> dict:
    return c.model_dump(mode="json")


# ---------------------------------------------------------------------------
# contracts / completeness
# ---------------------------------------------------------------------------

CONTRACTS = build_all_contracts()
for c in CONTRACTS:
    add(f"cd_{c.id}", "contract_dump", {"id": c.id}, {"result": dump(c)})
    add(f"cmp_{c.id}", "completeness", {"id": c.id},
        {"result": c.completeness()})

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

REG = WorkflowContractRegistry()
add("reg_list", "list_contracts", {},
    {"result": [c.id for c in REG.list_contracts()]})
add("reg_get_hit", "get_contract", {"id": "factor_interpolation"},
    {"result": dump(REG.get_contract("factor_interpolation"))})
add("reg_get_miss", "get_contract", {"id": "nope"}, {"result": None})
add("reg_by_cat", "contracts_by_category", {"category": "factor"},
    {"result": [c.id for c in REG.contracts_by_category("factor")]})
add("reg_by_cat_miss", "contracts_by_category", {"category": "zzz"},
    {"result": []})
add("reg_up", "upstream", {"id": "paleomap_compile"},
    {"result": [c.id for c in REG.upstream("paleomap_compile")]})
add("reg_down", "downstream", {"id": "factor_interpolation"},
    {"result": [c.id for c in REG.downstream("factor_interpolation")]})
add("reg_up_unknown", "upstream", {"id": "nope"}, {"result": []})
add("reg_questions", "all_expert_questions", {},
    {"result": [q.id for q in REG.all_expert_questions()]})
add("reg_p0", "p0_ids", {}, {"result": REG.p0_ids()})
add("reg_issues", "validation_issues", {},
    {"result": list(REG.validation_issues())})
add("reg_dup", "duplicate_registry", {},
    {"raises": "ValueError", "message": "duplicate contract id: dup"})


# ---------------------------------------------------------------------------
# custom registries → validate_registry issue text
# ---------------------------------------------------------------------------

def spec(id_: str, **kw) -> dict:
    d = {"id": id_, "name": id_}
    d.update(kw)
    return d


CUSTOM_SETS = {
    "missing_mirror": [
        spec("a", upstream_contract_ids=["b"], downstream_contract_ids=[]),
        spec("b", upstream_contract_ids=[], downstream_contract_ids=[]),
    ],
    "unknown_edges": [
        spec("a", upstream_contract_ids=["ghost"], downstream_contract_ids=["phantom"]),
    ],
    "bad_datarun_op": [
        spec("a", datarun_operations=["factor_map", "bogus_op"]),
    ],
    "missing_expected_op": [
        spec("factor_interpolation", datarun_operations=["prediction"]),
    ],
    "param_needs_question": [
        spec("a", parameters=[{"id": "p1", "name": "P",
                               "certainty": "EXPERT_CONFIRMATION_REQUIRED"}]),
    ],
    "empty_question": [
        spec("a", expert_questions=[{"id": "q1", "module_id": "a",
                                     "category": "INPUT", "question": "  "}]),
    ],
    "evidence_no_path": [
        spec("a", expert_questions=[{"id": "q1", "module_id": "a",
                                     "category": "QC", "question": "Q?",
                                     "source_evidence": [{"path": ""}]}]),
    ],
    "clean_pair": [
        spec("a", downstream_contract_ids=["b"]),
        spec("b", upstream_contract_ids=["a"]),
    ],
}
for name, specs in CUSTOM_SETS.items():
    reg = WorkflowContractRegistry(
        [DomainWorkflowContract(**s) for s in specs]
    )
    add(f"cr_{name}", "custom_registry", {"contracts": specs},
        {"result": list(reg.validation_issues())})


# ---------------------------------------------------------------------------
# readiness — project duck-type built from JSON-shaped specs
# ---------------------------------------------------------------------------

def ns(project: dict):
    """Project spec → attribute object graph.

    Only *record positions* become SimpleNamespace (the project root, list
    elements, and nested record attrs like stratigraphy/meta). Dict-valued
    fields such as ``parameters`` / ``view_state`` / ``depth_domains`` stay
    dicts — production models store plain dicts there and readiness calls
    ``.get`` on them (conv-21's getattr-parity lesson).
    """
    out = {}
    for k, v in project.items():
        if isinstance(v, list):
            out[k] = [types.SimpleNamespace(**x) if isinstance(x, dict) else x
                      for x in v]
        elif isinstance(v, dict):
            out[k] = types.SimpleNamespace(**v)
        else:
            out[k] = v
    return types.SimpleNamespace(**out)


class Probe:
    """find_production_model stub for the facies_prediction catalog seam."""

    def __init__(self, mode: str):
        self.mode = mode

    def find_production_model(self, capability):
        if self.mode == "model":
            return {"asset_id": "m1"}
        if self.mode == "none":
            return None
        raise RuntimeError("store exploded")


def res(t: str, status: str = "indexed", path: str = "") -> dict:
    return {"type": t, "status": status, "path": path}


def task(status: str = "complete", sample_points=None, target_horizon="",
         adapter_kind: str | None = None) -> dict:
    d: dict = {"status": status,
               "parameters": {} if sample_points is None else
               {"sample_points": sample_points},
               "target_horizon": target_horizon}
    if adapter_kind is not None:
        d["adapter_kind"] = adapter_kind
    return d


def doc(linked: str = "", demo: bool = False) -> dict:
    return {"linked_target_horizon": linked,
            "view_state": {"is_demo_draft": demo}}


def readiness_case(cid: str, contract_id: str, project: dict,
                   probe: str = "model") -> None:
    # probe="unset" exercises Python's catalog=None → get_catalog_service()
    # fallback (returns None in a bare process → "目录未连接").
    catalog = None if probe == "unset" else Probe(probe)
    add(cid, "readiness",
        {"contract_id": contract_id, "project": project, "probe": probe},
        {"result": evaluate_readiness(ns(project), contract_id,
                                      catalog=catalog).to_dict()})


EMPTY: dict = {}

# generic required-input paths
readiness_case("rd_empty_factor", "factor_interpolation", EMPTY)
readiness_case(
    "rd_wells_one", "well_correlation",
    {"resources": [res("well_log"), res("well_log")]})
# depth-domain mismatch is judged PER interpretation ref, not globally.
readiness_case(
    "rd_wells_depth_mismatch", "well_correlation",
    {"resources": [res("well_log")] * 3,
     "correlation_interpretations": [{"depth_domains": ["depth", "tvdss"]}]})
readiness_case(
    "rd_wells_per_ref_domains", "well_correlation",
    {"resources": [res("well_log"), res("well_log")],
     "correlation_interpretations": [{"depth_domain": "depth"},
                                     {"depth_domain": "tvdss"}]})
# EXACTLY_ONE + required + resource_types → ambiguous_input warn at n > 1.
readiness_case(
    "rd_seismic_ambiguous", "seismic_volume",
    {"resources": [res("seismic"), res("seismic")]})
readiness_case(
    "rd_factor_no_pts", "factor_interpolation",
    {"resources": [res("well_log"), res("seismic")],
     "factor_map_tasks": [task(sample_points=None, target_horizon="H1")]})
readiness_case(
    "rd_factor_no_horizon", "factor_interpolation",
    {"resources": [res("well_log"), res("seismic")],
     "factor_map_tasks": [task(sample_points=[[1, 2, 3]])]})
readiness_case(
    "rd_factor_ready", "factor_interpolation",
    {"resources": [res("well_log"), res("seismic")],
     "factor_map_tasks": [task(sample_points=[[1, 2, 3]],
                               target_horizon="H1")]})
readiness_case("rd_paleomap_empty", "paleomap_compile",
               {"factor_map_tasks": [task()]})
readiness_case(
    "rd_paleomap_no_link", "paleomap_compile",
    {"factor_map_tasks": [task()], "paleomap_documents": [doc("")],
     "stratigraphy": {"target_horizon": "H1"}})
readiness_case(
    "rd_paleomap_demo", "paleomap_compile",
    {"factor_map_tasks": [task()], "paleomap_documents": [doc("H1", True)]})
readiness_case("rd_facies_demo", "facies_prediction", EMPTY)
readiness_case(
    "rd_facies_mock", "facies_prediction",
    {"prediction_tasks": [{"adapter_kind": "mock"}]})
readiness_case(
    "rd_facies_prod_model", "facies_prediction",
    {"factor_map_tasks": [task()]}, probe="model")
readiness_case(
    "rd_facies_no_model", "facies_prediction",
    {"factor_map_tasks": [task()]}, probe="none")
readiness_case(
    "rd_facies_catalog_err", "facies_prediction",
    {"factor_map_tasks": [task()]}, probe="raise")
readiness_case(
    "rd_facies_catalog_none", "facies_prediction",
    {"factor_map_tasks": [task()]}, probe="unset")
readiness_case("rd_qc_empty", "quality_control", EMPTY)
readiness_case("rd_export_empty", "export", EMPTY)
readiness_case("rd_geomodel", "geomodel_3d", EMPTY)
readiness_case("rd_unknown_contract", "not_a_module", EMPTY)
readiness_case(
    "rd_missing_resource", "well_log_ingest",
    {"resources": [res("well_log", status="missing")]})
readiness_case(
    "rd_sample_points_meta", "factor_interpolation",
    {"resources": [res("well_log"), res("seismic")],
     "factor_map_tasks": [{"status": "complete",
                           "parameters": {"sample_points": [[0, 0, 0]]},
                           "target_horizon": "H"}]})


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

add("rep_consult", "report_consultation", {},
    {"result": generate_consultation_report()})
add("rep_consult_project", "report_consultation",
    {"project": {"factor_map_tasks": [task(sample_points=[[1, 2, 3]],
                                          target_horizon="H1")],
                 "paleomap_documents": [doc("H1")]}},
    {"result": generate_consultation_report(
        project=ns({"factor_map_tasks": [task(sample_points=[[1, 2, 3]],
                                             target_horizon="H1")],
                    "paleomap_documents": [doc("H1")]}))})
add("rep_gap", "report_gap", {}, {"result": generate_gap_report()})


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

FIXTURE.parent.mkdir(parents=True, exist_ok=True)
with FIXTURE.open("w", encoding="utf-8", newline="\n") as f:
    json.dump({"cases": cases}, f, ensure_ascii=False, indent=1)
    f.write("\n")

modules_json = json.dumps([dump(c) for c in CONTRACTS],
                          ensure_ascii=False, separators=(",", ":"))
INC.parent.mkdir(parents=True, exist_ok=True)
with INC.open("w", encoding="utf-8", newline="\n") as f:
    f.write("// Generated by tools/oracle/generate_workflow_contract_fixtures.py\n")
    f.write("// Frozen declarations of workflow/contracts/modules.py — do not edit.\n")
    f.write('R"PWB_MODULES_JSON(')
    f.write(modules_json)
    f.write(')PWB_MODULES_JSON"\n')

print(f"wrote {FIXTURE} ({len(cases)} cases) + {INC} "
      f"({len(CONTRACTS)} contracts, {len(modules_json)} json bytes)")
