#!/usr/bin/env python3
"""Freeze pipeline/compile_map*.py behaviour for the C++ replay test.

Drives the REAL Python implementations:

- ``compile_map_draft`` — deterministic demo-draft compiler (placeholder
  squares, Python % on negative seeds, idempotent demo-doc replacement,
  factor-sample wells → applicable_wells → well_log-stem fallback).
- ``compile_map_production`` — fail-closed production compiler (demo /
  non-scientific / spatial-validation / model-trust / WELL_INTERVALS /
  compilability / horizon gates, then lineage-first registration).

Catalog parity: a recording double stands in for the DataCatalogService
surface (register_run / register_result_asset / update_run_status +
list_runs / resolve_version for _versions_for_domain_tasks + the optional
get_model_version_by_id verifier). Sequential ids ("run_000001"…),
sha256 checksums over the payload TEXT, and the parsed payload are frozen
— the C++ double mirrors the same allocation scheme.

Determinism: project.models._id / _now_iso are patched to sequential /
fixed values before any model is built.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.project.models as models  # noqa: E402

_seq = itertools.count(1)
models._id = lambda prefix: f"{prefix}_fix{next(_seq):04d}"  # noqa: E402
models._now_iso = lambda: "2026-01-01T00:00:00+00:00"  # noqa: E402

from paleo_workbench.pipeline.compile_map import compile_map_draft  # noqa: E402
from paleo_workbench.pipeline.compile_map_production import (  # noqa: E402
    compile_map_production,
)
from paleo_workbench.project.models import ProjectDocument  # noqa: E402

# ---------------------------------------------------------------------------
# recording catalog double (DataCatalogService path-1 surface)
# ---------------------------------------------------------------------------


class FakeCatalog:
    """Service-like double: register_* primitives + run/version lookup."""

    def __init__(self, seed):
        self.seq = 0
        self.seed_runs = [
            SimpleNamespace(
                id=r["id"],
                domain_task_id=r.get("domain_task_id"),
                status=r.get("status", "complete"),
                output_version_ids=list(r.get("output_version_ids") or []),
                input_version_ids=list(r.get("input_version_ids") or []),
            )
            for r in seed.get("runs") or []
        ]
        self.seed_versions = {
            v["id"]: SimpleNamespace(trashed=bool(v.get("trashed")))
            for v in seed.get("versions") or []
        }
        self.model_versions = seed.get("model_versions") or {}
        self.fail_output = bool(seed.get("fail_output"))
        self.registered_runs: list[dict] = []
        self.assets: list[dict] = []
        self.versions: list[dict] = []

    # -- read surface (_versions_for_domain_tasks port view) --------------
    def list_runs(self):
        return self.seed_runs

    def resolve_version(self, version_id):
        return self.seed_versions.get(version_id)

    # -- optional model-trust verifier -------------------------------------
    # Only the WithVerifier subclass below carries get_model_version_by_id —
    # the base class genuinely lacks it, so hasattr(...) is False (the
    # Python `verifier is None` refusal path).
    def _resolve_model_version(self, version_id):
        record = self.model_versions.get(version_id)
        if record is None:
            raise KeyError(version_id)
        return SimpleNamespace(**record)

    # -- write surface ------------------------------------------------------
    def register_run(self, operation, *, input_version_ids=(),
                     parameters=None, generator="", status="completed",
                     **_kw):
        self.seq += 1
        run = {
            "id": f"run_{self.seq:06d}",
            "operation": operation,
            "input_version_ids": list(input_version_ids),
            "parameters": parameters or {},
            "generator": generator,
            "status": status,
        }
        self.registered_runs.append(run)
        return SimpleNamespace(id=run["id"])

    def register_result_asset(self, *, name, type, format, asset_metadata,
                              source_path, stage, run_id=None,
                              version_metadata=None):
        if self.fail_output:
            raise RuntimeError("catalog write refused")
        payload_text = Path(source_path).read_text(encoding="utf-8")
        self.seq += 1
        asset = {
            "id": f"asset_{self.seq:06d}",
            "name": name,
            "type": type,
            "format": format,
            "asset_metadata": asset_metadata,
        }
        self.assets.append(asset)
        version = {
            "id": f"ver_{self.seq:06d}",
            "asset_id": asset["id"],
            "name": name,
            "stage": getattr(stage, "value", stage),
            "run_id": run_id,
            "sha256": hashlib.sha256(payload_text.encode("utf-8"))
            .hexdigest(),
            "version_metadata": version_metadata,
            # The raw staged-file bytes — insertion-order json.dump, NOT
            # sort_keys. Byte parity is part of the contract.
            "payload_text": payload_text,
            "payload": json.loads(payload_text),
        }
        self.versions.append(version)
        return SimpleNamespace(id=version["id"])

    def update_run_status(self, run_id, status, *, extra_parameters=None):
        for run in self.registered_runs:
            if run["id"] == run_id:
                run["status"] = status
                if extra_parameters is not None:
                    run["extra_parameters"] = extra_parameters
                return
        raise RuntimeError(f"unknown run {run_id}")

    # -- frozen view ---------------------------------------------------------
    def freeze(self):
        runs = [
            {
                "id": r.id,
                "domain_task_id": r.domain_task_id,
                "status": r.status,
                "output_version_ids": r.output_version_ids,
                "input_version_ids": r.input_version_ids,
            }
            for r in self.seed_runs
        ] + self.registered_runs
        versions = [
            {"id": vid, "trashed": ref.trashed}
            for vid, ref in self.seed_versions.items()
        ] + self.versions
        return {"runs": runs, "assets": self.assets, "versions": versions}


class FakeCatalogWithVerifier(FakeCatalog):
    def get_model_version_by_id(self, version_id):
        return self._resolve_model_version(version_id)


# ---------------------------------------------------------------------------
# drivers
# ---------------------------------------------------------------------------


def norm_project(raw):
    """Validate the seed through the real model → the exact Json tree the
    Python functions operate on (defaults materialised). Frozen so the C++
    replay sees the identical tree."""
    return ProjectDocument.model_validate(raw).model_dump()


def drive_draft(case):
    project = ProjectDocument.model_validate(case["project"])
    opts = case.get("options") or {}
    try:
        doc = compile_map_draft(
            project,
            target_horizon=opts.get("target_horizon"),
            prediction_task_id=opts.get("prediction_task_id"),
            seed=opts.get("seed", 0),
        )
        out = {
            "doc": doc.model_dump(),
            "documents": [d.model_dump()
                          for d in project.paleomap_documents],
            "active_id": (
                project.compilation_runs[-1].active_paleomap_document_id
                if project.compilation_runs
                else None
            ),
        }
        return out
    except Exception as exc:  # noqa: BLE001 — freeze the failure verbatim
        return {
            "error": {
                "class": exc.__class__.__name__,
                "message": str(exc),
            }
        }


def drive_production(case):
    project = ProjectDocument.model_validate(case["project"])
    opts = case.get("options") or {}
    seed = case.get("catalog_seed")
    catalog = None
    if seed is not None:
        cls = (
            FakeCatalogWithVerifier
            if seed.get("has_verifier", True)
            else FakeCatalog
        )
        catalog = cls(seed)
    try:
        doc = compile_map_production(
            project,
            target_horizon=opts.get("target_horizon"),
            prediction_task_id=opts.get("prediction_task_id"),
            prediction_payload=opts.get("prediction_payload"),
            map_crs=opts.get("map_crs"),
            catalog_service=catalog,
            prediction_version_id=opts.get("prediction_version_id"),
            allow_demo_task=bool(opts.get("allow_demo_task")),
        )
        return {
            "doc": doc.model_dump(),
            "documents": [d.model_dump()
                          for d in project.paleomap_documents],
            "active_id": (
                project.compilation_runs[-1].active_paleomap_document_id
                if project.compilation_runs
                else None
            ),
            "catalog": catalog.freeze() if catalog is not None else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": {
                "class": exc.__class__.__name__,
                "message": str(exc),
            },
            "catalog": catalog.freeze() if catalog is not None else None,
        }


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def polygon(lng=100.0, lat=30.0, size=1.0):
    return {
        "type": "Feature",
        "properties": {"facies": "三角洲前缘"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[lng, lat], [lng + size, lat],
                             [lng + size, lat + size], [lng, lat + size],
                             [lng, lat]]],
        },
    }


def valid_payload(**over):
    payload = {
        "result_summary": {
            "spatial_output_type": "VECTOR_POLYGONS",
            "final_scientific_prediction": True,
            "spatial": {
                "crs": "EPSG:4326",
                "features": [polygon(), polygon(105.0, 32.0)],
            },
        }
    }
    payload["result_summary"].update(over)
    return payload


def base_project(**over):
    project = {"meta": {"name": "oracle"}}
    project.update(over)
    return project


def demo_doc(doc_id, name="旧演示草稿", keep_layers=None):
    doc = {
        "id": doc_id,
        "name": name,
        "linked_target_horizon": "h",
        "view_state": {
            "generator": "deterministic-map-draft-v1",
            "is_demo_draft": True,
            "seed": 0,
        },
    }
    if keep_layers is not None:
        doc["reference_layers"] = keep_layers
    return doc


def user_doc(doc_id, name="用户图"):
    return {
        "id": doc_id,
        "name": name,
        "linked_target_horizon": "h",
    }


def run_case_list(name, cases, driver):
    out = []
    for case in cases:
        entry = {"name": f"{name}.{case['name']}"}
        if "project" in case:
            entry["project"] = norm_project(case["project"])
        if "options" in case:
            entry["options"] = case["options"]
        if "catalog_seed" in case:
            entry["catalog_seed"] = case["catalog_seed"]
        entry["expect"] = driver(case)
        out.append(entry)
    return out


def main():
    cases = []

    def valid_payload_spatial(features):
        return {
            "result_summary": {
                "spatial_output_type": "VECTOR_POLYGONS",
                "final_scientific_prediction": True,
                "spatial": {"crs": "EPSG:4326", "features": features},
            }
        }

    def valid_payload_model(version_id):
        p = valid_payload()
        p["model"] = {"model_version_id": version_id}
        return p

    # --------------------------- draft compiler ---------------------------
    draft_cases = [
        {
            "name": "empty_project",
            "project": base_project(),
            "options": {},
        },
        {
            "name": "explicit_horizon_and_seed",
            "project": base_project(
                stratigraphy={"target_horizon": "层位A"},
                compilation_runs=[
                    {"id": "run_a", "name": "r", "target_horizon": "层位B",
                     "created_at": "2026-01-01T00:00:00+00:00",
                     "updated_at": "2026-01-01T00:00:00+00:00"}
                ],
            ),
            "options": {"target_horizon": "层位C", "seed": 3},
        },
        {
            "name": "horizon_from_run_then_stratigraphy",
            "project": base_project(
                stratigraphy={"target_horizon": "层位A"},
                compilation_runs=[
                    {"id": "run_a", "name": "r", "target_horizon": "",
                     "created_at": "2026-01-01T00:00:00+00:00",
                     "updated_at": "2026-01-01T00:00:00+00:00"}
                ],
            ),
            "options": {},
        },
        {
            "name": "negative_seed_python_mod",
            "project": base_project(),
            "options": {"seed": -3},
        },
        {
            "name": "regions_grid_wrap",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1"},
                prediction_tasks=[
                    {"id": "pred_1", "name": "p",
                     "result_summary": {
                         "predicted_regions": [
                             {"facies": "河道", "probability": 0.9,
                              "region_id": "r1"},
                             {"facies": "三角洲", "probability": 0},
                             {"facies": "", "region_id": "r3"},
                             {"region_id": "r4"},
                             {"facies": "滨湖"},
                         ]}}
                ],
            ),
            "options": {},
        },
        {
            "name": "explicit_task_id_and_missing",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1"},
                prediction_tasks=[
                    {"id": "pred_1", "name": "p1",
                     "result_summary": {"predicted_regions": [
                         {"facies": "A"}]}},
                    {"id": "pred_2", "name": "p2",
                     "result_summary": {"predicted_regions": [
                         {"facies": "B"}, {"facies": "C"}]}},
                ],
            ),
            "options": {"prediction_task_id": "pred_1"},
        },
        {
            "name": "task_id_not_found",
            "project": base_project(
                prediction_tasks=[
                    {"id": "pred_1", "name": "p1",
                     "result_summary": {"predicted_regions": [
                         {"facies": "A"}]}},
                ],
            ),
            "options": {"prediction_task_id": "nope"},
        },
        {
            "name": "regions_not_a_list",
            "project": base_project(
                prediction_tasks=[
                    {"id": "pred_1", "name": "p",
                     "result_summary": {"predicted_regions": "oops"}},
                ],
            ),
            "options": {},
        },
        {
            "name": "demo_replace_keeps_id_and_layers",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1"},
                paleomap_documents=[
                    user_doc("user_1"),
                    demo_doc("demo_1", keep_layers=[
                        {"id": "ref_1", "name": "底图",
                         "source_path": "a.tif", "source_kind": "raster",
                         "source_crs": "EPSG:4326",
                         "project_crs": "EPSG:4326"}]),
                    demo_doc("demo_2"),
                ],
                compilation_runs=[
                    {"id": "run_a", "name": "r", "target_horizon": "SQ1",
                     "created_at": "2026-01-01T00:00:00+00:00",
                     "updated_at": "2026-01-01T00:00:00+00:00"}
                ],
            ),
            "options": {"seed": 2},
        },
        {
            "name": "wells_from_factor_tasks",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1",
                              "applicable_wells": ["W9"]},
                factor_map_tasks=[
                    {"id": "ft_1", "name": "f", "target_horizon": "SQ1",
                     "factor_type": "sand", "method": "idw",
                     "parameters": {"sample_points": [
                         {"well": "W1", "x": 114.5, "y": 22.7},
                         {"name": "W2", "lng": "114.6", "lat": 22.8},
                         {"well_name": "W3", "x": 114.7, "y": 22.9},
                         {"well": "W1", "x": 114.5, "y": 22.7},  # dup
                         {"well": "W4", "x": "bad", "y": 22.9},   # bad
                         {"well": "W5"},                          # no xy
                         "junk",                                  # non-dict
                     ]}},
                ],
            ),
            "options": {},
        },
        {
            "name": "wells_applicable_then_stems",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1",
                              "applicable_wells": ["W_B", "W_A"]},
                resources=[
                    {"id": "r1", "name": "w1.las", "path": "p",
                     "type": "well_log", "format": "las"},
                ],
            ),
            "options": {},
        },
        {
            "name": "wells_from_resource_stems",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ1"},
                resources=[
                    {"id": "r1", "name": "b/w2.las", "path": "p",
                     "type": "well_log", "format": "las"},
                    {"id": "r2", "name": "w1.LAS", "path": "p",
                     "type": "well_log", "format": "las"},
                    {"id": "r3", "name": "segy.sgy", "path": "p",
                     "type": "segy", "format": "sgy"},
                    {"id": "r4", "name": "w2.las", "path": "p2",
                     "type": "well_log", "format": "las"},
                ],
            ),
            "options": {},
        },
        {
            "name": "falsy_region_props",
            "project": base_project(
                prediction_tasks=[
                    {"id": "p1", "name": "p",
                     "result_summary": {"predicted_regions": [
                         {"facies": 0, "probability": 0.5},
                         {"facies": False},
                         {"facies": None},
                     ]}},
                ],
            ),
            "options": {},
        },
    ]

    # ------------------------- production compiler -------------------------
    prod_cases = [
        {
            "name": "happy_path_explicit_version",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                compilation_runs=[
                    {"id": "run_a", "name": "r", "target_horizon": "SQ2",
                     "created_at": "2026-01-01T00:00:00+00:00",
                     "updated_at": "2026-01-01T00:00:00+00:00"}
                ],
            ),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {},
        },
        {
            "name": "no_catalog_degrades_untracked",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {"prediction_payload": valid_payload()},
            "catalog_seed": None,
        },
        {
            "name": "demo_allowed_untracked",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload(demo=True),
                "allow_demo_task": True,
            },
            "catalog_seed": {},
        },
        {
            "name": "demo_refused",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {"prediction_payload": valid_payload(is_mock=True)},
            "catalog_seed": {},
        },
        {
            "name": "non_scientific_refused",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload(
                    final_scientific_prediction=False),
            },
            "catalog_seed": {},
        },
        {
            "name": "non_scientific_allowed_by_flag",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload(
                    final_scientific_prediction=False,
                    allow_map_compile=True),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {},
        },
        {
            "name": "demo_square_rejected",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload_spatial(
                    [polygon(114.0, 22.5, 0.04)]),
            },
            "catalog_seed": {},
        },
        {
            "name": "missing_crs_rejected",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": {
                    "result_summary": {
                        "spatial_output_type": "VECTOR_POLYGONS",
                        "final_scientific_prediction": True,
                        "spatial": {"features": [polygon()]},
                    }
                },
            },
            "catalog_seed": {},
        },
        {
            "name": "well_intervals_refused",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": {
                    "result_summary": {
                        "spatial_output_type": "WELL_INTERVALS",
                        "final_scientific_prediction": True,
                        "spatial": {"intervals": [
                            {"well": "W1", "top": 1, "bottom": 2}]},
                    }
                },
            },
            "catalog_seed": {},
        },
        {
            "name": "not_compilable_refused",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": {
                    "result_summary": {
                        "spatial_output_type": "VECTOR_POLYGONS",
                        "final_scientific_prediction": True,
                        "spatial": {"crs": "EPSG:4326", "features": []},
                    },
                    "model": {},
                },
            },
            "catalog_seed": {},
        },
        {
            "name": "no_task_no_payload",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {},
            "catalog_seed": {},
        },
        {
            "name": "empty_horizon_refused",
            "project": base_project(),
            "options": {"prediction_payload": valid_payload()},
            "catalog_seed": {},
        },
        {
            "name": "model_version_production_ok",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {
                "model_versions": {
                    "mv_1": {"status": "production", "demo_only": False}},
            },
        },
        {
            "name": "model_version_demo_only_refused",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload_model("mv_1"),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {
                "model_versions": {
                    "mv_1": {"status": "production", "demo_only": True}},
            },
        },
        {
            "name": "model_version_missing",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload_model("mv_404"),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {},
        },
        {
            "name": "model_version_no_verifier",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload_model("mv_1"),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {"has_verifier": False},
        },
        {
            "name": "input_ids_from_run_graph",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                prediction_tasks=[
                    {"id": "pred_t1", "name": "p", "model_metadata": {},
                     "result_summary": {}},
                ],
            ),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_task_id": "pred_t1",
            },
            "catalog_seed": {
                "runs": [
                    {"id": "r_old", "domain_task_id": "pred_t1",
                     "status": "complete",
                     "output_version_ids": ["ver_old"]},
                    {"id": "r_fail", "domain_task_id": "pred_t1",
                     "status": "failed",
                     "output_version_ids": ["ver_bad"]},
                    {"id": "r_new", "domain_task_id": "pred_t1",
                     "status": "complete",
                     "output_version_ids": ["ver_new", "ver_trash"]},
                ],
                "versions": [{"id": "ver_trash", "trashed": True}],
            },
        },
        {
            "name": "input_ids_fallback_to_run_inputs",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                prediction_tasks=[
                    {"id": "pred_t1", "name": "p", "model_metadata": {},
                     "result_summary": {}},
                ],
            ),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_task_id": "pred_t1",
            },
            "catalog_seed": {
                "runs": [
                    {"id": "r_io", "domain_task_id": "pred_t1",
                     "status": "completed",
                     "output_version_ids": [],
                     "input_version_ids": ["ver_in1", "ver_in2"]},
                ],
            },
        },
        {
            "name": "no_resolvable_inputs_refused",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                prediction_tasks=[
                    {"id": "pred_t1", "name": "p", "model_metadata": {},
                     "result_summary": {}},
                ],
            ),
            "options": {"prediction_payload": valid_payload()},
            "catalog_seed": {"runs": []},
        },
        {
            "name": "explicit_payload_links_default_task_inputs",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                prediction_tasks=[
                    {"id": "pred_t1", "name": "p", "model_metadata": {},
                     "result_summary": {}},
                ],
            ),
            # Explicit payload + NO task id → doc unlinked, but input
            # lineage still resolves through the default-resolved task.
            "options": {"prediction_payload": valid_payload()},
            "catalog_seed": {
                "runs": [
                    {"id": "r_io", "domain_task_id": "pred_t1",
                     "status": "complete",
                     "output_version_ids": ["ver_out1"]},
                ],
            },
        },
        {
            "name": "catalog_write_failure_marks_failed",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_version_id": "ver_pred_1",
            },
            "catalog_seed": {"fail_output": True},
        },
        {
            "name": "map_crs_precedence",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                coordinate={"project_crs": "EPSG:4490"},
            ),
            "options": {
                "prediction_payload": valid_payload(),
                "map_crs": "EPSG:3857",
                "prediction_version_id": "v1",
            },
            "catalog_seed": {},
        },
        {
            "name": "crs_from_project",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                coordinate={"project_crs": "EPSG:4490"},
            ),
            "options": {
                "prediction_payload": valid_payload(),
                "prediction_version_id": "v1",
            },
            "catalog_seed": {},
        },
        {
            "name": "task_derived_payload_path",
            "project": base_project(
                stratigraphy={"target_horizon": "SQ2"},
                prediction_tasks=[
                    {"id": "pred_t1", "name": "p",
                     "model_metadata": {"runtime": "onnx"},
                     "result_summary": {
                         "spatial_output_type": "VECTOR_POLYGONS",
                         "final_scientific_prediction": True,
                         "spatial": {
                             "crs": "EPSG:4326",
                             "features": [polygon(110.0, 35.0)],
                         },
                     }},
                ],
            ),
            "options": {"prediction_version_id": "ver_pred_9"},
            "catalog_seed": {},
        },
        {
            "name": "feature_normalization",
            "project": base_project(stratigraphy={"target_horizon": "SQ2"}),
            "options": {
                "prediction_payload": {
                    "result_summary": {
                        "spatial_output_type": "VECTOR_POLYGONS",
                        "final_scientific_prediction": True,
                        "spatial": {
                            "crs": "EPSG:4326",
                            "features": [
                                {"type": "Feature",
                                 "properties": {"name": "河道",
                                                "confidence": 0.8},
                                 "geometry": polygon()["geometry"]},
                                {"type": "Feature",
                                 "facies": "feature级相",
                                 "properties": {},
                                 "geometry": polygon(105.0)["geometry"]},
                                {"type": "Feature",
                                 "properties": {},
                                 "geometry": polygon(107.0)["geometry"]},
                            ],
                        },
                    }
                },
                "prediction_version_id": "v1",
            },
            "catalog_seed": {},
        },
    ]

    cases += run_case_list("draft", draft_cases, drive_draft)
    cases += run_case_list("production", prod_cases, drive_production)

    fixture = {
        "generator": "generate_map_compile_oracle.py",
        "frozen_from": "paleo_workbench/pipeline/compile_map{,_production}.py",
        "cases": cases,
    }
    out = (
        REPO
        / "libs/closure_workflow/closure_workflow_tests/fixtures"
        / "map_compile_oracle.json"
    )
    # NO sort_keys: the byte-level payload contract depends on insertion
    # order (the C++ replay must see the same key order the Python
    # functions operated on).
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=1))
    print(f"wrote {out} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
