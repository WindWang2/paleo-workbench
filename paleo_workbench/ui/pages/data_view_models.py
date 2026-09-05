"""Data View Models & Presentation Adapter (Seam for UI 2.0).

Provides presentation DTOs (AssetView, VersionView, TagView, LineageView) and
adapter functions that wrap legacy ResourceItem / ExportArtifact objects today
and seamlessly connect to future DataCatalogCore DataAsset objects.
"""
from __future__ import annotations

import os
import stat as stat_module
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
from paleo_workbench.catalog import DataStage, normalize_tag_name  # noqa: F401
from paleo_workbench.catalog.governance import governance_values

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
    # Version-level tags (catalog version_tags); empty for un-enriched views.
    tags: list[str] = field(default_factory=list)

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
    # Governance metadata (asset-level, controlled vocabulary subset).
    governance: dict[str, str] = field(default_factory=dict)
    # Compact lineage verdict for the table column ("" = no catalog lineage).
    lineage_status: str = ""
    # Full catalog asset metadata (display-only; governance keys shown apart).
    catalog_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.normalized_tags and self.tags:
            self.normalized_tags = {
                normalize_tag_name(t) for t in self.tags if t and str(t).strip()
            }

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
    "geojson": "GeoJSON矢量",
    # Catalog-produced scientific products (catalog-only rows; keys follow
    # the ``kind`` values business modules register).
    "factor_map": "因子图",
    "factor_map_grid": "因子图",
    "prediction": "预测",
    "prediction_result": "预测",
    "paleomap": "古地图",
    "interpretation": "解释",
    "horizon_interpretation": "解释",
    "correlation": "地层对比",
    "stratigraphic_correlation": "地层对比",
    "fault_interpretation": "断层解释",
    "qc": "质检",
    "qc_report": "质检",
    "export": "成果",
    "modeling": "三维建模",
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


def path_exists_safe(path_obj: Path) -> bool:
    """Public alias of :func:`_path_exists` for sibling UI modules (#891)."""
    return _path_exists(path_obj)


def path_is_dir_safe(path_obj: Path) -> bool:
    """``Path.is_dir()`` that treats an unprobeable path as "not a dir"."""
    try:
        return path_obj.is_dir()
    except OSError:
        return False


