"""Central workflow contract registry (Stage 11)."""

from __future__ import annotations

from paleo_workbench.workflow.contracts.models import DomainWorkflowContract
from paleo_workbench.workflow.contracts.modules import build_all_contracts
from paleo_workbench.workflow.contracts.validation import validate_registry


class WorkflowContractRegistry:
    """In-memory registry of professional module contracts.

    Not a lineage database. Potential edges live on contracts; actual
    scientific lineage remains Stage-9 DataRun / DependencyGraph.
    """

    def __init__(self, contracts: list[DomainWorkflowContract] | None = None) -> None:
        items = list(contracts if contracts is not None else build_all_contracts())
        self._by_id: dict[str, DomainWorkflowContract] = {}
        for c in items:
            if c.id in self._by_id:
                raise ValueError(f"duplicate contract id: {c.id}")
            self._by_id[c.id] = c
        self._issues = validate_registry(self)

    def list_contracts(self) -> list[DomainWorkflowContract]:
        return list(self._by_id.values())

    def get_contract(self, contract_id: str) -> DomainWorkflowContract | None:
        return self._by_id.get(contract_id)

    def contracts_by_category(self, category: str) -> list[DomainWorkflowContract]:
        return [c for c in self._by_id.values() if c.category == category]

    def upstream(self, contract_id: str) -> list[DomainWorkflowContract]:
        c = self._by_id.get(contract_id)
        if c is None:
            return []
        return [self._by_id[i] for i in c.upstream_contract_ids if i in self._by_id]

    def downstream(self, contract_id: str) -> list[DomainWorkflowContract]:
        c = self._by_id.get(contract_id)
        if c is None:
            return []
        return [self._by_id[i] for i in c.downstream_contract_ids if i in self._by_id]

    def all_expert_questions(self):
        out = []
        for c in self._by_id.values():
            out.extend(c.expert_questions)
        return out

    def validation_issues(self) -> list[str]:
        return list(self._issues)

    def p0_ids(self) -> list[str]:
        return [
            "data_import",
            "well_log_ingest",
            "well_log_visualization",
            "seismic_volume",
            "horizon_interpretation",
            "factor_interpolation",
            "facies_prediction",
            "paleomap_compile",
            "quality_control",
            "export",
        ]


_DEFAULT: WorkflowContractRegistry | None = None


def get_default_registry() -> WorkflowContractRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = WorkflowContractRegistry()
    return _DEFAULT


def reset_default_registry() -> None:
    global _DEFAULT
    _DEFAULT = None
