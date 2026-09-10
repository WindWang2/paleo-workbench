"""FactorProduct — 单因素分析成果的统一领域投影（V9 ADR-4）。

一个单因素分析的 grid / contours / polygons / uncertainty / QC 不再是
彼此无关的渲染期产物：它们是同一个 :class:`FactorProduct` 的不同
artifacts（goal §7）。本模块是**只读投影**——写路径仍由
``factor_interpolation`` / ``factor_grid_artifacts`` / ``catalog.lifecycle``
拥有；身份 = FactorMapTask.id（task id 是既有稳定身份），载荷权威 =
catalog 版本 / npz artifact / live cache。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.factor_units import (
    FACTOR_FAMILIES,
    unit_for_factor,
)


def factor_family_for_type(factor_type: str) -> str:
    """因子类型 → 家族 key（FACTOR_FAMILIES 反查；未知→""，不猜）。"""
    key = str(factor_type or "").strip().lower()
    if not key:
        return ""
    for family, aliases in FACTOR_FAMILIES.items():
        if key in {alias.lower() for alias in aliases}:
            return family
    return ""


@dataclass(frozen=True)
class FactorArtifactRef:
    """FactorProduct 的一个 artifact（presence + 版本引用 + 诚实缺失原因）。"""

    artifact: str  # grid | contours | polygons | uncertainty | qc
    present: bool
    version_id: str = ""
    #: present=False 时的诚实原因（绝不静默缺失）。
    absent_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "present": self.present,
            "version_id": self.version_id,
            "absent_reason": self.absent_reason,
        }


@dataclass(frozen=True)
class FactorProduct:
    """一次单因素分析的完整领域身份（投影，绝不复制载荷）。"""

    factor_id: str                       # = FactorMapTask.id
    name: str = ""
    factor_type: str = ""
    factor_family: str = ""
    target_horizon: str = ""
    #: engine 规范算法 id（经 algorithm_registry.canonical_algorithm_id）。
    algorithm_id: str = ""
    method_label: str = ""               # 任务记录的原始 method 字符串
    parameters: dict[str, Any] = field(default_factory=dict)
    unit: str = ""
    unit_declared: bool = False
    crs: str = ""
    crs_declared: bool = False
    grid_shape: tuple[int, ...] = ()
    #: 输入版本（run inputs；经 grid_artifact_version_id → run → inputs）。
    input_version_ids: tuple[str, ...] = ()
    grid_version_id: str = ""
    run_id: str = ""
    source_kind: str = ""
    generator_version: str = ""
    #: 来自 quality_metrics 的 QC 摘要（只取已知键）。
    qc: dict[str, Any] = field(default_factory=dict)
    #: workspace 成熟度（draft/reviewed/frozen/published）。
    maturity: str = "draft"
    #: 工作区新鲜度状态（dependencies 服务词汇；""=未评估）。
    freshness: str = ""
    freshness_detail: str = ""
    artifacts: tuple[FactorArtifactRef, ...] = ()
    constraint_pins: tuple[dict[str, Any], ...] = ()
    created_at: str = ""

    @property
    def is_mock(self) -> bool:
        return self.source_kind in ("mock", "mixed")

    @property
    def has_uncertainty(self) -> bool:
        return any(
            a.artifact == "uncertainty" and a.present for a in self.artifacts)

    def artifact(self, kind: str) -> FactorArtifactRef:
        for ref in self.artifacts:
            if ref.artifact == kind:
                return ref
        return FactorArtifactRef(kind, False, "", "not part of this product")

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "name": self.name,
            "factor_type": self.factor_type,
            "factor_family": self.factor_family,
            "target_horizon": self.target_horizon,
            "algorithm_id": self.algorithm_id,
            "method_label": self.method_label,
            "unit": self.unit,
            "unit_declared": self.unit_declared,
            "crs": self.crs,
            "crs_declared": self.crs_declared,
            "grid_shape": list(self.grid_shape),
            "input_version_ids": list(self.input_version_ids),
            "grid_version_id": self.grid_version_id,
            "run_id": self.run_id,
            "source_kind": self.source_kind,
            "generator_version": self.generator_version,
            "qc": dict(self.qc),
            "maturity": self.maturity,
            "freshness": self.freshness,
            "freshness_detail": self.freshness_detail,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "constraint_pins": [dict(p) for p in self.constraint_pins],
            "created_at": self.created_at,
        }


def _task_run_inputs(catalog: Any, run_id: str) -> list[str]:
    if catalog is None or not run_id:
        return []
    try:
        run = catalog.resolve_run(run_id)
    except Exception:  # noqa: BLE001 — 溯源缺失→空（版本字段诚实为空）
        return []
    if run is None:
        return []
    return [str(v) for v in (getattr(run, "input_version_ids", None) or [])]


def factor_product_for_task(
    document: Any,
    task_id: str,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
    freshness_entry: Any = None,
) -> FactorProduct | None:
    """从文档任务投影 FactorProduct（task 不存在 → None）。"""
    task = None
    for candidate in getattr(document, "factor_map_tasks", None) or []:
        if str(candidate.id) == str(task_id):
            task = candidate
            break
    if task is None:
        return None

    params = dict(task.parameters or {})
    metrics = dict(task.quality_metrics or {})
    metadata = dict(task.grid_metadata or {})

    # 算法身份：任务 method 是 UI 标签或 engine id（历史两者皆有）——
    # 经注册表规范化；无法识别时诚实保留原串并标记。
    method_label = str(task.method or "")
    from paleo_workbench.workflow.interpretation.algorithm_registry import (
        canonical_algorithm_id,
    )

    try:
        algorithm_id = canonical_algorithm_id(method_label)
    except ValueError:
        algorithm_id = ""  # 未知方法词汇：绝不猜（摘要层如实显示 method_label）

    # 单位：grid 契约 > 任务参数 > 因子默认（默认标注 unit_declared=False）。
    declared_unit = metadata.get("unit")
    unit = ""
    unit_declared = False
    if declared_unit:
        unit = str(declared_unit)
        unit_declared = True
    elif params.get("unit"):
        unit = str(params["unit"])
        unit_declared = True
    else:
        unit = unit_for_factor(task.factor_type) or ""
        if unit:
            unit_declared = False  # 家族默认，非本任务声明

    crs = metadata.get("crs") or ""
    grid_shape = tuple(metadata.get("shape") or ())

    grid_version_id = str(task.grid_artifact_version_id or "")
    run_id = ""
    input_versions: list[str] = []
    if grid_version_id and catalog is not None:
        try:
            info = catalog.resolve_version(grid_version_id)
        except Exception:  # noqa: BLE001
            info = None
        if info is not None:
            run_id = str(getattr(info, "run_id", "") or "")
            input_versions = _task_run_inputs(catalog, run_id)

    qc_keys = (
        "r_squared", "r2", "n_points", "backend", "mean", "range",
        "variance_min", "variance_max", "distance_policy",
        "duplicate_wells_dropped", "synthesized_fallback",
    )
    qc = {k: metrics[k] for k in qc_keys if k in metrics}

    # artifacts：grid 为载荷权威；派生件按能力诚实标注 presence。
    from paleo_workbench.mapping_workspace.artifact_keys import factor_key

    maturity = "draft"
    if workspace_state is not None:
        maturity = workspace_state.maturity_of(factor_key(task.id))
    freshness = ""
    freshness_detail = ""
    if freshness_entry is not None:
        freshness = str(getattr(freshness_entry, "status", "") or "")
        if freshness:
            freshness = str(getattr(freshness_entry.status, "value",
                                    freshness_entry.status))
        freshness_detail = str(getattr(freshness_entry, "detail", "") or "")

    has_variance = bool(metrics.get("variance_min") is not None
                        or metadata.get("has_variance"))
    artifacts = (
        FactorArtifactRef(
            "grid", bool(grid_version_id or metadata), grid_version_id,
            "" if (grid_version_id or metadata) else "尚无插值结果（任务未完成）"),
        FactorArtifactRef(
            "contours", bool(metadata),
            "", "" if metadata else "等值线由 grid 派生（渲染期生成，无独立版本）"),
        FactorArtifactRef(
            "polygons", False, "",
            "分类多边形由 grid 派生（按阈值请求生成，无独立版本）"),
        FactorArtifactRef(
            "uncertainty", has_variance,
            "", "" if has_variance else
            ("本方法不产生不确定度面（algorithm_registry.produces_uncertainty）"
             if algorithm_id == "idw" else "任务无方差记录")),
        FactorArtifactRef(
            "qc", bool(qc), "",
            "" if qc else "无质量指标记录"),
    )

    pins = [dict(p) for p in (params.get("constraint_pins") or [])]

    return FactorProduct(
        factor_id=str(task.id),
        name=str(task.name or ""),
        factor_type=str(task.factor_type or ""),
        factor_family=factor_family_for_type(str(task.factor_type or "")),
        target_horizon=str(task.target_horizon or ""),
        algorithm_id=algorithm_id,
        method_label=method_label,
        parameters=params,
        unit=unit,
        unit_declared=unit_declared,
        crs=str(crs or ""),
        crs_declared=bool(crs),
        grid_shape=grid_shape,
        input_version_ids=tuple(input_versions),
        grid_version_id=grid_version_id,
        run_id=run_id,
        source_kind=str(task.source_kind or ""),
        generator_version=str(task.generator_version or ""),
        qc=qc,
        maturity=maturity,
        freshness=freshness,
        freshness_detail=freshness_detail,
        artifacts=artifacts,
        constraint_pins=tuple(pins),
        created_at=str(getattr(task, "created_at", "") or ""),
    )


def factor_products(
    document: Any,
    *,
    catalog: Any = None,
    workspace_state: Any = None,
) -> list[FactorProduct]:
    """全部任务的产品投影（一次新鲜度评估复用，避免 O(n²) 重评估）。"""
    freshness_by_task: dict[str, Any] = {}
    if workspace_state is not None and document is not None:
        try:
            from paleo_workbench.mapping_workspace.dependencies import (
                MappingDependencyService,
            )

            summary = MappingDependencyService().evaluate(
                document, workspace_state, catalog)
            for entry in summary.artifacts:
                # factor_key 形如 "factor:<task_id>"
                if entry.artifact_type == "factor" \
                        and entry.artifact_key.startswith("factor:"):
                    task_id = entry.artifact_key.split(":", 1)[1]
                    if task_id:
                        freshness_by_task[task_id] = entry
        except Exception:  # noqa: BLE001 — 新鲜度评估失败不阻断投影
            freshness_by_task = {}
    out = []
    for task in getattr(document, "factor_map_tasks", None) or []:
        product = factor_product_for_task(
            document, task.id, catalog=catalog,
            workspace_state=workspace_state,
            freshness_entry=freshness_by_task.get(str(task.id)))
        if product is not None:
            out.append(product)
    return out
