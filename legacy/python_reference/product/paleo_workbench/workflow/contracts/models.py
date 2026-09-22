"""Typed professional workflow contract models (Stage 11).

Uses Pydantic to match ProjectDocument / catalog model style.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Certainty(str, Enum):
    KNOWN_FROM_CODE = "KNOWN_FROM_CODE"
    INFERRED = "INFERRED"
    EXPERT_CONFIRMATION_REQUIRED = "EXPERT_CONFIRMATION_REQUIRED"


class ImplementationStatus(str, Enum):
    PRODUCTION = "PRODUCTION"
    PARTIAL = "PARTIAL"
    DEMO = "DEMO"
    PLACEHOLDER = "PLACEHOLDER"


class InputCardinality(str, Enum):
    EXACTLY_ONE = "EXACTLY_ONE"
    ONE_OR_MORE = "ONE_OR_MORE"
    ZERO_OR_MORE = "ZERO_OR_MORE"
    ZERO_OR_ONE = "ZERO_OR_ONE"


class InputVersionSemantics(str, Enum):
    ANY_VERSION = "ANY_VERSION"
    CURRENT_VERSION = "CURRENT_VERSION"
    EXPLICIT_SELECTED_VERSION = "EXPLICIT_SELECTED_VERSION"
    RAW_ONLY = "RAW_ONLY"
    DERIVED_ALLOWED = "DERIVED_ALLOWED"


class InputRole(str, Enum):
    PRIMARY = "PRIMARY"
    CONSTRAINT = "CONSTRAINT"
    REFERENCE = "REFERENCE"
    CALIBRATION = "CALIBRATION"
    OPTIONAL_CONTEXT = "OPTIONAL_CONTEXT"


class ParameterCategory(str, Enum):
    SCIENTIFIC = "SCIENTIFIC"
    ALGORITHM = "ALGORITHM"
    DISPLAY = "DISPLAY"
    IO = "IO"


class QCSeverity(str, Enum):
    HARD_GATE = "HARD_GATE"
    WARNING = "WARNING"
    INFORMATION = "INFORMATION"


class ExpertQuestionCategory(str, Enum):
    INPUT = "INPUT"
    PARAMETER = "PARAMETER"
    OPERATION = "OPERATION"
    OUTPUT = "OUTPUT"
    QC = "QC"
    WORKFLOW = "WORKFLOW"
    GEOLOGICAL_RULE = "GEOLOGICAL_RULE"
    DATA_QUALITY = "DATA_QUALITY"
    VERSIONING = "VERSIONING"


class ExpertQuestionPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class ExpertQuestionStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ReadinessStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class WorkflowSourceEvidence(BaseModel):
    """Stable code reference (prefer module.symbol, not line numbers)."""

    path: str
    symbol: str = ""
    description: str = ""


class WorkflowInputSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    resource_types: list[str] = Field(default_factory=list)
    asset_kinds: list[str] = Field(default_factory=list)
    accepted_formats: list[str] = Field(default_factory=list)
    stage_requirement: str = ""  # raw / derived / intermediate / output / any
    cardinality: InputCardinality = InputCardinality.ZERO_OR_MORE
    required: bool = False
    current_version_required: bool = False
    version_semantics: InputVersionSemantics = InputVersionSemantics.ANY_VERSION
    role: InputRole = InputRole.PRIMARY
    scientific_constraints: str = ""
    software_validation: str = ""
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)
    certainty: Certainty = Certainty.KNOWN_FROM_CODE
    expert_question_ids: list[str] = Field(default_factory=list)


class WorkflowParameterSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    value_type: str = "str"
    unit: str = ""
    default: Any = None
    range_hint: str = ""
    required: bool = False
    category: ParameterCategory = ParameterCategory.ALGORITHM
    certainty: Certainty = Certainty.KNOWN_FROM_CODE
    expert_question_id: str | None = None
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)


class WorkflowOperationStep(BaseModel):
    id: str
    name: str
    description: str = ""
    executor_ref: str = ""  # symbolic, not a callback
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    user_action: str = ""
    software_action: str = ""
    blocking_requirements: list[str] = Field(default_factory=list)
    datarun_operation: str = ""  # actual DataRun.operation when produced
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)
    certainty: Certainty = Certainty.KNOWN_FROM_CODE


class WorkflowOutputSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    asset_kind: str = ""
    format: str = ""
    data_stage: str = ""  # raw|derived|intermediate|output|none
    versioned: bool = False
    persistent: bool = False
    scientific_meaning: str = ""
    output_class: str = "scientific"  # scientific|intermediate|visualization|export
    downstream_usage: list[str] = Field(default_factory=list)
    qc_required: bool = False
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)
    certainty: Certainty = Certainty.KNOWN_FROM_CODE


class WorkflowQCSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    severity: QCSeverity = QCSeverity.WARNING
    check_type: str = ""
    implemented: bool = False
    implementation_ref: str = ""
    expert_confirmation_required: bool = False
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)
    certainty: Certainty = Certainty.KNOWN_FROM_CODE


class ExpertConsultationQuestion(BaseModel):
    id: str
    module_id: str
    category: ExpertQuestionCategory
    question: str
    current_software_behavior: str = ""
    why_it_matters: str = ""
    options_if_known: list[str] = Field(default_factory=list)
    impact_if_unresolved: str = ""
    priority: ExpertQuestionPriority = ExpertQuestionPriority.P1
    certainty: Certainty = Certainty.EXPERT_CONFIRMATION_REQUIRED
    status: ExpertQuestionStatus = ExpertQuestionStatus.OPEN
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)


class ReadinessReason(BaseModel):
    code: str
    message_zh: str
    severity: str = "block"  # block|warn|info
    input_id: str | None = None


class DomainWorkflowContract(BaseModel):
    """One professional geological module contract."""

    id: str
    name: str
    name_zh: str = ""
    category: str = ""
    description: str = ""
    description_zh: str = ""
    implementation_status: ImplementationStatus = ImplementationStatus.PARTIAL
    entry_points: list[str] = Field(default_factory=list)
    inputs: list[WorkflowInputSpec] = Field(default_factory=list)
    parameters: list[WorkflowParameterSpec] = Field(default_factory=list)
    operations: list[WorkflowOperationStep] = Field(default_factory=list)
    outputs: list[WorkflowOutputSpec] = Field(default_factory=list)
    qc_rules: list[WorkflowQCSpec] = Field(default_factory=list)
    # Potential (contract) workflow edges — not actual DataRun lineage
    upstream_contract_ids: list[str] = Field(default_factory=list)
    downstream_contract_ids: list[str] = Field(default_factory=list)
    # Map to Stage-9 / lifecycle operation ids
    datarun_operations: list[str] = Field(default_factory=list)
    workflow_step_types: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    expert_questions: list[ExpertConsultationQuestion] = Field(default_factory=list)
    source_evidence: list[WorkflowSourceEvidence] = Field(default_factory=list)

    def completeness(self) -> dict[str, bool]:
        """Software requirements completeness — not a scientific score."""
        open_q = [
            q
            for q in self.expert_questions
            if q.status is ExpertQuestionStatus.OPEN
        ]
        return {
            "input_contract_complete": bool(self.inputs),
            "operation_contract_complete": bool(self.operations),
            "output_contract_complete": bool(self.outputs),
            "qc_contract_complete": bool(self.qc_rules),
            "expert_questions_resolved": len(open_q) == 0,
            "has_open_expert_questions": len(open_q) > 0,
        }
