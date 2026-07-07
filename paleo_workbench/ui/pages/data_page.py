from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import (
    ImportReport,
    import_files,
    import_folder,
)
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.ui.pages.action_panel import ActionPanel
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar
from paleo_workbench.workflow.service import dashboard_state


class DataPage(QWidget):
    data_context_changed = Signal(dict)

    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataPage")
        self.project = project or ProjectDocument.new("Untitled Project")
        self._resources = self.project.resources
        self._artifacts = self.project.export_artifacts
        self._selected_asset: object | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)

        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("DataContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.catalog_panel = DataCatalogPanel()
        self.content_splitter.addWidget(self.catalog_panel)

        self.asset_table = DataAssetTable()
        self.content_splitter.addWidget(self.asset_table)

        self.reader_panel = DataReaderPanel()
        self.content_splitter.addWidget(self.reader_panel)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setStretchFactor(2, 2)
        self.content_splitter.setSizes([180, 560, 520])
        bottom.addWidget(self.content_splitter, 1)

        self.action_panel = ActionPanel()
        self.import_btn = self.action_panel.import_btn
        self.import_folder_btn = self.action_panel.import_folder_btn
        self.rescan_btn = self.action_panel.rescan_btn
        self.remove_btn = self.action_panel.remove_btn
        bottom.addWidget(self.action_panel, 0)

        layout.addLayout(bottom, 1)

        self.catalog_panel.category_changed.connect(self.asset_table.set_category)
        self.asset_table.selected_asset_changed.connect(self._set_selected_asset)
        self.import_btn.clicked.connect(self.import_files_from_dialog)
        self.import_folder_btn.clicked.connect(self.import_folder_from_dialog)
        self.rescan_btn.clicked.connect(self.rescan_selected_asset)
        self.remove_btn.clicked.connect(self.remove_selected_asset)
        self.action_panel.open_folder_btn.clicked.connect(self.open_selected_folder)
        self.reader_panel.reader_mode_changed.connect(self._handle_reader_mode_changed)

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
        self.action_panel.update_selection_state(
            has_resource=isinstance(self._selected_asset, ResourceItem),
            has_asset=self._selected_asset is not None,
            reader_mode=self.reader_panel.current_mode,
        )
        self._emit_data_context()

    def import_paths(self, paths: list[Path]) -> ImportReport:
        report = import_files(paths, self.project.resources)
        self.project.resources.extend(report.added)
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        self._set_import_status(report)
        return report

    def import_folder_path(self, path: Path) -> ImportReport:
        report = import_folder(path, self.project.resources)
        self.project.resources.extend(report.added)
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        self._set_import_status(report)
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

    def remove_selected_asset(self) -> bool:
        if not isinstance(self._selected_asset, ResourceItem):
            self._set_action_status("请选择一个项目资源")
            return False
        selected_id = self._selected_asset.id
        before = len(self.project.resources)
        self.project.resources[:] = [
            resource
            for resource in self.project.resources
            if resource.id != selected_id
        ]
        removed = len(self.project.resources) != before
        if removed:
            self._set_selected_asset(None)
            self.update_state(
                dashboard_state(self.project),
                self.project.resources,
                self.project.export_artifacts,
            )
            self._set_action_status("已移出项目")
        return removed

    def rescan_selected_asset(self) -> bool:
        if not isinstance(self._selected_asset, ResourceItem):
            self._set_action_status("请选择一个项目资源")
            return False
        resource = self._selected_asset
        path = Path(resource.path)
        if not path.exists():
            resource.status = "missing"
            resource.parsed_summary["preview_warning"] = "文件不存在"
            self.update_state(
                dashboard_state(self.project),
                self.project.resources,
                self.project.export_artifacts,
            )
            self.reader_panel.update_asset(resource)
            self._set_action_status("文件不存在")
            return True

        scanned = scan_resources(path.parent)
        updated = next(
            (item for item in scanned if Path(item.path).resolve() == path.resolve()),
            None,
        )
        if updated is None:
            self._set_action_status("重新扫描未找到文件")
            return False
        resource.name = updated.name
        resource.path = updated.path
        resource.type = updated.type
        resource.format = updated.format
        resource.status = updated.status
        resource.source = updated.source
        resource.parsed_summary = updated.parsed_summary
        resource.checksum = updated.checksum
        resource.external = updated.external
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        self.reader_panel.update_asset(resource)
        self._set_action_status("已重新扫描")
        return True

    def open_selected_folder(self) -> Path | None:
        if not isinstance(self._selected_asset, ResourceItem):
            self._set_action_status("请选择一个项目资源")
            return None
        path = Path(self._selected_asset.path)
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            self._set_action_status("目录不存在")
            return folder
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder.as_posix()))
        self._set_action_status(f"目录: {folder.as_posix()}")
        return folder

    def _set_selected_asset(self, asset: object | None) -> None:
        self._selected_asset = asset
        self.reader_panel.update_asset(asset)
        has_resource = isinstance(asset, ResourceItem)
        self.action_panel.update_selection_state(
            has_resource=has_resource,
            has_asset=asset is not None,
            reader_mode=self.reader_panel.current_mode,
        )
        self._emit_data_context()

    def current_reader_mode(self) -> str:
        return self.reader_panel.current_mode

    def _emit_data_context(self) -> None:
        issue_count = sum(
            1
            for resource in self.project.resources
            if resource.status in {"missing", "warning", "failed", "error"}
        )
        selected = self._selected_asset
        selected_name = "未选择"
        selected_type = ""
        selected_format = ""
        if isinstance(selected, ResourceItem):
            selected_name = selected.name
            selected_type = selected.type
            selected_format = selected.format
        elif isinstance(selected, ExportArtifact):
            selected_name = Path(selected.output_path).name
            selected_type = "成果"
            selected_format = selected.format
        self.data_context_changed.emit(
            {
                "resource_count": len(self.project.resources),
                "artifact_count": len(self.project.export_artifacts),
                "issue_count": issue_count,
                "selected_name": selected_name,
                "selected_type": selected_type,
                "selected_format": selected_format,
                "reader_mode": self.reader_panel.current_mode,
            }
        )

    def _handle_reader_mode_changed(self, _mode: str) -> None:
        self.action_panel.update_selection_state(
            has_resource=isinstance(self._selected_asset, ResourceItem),
            has_asset=self._selected_asset is not None,
            reader_mode=self.reader_panel.current_mode,
        )

    def _set_import_status(self, report: ImportReport) -> None:
        self._set_action_status(
            f"新增 {report.added_count} · 重复 {report.skipped_count} · 警告 {len(report.warnings)}"
        )

    def _set_action_status(self, text: str) -> None:
        self.action_panel.status_label.setText(text)
