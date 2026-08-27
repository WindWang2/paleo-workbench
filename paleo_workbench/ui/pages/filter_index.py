from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from paleo_workbench.catalog import normalize_tag_name
from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.asset_table_model import (
    RESOURCE_TYPE_LABELS,
    _match_positions_by_identity,
)
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    IntegrityState,
    asset_view_from_object,
    stage_label,
)

ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}
# Non-linked material shown by the Data Manager's “辅助资料” smart view.
# NavigationTree imports this canonical set so its count and the table filter
# cannot drift apart.
AUXILIARY_TYPES = {"document", "image_reference", "reference_map", "tabular"}

# Canonical category vocabulary mapping for backward compatibility.
CATEGORIES = {
    "全部": None,
    "测井": "well_log",
    "地震": "seismic",
    "层位": "horizon",
    "井分层": "well_stratification",
    "时深": "time_depth",
    "表格": "tabular",
    "文档": "document",
    "影像": "image_reference",
    "参考图": "reference_map",
    "测井参考": "well_reference",
    "GeoJSON矢量": "geojson",
    "矢量": "vector",
    "未知": "unknown",
}

_STATUS_LABELS = {
    "indexed": "已索引",
    "parsed": "已解析",
    "missing": "缺失",
    "warning": "警告",
    "failed": "失败",
    "error": "错误",
    "ready": "就绪",
    "generated": "已生成",
}


@dataclass
class FilterQuery:
    node_type: str = "all"
    # Vocabulary: "all", "stage", "type", "tag", "integrity", "review_status",
    # "trash", "legacy_category" — plus WorkArea-domain nodes:
    #   "entity"       → one Well/Survey (node_value = canonical entity id)
    #   "entity_group" → all entities of a kind (node_value = entity_type)
    node_value: str | None = None
    search_text: str = ""
    stage: str | None = None
    data_type: str | None = None
    tag: str | None = None
    integrity: str | None = None
    # Multi-tag secondary criteria: all listed tags combined with
    # ``tag_operator`` ("and" = asset must carry every tag, "or" = any).
    # The legacy singular ``tag`` field is unioned into ``tags`` at match time.
    tags: list[str] = field(default_factory=list)
    tag_operator: str = "and"
    # Governance filter: review_status vocabulary value (draft/pending_review/
    # approved/rejected).
    review_status: str | None = None
    # Entity-node membership set (catalog DataAsset ids ∪ legacy ResourceItem
    # ids).  Computed by DataPage at query time from EntityAssetLinks; None
    # disables entity matching so plain queries stay allocation-free.
    entity_asset_ids: frozenset[str] | None = None
    # Optional EntityAssetLink.role refinement for entity nodes (e.g. a well's
    # 测井/时深 sub-leaves).  None = every role of the entity.
    entity_role: str | None = None
    # Optional single-asset refinement for entity file leaves (a concrete
    # file under one well node).  Carries the catalog DataAsset id; DataPage
    # resolves the legacy ResourceItem id alongside.
    asset_id: str | None = None


@dataclass
class CatalogCounts:
    total: int = 0
    stages: dict[str, int] = field(default_factory=dict)
    types: dict[str, int] = field(default_factory=dict)
    tags: dict[str, int] = field(default_factory=dict)
    integrity: dict[str, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)
    review_status: dict[str, int] = field(default_factory=dict)


