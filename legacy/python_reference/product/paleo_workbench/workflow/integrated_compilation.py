"""§12 fusion production entry — evidence-set-driven Stage-3 computational fusion.

``workflow.factor_fusion`` (M5, decision D7) shipped fully tested with ZERO
production callers (audit P1-9): Stage-3 integrated interpretation was
manual-only.  This module is the missing wiring — it turns a workspace
Compilation Input Set (``select_evidence`` entries) into a runnable
:class:`~paleo_workbench.workflow.factor_fusion.FusionModel`, fuses it, and
returns a role-ready summary.  **No fusion science is implemented or altered
here** — every weight, normalisation and classification threshold is built,
recorded, and handed to :func:`~paleo_workbench.workflow.factor_fusion.fuse`
unchanged.

Layer-role / descriptor decision (no new ``LayerRole`` values are allowed in
``mapping_workspace``):

* The fused likelihood / confidence / variance grids are exposed as
  **scalar_grid descriptors** following the ``mapping.factor_layer_products``
  vocabulary (``layer_id / role / title / geometry_kind="raster" / payload /
  metadata`` with ``layer_type = SCALAR_GRID_LAYER_TYPE``) plus an explicit
  ``metadata["fusion"]`` provenance block.  Rendering them requires the canvas
  scalar publish path (snapshot consumption), which this module does not own —
  the descriptors are still produced so domain state is complete (same honest
  "descriptor-only" contract as the factor grid children).
* Their membership role is :attr:`LayerRole.ANALYSIS_AID` (分析辅助) — the
  existing vocabulary slot for computed, read-only analysis surfaces.  They are
  **not** factor children (no ``FACTOR_*`` role, no ``factor_task_id``) and
  **not** the integrated interpretation itself.
* :attr:`LayerRole.INTEGRATED_FACIES` stays reserved for the *editable*
  integrated draft.  The ``run_fusion`` stage action may seed that draft from
  the fused classification polygons when no draft exists yet (computational
  seed, human refinement); an existing draft is never overwritten.

Determinism contract — nothing is silently defaulted:

* ``weights=None`` → equal weights (1.0 each);
* ``class_names=None`` → three classes 低/中/高 (low/medium/high) with equal
  thirds thresholds [1/3, 2/3];
* ``normalizations=None`` → per-factor minmax over each grid's own finite
  value range (bounds live in the factor's own unit and land in the model
  provenance).

Every one of these defaults is recorded under ``qc["defaults"]`` of the
returned summary, and all of them (weights, bounds, thresholds) serialise via
the model's own provenance dict.

Degraded mode: running without a catalog service (``catalog=None``) skips
registration honestly — ``registered=False`` with an explicit reason — instead
of pretending the product is version-pinned.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.workflow.factor_fusion import (
    FactorEvidence,
    FusionModel,
    FusionResult,
    Normalization,
    fuse,
    register_output,
    sensitivity_report,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "DEFAULT_FUSION_CLASS_NAMES",
    "DEFAULT_FUSION_CLASS_THRESHOLDS",
    "build_fusion_model",
    "fusion_inputs_from_document",
    "run_integrated_fusion",
]

#: Deterministic default classes (low / medium / high).
DEFAULT_FUSION_CLASS_NAMES: tuple[str, ...] = ("低", "中", "高")

#: Equal-thirds thresholds matching :data:`DEFAULT_FUSION_CLASS_NAMES`.
DEFAULT_FUSION_CLASS_THRESHOLDS: tuple[float, ...] = (1.0 / 3.0, 2.0 / 3.0)

#: Default default-class label (matches the ``factor_fusion`` vocabulary).
DEFAULT_FUSION_DEFAULT_CLASS = "未定"  # undetermined

#: Default model name (appears in layer titles and catalog provenance).
DEFAULT_FUSION_MODEL_NAME = "综合证据融合"


def _task_id_of_evidence(value: object) -> str | None:
    """Task id of a ``factor:<task_id>:<version>`` evidence value (else None)."""
    parts = str(value or "").split(":")
    if len(parts) >= 2 and parts[0] == "factor" and parts[1]:
        return parts[1]
    return None


def _grid_from_catalog_version(catalog: Any, version_id: str):
    """Load a pinned factor-grid version from the catalog, or None."""
    from paleo_workbench.catalog.grid_artifact import read_grid_artifact

    if catalog is None or not version_id:
        return None
    try:
        version = catalog.get_version(version_id)
        path = catalog.resolve_path(version)
        return read_grid_artifact(path)
    except Exception:
        return None


def fusion_inputs_from_document(
    document: Any,
    evidence_set: Mapping[str, str],
    mismatches: list[str] | None = None,
    catalog: Any = None,
) -> dict[str, FactorGridResult]:
    """Resolve every ``factor:<task>:<version>`` evidence entry to its grid.

    When a selector carries a pinned version different from the task's
    current grid, that catalog artifact is the runtime input if it loads
    (#1271). A missing pin fails closed when the task already has a
    current version (refuse to fuse "current" as the pin). Catalogless
    live tokens (no current version, pin not in catalog) still resolve
    from the live cache.

    Raises:
        ValueError: listing every unresolvable factor task (unknown task id,
            or grid resolution failed) — never a silent partial evidence set.
    """
    from paleo_workbench.project.factor_grid_artifacts import (
        factor_grid_result_for_task,
    )

    tasks = {
        str(getattr(task, "id", "") or ""): task
        for task in (getattr(document, "factor_map_tasks", None) or [])
    }
    resolved: dict[str, FactorGridResult] = {}
    unresolvable: list[str] = []
    for label, value in dict(evidence_set or {}).items():
        task_id = _task_id_of_evidence(value)
        if task_id is None or task_id in resolved:
            continue
        task = tasks.get(task_id)
        if task is None:
            unresolvable.append(
                f"{label}（{value}）：工程中没有该单因素任务")
            continue
        pinned_version = ""
        parts = str(value).split(":")
        if len(parts) >= 3:
            pinned_version = parts[2]
        current_version = str(
            getattr(task, "grid_artifact_version_id", "") or "")
        if pinned_version and pinned_version != current_version:
            pinned = _grid_from_catalog_version(catalog, pinned_version)
            if pinned is not None:
                if mismatches is not None:
                    mismatches.append(
                        f"{label}：钉住版本 {pinned_version} ≠ 任务当前版本 "
                        f"{current_version or '∅'}——融合使用钉住网格")
                resolved[task_id] = pinned
                continue
            if current_version:
                unresolvable.append(
                    f"{label}（{value}）：钉住版本 {pinned_version} 无法从目录"
                    "装载网格（拒绝用当前网格冒充冻结输入）")
                continue
            # No current version and pin not in catalog: legacy live token.
        try:
            resolved[task_id] = factor_grid_result_for_task(task)
        except Exception as exc:  # noqa: BLE001 — report, never partial-fuse
            unresolvable.append(f"{label}（{value}）：{exc}")
    if unresolvable:
        raise ValueError(
            "以下证据因子无法解析为网格成果（pin 目录工件 → live 缓存 → "
            "npz 工件 → 内联参数均失败），拒绝在残缺证据集上融合："
            + "；".join(unresolvable)
        )
    return resolved


def _unique_factor_names(
    factor_results: Mapping[str, FactorGridResult],
) -> dict[str, str]:
    """Deterministic task-id-ordered evidence names, de-duplicated.

    ``FactorEvidence.factor_name`` keys rule tables and the sensitivity
    report; two tasks sharing one ``factor_name`` would silently merge there,
    so duplicates get an explicit ``(task_id)`` suffix.
    """
    names: dict[str, str] = {}
    seen: set[str] = set()
    for task_id in sorted(factor_results):
        grid = factor_results[task_id]
        base = str(getattr(grid, "factor_name", "") or task_id)
        name = base if base not in seen else f"{base}({task_id})"
        seen.add(name)
        names[task_id] = name
    return names


def _resolve_weights(
    task_ids: Sequence[str],
    weights: Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Equal-weight default (recorded) or validated explicit weights."""
    if weights is None:
        record = {"policy": "equal", "value": 1.0}
        return {task_id: 1.0 for task_id in task_ids}, record
    known = list(task_ids)
    unknown = [str(key) for key in weights if str(key) not in known]
    if unknown:
        raise ValueError(
            f"weights 引用了未知任务 {unknown}；可用任务 id：{known}"
        )
    resolved: dict[str, float] = {}
    for task_id in known:
        raw = weights.get(task_id)
        if raw is None:
            raise ValueError(f"weights 缺少任务 {task_id!r} 的权重")
        value = float(raw)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"任务 {task_id!r} 的权重必须为有限正数，得到 {raw!r}"
            )
        resolved[task_id] = value
    return resolved, {"policy": "explicit", "values": dict(resolved)}


