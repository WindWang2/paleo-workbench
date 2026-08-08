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


class DataStage(str, Enum):
    RAW = "RAW"
    DERIVED = "DERIVED"
    INTERMEDIATE = "INTERMEDIATE"
    OUTPUT = "OUTPUT"

    @property
    def label(self) -> str:
        labels = {
            DataStage.RAW: "原始输入",
            DataStage.DERIVED: "派生数据",
            DataStage.INTERMEDIATE: "中间结果",
            DataStage.OUTPUT: "输出成果",
        }
        return labels.get(self, self.value)

    @property
    def icon_symbol(self) -> str:
        symbols = {
            DataStage.RAW: "🔒",
            DataStage.DERIVED: "🌿",
            DataStage.INTERMEDIATE: "⚡",
            DataStage.OUTPUT: "📦",
        }
        return symbols.get(self, "📄")

    @property
    def color_token(self) -> str:
        colors = {
            DataStage.RAW: tokens.PRIMARY,
            DataStage.DERIVED: tokens.SUCCESS,
            DataStage.INTERMEDIATE: "#E6A23C",  # Warm Amber
            DataStage.OUTPUT: "#409EFF",       # Bright Cyan-Blue
        }
        return colors.get(self, tokens.TEXT_SECONDARY)


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
    def stage_label(self) -> str:
        return self.stage.label

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
