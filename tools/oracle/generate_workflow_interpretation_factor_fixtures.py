#!/usr/bin/env python3
"""Oracle fixture generator for the workflow_interpretation factor product +
inspector summaries (CONV-32, I5).

Imports the REAL implementations (paleo_workbench.workflow.interpretation.
factor_product / summaries / algorithm_registry) and freezes their outputs to
JSON so the C++ port in libs/workflow_interpretation can be verified against
the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_interpretation_factor_fixtures.py

17 factor cases + 2 interpretation cases (see main()): full task product +
summary, missing task, params-unit, family default, unknown everything,
unknown method, variance present / 0 / null, kriging_fallback, alias
canonicalization batch, grid_shape variants, catalog seam (ok / None /
raise), freshness (stale + detail / current), mock/mixed/real source kinds,
maturity reviewed/draft, QC str() semantics (0.123456789, True, 10),
interpretation no-record and full-with-revision (12-char base cut, evidence
join, conflict-row ordering).
"""
from __future__ import annotations

import json
import sys
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

from paleo_workbench.mapping_workspace.dependencies import FreshnessStatus  # noqa: E402
from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState  # noqa: E402
from paleo_workbench.project.models import FactorMapTask  # noqa: E402
from paleo_workbench.workflow.interpretation.factor_product import (  # noqa: E402
    factor_product_for_task,
    factor_products,
)
from paleo_workbench.workflow.interpretation.integrated_interpretation import (  # noqa: E402
    IntegratedInterpretation,
)
from paleo_workbench.workflow.interpretation.revision import (  # noqa: E402
    InterpretationRevision,
)
from paleo_workbench.workflow.interpretation.summaries import (  # noqa: E402
    factor_summary,
    factor_summary_for_task,
    interpretation_summary_rows,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_interpretation"
    / "workflow_interpretation_tests"
    / "fixtures"
    / "workflow_interpretation_factor_oracle.json"
)

# Exactly the attributes factor_product_for_task reads off a task entry —
# this is the Json-array seam handed to the C++ port.
TASK_FIELDS = (
    "id", "name", "target_horizon", "factor_type", "method", "parameters",
    "quality_metrics", "grid_artifact_version_id", "grid_metadata",
    "source_kind", "generator_version",
)


def task_payload(task: object) -> dict:
    payload = {k: getattr(task, k) for k in TASK_FIELDS}
    if hasattr(task, "created_at"):
        payload["created_at"] = getattr(task, "created_at")
    return payload


def make_task(**kw) -> FactorMapTask:
    base = dict(
        name="砂岩厚度", target_horizon="T1", factor_type="砂岩厚度",
        method="IDW", source_kind="real",
    )
    base.update(kw)
    return FactorMapTask(**base)


class FakeCatalog:
    """catalog seam: resolve_version / resolve_run with None + raise paths."""

    def __init__(self, versions=None, runs=None,
                 raise_versions=(), raise_runs=()):
        self._versions = {
            v: SimpleNamespace(run_id=info["run_id"])
            for v, info in (versions or {}).items()
        }
        self._runs = {
            r: SimpleNamespace(input_version_ids=list(info["input_version_ids"]))
            for r, info in (runs or {}).items()
        }
        self._raise_versions = set(raise_versions)
        self._raise_runs = set(raise_runs)

    def resolve_version(self, version_id):
        if version_id in self._raise_versions:
            raise RuntimeError(f"catalog unavailable: {version_id}")
        return self._versions.get(version_id)

    def resolve_run(self, run_id):
        if run_id in self._raise_runs:
            raise RuntimeError(f"catalog unavailable: {run_id}")
        return self._runs.get(run_id)

    def fixture(self) -> dict:
        return {
            "versions": {v: {"run_id": info.run_id}
                         for v, info in self._versions.items()},
            "runs": {r: {"input_version_ids": list(info.input_version_ids)}
                     for r, info in self._runs.items()},
            "raise_versions": sorted(self._raise_versions),
            "raise_runs": sorted(self._raise_runs),
        }


