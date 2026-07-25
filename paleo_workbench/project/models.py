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


class WellTableRow(BaseModel):
    """One well / sample row for single-factor preparation (spatial well table).

    Supports thickness/sand-ratio attributes and QC annotations used by MAD
    outlier detection and directional trend-surface weighting.
    """

    well_id: str = Field(default_factory=lambda: _id("well"))
    name: str = ""
    x: float
    y: float
    z: float | None = None
    H_s: float | None = None  # sand thickness
    H_t: float | None = None  # total thickness
    R_s: float | None = None  # sand ratio H_s/H_t when valid
    q: float = 1.0  # sample quality weight ∈ [0, 1+]
    b_i: float = 1.0  # barrier / usability weight ∈ [0, 1]
    qc_flag: Literal["ok", "outlier", "invalid_ratio", "missing"] = "ok"
    qc_z_star: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class WellTable(BaseModel):
    """Tabular well-point set shared by 制备 → 插值 → 编图 factor shelf."""

    id: str = Field(default_factory=lambda: _id("wtable"))
    name: str
    target_horizon: str = ""
    factor_type: str = ""
    rows: list[WellTableRow] = Field(default_factory=list)
    crs: str | None = None
    source_resource_ids: list[str] = Field(default_factory=list)
    linked_factor_task_id: str | None = None


class FactorMapTask(BaseModel):
    id: str = Field(default_factory=lambda: _id("factor"))
    name: str
    target_horizon: str
    factor_type: str
    input_resource_ids: list[str] = Field(default_factory=list)
    well_table_id: str | None = None
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


class MapReferenceLayer(BaseModel):
    """A GDAL-readable reference layer normalized to the project CRS."""

    id: str = Field(default_factory=lambda: _id("ref"))
    name: str
    source_path: str
    source_kind: Literal["raster", "vector"]
    source_crs: str
    project_crs: str
    transform_wkt: str = ""
    visible: bool = True
    opacity: float = Field(default=0.65, ge=0.0, le=1.0)
    order: int = 0
    participates_in_snap: bool = False
    cache_key: str = ""
    # True when source_path is outside the project directory (absolute on disk).
    external: bool = False
    status: Literal["ready", "offline", "failed"] = "ready"
    error_message: str = ""


class ConstraintLine(BaseModel):
    """A single geometric constraint used by trend-surface / IDW preparation.

    Roles:
      - ``break``: fault / barrier polyline (IDW ``fault_polylines``)
      - ``direction``: anisotropy axis (azimuth + optional a/b semi-axes)
      - ``boundary``: study-area outline (reserved)
      - ``other``: free-form guide line
    """

    id: str = Field(default_factory=lambda: _id("cline"))
    name: str = ""
    role: Literal["break", "direction", "boundary", "other"] = "other"
    # Open polyline: [[x, y], ...] (at least 2 vertices for break/direction).
    coordinates: list[list[float]] = Field(default_factory=list)
    azimuth_deg: float | None = None  # direction lines: major-axis bearing
    semi_major: float | None = None  # a — elongated along strike
    semi_minor: float | None = None  # b — across strike
    active: bool = True
    target_horizon: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ConstraintLayers(BaseModel):
    """Named set of break / direction / boundary lines for one horizon (or project-wide)."""

    id: str = Field(default_factory=lambda: _id("clayers"))
    name: str = "约束层"
    target_horizon: str = ""
    lines: list[ConstraintLine] = Field(default_factory=list)
    linked_factor_task_ids: list[str] = Field(default_factory=list)
    crs: str | None = None


class ContourSegment(BaseModel):
    """One isoline polyline at a fixed contour level."""

    id: str = Field(default_factory=lambda: _id("cseg"))
    level: float
    coordinates: list[list[float]] = Field(default_factory=list)  # [[x,y], ...]
    closed: bool = False
    properties: dict[str, Any] = Field(default_factory=dict)