def _resolve_classes(
    class_names: Sequence[str] | None,
    class_thresholds: Sequence[float] | None,
) -> tuple[list[str], list[float], dict[str, Any]]:
    """Default equal-thirds classes (recorded) or validated explicit scheme."""
    if class_names is None and class_thresholds is None:
        names = list(DEFAULT_FUSION_CLASS_NAMES)
        thresholds = [float(t) for t in DEFAULT_FUSION_CLASS_THRESHOLDS]
        record = {
            "policy": "default_equal_thirds",
            "class_names": names,
            "class_thresholds": thresholds,
        }
        return names, thresholds, record
    if class_names is None or class_thresholds is None:
        raise ValueError(
            "class_names 与 class_thresholds 必须同时提供"
            f"（得到 names={class_names is not None}, "
            f"thresholds={class_thresholds is not None}）；"
            "或同时省略以使用低/中/高三分默认"
        )
    names = [str(name) for name in class_names]
    thresholds = [float(t) for t in class_thresholds]
    if len(thresholds) != len(names) - 1:
        raise ValueError(
            f"class_thresholds 需要 len(class_names)-1={len(names) - 1} 个"
            f"阈值，得到 {len(thresholds)}"
        )
    record = {
        "policy": "explicit",
        "class_names": names,
        "class_thresholds": thresholds,
    }
    return names, thresholds, record