class FilterIndex:
    def __init__(self) -> None:
        self._assets: list[ResourceItem | ExportArtifact | Any] = []
        self._views: list[AssetView] = []
        self._haystacks: list[str] = []
        # View-reuse token (#1063): recycling is only valid while the
        # view-building inputs are unchanged.
        self._view_build_token: tuple | None = None

    def rebuild(
        self,
        assets: Sequence[ResourceItem | ExportArtifact | Any],
        project_root: Path | None = None,
        enricher: Any = None,
        views: Sequence[Any] | None = None,
    ) -> None:
        """(Re)build the index; identical asset objects keep their views.

        Every AssetView build probes the filesystem (exists/stat per
        resource), which dominated refresh time at 10万-scale. Rows arriving
        as the same object as the previous rebuild reuse their view AND
        search haystack; everything else rebuilds (#1063). Caller-provided
        views (#527) always win verbatim.
        """
        def _build(asset) -> AssetView:
            view = asset_view_from_object(asset, project_root=project_root)
            return enricher(view) if enricher is not None else view

        new_assets = list(assets)
        token = (project_root, enricher)
        if views is not None and len(views) == len(new_assets):
            # Shared prebuilt views (#527): every AssetView build probes the
            # filesystem (exists/stat per resource) — building them once per
            # refresh and threading them through the consumers removed the
            # per-pass multiplication.
            self._views = list(views)
            self._haystacks = [self._haystack(view) for view in self._views]
        elif token == self._view_build_token and self._assets:
            # Recycle views and haystacks together: the haystack is derived
            # from the view, so a recycled view keeps its haystack too.
            matches = _match_positions_by_identity(self._assets, new_assets)
            old_views = self._views
            old_haystacks = self._haystacks
            pairs = [
                (old_views[m], old_haystacks[m]) if m is not None else (None, None)
                for m in matches
            ]
            self._views = []
            self._haystacks = []
            for (view, haystack), asset in zip(pairs, new_assets):
                if view is None:
                    view = _build(asset)
                    haystack = self._haystack(view)
                self._views.append(view)
                self._haystacks.append(haystack)
        else:
            self._views = []
            self._haystacks = []
            for asset in new_assets:
                view = _build(asset)
                self._views.append(view)
                self._haystacks.append(self._haystack(view))
        self._assets = new_assets
        self._view_build_token = token

    @property
    def views(self) -> list:
        return list(self._views)

    def filter(self, category: str, search_text: str) -> list[int]:
        """Legacy filter interface (category string + search text)."""
        query = self._parse_legacy_category(category, search_text)
        return self.filter_query(query)

    def filter_query(self, query: FilterQuery) -> list[int]:
        needle = query.search_text.strip().lower()
        rows: list[int] = []

        for i, view in enumerate(self._views):
            if not self._matches_query(view, query):
                continue
            if needle and needle not in self._haystacks[i]:
                continue
            rows.append(i)
        return rows

    def _matches_query(self, view: AssetView, query: FilterQuery) -> bool:
        # Trashed (recoverable) items live in the 回收站 filter; every other
        # filter excludes them so the active view never mixes them in.
        if query.node_type == "trash":
            if not view.trashed:
                return False
        elif view.trashed:
            return False

        # 1. Primary tree node filter
        if query.node_type == "stage":
            if query.node_value and view.stage.value != query.node_value:
                return False
        elif query.node_type == "stage_any":
            stages = {
                value.strip()
                for value in (query.node_value or "").split(",")
                if value.strip()
            }
            if not stages or view.stage.value not in stages:
                return False
        elif query.node_type == "type":
            if query.node_value and view.type != query.node_value:
                # Handle special "other" or "reference" type groupings if needed
                if query.node_value == "other" and view.type in CATEGORIES.values():
                    return False
                elif query.node_value != "other" and view.type != query.node_value:
                    return False
        elif query.node_type == "auxiliary":
            if view.type not in AUXILIARY_TYPES:
                return False
        elif query.node_type == "tag":
            if query.node_value:
                normalized_target = normalize_tag_name(query.node_value)
                if normalized_target not in view.normalized_tags:
                    return False
        elif query.node_type == "integrity":
            if query.node_value and view.integrity_state.value != query.node_value:
                return False
        elif query.node_type == "review_status":
            if query.node_value:
                if view.governance.get("review_status") != query.node_value:
                    return False
        elif query.node_type == "legacy_category":
            if query.node_value and query.node_value != "全部":
                if isinstance(view.raw_asset, ExportArtifact):
                    return False
                target_type = CATEGORIES.get(query.node_value)
                if view.type != target_type:
                    return False
        elif query.node_type in ("entity", "entity_group"):
            if not query.entity_asset_ids:
                return False
            raw = view.raw_asset
            row_ids = {
                str(getattr(raw, "id", "") or ""),
                str(getattr(raw, "legacy_resource_id", "") or ""),
            }
            if not row_ids & set(query.entity_asset_ids):
                return False

        # 2. Multi-dimensional secondary criteria
        if query.stage and view.stage.value != query.stage:
            return False
        if query.data_type and view.type != query.data_type:
            return False
        tag_criteria = [t for t in (query.tags or []) if t and str(t).strip()]
        if query.tag:
            tag_criteria.append(query.tag)
        if tag_criteria:
            normalized_targets = {
                normalize_tag_name(t) for t in tag_criteria if str(t).strip()
            }
            if normalized_targets:
                if query.tag_operator == "or":
                    if not normalized_targets & view.normalized_tags:
                        return False
                else:  # "and" (default): the asset must carry every tag.
                    if not normalized_targets <= view.normalized_tags:
                        return False
        if query.integrity and view.integrity_state.value != query.integrity:
            return False
        if query.review_status and view.governance.get("review_status") != query.review_status:
            return False

        return True

    def _parse_legacy_category(self, category: str, search_text: str) -> FilterQuery:
        if category in (None, "", "全部"):
            return FilterQuery(node_type="all", search_text=search_text)
        if category in ("回收站", "trash", "Trash"):
            return FilterQuery(node_type="trash", search_text=search_text)
        # Match the Core enum value (lowercase), the zh label, and the legacy
        # uppercase name so old saved filters keep resolving after the DataStage
        # unification (ADR 0056: values are now "raw"/"derived"/...).
        if category in (DataStage.RAW.value, stage_label(DataStage.RAW), "原始输入", "RAW"):
            return FilterQuery(node_type="stage", node_value=DataStage.RAW.value, search_text=search_text)
        if category in (DataStage.DERIVED.value, stage_label(DataStage.DERIVED), "派生数据", "DERIVED"):
            return FilterQuery(node_type="stage", node_value=DataStage.DERIVED.value, search_text=search_text)
        if category in (DataStage.INTERMEDIATE.value, stage_label(DataStage.INTERMEDIATE), "中间结果", "INTERMEDIATE"):
            return FilterQuery(node_type="stage", node_value=DataStage.INTERMEDIATE.value, search_text=search_text)
        if category in (DataStage.OUTPUT.value, stage_label(DataStage.OUTPUT), "输出成果", "OUTPUT"):
            return FilterQuery(node_type="stage", node_value=DataStage.OUTPUT.value, search_text=search_text)
        if category.startswith("tag:") or category.startswith("#"):
            tag_name = category.split(":", 1)[-1].lstrip("#")
            return FilterQuery(node_type="tag", node_value=tag_name, search_text=search_text)
        if category in CATEGORIES:
            return FilterQuery(node_type="legacy_category", node_value=category, search_text=search_text)

        # Fallback to type or legacy category match
        return FilterQuery(node_type="legacy_category", node_value=category, search_text=search_text)

    def _haystack(self, view: AssetView) -> str:
        status_zh = _STATUS_LABELS.get(view.status, view.status)
        stage_zh = stage_label(view.stage)
        integrity_zh = view.integrity_state.label
        res_type_zh = RESOURCE_TYPE_LABELS.get(view.type, view.type)

        parts = [
            view.name,
            view.type,
            view.type_label,
            res_type_zh,
            view.format,
            view.stage.value,
            stage_zh,
            view.current_version,
            " ".join(view.tags),
            "受管" if view.managed else "外部 external",
            view.integrity_state.value,
            integrity_zh,
            view.checksum or "",
            view.status,
            status_zh,
            view.source,
            view.path,
            view.lineage_status,
            " ".join(str(v) for v in view.governance.values()),
        ]
        if view.parsed_summary:
            parts.append(str(view.parsed_summary))
        return " ".join(str(p) for p in parts if p).lower()


