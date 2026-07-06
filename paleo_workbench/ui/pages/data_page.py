from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import (
    ImportReport,
    import_files,
    import_folder,
)
from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_detail_panel import DataDetailPanel
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar
from paleo_workbench.workflow.service import dashboard_state


class DataPage(QWidget):
    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataPage")
        self.project = project or ProjectDocument.new("Untitled Project")
        self._resources = self.project.resources
        self._artifacts = self.project.export_artifacts

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        self.catalog_panel = DataCatalogPanel()
        bottom.addWidget(self.catalog_panel, 0)

        self.asset_table = DataAssetTable()
        bottom.addWidget(self.asset_table, 1)

        self.detail_panel = DataDetailPanel()
        bottom.addWidget(self.detail_panel, 0)

        self.action_panel = ActionPanel()
        self.import_btn = self.action_panel.import_btn
        self.import_folder_btn = self.action_panel.import_folder_btn
        self.rescan_btn = self.action_panel.rescan_btn
        self.remove_btn = self.action_panel.remove_btn
        bottom.addWidget(self.action_panel, 0)

        layout.addLayout(bottom, 1)

        self.catalog_panel.category_changed.connect(self.asset_table.set_category)
        self.asset_table.selected_asset_changed.connect(self.detail_panel.update_asset)
        self.import_btn.clicked.connect(self.import_files_from_dialog)
        self.import_folder_btn.clicked.connect(self.import_folder_from_dialog)

        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )

    def update_state(
        self,
        state: dict,
        resources: list[ResourceItem],
        artifacts: list[ExportArtifact] | None = None,
    ) -> None:
        self._resources = resources
        self._artifacts = artifacts or []
        self.summary_bar.update_state(state)
        self.catalog_panel.update_counts(self._resources, self._artifacts)
        self.asset_table.update_assets(self._resources, self._artifacts)

    def import_paths(self, paths: list[Path]) -> ImportReport:
        report = import_files(paths, self.project.resources)
        self.project.resources.extend(report.added)
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        return report

    def import_folder_path(self, path: Path) -> ImportReport:
        report = import_folder(path, self.project.resources)
        self.project.resources.extend(report.added)
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        return report

    def _choose_import_files(self) -> list[Path]:
        paths, _selected_filter = QFileDialog.getOpenFileNames(self, "导入文件")
        return [Path(path) for path in paths]

    def _choose_import_folder(self) -> Path | None:
        path = QFileDialog.getExistingDirectory(self, "导入目录")
        return Path(path) if path else None

    def import_files_from_dialog(self) -> ImportReport:
        paths = self._choose_import_files()
        if not paths:
            return ImportReport()
        return self.import_paths(paths)

    def import_folder_from_dialog(self) -> ImportReport:
        folder = self._choose_import_folder()
        if folder is None:
            return ImportReport()
        return self.import_folder_path(folder)