def _resolve_normalizations(
    factor_results: Mapping[str, FactorGridResult],
    names: Mapping[str, str],
    normalizations: Mapping[str, Normalization] | None,
) -> tuple[dict[str, Normalization], dict[str, Any]]:
    """Per-factor finite-range minmax default (recorded) or explicit bounds."""
    if normalizations is not None:
        unknown = [str(k) for k in normalizations if str(k) not in factor_results]
        if unknown:
            raise ValueError(
                f"normalizations 引用了未知任务 {unknown}；"
                f"可用任务 id：{sorted(factor_results)}"
            )
        resolved = {str(k): v for k, v in normalizations.items()}
        record = {
            "policy": "explicit",
            "bounds": {k: v.to_dict() for k, v in sorted(resolved.items())},
        }
        return resolved, record
    resolved: dict[str, Normalization] = {}
    for task_id in sorted(factor_results):
        grid = factor_results[task_id]
        lo = float(grid.statistics.min)
        hi = float(grid.statistics.max)
        if not (math.isfinite(lo) and math.isfinite(hi)):
            raise ValueError(
                f"因子 {names[task_id]!r}（任务 {task_id}）没有有限值——"
                "无法从数据确定归一化范围；请显式提供 normalizations"
            )
        if not hi > lo:
            raise ValueError(
                f"因子 {names[task_id]!r}（任务 {task_id}）是常数网格"
                f"（min == max == {lo}）——归一化需要 high > low；"
                "请显式提供 normalizations"
            )
        resolved[task_id] = Normalization(kind="minmax", low=lo, high=hi)
    record = {
        "policy": "per_factor_finite_range",
        "bounds": {k: v.to_dict() for k, v in sorted(resolved.items())},
    }
    return resolved, record


