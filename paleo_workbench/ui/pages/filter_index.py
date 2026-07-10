from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_catalog_panel import CATEGORIES

ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}


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
                asset.output_path,
                asset.linked_id,
            ]
        else:
            parts = [
                asset.name,
                asset.type,
                asset.format,
                asset.status,
                asset.source,
                asset.path,
            ]
        return " ".join(parts).lower()

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