def build_case(case_id, tasks, *, catalog=None, workspace=None,
               freshness=None, product_ids=(), summary_ids=(),
               batch=False):
    """Run the real Python projection and freeze case JSON."""
    document = SimpleNamespace(factor_map_tasks=list(tasks))
    workspace_state = None
    if workspace is not None:
        workspace_state = MappingWorkspaceState()
        for key, maturity in workspace.items():
            workspace_state.set_maturity(key, maturity)
    checks: dict = {"products": {}, "summaries": {}}
    for task in tasks:
        entry = None
        if freshness and task.id in freshness:
            entry = SimpleNamespace(
                status=freshness[task.id]["status"],
                detail=freshness[task.id]["detail"])
        product = factor_product_for_task(
            document, task.id, catalog=catalog,
            workspace_state=workspace_state, freshness_entry=entry)
        if task.id in product_ids:
            checks["products"][task.id] = (
                product.to_dict() if product is not None else None)
        if task.id in summary_ids:
            checks["summaries"][task.id] = factor_summary(
                product).to_display_dict()
    # Ids that match no task (missing-task path): product None + honest
    # 单因素（不存在） summary via the compose helper.
    for task_id in product_ids:
        if task_id not in checks["products"]:
            product = factor_product_for_task(
                document, task_id, catalog=catalog,
                workspace_state=workspace_state)
            checks["products"][task_id] = (
                product.to_dict() if product is not None else None)
    for task_id in summary_ids:
        if task_id not in checks["summaries"]:
            checks["summaries"][task_id] = factor_summary_for_task(
                document, task_id, catalog=catalog,
                workspace_state=workspace_state).to_display_dict()
    case = {
        "id": case_id,
        "tasks": [task_payload(t) for t in tasks],
        "resolver": catalog.fixture() if catalog is not None else None,
        "workspace": workspace,
        "freshness": freshness,
        "checks": checks,
    }
    if batch:
        # factor_products evaluates freshness INTERNALLY via
        # MappingDependencyService (only when workspace_state is not None —
        # the None case skips evaluation entirely); freeze that computed map
        # so the C++ batch seam receives exactly the same entries.
        batch_freshness: dict = {}
        if workspace_state is not None:
            try:
                from paleo_workbench.mapping_workspace.dependencies import (
                    MappingDependencyService,
                )

                staleness = MappingDependencyService().evaluate(
                    document, workspace_state, catalog)
                for entry in staleness.artifacts:
                    if entry.artifact_type == "factor" \
                            and entry.artifact_key.startswith("factor:"):
                        task_id = entry.artifact_key.split(":", 1)[1]
                        if task_id:
                            status = entry.status
                            batch_freshness[task_id] = {
                                "status": getattr(status, "value", status),
                                "detail": str(getattr(entry, "detail", "") or ""),
                            }
            except Exception:  # noqa: BLE001 — same guard as factor_products
                batch_freshness = {}
        case["batch_freshness"] = batch_freshness
        products = factor_products(
            document, catalog=catalog, workspace_state=workspace_state)
        case["batch_products"] = [p.to_dict() for p in products]
    return case


