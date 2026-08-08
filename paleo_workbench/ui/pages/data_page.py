from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QLineEdit, QTextBrowser, QTextEdit, QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.project.paths import resolve_project_path
from paleo_workbench.resources.export_service import (
    default_export_dir,
    export_asset_to_path,
    export_project_inventory,
)
from paleo_workbench.resources.exporters import extension_for_label, get_available_formats
from paleo_workbench.resources.import_service import (
    ImportReport,
    import_files,
    import_folder,
)
from paleo_workbench.resources.io_registry import ROLE_BY_TYPE
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.ui import tokens
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.pages.data_view_models import DataStage, asset_view_from_object
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.filter_index import CATEGORIES
from paleo_workbench.ui.pages.integrity_worker import IntegrityCheckReport, IntegrityWorker
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar
from paleo_workbench.ui.pages.tag_widgets import TagInputDialog
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

    def __init__(
        self,
        project: ProjectDocument | None = None,
        parent=None,
        *,
        well_state_store=None,
    ):
        super().__init__(parent)
        self.setObjectName("DataPage")
        self.project = project or ProjectDocument.new("Untitled Project")
        self.project_path: Path | None = None
        self._resources = self.project.resources
        self._artifacts = self.project.export_artifacts
        self._selected_asset: object | None = None
        self._selected_assets: list[object] = []
        self._import_job = OwnedWorkerJob(self)
        self._import_job.released.connect(self._finish_import_job)
        self._verify_job = OwnedWorkerJob(self)
        self._import_in_progress = False
        self._viz_adapter = VizAdapter()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN, tokens.PAGE_MARGIN)
        layout.setSpacing(tokens.SPACE_4)

        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)

        self.data_toolbar = DataToolbar()
        layout.addWidget(self.data_toolbar)

        self.workspace = DataWorkspace(
            well_state_store=well_state_store,
            comparison_crs=str(self.project.coordinate.project_crs or ""),
        )
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

        self.import_btn = self.data_toolbar.import_btn
        self.import_folder_btn = self.data_toolbar.import_folder_btn
        self.rescan_btn = self.data_toolbar.rescan_btn
        self.remove_btn = self.data_toolbar.remove_btn
        self.open_visualization_btn = self.data_toolbar.visualize_btn
        self.open_folder_btn = self.data_toolbar.open_folder_btn

        self._preview_controller = PreviewRequestController(
            self.reader_panel.provider,
            self,
            settings=self.reader_panel.preview_settings,
            request_kind="summary",
        )
        self._preview_controller.loading.connect(
            lambda: self.reader_panel.show_loading(self._selected_asset)
        )
        self._preview_controller.result_ready.connect(self.reader_panel.render)
        self._preview_controller.failed.connect(self._handle_preview_failed)

        self._visualization_controller = PreviewRequestController(
            self.reader_panel.provider,
            self,
            settings=self.reader_panel.preview_settings,
            request_kind="visualization",
        )
        comparison_crs = str(self.project.coordinate.project_crs or "")
        self._preview_controller.set_comparison_crs(comparison_crs or None)
        self._visualization_controller.set_comparison_crs(comparison_crs or None)
        self._visualization_controller.loading.connect(
            self.reader_panel.show_visualization_loading
        )
        self._visualization_controller.result_ready.connect(
            self.reader_panel.render_visualization
        )
        self._visualization_controller.failed.connect(
            self.reader_panel.show_visualization_error
        )

        # Wire tree & table navigation
        self.navigation_tree.category_changed.connect(self.asset_table.set_category)
        self.navigation_tree.filter_query_changed.connect(self.asset_table.set_filter_query)

        self.asset_table.selected_asset_changed.connect(self._set_selected_asset)
        self.asset_table.selected_assets_changed.connect(self._set_selected_assets)
        self.asset_table.selected_asset_changed.connect(self.inspector_panel.update_asset)
        self.asset_table.context_menu_requested.connect(self._show_context_menu)

        # Wire toolbar buttons
        self.data_toolbar.import_files_requested.connect(self.begin_import_files_from_dialog)
        self.data_toolbar.import_folder_requested.connect(self.begin_import_folder_from_dialog)
        self.data_toolbar.verify_requested.connect(self._verify_current_or_all_assets)
        self.data_toolbar.rescan_requested.connect(self.rescan_selected_asset)
        self.data_toolbar.remove_requested.connect(self.remove_selected_asset)
        self.data_toolbar.open_folder_requested.connect(self.open_selected_folder)
        self.data_toolbar.visualize_requested.connect(self._emit_open_visualization)
        self.data_toolbar.clear_preview_cache_requested.connect(self.clear_preview_cache)
        self.data_toolbar.search_changed.connect(self.asset_table.set_search_text)
        self.data_toolbar.reader_toggled.connect(self._toggle_reader_from_toolbar)
        self._sync_toolbar_toggle_state()

        # Wire inspector panel interactive signals
        self.inspector_panel.tag_added.connect(self._handle_tag_added)
        self.inspector_panel.tag_removed.connect(self._handle_tag_removed)
        self.inspector_panel.verify_requested.connect(self._verify_single_asset)
        self.inspector_panel.create_derived_requested.connect(self._create_derived_copy)

        self.reader_panel.reader_mode_changed.connect(self._handle_reader_mode_changed)
        self.reader_panel.preview_settings_changed.connect(self._handle_preview_settings_changed)
        self.reader_panel.visualization_requested.connect(self._request_selected_visualization)

        self._refresh()

        QShortcut(
            QKeySequence("Delete"),
            self,
            self._shortcut_remove_asset,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )

    def _shortcut_remove_asset(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        self.remove_selected_asset()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._shutdown_workers()
        super().closeEvent(event)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.DeferredDelete:
            self._shutdown_workers()
        return super().event(event)

    def _shutdown_workers(self) -> None:
        wait_ms = 5000 if "pytest" in sys.modules else 100
        self._preview_controller.shutdown(wait_ms)
        self._visualization_controller.shutdown(wait_ms)
        self.reader_panel.release_engine_widgets()
        self._shutdown_import_jobs(wait_ms)
        self._verify_job.shutdown(wait_ms)

    def _shutdown_import_jobs(self, wait_ms: int = 5_000) -> None:
        self._import_job.shutdown(wait_ms)
        self._set_import_running(False)

    def update_state(
        self,
        state: dict,
        resources: list[ResourceItem],
        artifacts: list[ExportArtifact] | None = None,
    ) -> None:
        self._resources = resources
        self._artifacts = artifacts or []
        preview_root = self._preview_disk_project_root()
        self._preview_controller.set_project_root(preview_root)
        self._visualization_controller.set_project_root(preview_root)
        self.summary_bar.update_state(state)
        self.navigation_tree.update_counts(self._resources, self._artifacts)
        self.asset_table.update_assets(self._resources, self._artifacts)
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _refresh(self) -> None:
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )

    def _preview_disk_project_root(self) -> Path | None:
        raw = getattr(self.project.meta, "project_root", None)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text or text == ".":
            return None
        return Path(text)

    def clear_preview_cache(self) -> None:
        self._preview_controller.clear_disk_cache()
        self._visualization_controller.clear_disk_cache()
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
        paths, _selected_filter = QFileDialog.getOpenFileNames(self, "导入受管文件")
        return [Path(path) for path in paths]

    def _choose_import_folder(self) -> Path | None:
        path = QFileDialog.getExistingDirectory(self, "导入受管目录")
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

    def set_project_path(self, path: Path | str | None) -> None:
        if path is None or str(path).strip() in {"", ".", ".."}:
            self.project_path = None
        else:
            self.project_path = Path(path)

    def _project_file_for_io(self) -> Path | None:
        return self.project_path

    def _resolve_resource_path(self, resource: ResourceItem) -> Path:
        raw = Path(resource.path)
        if raw.is_absolute() or self.project_path is None:
            return raw.expanduser()
        return Path(resolve_project_path(str(raw), self.project_path))

    def begin_import_paths(self, paths: list[Path]) -> bool:
        if self._import_in_progress:
            self._set_action_status("正在导入，请稍候")
            return False
        existing = list(self.project.resources)
        project_path = self._project_file_for_io()
        return self._start_import_job(
            lambda: import_files(paths, existing, project_path=project_path)
        )

    def begin_import_folder_path(self, path: Path) -> bool:
        if self._import_in_progress:
            self._set_action_status("正在导入，请稍候")
            return False
        existing = list(self.project.resources)
        project_path = self._project_file_for_io()
        return self._start_import_job(
            lambda: import_folder(path, existing, project_path=project_path)
        )

    def _start_import_job(self, task: Callable[[], ImportReport]) -> bool:
        worker = _ImportWorker(task)
        self._import_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._handle_import_finished_signal),
                (worker.failed, self._handle_import_failed_signal),
            ),
            target=self.project,
        )

        self._set_import_running(True)
        self._set_action_status("正在归档文件...")
        return True

    @Slot(object)
    def _handle_import_finished_signal(self, report: ImportReport) -> None:
        if self._import_job.target is not self.project:
            return
        self._handle_import_finished(report)

    @Slot(str)
    def _handle_import_failed_signal(self, message: str) -> None:
        if self._import_job.target is not self.project:
            return
        self._handle_import_failed(message)

    def _handle_import_finished(self, report: ImportReport) -> None:
        if report is None:
            self._set_action_status("导入未返回有效报告")
            return
        self._apply_import_report(report)
        self.import_finished.emit(report)

    def _handle_import_failed(self, message: str) -> None:
        self._set_action_status(f"导入失败: {message}")
        self.import_failed.emit(message)

    def _finish_import_job(self) -> None:
        self._set_import_running(False)

    def _set_import_running(self, running: bool) -> None:
        self._import_in_progress = running
        self.data_toolbar.import_btn.setEnabled(not running)
        self.data_toolbar.import_folder_btn.setEnabled(not running)

    def remove_selected_asset(self) -> bool:
        if not self._selected_assets and self._selected_asset is not None:
            items = [self._selected_asset]
        else:
            items = self._selected_assets

        if not items:
            self._set_action_status("请选择一个或多个数据项")
            return False

        return self.remove_assets(items)

    def remove_assets(self, items: list[object]) -> bool:
        removed_count = 0
        target_ids = {getattr(it, "id", None) for it in items if getattr(it, "id", None)}

        before_res = len(self.project.resources)
        self.project.resources[:] = [
            r for r in self.project.resources if r.id not in target_ids
        ]
        removed_count += before_res - len(self.project.resources)

        before_art = len(self.project.export_artifacts)
        self.project.export_artifacts[:] = [
            a for a in self.project.export_artifacts if a.id not in target_ids
        ]
        removed_count += before_art - len(self.project.export_artifacts)

        if removed_count > 0:
            self._set_selected_asset(None)
            self._refresh()
            self._set_action_status(f"已移出项目 ({removed_count} 项)")
            return True
        return False

    def rescan_selected_asset(self) -> bool:
        if not isinstance(self._selected_asset, ResourceItem):
            self._set_action_status("请选择一个项目资源")
            return False
        resource = self._selected_asset
        path = self._resolve_resource_path(resource)
        if not path.exists():
            resource.status = "missing"
            if resource.parsed_summary is None:
                resource.parsed_summary = {}
            resource.parsed_summary["preview_warning"] = "文件不存在"
            self._refresh()
            self._request_summary(resource)
            self._set_action_status("文件不存在")
            return True

        project_path = self._project_file_for_io()
        scanned = scan_resources(path.parent, project_path=project_path)
        path_resolved = path.resolve()
        updated = None
        for item in scanned:
            try:
                item_path = Path(item.path)
                if not item_path.is_absolute() and project_path is not None:
                    item_path = Path(resolve_project_path(str(item.path), project_path))
                if item_path.resolve() == path_resolved:
                    updated = item
                    break
            except OSError:
                continue
        if updated is None:
            self._set_action_status("重新扫描未找到文件")
            return False

        keep_type = resource.type
        keep_role = resource.artifact_role
        keep_tags = list(resource.tags or [])
        resource.name = updated.name
        resource.path = updated.path
        resource.format = updated.format
        resource.status = updated.status
        resource.source = updated.source
        resource.parsed_summary = updated.parsed_summary
        resource.checksum = updated.checksum
        resource.external = updated.external

        if keep_type == updated.type or not keep_type:
            resource.type = updated.type
            resource.artifact_role = updated.artifact_role or keep_role
        else:
            resource.type = keep_type
            resource.artifact_role = keep_role
            resource.tags = keep_tags

        self._refresh()
        self._request_summary(resource)
        self._set_action_status("已重新扫描")
        return True

    def open_selected_folder(self) -> Path | None:
        if self._selected_asset is None:
            self._set_action_status("请选择一个数据项")
            return None
        if isinstance(self._selected_asset, ResourceItem):
            path = Path(self._selected_asset.path)
        elif isinstance(self._selected_asset, ExportArtifact):
            path = Path(self._selected_asset.output_path)
        else:
            path = Path(getattr(self._selected_asset, "path", ""))

        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            self._set_action_status("目录不存在")
            return folder
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder.as_posix()))
        self._set_action_status(f"目录: {folder.as_posix()}")
        return folder

    def _create_derived_copy(self, asset: object) -> None:
        """Create a derived data copy from a locked RAW asset."""
        if not isinstance(asset, ResourceItem):
            self._set_action_status("仅支持为 ResourceItem 数据创建派生副本")
            return

        view = asset_view_from_object(asset)
        derived_item = ResourceItem(
            name=f"{asset.name}_derived",
            path=asset.path,
            type=asset.type,
            format=asset.format,
            crs=asset.crs,
            status=asset.status,
            tags=["派生", *asset.tags],
            source=f"derived from {asset.name}",
            parsed_summary={"derived_from_id": asset.id, "derived_from_name": asset.name, **asset.parsed_summary},
            checksum=asset.checksum,
            external=asset.external,
            artifact_role="derived",
        )

        self.project.resources.append(derived_item)
        self._refresh()
        self._set_selected_asset(derived_item)
        self._set_action_status(f"已从 🔒 RAW 建立派生副本: {derived_item.name}")

    def _show_context_menu(self, global_pos, target) -> None:
        viz_supported = False
        first = target[0] if isinstance(target, (list, tuple)) and target else target
        if isinstance(first, ResourceItem):
            viz_supported = self._viz_adapter.supports_resource(first)

        menu = AssetContextMenu(self)
        menu.build(target, viz_supported)

        preview_act = menu.find_action("ctx_preview")
        if preview_act:
            preview_act.triggered.connect(lambda: self._request_summary(first))

        create_derived_act = menu.find_action("ctx_create_derived")
        if create_derived_act:
            create_derived_act.triggered.connect(lambda: self._create_derived_copy(first))

        verify_act = menu.find_action("ctx_verify")
        if verify_act:
            verify_act.triggered.connect(lambda: self._verify_single_asset(first))

        add_tag_act = menu.find_action("ctx_add_tag")
        if add_tag_act:
            add_tag_act.triggered.connect(lambda: self._prompt_add_tag_to_assets([first]))

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

        # Multi selection context actions
        items = list(target) if isinstance(target, (list, tuple)) else [target]
        bulk_add_tag_act = menu.find_action("ctx_bulk_add_tag")
        if bulk_add_tag_act:
            bulk_add_tag_act.triggered.connect(lambda: self._prompt_add_tag_to_assets(items))

        bulk_remove_tag_act = menu.find_action("ctx_bulk_remove_tag")
        if bulk_remove_tag_act:
            bulk_remove_tag_act.triggered.connect(lambda: self._prompt_remove_tag_from_assets(items))

        bulk_verify_act = menu.find_action("ctx_bulk_verify")
        if bulk_verify_act:
            bulk_verify_act.triggered.connect(lambda: self.verify_assets(items))

        bulk_remove_act = menu.find_action("ctx_bulk_remove")
        if bulk_remove_act:
            bulk_remove_act.triggered.connect(lambda: self.remove_assets(items))

        # Wire export sub-actions
        if first:
            for label, _fn in get_available_formats(first):
                sub_act = menu.find_export_action(label)
                if sub_act:
                    sub_act.triggered.connect(
                        lambda checked=False, fmt=label: self._export_selected_asset(fmt)
                    )
            inv_act = menu.find_export_action("INVENTORY")
            if inv_act:
                inv_act.triggered.connect(
                    lambda checked=False: self._export_selected_asset("INVENTORY")
                )

            if isinstance(first, ResourceItem):
                for label, rtype in CATEGORIES.items():
                    if rtype is None or rtype == first.type:
                        continue
                    sub_act = menu.find_export_action(f"classify_{rtype}")
                    if sub_act:
                        sub_act.triggered.connect(
                            lambda checked=False, t=rtype: self._classify_selected_asset(t)
                        )

        menu.exec(global_pos)

    def _export_selected_asset(self, format_label: str) -> None:
        asset = self._selected_asset
        if asset is None or isinstance(asset, ExportArtifact):
            return
        project_file = self._project_file_for_io()
        if format_label == "INVENTORY":
            start = default_export_dir(project_file)
            suggested = str(start / f"{self.project.meta.name or 'project'}_inventory.json")
            output_path, _ = QFileDialog.getSaveFileName(
                self, "导出工程清单", suggested, "JSON (*.json)"
            )
            if not output_path:
                return
            try:
                result = export_project_inventory(
                    self.project,
                    Path(output_path),
                    project_path=project_file,
                    register=True,
                )
            except Exception as exc:
                self._set_action_status(f"导出失败：{exc}")
                return
            self._set_action_status(result.message)
            if result.success:
                self._refresh()
            return

        formats = get_available_formats(asset)
        if not any(lbl == format_label for lbl, _ in formats):
            return
        input_path = self._resolve_resource_path(asset) if isinstance(asset, ResourceItem) else Path(asset.path)
        out_ext = extension_for_label(format_label)
        suggested = str(
            default_export_dir(project_file) / f"{input_path.stem}{out_ext}"
        )
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self, "导出为", suggested
        )
        if not output_path:
            return
        try:
            result = export_asset_to_path(
                asset,
                format_label,
                Path(output_path),
                project=self.project,
                project_path=project_file,
                register=True,
            )
        except Exception as exc:
            self._set_action_status(f"导出失败：{exc}")
            return
        self._set_action_status(result.message)
        if result.success and result.artifact is not None:
            self._refresh()

    def _classify_selected_asset(self, new_type: str) -> None:
        asset = self._selected_asset
        if not isinstance(asset, ResourceItem):
            return
        old_type = asset.type
        asset.type = new_type
        role = ROLE_BY_TYPE.get(new_type)
        asset.artifact_role = role
        other = [t for t in (asset.tags or []) if t not in ROLE_BY_TYPE.values()]
        asset.tags = ([role] if role else []) + other
        self._refresh()
        old_label = RESOURCE_TYPE_LABELS.get(old_type, old_type)
        new_label = RESOURCE_TYPE_LABELS.get(new_type, new_type)
        self._set_action_status(f"已归类: {old_label} → {new_label}")

    def _set_selected_asset(self, asset: object | None) -> None:
        self._selected_asset = asset
        self._selected_assets = [asset] if asset is not None else []
        self.asset_table.set_selected_asset(asset)
        self._request_summary(asset)
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _set_selected_assets(self, assets: list[object]) -> None:
        self._selected_assets = list(assets)
        first = self._selected_assets[0] if self._selected_assets else None
        if first != self._selected_asset:
            self._selected_asset = first
            self.inspector_panel.update_asset(first)
            self._request_summary(first)
            self._update_selection_action_state()
            self._sync_visualization_button()
            self._emit_data_context()

    # --- Tag Operations ---

    def _handle_tag_added(self, asset: object, tag_name: str) -> None:
        if isinstance(asset, ResourceItem):
            if tag_name not in asset.tags:
                asset.tags.append(tag_name)
                self._refresh()
                self._set_action_status(f"已添加标签 #{tag_name}")

    def _handle_tag_removed(self, asset: object, tag_name: str) -> None:
        if isinstance(asset, ResourceItem):
            if tag_name in asset.tags:
                asset.tags.remove(tag_name)
                self._refresh()
                self._set_action_status(f"已移除标签 #{tag_name}")

    def _prompt_add_tag_to_assets(self, items: list[object]) -> None:
        dlg = TagInputDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tag = dlg.get_tag_name()
            if not new_tag:
                return
            count = 0
            for it in items:
                if isinstance(it, ResourceItem):
                    if new_tag not in it.tags:
                        it.tags.append(new_tag)
                        count += 1
            if count > 0:
                self._refresh()
                self._set_action_status(f"已为 {count} 项数据添加标签 #{new_tag}")

    def _prompt_remove_tag_from_assets(self, items: list[object]) -> None:
        all_tags = set()
        for it in items:
            if isinstance(it, ResourceItem):
                all_tags.update(it.tags)

        if not all_tags:
            self._set_action_status("选中数据无可用标签")
            return

        dlg = TagInputDialog(parent=self)
        dlg.setWindowTitle("批量移除标签")
        dlg.label.setText("请输入要移除的标签名称:")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tag_to_remove = dlg.get_tag_name()
            if not tag_to_remove:
                return
            count = 0
            for it in items:
                if isinstance(it, ResourceItem):
                    if tag_to_remove in it.tags:
                        it.tags.remove(tag_to_remove)
                        count += 1
            if count > 0:
                self._refresh()
                self._set_action_status(f"已从 {count} 项数据移除标签 #{tag_to_remove}")

    # --- Integrity Verification ---

    def _verify_single_asset(self, asset: object) -> None:
        self.verify_assets([asset])

    def _verify_current_or_all_assets(self) -> None:
        if self._selected_assets:
            self.verify_assets(self._selected_assets)
        else:
            all_assets = [*self._resources, *self._artifacts]
            self.verify_assets(all_assets)

    def verify_assets(self, items: list[object]) -> None:
        if not items:
            self._set_action_status("没有可校验的数据资产")
            return

        worker = IntegrityWorker(items, project_root=self._preview_disk_project_root())
        self._verify_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_verify_finished),
                (worker.failed, self._on_verify_failed),
            ),
        )
        self._set_action_status(f"正在后台校验 {len(items)} 项数据资产完整性...")

    @Slot(object)
    def _on_verify_finished(self, report: IntegrityCheckReport) -> None:
        if report.checksum_updates:
            for res in self._resources:
                if res.id in report.checksum_updates:
                    res.checksum = report.checksum_updates[res.id]
        self._refresh()
        self._set_action_status(f"完整性校验完成: {report.summary_text}")

    @Slot(str)
    def _on_verify_failed(self, message: str) -> None:
        self._set_action_status(f"完整性校验失败: {message}")

    # --- Preview & Workspace ---

    def _handle_preview_settings_changed(self, settings) -> None:
        summary_changed = self._preview_controller.set_settings(settings)
        visualization_changed = self._visualization_controller.set_settings(settings)
        if not summary_changed and not visualization_changed:
            return
        if summary_changed:
            self._preview_controller.request(self._selected_asset)
        self._set_action_status("预览设置已应用")

    def _request_summary(self, asset: object | None) -> None:
        self._visualization_controller.invalidate()
        self._preview_controller.request(asset)

    def _request_selected_visualization(self) -> None:
        asset = self._selected_asset
        if not isinstance(asset, ResourceItem):
            self.reader_panel.show_visualization_error("当前数据不支持可视化预览")
            return
        self._visualization_controller.request(asset)

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
        self.project.resources.extend(report.added)
        # Register imported resources as catalog INPUT versions (RAW/EXTERNAL)
        # with the legacy bridge so downstream runs can resolve them. Best-effort:
        # the catalog seam must never break the import path. Each resource is
        # registered independently so one failure doesn't skip the rest.
        try:
            from paleo_workbench.catalog.lifecycle import register_resource_input

            for resource in report.added:
                try:
                    register_resource_input(resource)
                except Exception:
                    pass
        except Exception:
            pass
        self._refresh()
        self._set_import_status(report)

    def _set_action_status(self, text: str) -> None:
        self.data_toolbar.operation_status_label.setText(text)

    def _update_selection_action_state(self) -> None:
        has_resource = isinstance(self._selected_asset, ResourceItem)
        has_asset = self._selected_asset is not None or bool(self._selected_assets)
        self.rescan_btn.setEnabled(has_resource and not self._import_in_progress)
        self.remove_btn.setEnabled(has_asset)
        self.open_folder_btn.setEnabled(has_asset)
