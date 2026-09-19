#!/usr/bin/env python3
"""Generate the frozen integrated-fusion oracle for cpp-close-02.

Drives the REAL Python implementation
(paleo_workbench.workflow.integrated_compilation + the CONV-24 fusion
kernel) with deterministic 2x2 factor grids and freezes:
  * build_fusion_model outputs (model dict + fingerprint) under equal /
    explicit weights, default / explicit classes, default / explicit
    normalizations;
  * run_integrated_fusion summaries (descriptors, qc defaults, pin
    mismatches, honest degraded registration) with register=False;
  * the register=True path against a deterministic catalog double;
  * the fail-closed gates verbatim (unfrozen input set, unresolvable
    factor, unknown weights, degenerate normalization ranges).

Grid injection uses the supported Python seams: the live session cache
(``factor_grid_artifacts._LIVE_FACTOR_GRIDS``) for task-current grids and
a patched ``catalog.grid_artifact.read_grid_artifact`` for pinned
versions — the C++ replay feeds the same grids through its typed seams.
Re-runs are byte-identical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import paleo_workbench.catalog.grid_artifact as grid_artifact  # noqa: E402
import paleo_workbench.project.factor_grid_artifacts as fga  # noqa: E402
import paleo_workbench.project.models as pm  # noqa: E402
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402
from paleo_workbench.workflow.integrated_compilation import (  # noqa: E402
    build_fusion_model,
    fusion_inputs_from_document,
    run_integrated_fusion,
)

FIXTURE = (
    ROOT
    / "libs/closure_workflow/closure_workflow_tests/fixtures/"
    "closure_fusion_oracle.json"
)

FAULT = object()

FROZEN_NOW = "2026-01-01T00:00:00+00:00"
pm._now_iso = lambda: FROZEN_NOW


def make_grid(seed_name: str, values: list[list[float]],
              factor_name: str, algorithm_id: str) -> FactorGridResult:
    grid_z = np.array(values, dtype=np.float32)
    grid_x = np.array([0.0, 1.0], dtype=np.float64)
    grid_y = np.array([0.0, 1.0], dtype=np.float64)
    grid = FactorGridResult(
        grid_z=grid_z, grid_x=grid_x, grid_y=grid_y,
        factor_name=factor_name, algorithm_id=algorithm_id,
        algorithm_parameters={"power": 2},
        crs=None, unit="ratio",
        source_refs=[f"ver_src_{seed_name}"])
    grid._finalise()
    return grid


def install_live_grid(task_id: str, grid: FactorGridResult) -> None:
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        fga._LIVE_FACTOR_GRIDS[task_id] = grid


def clear_live_grid(task_id: str) -> None:
    with fga._LIVE_FACTOR_GRIDS_LOCK:
        fga._LIVE_FACTOR_GRIDS.pop(task_id, None)


def grid_to_json(grid: FactorGridResult) -> dict:
    def cells(array) -> list:
        return [None if not np.isfinite(v) else float(v)
                for v in np.asarray(array, dtype=np.float64).ravel()]

    return {
        "grid_z": cells(grid.grid_z),
        "grid_x": [float(v) for v in grid.grid_x],
        "grid_y": [float(v) for v in grid.grid_y],
        "height": grid.height,
        "width": grid.width,
        "factor_name": grid.factor_name,
        "algorithm_id": grid.algorithm_id,
        "algorithm_parameters": grid.algorithm_parameters,
        "crs": grid.crs,
        "unit": grid.unit,
        "source_refs": list(grid.source_refs),
        "run_ref": grid.run_ref,
        "variance_grid": (cells(grid.variance_grid)
                          if grid.variance_grid is not None else None),
    }


def make_document(with_input_set: bool, frozen: bool = False):
    from paleo_workbench.project.models import FactorMapTask, ProjectDocument

    doc = ProjectDocument.new("P", "R")
    # default_factory bound _now_iso at class-definition time; freeze the
    # stamped meta timestamps explicitly for byte-determinism.
    doc.meta.created_at = FROZEN_NOW
    doc.meta.updated_at = FROZEN_NOW
    doc.factor_map_tasks = [
        FactorMapTask(id="factor_1", name="物源综合", target_horizon="H1",
                      factor_type="重矿物ZTR", method="idw",
                      grid_artifact_version_id="ver_grid1",
                      source_kind="real"),
        FactorMapTask(id="factor_2", name="古流向", target_horizon="H1",
                      factor_type="古流向", method="kriging",
                      grid_artifact_version_id="ver_grid2",
                      source_kind="real"),
    ]
    if with_input_set:
        from paleo_workbench.workflow.interpretation.compilation import (
            create_input_set,
            freeze_input_set,
            persist_input_set,
        )
        input_set = create_input_set(
            doc, ["factor:factor_1:ver_grid1",
                  "factor:factor_2:ver_grid2"],
            name="综合编图输入集")
        if frozen:
            freeze_input_set(input_set, doc)
        persist_input_set(doc, input_set)
    return doc


EVIDENCE = [("物源", "factor:factor_1:ver_grid1"),
            ("古流向", "factor:factor_2:ver_grid2")]


def install_grids():
    grid1 = make_grid("g1", [[0.1, 0.4], [0.7, 1.0]], "物源综合", "idw")
    grid2 = make_grid("g2", [[0.2, 0.5], [0.3, 0.9]], "古流向", "kriging")
    install_live_grid("factor_1", grid1)
    install_live_grid("factor_2", grid2)
    return grid1, grid2


def case_model_default():
    grid1, grid2 = install_grids()
    try:
        doc = make_document(with_input_set=False)
        results = fusion_inputs_from_document(doc, dict(EVIDENCE))
        model = build_fusion_model(dict(EVIDENCE), results)
        return {
            "id": "model_default",
            "input": {"evidence": EVIDENCE,
                      "grids": {"factor_1": grid_to_json(grid1),
                                "factor_2": grid_to_json(grid2)},
                      "project": doc.model_dump()},
            "expected": {"model": model.to_dict(),
                         "fingerprint": model.fingerprint()},
        }
    finally:
        clear_live_grid("factor_1")
        clear_live_grid("factor_2")


def case_model_explicit():
    grid1, grid2 = install_grids()
    try:
        doc = make_document(with_input_set=False)
        results = fusion_inputs_from_document(doc, dict(EVIDENCE))
        model = build_fusion_model(
            dict(EVIDENCE), results,
            weights={"factor_1": 0.75, "factor_2": 0.25},
            class_names=["低", "中", "高"], class_thresholds=[0.4, 0.8],
            weight_provenance={"decided_by": "专家评审", "reason": None})
        return {
            "id": "model_explicit",
            "input": {"evidence": EVIDENCE,
                      "grids": {"factor_1": grid_to_json(grid1),
                                "factor_2": grid_to_json(grid2)},
                      "project": doc.model_dump()},
            "expected": {"model": model.to_dict(),
                         "fingerprint": model.fingerprint()},
        }
    finally:
        clear_live_grid("factor_1")
        clear_live_grid("factor_2")


def case_run_degraded():
    grid1, grid2 = install_grids()
    try:
        doc = make_document(with_input_set=False)
        summary = run_integrated_fusion(doc, dict(EVIDENCE), catalog=None,
                                        register=False)
        return {
            "id": "run_degraded",
            "input": {"evidence": EVIDENCE,
                      "grids": {"factor_1": grid_to_json(grid1),
                                "factor_2": grid_to_json(grid2)},
                      "project": doc.model_dump()},
            "expected": {"summary": summary},
        }
    finally:
        clear_live_grid("factor_1")
        clear_live_grid("factor_2")


def case_pin_mismatch():
    grid1, grid2 = install_grids()
    try:
        doc = make_document(with_input_set=False)
        doc.factor_map_tasks[0].grid_artifact_version_id = "ver_grid9"
        # The pinned version ver_grid1 resolves from the (patched) catalog
        # artifact reader even though the task has moved on to ver_grid9.
        pinned = make_grid("g1p", [[0.15, 0.35], [0.65, 0.95]], "物源综合",
                           "idw")
        readers = {"ver_grid1": pinned}

        class FakeVersion:
            def __init__(self, vid):
                self.id = vid

        class FakeCatalog:
            def get_version(self, vid):
                if vid in readers:
                    return FakeVersion(vid)
                raise KeyError(vid)

            def resolve_path(self, version):
                return f"artifact://{version.id}"

        original_reader = grid_artifact.read_grid_artifact

        def fake_reader(path):
            vid = str(path).removeprefix("artifact://")
            if vid in readers:
                return readers[vid]
            raise FileNotFoundError(path)

        grid_artifact.read_grid_artifact = fake_reader
        mismatches: list[str] = []
        try:
            results = fusion_inputs_from_document(
                doc, dict(EVIDENCE), mismatches=mismatches,
                catalog=FakeCatalog())
            summary = run_integrated_fusion(doc, dict(EVIDENCE),
                                            catalog=FakeCatalog(),
                                            register=False)
        finally:
            grid_artifact.read_grid_artifact = original_reader
        return {
            "id": "pin_mismatch",
            "input": {
                "evidence": EVIDENCE,
                "grids": {"factor_1": grid_to_json(pinned),
                          "factor_2": grid_to_json(grid2)},
                "project": doc.model_dump()},
            "expected": {"mismatches": mismatches,
                         "summary": summary},
        }
    finally:
        clear_live_grid("factor_1")
        clear_live_grid("factor_2")


def case_register():
    grid1, grid2 = install_grids()
    try:
        doc = make_document(with_input_set=False)

        class FakeVersionRef:
            def __init__(self, vid):
                self.id = vid

        class FakeCatalogService:
            def __init__(self):
                self.derived = []

            def create_derived(self, artifact_path, parent_version_ids=(),
                               name="", operation="", parameters=None,
                               generator="", type="", format=""):
                self.derived.append({
                    "parent_version_ids": sorted(parent_version_ids),
                    "name": name,
                    "operation": operation,
                    "generator": generator,
                    "type": type,
                    "format": format,
                })
                return FakeVersionRef("ver_fusion_1")

        service = FakeCatalogService()
        summary = run_integrated_fusion(doc, dict(EVIDENCE),
                                        catalog=service, register=True)
        return {
            "id": "register",
            "input": {"evidence": EVIDENCE,
                      "grids": {"factor_1": grid_to_json(grid1),
                                "factor_2": grid_to_json(grid2)},
                      "project": doc.model_dump()},
            "expected": {"summary": summary, "derived": service.derived},
        }
    finally:
        clear_live_grid("factor_1")
        clear_live_grid("factor_2")


def error_case(case_id: str) -> dict:
    case_evidence = EVIDENCE
    if case_id == "unfrozen_input_set":
        doc = make_document(with_input_set=True, frozen=False)
        try:
            run_integrated_fusion(doc, dict(EVIDENCE), catalog=None)
            raise AssertionError("did not refuse")
        except ValueError as exc:
            message = str(exc)
    elif case_id == "unresolvable_factor":
        doc = make_document(with_input_set=False)
        evidence = [("物源", "factor:factor_1:ver_grid1"),
                    ("缺失", "factor:factor_x:ver_x")]
        try:
            install_live_grid("factor_1", make_grid(
                "g1", [[0.1, 0.4], [0.7, 1.0]], "物源综合", "idw"))
            fusion_inputs_from_document(doc, dict(evidence))
            raise AssertionError("did not refuse")
        except ValueError as exc:
            message = str(exc)
        finally:
            clear_live_grid("factor_1")
        case_evidence = evidence
    elif case_id == "unknown_weight":
        grid1, grid2 = install_grids()
        try:
            doc = make_document(with_input_set=False)
            results = fusion_inputs_from_document(doc, dict(EVIDENCE))
            try:
                build_fusion_model(dict(EVIDENCE), results,
                                   weights={"nope": 1.0})
                raise AssertionError("did not refuse")
            except ValueError as exc:
                message = str(exc)
        finally:
            clear_live_grid("factor_1")
            clear_live_grid("factor_2")
    elif case_id == "constant_grid_normalization":
        grid1 = make_grid("c1", [[0.5, 0.5], [0.5, 0.5]], "物源综合", "idw")
        grid2 = make_grid("c2", [[0.2, 0.5], [0.3, 0.9]], "古流向", "kriging")
        install_live_grid("factor_1", grid1)
        install_live_grid("factor_2", grid2)
        try:
            doc = make_document(with_input_set=False)
            results = fusion_inputs_from_document(doc, dict(EVIDENCE))
            try:
                build_fusion_model(dict(EVIDENCE), results)
                raise AssertionError("did not refuse")
            except ValueError as exc:
                message = str(exc)
        finally:
            clear_live_grid("factor_1")
            clear_live_grid("factor_2")
    else:
        raise AssertionError(case_id)
    return {
        "id": case_id,
        "input": {"evidence": case_evidence if case_id ==
                  "unresolvable_factor" else EVIDENCE},
        "expected": {"error": {"type": "ValueError", "message": message}},
    }


def main() -> int:
    cases = [
        case_model_default(),
        case_model_explicit(),
        case_run_degraded(),
        case_pin_mismatch(),
        case_register(),
        error_case("unfrozen_input_set"),
        error_case("unresolvable_factor"),
        error_case("unknown_weight"),
        error_case("constant_grid_normalization"),
    ]
    fixture = {
        "generator": "tools/oracle/generate_closure_fusion_fixtures.py",
        "frozen_from": "paleo_workbench.workflow.integrated_compilation",
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
