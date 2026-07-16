from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLineEdit, QTextBrowser, QTextEdit, QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.resources.exporters import get_available_formats
from paleo_workbench.resources.import_service import (
    ImportReport,
    import_files,
    import_folder,
)
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.workflow.service import dashboard_state


class _ImportWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, task: Callable[[], ImportReport], parent=None):
        super().__init__(parent)
        self._task = task

    @Slot()
    def run(self) -> None:
        try:
            report = self._task()
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(str(exc))
            return
        self.finished.emit(report)


class DataPage(QWidget):
    data_context_changed = Signal(dict)
    import_finished = Signal(object)
    import_failed = Signal(str)
    open_in_visualization = Signal(object)  # VizRef

    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataPage")
        self.project = project or ProjectDocument.new("Untitled Project")
        self._resources = self.project.resources
        self._artifacts = self.project.export_artifacts
        self._selected_asset: object | None = None
        self._import_jobs: list[tuple[QThread, _ImportWorker]] = []
        self._import_in_progress = False
        self._viz_adapter = VizAdapter()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        layout.setSpacing(tokens.SPACE_4)

        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)

        self.data_toolbar = DataToolbar()
        layout.addWidget(self.data_toolbar)

        self.workspace = DataWorkspace()
        layout.addWidget(self.workspace, 1)

        self.navigation_tree = self.workspace.navigation_tree
        self.asset_table = self.workspace.asset_table
        self.reader_panel = self.workspace.reader_panel
        self.inspector_panel = self.workspace.inspector_panel
        self.main_splitter = self.workspace.main_splitter
        self.right_splitter = self.workspace.right_splitter

        self.column_settings_btn = self.asset_table.column_settings_btn
        self.column_settings_menu = self.asset_table.column_settings_menu
        self.column_actions = self.asset_table.column_actions
        self.reset_columns_action = self.asset_table.reset_columns_action
        self.data_toolbar.set_column_settings_button(self.column_settings_btn)

        # Action buttons now live on the toolbar. Keep page-level aliases so
        # existing call sites (and tests) referencing page.import_btn keep
        # working, but they ARE the toolbar buttons — wire each signal once.
        self.import_btn = self.data_toolbar.import_btn
        self.import_folder_btn = self.data_toolbar.import_folder_btn
        self.rescan_btn = self.data_toolbar.rescan_btn
        self.remove_btn = self.data_toolbar.remove_btn
        self.open_visualization_btn = self.data_toolbar.visualize_btn
        self.open_folder_btn = self.data_toolbar.open_folder_btn

        self._preview_controller = PreviewRequestController(
            self.reader_panel.provider,
            self,
        )
        self._preview_controller.loading.connect(
            lambda: self.reader_panel.show_loading(self._selected_asset)
        )
        self._preview_controller.result_ready.connect(self.reader_panel.render)
        self._preview_controller.failed.connect(self._handle_preview_failed)

        self.navigation_tree.category_changed.connect(self.asset_table.set_category)
        self.asset_table.selected_asset_changed.connect(self._set_selected_asset)
        self.asset_table.selected_asset_changed.connect(self.inspector_panel.update_asset)
        self.asset_table.context_menu_requested.connect(self._show_context_menu)
        self.data_toolbar.import_files_requested.connect(self.begin_import_files_from_dialog)
        self.data_toolbar.import_folder_requested.connect(
            self.begin_import_folder_from_dialog
        )
        self.data_toolbar.rescan_requested.connect(self.rescan_selected_asset)
        self.data_toolbar.remove_requested.connect(self.remove_selected_asset)
        self.data_toolbar.open_folder_requested.connect(self.open_selected_folder)
        self.data_toolbar.visualize_requested.connect(self._emit_open_visualization)
        self.data_toolbar.clear_preview_cache_requested.connect(self.clear_preview_cache)
        self.data_toolbar.search_changed.connect(self.asset_table.set_search_text)
        self.data_toolbar.reader_toggled.connect(self._toggle_reader_from_toolbar)
        self._sync_toolbar_toggle_state()
        self.reader_panel.reader_mode_changed.connect(self._handle_reader_mode_changed)

        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )

        # Delete removes the selected asset. Widget-scoped (parent=self) so it
        # only fires when the DataPage or a child has focus; guarded against
        # text-entry widgets so Delete-in-search isn't intercepted.
        QShortcut(QKeySequence("Delete"), self, self._shortcut_remove_asset)

    def _shortcut_remove_asset(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        self.remove_selected_asset()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._preview_controller.shutdown()
        self.reader_panel.release_engine_widgets()
        super().closeEvent(event)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        # Shell rebuild uses deleteLater; closeEvent may not run for nested pages.
        if event.type() == QEvent.Type.DeferredDelete:
            self._preview_controller.shutdown()
            self.reader_panel.release_engine_widgets()
        return super().event(event)

    def update_state(
        self,
        state: dict,
        resources: list[ResourceItem],
        artifacts: list[ExportArtifact] | None = None,
    ) -> None:
        self._resources = resources
        self._artifacts = artifacts or []
        self._preview_controller.set_project_root(self._preview_disk_project_root())
        self.summary_bar.update_state(state)
        self.navigation_tree.update_counts(self._resources, self._artifacts)
        self.asset_table.update_assets(self._resources, self._artifacts)
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _preview_disk_project_root(self) -> str | Path | None:
        """Resolve a real project root for disk cache; treat placeholders as unknown."""
        raw = getattr(self.project.meta, "project_root", None)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text or text == ".":
            return None
        return text

    def clear_preview_cache(self) -> None:
        """Clear the project-scoped disk preview cache and in-memory LRU."""
        self._preview_controller.clear_disk_cache()
        self._set_action_status("已清除预览缓存")

    def import_paths(self, paths: list[Path]) -> ImportReport:
        report = import_files(paths, self.project.resources)
        self._apply_import_report(report)
        return report

    def import_folder_path(self, path: Path) -> ImportReport:
        report = import_folder(path, self.project.resources)
        self._apply_import_report(report)
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

    def begin_import_files_from_dialog(self) -> bool:
        paths = self._choose_import_files()
        if not paths:
            return False
        return self.begin_import_paths(paths)

    def begin_import_folder_from_dialog(self) -> bool:
        folder = self._choose_import_folder()
        if folder is None:
            return False
        return self.begin_import_folder_path(folder)

    def begin_import_paths(self, paths: list[Path]) -> bool:
        if self._import_in_progress:
            self._set_action_status("正在导入，请稍候")
            return False
        existing = list(self.project.resources)
        return self._start_import_job(lambda: import_files(paths, existing))

    def begin_import_folder_path(self, path: Path) -> bool:
        if self._import_in_progress:
            self._set_action_status("正在导入，请稍候")
            return False
        existing = list(self.project.resources)
        return self._start_import_job(lambda: import_folder(path, existing))

    def _start_import_job(self, task: Callable[[], ImportReport]) -> bool:
        thread = QThread(self)
        worker = _ImportWorker(task)
        worker.moveToThread(thread)
        self._import_jobs.append((thread, worker))

        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda report, thread=thread, worker=worker: self._handle_import_finished(
                report,
                thread,
                worker,
            )
        )
        worker.failed.connect(
            lambda message, thread=thread, worker=worker: self._handle_import_failed(
                message,
                thread,
                worker,
            )
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._set_import_running(True)
        self._set_action_status("正在归档文件...")
        thread.start()
        return True

    def _handle_import_finished(
        self,
        report: ImportReport,
        thread: QThread,
        worker: _ImportWorker,
    ) -> None:
        self._apply_import_report(report)
        self._finish_import_job(thread, worker)
        self.import_finished.emit(report)

    def _handle_import_failed(
        self,
        message: str,
        thread: QThread,
        worker: _ImportWorker,
    ) -> None:
        self._set_action_status(f"导入失败: {message}")
        self._finish_import_job(thread, worker)
        self.import_failed.emit(message)

    def _finish_import_job(self, thread: QThread, worker: _ImportWorker) -> None:
        self._import_jobs = [
            job
            for job in self._import_jobs
            if job != (thread, worker)
        ]
        self._set_import_running(False)

    def _set_import_running(self, running: bool) -> None:
        self._import_in_progress = running
        # The toolbar import buttons are the single source of truth; the page
        # aliases (self.import_btn / self.import_folder_btn) point at them.
        self.data_toolbar.import_btn.setEnabled(not running)
        self.data_toolbar.import_folder_btn.setEnabled(not running)

    def remove_selected_asset(self) -> bool:
        if self._selected_asset is None:
            self._set_action_status("请选择一个数据项")
            return False
        selected_id = self._selected_asset.id
        removed = False
        if isinstance(self._selected_asset, ResourceItem):
            before = len(self.project.resources)
            self.project.resources[:] = [
                resource
                for resource in self.project.resources
                if resource.id != selected_id
            ]
            removed = len(self.project.resources) != before
        elif isinstance(self._selected_asset, ExportArtifact):
            before = len(self.project.export_artifacts)
            self.project.export_artifacts[:] = [
                artifact
                for artifact in self.project.export_artifacts
                if artifact.id != selected_id
            ]
            removed = len(self.project.export_artifacts) != before

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
            # Participate in generation invalidation so in-flight previews cannot win.
            self._preview_controller.request(resource)
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
        # Participate in generation invalidation so in-flight previews cannot win.
        self._preview_controller.request(resource)
        self._set_action_status("已重新扫描")
        return True

    def open_selected_folder(self) -> Path | None:
        if self._selected_asset is None:
            self._set_action_status("请选择一个数据项")
            return None
        if isinstance(self._selected_asset, ResourceItem):
            path = Path(self._selected_asset.path)
        else:
            path = Path(self._selected_asset.output_path)
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            self._set_action_status("目录不存在")
            return folder
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder.as_posix()))
        self._set_action_status(f"目录: {folder.as_posix()}")
        return folder

    def _show_context_menu(self, global_pos, asset) -> None:
        """Build and exec the right-click context menu for an asset.

        Wired to ``DataAssetTable.context_menu_requested``. Each menu action's
        ``triggered`` signal is connected to the matching existing handler on
        this page; export sub-actions route through ``_export_selected_asset``.
        """
        viz_supported = isinstance(asset, ResourceItem) and self._viz_adapter.supports_resource(asset)
        menu = AssetContextMenu(self)
        menu.build(asset, viz_supported)

        preview_act = menu.find_action("ctx_preview")
        if preview_act:
            preview_act.triggered.connect(lambda: self._preview_controller.request(asset))

        rescan_act = menu.find_action("ctx_rescan")
        if rescan_act:
            rescan_act.triggered.connect(self.rescan_selected_asset)

        open_folder_act = menu.find_action("ctx_open_folder")
        if open_folder_act:
            open_folder_act.triggered.connect(self.open_selected_folder)

        visualize_act = menu.find_action("ctx_visualize")
        if visualize_act:
            visualize_act.triggered.connect(self._emit_open_visualization)

        remove_act = menu.find_action("ctx_remove")
        if remove_act:
            remove_act.triggered.connect(self.remove_selected_asset)

        # Wire export sub-actions (one per available converter).
        for label, _fn in get_available_formats(asset):
            sub_act = menu.find_export_action(label)
            if sub_act:
                sub_act.triggered.connect(
                    lambda checked=False, fmt=label: self._export_selected_asset(fmt)
                )

        # Wire classify sub-actions (one per available type).
        if isinstance(asset, ResourceItem):
            from paleo_workbench.ui.pages.filter_index import CATEGORIES
            for label, rtype in CATEGORIES.items():
                if rtype is None or rtype == asset.type:
                    continue
                sub_act = menu.find_export_action(f"classify_{rtype}")
                if sub_act:
                    sub_act.triggered.connect(
                        lambda checked=False, t=rtype: self._classify_selected_asset(t)
                    )

        menu.exec(global_pos)

    def _export_selected_asset(self, format_label: str) -> None:
        """Convert the selected resource to ``format_label`` via a save dialog."""
        asset = self._selected_asset
        if asset is None:
            return
        if isinstance(asset, ExportArtifact):
            return
        formats = get_available_formats(asset)
        convert_fn = next((fn for lbl, fn in formats if lbl == format_label), None)
        if convert_fn is None:
            return
        input_path = Path(asset.path)
        # Suggested output extension derived from the target format label.
        ext_map = {"CSV": ".csv", "JSON": ".json", "PNG": ".png", "TXT": ".txt"}
        out_ext = ext_map.get(format_label, ".out")
        suggested = f"{input_path.stem}{out_ext}"
        output_path, _selected_filter = QFileDialog.getSaveFileName(self, "导出为", suggested)
        if not output_path:
            return
        output_path = Path(output_path)
        try:
            convert_fn(input_path, output_path)
            self._set_action_status(f"已导出: {output_path.name}")
        except Exception as exc:
            self._set_action_status(f"导出失败: {exc}")

    def _classify_selected_asset(self, new_type: str) -> None:
        """Change the selected resource's type (manual reclassification)."""
        asset = self._selected_asset
        if not isinstance(asset, ResourceItem):
            return
        old_type = asset.type
        asset.type = new_type
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
        old_label = RESOURCE_TYPE_LABELS.get(old_type, old_type)
        new_label = RESOURCE_TYPE_LABELS.get(new_type, new_type)
        self._set_action_status(f"已归类: {old_label} → {new_label}")

    def _set_selected_asset(self, asset: object | None) -> None:
        self._selected_asset = asset
        self.asset_table.set_selected_asset(asset)
        self._preview_controller.request(asset)
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _sync_visualization_button(self) -> None:
        asset = self._selected_asset
        ok = isinstance(asset, ResourceItem) and self._viz_adapter.supports_resource(asset)
        self.open_visualization_btn.setEnabled(ok)

    def _emit_open_visualization(self) -> None:
        asset = self._selected_asset
        if not isinstance(asset, ResourceItem):
            return
        ref = self._viz_adapter.ref_from_resource(asset)
        if ref is None:
            return
        self.open_in_visualization.emit(replace(ref, source="data_page"))

    def _handle_preview_failed(self, message: str) -> None:
        self.reader_panel.render(
            PreviewResult(mode="message", title="预览失败", message=message)
        )

    def current_reader_mode(self) -> str:
        return self.reader_panel.current_mode

    def _toggle_reader_from_toolbar(self) -> None:
        # The reader toggle shows/hides the right column (reader + inspector).
        # Use isHidden() (intent) rather than isVisible() (render state) so the
        # toggle works before the page has been shown, and so it correctly
        # detects an explicitly-hidden right_splitter.
        make_visible = self.right_splitter.isHidden()
        self.workspace.set_right_visible(make_visible)
        self.data_toolbar.reader_btn.setChecked(make_visible)

    def _sync_toolbar_toggle_state(self) -> None:
        self.data_toolbar.reader_btn.setChecked(not self.right_splitter.isHidden())

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
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _set_import_status(self, report: ImportReport) -> None:
        self._set_action_status(
            f"已归档 {report.added_count} · 重复路径 {len(report.skipped_path)} · 警告 {len(report.warnings)}"
        )

    def _apply_import_report(self, report: ImportReport) -> None:
        """Single batch UI refresh after import (sync or async completion).

        Extends project resources once, then routes through update_state so the
        asset table performs one model reset via set_assets_filtered. Does not
        rebuild the reader; selection may keep prior preview content.
        """
        self.project.resources.extend(report.added)
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )
        self._set_import_status(report)

    def _set_action_status(self, text: str) -> None:
        self.data_toolbar.operation_status_label.setText(text)

    def _update_selection_action_state(self) -> None:
        """Mirror the legacy ActionPanel.update_selection_state enable rules.

        Manages enable state for rescan / remove / open-folder buttons (all on
        the toolbar now) based on the current selection. The toolbar has no
        selection-status label, so only button enable state is synchronized.
        """
        has_resource = isinstance(self._selected_asset, ResourceItem)
        has_asset = self._selected_asset is not None
        self.rescan_btn.setEnabled(has_resource and not self._import_in_progress)
        self.remove_btn.setEnabled(has_asset)
        self.open_folder_btn.setEnabled(has_asset)