def build_fusion_model(
    evidence_set: Mapping[str, str],
    factor_results: Mapping[str, FactorGridResult],
    *,
    weights: Mapping[str, float] | None = None,
    normalizations: Mapping[str, Normalization] | None = None,
    default_class: str = DEFAULT_FUSION_DEFAULT_CLASS,
    class_names: Sequence[str] | None = None,
    class_thresholds: Sequence[float] | None = None,
    name: str = DEFAULT_FUSION_MODEL_NAME,
    weight_provenance: Mapping[str, Any] | None = None,
) -> FusionModel:
    """Build a weighted-evidence :class:`FusionModel` from a Compilation Input Set.

    Parameters:
        evidence_set: label → evidence value (``select_evidence`` vocabulary).
            Only ``factor:<task_id>:<version>`` entries are computational
            fusion inputs; other entries (draft/constraints references) are
            skipped — they belong to the manual interpretation path.
        factor_results: task_id → loaded ``FactorGridResult`` (see
            :func:`fusion_inputs_from_document`).
        weights: optional task_id → positive finite weight (default: equal).
        normalizations: optional task_id → :class:`Normalization` in the
            factor's own unit (default: minmax over each grid's finite range).
        default_class / class_names / class_thresholds: classification scheme
            (default: 低/中/高 at equal thirds).  ``default_class`` matches the
            ``factor_fusion`` vocabulary ("未定" = undetermined) and is
            provenance-only for the weighted family.
        name: model name used in layer titles and catalog provenance.

    Raises:
        ValueError: zero factor entries; evidence referencing a task missing
            from *factor_results*; unknown/non-positive weights; degenerate
            default normalisation ranges; inconsistent class schemes.  Grid
            geometry/CRS agreement is NOT re-checked here —
            ``fuse``/``_aligned_or_raise`` owns that contract.

    Evidence order is task-id-sorted, so the model fingerprint is
    deterministic for one evidence content.
    """
    wanted: list[str] = []
    for label, value in dict(evidence_set or {}).items():
        task_id = _task_id_of_evidence(value)
        if task_id is None:
            continue
        if task_id not in factor_results:
            raise ValueError(
                f"证据 {label!r}（{value}）引用的任务 {task_id!r} 不在已加载"
                f"网格中（已加载：{sorted(factor_results)}）——拒绝静默丢弃证据"
            )
        if task_id not in wanted:
            wanted.append(task_id)
    if not wanted:
        raise ValueError(
            "证据集中没有 factor:<task>:<version> 条目——加权证据融合至少"
            "需要一个单因素网格"
        )
    ordered = sorted(wanted)
    names = _unique_factor_names({t: factor_results[t] for t in ordered})
    resolved_weights, _weight_record = _resolve_weights(ordered, weights)
    resolved_norms, _norm_record = _resolve_normalizations(
        {t: factor_results[t] for t in ordered}, names, normalizations
    )
    class_names_r, class_thresholds_r, _class_record = _resolve_classes(
        class_names, class_thresholds
    )
    evidences = [
        FactorEvidence(
            factor_name=names[task_id],
            grid=factor_results[task_id],
            weight=resolved_weights[task_id],
            normalization=resolved_norms[task_id],
        )
        for task_id in ordered
    ]
    model = FusionModel(
        name=name,
        kind="weighted_evidence",
        evidences=evidences,
        default_class=default_class,
        class_thresholds=class_thresholds_r,
        class_names=class_names_r,
    )
    # V8 M5 weight provenance: WHO chose the weights and WHY travels with
    # the model (fingerprinted + catalog run parameters) — "explicit" vs
    # "equal default" alone could not answer who decided.
    if weight_provenance:
        record = {
            str(k): v for k, v in dict(weight_provenance).items() if v is not None
        }
        if record:
            model.weight_provenance = record
    return model


def _defaults_record(
    evidence_set: Mapping[str, str],
    factor_results: Mapping[str, FactorGridResult],
    *,
    weights: Mapping[str, float] | None,
    normalizations: Mapping[str, Normalization] | None,
    class_names: Sequence[str] | None,
    class_thresholds: Sequence[float] | None,
) -> dict[str, Any]:
    """The qc ``defaults`` block — mirrors exactly what build_fusion_model applied."""
    wanted = sorted(
        {
            task_id
            for value in dict(evidence_set or {}).values()
            if (task_id := _task_id_of_evidence(value)) is not None
        }
    )
    subset = {t: factor_results[t] for t in wanted}
    names = _unique_factor_names(subset)
    _, weight_record = _resolve_weights(wanted, weights)
    _, _, class_record = _resolve_classes(class_names, class_thresholds)
    _, norm_record = _resolve_normalizations(subset, names, normalizations)
    return {
        "weights": weight_record,
        "classes": class_record,
        "normalization": norm_record,
    }


