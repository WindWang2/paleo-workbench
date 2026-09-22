#!/usr/bin/env python
"""Generate the ToolPolicy golden matrix from the Python canonical evaluator.

Runs the *main repository's* tool_availability (read-only import; no product
mutation) over a JSON-encoded set of context snapshots and dumps every tool
verdict. The C++ port test (test_tool_policy_golden.cpp) rebuilds the same
snapshots and must match every verdict byte-for-byte (enabled/visible/
checked/disabled_reason) — the cross-implementation contract evidence for
Oracle 3.

Usage (from the platform worktree):
  C:/.../paleo-workbench/.venv/Scripts/python.exe tests/cpp/platform/make_golden.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAIN_REPO = r"C:/Users/wangj.KEVIN/projects/paleo-workbench"
sys.path.insert(0, MAIN_REPO)

import sys as _sys  # archived-reference shim (legacy/python_reference)

from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'legacy' / 'python_reference' / 'product'))

from paleo_workbench.mapping.tool_availability import (  # noqa: E402
    evaluate_all,
)
from paleo_workbench.mapping.tool_context import ToolContext  # noqa: E402

HAPPY_FLAGS = [
    "qgis.native_tool.identify", "qgis.native_tool.select",
    "qgis.native_tool.addPoint", "qgis.native_tool.addLine",
    "qgis.native_tool.addPolygon", "qgis.native_tool.move",
    "qgis.native_tool.vertex", "qgis.geometry_op.validate",
    "qgis.geometry_op.reshape", "qgis.geometry_op.add_part",
]


def base_happy() -> dict:
    return {
        "project_open": True,
        "qgis_available": True,
        "native_canvas_available": True,
        "backend_mode": "native",
        "active_layer_id": "layer-1",
        "active_layer_kind": "polygon",
        "qgis_layer_type": "vector",
        "vector_writable": True,
        "edit_gate_open": True,
        "editing": True,
        "dirty": True,
        "can_undo": True,
        "selection_count": 1,
        "provider_writable": True,
        "provider_name": "ogr",
        "capability_flags": list(HAPPY_FLAGS),
    }


def contexts() -> dict[str, dict]:
    cases: dict[str, dict] = {}

    cases["happy_editing"] = base_happy()
    cases["happy_editing"]["current_tool"] = "vertex"
    cases["happy_editing"]["snapping_enabled"] = True
    cases["happy_editing"]["topology_enabled"] = True
    cases["happy_editing"]["vertex_all_layers"] = False

    no_project = base_happy()
    no_project["project_open"] = False
    no_project["blocking_task"] = "importing"
    cases["no_project_blocking"] = no_project

    no_layer = base_happy()
    no_layer["active_layer_id"] = ""
    no_layer["active_layer_kind"] = ""
    cases["no_active_layer"] = no_layer

    readonly = base_happy()
    readonly["provider_writable"] = False
    cases["readonly_provider"] = readonly

    readonly_approx = base_happy()
    readonly_approx["provider_writable"] = False
    readonly_approx["provider_writable_approximate"] = True
    cases["readonly_provider_approx"] = readonly_approx

    raw = base_happy()
    raw["edit_gate_open"] = False
    raw["raw_locked"] = True
    cases["raw_gate"] = raw

    frozen = base_happy()
    frozen["edit_gate_open"] = False
    frozen["layer_frozen"] = True
    cases["frozen_gate"] = frozen

    stage_locked = base_happy()
    stage_locked["edit_gate_open"] = False
    stage_locked["stage_locked"] = True
    cases["stage_locked_gate"] = stage_locked

    unknown_gate = base_happy()
    unknown_gate["edit_gate_open"] = None
    cases["edit_gate_unknown"] = unknown_gate

    not_editing = base_happy()
    not_editing["editing"] = False
    cases["not_editing"] = not_editing

    clean_session = base_happy()
    clean_session["dirty"] = False
    clean_session["can_undo"] = False
    clean_session["can_redo"] = False
    cases["clean_session"] = clean_session

    line_layer = base_happy()
    line_layer["active_layer_kind"] = "line"
    cases["capture_line_layer"] = line_layer

    unknown_kind = base_happy()
    unknown_kind["active_layer_kind"] = ""
    cases["capture_unknown_kind"] = unknown_kind

    line_role_polygon = base_happy()
    line_role_polygon["layer_role"] = "provenance_line"
    line_role_polygon["layer_role_label"] = "物源线"
    cases["line_role_polygon_layer"] = line_role_polygon

    for stage in ("facies_calibration", "constraint_factor",
                  "integrated_compilation", "unknown_stage", "", "phase2"):
        ctx = base_happy()
        ctx["mapping_stage"] = stage
        cases[f"stage_{stage or 'empty'}"] = ctx

    topo_errors = base_happy()
    topo_errors["topology_error_count"] = 2
    cases["topology_errors"] = topo_errors

    no_selection = base_happy()
    no_selection["selection_count"] = 0
    cases["no_selection"] = no_selection

    facies_layer = base_happy()
    facies_layer["layer_is_facies"] = True
    facies_layer["current_tool"] = "add_polygon"
    cases["facies_layer"] = facies_layer

    degraded = base_happy()
    degraded["backend_mode"] = "degraded"
    degraded["backend_reason"] = "同步异常"
    cases["backend_degraded"] = degraded

    missing = base_happy()
    missing["layer_missing"] = True
    missing["edit_gate_reason"] = ""
    cases["layer_missing"] = missing

    degraded_facts = base_happy()
    degraded_facts["layer_degraded"] = True
    degraded_facts["edit_gate_open"] = False
    cases["layer_degraded"] = degraded_facts

    no_snapping = base_happy()
    no_snapping["snapping_available"] = False
    cases["no_snapping_engine"] = no_snapping

    bad_crs = base_happy()
    bad_crs["crs_valid"] = False
    cases["invalid_crs"] = bad_crs

    return cases


def main() -> int:
    golden = {"contexts": {}, "expectations": {}}
    for name, fields in contexts().items():
        kwargs = dict(fields)
        kwargs["capability_flags"] = frozenset(kwargs["capability_flags"])
        ctx = ToolContext(**kwargs)
        golden["contexts"][name] = fields
        golden["expectations"][name] = {
            tool_id: {
                "visible": verdict.visible,
                "enabled": verdict.enabled,
                "checked": verdict.checked,
                "disabled_reason": verdict.disabled_reason,
            }
            for tool_id, verdict in evaluate_all(ctx).items()
        }
    out = Path(__file__).with_name("golden_tool_policy.json")
    out.write_text(json.dumps(golden, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    total = sum(len(v) for v in golden["expectations"].values())
    print(f"golden written: {out} ({len(golden['expectations'])} contexts x "
          f"{total // max(1, len(golden['expectations']))} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
