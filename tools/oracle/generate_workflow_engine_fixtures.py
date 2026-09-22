#!/usr/bin/env python3
"""Oracle fixture generator for the C++ in-memory DAG workflow engine (M7).

Imports the REAL implementations (paleo_workbench.mapping.geological_pipeline
extract/interpolate and paleo_workbench.workflow.dag validation) and freezes
their outputs to JSON so the C++ engine in libs/workflow_engine can be
verified against the Python chain. Regenerate with:

    /home/kevin/projects/paleo_project/main/.venv/bin/python \
        tools/oracle/generate_workflow_engine_fixtures.py

The engine slice owns the ORCHESTRATION (topological order, failure
short-circuit, cancellation, per-node logging); the IDW/extract numerics are
already frozen by the mapping_kernel oracles. This fixture therefore freezes
the *chained products* (extract node output feeding the idw node, final grid,
statistics, distance policy annotation) plus the frozen failure message and
the frozen validation problem lists for the engine's minimal spec subset.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.mapping.geological_pipeline.interpolator import (  # noqa: E402
    InterpolationOptions as PipelineInterpolationOptions,
    interpolate_factor as pipeline_interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (  # noqa: E402
    GeologicalFactor,
    GeologicalFactorDataset,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (  # noqa: E402
    GeologicalMappingPipeline,
)
from paleo_workbench.harness.registry import ActionRegistry  # noqa: E402
from paleo_workbench.harness.spec import ActionRisk, ActionSpec  # noqa: E402
from paleo_workbench.workflow.dag.model import NodeSpec, WorkflowSpec  # noqa: E402
from paleo_workbench.workflow.dag.validation import (  # noqa: E402
    BindingError,
    resolve_value,
    validate_workflow_spec,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_engine"
    / "workflow_engine_tests"
    / "fixtures"
)


RECORDS = [
    {"well_id": "W1", "name": "W1", "x": 114.10, "y": 22.50, "POR": 18.5,
     "formation": "H1"},
    {"well_id": "W2", "name": "W2", "x": 114.25, "y": 22.52,
     "porosity": 22.3, "formation": "H1"},
    {"well_id": "W3", "name": "W3", "x": 114.38, "y": 22.48, "POR": 15.2,
     "formation": "H1"},
    {"well_id": "W4", "name": "W4", "x": 114.15, "y": 22.65, "POR": 24.1,
     "formation": "H2"},
    {"well_id": "W5", "name": "W5", "x": 114.30, "y": 22.68, "POR": 0.0,
     "formation": "H2"},
    {"well_id": "W6", "name": "W6", "x": 114.42, "y": 22.62, "POR": 12.4,
     "formation": "H2"},
    {"well_id": "W7", "name": "W7", "x": 114.20, "y": 22.80, "POR": 26.5,
     "formation": "H1", "qc_flag": "bad"},
    {"well_id": "W8", "name": "W8", "x": 114.35, "y": 22.82, "POR": 21.0,
     "formation": "H1"},
    # Missing coordinates → skipped_missing (never cross-paired, never used).
    {"well_id": "W9", "name": "W9", "POR": 10.0, "formation": "H1"},
    # Unparseable coordinate → skipped_invalid.
    {"well_id": "W10", "name": "W10", "x": "n/a", "y": 22.0, "POR": 11.0},
]

# Coordinates present, no value anywhere (including aliases/nesting) → the
# extract node SUCCEEDS with 0 points and the idw node must FAIL.
EMPTY_RECORDS = [
    {"well_id": "F1", "name": "F1", "x": 0.0, "y": 0.0},
    {"well_id": "F2", "name": "F2", "x": 1.0, "y": 1.0},
]

FACTOR = "porosity"


def num(value: float) -> float | None:
    """JSON has no NaN: non-finite → null (mapping_kernel generator同款)."""
    v = float(value)
    return v if math.isfinite(v) else None


def extract_case(records: list[dict], options: dict) -> dict:
    ds = GeologicalMappingPipeline().extract_factors(
        records,
        FACTOR,
        target_horizon=options.get("target_horizon", ""),
        unit=options.get("unit"),
        crs=options.get("crs", ""),
    )
    return {
        "factor_name": ds.factor_name,
        "unit": ds.unit,
        "target_horizon": ds.target_horizon,
        "crs": ds.crs,
        "point_count": len(ds.points),
        # [x, y, value, qc_flag] rows in extraction order.
        "points": [
            [float(p.x), float(p.y), num(p.value), str(p.qc_flag)]
            for p in ds.points
        ],
        "diagnostics": {
            "coordinate_key_families_used": dict(
                ds.metadata.get("coordinate_key_families_used", {})
            ),
            "skipped_missing_coordinates": int(
                ds.metadata.get("skipped_missing_coordinates", 0)
            ),
            "skipped_invalid_coordinates": int(
                ds.metadata.get("skipped_invalid_coordinates", 0)
            ),
            "derived_points": int(ds.metadata.get("derived_points", 0)),
        },
    }


def idw_case(cid: str, records: list[dict], extract_options: dict,
             idw_options: dict) -> dict:
    ds = GeologicalMappingPipeline().extract_factors(
        records,
        FACTOR,
        target_horizon=extract_options.get("target_horizon", ""),
        unit=extract_options.get("unit"),
        crs=extract_options.get("crs", ""),
    )
    opts = PipelineInterpolationOptions(method="idw", **idw_options)
    res = pipeline_interpolate_factor(ds, opts)
    stats = res.statistics
    return {
        "id": cid,
        "extract_options": extract_options,
        # The extract node's expected output: both engine cases share the
        # same records, so the C++ test can compare its extract node output
        # against this block before the idw node runs.
        "extract": extract_case(records, extract_options),
        "idw_options": {
            "method": "idw",
            "grid_n": int(idw_options.get("grid_n", 50)),
            "power": float(idw_options.get("power", 2.0)),
            "min_neighbors": int(idw_options.get("min_neighbors", 1)),
            "max_neighbors": idw_options.get("max_neighbors"),
            # The interpolation CRS is the DATASET crs (Python
            # interpolate_factor: resolve_distance_policy(dataset.crs, ...)),
            # not an interpolation option.
            "dataset_crs": extract_options.get("crs", ""),
        },
        "grid_x": [float(v) for v in np.asarray(res.grid_x)],
        "grid_y": [float(v) for v in np.asarray(res.grid_y)],
        "grid_z": [
            [num(float(v)) for v in row] for row in np.asarray(res.grid_z)
        ],
        "statistics": {
            "min": num(stats.min),
            "max": num(stats.max),
            "mean": num(stats.mean),
            "std": num(stats.std),
            "valid_count": int(stats.valid_count),
            "total_count": int(stats.total_count),
        },
        "n_samples": int(res.algorithm_parameters["n_samples"]),
        "distance_policy": res.algorithm_parameters["distance_policy"],
        "distance_policy_annotation":
            res.algorithm_parameters["distance_policy_annotation"],
    }


def _registry() -> ActionRegistry:
    reg = ActionRegistry()
    for name in ("test.noop", "map.extract_factors", "map.interpolate_idw"):
        reg.register(ActionSpec(action_id=name, description=name,
                                handler=lambda c, p: {}, risk=ActionRisk.COMPUTE))
    return reg


def _problems(spec: WorkflowSpec, reg: ActionRegistry) -> list[str]:
    return list(validate_workflow_spec(spec, reg))


def validation_cases() -> dict:
    """Freeze the REAL validate_workflow_spec problem lists for the invalid
    specs the C++ engine's minimal validator mirrors (message text is the
    oracle; the C++ subset must reproduce these strings verbatim)."""
    reg = _registry()

    def spec(nodes: tuple[NodeSpec, ...], workflow_id: str = "t.spec") -> WorkflowSpec:
        return WorkflowSpec(workflow_id=workflow_id, name="t", nodes=nodes)

    cycle = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop", depends_on=("b",)),
        NodeSpec(node_id="b", action_id="test.noop", depends_on=("a",)),
    )), reg)
    three_cycle = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop", depends_on=("c",)),
        NodeSpec(node_id="b", action_id="test.noop", depends_on=("a",)),
        NodeSpec(node_id="c", action_id="test.noop", depends_on=("b",)),
    )), reg)
    missing = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop", depends_on=("ghost",)),
    )), reg)
    dup = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop"),
        NodeSpec(node_id="a", action_id="map.extract_factors"),
    )), reg)
    unknown = _problems(spec((
        NodeSpec(node_id="a", action_id="ghost.op"),
    )), reg)
    self_dep = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop", depends_on=("a",)),
    )), reg)
    ref_not_dep = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop"),
        NodeSpec(node_id="b", action_id="map.extract_factors",
                 parameters={"samples": {"$ref": "a", "key": "points"}}),
    )), reg)
    ref_unknown = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop",
                 parameters={"up": {"$ref": "ghost"}}),
    )), reg)
    ref_bad_key = _problems(spec((
        NodeSpec(node_id="a", action_id="test.noop"),
        NodeSpec(node_id="b", action_id="map.extract_factors",
                 depends_on=("a",),
                 parameters={"samples": {"$ref": "a", "key": 3}}),
    )), reg)
    bad_node_id = _problems(spec((
        NodeSpec(node_id="Big", action_id="test.noop"),
    )), reg)
    empty = _problems(spec(()), reg)
    return {
        "cycle_two": cycle,
        "cycle_three": three_cycle,
        "missing_dependency": missing,
        "duplicate_node": dup,
        "unknown_action": unknown,
        "self_dependency": self_dep,
        "ref_not_in_depends_on": ref_not_dep,
        "ref_unknown_node": ref_unknown,
        "ref_key_not_string": ref_bad_key,
        "bad_node_id": bad_node_id,
        "empty_workflow": empty,
    }


def runtime_binding_cases() -> dict:
    """Freeze the REAL resolve_value BindingError messages the engine's $ref
    half-binding must reproduce at run time (fail-closed node failure)."""

    class _Run:
        slot_values: dict = {}

    outputs = {"points": [1, 2]}
    results = {"a": outputs}
    missing_key = unknown = None
    try:
        resolve_value({"$ref": "a", "key": "nope"}, run=_Run(), results=results)
    except BindingError as exc:
        missing_key = str(exc)
    try:
        resolve_value({"$ref": "ghost"}, run=_Run(), results=results)
    except BindingError as exc:
        unknown = str(exc)
    return {
        "ref_missing_key": missing_key,
        "ref_unresolved_node": unknown,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    extract_options = {"target_horizon": "H1", "unit": None,
                       "crs": "EPSG:3857"}
    cases = [
        idw_case("chain_idw_n12_p2_3857", RECORDS, extract_options,
                 {"grid_n": 12, "power": 2.0, "crs": "EPSG:3857"}),
        idw_case("chain_idw_n10_p1_knn3", RECORDS, extract_options,
                 {"grid_n": 10, "power": 1.0, "max_neighbors": 3}),
    ]

    fail_ds = GeologicalMappingPipeline().extract_factors(
        EMPTY_RECORDS, FACTOR, target_horizon="H1", unit=None, crs="")
    assert len(fail_ds.points) == 0, "failure records must extract 0 points"
    try:
        pipeline_interpolate_factor(
            fail_ds, PipelineInterpolationOptions(method="idw", grid_n=8))
        raise AssertionError("empty extract must fail interpolation")
    except ValueError as exc:
        failure_message = str(exc)

    doc = {
        "records": RECORDS,
        "factor_name": FACTOR,
        "cases": cases,
        "failure": {
            "records": EMPTY_RECORDS,
            "point_count": 0,
            "message": failure_message,
        },
        "validation": validation_cases(),
        "runtime_binding": runtime_binding_cases(),
    }
    target = OUT / "workflow_engine_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(cases)} chain cases, failure message frozen, "
          f"{len(doc['validation'])} validation problem lists)")


if __name__ == "__main__":
    main()
