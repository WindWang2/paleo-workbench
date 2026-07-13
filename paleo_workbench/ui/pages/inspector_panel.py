from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.preview_widgets import TablePreviewWidget


class InspectorPanel(QFrame):
    """Read-only metadata inspector for the selected asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setStyleSheet(
            f"QFrame#InspectorPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("检查器")
        self.title_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.metadata_table = TablePreviewWidget()
        layout.addWidget(self.metadata_table, 1)

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        if asset is None:
            self.metadata_table.load_table((), ())
            return
        if isinstance(asset, ResourceItem):
            rows = self._resource_rows(asset)
        else:
            rows = self._artifact_rows(asset)
        self.metadata_table.load_table(("属性", "值"), rows)

    @staticmethod
    def _resource_rows(res: ResourceItem) -> tuple[tuple[str, str], ...]:
        size = res.parsed_summary.get("size_bytes")
        tags = ", ".join(res.tags) if res.tags else "—"
        return (
            ("名称", res.name),
            ("路径", res.path),
            ("类型", RESOURCE_TYPE_LABELS.get(res.type, res.type)),
            ("格式", res.format),
            ("CRS", res.crs or "—"),
            ("标签", tags),
            ("校验和", res.checksum or "—"),
            ("状态", res.status),
            ("大小", str(size) if size is not None else "—"),
            ("来源", res.source),
            ("外部", "是" if res.external else "否"),
        )

    @staticmethod
    def _artifact_rows(art: ExportArtifact) -> tuple[tuple[str, str], ...]:
        return (
            ("格式", art.format),
            ("输出路径", art.output_path),
            ("关联对象", art.linked_id),
            ("包含要素", ", ".join(art.included_map_elements) or "—"),
            ("生成时间", art.generated_at),
            ("来源任务", ", ".join(art.source_task_ids) or "—"),
        )
