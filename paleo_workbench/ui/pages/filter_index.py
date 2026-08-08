from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    IntegrityState,
    asset_view_from_object,
    stage_label,
)

ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}

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
    node_type: str = "all"  # "all", "stage", "type", "tag", "integrity"
    node_value: str | None = None
    search_text: str = ""
    stage: str | None = None
    data_type: str | None = None
    tag: str | None = None
    integrity: str | None = None


@dataclass
class CatalogCounts:
    total: int = 0
    stages: dict[str, int] = field(default_factory=dict)
    types: dict[str, int] = field(default_factory=dict)
    tags: dict[str, int] = field(default_factory=dict)
    integrity: dict[str, int] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)


class FilterIndex:
    def __init__(self) -> None:
        self._assets: list[ResourceItem | ExportArtifact | Any] = []
        self._views: list[AssetView] = []
        self._haystacks: list[str] = []

    def rebuild(self, assets: Sequence[ResourceItem | ExportArtifact | Any], project_root: Path | None = None) -> None:
        self._assets = list(assets)
        self._views = [asset_view_from_object(a, project_root=project_root) for a in self._assets]
        self._haystacks = [self._haystack(view) for view in self._views]

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
        # 1. Primary tree node filter
        if query.node_type == "stage":
            if query.node_value and view.stage.value != query.node_value:
                return False
        elif query.node_type == "type":
            if query.node_value and view.type != query.node_value:
                # Handle special "other" or "reference" type groupings if needed
                if query.node_value == "other" and view.type in CATEGORIES.values():
                    return False
                elif query.node_value != "other" and view.type != query.node_value:
                    return False
        elif query.node_type == "tag":
            if query.node_value:
                normalized_target = query.node_value.strip().lower()
                asset_tags = [t.strip().lower() for t in view.tags]
                if normalized_target not in asset_tags:
                    return False
        elif query.node_type == "integrity":
            if query.node_value and view.integrity_state.value != query.node_value:
                return False
        elif query.node_type == "legacy_category":
            if query.node_value and query.node_value != "全部":
                if isinstance(view.raw_asset, ExportArtifact):
                    return False
                target_type = CATEGORIES.get(query.node_value)
                if view.type != target_type:
                    return False

        # 2. Multi-dimensional secondary criteria
        if query.stage and view.stage.value != query.stage:
            return False
        if query.data_type and view.type != query.data_type:
            return False
        if query.tag:
            target_tag = query.tag.strip().lower()
            if target_tag not in view.normalized_tags:
                return False
        if query.integrity and view.integrity_state.value != query.integrity:
            return False

        return True

    def _parse_legacy_category(self, category: str, search_text: str) -> FilterQuery:
        if category in (None, "", "全部"):
            return FilterQuery(node_type="all", search_text=search_text)
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
        ]
        if view.parsed_summary:
            parts.append(str(view.parsed_summary))
        return " ".join(str(p) for p in parts if p).lower()


def compute_catalog_counts(
    resources: Sequence[ResourceItem],
    artifacts: Sequence[ExportArtifact],
    project_root: Path | None = None,
) -> CatalogCounts:
    views: list[AssetView] = [
        *[asset_view_from_object(r, project_root=project_root) for r in resources],
        *[asset_view_from_object(a, project_root=project_root) for a in artifacts],
    ]

    total = len(views)
    stage_counts = Counter(v.stage.value for v in views)
    type_counts = Counter(v.type for v in views)
    integrity_counts = Counter(v.integrity_state.value for v in views)

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
    )


def compute_category_counts(resources: list, artifacts: list) -> dict[str, int]:
    """Legacy helper function backward-compatibility wrapper."""
    return compute_catalog_counts(resources, artifacts).categories
