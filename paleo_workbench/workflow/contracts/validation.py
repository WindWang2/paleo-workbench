"""Contract consistency checks (DataRun ops, edge refs) — not lineage rebuild."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from paleo_workbench.workflow.contracts.registry import WorkflowContractRegistry

# Known lifecycle / Stage-9 DataRun.operation strings (from catalog.lifecycle)
KNOWN_DATARUN_OPERATIONS = frozenset(
    {
        "factor_map",
        "prediction",
        "export",
        "horizon_interpretation",
        "map_compile",
        "qc",
        "modeling",
        "derived_copy",
        "delivery",
        "stratigraphic_correlation",
        "fault_interpretation",
    }
)

# Map contract ids to expected primary DataRun ops where applicable
CONTRACT_DATARUN_MAP = {
    "factor_interpolation": "factor_map",
    "facies_prediction": "prediction",
    "export": "export",
    "horizon_interpretation": "horizon_interpretation",
    "paleomap_compile": "map_compile",
    "quality_control": "qc",
    "geomodel_3d": "modeling",
    "well_correlation": "stratigraphic_correlation",
    "fault_interpretation": "fault_interpretation",
}


def validate_registry(registry: "WorkflowContractRegistry") -> list[str]:
    issues: list[str] = []
    ids = {c.id for c in registry.list_contracts()}
    by_id = {c.id: c for c in registry.list_contracts()}
    for c in registry.list_contracts():
        for up in c.upstream_contract_ids:
            if up not in ids:
                issues.append(f"{c.id}: unknown upstream {up}")
            elif c.id not in by_id[up].downstream_contract_ids:
                # Graph consistency (audit #848): downstream/upstream edges
                # must mirror each other; one-sided declarations hid real
                # consumption relationships from the readiness graph.
                issues.append(f"{up}->{c.id}: missing mirror downstream on {up}")
        for down in c.downstream_contract_ids:
            if down not in ids:
                issues.append(f"{c.id}: unknown downstream {down}")
            elif c.id not in by_id[down].upstream_contract_ids:
                issues.append(f"{c.id}->{down}: missing mirror upstream on {down}")
        for op in c.datarun_operations:
            if op and op not in KNOWN_DATARUN_OPERATIONS:
                issues.append(f"{c.id}: undeclared DataRun operation {op!r}")
        expected = CONTRACT_DATARUN_MAP.get(c.id)
        if expected and expected not in (c.datarun_operations or []):
            issues.append(
                f"{c.id}: missing expected DataRun operation {expected!r}"
            )
        # Expert questions for EXPERT_CONFIRMATION_REQUIRED parameters
        for p in c.parameters:
            if p.certainty.value == "EXPERT_CONFIRMATION_REQUIRED" and not p.expert_question_id:
                issues.append(f"{c.id}: parameter {p.id} needs expert_question_id")
        # Open questions should have non-empty question text
        for q in c.expert_questions:
            if not (q.question or "").strip():
                issues.append(f"{c.id}: empty expert question {q.id}")
            for e in q.source_evidence:
                if not e.path:
                    issues.append(f"{c.id}/{q.id}: evidence missing path")
    return issues