def factor_cases() -> list[dict]:
    cases = []

    # 1 — full task: metadata unit/crs, qc, pins, catalog ok, empty workspace.
    full = make_task(
        name="砂岩厚度", method="IDW", status="complete",
        quality_metrics={"r_squared": 0.8, "n_points": 10, "backend": "idw"},
        grid_metadata={"unit": "m", "crs": "EPSG:32650", "height": 50,
                       "width": 50, "shape": [50, 50]},
        parameters={"constraint_pins": [{"group": "g", "content_hash": "h1"}],
                    "grid_n": 12},
        grid_artifact_version_id="gv_full_1", generator_version="eng-1.2",
    )
    full_catalog = FakeCatalog(
        versions={"gv_full_1": {"run_id": "run_full"}},
        runs={"run_full": {"input_version_ids": ["vin_a", "vin_b"]}})
    cases.append(build_case(
        "full_task", [full], catalog=full_catalog, workspace={},
        product_ids=[full.id], summary_ids=[full.id], batch=True))

    # 2 — missing task id -> None + 单因素（不存在） summary.
    cases.append(build_case(
        "missing_task", [full], catalog=full_catalog, workspace={},
        product_ids=["nope"], summary_ids=["nope"]))

    # 3 — params-unit declared (metadata has no unit).
    params_unit = make_task(
        name="地层厚度", factor_type="地层厚度", method="克里金",
        parameters={"unit": "ft"}, quality_metrics={"n_points": 7},
        grid_metadata={"crs": "EPSG:4326", "height": 30, "width": 20},
        grid_artifact_version_id="gv_params_unit")
    params_catalog = FakeCatalog(
        versions={"gv_params_unit": {"run_id": "run_pu"}},
        runs={"run_pu": {"input_version_ids": []}})
    cases.append(build_case(
        "params_unit_declared", [params_unit], catalog=params_catalog,
        product_ids=[params_unit.id], summary_ids=[params_unit.id]))

    # 4 — family default unit: 孔隙度 -> "%" declared=False.
    porosity = make_task(
        name="孔隙度", factor_type="孔隙度", method="样条",
        grid_metadata={"height": 24, "width": 24})
    cases.append(build_case(
        "family_default_porosity", [porosity],
        product_ids=[porosity.id], summary_ids=[porosity.id]))

    # 5 — unknown everything: family "", unit "", no metadata, no qc.
    unknown = make_task(
        name="伽马均值", factor_type="伽马均值", method="nearest",
        source_kind="imported")
    cases.append(build_case(
        "unknown_everything", [unknown],
        product_ids=[unknown.id], summary_ids=[unknown.id]))

    # 6 — unregistered method -> algorithm_id "" + （未注册方法）.
    bad_method = make_task(name="未知法", factor_type="砂岩厚度",
                           method="神经网络 v2")
    cases.append(build_case(
        "unknown_method", [bad_method],
        product_ids=[bad_method.id], summary_ids=[bad_method.id]))

    # 7 — variance present: variance_min 0.1 (kriging).
    variance = make_task(
        name="孔隙度", factor_type="孔隙度", method="克里金",
        quality_metrics={"variance_min": 0.1, "variance_max": 0.5,
                         "n_points": 25, "backend": "kriging"},
        grid_metadata={"unit": "%", "height": 60, "width": 40})
    cases.append(build_case(
        "variance_present_kriging", [variance],
        product_ids=[variance.id], summary_ids=[variance.id]))

    # 8 — variance_min 0 counts (0 is not None).
    zero_var = make_task(
        factor_type="砂岩厚度", method="ordinary_kriging",
        quality_metrics={"variance_min": 0},
        grid_metadata={"unit": "m"})
    cases.append(build_case(
        "variance_min_zero_counts", [zero_var],
        product_ids=[zero_var.id], summary_ids=[zero_var.id]))

    # 9 — variance_min null does NOT count; has_variance_grid false.
    null_var = make_task(
        factor_type="砂岩厚度", method="ok",
        quality_metrics={"variance_min": None, "variance_max": 1.0},
        grid_metadata={"unit": "m", "has_variance_grid": False,
                       "height": 16, "width": 16})
    cases.append(build_case(
        "variance_min_null_no_count", [null_var],
        product_ids=[null_var.id], summary_ids=[null_var.id]))

    # 10 — kriging_fallback absent reason.
    fallback = make_task(
        factor_type="孔隙度", method="克里金",
        grid_metadata={"algorithm_parameters": {"method": "kriging_fallback",
                                                "grid_n": 64},
                       "unit": "%"})
    cases.append(build_case(
        "kriging_fallback_reason", [fallback],
        product_ids=[fallback.id], summary_ids=[fallback.id]))

    # 11 — alias canonicalization batch (freshness via internal service is
    # empty on fake docs; current entry below rides the seam map instead).
    aliases = [
        make_task(name="克里金", method="克里金"),
        make_task(name="ordinary_kriging", method="ordinary_kriging"),
        make_task(name="ok", method="ok"),
        make_task(name="cubic", method="cubic"),
        make_task(name="样条插值", method="样条插值"),
        make_task(name="RBF 多二次", method="RBF 多二次"),
    ]
    cases.append(build_case(
        "alias_canonicalization_batch", aliases, batch=True,
        product_ids=[t.id for t in aliases]))

    # 12 — grid_shape variants: [100,80] / [80] / [80] / [].
    shapes = [
        make_task(name="both", grid_metadata={"height": 100, "width": 80}),
        make_task(name="width_absent", grid_metadata={"height": 80}),
        make_task(name="width_null", grid_metadata={"height": 80,
                                                    "width": None}),
        make_task(name="non_int", grid_metadata={"height": 80.5,
                                                 "width": "90"}),
    ]
    cases.append(build_case(
        "grid_shape_variants_batch", shapes, batch=True,
        product_ids=[t.id for t in shapes]))

    # 13 — catalog seam: unknown version -> None; raise on version; raise on
    # run (inputs []).
    seam_tasks = [
        make_task(name="unknown_version",
                  grid_artifact_version_id="gv_unknown",
                  grid_metadata={"unit": "m"}),
        make_task(name="raise_version",
                  grid_artifact_version_id="gv_raise",
                  grid_metadata={"unit": "m"}),
        make_task(name="raise_run",
                  grid_artifact_version_id="gv_run_ok",
                  grid_metadata={"unit": "m"}),
    ]
    seam_catalog = FakeCatalog(
        versions={"gv_run_ok": {"run_id": "run_boom"}},
        runs={}, raise_versions=["gv_raise"], raise_runs=["run_boom"])
    cases.append(build_case(
        "catalog_seam_none_and_raise_batch", seam_tasks, catalog=seam_catalog,
        batch=True, product_ids=[t.id for t in seam_tasks],
        summary_ids=[seam_tasks[0].id]))

    # 14 — freshness: stale (+ detail -> 说明 row) and current (plain string
    # status, no detail).
    fresh_tasks = [
        make_task(name="陈旧", method="克里金",
                  grid_artifact_version_id="gv_fresh"),
        make_task(name="新鲜", method="idw"),
    ]
    fresh_catalog = FakeCatalog(
        versions={"gv_fresh": {"run_id": "run_fresh"}},
        runs={"run_fresh": {"input_version_ids": ["vin_x"]}})
    cases.append(build_case(
        "freshness_stale_and_current", fresh_tasks, catalog=fresh_catalog,
        freshness={fresh_tasks[0].id: {"status": FreshnessStatus.STALE,
                                        "detail": "输入版本已被取代（v3 > v2）"},
                   fresh_tasks[1].id: {"status": "current", "detail": ""}},
        product_ids=[t.id for t in fresh_tasks],
        summary_ids=[t.id for t in fresh_tasks]))

    # 15 — source kinds: mock / mixed / real.
    kinds = [
        make_task(name="模拟", source_kind="mock"),
        make_task(name="混合", source_kind="mixed"),
        make_task(name="实测", source_kind="real"),
    ]
    cases.append(build_case(
        "source_kinds_mock_mixed_real", kinds,
        product_ids=[t.id for t in kinds], summary_ids=[t.id for t in kinds]))

    # 16 — maturity: reviewed via workspace pin, draft default sibling.
    mat_tasks = [make_task(name="已审"), make_task(name="草稿")]
    cases.append(build_case(
        "maturity_reviewed_and_draft", mat_tasks,
        workspace={"factor:" + mat_tasks[0].id: "reviewed"},
        product_ids=[t.id for t in mat_tasks],
        summary_ids=[mat_tasks[0].id]))

    # 17 — QC str() semantics + known-key subset/reorder; float 0.123456789,
    # bool True -> "True", int 10; distance_policy bool in summary subset.
    qc_task = make_task(
        factor_type="砂岩厚度", method="克里金",
        quality_metrics={"backend": "kriging", "synthesized_fallback": True,
                         "r2": 0.91, "r_squared": 0.123456789,
                         "n_points": 10, "variance_min": None, "mean": 3.25,
                         "range": [0.5, 9.5], "distance_policy": True,
                         "duplicate_wells_dropped": 2},
        grid_metadata={"unit": "m", "height": 32, "width": 32})
    cases.append(build_case(
        "qc_str_semantics_subset_order", [qc_task],
        product_ids=[qc_task.id], summary_ids=[qc_task.id]))

    return cases


