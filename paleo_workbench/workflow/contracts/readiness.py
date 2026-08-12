"""Metadata-only readiness evaluation (Stage 11).

Distinct from Stage-9 freshness: readiness asks whether required inputs
exist to *run* a module; freshness asks whether existing results are current.
Never loads SEG-Y/LAS bodies or factor NPZ arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.contracts.models import (
    DomainWorkflowContract,
    ImplementationStatus,
    InputCardinality,
    ReadinessReason,
    ReadinessStatus,
)
from paleo_workbench.workflow.contracts.registry import (
    WorkflowContractRegistry,
    get_default_registry,
)


@dataclass
class ReadinessReport:
    contract_id: str
    status: ReadinessStatus
    reasons: list[ReadinessReason] = field(default_factory=list)
    implementation_status: ImplementationStatus = ImplementationStatus.PARTIAL
    # Explicit: not freshness
    freshness_note: str = "freshness_owned_by_stage9"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "status": self.status.value,
            "reasons": [r.model_dump() for r in self.reasons],
            "implementation_status": self.implementation_status.value,
            "freshness_note": self.freshness_note,
        }


def _resource_counts(project: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in getattr(project, "resources", None) or []:
        t = getattr(r, "type", "") or "unknown"
        counts[t] = counts.get(t, 0) + 1
    return counts


def _count_for_types(counts: dict[str, int], types: list[str]) -> int:
    if not types:
        return 0
    return sum(counts.get(t, 0) for t in types)


def evaluate_contract_readiness(
    project: Any,
    contract: DomainWorkflowContract,
) -> ReadinessReport:
    """Evaluate readiness for one contract using project metadata only."""
    reasons: list[ReadinessReason] = []
    counts = _resource_counts(project)

    # Demo/partial honesty: never claim production-ready path when DEMO contract
    # with only mock artifacts — still can be READY to *run* the demo path.
    for inp in contract.inputs:
        if not inp.required:
            continue
        n = 0
        if inp.resource_types:
            n = _count_for_types(counts, inp.resource_types)
        elif inp.id == "sample_points":
            # Factor tasks with sample_points in parameters (metadata presence)
            for task in getattr(project, "factor_map_tasks", None) or []:
                pts = (getattr(task, "parameters", None) or {}).get("sample_points")
                if pts:
                    n += 1
        elif inp.id == "target_horizon":
            # Stratigraphy, factor tasks, or paleomap linked horizon (metadata only).
            th = getattr(getattr(project, "stratigraphy", None), "target_horizon", "") or ""
            if th.strip():
                n = 1
            if n < 1:
                for task in getattr(project, "factor_map_tasks", None) or []:
                    if (getattr(task, "target_horizon", None) or "").strip():
                        n = 1
                        break
            if n < 1:
                for doc in getattr(project, "paleomap_documents", None) or []:
                    if (getattr(doc, "linked_target_horizon", None) or "").strip():
                        n = 1
                        break
        elif inp.id == "map_document":
            n = len(getattr(project, "paleomap_documents", None) or [])
        elif inp.id == "factor_maps":
            n = sum(
                1
                for t in (getattr(project, "factor_map_tasks", None) or [])
                if getattr(t, "status", "") == "complete"
                or getattr(t, "grid_artifact_path", None)
            )
        elif inp.id in {"source_products", "prediction_or_factors", "parent_version", "seismic_or_seed"}:
            # optional-ish; required handled below by cardinality on other fields
            continue
        elif inp.id == "wells":
            n = counts.get("well_log", 0)
        elif inp.id == "well_logs":
            n = counts.get("well_log", 0)
        elif inp.id == "las_files":
            n = counts.get("well_log", 0)
        elif inp.id == "segy":
            n = counts.get("seismic", 0)
        elif inp.id == "seismic":
            n = counts.get("seismic", 0)
        elif inp.id == "source_files":
            n = sum(counts.values())

        need = 1
        if inp.cardinality is InputCardinality.ONE_OR_MORE:
            need = 1
        elif inp.cardinality is InputCardinality.EXACTLY_ONE:
            need = 1

        if n < need:
            reasons.append(
                ReadinessReason(
                    code=f"missing_input:{inp.id}",
                    message_zh=f"缺少必需输入：{inp.name}",
                    severity="block",
                    input_id=inp.id,
                )
            )

    # Module-specific soft checks
    if contract.id == "factor_interpolation":
        tasks = getattr(project, "factor_map_tasks", None) or []
        if not tasks:
            reasons.append(
                ReadinessReason(
                    code="no_factor_task",
                    message_zh="尚未创建单因素图任务",
                    severity="block",
                )
            )
        else:
            incomplete = [
                t
                for t in tasks
                if not (getattr(t, "parameters", None) or {}).get("sample_points")
            ]
            if len(incomplete) == len(tasks):
                reasons.append(
                    ReadinessReason(
                        code="no_sample_points",
                        message_zh="单因素任务缺少样点 sample_points",
                        severity="block",
                    )
                )
            if not any((getattr(t, "target_horizon", None) or "").strip() for t in tasks):
                reasons.append(
                    ReadinessReason(
                        code="no_target_horizon",
                        message_zh="缺少目标层位",
                        severity="block",
                    )
                )

    if contract.id == "paleomap_compile":
        # P0 mapping path requires a paleomap document with linked target horizon.
        docs = getattr(project, "paleomap_documents", None) or []
        if not docs:
            reasons.append(
                ReadinessReason(
                    code="no_paleomap_document",
                    message_zh="尚未创建古地理图文档",
                    severity="block",
                )
            )
        elif not any(
            (getattr(d, "linked_target_horizon", None) or "").strip() for d in docs
        ):
            reasons.append(
                ReadinessReason(
                    code="no_linked_target_horizon",
                    message_zh="古地理图未关联目标层位",
                    severity="block",
                )
            )

    if contract.id == "facies_prediction":
        # Can run mock with empty factors, but warn
        preds = getattr(project, "prediction_tasks", None) or []
        factors = getattr(project, "factor_map_tasks", None) or []
        if not factors and not preds:
            reasons.append(
                ReadinessReason(
                    code="prediction_demo_only",
                    message_zh="无单因素输入；仅可运行演示/mock 预测路径",
                    severity="warn",
                )
            )
        # If only mock adapters complete, partial
        if preds and all(getattr(t, "adapter_kind", "mock") == "mock" for t in preds):
            reasons.append(
                ReadinessReason(
                    code="mock_adapter",
                    message_zh="当前预测适配器为 mock（非生产模型）",
                    severity="warn",
                )
            )

    if contract.id == "quality_control":
        if not (getattr(project, "paleomap_documents", None) or []):
            reasons.append(
                ReadinessReason(
                    code="no_map",
                    message_zh="无可质检的古地理图文档",
                    severity="block",
                )
            )

    if contract.id == "export":
        has_anything = bool(
            getattr(project, "paleomap_documents", None)
            or getattr(project, "prediction_tasks", None)
            or getattr(project, "factor_map_tasks", None)
            or getattr(project, "export_artifacts", None)
        )
        if not has_anything:
            reasons.append(
                ReadinessReason(
                    code="nothing_to_export",
                    message_zh="无可导出的成果",
                    severity="block",
                )
            )

    if contract.id == "geomodel_3d":
        reasons.append(
            ReadinessReason(
                code="demo_modeling",
                message_zh="三维建模模块当前实现以演示/合成为主",
                severity="warn",
            )
        )

    blocks = [r for r in reasons if r.severity == "block"]
    warns = [r for r in reasons if r.severity == "warn"]
    if blocks:
        status = ReadinessStatus.BLOCKED
    elif warns:
        status = ReadinessStatus.PARTIAL
    elif contract.implementation_status is ImplementationStatus.PLACEHOLDER:
        status = ReadinessStatus.UNKNOWN
    else:
        status = ReadinessStatus.READY

    return ReadinessReport(
        contract_id=contract.id,
        status=status,
        reasons=reasons,
        implementation_status=contract.implementation_status,
    )


def evaluate_readiness(
    project: Any,
    contract_id: str,
    *,
    registry: WorkflowContractRegistry | None = None,
) -> ReadinessReport:
    reg = registry or get_default_registry()
    c = reg.get_contract(contract_id)
    if c is None:
        return ReadinessReport(
            contract_id=contract_id,
            status=ReadinessStatus.UNKNOWN,
            reasons=[
                ReadinessReason(
                    code="unknown_contract",
                    message_zh=f"未知模块合同：{contract_id}",
                    severity="block",
                )
            ],
        )
    return evaluate_contract_readiness(project, c)


class WorkflowReadinessEvaluator:
    def __init__(self, registry: WorkflowContractRegistry | None = None) -> None:
        self.registry = registry or get_default_registry()

    def evaluate(self, project: Any, contract_id: str) -> ReadinessReport:
        return evaluate_readiness(project, contract_id, registry=self.registry)

    def evaluate_all(self, project: Any) -> list[ReadinessReport]:
        return [
            evaluate_contract_readiness(project, c)
            for c in self.registry.list_contracts()
        ]
