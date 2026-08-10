"""Data View Models & Presentation Adapter (Seam for UI 2.0).

Provides presentation DTOs (AssetView, VersionView, TagView, LineageView) and
adapter functions that wrap legacy ResourceItem / ExportArtifact objects today
and seamlessly connect to future DataCatalogCore DataAsset objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from typing import Any, Sequence

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.tokens import format_size

# The single authoritative lifecycle enum lives in the Data Catalog Core
# (ADR 0056, lowercase values "raw"/"derived"/"intermediate"/"output").
# Re-exported here so existing UI imports keep working.
from paleo_workbench.catalog import DataStage  # noqa: F401

# Presentation data for the Core DataStage — UI-only, keyed on the Core enum.
STAGE_LABELS = {
    DataStage.RAW: "原始输入",
    DataStage.DERIVED: "派生数据",
    DataStage.INTERMEDIATE: "中间结果",
    DataStage.OUTPUT: "输出成果",
}

STAGE_ICONS = {
    DataStage.RAW: "🔒",
    DataStage.DERIVED: "🌿",
    DataStage.INTERMEDIATE: "⚡",
    DataStage.OUTPUT: "📦",
}

STAGE_COLORS = {
    DataStage.RAW: tokens.PRIMARY,
    DataStage.DERIVED: tokens.SUCCESS,
    DataStage.INTERMEDIATE: "#E6A23C",  # Warm Amber
    DataStage.OUTPUT: "#409EFF",       # Bright Cyan-Blue
}


def stage_label(stage: DataStage) -> str:
    return STAGE_LABELS.get(stage, str(stage.value))


def stage_icon(stage: DataStage) -> str:
    return STAGE_ICONS.get(stage, "📄")


def stage_color(stage: DataStage) -> str:
    return STAGE_COLORS.get(stage, tokens.TEXT_SECONDARY)


class IntegrityState(str, Enum):
    VERIFIED = "VERIFIED"
    MODIFIED = "MODIFIED"
    MISSING = "MISSING"
    UNMANAGED = "UNMANAGED"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        labels = {
            IntegrityState.VERIFIED: "已校验",
            IntegrityState.MODIFIED: "已修改",
            IntegrityState.MISSING: "缺失",
            IntegrityState.UNMANAGED: "外部链接",
            IntegrityState.UNKNOWN: "未校验",
        }
        return labels.get(self, self.value)

    @property
    def icon_symbol(self) -> str:
        symbols = {
            IntegrityState.VERIFIED: "✅",
            IntegrityState.MODIFIED: "⚠️",
            IntegrityState.MISSING: "❌",
            IntegrityState.UNMANAGED: "🔗",
            IntegrityState.UNKNOWN: "❓",
        }
        return symbols.get(self, "❓")

    @property
    def color_token(self) -> str:
        colors = {
            IntegrityState.VERIFIED: tokens.SUCCESS,
            IntegrityState.MODIFIED: tokens.WARNING,
            IntegrityState.MISSING: tokens.ERROR_RED,
            IntegrityState.UNMANAGED: tokens.TEXT_SECONDARY,
            IntegrityState.UNKNOWN: tokens.TEXT_SECONDARY,
        }
        return colors.get(self, tokens.TEXT_SECONDARY)


@dataclass
class VersionView:
    version_id: str
    is_current: bool = True
    stage: DataStage = DataStage.RAW
    created_at: str = "—"
    checksum: str | None = None
    checksum_state: IntegrityState = IntegrityState.UNKNOWN
    parent_version_id: str | None = None
    managed: bool = True
    source_note: str = ""

    @property
    def checksum_display(self) -> str:
        if not self.checksum:
            return "—"
        if len(self.checksum) > 12:
            return f"{self.checksum[:8]}...{self.checksum[-4:]}"
        return self.checksum


@dataclass
class TagView:
    name: str
    count: int = 0
    category: str = "custom"


@dataclass
class LineageView:
    parent_ids: list[str] = field(default_factory=list)
    parent_names: list[str] = field(default_factory=list)
    run_id: str | None = None
    workflow_step: str | None = None
    child_ids: list[str] = field(default_factory=list)
    child_names: list[str] = field(default_factory=list)

    @property
    def has_lineage(self) -> bool:
        return bool(self.parent_ids or self.child_ids or self.run_id)


from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataAssetProtocol(Protocol):
    """Protocol defining the expected presentation interface for future DataCatalogCore entities."""
    name: str
    type: str
    format: str
    path: str


@dataclass
class AssetView:
    id: str
    name: str
    type: str
    type_label: str
    format: str
    stage: DataStage
    current_version: str
    versions: list[VersionView]
    tags: list[str]
    managed: bool
    integrity_state: IntegrityState
    checksum: str | None
    path: str
    size_bytes: int | None
    size_formatted: str
    created_at: str
    modified_at: str
    source: str
    lineage: LineageView
    crs: str | None = None
    status: str = "indexed"
    parsed_summary: dict[str, Any] = field(default_factory=dict)
    raw_asset: ResourceItem | ExportArtifact | Any = None
    normalized_tags: set[str] = field(default_factory=set)
    # Tombstone display: True when the bridged catalog asset is in the trash.
    trashed: bool = False
    trashed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.normalized_tags and self.tags:
            self.normalized_tags = {t.strip().lower() for t in self.tags if t}

    @property
    def is_raw(self) -> bool:
        return self.stage == DataStage.RAW

    @property
    def is_derived(self) -> bool:
        return self.stage == DataStage.DERIVED

    @property
    def is_output(self) -> bool:
        return self.stage == DataStage.OUTPUT

    @property
    def is_trashed(self) -> bool:
        return self.trashed

    @property
    def trashed_label(self) -> str:
        return "🗑 已移至回收站"

    @property
    def stage_label(self) -> str:
        return stage_label(self.stage)

    @property
    def integrity_label(self) -> str:
        return self.integrity_state.label

    @property
    def checksum_display(self) -> str:
        if not self.checksum:
            return "—"
        if len(self.checksum) > 12:
            return f"{self.checksum[:8]}...{self.checksum[-4:]}"
        return self.checksum

    @property
    def is_missing(self) -> bool:
        return self.integrity_state == IntegrityState.MISSING or self.status == "missing"


RESOURCE_TYPE_DISPLAY_LABELS = {
    "well_log": "测井",
    "seismic": "地震",
    "horizon": "层位",
    "well_stratification": "井分层",
    "time_depth": "时深",
    "tabular": "表格",
    "spreadsheet": "表格",
    "document": "文档",
    "image_reference": "影像",
    "reference_map": "参考图",
    "well_reference": "测井参考",
    "fault": "断层",
    "raster": "栅格",
    "vector": "矢量",
    "unknown": "其他",
}


def _infer_stage(role: str | None, rtype: str) -> DataStage:
    if role == "input":
        return DataStage.RAW
    elif role == "derived":
        return DataStage.DERIVED
    elif role == "intermediate":
        return DataStage.INTERMEDIATE
    elif role in ("export", "output"):
        return DataStage.OUTPUT

    # Default fallbacks based on type
    if rtype in ("document", "reference_map", "image_reference", "well_reference"):
        return DataStage.RAW
    return DataStage.RAW


def asset_view_from_resource(resource: ResourceItem, project_root: Path | None = None) -> AssetView:
    stage = _infer_stage(resource.artifact_role, resource.type)

    # Check file existence & integrity
    path_obj = Path(resource.path)
    if not path_obj.is_absolute() and project_root is not None:
        path_obj = project_root / path_obj

    file_exists = path_obj.exists()
    if not file_exists or resource.status == "missing":
        integrity = IntegrityState.MISSING
    elif resource.external:
        integrity = IntegrityState.UNMANAGED
    elif resource.checksum:
        integrity = IntegrityState.VERIFIED
    else:
        integrity = IntegrityState.UNKNOWN

    size_bytes = resource.parsed_summary.get("size_bytes")
    if size_bytes is None and file_exists and path_obj.is_file():
        try:
            size_bytes = path_obj.stat().st_size
        except OSError:
            size_bytes = None

    modified_at = "—"
    if file_exists and path_obj.is_file():
        try:
            mtime = path_obj.stat().st_mtime
            from datetime import datetime
            modified_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            pass

    type_label = RESOURCE_TYPE_DISPLAY_LABELS.get(resource.type, resource.type)

    default_version = VersionView(
        version_id="v1",
        is_current=True,
        stage=stage,
        created_at=modified_at,
        checksum=resource.checksum,
        checksum_state=integrity,
        managed=not resource.external,
        source_note="Legacy / v1-compatible",
    )

    tags = list(resource.tags or [])

    lineage = LineageView()

    return AssetView(
        id=resource.id,
        name=resource.name,
        type=resource.type,
        type_label=type_label,
        format=resource.format,
        stage=stage,
        current_version="v1",
        versions=[default_version],
        tags=tags,
        managed=not resource.external,
        integrity_state=integrity,
        checksum=resource.checksum,
        path=resource.path,
        size_bytes=size_bytes,
        size_formatted=format_size(size_bytes),
        created_at=modified_at,
        modified_at=modified_at,
        source=resource.source,
        lineage=lineage,
        crs=resource.crs,
        status=resource.status,
        parsed_summary=dict(resource.parsed_summary or {}),
        raw_asset=resource,
        trashed=bool((resource.parsed_summary or {}).get("catalog_trashed")),
        trashed_at=(resource.parsed_summary or {}).get("catalog_trashed_at"),
    )


def asset_view_from_artifact(artifact: ExportArtifact, project_root: Path | None = None) -> AssetView:
    name = Path(artifact.output_path).name or artifact.output_path
    path_obj = Path(artifact.output_path)
    if not path_obj.is_absolute() and project_root is not None:
        path_obj = project_root / path_obj

    file_exists = path_obj.exists()
    integrity = IntegrityState.VERIFIED if file_exists else IntegrityState.MISSING

    size_bytes = None
    if file_exists and path_obj.is_file():
        try:
            size_bytes = path_obj.stat().st_size
        except OSError:
            pass

    default_version = VersionView(
        version_id="v1",
        is_current=True,
        stage=DataStage.OUTPUT,
        created_at=artifact.generated_at or "—",
        checksum_state=integrity,
        managed=True,
        source_note="Exported Artifact",
    )

    lineage = LineageView(
        parent_ids=[artifact.linked_id] if artifact.linked_id else [],
        run_id=artifact.source_task_ids[0] if artifact.source_task_ids else None,
    )

    return AssetView(
        id=artifact.id,
        name=name,
        type="export",
        type_label="成果",
        format=artifact.format,
        stage=DataStage.OUTPUT,
        current_version="v1",
        versions=[default_version],
        tags=["成果"],
        managed=True,
        integrity_state=integrity,
        checksum=None,
        path=artifact.output_path,
        size_bytes=size_bytes,
        size_formatted=format_size(size_bytes),
        created_at=artifact.generated_at or "—",
        modified_at=artifact.generated_at or "—",
        source="export",
        lineage=lineage,
        crs=None,
        status="generated",
        parsed_summary={"included_map_elements": artifact.included_map_elements},
        raw_asset=artifact,
    )


def asset_view_from_object(asset: Any, project_root: Path | None = None) -> AssetView:
    if isinstance(asset, AssetView):
        return asset
    if isinstance(asset, ResourceItem):
        return asset_view_from_resource(asset, project_root=project_root)
    if isinstance(asset, ExportArtifact):
        return asset_view_from_artifact(artifact=asset, project_root=project_root)

    # Duck-typing fallback for generic asset objects
    name = getattr(asset, "name", str(asset))
    return AssetView(
        id=getattr(asset, "id", f"asset_{id(asset)}"),
        name=name,
        type=getattr(asset, "type", "unknown"),
        type_label=getattr(asset, "type_label", "未知"),
        format=getattr(asset, "format", "unknown"),
        stage=getattr(asset, "stage", DataStage.RAW),
        current_version=getattr(asset, "current_version", "v1"),
        versions=[
            VersionView(
                version_id="v1",
                is_current=True,
                stage=getattr(asset, "stage", DataStage.RAW),
            )
        ],
        tags=list(getattr(asset, "tags", [])),
        managed=bool(getattr(asset, "managed", True)),
        integrity_state=getattr(asset, "integrity_state", IntegrityState.UNKNOWN),
        checksum=getattr(asset, "checksum", None),
        path=str(getattr(asset, "path", "")),
        size_bytes=getattr(asset, "size_bytes", None),
        size_formatted=format_size(getattr(asset, "size_bytes", None)),
        created_at="—",
        modified_at="—",
        source="local",
        lineage=LineageView(),
        raw_asset=asset,
    )


def _integrity_from_version(service: Any, version: Any) -> IntegrityState:
    """Map the catalog's recorded integrity posture for *version* to the UI
    enum WITHOUT re-hashing the payload on the UI thread.

    A full SHA-256 re-verification is O(payload size) and stalls the UI for
    every row selection on GB-scale files; that job belongs to the explicit
    threaded IntegrityWorker (data_lifecycle_controller). Here we report the
    cheap, non-blocking facts: trashed → UNKNOWN, unmanaged → UNMANAGED,
    managed payload present → VERIFIED (recorded checksum exists), managed
    payload missing → MISSING. A byte-level tamper verdict is delivered by
    the worker flow (review finding I6)."""
    try:
        if version.trashed:
            return IntegrityState.UNKNOWN
        if not version.managed:
            return IntegrityState.UNMANAGED
        payload = service.resolve_path(version)
        if not payload.is_file():
            return IntegrityState.MISSING
        if version.sha256:
            return IntegrityState.VERIFIED
        return IntegrityState.UNKNOWN
    except Exception:
        return IntegrityState.UNKNOWN


def enrich_view_from_catalog(view: AssetView, service: Any, asset_id: str) -> AssetView:
    """Enrich a presentation ``AssetView`` with authoritative catalog data.

    ``service`` is the Core ``DataCatalogService``; ``asset_id`` is the catalog
    asset bridged to the legacy resource behind *view*. Enriches versions,
    tags, checksum, stage, and lineage in place and returns the same view.
    Any catalog failure leaves the (legacy) view untouched — presentation
    must never break because the catalog is unavailable.
    """
    try:
        asset = service.get_asset(asset_id)
    except Exception:
        return view

    # --- tombstone state ---------------------------------------------------
    view.trashed = bool(getattr(asset, "trashed", False))
    view.trashed_at = getattr(asset, "trashed_at", None)

    # --- versions ---------------------------------------------------------
    try:
        versions = service.list_versions(asset_id)
    except Exception:
        versions = []
    current_version = None
    if versions:
        view.versions = [
            VersionView(
                version_id=v.id,
                is_current=(v.id == asset.current_version_id),
                stage=v.stage,
                created_at=v.created_at or "—",
                checksum=v.sha256,
                parent_version_id=v.parent_version_ids[0] if v.parent_version_ids else None,
                managed=v.managed,
                source_note=f"catalog v{v.version_number}",
            )
            for v in versions
        ]
        if asset.current_version_id:
            view.current_version = asset.current_version_id
        current_version = next(
            (v for v in versions if v.id == asset.current_version_id), None
        )
        if current_version is not None:
            view.stage = current_version.stage
            if current_version.sha256:
                view.checksum = current_version.sha256

    # --- integrity ---------------------------------------------------------
    # The catalog is the lifecycle authority: report the CURRENT version's
    # recorded integrity instead of the legacy inference. A trashed version
    # reports UNKNOWN (its payload moved out of its stage location).
    if current_version is not None:
        view.integrity_state = _integrity_from_version(service, current_version)

    # --- tags -------------------------------------------------------------
    try:
        tag_ids = service.document.asset_tags.get(asset_id, [])
        by_id = {t.id: t for t in service.document.tags}
        catalog_tags = [
            by_id[tid].display_name or by_id[tid].name
            for tid in tag_ids
            if tid in by_id
        ]
    except Exception:
        catalog_tags = []
    if catalog_tags:
        view.tags = catalog_tags
        view.normalized_tags = {t.strip().lower() for t in catalog_tags if t}

    # --- lineage ----------------------------------------------------------
    if asset.current_version_id:
        try:
            lineage = service.get_lineage(asset.current_version_id)
        except Exception:
            lineage = None
        if lineage is not None:

            def _version_name(v: Any) -> str:
                try:
                    return service.get_asset(v.asset_id).name
                except Exception:
                    return v.id

            run = lineage.get("run")
            view.lineage = LineageView(
                parent_ids=[v.id for v in lineage.get("parents", [])],
                parent_names=[_version_name(v) for v in lineage.get("parents", [])],
                run_id=run.id if run is not None else None,
                workflow_step=run.operation if run is not None else None,
                child_ids=[v.id for v in lineage.get("children", [])],
                child_names=[_version_name(v) for v in lineage.get("children", [])],
            )

    return view