def _fusion_scalar_descriptor(
    grid: FactorGridResult,
    result: FusionResult,
    *,
    quantity: str,
    title: str,
    catalog_version_id: str = "",
) -> dict[str, Any]:
    """Scalar-grid descriptor in the ``factor_layer_products`` vocabulary.

    Grid arrays never cross into the descriptor (``FactorGridResult.\
    to_descriptor`` metadata only); rendering requires the canvas scalar
    publish path, which the caller may not own — the registration is
    descriptor-only until that bridge exists.
    """
    from paleo_workbench.mapping.factor_layer_products import (
        SCALAR_GRID_LAYER_TYPE,
    )

    fingerprint = result.model.fingerprint()
    metadata: dict[str, Any] = {
        "layer_type": SCALAR_GRID_LAYER_TYPE,
        "quantity": quantity,
        "source": "factor_fusion",
        "algorithm_id": grid.algorithm_id,
        "crs": grid.crs,
        "unit": grid.unit,
        "extent": list(grid.extent),
        "width": grid.width,
        "height": grid.height,
        "statistics": grid.statistics.to_dict(),
        "artifact_version_id": catalog_version_id,
        "run_ref": grid.run_ref,
        "fusion": {
            "model_name": result.model.name,
            "model_fingerprint": fingerprint,
            "fusion_kind": result.model.kind,
            "class_names": list(result.class_names),
            "class_thresholds": list(result.model.class_thresholds),
            "evidence_count": len(result.model.evidences),
            "evidences": [ev.factor_name for ev in result.model.evidences],
        },
    }
    return {
        "layer_id": f"{quantity}:{fingerprint[:12]}",
        "role": LayerRole.ANALYSIS_AID,
        "title": title,
        "geometry_kind": "raster",
        "payload": {
            "layer_type": SCALAR_GRID_LAYER_TYPE,
            "factor_task_id": "",
            "quantity": quantity,
            "source": "factor_fusion",
            "descriptor": grid.to_descriptor(),
            "metadata": metadata,
        },
        "metadata": metadata,
    }


def _classification_features(
    result: FusionResult,
) -> tuple[list[tuple[dict, dict]], dict[str, Any]]:
    """Polygonised fused classification ((geometry, properties), qc).

    Reuses the single-factor polygonization pipeline on the fused likelihood
    with the model's own thresholds/names; failures are honest emptiness with
    an ``absent_reason`` — never a fabricated layer.
    """
    qc: dict[str, Any] = {"feature_count": 0}
    features: list[tuple[dict, dict]] = []
    try:
        from paleo_workbench.mapping.geological_pipeline.polygonization import (
            generate_facies_polygon_layer,
        )

        polygon_layer = generate_facies_polygon_layer(
            result.likelihood,
            thresholds=[float(t) for t in result.model.class_thresholds],
            facies_names=list(result.class_names),
        )
        snapshot = polygon_layer.to_snapshot()
        features = [
            (dict(record.get("geometry") or {}), dict(record.get("properties") or {}))
            for record in snapshot.features
        ]
        qc["polygon_qc"] = dict((polygon_layer.metadata or {}).get("polygon_qc") or {})
    except Exception as exc:  # noqa: BLE001 — honest absence, not a crash
        qc["absent_reason"] = f"polygonization failed: {exc}"
    qc["feature_count"] = len(features)
    return features, qc