def interpretation_cases() -> list[dict]:
    cases = []

    # A — no record for the layer.
    empty_doc = SimpleNamespace(integrated_interpretations=[],
                                interpretation_revisions=[])
    summary = interpretation_summary_rows(empty_doc, "layer_missing")
    cases.append({
        "id": "no_record",
        "interpretation": None,
        "revision": None,
        "expect": summary.to_display_dict(),
    })

    # B — full record + latest revision (12-char base cut, evidence join,
    # conflict rows in FUSION_CONFLICT_KEYS order, extras dropped).
    interpretation_payload = {
        "interpretation_id": "iint_abc123def456",
        "name": "T1 综合解释",
        "input_set_id": "cis_001",
        "layer_id": "layer_int_1",
        "fusion_version_id": "ver_fusion_seed_0001",
        "committed_version_id": "ver_committed_777",
        "class_schema": ["三角洲", "河道", "河口湾"],
        "conflicts": {"mean_conflict_fraction": 0.123456789,
                      "agreement_fraction": 0.7,
                      "low_confidence_fraction": 0.25,
                      "low_margin_fraction": 3.25,
                      "high_conflict_fraction": 1e-05},
        "revision_ids": ["irev_aaa", "irev_bbb"],
        "last_committed_revision_id": "irev_aaa",
        "maturity": "reviewed",
    }
    revisions_payload = [
        {"revision_id": "irev_aaa", "target_kind": "integrated_facies",
         "target_layer_id": "layer_int_1", "actor": "系统",
         "created_at": "2026-09-01T08:00:00", "base_kind": "fusion",
         "base_version_id": "feed0000feed", "evidence_refs": []},
        {"revision_id": "irev_other", "target_kind": "integrated_facies",
         "target_layer_id": "layer_other", "actor": "他层",
         "created_at": "2026-09-02T08:00:00", "base_kind": "manual",
         "base_version_id": "", "evidence_refs": []},
        {"revision_id": "irev_bbb", "target_kind": "integrated_boundary",
         "target_layer_id": "layer_int_1", "actor": "地质师A",
         "created_at": "2026-09-19T10:30:00", "base_kind": "fusion",
         "base_version_id": "deadbeefcafe0123feed",
         "evidence_refs": ["factor:task_1", "factor:task_2",
                           "constraint:poly_9"]},
    ]
    doc = SimpleNamespace(
        integrated_interpretations=[interpretation_payload],
        interpretation_revisions=revisions_payload)
    summary = interpretation_summary_rows(doc, "layer_int_1")
    # Sanity: the seam hands the C++ side exactly these two payloads.
    assert (IntegratedInterpretation.from_dict(interpretation_payload)
            .interpretation_id == "iint_abc123def456")
    latest = InterpretationRevision.from_dict(revisions_payload[-1])
    assert latest.revision_id == "irev_bbb"
    cases.append({
        "id": "with_revision",
        "interpretation": interpretation_payload,
        "revision": revisions_payload[-1],
        "expect": summary.to_display_dict(),
    })
    return cases


def main() -> None:
    doc = {
        "cases": factor_cases(),
        "interpretation_cases": interpretation_cases(),
    }
    target = OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    n_products = sum(
        len(c["checks"]["products"]) for c in doc["cases"])
    n_summaries = sum(len(c["checks"]["summaries"]) for c in doc["cases"])
    n_batch = sum(len(c.get("batch_products", [])) for c in doc["cases"])
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(doc['cases'])} factor cases, "
          f"{len(doc['interpretation_cases'])} interpretation cases, "
          f"{n_products} product checks, {n_summaries} summary checks, "
          f"{n_batch} batch products)")


if __name__ == "__main__":
    main()