def compute_catalog_counts(
    resources: Sequence[ResourceItem],
    artifacts: Sequence[ExportArtifact],
    project_root: Path | None = None,
    extra_assets: Sequence[Any] | None = None,
    enricher: Any = None,
    views: Sequence[AssetView] | None = None,
) -> CatalogCounts:
    if views is not None and len(views) == len(resources) + len(artifacts) + len(
        extra_assets or []
    ):
        views = list(views)  # shared prebuilt views (#527)
    else:
        views = []
        for asset in [*resources, *artifacts, *(extra_assets or [])]:
            view = asset_view_from_object(asset, project_root=project_root)
            if enricher is not None:
                view = enricher(view)
            views.append(view)

    total = len(views)
    stage_counts = Counter(v.stage.value for v in views)
    type_counts = Counter(v.type for v in views)
    integrity_counts = Counter(v.integrity_state.value for v in views)
    review_counts = Counter(
        v.governance["review_status"]
        for v in views
        if v.governance.get("review_status")
    )

    tag_counter = Counter()
    for v in views:
        for tag in v.tags:
            tag_counter[tag.strip()] += 1

    # Legacy category counts (resources only for type leaves)
    legacy_type_counts = Counter(r.type for r in resources)
    category_counts = {"全部": total}
    for label, rtype in CATEGORIES.items():
        if label == "全部":
            continue
        category_counts[label] = legacy_type_counts.get(rtype, 0) if rtype else 0

    return CatalogCounts(
        total=total,
        stages=dict(stage_counts),
        types=dict(type_counts),
        tags=dict(tag_counter),
        integrity=dict(integrity_counts),
        categories=category_counts,
        review_status=dict(review_counts),
    )


def compute_category_counts(resources: list, artifacts: list) -> dict[str, int]:
    """Legacy helper function backward-compatibility wrapper."""
    return compute_catalog_counts(resources, artifacts).categories
