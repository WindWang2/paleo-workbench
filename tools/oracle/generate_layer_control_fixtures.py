#!/usr/bin/env python3
"""Freeze the layer-control oracle from the real Python product.

QGIS-native layer control convergence: the order-key/tree/diff
vocabularies retired with the second layer tree (QgsLayerTree is the
runtime authority; tree truth is asserted by
platform.layer_tree_composer against the real QGIS API). The surviving
Qt-free kernels under oracle parity are:

* source_usage.py  — version/asset reverse usage queries
* stage_state.py   — the behavior surface the controllers consume
                     (effective_group_visibility / record_* / defaults)

Outputs libs/workspace/workspace_tests/fixtures/layer_control_oracle.json.
The C++ side replays every case against the frozen expectations
(workspace_tests/oracle_replay_test.cpp); regeneration requires this
script plus the frozen Python modules (never hand-edited).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.mapping_workspace.source_usage import (  # noqa: E402
    usages_of_asset,
    usages_of_version,
)
from paleo_workbench.mapping_workspace.stage_state import (  # noqa: E402
    MappingWorkspaceState,
    StageViewState,
)


class FakeCatalog:
    """Duck-typed catalog for the usage oracle (records + planned errors)."""

    def __init__(self):
        self.run_inputs = {
            "run_map": ["v1", "v2"],
            "run_wide": [f"v{i}" for i in range(200)],
        }
        self.run_meta = {
            "run_map": ("export_map", "finished"),
            "run_wide": ("predict", "running"),
            "run_other": ("import", "finished"),
        }
        for i in range(120):
            self.run_meta[f"run_cap_{i}"] = (f"batch_{i}", "finished")
        self._runs_consuming = {
            "v1": ["run_map", "run_other"],
            "v2": ["run_wide"],
            "v3": [f"run_cap_{i}" for i in range(120)],
        }
        self._versions_by_asset = {"asset_1": ["v1", "v2"], "asset_2": ["v3"]}

    def get_run(self, run_id):
        if run_id not in self.run_meta:
            return None

        class _Run:
            pass
        run = _Run()
        run.id = run_id
        run.operation, run.status = self.run_meta[run_id]
        run.input_version_ids = self.run_inputs.get(run_id, [])
        return run

    def runs_consuming(self, version_id):
        return [self.get_run(rid)
                for rid in self._runs_consuming.get(version_id, [])]

    def _ensure_maps(self):
        class _Maps:
            pass
        maps = _Maps()
        # The real catalog map holds version records with .id; the oracle
        # fixture stores bare ids (the C++ seam contract).
        maps.versions_by_asset = {
            asset: tuple(SimpleNamespace(id=vid) for vid in vids)
            for asset, vids in self._versions_by_asset.items()}
        return maps


class FakeProject:
    """Duck-typed ProjectDocument (attribute access via getattr)."""

    def __init__(self, data):
        self.factor_map_tasks = [
            SimpleNamespace(**task) for task in data["factor_map_tasks"]]
        self.compilation_input_sets = data["compilation_input_sets"]
        self.map_products = [
            SimpleNamespace(**record) for record in data["map_products"]]


def usage_cases() -> dict:
    workspace_dict = {
        "schema_version": 1,
        "memberships": {
            "layer_map": {"role": "facies_boundary",
                          "source_version_id": "v1",
                          "source_asset_id": "asset_1",
                          "binding_kind": "catalog_version",
                          "created_stage": "constraint_factor"},
            "layer_direct_asset": {"role": "well_facies_prediction",
                                   "source_version_id": "v9",
                                   "source_asset_id": "asset_2"},
            "layer_fp": {"role": "fault_constraint",
                         "binding_kind": "content_fingerprint"},
        },
    }
    project_dict = {
        "factor_map_tasks": [
            {"id": "task_1", "name": "GR 网格", "grid_artifact_version_id": "v2"},
            {"id": "task_2", "grid_artifact_version_id": ""},
        ],
        "compilation_input_sets": [
            {"id": "set_1", "name": "最终编图输入", "frozen": True,
             "entries": [{"pinned_version_id": "v1"},
                         {"pinned_version_id": "v3",
                          "resolved_asset_id": "asset_2"}]},
            {"id": "set_2", "entries": [{"pinned_version_id": "v2"}]},
        ],
        "map_products": [
            {"id": "prod_1", "product_name": "P1", "output_version_id": "v3",
             "run_id": "run_map", "lifecycle": "published"},
            {"id": "prod_2", "product_name": "", "output_version_id": "v0",
             "run_id": "run_map", "lifecycle": ""},
        ],
    }
    catalog = FakeCatalog()
    workspace = MappingWorkspaceState.from_dict(workspace_dict)
    project = FakeProject(project_dict)
    version_queries = []
    for vid, include_runs, with_project in (
            ("v1", True, True), ("v2", True, True), ("v3", True, True),
            ("v9", True, True), ("missing", True, False), ("", True, True),
            ("v1", False, True)):
        report = usages_of_version(
            vid, workspace=workspace,
            project=project if with_project else None,
            catalog=catalog, include_runs=include_runs)
        version_queries.append({
            "version_id": vid,
            "include_runs": include_runs,
            "with_project": with_project,
            "expected": [u.__dict__ for u in report.usages],
            "truncated": report.truncated,
        })
    asset_queries = []
    for aid, with_catalog, with_project in (
            ("asset_1", True, True), ("asset_2", True, True),
            ("asset_none", True, True), ("", True, True),
            ("asset_1", False, True), ("asset_1", False, False)):
        report = usages_of_asset(
            aid, workspace=workspace,
            project=project if with_project else None,
            catalog=catalog if with_catalog else None)
        asset_queries.append({
            "asset_id": aid,
            "with_catalog": with_catalog,
            "with_project": with_project,
            "expected": [u.__dict__ for u in report.usages],
        })
    return {
        # NOTE: expected usages are in Python's natural collection order;
        # the C++ replay compares them SORTED by (kind, ref_id, version_id)
        # — iteration order of the underlying containers is not a frozen
        # contract (Python dict insertion order vs std::map key order).
        "workspace": workspace_dict,
        "project": project_dict,
        "catalog": {
            "run_inputs": catalog.run_inputs,
            "runs_consuming": catalog._runs_consuming,
            "versions_by_asset": catalog._versions_by_asset,
            "run_meta": {rid: list(meta)
                         for rid, meta in catalog.run_meta.items()},
        },
        "version_queries": version_queries,
        "asset_queries": asset_queries,
    }


def stage_view_cases() -> dict:
    view_input = {
        "stage": "constraint_factor",
        "group_visibility": {"g1": True, "g2": None, "g3": False},
        "layer_opacity": {"l1": 0.3, "l2": 2.0},
        "customized": False,
    }
    defaults = {"g1": False, "g2": True, "g4": True}
    view = StageViewState.from_dict(view_input)
    ops = [
        {"kind": "group_visibility", "id": "gA", "value": True},
        {"kind": "layer_visibility", "id": "l1", "value": False},
        {"kind": "layer_opacity", "id": "l1", "value": 0.03},
        {"kind": "layer_opacity", "id": "l2", "value": 5.0},
    ]
    recorder = StageViewState.from_dict({"stage": "constraint_factor"})
    for op in ops:
        if op["kind"] == "group_visibility":
            recorder.record_group_visibility(op["id"], op["value"])
        elif op["kind"] == "layer_visibility":
            recorder.record_layer_visibility(op["id"], op["value"])
        else:
            recorder.record_layer_opacity(op["id"], op["value"])
    reset_input = {
        "stage": "constraint_factor",
        "group_visibility": {"g1": True},
        "layer_visibility": {"l1": False},
        "layer_opacity": {"l1": 0.5},
        "customized": True,
    }
    reset_view = StageViewState.from_dict(reset_input)
    reset_view.reset_to_defaults()
    reset_defaults = {"g0": False}
    return {
        "effective": {
            "view": view_input,
            "defaults": defaults,
            "expected": dict(view.effective_group_visibility(defaults)),
        },
        "records": {
            "ops": ops,
            "effective_defaults": {},
            "expected_effective":
                dict(recorder.effective_group_visibility({})),
            "expected_visibility":
                {k: v for k, v in recorder.layer_visibility.items()
                 if v is not None},
            "expected_opacity":
                {k: v for k, v in recorder.layer_opacity.items()
                 if v is not None},
            "customized": recorder.customized,
        },
        "reset": {
            "view": reset_input,
            "defaults": reset_defaults,
            "expected_effective":
                dict(reset_view.effective_group_visibility(reset_defaults)),
            "customized": reset_view.customized,
        },
    }


def main() -> int:
    oracle = {
        "schema": "pwb.workspace.layer_control.oracle/1",
        "expectation_source": "python-product",
        "usage_cases": usage_cases(),
        "stage_view_cases": stage_view_cases(),
    }
    out = ROOT / "libs/workspace/workspace_tests/fixtures/layer_control_oracle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
