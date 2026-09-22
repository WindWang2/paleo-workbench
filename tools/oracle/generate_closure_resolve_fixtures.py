#!/usr/bin/env python3
"""Generate the frozen current-context resolve oracle for cpp-close-02.

Drives the REAL Python implementation
(paleo_workbench.workflow.current_context.resolve_current_project_version_context,
the five-segment project injection CONV-33 findings A3 left to the
consuming line) with representative catalog + project scenarios and
freezes the resulting context verbatim:
  * catalog asset current pointers;
  * horizon / correlation / fault interpretation refs (known + unknown
    versions, scientific fingerprints → expected identity);
  * domain-task pointers + superseded-tip deselection (issue #373 / C15);
  * factor map task grid pointers + scientific parameter identity;
  * prediction task model_ref identity;
  * extra_selected overrides; project=None / catalog=None edges.

The fake catalog is a deterministic in-memory double (the Python tests'
shape): list_assets / resolve_version / list_runs. Determinism: Python's
selected_version_ids is a SET (hash order) — the fixture freezes it
SORTED and the C++ replay compares as sorted lists. Re-runs are
byte-identical.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.catalog.runtime as catalog_runtime  # noqa: E402
from paleo_workbench.project.models import (  # noqa: E402
    CorrelationInterpretationRef,
    FactorMapTask,
    FaultInterpretationRef,
    HorizonInterpretationRef,
    PredictionTask,
    ProjectDocument,
)
from paleo_workbench.workflow.current_context import (  # noqa: E402
    resolve_current_project_version_context,
)

FIXTURE = (
    ROOT
    / "libs/closure_workflow/closure_workflow_tests/fixtures/"
    "closure_resolve_oracle.json"
)


@dataclass
class FakeAsset:
    id: str
    name: str
    current_version_id: str | None = None


@dataclass
class FakeVersion:
    version_id: str
    asset_id: str
    name: str
    producing_run_id: str | None = None
    created_at: str = ""


@dataclass
class FakeRun:
    run_id: str
    domain_task_id: str | None = None
    operation: str = ""


@dataclass
class FakeCatalogService:
    """The `svc` face: list_assets with current pointers (include_trashed)."""

    catalog: "FakeCatalog"

    def list_assets(self, include_trashed=True):
        return [a for a in self.catalog.assets
                if include_trashed or a.trashed is False]


@dataclass
class FakeAsset:
    id: str
    name: str
    current_version_id: str | None = None
    trashed: bool = False


@dataclass
class FakeCatalog:
    assets: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    runs: list = field(default_factory=list)

    def __post_init__(self):
        # The production runtime wires a Core adapter whose `.service` is
        # the DataCatalogService; the fake mirrors the attribute contract
        # so get_catalog_service() returns the service face.
        self.service = FakeCatalogService(self)

    def resolve_version(self, vid):
        for v in self.versions:
            if v.version_id == vid:
                return v
        return None

    def list_runs(self):
        return list(self.runs)


def install_catalog(cat: FakeCatalog | None) -> None:
    """Point the catalog runtime global at the fake (set_catalog parity)."""
    catalog_runtime._active = cat


def catalog_to_json(cat: FakeCatalog | None):
    if cat is None:
        return None
    return {
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "current_version_id": a.current_version_id,
            }
            for a in cat.assets
        ],
        "versions": [
            {
                "version_id": v.version_id,
                "asset_id": v.asset_id,
                "name": v.name,
                "producing_run_id": v.producing_run_id,
                "created_at": v.created_at,
            }
            for v in cat.versions
        ],
        "runs": [
            {
                "run_id": r.run_id,
                "domain_task_id": r.domain_task_id,
                "operation": r.operation,
            }
            for r in cat.runs
        ],
    }


def resolve_with_install(cat, **kwargs):
    install_catalog(cat)
    try:
        return resolve_current_project_version_context(catalog=cat, **kwargs)
    finally:
        install_catalog(None)


def context_to_json(ctx) -> dict:
    return {
        "current_by_asset": dict(ctx.current_by_asset),
        "selected_version_ids": sorted(ctx.selected_version_ids),
        "labels": dict(ctx.labels),
        "expected_identity": {k: v for k, v in ctx.expected_identity.items()},
        "current_by_domain_task": dict(ctx.current_by_domain_task),
    }


def case_catalog_pointers():
    cat = FakeCatalog(
        assets=[
            FakeAsset("asset_000001", "实测曲线", "ver_000002"),
            FakeAsset("asset_000002", "因子网格", "ver_000003"),
        ],
        versions=[
            FakeVersion("ver_000001", "asset_000001", "曲线v1", created_at="t1"),
            FakeVersion("ver_000002", "asset_000001", "曲线v2", created_at="t2"),
            FakeVersion("ver_000003", "asset_000002", "网格v1", created_at="t3"),
        ],
        runs=[],
    )
    return {
        "id": "catalog_pointers",
        "input": {"catalog": catalog_to_json(cat), "project": None,
                  "extra_selected": {}},
        "expected": context_to_json(
            resolve_with_install(cat, project=None)),
    }


def case_horizon_refs():
    cat = FakeCatalog(
        assets=[FakeAsset("asset_000010", "层位解释", "ver_000020")],
        versions=[
            FakeVersion("ver_000020", "asset_000010", "H1解释",
                        created_at="t1"),
            FakeVersion("ver_000099", "asset_000010", "未知引用落点",
                        created_at="t0"),
        ],
        runs=[],
    )
    project = ProjectDocument.new("P", "R")
    project.horizon_interpretations = [
        HorizonInterpretationRef(
            id="interp_h1", name="H1 层位", horizon_key="H1",
            current_version_id="ver_000020",
            scientific_fingerprint="fp-horizon-1"),
        HorizonInterpretationRef(
            id="interp_h2", name="H2 缺失", horizon_key="H2",
            current_version_id="ver_missing"),
    ]
    project_json = project.model_dump()
    return {
        "id": "horizon_refs",
        "input": {"catalog": catalog_to_json(cat), "project": project_json,
                  "extra_selected": {}},
        "expected": context_to_json(
            resolve_with_install(cat, project=project)),
    }


def case_domain_deselect():
    # Legacy asset-per-run catalog: an old correlation tip is selected via
    # the catalog pointer; the project selects the newer tip of the same
    # domain task — the superseded tip must be deselected (issue #373).
    cat = FakeCatalog(
        assets=[
            FakeAsset("asset_old", "旧相关解释", "ver_old"),
            FakeAsset("asset_new", "新相关解释", "ver_new"),
        ],
        versions=[
            FakeVersion("ver_old", "asset_old", "corr v1",
                        producing_run_id="run_old", created_at="t1"),
            FakeVersion("ver_new", "asset_new", "corr v2",
                        producing_run_id="run_new", created_at="t2"),
        ],
        runs=[
            FakeRun("run_old", domain_task_id="corr_task"),
            FakeRun("run_new", domain_task_id="corr_task"),
        ],
    )
    project = ProjectDocument.new("P", "R")
    project.correlation_interpretations = [
        CorrelationInterpretationRef(
            id="corr_task", name="连井对比",
            current_version_id="ver_new",
            scientific_fingerprint="fp-corr-1"),
    ]
    project_json = project.model_dump()
    return {
        "id": "domain_deselect",
        "input": {"catalog": catalog_to_json(cat), "project": project_json,
                  "extra_selected": {}},
        "expected": context_to_json(
            resolve_with_install(cat, project=project)),
    }


def case_factor_and_prediction():
    cat = FakeCatalog(
        assets=[FakeAsset("asset_grid", "物源网格", "ver_grid2")],
        versions=[
            FakeVersion("ver_grid1", "asset_grid", "网格v1",
                        producing_run_id="run_g1", created_at="t1"),
            FakeVersion("ver_grid2", "asset_grid", "网格v2",
                        producing_run_id="run_g2", created_at="t2"),
        ],
        runs=[
            FakeRun("run_g1", domain_task_id="factor_task_1"),
            FakeRun("run_g2", domain_task_id="factor_task_1"),
        ],
    )
    project = ProjectDocument.new("P", "R")
    project.factor_map_tasks = [
        FactorMapTask(
            id="factor_task_1", name="物源综合", target_horizon="H1",
            factor_type="重矿物ZTR", method="idw",
            parameters={
                "power": 2,
                "search_radius": 10.0,
                "_display_colormap": "viridis",
            },
            grid_artifact_version_id="ver_grid2",
            input_snapshot_hash="snap-1", generator_version="idw-v3",
            source_kind="real"),
    ]
    project.prediction_tasks = [
        PredictionTask(
            id="pred_task_1", name="相带预测", adapter_kind="local",
            input_snapshot_hash="snap-p1", generator_version="onnx-v2",
            model_metadata={
                "model_id": "facies-net",
                "model_version": "7",
                "model_version_id": "mv_7",
                "threshold": 0.42,
                "extra": "dropped",
            }),
    ]
    project_json = project.model_dump()
    return {
        "id": "factor_and_prediction",
        "input": {"catalog": catalog_to_json(cat), "project": project_json,
                  "extra_selected": {"asset_000001": "ver_override"}},
        "expected": context_to_json(
            resolve_with_install(cat, project=project,
                extra_selected={"asset_000001": "ver_override"})),
    }


def case_null_project():
    cat = FakeCatalog(
        assets=[FakeAsset("asset_1", "网格", "ver_1")],
        versions=[FakeVersion("ver_1", "asset_1", "网格v1", created_at="t1")],
        runs=[],
    )
    return {
        "id": "null_project",
        "input": {"catalog": catalog_to_json(cat), "project": None,
                  "extra_selected": {"asset_x": "ver_x"}},
        "expected": context_to_json(
            resolve_with_install(cat, project=None,
                extra_selected={"asset_x": "ver_x"})),
    }


def case_null_catalog():
    project = ProjectDocument.new("P", "R")
    project.horizon_interpretations = [
        HorizonInterpretationRef(
            id="i1", name="H1", horizon_key="H1",
            current_version_id="ver_ghost",
            scientific_fingerprint="fp-ghost"),
    ]
    project.factor_map_tasks = [
        FactorMapTask(id="f1", name="因子", target_horizon="H1",
                      factor_type="重矿物ZTR", method="idw",
                      grid_artifact_version_id="ver_g"),
    ]
    project_json = project.model_dump()
    return {
        "id": "null_catalog",
        "input": {"catalog": None, "project": project_json,
                  "extra_selected": {}},
        "expected": context_to_json(
            resolve_with_install(None, project=project)),
    }


def main() -> int:
    cases = [
        case_catalog_pointers(),
        case_horizon_refs(),
        case_domain_deselect(),
        case_factor_and_prediction(),
        case_null_project(),
        case_null_catalog(),
    ]
    fixture = {
        "generator": "tools/oracle/generate_closure_resolve_fixtures.py",
        "frozen_from": "paleo_workbench.workflow.current_context"
                       ".resolve_current_project_version_context",
        "cases": cases,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(fixture, ensure_ascii=False, indent=1, sort_keys=True)
    FIXTURE.write_text(text + "\n", encoding="utf-8")
    print(f"frozen {len(cases)} cases -> {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