def run_integrated_fusion(
    document: Any,
    evidence_set: Mapping[str, str],
    catalog: Any = None,
    *,
    weights: Mapping[str, float] | None = None,
    normalizations: Mapping[str, Normalization] | None = None,
    class_names: Sequence[str] | None = None,
    class_thresholds: Sequence[float] | None = None,
    register: bool = True,
    name: str = DEFAULT_FUSION_MODEL_NAME,
    weight_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build + fuse + (optionally) register the integrated fusion product.

    Pipeline: :func:`fusion_inputs_from_document` → :func:`build_fusion_model`
    → :func:`~paleo_workbench.workflow.factor_fusion.fuse` → optional
    :func:`~paleo_workbench.workflow.factor_fusion.register_output`.

    Returns a summary dict with:

    * ``likelihood_descriptor`` / ``confidence_descriptor`` /
      ``variance_descriptor`` (``None` when inputs carried no variance) —
      scalar_grid descriptors with ``metadata["fusion"]`` provenance;
    * ``variance_available`` — bool;
    * ``class_names`` — the classification vocabulary actually used;
    * ``classification_features`` — ((geometry, properties), …) polygonised
      classification for seeding the integrated draft;
    * ``qc`` — the fusion QC (class counts, unit warnings, coverage) plus
      ``defaults`` (every defaulted weight/class/normalisation policy) and
      ``registration``;
    * ``sensitivity`` — leave-one-factor-out report;
    * ``registered`` / ``catalog_version_id`` — registration outcome (honest
      ``False`` with a reason when ``register=False`` or no catalog service).
    """
    from paleo_workbench.workflow.interpretation.compilation import (
        active_input_set,
    )

    input_set = active_input_set(document)
    if input_set is not None and not getattr(input_set, "frozen", False):
        raise ValueError("请先冻结 Compilation Input Set 再运行融合")
    pin_mismatches: list[str] = []
    factor_results = fusion_inputs_from_document(
        document, evidence_set, mismatches=pin_mismatches, catalog=catalog)
    model = build_fusion_model(
        evidence_set,
        factor_results,
        weights=weights,
        normalizations=normalizations,
        class_names=class_names,
        class_thresholds=class_thresholds,
        name=name,
        weight_provenance=weight_provenance,
    )
    result = fuse(model)

    # V9 (P1-7): pin-vs-current mismatch must ride the QC — the fusion used
    # the current grid while the evidence set pinned older versions; the
    # product may never read as if it fused exactly the pinned inputs.
    if pin_mismatches:
        result.qc["pinned_version_mismatches"] = list(pin_mismatches)

    # qc extras FIRST: register_output snapshots result.qc into the run
    # provenance, so the defaults record must be on it before registration.
    confidence_values = np.asarray(result.confidence.grid_z, dtype=float)
    finite_conf = confidence_values[np.isfinite(confidence_values)]
    result.qc["confidence_coverage"] = {
        "finite_fraction": (
            float(finite_conf.size) / float(confidence_values.size)
            if confidence_values.size
            else 0.0
        ),
        "mean": float(finite_conf.mean()) if finite_conf.size else None,
    }
    result.qc["defaults"] = _defaults_record(
        evidence_set,
        factor_results,
        weights=weights,
        normalizations=normalizations,
        class_names=class_names,
        class_thresholds=class_thresholds,
    )
    features, classification_qc = _classification_features(result)
    result.qc["classification"] = classification_qc

    registration: dict[str, Any] = {
        "requested": bool(register),
        "registered": False,
    }
    catalog_version_id = ""
    if register and catalog is not None:
        catalog_version_id = register_output(catalog, result)
        registration.update({
            "registered": True,
            "catalog_version_id": catalog_version_id,
            "confidence_version_id": str(result.qc.get("confidence_version_id") or ""),
            "variance_version_id": str(result.qc.get("variance_version_id") or ""),
        })
    elif not register:
        registration["reason"] = "register=False"
    else:
        registration["reason"] = (
            "catalog service unavailable (no project catalog wired) — "
            "product not version-pinned; re-run with a catalog to register"
        )

    # V8 M5: reuse the sensitivity cached by registration when present —
    # computing it twice doubled the (N-1) re-fusions per run.
    sensitivity = result.qc.pop("_cached_sensitivity", None)
    if sensitivity is None:
        sensitivity = sensitivity_report(model, result)
    qc = dict(result.qc)
    qc["registration"] = registration

    likelihood_descriptor = _fusion_scalar_descriptor(
        result.likelihood,
        result,
        quantity="fusion_likelihood",
        title=f"{model.name}·融合似然",
        catalog_version_id=catalog_version_id,
    )
    confidence_descriptor = _fusion_scalar_descriptor(
        result.confidence,
        result,
        quantity="fusion_confidence",
        title=f"{model.name}·融合置信度",
        catalog_version_id=str(result.qc.get("confidence_version_id") or ""),
    )
    variance_descriptor = None
    if result.variance is not None:
        variance_descriptor = _fusion_scalar_descriptor(
            result.variance,
            result,
            quantity="fusion_variance",
            title=f"{model.name}·融合方差",
            # V8 review R1-P2: bind the registered sibling version so the
            # descriptor resolves from the catalog like confidence does.
            catalog_version_id=str(result.qc.get("variance_version_id") or ""),
        )

    return {
        "model_name": model.name,
        "n_factors": len(model.evidences),
        "likelihood_descriptor": likelihood_descriptor,
        "confidence_descriptor": confidence_descriptor,
        "variance_descriptor": variance_descriptor,
        "variance_available": result.variance is not None,
        "class_names": list(result.class_names),
        "classification_features": features,
        "registered": bool(registration["registered"]),
        "catalog_version_id": catalog_version_id,
        "qc": qc,
        "sensitivity": sensitivity,
    }