class ContourDraft(BaseModel):
    """Editable contour draft generated from a FactorMapTask trend/grid surface.

    Lifecycle: 制备 grid_z → ContourDraft (初稿) → 编图 line_features 修编 → 定稿.
    """

    id: str = Field(default_factory=lambda: _id("cdraft"))
    name: str
    target_horizon: str = ""
    factor_type: str = ""
    linked_factor_task_id: str | None = None
    linked_map_document_id: str | None = None
    levels: list[float] = Field(default_factory=list)
    segments: list[ContourSegment] = Field(default_factory=list)
    # Snapshot of source grid metadata (not full grid_z to keep .paleo.json lean).
    source_grid_n: int | None = None
    source_backend: str | None = None
    source_value_range: list[float] = Field(default_factory=list)  # [min, max]
    status: Literal["draft", "editing", "final"] = "draft"
    generator_version: str = "contour-draft-v1"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class PaleoMapDocument(BaseModel):
    id: str = Field(default_factory=lambda: _id("map"))
    name: str
    linked_target_horizon: str
    linked_prediction_task_id: str | None = None
    linked_contour_draft_id: str | None = None
    facies_polygons: list[dict[str, Any]] = Field(default_factory=list)
    facies_style: dict[str, Any] = Field(default_factory=dict)
    well_overlays: list[dict[str, Any]] = Field(default_factory=list)
    line_features: list[dict[str, Any]] = Field(default_factory=list)
    label_features: list[dict[str, Any]] = Field(default_factory=list)
    reference_layers: list[MapReferenceLayer] = Field(default_factory=list)
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


class VersionSnapshot(BaseModel):
    """Point-in-time expert-approved state of a map (and optional contour draft)."""

    id: str = Field(default_factory=lambda: _id("vsnap"))
    map_document_id: str
    contour_draft_id: str | None = None
    quality_report_id: str | None = None
    factor_task_ids: list[str] = Field(default_factory=list)
    map_name: str = ""
    target_horizon: str = ""
    line_feature_count: int = 0
    facies_count: int = 0
    contour_segment_count: int = 0
    qc_status: str = ""
    note: str = ""
    # Compact geometry fingerprint for audit (not full payload).
    content_fingerprint: str = ""
    created_at: str = Field(default_factory=_now_iso)
    created_by: str = ""


class VersionSet(BaseModel):
    """Version lineage for expert finalization of maps under a horizon / theme."""

    id: str = Field(default_factory=lambda: _id("vset"))
    name: str
    target_horizon: str = ""
    status: Literal["open", "final", "superseded"] = "open"
    snapshots: list[VersionSnapshot] = Field(default_factory=list)
    active_snapshot_id: str | None = None
    finalized_by: str = ""
    finalized_at: str | None = None
    linked_compilation_run_id: str | None = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class ExportArtifact(BaseModel):
    id: str = Field(default_factory=lambda: _id("artifact"))
    linked_id: str
    format: str
    output_path: str
    options: dict[str, Any] = Field(default_factory=dict)
    included_map_elements: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)
    source_task_ids: list[str] = Field(default_factory=list)


class JointAnalysisState(BaseModel):
    """Persisted joint presentation on Geological Modeling 3D (PRD #85 / #90).

    Paths are optional hints; hybrid resolve still prefers project.resources.
    Never stores preview voxels.
    """

    tree_checks: dict[str, bool] = Field(default_factory=dict)
    vertical_domain: str = "Time"
    active_fence_wells: list[str] = Field(default_factory=list)
    active_fence_name: str | None = None
    # Optional absolute/relative path hints (segy, well_head, …)
    path_hints: dict[str, str] = Field(default_factory=dict)


class ProjectDocument(BaseModel):
    meta: ProjectMeta
    coordinate: CoordinateReference = Field(default_factory=CoordinateReference)
    stratigraphy: StratigraphicFramework = Field(default_factory=StratigraphicFramework)
    resources: list[ResourceItem] = Field(default_factory=list)
    well_tables: list[WellTable] = Field(default_factory=list)
    constraint_layers: list[ConstraintLayers] = Field(default_factory=list)
    contour_drafts: list[ContourDraft] = Field(default_factory=list)
    compilation_runs: list[CompilationRun] = Field(default_factory=list)
    factor_map_tasks: list[FactorMapTask] = Field(default_factory=list)
    prediction_tasks: list[PredictionTask] = Field(default_factory=list)
    paleomap_documents: list[PaleoMapDocument] = Field(default_factory=list)
    quality_reports: list[QualityReport] = Field(default_factory=list)
    version_sets: list[VersionSet] = Field(default_factory=list)
    export_artifacts: list[ExportArtifact] = Field(default_factory=list)
    joint_analysis: JointAnalysisState = Field(default_factory=JointAnalysisState)

    @classmethod
    def new(cls, name: str, region: str = "") -> "ProjectDocument":
        return cls(meta=ProjectMeta(name=name, region=region))
