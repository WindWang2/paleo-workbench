from __future__ import annotations

from collections import Counter
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS

ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}

# Canonical home for the smart-group category mapping. Moved here from
# data_catalog_panel to resolve a circular import (filter_index is imported
# during panel construction). data_catalog_panel now imports this dict.
CATEGORIES = {
    "全部": None,
    "输入数据": "input",
    "成果": "artifact",
    "参考资料": "reference",
    "异常": "issue",
    "测井": "well_log",
    "地震": "seismic",
    "层位": "horizon",
    "井分层": "well_stratification",
    "时深": "time_depth",
    "表格": "tabular",
    "文档": "document",
    "影像": "image_reference",
    "参考图": "reference_map",
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
}


class FilterIndex:
    def __init__(self) -> None:
        self._assets: list[ResourceItem | ExportArtifact] = []
        self._haystacks: list[str] = []

    def rebuild(self, assets: list[ResourceItem | ExportArtifact]) -> None:
        self._assets = list(assets)
        self._haystacks = [self._haystack(asset) for asset in self._assets]

    def filter(self, category: str, search_text: str) -> list[int]:
        needle = search_text.strip().lower()
        rows: list[int] = []
        for i, asset in enumerate(self._assets):
            if not self._matches_category(asset, category):
                continue
            if needle and needle not in self._haystacks[i]:
                continue
            rows.append(i)
        return rows

    def _haystack(self, asset: ResourceItem | ExportArtifact) -> str:
        if isinstance(asset, ExportArtifact):
            parts = [
                Path(asset.output_path).name,
                asset.format,
                "成果",
                "export",
                asset.output_path,
                asset.linked_id,
            ]
        else:
            type_zh = RESOURCE_TYPE_LABELS.get(asset.type, asset.type)
            status_zh = _STATUS_LABELS.get(asset.status, asset.status)
            parts = [
                asset.name,
                asset.type,
                type_zh,
                asset.format,
                asset.status,
                status_zh,
                asset.source,
                asset.path,
            ]
        return " ".join(str(p) for p in parts if p).lower()

    def _matches_category(
        self,
        asset: ResourceItem | ExportArtifact,
        category: str,
    ) -> bool:
        if category == "全部":
            return True
        if isinstance(asset, ExportArtifact):
            return category == "成果"

        if category == "输入数据":
            return (asset.artifact_role or "input") == "input"
        if category == "成果":
            return (asset.artifact_role or "") in {"derived", "export"}
        if category == "参考资料":
            return asset.type in REFERENCE_TYPES
        if category == "异常":
            return asset.status in ISSUE_STATUSES

        resource_type = CATEGORIES.get(category)
        return asset.type == resource_type


def compute_category_counts(resources: list, artifacts: list) -> dict[str, int]:
    """Count assets per CATEGORIES key, mirroring DataCatalogPanel logic."""
    type_counts = Counter(r.type for r in resources)
    role_counts = Counter(r.artifact_role or "input" for r in resources)
    issue_count = sum(1 for r in resources if r.status in ISSUE_STATUSES)
    values = {
        "全部": len(resources) + len(artifacts),
        "输入数据": role_counts["input"],
        "成果": len(artifacts) + role_counts["derived"] + role_counts["export"],
        "参考资料": sum(type_counts[k] for k in REFERENCE_TYPES),
        "异常": issue_count,
    }
    result = dict(values)
    for label, rtype in CATEGORIES.items():
        if label not in result:
            result[label] = type_counts[rtype] if rtype else 0
    return result
