from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from dataclasses import replace

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLineEdit, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from paleo_workbench.project.models import (
    ExportArtifact,
    ProjectDocument,
    ResourceItem,
)
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
from paleo_workbench.ui import tokens
from paleo_workbench.ui.data_lifecycle_controller import DataLifecycleController
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.asset_table_model import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.data_toolbar import DataToolbar
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    asset_view_from_object,
    enrich_view_from_catalog,
)
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.ui.pages.filter_index import CATEGORIES
from paleo_workbench.ui.pages.integrity_worker import IntegrityCheckReport
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
        # Business orchestration (catalog-aware lifecycle actions) lives in the
        # controller; the page keeps thin delegating methods for every name
        # callers (tests, context menu) invoke directly.
        self._lifecycle = DataLifecycleController(self)

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
        self.navigation_tree.category_changed.connect(self._on_navigation_category_changed)
        self.navigation_tree.filter_query_changed.connect(self.asset_table.set_filter_query)

        self.asset_table.selected_asset_changed.connect(self._set_selected_asset)
        self.asset_table.selected_assets_changed.connect(self._set_selected_assets)
        self.asset_table.selected_asset_changed.connect(self._update_inspector)
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

    def _shutdown_workers(self) -> bool:
        wait_ms = 5000 if "pytest" in sys.modules else 100
        preview_joined = self._preview_controller.shutdown(wait_ms)
        visualization_joined = self._visualization_controller.shutdown(wait_ms)
        import_joined = self._shutdown_import_jobs(wait_ms)
        verify_joined = self._verify_job.shutdown(wait_ms)
        joined = all(
            result is not False
            for result in (preview_joined, visualization_joined, import_joined, verify_joined)
        )
        # Do not tear down active-engine widgets if a project switch is about
        # to be rejected because a cooperative job did not stop.
        if joined:
            self.reader_panel.release_engine_widgets()
        return joined

    def _shutdown_import_jobs(self, wait_ms: int = 5_000) -> bool:
        joined = self._import_job.shutdown(wait_ms)
        self._set_import_running(False)
        return joined

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
        self.navigation_tree.set_trash_count(len(self._trashed_companions()))
        display_resources = list(self._resources)
        if self._trash_view_active():
            display_resources.extend(self._trashed_companions())
        self.asset_table.update_assets(display_resources, self._artifacts)
        self._update_selection_action_state()
        self._sync_visualization_button()
        self._emit_data_context()

    def _refresh(self) -> None:
        self.update_state(
            dashboard_state(self.project),
            self.project.resources,
            self.project.export_artifacts,
        )

    def _trash_view_active(self) -> bool:
        """True when the navigation tree's 回收站 filter is active."""
        try:
            query = self.navigation_tree.current_filter_query()
        except Exception:
            return False
        return getattr(query, "node_type", "") == "trash"

    def _on_navigation_category_changed(self, category: str) -> None:
        self.asset_table.set_category(category)
        if category in ("回收站", "trash"):
            # Entering the trash view must surface trashed catalog assets
            # (they are not part of project.resources).
            self._refresh()

    def _trashed_companions(self) -> list[ResourceItem]:
        """Reconstruct legacy ResourceItem companions for trashed catalog
        assets so the 回收站 view can list and restore them."""
        return self._lifecycle.trashed_companions()

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
        """移出项目 (orchestration in DataLifecycleController)."""
        return self._lifecycle.remove_assets(items)

    def restore_selected_asset(self) -> bool:
        """还原: restore a trashed catalog asset (orchestration in controller)."""
        return self._lifecycle.restore_selected_asset()

    def rescan_selected_asset(self) -> bool:
        return self._lifecycle.rescan_selected_asset()

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
        """Create a derived data copy from a locked RAW asset (controller)."""
        self._lifecycle.create_derived_copy(asset)

    def _create_derived_via_catalog(
        self,
        asset: ResourceItem,
        *,
        service=None,
        ref=None,
    ) -> ResourceItem | None:
        """Create the DERIVED version through Core; None when not resolvable.

        Thin delegator — the orchestration lives in the lifecycle controller
        (tests pin this method name on the page).
        """
        return self._lifecycle.create_derived_via_catalog(asset, service=service, ref=ref)

    def _materialize_asset(self, asset: object) -> None:
        """纳管至项目 (orchestration in DataLifecycleController)."""
        self._lifecycle.materialize_asset(asset)

    # --- working copies / new versions ---------------------------------------

    def _new_version_from_asset(self, asset: object) -> None:
        """新建版本 / 工作副本 (orchestration in DataLifecycleController)."""
        self._lifecycle.new_version_from_asset(asset)

    # --- promote --------------------------------------------------------------

    def _promote_asset(self, asset: object) -> None:
        """提升为正式数据 (orchestration in DataLifecycleController)."""
        self._lifecycle.promote_asset(asset)

    # --- export / delivery ----------------------------------------------------

    def _deliver_asset(self, asset: object) -> None:
        """导出 / 交付 (orchestration in DataLifecycleController)."""
        self._lifecycle.deliver_asset(asset)

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
            # §8.2: derived requires an active catalog; without a bridge the
            # action is disabled with a clear tooltip (never a RAW-path alias).
            _svc, derived_ref = self._catalog_bridge(first) if isinstance(first, ResourceItem) else (None, None)
            if derived_ref is None:
                create_derived_act.setEnabled(False)
                create_derived_act.setToolTip("创建派生副本需要活动数据目录")
            else:
                create_derived_act.triggered.connect(lambda: self._create_derived_copy(first))

        new_version_act = menu.find_action("ctx_new_version")
        if new_version_act:
            _svc, nv_ref = self._catalog_bridge(first) if isinstance(first, ResourceItem) else (None, None)
            if nv_ref is None:
                new_version_act.setEnabled(False)
                new_version_act.setToolTip("新建版本需要活动数据目录（数据未桥接）")
            else:
                new_version_act.triggered.connect(lambda: self._new_version_from_asset(first))

        promote_act = menu.find_action("ctx_promote")
        if promote_act:
            _svc, prom_ref = self._catalog_bridge(first) if isinstance(first, ResourceItem) else (None, None)
            if prom_ref is None:
                promote_act.setEnabled(False)
                promote_act.setToolTip("提升为正式数据需要活动数据目录（数据未桥接）")
            else:
                promote_act.triggered.connect(lambda: self._promote_asset(first))

        export_open_act = menu.find_action("ctx_export_open")
        if export_open_act:
            export_open_act.triggered.connect(lambda: self._deliver_asset(first))

        restore_act = menu.find_action("ctx_restore")
        if restore_act:
            restore_act.triggered.connect(self.restore_selected_asset)

        verify_act = menu.find_action("ctx_verify")
        if verify_act:
            verify_act.triggered.connect(lambda: self._verify_single_asset(first))

        add_tag_act = menu.find_action("ctx_add_tag")
        if add_tag_act:
            add_tag_act.triggered.connect(lambda: self._prompt_add_tag_to_assets([first]))

        # 纳管至项目: only actionable when the asset is bridged to an unmanaged
        # (external) catalog version; otherwise it stays disabled.
        materialize_act = menu.find_action("ctx_materialize")
        if materialize_act and isinstance(first, ResourceItem):
            _svc, mat_ref = self._catalog_bridge(first)
            if mat_ref is not None and mat_ref.external:
                materialize_act.setEnabled(True)
                materialize_act.setToolTip("将外部文件复制为受管 RAW 快照 (不可变)")
                materialize_act.triggered.connect(lambda: self._materialize_asset(first))

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
        # A fresh menu is built per right-click; schedule its teardown so the
        # parented menu/actions/QShortcuts don't accumulate for the session.
        menu.deleteLater()

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
        asset = self._unwrap_asset(self._selected_asset)
        if not isinstance(asset, ResourceItem):
            return
        old_type = asset.type
        old_tags = list(asset.tags or [])
        asset.type = new_type
        role = ROLE_BY_TYPE.get(new_type)
        asset.artifact_role = role
        other = [t for t in (asset.tags or []) if t not in ROLE_BY_TYPE.values()]
        asset.tags = ([role] if role else []) + other
        # Mirror the role-tag rewrite into the catalog (best-effort).
        for tag in old_tags:
            if tag not in asset.tags:
                self._mirror_tag_to_catalog(asset, tag, add=False)
        for tag in asset.tags:
            if tag not in old_tags:
                self._mirror_tag_to_catalog(asset, tag, add=True)
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
            self._update_inspector(first)
            self._request_summary(first)
            self._update_selection_action_state()
            self._sync_visualization_button()
            self._emit_data_context()

    def _update_inspector(self, asset: object | None) -> None:
        """Build the inspector AssetView, enriched from the catalog when the
        asset is bridged (legacy plain view otherwise)."""
        if asset is None:
            self.inspector_panel.update_asset(None)
            return
        view = asset_view_from_object(asset)
        view = self._enrich_view_from_catalog(view)
        self.inspector_panel.update_asset(view)

    def _enrich_view_from_catalog(self, view: AssetView) -> AssetView:
        resource = view.raw_asset
        service, ref = self._catalog_bridge(resource)
        if service is None or ref is None:
            return view
        try:
            return enrich_view_from_catalog(view, service, ref.asset_id)
        except Exception:
            # Enrichment is best-effort; the plain legacy view still renders.
            return view

    # --- Catalog bridge (Core DataCatalogService wiring) ---

    @staticmethod
    def _unwrap_asset(asset: object) -> object:
        """Unwrap an enriched ``AssetView`` back to its underlying asset."""
        if isinstance(asset, AssetView) and asset.raw_asset is not None:
            return asset.raw_asset
        return asset

    def _catalog_service(self):
        """The active Core DataCatalogService, or None (no project catalog)."""
        return self._lifecycle.catalog_service()

    def _catalog_bridge(self, resource: object):
        """Resolve a legacy ResourceItem to ``(service, DataVersionRef)``.

        Returns ``(None, None)`` when no catalog is wired or the resource is
        not bridged (migrated projections have asset id == resource id).
        """
        return self._lifecycle.catalog_bridge(resource)

    def _mirror_tag_to_catalog(self, resource: object, tag_name: str, *, add: bool) -> None:
        """Mirror a legacy tag change into the catalog. Best-effort: catalog
        failures never break the UI tag action."""
        self._lifecycle.mirror_tag_to_catalog(resource, tag_name, add=add)

    # --- Tag Operations ---

    def _handle_tag_added(self, asset: object, tag_name: str) -> None:
        self._lifecycle.handle_tag_added(asset, tag_name)

    def _handle_tag_removed(self, asset: object, tag_name: str) -> None:
        self._lifecycle.handle_tag_removed(asset, tag_name)

    def _prompt_add_tag_to_assets(self, items: list[object]) -> None:
        self._lifecycle.prompt_add_tag_to_assets(items)

    def _prompt_remove_tag_from_assets(self, items: list[object]) -> None:
        self._lifecycle.prompt_remove_tag_from_assets(items)

    # --- Integrity Verification ---

    def _verify_single_asset(self, asset: object) -> None:
        self.verify_assets([asset])

    def _verify_current_or_all_assets(self) -> None:
        if self._selected_assets:
            self.verify_assets(self._selected_assets)
        else:
            all_assets = [*self._resources, *self._artifacts]
            self.verify_assets(all_assets)

    def _bridged_version_map(self, items: list[object]) -> tuple[object, dict[str, str]]:
        """Resolve catalog-bridged assets to ``(service, {asset_id: version_id})``.

        Cheap metadata lookup on the UI thread; hashing itself stays in the
        IntegrityWorker thread. ``(None, {})`` when no catalog is wired.
        """
        return self._lifecycle.bridged_version_map(items)

    def verify_assets(self, items: list[object]) -> None:
        self._lifecycle.verify_assets(items)

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
        # the catalog seam must never break the import path.
        self._lifecycle.register_imported_resources(report.added)
        self._refresh()
        self._set_import_status(report)

    def _set_action_status(self, text: str) -> None:
        self.data_toolbar.operation_status_label.setText(text)

    def _update_selection_action_state(self) -> None:
        has_resource = isinstance(self._selected_asset, ResourceItem)
        has_asset = self._selected_asset is not None or bool(self._selected_assets)
        selected_trashed = False
        if isinstance(self._selected_asset, ResourceItem):
            selected_trashed = bool(
                (self._selected_asset.parsed_summary or {}).get("catalog_trashed")
            )
        self.rescan_btn.setEnabled(
            has_resource and not selected_trashed and not self._import_in_progress
        )
        self.remove_btn.setEnabled(has_asset and not selected_trashed)
        self.open_folder_btn.setEnabled(has_asset)
