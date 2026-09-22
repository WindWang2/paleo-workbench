#!/usr/bin/env python3
"""Generate the frozen workflow service oracle for CONV-33 (route A4).

Drives the REAL Python implementation (paleo_workbench.workflow.service)
with deterministic ids/timestamps and fake catalogs, freezing every
observable: evidence step statuses, freshness overlay results,
home_workflow_steps round-trips (in-place run writeback included),
create_compilation_run stamps, dashboard_state aggregation, recompute
plans and downstream impact rows.

Coverage boundary (honest): the C++ composition of FreshnessService from
a project mirrors FreshnessService.for_project's degraded branch —
catalog graph + last-tip-per-asset context (resolve_current_project_
version_context with service=None and no project overlay). The
project-side resolve overlay (horizon/correlation/fault refs, factor
grid pointers) belongs to the un-ported A3 resolve face, so every
fixture project here avoids those sections and keeps run.domain_task_id
distinct from any task id (no expected-identity collisions).

Determinism: paleo_workbench.project.models._now_iso is pinned to a fixed
constant and _id to a global counter; re-run must be byte-identical.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime as _real_datetime
from datetime import timezone as _timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.project.models as pmodels  # noqa: E402

# Determinism seam. _id is resolved lazily by the default_factory lambdas
# (module global at call time), but _now_iso was captured DIRECTLY as a
# default_factory — pydantic 2.13 bakes it into the compiled validator,
# so patching the module symbol or the FieldInfo does nothing. The
# datetime CLASS itself is the only seam _now_iso reads at call time.
_NOW = "2026-01-01T00:00:00+00:00"


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
    CompilationRun,
    ExportArtifact,
    FactorMapTask,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ProjectMeta,
    QualityReport,
    ResourceItem,
    WorkflowStep,
)
from paleo_workbench.workflow import service as wf_service  # noqa: E402

FIXTURE = (
    ROOT
    / "libs/workflow_runtime/workflow_runtime_tests/fixtures/"
    "workflow_service_oracle.json"
)

cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


# The Json-seam section view the C++ replay reconstructs from (missing
# section == empty; the Python side works on full models).
SECTIONS = (
    "meta",
    "stratigraphy",
    "resources",
    "factor_map_tasks",
    "prediction_tasks",
    "paleomap_documents",
    "quality_reports",
    "compilation_runs",
    "export_artifacts",
)


def project_view(project: ProjectDocument) -> dict:
    dump = project.model_dump()
    return {key: dump[key] for key in SECTIONS}


# ------------------------------------------------------------- fakes ----


class FakeVersion(types.SimpleNamespace):
    """DataVersionRef-shaped record with checksum/trashed/path."""


class FakeCatalog:
    """CatalogPort-shaped fake: list/list/resolve seam.

    fail_listing  — list_versions/list_runs raise (composition failure).
    resolve_boom  — resolve_version raises (probe failure, audit #847-3).
    """

    def __init__(self, versions, runs, *, fail_listing=False, resolve_boom=False):
        self._versions = list(versions)
        self._runs = list(runs)
        self.fail_listing = fail_listing
        self.resolve_boom = resolve_boom
        self._by_id = {v.version_id: v for v in self._versions}

    def list_versions(self):
        if self.fail_listing:
            raise RuntimeError("catalog listing exploded")
        return list(self._versions)

    def list_runs(self):
        if self.fail_listing:
            raise RuntimeError("catalog listing exploded")
        return list(self._runs)

    def resolve_version(self, version_id: str):
        if self.resolve_boom:
            raise RuntimeError("catalog backend exploded")
        return self._by_id.get(version_id)

    def resolve_run(self, run_id: str):
        return None

    def verify_integrity(self, version_id: str):
        return None


def spec_version(spec: dict) -> FakeVersion:
    return FakeVersion(
        asset_id=spec["asset_id"],
        version_id=spec["version_id"],
        name=spec.get("name", ""),
        producing_run_id=spec.get("producing_run_id"),
        checksum=spec.get("checksum"),
        trashed=spec.get("trashed", False),
        path=spec.get("path", ""),
        created_at=spec.get("created_at", "2026-01-01T00:00:00"),
    )


def spec_run(spec: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        run_id=spec["run_id"],
        operation=spec.get("operation", ""),
        input_version_ids=spec.get("input_version_ids") or [],
        output_version_ids=spec.get("output_version_ids") or [],
        parameters=spec.get("parameters"),
        generator_version=spec.get("generator_version"),
        status=spec.get("status", "running"),
        started_at=spec.get("started_at", "2026-01-01T00:00:00"),
        finished_at=spec.get("finished_at"),
        domain_task_id=spec.get("domain_task_id"),
        input_snapshot_hash=spec.get("input_snapshot_hash"),
    )


def fake_catalog(spec: dict) -> FakeCatalog:
    return FakeCatalog(
        [spec_version(v) for v in spec.get("versions", [])],
        [spec_run(r) for r in spec.get("runs", [])],
        fail_listing=spec.get("fail_listing", False),
        resolve_boom=spec.get("resolve_boom", False),
    )


# ------------------------------------------------------ model builders --


def new_project(name: str = "Demo") -> ProjectDocument:
    return ProjectDocument(meta=ProjectMeta(name=name))


def add_resource(project, name: str, type_: str, fmt: str) -> None:
    project.resources.append(
        ResourceItem(name=name, path=f"data/{name}", type=type_, format=fmt)
    )


def factor_task(status: str, name: str = "sand") -> FactorMapTask:
    return FactorMapTask(
        name=name,
        target_horizon="H1",
        factor_type="sand",
        method="IDW",
        status=status,
    )


def prediction_task(status: str, name: str = "p1") -> PredictionTask:
    return PredictionTask(name=name, status=status)


def map_doc(name: str = "M1") -> PaleoMapDocument:
    return PaleoMapDocument(name=name, linked_target_horizon="H1")


def qc_report(linked: str, status: str, issues=None) -> QualityReport:
    return QualityReport(
        linked_map_document_id=linked,
        rules=["target_horizon_present"],
        issues=issues if issues is not None else [],
        status=status,
    )


def export_artifact(linked: str = "map_1") -> ExportArtifact:
    return ExportArtifact(
        linked_id=linked, format="geojson", output_path="exports/map.geojson"
    )


def build_run(step_specs, *, name="Run", horizon="ZJ2", scheme="scheme",
              status="draft") -> CompilationRun:
    return CompilationRun(
        name=name,
        target_horizon=horizon,
        sequence_scheme_ref=scheme,
        status=status,
        workflow_steps=[
            WorkflowStep(step_type=step_type, status=step_status)
            for step_type, step_status in step_specs
        ],
    )


class BoomFreshness:
    """issue847 shape: step_freshness raises."""

    def step_freshness(self, step_type):
        raise RuntimeError("catalog backend exploded")


def strip_ephemeral_ids(step_dicts):
    """Ids of never-persisted steps are host-side stamps — compare the
    observable (step_type/status) only."""
    out = []
    for entry in step_dicts:
        entry = dict(entry)
        entry.pop("id", None)
        out.append(entry)
    return out


def strip_appended_ids(runs_dump, preexisting_ids):
    """Remove ids the C++ replay cannot predict (freshly stamped during
    the call); pre-existing persisted ids stay frozen."""
    runs_dump = json.loads(json.dumps(runs_dump))
    for run in runs_dump:
        for step in run.get("workflow_steps", []):
            if step.get("id") not in preexisting_ids:
                step.pop("id", None)
    return runs_dump


def steps_view(steps, preexisting_ids):
    wrapped = strip_appended_ids(
        [{"workflow_steps": [s.model_dump() for s in steps]}], preexisting_ids
    )
    return wrapped[0]["workflow_steps"]


# --------------------------------------------- create_compilation_run ---

project = new_project()
input_view = project_view(project)
start = _counter[0]
run = wf_service.create_compilation_run(
    project, name="ZJ2 编图", target_horizon="ZJ2", sequence_scheme="三级层序格架"
)
add(
    "create_run_empty_project",
    "service.create_compilation_run",
    {
        "project": input_view,
        "name": "ZJ2 编图",
        "target_horizon": "ZJ2",
        "sequence_scheme": "三级层序格架",
        "id_counter_start": start,
    },
    {
        "run": run.model_dump(),
        "stratigraphy_after": project.model_dump()["stratigraphy"],
        "compilation_runs_after": project.model_dump()["compilation_runs"],
    },
)

project = new_project()
project.stratigraphy.target_horizon = "H1-old"
project.stratigraphy.systems_tract_scheme = "旧格架"
project.compilation_runs.append(
    build_run([("data_check", "complete")], name="旧 Run", horizon="H1-old",
              scheme="旧格架")
)
input_view = project_view(project)
start = _counter[0]
run = wf_service.create_compilation_run(
    project, name="第二轮", target_horizon="SB3", sequence_scheme="LST/TST/HST"
)
add(
    "create_run_second_appends_and_overwrites",
    "service.create_compilation_run",
    {
        "project": input_view,
        "name": "第二轮",
        "target_horizon": "SB3",
        "sequence_scheme": "LST/TST/HST",
        "id_counter_start": start,
    },
    {
        "run": run.model_dump(),
        "stratigraphy_after": project.model_dump()["stratigraphy"],
        "compilation_runs_after": project.model_dump()["compilation_runs"],
    },
)


# -------------------------------------------------- evidence families ---


def infer_all(project, **kwargs) -> dict:
    return {
        step: wf_service.infer_workflow_step_status(project, step, **kwargs)
        for step in wf_service.STEP_ORDER
    }


# empty project: every step pending (audit #847-2 adjacency — an empty
# strip must never claim progress).
add(
    "infer_empty_project_all_pending",
    "service.infer_workflow_step_status",
    {"project": project_view(new_project()), "steps": list(wf_service.STEP_ORDER)},
    {"result": infer_all(new_project())},
)

# resources only: data_check complete, everything else pending.
project = new_project()
add_resource(project, "A1.Las", "well_log", "las")
add_resource(project, "200P.sgy", "seismic", "sgy")
add_resource(project, "H1.grd", "horizon", "grd")
add(
    "infer_resources_only",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "steps": list(wf_service.STEP_ORDER)},
    {"result": infer_all(project)},
)

# factor_map task-status aggregation matrix (issue847 #1).
factor_matrix = [
    [],
    ["running"],
    ["pending"],
    ["complete"],
    ["failed", "failed"],
    ["complete", "failed"],
    ["error"],
    ["complete", "running"],
]
results = []
for statuses in factor_matrix:
    project = new_project()
    for status in statuses:
        project.factor_map_tasks.append(factor_task(status))
    results.append(
        {
            "factor_map": wf_service.infer_workflow_step_status(
                project, "factor_map"
            ),
        }
    )
add(
    "infer_factor_map_status_matrix",
    "service.infer_workflow_step_status",
    {"step": "factor_map", "matrix": factor_matrix},
    {"result": results},
)

# prediction task-status aggregation matrix (incl. "error").
pred_matrix = [
    [],
    ["running"],
    ["complete"],
    ["failed"],
    ["error"],
    ["complete", "failed"],
]
results = []
for statuses in pred_matrix:
    project = new_project()
    for status in statuses:
        project.prediction_tasks.append(prediction_task(status))
    results.append(
        {
            "prediction": wf_service.infer_workflow_step_status(
                project, "prediction"
            ),
        }
    )
add(
    "infer_prediction_status_matrix",
    "service.infer_workflow_step_status",
    {"step": "prediction", "matrix": pred_matrix},
    {"result": results},
)

# map_compile / export product evidence.
project = new_project()
empty_view = project_view(project)
empty_results = {s: infer_all(project)[s] for s in ("map_compile", "export")}
project.paleomap_documents.append(map_doc())
project.export_artifacts.append(export_artifact())
add(
    "infer_product_steps",
    "service.infer_workflow_step_status",
    {
        "project_empty": empty_view,
        "project_with_products": project_view(project),
        "steps": ["map_compile", "export"],
    },
    {
        "result": {
            "empty": empty_results,
            "with_products": {
                s: wf_service.infer_workflow_step_status(project, s)
                for s in ("map_compile", "export")
            },
        }
    },
)

# qc evidence matrix (active-run binding + error-severity rule L78-83).
qc_specs = [
    {"id": "no_reports", "reports": [], "active": None},
    {"id": "raw_pass", "reports": ["pass:m1"], "active": None},
    {"id": "raw_warning", "reports": ["warning:m1"], "active": None},
    {"id": "raw_error_severity", "reports": ["error:m1"], "active": None},
    {"id": "raw_failed", "reports": ["failed:m1"], "active": None},
    {"id": "two_maps_dedup", "reports": ["pass:m1", "warning:m2"], "active": None},
    {"id": "active_error_wins", "reports": ["pass:m1", "error:m2"], "active": 1},
    {"id": "active_dangling_falls_back", "reports": ["pass:m1"],
     "active": "missing"},
]
qc_inputs = []
qc_results = []
for spec in qc_specs:
    project = new_project()
    doc1 = map_doc("M1")
    doc2 = map_doc("M2")
    project.paleomap_documents.extend([doc1, doc2])
    reports = []
    for entry in spec["reports"]:
        status, _, map_name = entry.partition(":")
        linked = doc1.id if map_name in ("", "m1") else doc2.id
        issues = []
        if status == "warning":
            issues = [
                {"rule": "facies_polygons_present", "severity": "warning",
                 "message": "无相带多边形"}
            ]
        elif status in ("error", "failed"):
            issues = [{"rule": "r", "severity": status, "message": "x"}]
        reports.append(qc_report(linked, status, issues))
    project.quality_reports.extend(reports)
    active = spec["active"]
    if active is not None:
        run_rec = build_run([], name="R", horizon="H1", scheme="s")
        run_rec.active_quality_report_id = (
            reports[active].id if isinstance(active, int) else "qc_missing"
        )
        project.compilation_runs.append(run_rec)
    qc_inputs.append({"id": spec["id"], "project": project_view(project)})
    qc_results.append(
        {
            "id": spec["id"],
            "qc": wf_service.infer_workflow_step_status(project, "qc"),
        }
    )
add(
    "infer_qc_evidence_matrix",
    "service.infer_workflow_step_status",
    {"cases": qc_inputs},
    {"result": qc_results},
)


# ---------------------------------------------------- overlay families --

H1_V1 = {
    "asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1 旧",
    "producing_run_id": None, "created_at": "2026-01-01T00:00:01",
}
H1_V2 = {
    "asset_id": "asset_h1", "version_id": "ver_h1_v2", "name": "H1 新",
    "producing_run_id": None, "created_at": "2026-01-01T00:00:02",
}
F1_V1 = {
    "asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
    "producing_run_id": "run_f1",
}
P1_V1 = {
    "asset_id": "asset_p1", "version_id": "ver_p1_v1", "name": "P1",
    "producing_run_id": "run_p1",
}
M1_V1 = {
    "asset_id": "asset_m1", "version_id": "ver_m1_v1", "name": "M1",
    "producing_run_id": "run_m1",
}
Q1_V1 = {
    "asset_id": "asset_q1", "version_id": "ver_q1_v1", "name": "Q1",
    "producing_run_id": "run_q1",
}
E1_V1 = {
    "asset_id": "asset_e1", "version_id": "ver_e1_v1", "name": "E1",
    "producing_run_id": "run_e1",
    "checksum": "a" * 64,
    "path": "/tmp/pwb-a4-absent.payload",
}


def overlay_project(**evidence) -> ProjectDocument:
    project = new_project()
    if evidence.get("resources"):
        add_resource(project, "A1.Las", "well_log", "las")
    if evidence.get("factor_complete"):
        project.factor_map_tasks.append(factor_task("complete"))
    if evidence.get("prediction_complete"):
        project.prediction_tasks.append(prediction_task("complete"))
    if evidence.get("map_doc"):
        project.paleomap_documents.append(map_doc())
    if evidence.get("qc_pass"):
        doc = map_doc()
        project.paleomap_documents.append(doc)
        project.quality_reports.append(qc_report(doc.id, "pass"))
    if evidence.get("export"):
        project.export_artifacts.append(export_artifact())
    return project


# stale: factor run consumed ver_h1_v1 while the asset tip is ver_h1_v2.
catalog = {
    "versions": [H1_V1, H1_V2, F1_V1],
    "runs": [
        {
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v1"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:05",
        }
    ],
}
project = overlay_project(factor_complete=True)
add(
    "overlay_factor_map_stale",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "step": "factor_map", "catalog": catalog},
    {
        "result": wf_service.infer_workflow_step_status(
            project, "factor_map", catalog=fake_catalog(catalog)
        )
    },
)

# fresh: prediction run consumes the current factor tip.
catalog = {
    "versions": [F1_V1, P1_V1],
    "runs": [
        {
            "run_id": "run_p1", "operation": "prediction",
            "input_version_ids": ["ver_f1_v1"],
            "output_version_ids": ["ver_p1_v1"], "status": "complete",
            "domain_task_id": "task_p1",
            "started_at": "2026-01-01T00:00:06",
        }
    ],
}
project = overlay_project(prediction_complete=True)
add(
    "overlay_prediction_fresh_keeps_complete",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "step": "prediction", "catalog": catalog},
    {
        "result": wf_service.infer_workflow_step_status(
            project, "prediction", catalog=fake_catalog(catalog)
        )
    },
)

# failed: map_compile catalog run failed.
catalog = {
    "versions": [F1_V1, M1_V1],
    "runs": [
        {
            "run_id": "run_m1", "operation": "map_compile",
            "input_version_ids": ["ver_f1_v1"],
            "output_version_ids": ["ver_m1_v1"], "status": "failed",
            "domain_task_id": "task_m1",
            "started_at": "2026-01-01T00:00:07",
        }
    ],
}
project = overlay_project(map_doc=True)
add(
    "overlay_map_compile_failed_run",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "step": "map_compile", "catalog": catalog},
    {
        "result": wf_service.infer_workflow_step_status(
            project, "map_compile", catalog=fake_catalog(catalog)
        )
    },
)

# running: qc catalog run still running.
catalog = {
    "versions": [M1_V1, Q1_V1],
    "runs": [
        {
            "run_id": "run_q1", "operation": "qc",
            "input_version_ids": ["ver_m1_v1"],
            "output_version_ids": ["ver_q1_v1"], "status": "running",
            "domain_task_id": "task_q1",
            "started_at": "2026-01-01T00:00:08",
        }
    ],
}
project = overlay_project(qc_pass=True)
add(
    "overlay_qc_running_run",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "step": "qc", "catalog": catalog},
    {
        "result": wf_service.infer_workflow_step_status(
            project, "qc", catalog=fake_catalog(catalog)
        )
    },
)

# missing payload (check_integrity service injection): export output's
# payload file is hermetically absent -> MISSING -> warning.
catalog = {
    "versions": [M1_V1, E1_V1],
    "runs": [
        {
            "run_id": "run_e1", "operation": "export",
            "input_version_ids": ["ver_m1_v1"],
            "output_version_ids": ["ver_e1_v1"], "status": "complete",
            "domain_task_id": "task_e1",
            "started_at": "2026-01-01T00:00:09",
        }
    ],
    "check_integrity": True,
}
project = overlay_project(export=True)
from paleo_workbench.workflow.freshness import FreshnessService  # noqa: E402

svc_integrity = FreshnessService.for_project(
    project, catalog=fake_catalog(catalog), check_integrity=True
)
add(
    "overlay_export_missing_payload",
    "service.infer_workflow_step_status",
    {
        "project": project_view(project),
        "step": "export",
        "catalog": catalog,
        "freshness_service": "check_integrity",
    },
    {
        "result": wf_service.infer_workflow_step_status(
            project, "export", freshness_service=svc_integrity
        )
    },
)

# probe raises (dangling input + exploding resolve_version) — the broad
# except must degrade to evidence (audit #847-3).
catalog = {
    "versions": [F1_V1],
    "runs": [
        {
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_MISSING"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:10",
        }
    ],
    "resolve_boom": True,
}
project = overlay_project(factor_complete=True)
add(
    "overlay_probe_raises_keeps_evidence",
    "service.infer_workflow_step_status",
    {"project": project_view(project), "step": "factor_map", "catalog": catalog},
    {
        "result": wf_service.infer_workflow_step_status(
            project, "factor_map", catalog=fake_catalog(catalog)
        )
    },
)

# freshness_service that explodes from step_freshness (issue847 #3 shape).
project = overlay_project(factor_complete=True)
add(
    "overlay_service_param_boom",
    "service.infer_workflow_step_status",
    {
        "project": project_view(project),
        "step": "factor_map",
        "catalog": catalog,
        "freshness_service": "boom",
    },
    {
        "result": wf_service.infer_workflow_step_status(
            project, "factor_map", freshness_service=BoomFreshness()
        )
    },
)

# apply_freshness=False short-circuits even with a stale-making catalog.
catalog = {
    "versions": [H1_V1, H1_V2, F1_V1],
    "runs": [
        {
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v1"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:12",
        }
    ],
}
project = overlay_project(factor_complete=True)
add(
    "overlay_short_circuit_apply_freshness_false",
    "service.infer_workflow_step_status",
    {
        "project": project_view(project),
        "step": "factor_map",
        "catalog": catalog,
        "apply_freshness": False,
    },
    {
        "result": wf_service.infer_workflow_step_status(
            project, "factor_map", catalog=fake_catalog(catalog),
            apply_freshness=False,
        )
    },
)


# ------------------------------------------------- home_workflow_steps --

# ephemeral steps (no compilation run): ids are host-side stamps — both
# sides compare type/status only.
project = new_project()
add_resource(project, "A1.Las", "well_log", "las")
project.factor_map_tasks.append(factor_task("complete"))
project.prediction_tasks.append(prediction_task("running"))
project.paleomap_documents.append(map_doc())
project.export_artifacts.append(export_artifact())
steps = wf_service.home_workflow_steps(project)
add(
    "home_ephemeral_no_run",
    "service.home_workflow_steps",
    {"project": project_view(project)},
    {
        "result": {
            "steps": strip_ephemeral_ids([s.model_dump() for s in steps]),
            "compilation_runs_after": project.model_dump()["compilation_runs"],
        }
    },
)

# active-run round-trip without catalog: appended missing steps inherit
# inference, recovered evidence promotes persisted warning to complete
# (#668), untouched pending stays pending.
project = new_project()
project.compilation_runs.append(
    build_run(
        [
            ("data_check", "warning"),   # evidence complete -> promoted
            ("prediction", "pending"),   # no evidence -> stays pending
            ("map_compile", "warning"),  # evidence complete -> promoted
            ("export", "pending"),       # no evidence -> stays pending
        ]  # factor_map + qc missing -> appended
    )
)
add_resource(project, "A1.Las", "well_log", "las")
project.factor_map_tasks.append(factor_task("failed"))
project.paleomap_documents.append(map_doc())
preexisting_ids = {s.id for s in project.compilation_runs[-1].workflow_steps}
input_view = project_view(project)
steps = wf_service.home_workflow_steps(project)
add(
    "home_roundtrip_no_catalog",
    "service.home_workflow_steps",
    {"project": input_view},
    {
        "result": {
            "steps": steps_view(steps, preexisting_ids),
            "compilation_runs_after": strip_appended_ids(
                project.model_dump()["compilation_runs"], preexisting_ids
            ),
        }
    },
)

# sticky vs stale overlay (catalog-backed): persisted warning survives a
# stale overlay, persisted pending is overwritten by stale, a FRESH
# overlay promotes a persisted warning back to complete.
project = new_project()
project.compilation_runs.append(
    build_run(
        [
            ("data_check", "pending"),   # evidence complete -> complete
            ("factor_map", "warning"),   # stale overlay -> stays warning
            ("prediction", "warning"),   # fresh overlay -> promoted complete
            ("map_compile", "pending"),  # stale overlay -> stale
            ("export", "pending"),       # stale overlay -> stale
        ]  # qc missing -> appended (no qc runs -> evidence pending)
    )
)
add_resource(project, "A1.Las", "well_log", "las")
project.factor_map_tasks.append(factor_task("complete"))
project.prediction_tasks.append(prediction_task("complete"))
project.paleomap_documents.append(map_doc())
project.export_artifacts.append(export_artifact())
catalog = {
    "versions": [H1_V1, H1_V2, F1_V1, P1_V1, M1_V1],
    "runs": [
        {   # stale: consumed the superseded horizon tip
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v1"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:13",
        },
        {   # fresh: consumes the current horizon tip
            "run_id": "run_p1", "operation": "prediction",
            "input_version_ids": ["ver_h1_v2"],
            "output_version_ids": ["ver_p1_v1"], "status": "complete",
            "domain_task_id": "task_p1",
            "started_at": "2026-01-01T00:00:14",
        },
        {   # transitively stale: consumed the stale factor output
            "run_id": "run_m1", "operation": "map_compile",
            "input_version_ids": ["ver_f1_v1"],
            "output_version_ids": ["ver_m1_v1"], "status": "complete",
            "domain_task_id": "task_m1",
            "started_at": "2026-01-01T00:00:15",
        },
        {   # transitively stale: consumed the stale map output
            "run_id": "run_e1", "operation": "export",
            "input_version_ids": ["ver_m1_v1"],
            "output_version_ids": ["ver_e1_v1"], "status": "complete",
            "domain_task_id": "task_e1",
            "started_at": "2026-01-01T00:00:16",
        },
    ],
}
preexisting_ids = {s.id for s in project.compilation_runs[-1].workflow_steps}
input_view = project_view(project)
steps = wf_service.home_workflow_steps(project, catalog=fake_catalog(catalog))
add(
    "home_sticky_vs_stale_overlay",
    "service.home_workflow_steps",
    {"project": input_view, "catalog": catalog},
    {
        "result": {
            "steps": steps_view(steps, preexisting_ids),
            "compilation_runs_after": strip_appended_ids(
                project.model_dump()["compilation_runs"], preexisting_ids
            ),
        }
    },
)

# composition failure (fail_listing catalog): evidence-only fallback
# (audit #847-3 — logged in Python, catch boundary in C++).
project = new_project()
project.factor_map_tasks.append(factor_task("complete"))
bad_catalog = {"versions": [], "runs": [], "fail_listing": True}
steps = wf_service.home_workflow_steps(project, catalog=fake_catalog(bad_catalog))
add(
    "home_composition_failure_evidence_only",
    "service.home_workflow_steps",
    {"project": project_view(project), "catalog": bad_catalog},
    {
        "result": {
            "steps": strip_ephemeral_ids([s.model_dump() for s in steps]),
            "compilation_runs_after": project.model_dump()["compilation_runs"],
        }
    },
)


# ------------------------------------------------------- plan family ---

CHAIN = {
    "versions": [H1_V1, H1_V2, F1_V1, P1_V1, M1_V1],
    "runs": [
        {
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v1"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:20",
        },
        {
            "run_id": "run_p1", "operation": "prediction",
            "input_version_ids": ["ver_h1_v1"],
            "output_version_ids": ["ver_p1_v1"], "status": "complete",
            "domain_task_id": "task_p1",
            "started_at": "2026-01-01T00:00:21",
        },
        {
            "run_id": "run_m1", "operation": "map_compile",
            "input_version_ids": ["ver_f1_v1"],
            "output_version_ids": ["ver_m1_v1"], "status": "complete",
            "domain_task_id": "task_m1",
            "started_at": "2026-01-01T00:00:22",
        },
    ],
}

project = new_project()
plan = wf_service.build_affected_products_plan(project, catalog=fake_catalog(CHAIN))
add(
    "plan_all_stale_no_roots",
    "service.build_affected_products_plan",
    {"project": project_view(project), "catalog": CHAIN},
    {"result": plan.to_dict()},
)

project = new_project()
plan = wf_service.build_affected_products_plan(
    project, changed_version_ids=["ver_f1_v1"], catalog=fake_catalog(CHAIN)
)
add(
    "plan_changed_roots_factor_output",
    "service.build_affected_products_plan",
    {
        "project": project_view(project),
        "catalog": CHAIN,
        "changed_version_ids": ["ver_f1_v1"],
    },
    {"result": plan.to_dict()},
)


# --------------------------------------------- downstream impact rows ---

# Root expansion (H1): asking for the NEW horizon tip must still surface
# the runs that consumed the superseded sibling (asset expansion).
project = new_project()
rows = wf_service.downstream_impact_for_version(
    "ver_h1_v2", project=project, catalog=fake_catalog(CHAIN)
)
add(
    "downstream_rows_root_expansion",
    "service.downstream_impact_for_version",
    {
        "version_id": "ver_h1_v2",
        "project": project_view(project),
        "catalog": CHAIN,
    },
    {"result": rows},
)

# Domain-task sibling expansion (H1): dependents attach to the versions
# they consumed; a retry run of the same domain task put its output on a
# DIFFERENT asset, so only the domain-sibling expansion surfaces the
# second consumer.
SIBLINGS = {
    "versions": [
        H1_V2,
        F1_V1,
        {"asset_id": "asset_f2", "version_id": "ver_f2_v1", "name": "F2",
         "producing_run_id": "run_f1b"},
        M1_V1,
        {"asset_id": "asset_m2", "version_id": "ver_m2_v1", "name": "M2",
         "producing_run_id": "run_m1b"},
    ],
    "runs": [
        {
            "run_id": "run_f1", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v2"],
            "output_version_ids": ["ver_f1_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:30",
        },
        {   # same domain task, retry: new asset
            "run_id": "run_f1b", "operation": "factor_map",
            "input_version_ids": ["ver_h1_v2"],
            "output_version_ids": ["ver_f2_v1"], "status": "complete",
            "domain_task_id": "task_f1",
            "started_at": "2026-01-01T00:00:31",
        },
        {
            "run_id": "run_m1", "operation": "map_compile",
            "input_version_ids": ["ver_f1_v1"],
            "output_version_ids": ["ver_m1_v1"], "status": "complete",
            "domain_task_id": "task_m1",
            "started_at": "2026-01-01T00:00:32",
        },
        {   # consumes the retry output — visible only via domain expansion
            "run_id": "run_m1b", "operation": "map_compile",
            "input_version_ids": ["ver_f2_v1"],
            "output_version_ids": ["ver_m2_v1"], "status": "failed",
            "domain_task_id": "task_m1b",
            "started_at": "2026-01-01T00:00:33",
        },
    ],
}
project = new_project()
rows = wf_service.downstream_impact_for_version(
    "ver_f1_v1", project=project, catalog=fake_catalog(SIBLINGS)
)
add(
    "downstream_rows_domain_sibling_expansion",
    "service.downstream_impact_for_version",
    {
        "version_id": "ver_f1_v1",
        "project": project_view(project),
        "catalog": SIBLINGS,
    },
    {"result": rows},
)

# A version with no siblings and no dependents -> empty panel payload.
LONELY = {
    "versions": [H1_V1],
    "runs": [],
}
project = new_project()
rows = wf_service.downstream_impact_for_version(
    "ver_h1_v1", project=project, catalog=fake_catalog(LONELY)
)
add(
    "downstream_rows_empty",
    "service.downstream_impact_for_version",
    {
        "version_id": "ver_h1_v1",
        "project": project_view(project),
        "catalog": LONELY,
    },
    {"result": rows},
)


# ------------------------------------------------------ dashboard ------

project = new_project()
add_resource(project, "A1.Las", "well_log", "las")
add_resource(project, "A2.Las", "well_log", "las")
add_resource(project, "200P.sgy", "seismic", "sgy")
project.factor_map_tasks.append(factor_task("complete"))
project.factor_map_tasks.append(factor_task("running"))
project.prediction_tasks.append(prediction_task("complete"))
doc = map_doc("M1")
doc2 = map_doc("M2")
project.paleomap_documents.extend([doc, doc2])
project.quality_reports.append(
    qc_report(doc.id, "warning", [{"rule": "r", "severity": "warning"}])
)
project.quality_reports.append(qc_report(doc2.id, "pass", [{"rule": "a"}, {"rule": "b"}]))
project.export_artifacts.append(export_artifact(doc.id))
run_rec = build_run([], name="编图 Run", horizon="ZJ2-Advanced", scheme="四级层序",
                    status="running")
run_rec.active_quality_report_id = project.quality_reports[0].id
project.compilation_runs.append(run_rec)
add(
    "dashboard_full_shape",
    "service.dashboard_state",
    {"project": project_view(project)},
    {"result": wf_service.dashboard_state(project)},
)

project = new_project()
project.stratigraphy.target_horizon = "H3"
add_resource(project, "w.las", "well_log", "las")
add_resource(project, "s.sgy", "seismic", "sgy")
add_resource(project, "h.grd", "horizon", "grd")
add(
    "dashboard_no_run_fallbacks",
    "service.dashboard_state",
    {"project": project_view(project)},
    {"result": wf_service.dashboard_state(project)},
)

# ---------------------------------------------------------------- write
FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {len(cases)} cases to {FIXTURE}")
