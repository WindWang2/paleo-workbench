from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from paleo_workbench.project.models import PredictionTask, ProjectDocument, ResourceItem

GENERATOR_VERSION = "mock-prediction-v1"
LOCAL_GENERATOR_VERSION = "local-asset-prediction-v1"

_FACIES_SAND = ("三角洲前缘砂体", "水下分流河道砂体", "滨岸砂体", "河道砂体")
_FACIES_MUD = ("分流间湾泥", "前三角洲泥", "滨岸泥", "泛滥平原泥")


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_resource_path(resource: ResourceItem, project: ProjectDocument) -> Path | None:
    raw = str(getattr(resource, "path", "") or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    root = str(getattr(project.meta, "project_root", "") or "").strip()
    if root and root not in {".", ".."}:
        joined = (Path(root).expanduser() / raw).resolve()
        if joined.is_file():
            return joined
    return candidate if candidate.exists() else None


def _resource_inputs(
    project: ProjectDocument,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project well-log / seismic resources → plain input dicts.

    The heuristic core (:func:`run_heuristic_facies`) consumes these dicts so
    both the legacy :class:`LocalAssetPredictionAdapter` (from the project) and
    the ModelRegistry-backed provider (from catalog input versions) share ONE
    implementation.
    """
    wells: list[dict[str, Any]] = []
    for resource in project.resources:
        if resource.type != "well_log":
            continue
        path = _resolve_resource_path(resource, project)
        wells.append(
            {
                "name": resource.name,
                "path": str(path) if path is not None else "",
                "readable": bool(path is not None and path.is_file()),
                "format": resource.format,
            }
        )
    seismics: list[dict[str, Any]] = []
    for resource in project.resources:
        if resource.type != "seismic":
            continue
        path = _resolve_resource_path(resource, project)
        seismics.append(
            {
                "name": resource.name,
                "path": str(path) if path is not None else resource.path,
                "readable": bool(path is not None and path.is_file()),
                "format": resource.format,
                "parsed_summary": getattr(resource, "parsed_summary", None) or {},
            }
        )
    return wells, seismics


def run_heuristic_facies(
    well_inputs: list[dict[str, Any]],
    seismic_inputs: list[dict[str, Any]],
    *,
    seed: int,
    factor_map_ids: list[str],
) -> dict[str, Any]:
    """Deterministic GR-median / window facies heuristic (honest, uncalibrated).

    This is the shared computational core for the local-asset heuristic. It
    NEVER fabricates "scientific" output:

    - readable well LAS with GR (or first curve) → real depth-annotated zones
    - otherwise, when ANY input exists → a seeded random TEMPLATE clearly
      marked ``template=True`` (the caller must reflect this as
      ``is_mock=True`` — random output must never display as 真实)
    - no inputs at all → ``source_kind="mock"`` with empty regions; the caller
      decides (legacy adapter falls back to MockPredictionAdapter; the
      registry-backed provider raises an honest no-input error).

    Probabilities are heuristic estimates, NOT calibrated posterior
    probabilities — callers must label them as such.
    """
    regions: list[dict[str, Any]] = []
    well_meta: dict[str, Any] = {}
    source_kind = "mock"

    for well in well_inputs[:3]:
        path = well.get("path") or ""
        if not path or not well.get("readable"):
            continue
        derived = _regions_from_las(Path(path), seed=seed)
        if derived:
            regions = derived["regions"]
            well_meta = {
                "source_well": well.get("name", ""),
                "source_path": path,
                "curve": derived.get("curve"),
                "top_depth": derived.get("top"),
                "bottom_depth": derived.get("bottom"),
            }
            source_kind = "las_curve"
            break

    seismic_meta: dict[str, Any] = {}
    for seismic in seismic_inputs[:1]:
        path = seismic.get("path") or ""
        summary = seismic.get("parsed_summary") or {}
        seismic_meta = {
            "source_seismic": seismic.get("name", ""),
            "source_path": path,
            "format": seismic.get("format", ""),
            "summary": summary if isinstance(summary, dict) else {},
            "path_readable": bool(seismic.get("readable")),
        }
        if source_kind == "mock":
            source_kind = "seismic_path"
        else:
            source_kind = "las_and_seismic"
        break

    if source_kind == "mock" and not regions:
        # No usable inputs — caller decides (mock fallback vs honest error).
        return {
            "regions": [],
            "well_meta": {},
            "seismic_meta": seismic_meta,
            "source_kind": "mock",
            "template": False,
            "factor_map_ids": list(factor_map_ids),
        }

    template = False
    if not regions:
        # Seismic-only (or unreadable wells): deterministic seeded template,
        # HONESTLY marked — this output must never display as 真实.
        rng = random.Random(seed + 17)
        facies = list(_FACIES_SAND) + list(_FACIES_MUD)
        regions = [
            {
                "region_id": f"seis_region_{i + 1}",
                "facies": facies[i % len(facies)],
                "probability": round(0.6 + rng.random() * 0.3, 3),
            }
            for i in range(4)
        ]
        template = True
    return {
        "regions": regions,
        "well_meta": well_meta,
        "seismic_meta": seismic_meta,
        "source_kind": source_kind,
        "template": template,
        "factor_map_ids": list(factor_map_ids),
    }


class MockPredictionAdapter:
    adapter_kind = "mock"
    schema_version = "1.0"

    def run(
        self,
        project: ProjectDocument,
        factor_map_ids: list[str],
        seed: int,
    ) -> PredictionTask:
        rng = random.Random(seed)
        facies = list(_FACIES_SAND) + list(_FACIES_MUD)
        predicted = [
            {
                "region_id": f"mock_region_{i + 1}",
                "facies": facies[i % len(facies)],
                "probability": round(0.55 + rng.random() * 0.35, 3),
            }
            for i in range(4)
        ]
        snapshot = {
            "factor_map_ids": factor_map_ids,
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "schema_version": self.schema_version,
        }
        task = PredictionTask(
            name="Mock sedimentary facies prediction",
            adapter_kind=self.adapter_kind,
            input_factor_map_ids=factor_map_ids,
            result_summary={
                "predicted_regions": predicted,
                "is_mock": True,
                "is_replaceable": True,
                "final_scientific_prediction": False,
                "demo": True,
                "source": "synthetic/demo",
                "model_type": "demo",
            },
            probability_summary={
                "mean_probability": round(
                    sum(item["probability"] for item in predicted) / len(predicted),
                    3,
                ),
            },
            evidence_contribution=[
                {"name": "sand_thickness", "weight": 0.45},
                {"name": "target_horizon", "weight": 0.30},
                {"name": "neighbor_wells", "weight": 0.25},
            ],
            review_areas=[item for item in predicted if item["probability"] < 0.7],
            status="complete",
            adapter_schema_version=self.schema_version,
            input_snapshot_hash=_snapshot_hash(snapshot),
            generator_version=GENERATOR_VERSION,
            seed=seed,
        )
        project.prediction_tasks.append(task)
        # Register a prediction DataRun (data-provenance layer). Errors are NOT
        # swallowed: a catalog failure must surface instead of silently losing
        # the provenance record.
        from paleo_workbench.catalog.lifecycle import register_prediction_run

        register_prediction_run(task, factor_task_ids=factor_map_ids)
        return task


class LocalAssetPredictionAdapter:
    """Deterministic facies prediction driven by bound LAS/SEGY when readable.

    - LAS with GR (or first curve): windowed mean → sand/mud facies along depth
    - SEGY path present: record volume path/meta for seismic host
    - Falls back to :class:`MockPredictionAdapter` when no usable assets exist.

    Honest labeling (P2): the GR median/window rule is a HEURISTIC — output is
    ``final_scientific_prediction=False``, ``model_type="heuristic"`` and the
    probabilities are uncalibrated. The seismic-only random template is marked
    ``is_mock=True`` (random output must never display as 真实).
    """

    adapter_kind = "local"
    schema_version = "1.0"

    def run(
        self,
        project: ProjectDocument,
        factor_map_ids: list[str],
        seed: int,
    ) -> PredictionTask:
        wells, seismics = _resource_inputs(project)
        core = run_heuristic_facies(
            wells, seismics, seed=seed, factor_map_ids=factor_map_ids
        )
        if core["source_kind"] == "mock" and not core["regions"]:
            return MockPredictionAdapter().run(project, factor_map_ids, seed=seed)

        regions = core["regions"]
        well_meta = core["well_meta"]
        seismic_meta = core["seismic_meta"]
        source_kind = core["source_kind"]
        template = core["template"]

        mean_p = round(
            sum(float(r.get("probability", 0) or 0) for r in regions) / max(len(regions), 1),
            3,
        )
        snapshot = {
            "factor_map_ids": factor_map_ids,
            "seed": seed,
            "generator_version": LOCAL_GENERATOR_VERSION,
            "schema_version": self.schema_version,
            "source_kind": source_kind,
            "well_meta": well_meta,
            "seismic_meta": {k: seismic_meta[k] for k in ("source_seismic", "path_readable") if k in seismic_meta},
        }
        evidence = [
            {"name": "bound_well_log", "weight": 0.5 if well_meta else 0.1},
            {"name": "bound_seismic", "weight": 0.3 if seismic_meta else 0.1},
            {"name": "factor_maps", "weight": 0.2 if factor_map_ids else 0.1},
        ]
        # renormalize weights
        total_w = sum(e["weight"] for e in evidence) or 1.0
        for e in evidence:
            e["weight"] = round(e["weight"] / total_w, 3)

        # Random template output must never display as 真实.
        is_mock = source_kind == "mock" or template
        task = PredictionTask(
            name="Local asset sedimentary facies prediction",
            adapter_kind=self.adapter_kind,
            input_factor_map_ids=factor_map_ids,
            result_summary={
                "predicted_regions": regions,
                "is_mock": is_mock,
                "is_replaceable": True,
                "final_scientific_prediction": False,
                "model_type": "heuristic",
                "probabilities_uncalibrated": True,
                "source_kind": source_kind,
                "well_meta": well_meta,
                "seismic_meta": seismic_meta,
                "demo": template,
                "source": "synthetic/demo" if template else "bound_assets",
            },
            probability_summary={"mean_probability": mean_p},
            evidence_contribution=evidence,
            review_areas=[item for item in regions if float(item.get("probability", 1)) < 0.7],
            status="complete",
            adapter_schema_version=self.schema_version,
            input_snapshot_hash=_snapshot_hash(snapshot),
            generator_version=LOCAL_GENERATOR_VERSION,
            seed=seed,
        )
        project.prediction_tasks.append(task)
        # Register a prediction DataRun (data-provenance layer). Errors are NOT
        # swallowed: a catalog failure must surface instead of silently losing
        # the provenance record.
        from paleo_workbench.catalog.lifecycle import register_prediction_run

        register_prediction_run(task, factor_task_ids=factor_map_ids)
        return task


def _regions_from_las(path: Path, *, seed: int, n_zones: int = 4) -> dict[str, Any] | None:
    """Derive sand/mud facies zones from GR (or first curve) statistics."""
    try:
        from geoviz import load_las_preview
    except Exception:
        return None
    try:
        data = load_las_preview(str(path))
    except Exception:
        return None
    if data is None:
        return None
    curves = list(getattr(data, "curves", None) or [])
    if not curves:
        return None
    curve = None
    for c in curves:
        name = str(getattr(c, "name", "") or "").upper()
        if name in {"GR", "GAMMA", "SGR", "CGR"}:
            curve = c
            break
    if curve is None:
        curve = curves[0]
    depths = list(getattr(curve, "depth", None) or [])
    values = list(getattr(curve, "values", None) or [])
    pairs = [
        (float(d), float(v))
        for d, v in zip(depths, values)
        if d is not None and v is not None
    ]
    pairs = [(d, v) for d, v in pairs if abs(v) < 1e10]  # drop LAS nulls roughly
    if len(pairs) < 4:
        return None
    depths_f = [p[0] for p in pairs]
    values_f = [p[1] for p in pairs]
    top, bottom = min(depths_f), max(depths_f)
    n = max(2, min(int(n_zones), len(pairs) // 2))
    # Sort by depth for windowing
    ordered = sorted(pairs, key=lambda p: p[0])
    chunk = max(1, len(ordered) // n)
    median = sorted(values_f)[len(values_f) // 2]
    rng = random.Random(seed + int(median * 10) % 1000)
    regions: list[dict[str, Any]] = []
    for i in range(n):
        start = i * chunk
        end = len(ordered) if i == n - 1 else min(len(ordered), (i + 1) * chunk)
        window = ordered[start:end]
        if not window:
            continue
        mean_v = sum(v for _, v in window) / len(window)
        d0, d1 = window[0][0], window[-1][0]
        if mean_v <= median:
            facies = _FACIES_SAND[i % len(_FACIES_SAND)]
            # lower GR → higher sand confidence
            prob = round(min(0.95, 0.65 + (median - mean_v) / (abs(median) + 1e-6) * 0.2), 3)
        else:
            facies = _FACIES_MUD[i % len(_FACIES_MUD)]
            prob = round(min(0.95, 0.60 + (mean_v - median) / (abs(median) + 1e-6) * 0.15), 3)
        prob = max(0.55, min(0.95, prob + rng.uniform(-0.02, 0.02)))
        regions.append(
            {
                "region_id": f"las_zone_{i + 1}",
                "facies": facies,
                "probability": round(prob, 3),
                "top": round(float(d0), 3),
                "bottom": round(float(d1), 3),
                "mean_curve": round(float(mean_v), 3),
            }
        )
    if not regions:
        return None
    return {
        "regions": regions,
        "curve": str(getattr(curve, "name", "") or "curve"),
        "top": top,
        "bottom": bottom,
    }
