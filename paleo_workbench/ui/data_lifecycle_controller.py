"""DataLifecycleController — business orchestration for DataPage's lifecycle actions.

Extracted from ``paleo_workbench.ui.pages.data_page`` (pattern:
:mod:`paleo_workbench.ui.project_controller`). The page stays a thin view that
delegates the catalog-aware orchestration — remove/trash, rescan, derived
create via catalog, materialize, verify, tag mirror, promote, export/delivery —
to this controller.

Catalog resolution is per-call (never cached across project switches): every
operation resolves the active catalog / bridge fresh, exactly as the original
page did.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.project.models import ExportArtifact, ResourceItem, _now_iso
from paleo_workbench.project.paths import relativize_path, resolve_project_path
from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.ui.pages.data_view_models import AssetView
from paleo_workbench.ui.pages.integrity_worker import IntegrityWorker
from paleo_workbench.ui.pages.tag_widgets import TagInputDialog


def unwrap_asset(asset: object) -> object:
    """Unwrap an enriched ``AssetView`` back to its underlying asset."""
    if isinstance(asset, AssetView) and asset.raw_asset is not None:
        return asset.raw_asset
    return asset


class _NewVersionDialog(QDialog):
    """提交新版本 dialog: stage select + version name for a working copy."""

    def __init__(self, parent=None, *, asset_name: str = "", default_stage: str = "derived"):
        super().__init__(parent)
        self.setWindowTitle(f"提交新版本 — {asset_name}")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("目标阶段 (Stage):"))
        self.stage_combo = QComboBox(self)
        for label, value in (
            ("派生数据 (DERIVED)", "derived"),
            ("中间结果 (INTERMEDIATE)", "intermediate"),
            ("输出成果 (OUTPUT)", "output"),
        ):
            self.stage_combo.addItem(label, value)
        if default_stage == "intermediate":
            self.stage_combo.setCurrentIndex(1)
        elif default_stage == "output":
            self.stage_combo.setCurrentIndex(2)
        layout.addWidget(self.stage_combo)

        layout.addWidget(QLabel("版本名称 (可选):"))
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("例如: 去毛刺滤波版")
        layout.addWidget(self.name_edit)

        buttons = QHBoxLayout()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("提交", self)
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def stage(self):
        from paleo_workbench.catalog import DataStage

        return DataStage(self.stage_combo.currentData())

    def version_name(self) -> str:
        return self.name_edit.text().strip() or None


class _PromoteDialog(QDialog):
    """提升为正式数据 dialog: target stage, reviewer, and note."""

    def __init__(self, parent=None, *, asset_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"提升为正式数据 — {asset_name}")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("目标阶段:"))
        self.stage_combo = QComboBox(self)
        self.stage_combo.addItem("输出成果 (OUTPUT)", "output")
        self.stage_combo.addItem("派生数据 (DERIVED)", "derived")
        self.stage_combo.addItem("中间结果 (INTERMEDIATE)", "intermediate")
        layout.addWidget(self.stage_combo)

        layout.addWidget(QLabel("审核人 (reviewed_by, 可选):"))
        self.reviewed_edit = QLineEdit(self)
        self.reviewed_edit.setPlaceholderText("例如: QC 工程师")
        layout.addWidget(self.reviewed_edit)

        layout.addWidget(QLabel("备注 (note, 可选):"))
        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("提升说明")
        layout.addWidget(self.note_edit)

        buttons = QHBoxLayout()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("提升", self)
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def stage(self):
        from paleo_workbench.catalog import DataStage

        return DataStage(self.stage_combo.currentData())

    def reviewed_by(self) -> str | None:
        return self.reviewed_edit.text().strip() or None

    def note(self) -> str | None:
        return self.note_edit.text().strip() or None


class _DeliveryDialog(QDialog):
    """导出 / 交付 dialog: destination path + delivery note."""

    def __init__(self, parent=None, *, asset_name: str = "", suggested_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"导出 / 交付 — {asset_name}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("交付文件路径:"))
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(suggested_path, self)
        path_row.addWidget(self.path_edit, 1)
        browse = QPushButton("浏览...", self)
        browse.clicked.connect(self._browse)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        layout.addWidget(QLabel("交付说明 (可选):"))
        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("交付给谁 / 用途")
        layout.addWidget(self.note_edit)

        buttons = QHBoxLayout()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("导出", self)
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(self, "选择交付位置", self.path_edit.text())
        if path:
            self.path_edit.setText(path)

    def output_path(self) -> Path:
        return Path(self.path_edit.text().strip())

    def note(self) -> str | None:
        return self.note_edit.text().strip() or None


class _CatalogActionWorker(QObject):
    """Run one heavy catalog payload action (copy + SHA) off the GUI thread.

    #931: 派生副本/纳管/新建版本/提升 used to execute the full payload copy
    on the GUI thread (400 MB measured 0.37-0.56 s freeze). Mirrors the
    import/rescan/delivery/export worker pattern: the closure runs on the
    OwnedWorkerJob thread; results return via queued signals.
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__(None)  # parentless: moveToThread must be able to relocate
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 — surfaced via failed signal
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DataLifecycleController:
    """Business orchestration for the Data Manager page (catalog-aware).

    Composed by :class:`paleo_workbench.ui.pages.data_page.DataPage`, which
    keeps thin delegating methods for every public/private name other code
    (tests, context menu) calls directly. The controller reads page state
    through ``self.page`` — the same pattern as ``ProjectController``.
    """

    def __init__(self, page) -> None:
        self.page = page
        # Import → catalog registration outcomes (E9): brief per-resource
        # failure descriptions from the last register_imported_resources call.
        self.last_registration_failures: list[str] = []
        # Bulk tag mirror outcome: True when the last bulk_apply_tag could not
        # mirror to the catalog (legacy side still applied).
        self.last_tag_mirror_failed: bool = False

    # ------------------------------------------------------------------ #
    # Catalog resolution (per-call, never cached across project switches)
    # ------------------------------------------------------------------ #

    def catalog_service(self):
        """The active Core DataCatalogService, or None (no project catalog)."""
        try:
            from paleo_workbench.catalog.runtime import get_catalog_service

            return get_catalog_service()
        except Exception:
            return None

    def catalog_bridge(self, resource: object):
        """Resolve a legacy ResourceItem to ``(service, DataVersionRef)``.

        Returns ``(None, None)`` when no catalog is wired or the resource is
        not bridged (migrated projections have asset id == resource id).
        """
        if not isinstance(resource, ResourceItem):
            return None, None
        try:
            from paleo_workbench.catalog.runtime import get_catalog

            catalog = get_catalog()
            if catalog is None:
                return None, None
            ref = catalog.resolve_legacy_resource(resource.id)
        except Exception:
            return None, None
        if ref is None:
            return None, None
        service = self.catalog_service()
        if service is None:
            return None, None
        return service, ref

    # ------------------------------------------------------------------ #
    # Catalog rows: batch enrichment + catalog-only asset surfacing
    # ------------------------------------------------------------------ #

    def _catalog_row_target(self, asset: object):
        """Resolve a table row to ``(service, asset_id, version_id, name)``.

        Covers both row shapes: bridged ResourceItems and catalog-only Core
        DataAsset rows. None when the row has no resolvable catalog version
        (no catalog wired, or a pure legacy item).
        """
        unwrapped = unwrap_asset(asset)
        if isinstance(unwrapped, ResourceItem):
            service, ref = self.catalog_bridge(unwrapped)
            if service is None or ref is None:
                return None
            return service, ref.asset_id, ref.version_id, unwrapped.name
        from paleo_workbench.catalog.models import DataAsset

        if isinstance(unwrapped, DataAsset) and unwrapped.current_version_id:
            service = self.catalog_service()
            if service is None:
                return None
            return service, unwrapped.id, unwrapped.current_version_id, unwrapped.name
        return None

    def catalog_enricher(self):
        """A ``view -> view`` enricher over the CURRENT catalog state, or None.

        One overview pass (per refresh) covers every table row: stage/version
        truth, integrity, tags, lineage status, governance values. Returns
        None when no catalog is active (legacy behavior).
        """
        service = self.catalog_service()
        if service is None:
            return None
        try:
            from paleo_workbench.ui.pages.data_view_models import make_catalog_enricher

            return make_catalog_enricher(service)
        except Exception:
            return None

    def catalog_only_rows(self, enricher=None) -> list:
        """Row objects for catalog assets WITHOUT a legacy companion.

        Factor-map grids, predictions, paleomaps, interpretations and QC
        outputs are registered by business modules as catalog versions with
        no ResourceItem — they used to be invisible in Data Manager. Returned
        as prebuilt AssetView rows (trashed assets excluded; the 回收站 view
        lists them via companions). Catalog OUTPUTs that already have an
        ExportArtifact row (registered exports) are excluded so the table
        never lists the same deliverable twice.
        """
        service = self.catalog_service()
        if service is None:
            return []
        try:
            from paleo_workbench.ui.pages.data_view_models import (
                asset_view_from_catalog_overview,
                catalog_row_overview,
            )

            if enricher is not None and getattr(enricher, "overview_map", None):
                overviews = enricher.overview_map
            else:
                overviews = catalog_row_overview(service)
        except Exception:
            return []
        legacy_ids = {r.id for r in self.page.project.resources}
        # Export artifacts render their own rows AND carry their registered
        # catalog version id — drop those catalog assets from the extra rows.
        artifact_version_ids = {
            a.catalog_version_id
            for a in self.page.project.export_artifacts
            if getattr(a, "catalog_version_id", None)
        }
        version_to_asset = getattr(enricher, "version_to_asset", None) or {}
        artifact_asset_ids = {
            version_to_asset[vid] for vid in artifact_version_ids if vid in version_to_asset
        }
        project_root = self.page._preview_disk_project_root()
        rows = []
        for asset_id, overview in overviews.items():
            if overview.trashed:
                continue
            if asset_id in legacy_ids or asset_id in artifact_asset_ids:
                continue
            if overview.legacy_resource_id and overview.legacy_resource_id in legacy_ids:
                continue
            try:
                rows.append(
                    asset_view_from_catalog_overview(overview, project_root=project_root)
                )
            except Exception:
                continue
        return rows

    def update_governance_metadata(self, asset_id: str, patch: dict) -> bool:
        """Persist a governance patch through the Core service (validated)."""
        service = self.catalog_service()
        if service is None:
            self.page._set_action_status("治理信息需要活动数据目录")
            return False
        try:
            service.update_asset_metadata(asset_id, patch)
        except Exception as exc:
            self.page._set_action_status(f"治理信息保存失败: {exc}")
            return False
        self.page._refresh()
        self.page._update_inspector_for_current_selection()
        self.page._set_action_status("已保存治理信息")
        return True

    def resolve_catalog_asset_id(self, asset: object) -> str | None:
        """Catalog asset id for a table row (bridge / companion / direct).

        ExportArtifact rows resolve ONLY through their registered
        ``catalog_version_id`` — the artifact's own ``id`` (``artifact_…``)
        is NOT a catalog asset id and must never reach the catalog API.
        """
        unwrapped = unwrap_asset(asset)
        if isinstance(unwrapped, ResourceItem):
            _svc, ref = self.catalog_bridge(unwrapped)
            return ref.asset_id if ref is not None else None
        if isinstance(unwrapped, ExportArtifact):
            version_id = getattr(unwrapped, "catalog_version_id", None)
            if not version_id:
                return None
            service = self.catalog_service()
            if service is None:
                return None
            try:
                return service.get_version(version_id).asset_id
            except Exception:
                return None
        from paleo_workbench.catalog.models import DataAsset

        if isinstance(unwrapped, DataAsset):
            return unwrapped.id
        # Enriched catalog-only views carry the catalog asset id directly.
        return getattr(unwrapped, "id", None)

    # ------------------------------------------------------------------ #
    # Remove / trash / restore / rescan
    # ------------------------------------------------------------------ #

    def remove_assets(self, items: list[object]) -> bool:
        """移出项目.

        Catalog-bridged managed assets are TRASHED in the catalog first
        (tombstone + payload moved to ``trash/``), so the asset disappears from
        the active view WITHOUT leaving a ghost catalog asset behind. Pure
        legacy (unbridged) items keep the legacy slice behavior. A catalog
        trash failure aborts the removal (never a ghost).
        """
        page = self.page
        removed_count = 0
        trashed_count = 0
        target_ids = {getattr(it, "id", None) for it in items if getattr(it, "id", None)}
        domain_asset_ids = {str(item_id) for item_id in target_ids if item_id}

        # Catalog-only rows (no legacy companion) trash directly in the
        # catalog. They surface as AssetView rows whose raw_asset is a Core
        # DataAsset (unwrap_asset resolves to it).
        service = self.catalog_service()
        if service is not None:
            from paleo_workbench.catalog.models import DataAsset as _DataAsset

            for item in items:
                unwrapped = unwrap_asset(item)
                if not isinstance(unwrapped, _DataAsset):
                    continue
                try:
                    service.trash_asset(unwrapped.id, reason="移出项目")
                    trashed_count += 1
                    domain_asset_ids.add(str(unwrapped.id))
                    target_ids.discard(unwrapped.id)
                except Exception as exc:
                    page._set_action_status(f"移入回收站失败，未移除: {exc}")
                    page._refresh()
                    return False

        for item in items:
            resource = unwrap_asset(item)
            if not isinstance(resource, ResourceItem):
                continue
            service, ref = self.catalog_bridge(resource)
            if service is None or ref is None:
                continue
            try:
                service.trash_asset(ref.asset_id, reason="移出项目")
                trashed_count += 1
                domain_asset_ids.add(str(ref.asset_id))
            except Exception as exc:
                # Never leave a ghost: abort the whole removal visibly.
                page._set_action_status(f"移入回收站失败，未移除: {exc}")
                page._refresh()
                return False

        before_res = len(page.project.resources)
        page.project.resources[:] = [
            r for r in page.project.resources if r.id not in target_ids
        ]
        removed_count += before_res - len(page.project.resources)

        before_art = len(page.project.export_artifacts)
        page.project.export_artifacts[:] = [
            a for a in page.project.export_artifacts if a.id not in target_ids
        ]
        removed_count += before_art - len(page.project.export_artifacts)

        if removed_count > 0 or trashed_count > 0:
            from paleo_workbench.project.domain import (
                remove_asset_links_and_prune_reference_wells,
            )

            removed_links, removed_wells = remove_asset_links_and_prune_reference_wells(
                page.project,
                domain_asset_ids,
            )
            page._set_selected_asset(None)
            if removed_links or removed_wells:
                page.refresh_domain_views()
            else:
                page._refresh()
            if trashed_count:
                page._set_action_status(f"已移至回收站 ({trashed_count} 项)")
            else:
                page._set_action_status(f"已移出项目 ({removed_count} 项)")
            return True
        return False

    def restore_selected_asset(self) -> bool:
        """还原: restore a trashed catalog asset (payload back to its stage
        location) and re-surface its legacy ResourceItem companion."""
        page = self.page
        item = page._selected_asset
        resource = unwrap_asset(item)
        if not isinstance(resource, ResourceItem):
            page._set_action_status("请选择回收站中的数据项")
            return False
        service = self.catalog_service()
        if service is None:
            page._set_action_status("该回收站项目无目录关联，无法还原")
            return False
        # Trashed assets have no current version, so the legacy bridge cannot
        # resolve them; the companion records the catalog asset id directly.
        asset_id = (resource.parsed_summary or {}).get("catalog_asset_id")
        if asset_id is None:
            _svc, ref = self.catalog_bridge(resource)
            if ref is None:
                page._set_action_status("该回收站项目无目录关联，无法还原")
                return False
            asset_id = ref.asset_id
        try:
            asset = service.restore_asset(asset_id)
        except Exception as exc:
            page._set_action_status(f"还原失败: {exc}")
            return False
        restored = self.resource_from_catalog_asset(service, asset)
        if restored is not None:
            existing = {r.id for r in page.project.resources}
            if restored.id not in existing:
                page.project.resources.append(restored)
        page._set_selected_asset(None)
        page._refresh()
        page._set_action_status("已从回收站还原")
        return True

    def prepare_rescan(self) -> tuple[str, object, Path, Path | None]:
        """Validate + resolve the rescan target (GUI-thread-cheap).

        Returns ``(status, resource, path, project_path)`` with status one of
        ``"ok"``, ``"missing"`` (already applied + reported) or ``"invalid"``.
        The heavy directory scan itself runs on a worker (#379).
        """
        page = self.page
        if not isinstance(page._selected_asset, ResourceItem):
            page._set_action_status("请选择一个项目资源")
            return "invalid", None, Path(), None
        resource = page._selected_asset
        path = page._resolve_resource_path(resource)
        # Unprobeable paths (over-long, EACCES) report as missing instead of
        # raising out of the slot — same policy as the data-page view builder
        # (#882/#891).
        try:
            path_exists = path.exists()
        except OSError:
            path_exists = False
        if not path_exists:
            resource.status = "missing"
            if resource.parsed_summary is None:
                resource.parsed_summary = {}
            resource.parsed_summary["preview_warning"] = "文件不存在"
            page._refresh()
            page._request_summary(resource)
            page._set_action_status("文件不存在")
            return "missing", resource, path, page._project_file_for_io()
        return "ok", resource, path, page._project_file_for_io()

    def run_rescan(self, folder: Path, project_path: Path | None) -> list:
        """Scan *folder* (worker thread): rglob + per-file checksums."""
        return scan_resources(folder, project_path=project_path)

    def find_rescan_match(
        self, scanned: list, path_resolved: Path, project_path: Path | None
    ) -> object | None:
        """Locate the scanned item corresponding to the rescan target."""
        for item in scanned:
            try:
                item_path = Path(item.path)
                if not item_path.is_absolute() and project_path is not None:
                    item_path = Path(resolve_project_path(str(item.path), project_path))
                if item_path.resolve() == path_resolved:
                    return item
            except OSError:
                continue
        return None

    def apply_rescan_result(self, resource: ResourceItem, updated) -> bool:
        """Apply the scanned item onto the resource and refresh the UI."""
        page = self.page
        if updated is None:
            page._set_action_status("重新扫描未找到文件")
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

        page._refresh()
        page._request_summary(resource)
        page._set_action_status("已重新扫描")
        return True

    def rescan_selected_asset(self) -> bool:
        """Synchronous rescan (direct callers/tests); the page uses the
        worker variant that splits prepare/scan/apply (#379)."""
        status, resource, path, project_path = self.prepare_rescan()
        if status != "ok":
            return status == "missing"
        scanned = self.run_rescan(path.parent, project_path)
        updated = self.find_rescan_match(scanned, path.resolve(), project_path)
        return self.apply_rescan_result(resource, updated)

    # ------------------------------------------------------------------ #
    # Derived copy via catalog
    # ------------------------------------------------------------------ #

    def _run_catalog_action(self, label: str, fn, on_result, on_fail=None) -> None:
        """Run heavy catalog *fn* on the copy worker; *on_result* back on GUI.

        #931: shared off-thread runner for the payload-copy actions. The
        status line keeps the user informed; failures surface via *on_fail*
        (default: status line), never half-states. Concurrent invocations are
        refused while running.
        """
        page = self.page
        job = getattr(page, "_catalog_copy_job", None)
        if job is None:
            # Defensive: pages constructed before the job existed.
            on_result(fn())
            return
        if job.is_running:
            page._set_action_status(f"{label}：上一个数据操作仍在进行，请稍候…")
            return

        def _on_fail(message: str) -> None:
            if on_fail is not None:
                on_fail(message)
            else:
                page._set_action_status(f"{label}失败: {message}")

        worker = _CatalogActionWorker(fn)
        job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, on_result),
                (worker.failed, _on_fail),
            ),
        )
        page._set_action_status(f"{label}中…（大数据可能需要数秒）")

    def create_derived_copy(self, asset: object) -> None:
        """Create a derived data copy from a locked RAW asset.

        Requires an active catalog: the derived result is an immutable DERIVED
        DataVersion with lineage — never a RAW-path alias. Without a catalog the
        action fails visibly; catalog failures surface as errors, never a
        half-state. Catalog-only rows produce the derived asset directly (no
        legacy companion needed — it surfaces as its own catalog row).
        """
        page = self.page
        asset = unwrap_asset(asset)
        target = self._catalog_row_target(asset)
        if target is None:
            page._set_action_status("创建派生副本需要活动数据目录（数据未桥接）")
            return
        service, asset_id, version_id, name = target
        if isinstance(asset, ResourceItem):
            def _derived_companion(_service=service, _ref=SimpleNamespace(
                asset_id=asset_id, version_id=version_id
            )):
                return self.create_derived_via_catalog(asset, service=_service, ref=_ref)

            def _derived_done(derived_item) -> None:
                if derived_item is None:
                    page._set_action_status("创建派生副本失败: 无法解析源版本")
                    return
                page.project.resources.append(derived_item)
                page._refresh()
                page._set_selected_asset(derived_item)
                page._set_action_status(f"已从 🔒 RAW 建立派生副本: {derived_item.name}")

            self._run_catalog_action("创建派生副本", _derived_companion, _derived_done)
            return

        def _derived_version():
            source_version = service.get_version(version_id)
            payload = service.resolve_path(source_version)
            if not payload.is_file():
                return None
            return service.create_derived(
                source_path=payload,
                parent_version_ids=[source_version.id],
                name=f"{name}_derived",
                operation="derived_copy",
                generator="data_manager",
            )

        def _version_done(version) -> None:
            if version is None:
                page._set_action_status("创建派生副本失败: 无法解析源版本")
                return
            page._refresh()
            page._set_action_status(
                f"已建立派生副本: {name}_derived (v{version.version_number})"
            )

        self._run_catalog_action("创建派生副本", _derived_version, _version_done)

    def create_derived_via_catalog(
        self,
        asset: ResourceItem,
        *,
        service=None,
        ref=None,
    ) -> ResourceItem | None:
        """Create the DERIVED version through Core; None when the source payload
        is not resolvable. Catalog failures RAISE (the caller surfaces them).

        The returned legacy ResourceItem is a companion pointing at the
        Core-managed payload so legacy workflows still see the data.
        """
        if service is None or ref is None:
            service, ref = self.catalog_bridge(asset)
        if service is None or ref is None:
            return None
        source_version = service.get_version(ref.version_id)
        source_payload = service.resolve_path(source_version)
        if not source_payload.is_file():
            return None
        version = service.create_derived(
            source_path=source_payload,
            parent_version_ids=[source_version.id],
            name=f"{asset.name}_derived",
            operation="derived_copy",
            generator="data_manager",
        )
        managed_path = service.resolve_path(version)
        # Store project-relative when the payload is inside the project
        # dir (managed storage always is) so .paleo.json stays relocatable.
        stored_path, _outside = relativize_path(
            managed_path.as_posix(), service.project_path
        )
        return ResourceItem(
            name=f"{asset.name}_derived",
            path=stored_path,
            type=asset.type,
            format=asset.format,
            crs=asset.crs,
            status=asset.status,
            tags=["派生", *asset.tags],
            source=f"derived from {asset.name}",
            parsed_summary={
                "derived_from_id": asset.id,
                "derived_from_name": asset.name,
                "catalog_asset_id": version.asset_id,
                "catalog_version_id": version.id,
                **asset.parsed_summary,
            },
            checksum=version.sha256,
            external=False,
            artifact_role="derived",
        )

    # ------------------------------------------------------------------ #
    # Materialize external
    # ------------------------------------------------------------------ #

    def materialize_asset(self, asset: object) -> None:
        """纳管至项目: promote an external (unmanaged) catalog version to a
        managed immutable RAW snapshot via the Core service."""
        page = self.page
        asset = unwrap_asset(asset)
        if not isinstance(asset, ResourceItem):
            page._set_action_status("仅支持纳管 ResourceItem 数据")
            return
        service, ref = self.catalog_bridge(asset)
        if service is None or ref is None:
            page._set_action_status("未连接数据目录，无法纳管")
            return
        if not ref.external:
            page._set_action_status("该数据已是受管数据")
            return
        # Provenance: record the materialize DataRun first so the service can
        # atomically attach the new snapshot as that run's output. Best-effort —
        # the materialize itself must succeed even if run booking fails.
        run_id = None
        try:
            external_path = service.resolve_path(service.get_version(ref.version_id))
            run = service.register_run(
                "materialize",
                input_version_ids=[ref.version_id],
                parameters={"source": external_path.as_posix()},
            )
            run_id = run.id
        except Exception:
            run_id = None

        def _materialize():
            version = service.materialize_external(ref.version_id, run_id=run_id)
            return version, service.resolve_path(version)

        def _materialize_done(result) -> None:
            version, managed_path = result
            stored_path, _outside = relativize_path(
                managed_path.as_posix(), service.project_path
            )
            asset.external = False
            asset.path = stored_path
            asset.checksum = version.sha256
            page._refresh()
            page._set_action_status(f"已纳管至项目: {asset.name}")

        def _materialize_fail(message: str) -> None:
            self._fail_booked_run(service, run_id)
            page._set_action_status(f"纳管失败: {message}")

        # Run the payload copy off the GUI thread (#931).
        self._run_catalog_action(
            "纳管", _materialize, _materialize_done, on_fail=_materialize_fail
        )

    # ------------------------------------------------------------------ #
    # Working copies / new versions / promote / delivery
    # ------------------------------------------------------------------ #

    def new_version_from_asset(self, asset: object) -> None:
        """新建版本 / 工作副本: create a mutable working copy of the current
        catalog version, reveal it for editing, then commit it as a new
        immutable version of the SAME asset."""
        page = self.page
        asset = unwrap_asset(asset)
        target = self._catalog_row_target(asset)
        if target is None:
            page._set_action_status("新建版本需要活动数据目录（数据未桥接）")
            return
        service, asset_id, version_id, name = target
        try:
            working_path = service.create_working_copy(version_id)
        except Exception as exc:
            page._set_action_status(f"创建工作副本失败: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(working_path.as_posix()))
        dlg = _NewVersionDialog(page, asset_name=name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            page._set_action_status(f"已创建可编辑工作副本（未提交）: {working_path}")
            return
        # Provenance: record the working-copy commit DataRun first so the
        # service can atomically attach the committed version as its output.
        # Best-effort — on booking failure the commit falls back to no run
        # (the commit itself must never fail because of bookkeeping).
        run_id = None
        try:
            run = service.register_run(
                "working_copy_commit",
                input_version_ids=[version_id],
                parameters={"stage": dlg.stage().value, "name": dlg.version_name()},
            )
            run_id = run.id
        except Exception:
            run_id = None

        def _commit():
            return service.commit_working_copy(
                working_path,
                asset_id=asset_id,
                name=dlg.version_name(),
                stage=dlg.stage(),
                run_id=run_id,
            )

        def _commit_done(version) -> None:
            page._refresh()
            page._set_action_status(
                f"已提交新版本: {version.id} (v{version.version_number}, {version.stage.value})"
            )

        def _commit_fail(message: str) -> None:
            self._fail_booked_run(service, run_id)
            page._set_action_status(f"提交新版本失败: {message}")

        # Commit (payload copy + SHA) off the GUI thread (#931).
        self._run_catalog_action("提交新版本", _commit, _commit_done, on_fail=_commit_fail)

    def promote_asset(self, asset: object) -> None:
        """提升为正式数据: copy the current version to a new immutable OUTPUT
        version (promote DataRun + current_version_id advance)."""
        page = self.page
        asset = unwrap_asset(asset)
        target = self._catalog_row_target(asset)
        if target is None:
            page._set_action_status("提升为正式数据需要活动数据目录（数据未桥接）")
            return
        _service, _asset_id, version_id, name = target
        dlg = _PromoteDialog(page, asset_name=name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        service = self.catalog_service()

        def _promote():
            return service.promote_version(
                version_id,
                to_stage=dlg.stage(),
                reviewed_by=dlg.reviewed_by(),
                note=dlg.note(),
            )

        def _promote_done(version) -> None:
            page._refresh()
            page._set_action_status(
                f"已提升为正式数据: {version.id} (v{version.version_number})"
            )

        # Promote copies the payload to a new immutable version (#931).
        self._run_catalog_action("提升为正式数据", _promote, _promote_done)

    def prepare_delivery(self, asset: object):
        """Resolve the payload source and ask for a destination (GUI thread).

        Returns ``(source_path, destination, service, ref)`` or None after
        reporting an error/cancel status.  The payload copy + checksum itself
        runs on a worker (#379).
        """
        page = self.page
        asset = unwrap_asset(asset)
        service, ref = self.catalog_bridge(asset) if isinstance(asset, ResourceItem) else (None, None)
        source_path: Path | None = None
        if isinstance(asset, ResourceItem):
            source_path = page._resolve_resource_path(asset)
            if service is not None and ref is not None:
                # Prefer the immutable managed snapshot the catalog version
                # references: the legacy original may have drifted since
                # import, and the delivery DataRun claims it is version X's
                # bytes (#835). Falls back to the legacy path only when the
                # managed payload is unavailable.
                try:
                    managed = service.resolve_path(service.get_version(ref.version_id))
                    if managed.is_file():
                        source_path = managed
                except Exception:
                    pass
            if not source_path.is_file() and service is not None and ref is not None:
                try:
                    source_path = service.resolve_path(service.get_version(ref.version_id))
                except Exception:
                    source_path = None
        elif isinstance(asset, ExportArtifact):
            # record_export stores project-RELATIVE output paths; resolve
            # against the project dir (never process CWD — review finding I1),
            # then fall back to the managed OUTPUT payload when available.
            rel = Path(asset.output_path)
            if not rel.is_absolute():
                try:
                    from paleo_workbench.project.paths import resolve_project_path

                    source_path = Path(
                        resolve_project_path(str(rel), page._project_file_for_io())
                    )
                except Exception:
                    source_path = rel
            else:
                source_path = rel
            if not source_path.is_file() and service is not None and ref is not None:
                try:
                    source_path = service.resolve_path(service.get_version(ref.version_id))
                except Exception:
                    source_path = None
        elif not isinstance(asset, ExportArtifact):
            # Catalog-only rows (Core DataAsset): resolve the current
            # version's managed payload through the catalog.
            service = self.catalog_service()
            version_id = getattr(asset, "current_version_id", None)
            if service is not None and version_id:
                try:
                    version = service.get_version(version_id)
                    source_path = service.resolve_path(version)
                    ref = SimpleNamespace(asset_id=asset.id, version_id=version.id)
                except Exception:
                    source_path = None
        if source_path is None or not source_path.is_file():
            page._set_action_status("导出 / 交付失败: 源文件不存在")
            return None
        suggested = str(default_export_dir(page._project_file_for_io()) / source_path.name)
        dlg = _DeliveryDialog(page, asset_name=getattr(asset, "name", source_path.name), suggested_path=suggested)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        destination = dlg.output_path()
        if not str(destination).strip():
            page._set_action_status("导出 / 交付已取消")
            return None
        return source_path, Path(destination), service, ref

    def run_delivery_copy(self, source_path: Path, destination: Path) -> str:
        """Copy the payload and checksum the destination (worker thread)."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        # copyfile (not copy2): managed payloads are stored with the owner
        # write bit cleared as an in-repo accident guard, and that guard is
        # not a delivery attribute — the recipient must be able to open and
        # save the deliverable (#835). Restore a writable mode explicitly.
        shutil.copyfile(source_path, destination)
        try:
            destination.chmod(0o644)
        except OSError:
            pass
        return sha256_file(destination)

    def finish_delivery(
        self,
        asset: object,
        service,
        ref,
        source_path: Path,
        destination: Path,
        checksum: str,
    ) -> None:
        """Record the delivery DataRun and report status (GUI thread)."""
        page = self.page
        recorded = False
        try:
            if service is not None and ref is not None:
                service.register_run(
                    "delivery",
                    input_version_ids=[ref.version_id],
                    parameters={
                        "source_version_id": ref.version_id,
                        "exported_path": destination.as_posix(),
                        "checksum": checksum,
                        "timestamp": _now_iso(),
                        "format": source_path.suffix.lstrip("."),
                        "delivery_status": "exported",
                    },
                )
                recorded = True
            elif (
                isinstance(asset, ExportArtifact)
                and asset.catalog_version_id
                and (artifact_service := self.catalog_service()) is not None
                and self._version_exists(artifact_service, asset.catalog_version_id)
            ):
                artifact_service.register_run(
                    "delivery",
                    input_version_ids=[asset.catalog_version_id],
                    parameters={
                        "source_version_id": asset.catalog_version_id,
                        "exported_path": destination.as_posix(),
                        "checksum": checksum,
                        "timestamp": _now_iso(),
                        "format": source_path.suffix.lstrip("."),
                        "delivery_status": "exported",
                    },
                )
                recorded = True
        except Exception:
            recorded = False
        page._set_action_status(
            f"已导出 / 交付: {destination.name} ({'已记录交付元数据' if recorded else '未记录交付元数据'})"
        )

    def deliver_asset(self, asset: object) -> None:
        """导出 / 交付 (synchronous composition for direct callers/tests; the
        page uses the worker variant that splits prepare/copy/finish, #379)."""
        prepared = self.prepare_delivery(asset)
        if prepared is None:
            return
        source_path, destination, service, ref = prepared
        try:
            checksum = self.run_delivery_copy(source_path, destination)
        except Exception as exc:
            self.page._set_action_status(f"导出 / 交付失败: {exc}")
            return
        self.finish_delivery(asset, service, ref, source_path, destination, checksum)

    # ------------------------------------------------------------------ #
    # Tag mirroring
    # ------------------------------------------------------------------ #

    def mirror_tag_to_catalog(self, resource: object, tag_name: str, *, add: bool) -> None:
        """Mirror a legacy tag change into the catalog. Best-effort: catalog
        failures never break the UI tag action."""
        service, ref = self.catalog_bridge(unwrap_asset(resource))
        if service is None or ref is None:
            return
        try:
            if add:
                service.add_tag(tag_name, asset_id=ref.asset_id)
            else:
                service.remove_tag(tag_name, asset_id=ref.asset_id)
        except Exception:
            pass

    def handle_tag_added(self, asset: object, tag_name: str) -> None:
        page = self.page
        asset = unwrap_asset(asset)
        from paleo_workbench.catalog.models import DataAsset

        if isinstance(asset, DataAsset):
            # Catalog-only row: the catalog is the only tag home (no legacy
            # ResourceItem to mirror onto).
            service = self.catalog_service()
            if service is not None:
                try:
                    service.add_tag(tag_name, asset_id=asset.id)
                    page._refresh()
                    page._set_action_status(f"已添加标签 #{tag_name}")
                except Exception as exc:
                    page._set_action_status(f"添加标签失败: {exc}")
            return
        if isinstance(asset, ResourceItem):
            if tag_name not in asset.tags:
                asset.tags.append(tag_name)
                self.mirror_tag_to_catalog(asset, tag_name, add=True)
                page._refresh()
                page._set_action_status(f"已添加标签 #{tag_name}")

    def handle_tag_removed(self, asset: object, tag_name: str) -> None:
        page = self.page
        asset = unwrap_asset(asset)
        from paleo_workbench.catalog.models import DataAsset

        if isinstance(asset, DataAsset):
            service = self.catalog_service()
            if service is not None:
                try:
                    service.remove_tag(tag_name, asset_id=asset.id)
                    page._refresh()
                    page._set_action_status(f"已移除标签 #{tag_name}")
                except Exception as exc:
                    page._set_action_status(f"移除标签失败: {exc}")
            return
        if isinstance(asset, ResourceItem):
            if tag_name in asset.tags:
                asset.tags.remove(tag_name)
                self.mirror_tag_to_catalog(asset, tag_name, add=False)
                page._refresh()
                page._set_action_status(f"已移除标签 #{tag_name}")

    @staticmethod
    def _version_exists(service, version_id: str) -> bool:
        """True when *version_id* still resolves (not purged); keeps delivery
        runs free of dangling inputs, matching the bridge-gated branch."""
        try:
            service.get_version(version_id)
            return True
        except Exception:
            return False

    @staticmethod
    def _fail_booked_run(service, run_id: str | None) -> None:
        """Mark a pre-booked run failed when the operation it describes fails.

        ``register_run`` books runs as ``completed``; without this a failed
        materialize/commit would leave phantom completed provenance behind."""
        if service is None or run_id is None:
            return
        try:
            service.update_run_status(run_id, "failed")
        except Exception:
            pass

    def bulk_apply_tag(self, items, tag_name: str, *, add: bool) -> int:
        """Batch add/remove one tag over many ResourceItems. Legacy ResourceItem.tags
        updated per item; catalog side mirrored via service.bulk_add_tag/bulk_remove_tag
        in ONE canonical write. Returns number of items changed; a failed catalog
        mirror is recorded on ``last_tag_mirror_failed`` (never blocks legacy)."""
        resources = [
            res
            for res in (unwrap_asset(it) for it in items)
            if isinstance(res, ResourceItem)
        ]
        # Catalog mirror first (best-effort, ONE write): collect the bridged
        # catalog asset ids the same way mirror_tag_to_catalog resolves them.
        self.last_tag_mirror_failed = False
        service = self.catalog_service()
        asset_ids: list[str] = []
        if service is not None:
            for resource in resources:
                _svc, ref = self.catalog_bridge(resource)
                if ref is not None:
                    asset_ids.append(ref.asset_id)
        if asset_ids:
            try:
                if add:
                    service.bulk_add_tag(tag_name, asset_ids=asset_ids)
                else:
                    service.bulk_remove_tag(tag_name, asset_ids=asset_ids)
            except Exception:
                # Best-effort mirror: a catalog failure never breaks the
                # legacy tag action (same contract as mirror_tag_to_catalog),
                # but it must stay VISIBLE (logged + flag for the status bar).
                self.last_tag_mirror_failed = True
                logging.getLogger("paleo_workbench.catalog").warning(
                    "catalog tag mirror failed for #%s (%d assets)",
                    tag_name,
                    len(asset_ids),
                    exc_info=True,
                )
        # Legacy side: per-item update, count only actual changes.
        count = 0
        for resource in resources:
            if add:
                if tag_name not in resource.tags:
                    resource.tags.append(tag_name)
                    count += 1
            elif tag_name in resource.tags:
                resource.tags.remove(tag_name)
                count += 1
        return count

    def set_version_tag(self, version_id: str, tag_name: str, *, add: bool) -> bool:
        """Add/remove a Version Tag on a catalog version (best-effort; returns success)."""
        service = self.catalog_service()
        if service is None:
            return False
        try:
            if add:
                service.add_tag(tag_name, version_id=version_id)
            else:
                service.remove_tag(tag_name, version_id=version_id)
            return True
        except Exception:
            return False

    def prompt_add_tag_to_assets(self, items: list[object]) -> None:
        page = self.page
        dlg = TagInputDialog(parent=page)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tag = dlg.get_tag_name()
            if not new_tag:
                return
            count = self.bulk_apply_tag(items, new_tag, add=True)
            if count > 0:
                page._refresh()
                page._set_action_status(f"已为 {count} 项数据添加标签 #{new_tag}")

    def prompt_remove_tag_from_assets(self, items: list[object]) -> None:
        page = self.page
        all_tags = set()
        for it in items:
            it = unwrap_asset(it)
            if isinstance(it, ResourceItem):
                all_tags.update(it.tags)

        if not all_tags:
            page._set_action_status("选中数据无可用标签")
            return

        dlg = TagInputDialog(parent=page)
        dlg.setWindowTitle("批量移除标签")
        dlg.label.setText("请输入要移除的标签名称:")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tag_to_remove = dlg.get_tag_name()
            if not tag_to_remove:
                return
            count = self.bulk_apply_tag(items, tag_to_remove, add=False)
            if count > 0:
                page._refresh()
                page._set_action_status(f"已从 {count} 项数据移除标签 #{tag_to_remove}")

    # ------------------------------------------------------------------ #
    # Integrity verification
    # ------------------------------------------------------------------ #

    def bridged_version_map(self, items: list[object]) -> tuple[object, dict[str, str]]:
        """Resolve catalog-bridged assets to ``(service, {asset_id: version_id})``.

        Cheap metadata lookup on the UI thread; hashing itself stays in the
        IntegrityWorker thread. ``(None, {})`` when no catalog is wired.
        """
        service = self.catalog_service()
        if service is None:
            return None, {}
        bridged: dict[str, str] = {}
        for item in items:
            resource = unwrap_asset(item)
            _svc, ref = self.catalog_bridge(resource)
            if ref is not None and isinstance(resource, ResourceItem):
                # Keyed by legacy resource id — the worker resolves views by it.
                bridged[resource.id] = ref.version_id
        if not bridged:
            return None, {}
        return service, bridged

    def verify_assets(self, items: list[object]) -> None:
        page = self.page
        if not items:
            page._set_action_status("没有可校验的数据资产")
            return
        if page._verify_job.is_running:
            page._verify_job.cancel()
            page._set_action_status("正在取消校验...")
            return

        # Catalog-bridged assets are verified via the Core service (the
        # lifecycle authority); un-bridged assets keep the legacy path.
        service, bridged = self.bridged_version_map(items)
        worker = IntegrityWorker(
            items,
            project_root=page._preview_disk_project_root(),
            catalog_service=service,
            bridged_versions=bridged,
        )
        page._verify_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, page._on_verify_finished),
                (worker.failed, page._on_verify_failed),
            ),
            cancel=worker.cancel,
            # #937-10: bind the job to the current project so a completion from
            # a PREVIOUS project cannot mutate the new one (the sibling
            # import/export/delivery jobs all carry target=).
            target=page.project,
        )
        page.data_toolbar.set_verify_running(True)
        page._set_action_status(f"正在后台校验 {len(items)} 项数据资产完整性...")

    # ------------------------------------------------------------------ #
    # Trashed companions / resource reconstruction
    # ------------------------------------------------------------------ #

    def trashed_companions(self) -> list[ResourceItem]:
        """Reconstruct legacy ResourceItem companions for trashed catalog
        assets so the 回收站 view can list and restore them."""
        service = self.catalog_service()
        if service is None:
            return []
        try:
            assets = service.get_trashed_assets()
        except Exception:
            return []
        companions = []
        for asset in assets:
            item = self.resource_from_catalog_asset(service, asset, trashed=True)
            if item is not None:
                companions.append(item)
        return companions

    def resource_from_catalog_asset(
        self, service, asset, *, trashed: bool = False
    ) -> ResourceItem | None:
        """Build a legacy ResourceItem companion for a catalog asset (used to
        re-surface restored assets and to list trashed ones)."""
        try:
            version = (
                service.get_version(asset.current_version_id)
                if asset.current_version_id is not None
                else None
            )
            payload = service.resolve_path(version) if version is not None else None
            stored_path = asset.id
            if payload is not None:
                stored_path, _outside = relativize_path(
                    payload.as_posix(), service.project_path
                )
            summary = dict(asset.metadata or {})
            if trashed:
                summary["catalog_trashed"] = True
            summary["catalog_asset_id"] = asset.id
            if version is not None:
                summary["catalog_version_id"] = version.id
            tags = list((asset.metadata or {}).get("legacy_tags", []))
            if not tags:
                try:
                    tag_ids = service.document.asset_tags.get(asset.id, [])
                    by_id = {t.id: t for t in service.document.tags}
                    tags = [
                        by_id[tid].display_name or by_id[tid].name
                        for tid in tag_ids
                        if tid in by_id
                    ]
                except Exception:
                    tags = []
            return ResourceItem(
                id=asset.legacy_resource_id or asset.id,
                name=asset.name,
                path=stored_path,
                type=asset.type,
                format=version.format if version else "",
                checksum=version.sha256 if version else None,
                external=bool(version and not version.managed),
                artifact_role=(asset.metadata or {}).get("artifact_role")
                or ("output" if version and version.stage.value == "output" else "input"),
                tags=tags,
                status="indexed" if payload is not None and payload.is_file() else "missing",
                source=(asset.metadata or {}).get("source", "catalog"),
                parsed_summary=summary,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Import → catalog registration
    # ------------------------------------------------------------------ #

    def register_imported_resources(
        self, resources: list[ResourceItem]
    ) -> dict[str, str]:
        """Register imported resources as catalog INPUT versions (RAW/EXTERNAL)
        with the legacy bridge so downstream runs can resolve them. Best-effort:
        the catalog seam must never break the import path. Each resource is
        registered independently so one failure doesn't skip the rest.

        Failures are never silent: each one is logged and summarized on
        ``last_registration_failures`` (reset per call) so the import status
        surface can report how many registrations were lost.

        Returns the exact ``ResourceItem.id → DataAsset.id`` values produced by
        this registration pass.  A reused catalog asset may retain an older
        legacy bridge, so callers must not try to reconstruct this result from
        the catalog's one-to-one legacy index.
        """
        self.last_registration_failures = []
        registered_asset_ids: dict[str, str] = {}
        try:
            from paleo_workbench.catalog.lifecycle import register_resource_input
        except Exception as exc:
            self.last_registration_failures.append(
                f"catalog lifecycle unavailable: {exc}"
            )
            logging.getLogger(__name__).warning(
                "import catalog registration unavailable: %s", exc
            )
            return registered_asset_ids
        # Bulk path (audit #849-3): register every file inside ONE batch so
        # the canonical document is written (serialize + fsync) once, not once
        # per file (O(N²) bytes on large folders). Per-resource failures are
        # caught inside the batch so one bad file never discards the others;
        # a failed final flush restores the pre-batch document and is recorded
        # like any other registration failure (the import must never break).
        batch = None
        try:
            from paleo_workbench.catalog import get_catalog

            cat = get_catalog()
            if cat is not None:
                enter = getattr(cat, "batch_save", None)
                if callable(enter):
                    batch = enter()
                    batch.__enter__()
        except Exception as exc:
            batch = None
            logging.getLogger(__name__).warning(
                "import catalog batch unavailable; falling back per-file: %s", exc
            )
        try:
            for resource in resources:
                try:
                    ref = register_resource_input(resource)
                    if ref is not None:
                        registered_asset_ids[str(resource.id)] = str(ref.asset_id)
                except Exception as exc:
                    failure = f"{resource.name} ({resource.id}): {exc}"
                    self.last_registration_failures.append(failure)
                    logging.getLogger(__name__).warning(
                        "import catalog registration failed for %s: %s",
                        resource.id,
                        exc,
                    )
        finally:
            if batch is not None:
                try:
                    batch.__exit__(None, None, None)
                except Exception as exc:
                    registered_asset_ids.clear()
                    self.last_registration_failures.append(f"批提交失败: {exc}")
                    logging.getLogger(__name__).warning(
                        "import catalog batch commit failed: %s", exc
                    )
        return registered_asset_ids