class FsProbeCache:
    """Per-refresh filesystem probe cache (#917 CI data-page stress).

    One ``os.stat`` per distinct path (the legacy path paid ``exists`` +
    ``is_file`` + ``stat`` per asset per refresh), shared results for repeated
    paths, and missing-directory pruning: once a directory is known absent,
    every probe beneath it short-circuits without a syscall. A dead prefix
    (unmounted NAS root, gone import root) costs O(1) probes per refresh
    instead of O(assets) — the CI superlinear blowup was stat pressure under
    exactly this shape.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, os.StatResult | None] = {}
        self._dirs: dict[str, bool] = {}

    def probe(self, path: Path) -> os.StatResult | None:
        key = str(path)
        if key in self._nodes:
            return self._nodes[key]
        result: os.StatResult | None = None
        if self._dir_exists(path.parent):
            try:
                result = os.stat(path)
            except OSError:
                result = None
        self._nodes[key] = result
        return result

    def _dir_exists(self, directory: Path) -> bool:
        key = str(directory)
        if key in self._dirs:
            return self._dirs[key]
        if directory == directory.parent:
            exists = True
        elif not self._dir_exists(directory.parent):
            exists = False
        else:
            node = self.probe(directory)
            exists = node is not None and stat_module.S_ISDIR(node.st_mode)
        self._dirs[key] = exists
        return exists


def _path_exists(path_obj: Path) -> bool:
    """``Path.exists()`` that treats an unprobeable path as absent, not an error.

    ``pathlib`` only suppresses a small set of "not found" errnos (ENOENT,
    ENOTDIR, EBADF, ELOOP), so an over-long path raises ``OSError``
    (ENAMETOOLONG, errno 36 on Linux). That escaped the view builder and aborted
    the entire data-page refresh because of one bad row (#882). Such a path is
    reachable from persisted data — an external link, a long relative path joined
    onto a long project root, or a project file written where limits differ; the
    255-byte per-component limit is only ~86 CJK characters in UTF-8.

    Reporting it as missing is the policy the adjacent ``stat()`` call already
    applied to the very same exception type on the very same path.
    """
    try:
        return path_obj.exists()
    except OSError:
        return False


def asset_view_from_resource(
    resource: ResourceItem,
    project_root: Path | None = None,
    fs_probe: "FsProbeCache | None" = None,
) -> AssetView:
    stage = _infer_stage(resource.artifact_role, resource.type)

    # Check file existence & integrity. With a per-refresh FsProbeCache this
    # is ONE stat per distinct path (missing directories prune whole
    # subtrees); the legacy path paid exists + is_file + stat per asset.
    path_obj = Path(resource.path)
    if not path_obj.is_absolute() and project_root is not None:
        path_obj = project_root / path_obj

    stat_result = None
    file_exists = False
    if fs_probe is not None:
        node = fs_probe.probe(path_obj)
        if node is not None:
            file_exists = True
            if stat_module.S_ISREG(node.st_mode):
                stat_result = node
    else:
        file_exists = _path_exists(path_obj)
        if file_exists and path_obj.is_file():
            try:
                stat_result = path_obj.stat()
            except OSError:
                stat_result = None
    if not file_exists or resource.status == "missing":
        integrity = IntegrityState.MISSING
    elif resource.external:
        integrity = IntegrityState.UNMANAGED
    elif resource.checksum:
        integrity = IntegrityState.VERIFIED
    else:
        integrity = IntegrityState.UNKNOWN

    size_bytes = resource.parsed_summary.get("size_bytes")
    if size_bytes is None and stat_result is not None:
        size_bytes = stat_result.st_size

    modified_at = "—"
    if stat_result is not None:
        from datetime import datetime
        modified_at = datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M")

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


def asset_view_from_artifact(
    artifact: ExportArtifact,
    project_root: Path | None = None,
    fs_probe: "FsProbeCache | None" = None,
) -> AssetView:
    name = Path(artifact.output_path).name or artifact.output_path
    path_obj = Path(artifact.output_path)
    if not path_obj.is_absolute() and project_root is not None:
        path_obj = project_root / path_obj

    # #1171: one probe answers exists + is-file + size (the legacy path paid
    # exists + is_file + stat — three syscalls — per artifact per refresh).
    stat_result = None
    file_exists = False
    if fs_probe is not None:
        node = fs_probe.probe(path_obj)
        file_exists = node is not None
        if node is not None and stat_module.S_ISREG(node.st_mode):
            stat_result = node
    else:
        file_exists = _path_exists(path_obj)
        if file_exists and path_obj.is_file():
            try:
                stat_result = path_obj.stat()
            except OSError:
                stat_result = None
    if not file_exists:
        integrity = IntegrityState.MISSING
    else:
        # An ExportArtifact carries no recorded checksum bytes; claiming
        # "已校验" on mere file existence was never a true statement.  The
        # explicit IntegrityWorker flow can verify it; until then the honest
        # posture is UNKNOWN ("未校验") (#850-4).
        integrity = IntegrityState.UNKNOWN

    size_bytes = stat_result.st_size if stat_result is not None else None

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


def asset_view_from_object(
    asset: Any,
    project_root: Path | None = None,
    fs_probe: "FsProbeCache | None" = None,
) -> AssetView:
    if isinstance(asset, AssetView):
        return asset
    if isinstance(asset, ResourceItem):
        return asset_view_from_resource(asset, project_root=project_root, fs_probe=fs_probe)
    if isinstance(asset, ExportArtifact):
        return asset_view_from_artifact(
            artifact=asset, project_root=project_root, fs_probe=fs_probe
        )

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


def _integrity_from_version(
    service: Any,
    version: Any,
    fs_probe: "FsProbeCache | None" = None,
) -> IntegrityState:
    """Map the catalog's recorded integrity posture for *version* to the UI
    enum WITHOUT re-hashing the payload on the UI thread.

    A full SHA-256 re-verification is O(payload size) and stalls the UI for
    every row selection on GB-scale files; that job belongs to the explicit
    threaded IntegrityWorker (data_lifecycle_controller). Here we report the
    cheap, non-blocking facts: trashed → UNKNOWN, unmanaged → UNMANAGED,
    managed payload present → VERIFIED (recorded checksum exists), managed
    payload missing → MISSING. A byte-level tamper verdict is delivered by
    the worker flow (review finding I6).

    ``fs_probe`` (#1171): when given, payload presence is answered by the
    shared per-refresh FsProbeCache (one stat per distinct path) instead of
    a fresh ``Path.is_file`` syscall per call, and results stay consistent
    within one materialization refresh."""
    try:
        if version.trashed:
            return IntegrityState.UNKNOWN
        if not version.managed:
            return IntegrityState.UNMANAGED
        payload = service.resolve_path(version)
        if fs_probe is not None:
            node = fs_probe.probe(payload)
            present = node is not None and stat_module.S_ISREG(node.st_mode)
        else:
            present = payload.is_file()
        if not present:
            return IntegrityState.MISSING
        if version.sha256:
            return IntegrityState.VERIFIED
        return IntegrityState.UNKNOWN
    except Exception:
        return IntegrityState.UNKNOWN


# Module-level tag-map cache (#1173): ``enrich_view_from_catalog`` used to
# rebuild tag_by_id + version_tag_map (O(tags + associations)) on EVERY call,
# and the data page calls it per row selection. Keyed on document identity +
# catalog revision + the service's mutation serial (public
# ``DataCatalogService.mutation_serial``), so any catalog write (including
# mutations deferred inside batch_save, where the revision is held until
# commit) invalidates it. The cache holds the document reference alive,
# keeping ``id()`` stable.
_CATALOG_TAG_MAPS_CACHE: tuple[Any, int, int, dict, dict[str, list[str]]] | None = None


def _catalog_tag_maps(service: Any) -> tuple[dict, dict[str, list[str]]]:
    """``(tag_by_id, version_tag_map)`` cached per catalog state (#1173)."""
    global _CATALOG_TAG_MAPS_CACHE
    document = service.document
    revision = document.catalog_revision
    serial = getattr(service, "mutation_serial", 0)
    cache = _CATALOG_TAG_MAPS_CACHE
    if (
        cache is not None
        and cache[0] is document
        and cache[1] == revision
        and cache[2] == serial
    ):
        return cache[3], cache[4]
    tag_by_id = {t.id: t for t in document.tags}
    version_tag_map: dict[str, list[str]] = {}
    try:
        for vid, tids in document.version_tags.items():
            version_tag_map[vid] = [
                tag_by_id[tid].display_name or tag_by_id[tid].name
                for tid in tids
                if tid in tag_by_id
            ]
    except Exception:
        version_tag_map = {}
    _CATALOG_TAG_MAPS_CACHE = (document, revision, serial, tag_by_id, version_tag_map)
    return tag_by_id, version_tag_map


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

    # --- governance / catalog metadata ------------------------------------
    try:
        view.governance = governance_values(asset.metadata)
        view.catalog_metadata = dict(asset.metadata or {})
    except Exception:
        pass

    # --- versions ---------------------------------------------------------
    try:
        versions = service.list_versions(asset_id)
    except Exception:
        versions = []
    # Version-level tags come from the catalog association map
    # (document.version_tags: version_id -> [tag_id]) — served from the
    # revision-keyed module cache instead of a per-call rebuild (#1173).
    tag_by_id, version_tag_map = _catalog_tag_maps(service)
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
                tags=list(version_tag_map.get(v.id, [])),
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
    # reports UNKNOWN (its payload moved out of its stage location). One
    # FsProbeCache covers every version of this enrichment pass (#1171).
    if current_version is not None:
        fs_probe = FsProbeCache()
        view.integrity_state = _integrity_from_version(
            service, current_version, fs_probe
        )

    # --- tags -------------------------------------------------------------
    try:
        tag_ids = service.document.asset_tags.get(asset_id, [])
        by_id = tag_by_id or {t.id: t for t in service.document.tags}
        catalog_tags = [
            by_id[tid].display_name or by_id[tid].name
            for tid in tag_ids
            if tid in by_id
        ]
    except Exception:
        catalog_tags = []
    if catalog_tags:
        view.tags = catalog_tags
        view.normalized_tags = {
            normalize_tag_name(t) for t in catalog_tags if t and str(t).strip()
        }

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


# ---------------------------------------------------------------------------
# Catalog row overview: one-pass batch enrichment for the asset table
# ---------------------------------------------------------------------------


@dataclass
class CatalogRowOverview:
    """Precomputed per-asset catalog facts for table rows (one pass per
    refresh — the table asks for every asset, so per-row catalog queries are
    the thing this exists to avoid at 1000+ assets)."""

    asset_id: str
    legacy_resource_id: str | None = None
    stage: DataStage = DataStage.RAW
    version_count: int = 0
    current_version_number: int | None = None
    current_version_id: str | None = None
    tags: list[str] = field(default_factory=list)
    governance: dict[str, str] = field(default_factory=dict)
    integrity_state: IntegrityState = IntegrityState.UNKNOWN
    lineage_status: str = ""
    checksum: str | None = None
    path: str = ""
    # Absolute runtime path from the catalog (pure path math — managed
    # versions resolve against the project dir); used for preview/open-folder
    # so catalog-only rows never resolve against the process CWD.
    resolved_path: str = ""
    size_bytes: int | None = None
    created_at: str = ""
    managed: bool = True
    trashed: bool = False
    asset: Any = None  # the catalog DataAsset


def _lineage_status_text(summary: dict[str, Any] | None, stage: DataStage) -> str:
    if not summary:
        return ""
    broken = " ⚠断链" if summary.get("broken") else ""
    if stage == DataStage.RAW or summary.get("to_raw") == 0:
        return f"源头{broken}".strip()
    to_raw = summary.get("to_raw")
    if to_raw is not None:
        return f"{to_raw} 级至源头{broken}".strip()
    if summary.get("has_parents"):
        return f"未接源头{broken}".strip()
    return f"无血缘记录{broken}".strip()


def catalog_row_overview(service: Any) -> dict[str, CatalogRowOverview]:
    """Build per-asset catalog facts in one locked pass (plus lineage
    summaries, cached per catalog revision inside the service).

    #1171: the whole overview is cached per (document, revision) — refresh
    triggers with no intervening save reuse it instead of re-resolving
    every asset's path and re-probing the filesystem.
    """
    document = service.document
    cache = getattr(service, "_view_overview_cache", None)
    if (
        cache is not None
        and cache[0] is document
        and cache[1] == document.catalog_revision
    ):
        return cache[2]
    overviews: dict[str, CatalogRowOverview] = {}
    try:
        assets = service.list_assets(include_trashed=True)
        summaries = service.lineage_summaries()
        tag_by_id = {t.id: t for t in service.document.tags}
        # One probe cache for the whole pass (#1171): per-asset integrity
        # checks share stats (one per distinct payload path) and stay
        # consistent within this materialization refresh.
        fs_probe = FsProbeCache()
        versions_by_asset: dict[str, list[Any]] = {}
        for version in service.document.versions:
            versions_by_asset.setdefault(version.asset_id, []).append(version)
        for asset in assets:
            versions = versions_by_asset.get(asset.id, [])
            current = next(
                (v for v in versions if v.id == asset.current_version_id), None
            )
            if current is None and versions:
                current = versions[-1]
            overview = CatalogRowOverview(
                asset_id=asset.id,
                legacy_resource_id=asset.legacy_resource_id,
                stage=current.stage if current is not None else DataStage.RAW,
                version_count=len(versions),
                current_version_number=(
                    current.version_number if current is not None else None
                ),
                current_version_id=current.id if current is not None else None,
                governance=governance_values(asset.metadata),
                lineage_status=(
                    _lineage_status_text(
                        summaries.get(current.id), current.stage
                    )
                    if current is not None
                    else ""
                ),
                checksum=current.sha256 if current is not None else None,
                path=current.path if current is not None else "",
                resolved_path=(
                    str(service.resolve_path(current))
                    if current is not None
                    else ""
                ),
                size_bytes=current.size_bytes if current is not None else None,
                created_at=(current.created_at if current is not None else "") or "",
                managed=bool(current.managed) if current is not None else True,
                trashed=asset.trashed,
                asset=asset,
            )
            if current is not None:
                overview.integrity_state = _integrity_from_version(
                    service, current, fs_probe
                )
            try:
                tag_ids = service.document.asset_tags.get(asset.id, [])
                overview.tags = [
                    tag_by_id[tid].display_name or tag_by_id[tid].name
                    for tid in tag_ids
                    if tid in tag_by_id
                ]
            except Exception:
                overview.tags = []
            overviews[asset.id] = overview
    except Exception:
        return {}
    service._view_overview_cache = (document, document.catalog_revision, overviews)
    return overviews


def apply_catalog_overview(view: AssetView, overview: CatalogRowOverview) -> AssetView:
    """Overlay catalog facts onto a legacy-built row view (in place)."""
    view.stage = overview.stage
    if overview.current_version_number is not None:
        view.current_version = f"v{overview.current_version_number}"
        if overview.version_count > 1:
            view.current_version = (
                f"v{overview.current_version_number} ({overview.version_count})"
            )
    view.integrity_state = overview.integrity_state
    view.lineage_status = overview.lineage_status
    view.governance = dict(overview.governance)
    try:
        view.catalog_metadata = dict((overview.asset.metadata or {}))
    except Exception:
        view.catalog_metadata = {}
    view.trashed = overview.trashed
    view.managed = overview.managed
    if overview.tags:
        view.tags = list(overview.tags)
        view.normalized_tags = {
            normalize_tag_name(t) for t in overview.tags if t and str(t).strip()
        }
    if overview.checksum:
        view.checksum = overview.checksum
    return view


def make_catalog_enricher(service: Any) -> Any:
    """Build a ``view -> view`` enricher resolved from the CURRENT catalog
    state (one overview pass now; O(1) dict lookups per row afterwards).

    Row resolution covers all three bridging shapes: migrated assets
    (asset id == resource id), production imports (asset linked via
    ``legacy_resource_id``), and ExportArtifacts (via their registered
    ``catalog_version_id``).
    """
    overviews = catalog_row_overview(service)
    version_to_asset: dict[str, str] = {}
    legacy_to_asset: dict[str, str] = {}
    for overview in overviews.values():
        if overview.current_version_id:
            version_to_asset[overview.current_version_id] = overview.asset_id
        if overview.legacy_resource_id:
            legacy_to_asset.setdefault(overview.legacy_resource_id, overview.asset_id)

    def resolve(view: AssetView) -> CatalogRowOverview | None:
        raw = view.raw_asset
        raw_id = getattr(raw, "id", None)
        if raw_id is not None and raw_id in overviews:
            return overviews[raw_id]
        # Production imports bridge resource id -> asset via legacy_resource_id.
        if raw_id is not None and raw_id in legacy_to_asset:
            return overviews.get(legacy_to_asset[raw_id])
        if isinstance(raw, ExportArtifact):
            version_id = getattr(raw, "catalog_version_id", None)
            asset_id = version_to_asset.get(version_id) if version_id else None
            if asset_id is not None:
                return overviews.get(asset_id)
        return None

    def enrich(view: AssetView) -> AssetView:
        try:
            overview = resolve(view)
            if overview is not None:
                return apply_catalog_overview(view, overview)
        except Exception:
            pass
        return view

    # Shared so catalog_only_rows reuses the same pass (no second walk).
    enrich.overview_map = overviews
    enrich.version_to_asset = version_to_asset
    return enrich


def asset_view_from_catalog_overview(
    overview: CatalogRowOverview,
    project_root: Path | None = None,
) -> AssetView:
    """Build a row view for a catalog-only asset (no legacy companion)."""
    asset = overview.asset
    name = getattr(asset, "name", overview.asset_id)
    fmt = ""
    try:
        fmt = str((getattr(asset, "metadata", None) or {}).get("format", "") or "")
    except Exception:
        fmt = ""
    path = overview.path
    if overview.resolved_path:
        path = overview.resolved_path
    elif project_root is not None and path and not Path(path).is_absolute():
        path = str(Path(project_root) / path)
    modified = overview.created_at or "—"
    stage = overview.stage
    version_label = f"v{overview.current_version_number}" if overview.current_version_number else "—"
    default_version = VersionView(
        version_id=overview.current_version_id or "—",
        is_current=True,
        stage=stage,
        created_at=overview.created_at or "—",
        checksum=overview.checksum,
        checksum_state=overview.integrity_state,
        managed=overview.managed,
        source_note="catalog",
    )
    return AssetView(
        id=overview.asset_id,
        name=name,
        type=getattr(asset, "type", "unknown"),
        type_label=RESOURCE_TYPE_DISPLAY_LABELS.get(
            getattr(asset, "type", "unknown"), getattr(asset, "type", "未知")
        ),
        format=fmt,
        stage=stage,
        current_version=version_label,
        versions=[default_version],
        tags=list(overview.tags),
        managed=overview.managed,
        integrity_state=overview.integrity_state,
        checksum=overview.checksum,
        path=path,
        size_bytes=overview.size_bytes,
        size_formatted=format_size(overview.size_bytes),
        created_at=overview.created_at or "—",
        modified_at=modified,
        source=(getattr(asset, "metadata", None) or {}).get("source", "catalog"),
        lineage=LineageView(),
        governance=dict(overview.governance),
        lineage_status=overview.lineage_status,
        catalog_metadata=dict((getattr(asset, "metadata", None) or {})),
        status="catalog",
        trashed=overview.trashed,
        raw_asset=asset,
    )
