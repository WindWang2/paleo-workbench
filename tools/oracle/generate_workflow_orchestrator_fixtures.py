#!/usr/bin/env python3
"""Generate the frozen workflow orchestrator oracle for CONV-33 (route A4).

Drives the REAL Python implementation
(paleo_workbench.workflow.orchestrator.WorkflowOrchestrator) through
public-API call sequences (get_step_context / next_step) and freezes
every observable: step contexts (Chinese step names, is_valid trap —
warning/running also count as valid), advancement / rejection messages
verbatim, cursor indices, and the terminal completion message.

Covers the three basic cases of tests/test_workflow_orchestrator.py plus
the orchestrator scenarios of tests/test_issue847_workflow_honesty.py
(empty project never walks to 已完成 — audit #847-2; advance refused when
the current step has no evidence; payload parameter accepted but ignored)
and a rejection probe at every gate of the strip.

API-boundary note (frozen contract, 33-decisions D8): the C++ header has
no cursor setter, and its project is a Json COPY — Python reaches the
prerequisite-rejection branch (非首步 + 空资源清单) only by mutating the
shared project object between calls or poking current_step_index. That
one case is frozen here for documentation with "cpp_replay": false; the
C++ replay reports it as an acknowledged boundary instead of replaying.

Determinism: same seam as the service generator (fixed datetime class +
counter ids); re-run must be byte-identical.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime as _real_datetime
from datetime import timezone as _timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.project.models as pmodels  # noqa: E402


class _FixedDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        return _real_datetime(2026, 1, 1, tzinfo=_timezone.utc)


pmodels.datetime = _FixedDatetime

_counter = [0]


def _counter_id(prefix: str) -> str:
    _counter[0] += 1
    return f"{prefix}_{_counter[0]:012d}"


pmodels._id = _counter_id

from paleo_workbench.project.models import (  # noqa: E402
    ExportArtifact,
    FactorMapTask,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ProjectMeta,
    QualityReport,
    ResourceItem,
)
from paleo_workbench.workflow.orchestrator import WorkflowOrchestrator  # noqa: E402

FIXTURE = (
    ROOT
    / "libs/workflow_runtime/workflow_runtime_tests/fixtures/"
    "workflow_orchestrator_oracle.json"
)

cases: list[dict] = []


def add(cid: str, inp: dict, expect: dict) -> None:
    cases.append(
        {"id": cid, "fn": "orchestrator.sequence", "input": inp, "expect": expect}
    )


SECTIONS = ("resources", "factor_map_tasks", "prediction_tasks",
            "paleomap_documents", "quality_reports", "export_artifacts")


def project_view(project) -> dict:
    dump = project.model_dump()
    return {key: dump[key] for key in SECTIONS}


def new_project(name: str = "Demo") -> ProjectDocument:
    return ProjectDocument(meta=ProjectMeta(name=name))


def run_sequence(orchestrator: WorkflowOrchestrator, calls: list) -> list:
    out = []
    for call in calls:
        if call == "ctx":
            out.append(asdict(orchestrator.get_step_context()))
        elif call == "next":
            res = orchestrator.next_step()
            out.append(
                {
                    "success": res.success,
                    "message": res.message,
                    "step_context": asdict(res.step_context),
                    "index_after": orchestrator.current_step_index,
                }
            )
        elif isinstance(call, dict) and "next_payload" in call:
            # step_payload is accepted but ignored (orchestrator.py L81).
            res = orchestrator.next_step(step_payload=call["next_payload"])
            out.append(
                {
                    "success": res.success,
                    "message": res.message,
                    "step_context": asdict(res.step_context),
                    "index_after": orchestrator.current_step_index,
                }
            )
        elif isinstance(call, dict) and "set_index" in call:
            orchestrator.current_step_index = call["set_index"]
            out.append({"set_index": call["set_index"]})
        else:
            raise AssertionError(f"unknown call {call!r}")
    return out


def full_evidence_project(*, qc_status: str = "pass",
                          with_export: bool = True) -> ProjectDocument:
    project = new_project()
    project.resources.append(
        ResourceItem(name="A1.Las", path="a.las", type="well_log", format="las")
    )
    project.factor_map_tasks.append(
        FactorMapTask(name="sand", target_horizon="H1", factor_type="sand",
                      method="IDW", status="complete")
    )
    project.prediction_tasks.append(PredictionTask(name="p1", status="complete"))
    doc = PaleoMapDocument(name="M1", linked_target_horizon="H1")
    project.paleomap_documents.append(doc)
    issues = (
        [{"rule": "facies_polygons_present", "severity": "warning",
          "message": "无相带多边形"}]
        if qc_status == "warning"
        else []
    )
    project.quality_reports.append(
        QualityReport(linked_map_document_id=doc.id, status=qc_status,
                      issues=issues)
    )
    if with_export:
        project.export_artifacts.append(
            ExportArtifact(linked_id=doc.id, format="geojson",
                           output_path="exports/map.geojson")
        )
    return project


# ------------------------------------------------- basic three cases ----

# 1. initial context (empty project, explicit).
project = new_project("Test")
orch = WorkflowOrchestrator(project=project)
calls = ["ctx"]
add(
    "initial_context_empty_project",
    {"project": project_view(project), "calls": calls},
    {"result": run_sequence(orch, calls)},
)

# 2. default construction (no project argument): Python substitutes
# ProjectDocument(meta=ProjectMeta(name="Default Project")); the C++
# Json-seam equivalent is the empty object (33-decisions D4) — status
# inference only reads the evidence sections.
orch = WorkflowOrchestrator()
calls = ["ctx"]
add(
    "default_project_context",
    {"project": None, "calls": calls},
    {"result": run_sequence(orch, calls)},
)

# 3. successful advancement with resources.
project = new_project("Test")
project.resources.append(
    ResourceItem(name="Well-01", type="well_log", format="las", path="/tmp/well.las")
)
orch = WorkflowOrchestrator(project=project)
calls = ["next", "ctx"]
res = run_sequence(orch, calls)
assert res[0]["success"] is True and res[1]["step_id"] == "factor_map"
add(
    "successful_advancement",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)


# --------------------------------------------- issue847 honesty batch --

# Empty project must never walk the strip to 已完成 (audit #847-2).
project = new_project("Demo")
orch = WorkflowOrchestrator(project=project)
calls = ["next"] * 8
res = run_sequence(orch, calls)
assert all(not r["success"] for r in res)
add(
    "empty_project_never_advances",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)

# Advance past data_check, then get refused at factor_map (no evidence).
project = new_project("Demo")
project.resources.append(
    ResourceItem(name="A1.las", path="a.las", type="well_log", format="las")
)
orch = WorkflowOrchestrator(project=project)
calls = ["next", "ctx", "next", "ctx"]
res = run_sequence(orch, calls)
assert res[0]["success"] is True
assert res[2]["success"] is False and res[3]["step_id"] == "factor_map"
add(
    "refused_when_current_step_lacks_evidence",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)

# Evidence-complete steps keep advancing (issue847 advance case).
project = full_evidence_project()
orch = WorkflowOrchestrator(project=project)
calls = ["next", "next"]
res = run_sequence(orch, calls)
assert res[0]["success"] and res[1]["success"]
add(
    "advances_when_step_evidence_complete",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)

# Full walk: contexts at all six steps, five advances, terminal message.
project = full_evidence_project()
orch = WorkflowOrchestrator(project=project)
calls = ["ctx", "next", "ctx", "next", "ctx", "next", "ctx", "next", "ctx",
         "next", "ctx", "next"]
res = run_sequence(orch, calls)
assert res[-1]["success"] and res[-1]["message"] == "工作流已全部完成"
add(
    "full_walk_to_completion",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)

# A warning-status QC gate is still evidence-valid (is_valid trap L65);
# the walk passes through qc and is then refused at pending export.
project = full_evidence_project(qc_status="warning", with_export=False)
orch = WorkflowOrchestrator(project=project)
calls = ["next", "next", "next", "next", "ctx", "next", "ctx", "next"]
res = run_sequence(orch, calls)
qc_ctx = res[4]
assert qc_ctx["step_id"] == "qc" and qc_ctx["status"] == "warning"
assert qc_ctx["is_valid"] is True
assert res[5]["success"] is True
assert res[7]["success"] is False
add(
    "warning_step_is_valid_gate",
    {"project": project_view(project), "calls": calls},
    {"result": res},
)

# step_payload is accepted but ignored: identical result shape.
project = full_evidence_project()
orch = WorkflowOrchestrator(project=project)
calls = [{"next_payload": {"anything": [1, 2, 3], "note": "ignored"}}]
add(
    "payload_parameter_ignored",
    {"project": project_view(project), "calls": calls},
    {"result": run_sequence(orch, calls)},
)

# Prerequisite rejection (数据资产清单不能为空): frozen for documentation —
# reachable in Python only by poking the cursor (or mutating the shared
# project between calls); the frozen C++ contract has no cursor setter
# and owns its project by value (D8), so the C++ replay cannot drive it.
project = new_project("Test")
orch = WorkflowOrchestrator(project=project)
calls = [{"set_index": 1}, "ctx", "next"]
res = run_sequence(orch, calls)
assert res[1]["prerequisites"] == ["数据资产清单不能为空"]
assert res[2]["success"] is False
add(
    "prerequisite_rejection_no_resources",
    {"project": project_view(project), "calls": calls,
     "cpp_replay": False,
     "cpp_boundary": "frozen header has no cursor setter and holds the "
                     "project by value (D8); branch verified on the "
                     "Python side only"},
    {"result": res},
)

# ---------------------------------------------------------------- write
FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {len(cases)} cases to {FIXTURE}")
