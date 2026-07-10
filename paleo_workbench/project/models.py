from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ProjectMeta(BaseModel):
    name: str
    region: str = ""
    version: str = "0.1.0"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    project_root: str = "."


class CoordinateReference(BaseModel):
    project_crs: str = "EPSG:4326 / WGS84"
    target_crs: str | None = None
    display_crs: str = "EPSG:4326 / WGS84"
    transform_history: list[dict[str, Any]] = Field(default_factory=list)


class StratigraphicFramework(BaseModel):
    target_horizon: str = ""
    sequence_boundaries: list[str] = Field(default_factory=list)
    systems_tract_scheme: str = "LST/TST/HST"
    interpretation_version: str = "v1"
    applicable_wells: list[str] = Field(default_factory=list)
    applicable_seismic_ranges: list[str] = Field(default_factory=list)


class ResourceItem(BaseModel):
    id: str = Field(default_factory=lambda: _id("res"))
    name: str
    path: str
    type: str
    format: str
    crs: str | None = None
    status: str = "indexed"
    tags: list[str] = Field(default_factory=list)
    source: str = "local"
    parsed_summary: dict[str, Any] = Field(default_factory=dict)
    checksum: str | None = None
    external: bool = False
    artifact_role: str | None = None


class WorkflowStep(BaseModel):
    id: str = Field(default_factory=lambda: _id("step"))
    step_type: Literal[
        "data_check",
        "factor_map",
        "prediction",
        "map_compile",
        "qc",
        "export",
    ]
    status: Literal[
        "pending",
        "ready",
        "running",
        "complete",
        "warning",
        "failed",
        "skipped",
        "mock",
    ] = "pending"
    required_input_resource_ids: list[str] = Field(default_factory=list)
    produced_ids: list[str] = Field(default_factory=list)
    blocking_issue_summary: str = ""
    provenance_summary: str = ""


class CompilationRun(BaseModel):
    id: str = Field(default_factory=lambda: _id("run"))
    name: str
    target_horizon: str
    sequence_scheme_ref: str = ""
    status: Literal[
        "draft",
        "running",
        "blocked",
        "review_required",
        "export_ready",
        "exported",
        "failed",
    ] = "draft"
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    active_factor_map_task_ids: list[str] = Field(default_factory=list)
    active_prediction_task_id: str | None = None
    active_paleomap_document_id: str | None = None
    active_quality_report_id: str | None = None
    export_artifact_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class FactorMapTask(BaseModel):
    id: str = Field(default_factory=lambda: _id("factor"))
    name: str
    target_horizon: str
    factor_type: str
    input_resource_ids: list[str] = Field(default_factory=list)
    method: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_resource_ids: list[str] = Field(default_factory=list)
    quality_metrics: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    source_kind: Literal["real", "imported", "mock", "mixed"] = "mock"
    input_snapshot_hash: str = ""
    generator_version: str | None = None
    seed: int | None = None


class PredictionTask(BaseModel):
    id: str = Field(default_factory=lambda: _id("pred"))
    name: str
    adapter_kind: Literal["mock", "http", "local"] = "mock"
    input_factor_map_ids: list[str] = Field(default_factory=list)
    input_refs: dict[str, list[str]] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    probability_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_contribution: list[dict[str, Any]] = Field(default_factory=list)
    review_areas: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    adapter_schema_version: str = "1.0"
    input_snapshot_hash: str = ""
    generator_version: str | None = None
    seed: int | None = None


class PaleoMapDocument(BaseModel):
    id: str = Field(default_factory=lambda: _id("map"))
    name: str
    linked_target_horizon: str
    linked_prediction_task_id: str | None = None
    facies_polygons: list[dict[str, Any]] = Field(default_factory=list)
    facies_style: dict[str, Any] = Field(default_factory=dict)
    well_overlays: list[dict[str, Any]] = Field(default_factory=list)
    line_features: list[dict[str, Any]] = Field(default_factory=list)
    label_features: list[dict[str, Any]] = Field(default_factory=list)
    map_chrome: dict[str, Any] = Field(default_factory=dict)
    view_state: dict[str, Any] = Field(default_factory=dict)
    edit_history: list[dict[str, Any]] = Field(default_factory=list)


class QualityReport(BaseModel):
    id: str = Field(default_factory=lambda: _id("qc"))
    linked_map_document_id: str
    rules: list[str] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    generated_at: str = Field(default_factory=_now_iso)


class ExportArtifact(BaseModel):
    id: str = Field(default_factory=lambda: _id("artifact"))
    linked_id: str
    format: str
    output_path: str
    options: dict[str, Any] = Field(default_factory=dict)
    included_map_elements: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)
    source_task_ids: list[str] = Field(default_factory=list)


class ProjectDocument(BaseModel):
    meta: ProjectMeta
    coordinate: CoordinateReference = Field(default_factory=CoordinateReference)
    stratigraphy: StratigraphicFramework = Field(default_factory=StratigraphicFramework)
    resources: list[ResourceItem] = Field(default_factory=list)
    compilation_runs: list[CompilationRun] = Field(default_factory=list)
    factor_map_tasks: list[FactorMapTask] = Field(default_factory=list)
    prediction_tasks: list[PredictionTask] = Field(default_factory=list)
    paleomap_documents: list[PaleoMapDocument] = Field(default_factory=list)
    quality_reports: list[QualityReport] = Field(default_factory=list)
    export_artifacts: list[ExportArtifact] = Field(default_factory=list)

    @classmethod
    def new(cls, name: str, region: str = "") -> "ProjectDocument":
        return cls(meta=ProjectMeta(name=name, region=region))
