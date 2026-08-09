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

import shutil
from pathlib import Path

from PySide6.QtCore import QUrl
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


class DataLifecycleController:
    """Business orchestration for the Data Manager page (catalog-aware).

    Composed by :class:`paleo_workbench.ui.pages.data_page.DataPage`, which
    keeps thin delegating methods for every public/private name other code
    (tests, context menu) calls directly. The controller reads page state
    through ``self.page`` — the same pattern as ``ProjectController``.
    """

    def __init__(self, page) -> None:
        self.page = page

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
            page._set_selected_asset(None)
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

    def rescan_selected_asset(self) -> bool:
        page = self.page
        if not isinstance(page._selected_asset, ResourceItem):
            page._set_action_status("请选择一个项目资源")
            return False
        resource = page._selected_asset
        path = page._resolve_resource_path(resource)
        if not path.exists():
            resource.status = "missing"
            if resource.parsed_summary is None:
                resource.parsed_summary = {}
            resource.parsed_summary["preview_warning"] = "文件不存在"
            page._refresh()
            page._request_summary(resource)
            page._set_action_status("文件不存在")
            return True

        project_path = page._project_file_for_io()
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

    # ------------------------------------------------------------------ #
    # Derived copy via catalog
    # ------------------------------------------------------------------ #

    def create_derived_copy(self, asset: object) -> None:
        """Create a derived data copy from a locked RAW asset.

        Requires an active catalog: the derived result is an immutable DERIVED
        DataVersion with lineage — never a RAW-path alias. Without a catalog the
        action fails visibly; catalog failures surface as errors, never a
        half-state.
        """
        page = self.page
        asset = unwrap_asset(asset)
        if not isinstance(asset, ResourceItem):
            page._set_action_status("仅支持为 ResourceItem 数据创建派生副本")
            return

        service, ref = self.catalog_bridge(asset)
        if service is None or ref is None:
            page._set_action_status("创建派生副本需要活动数据目录（数据未桥接）")
            return
        try:
            derived_item = self.create_derived_via_catalog(asset, service=service, ref=ref)
        except Exception as exc:
            page._set_action_status(f"创建派生副本失败: {exc}")
            return
        if derived_item is None:
            page._set_action_status("创建派生副本失败: 无法解析源版本")
            return

        page.project.resources.append(derived_item)
        page._refresh()
        page._set_selected_asset(derived_item)
        page._set_action_status(f"已从 🔒 RAW 建立派生副本: {derived_item.name}")

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
        try:
            version = service.materialize_external(ref.version_id)
            managed_path = service.resolve_path(version)
        except Exception as exc:
            page._set_action_status(f"纳管失败: {exc}")
            return
        # Keep the legacy ResourceItem in sync with the new managed version.
        # Project-relative storage keeps .paleo.json relocatable.
        stored_path, _outside = relativize_path(
            managed_path.as_posix(), service.project_path
        )
        asset.external = False
        asset.path = stored_path
        asset.checksum = version.sha256
        page._refresh()
        page._set_action_status(f"已纳管至项目: {asset.name}")

    # ------------------------------------------------------------------ #
    # Working copies / new versions / promote / delivery
    # ------------------------------------------------------------------ #

    def new_version_from_asset(self, asset: object) -> None:
        """新建版本 / 工作副本: create a mutable working copy of the current
        catalog version, reveal it for editing, then commit it as a new
        immutable version of the SAME asset."""
        page = self.page
        asset = unwrap_asset(asset)
        if not isinstance(asset, ResourceItem):
            page._set_action_status("仅支持为资源数据创建新版本")
            return
        service, ref = self.catalog_bridge(asset)
        if service is None or ref is None:
            page._set_action_status("新建版本需要活动数据目录（数据未桥接）")
            return
        try:
            working_path = service.create_working_copy(ref.version_id)
        except Exception as exc:
            page._set_action_status(f"创建工作副本失败: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(working_path.as_posix()))
        dlg = _NewVersionDialog(page, asset_name=asset.name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            page._set_action_status(f"已创建可编辑工作副本（未提交）: {working_path}")
            return
        try:
            version = service.commit_working_copy(
                working_path,
                asset_id=ref.asset_id,
                name=dlg.version_name(),
                stage=dlg.stage(),
            )
        except Exception as exc:
            page._set_action_status(f"提交新版本失败: {exc}")
            return
        page._refresh()
        page._set_action_status(
            f"已提交新版本: {version.id} (v{version.version_number}, {version.stage.value})"
        )

    def promote_asset(self, asset: object) -> None:
        """提升为正式数据: copy the current version to a new immutable OUTPUT
        version (promote DataRun + current_version_id advance)."""
        page = self.page
        asset = unwrap_asset(asset)
        if not isinstance(asset, ResourceItem):
            page._set_action_status("仅支持为资源数据提升版本")
            return
        service, ref = self.catalog_bridge(asset)
        if service is None or ref is None:
            page._set_action_status("提升为正式数据需要活动数据目录（数据未桥接）")
            return
        dlg = _PromoteDialog(page, asset_name=asset.name)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            version = service.promote_version(
                ref.version_id,
                to_stage=dlg.stage(),
                reviewed_by=dlg.reviewed_by(),
                note=dlg.note(),
            )
        except Exception as exc:
            page._set_action_status(f"提升失败: {exc}")
            return
        page._refresh()
        page._set_action_status(f"已提升为正式数据: {version.id} (v{version.version_number})")

    def deliver_asset(self, asset: object) -> None:
        """导出 / 交付: copy the OUTPUT payload to a user-chosen destination and
        record delivery metadata as a ``delivery`` DataRun (source version,
        exported path, checksum, timestamp, format, delivery status)."""
        page = self.page
        asset = unwrap_asset(asset)
        service, ref = self.catalog_bridge(asset)
        source_path: Path | None = None
        if isinstance(asset, ResourceItem):
            source_path = page._resolve_resource_path(asset)
            if not source_path.is_file() and service is not None and ref is not None:
                try:
                    source_path = service.resolve_path(service.get_version(ref.version_id))
                except Exception:
                    source_path = None
        elif isinstance(asset, ExportArtifact):
            source_path = Path(asset.output_path)
        if source_path is None or not source_path.is_file():
            page._set_action_status("导出 / 交付失败: 源文件不存在")
            return
        suggested = str(default_export_dir(page._project_file_for_io()) / source_path.name)
        dlg = _DeliveryDialog(page, asset_name=getattr(asset, "name", source_path.name), suggested_path=suggested)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        destination = dlg.output_path()
        if not str(destination).strip():
            page._set_action_status("导出 / 交付已取消")
            return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            checksum = sha256_file(destination)
        except Exception as exc:
            page._set_action_status(f"导出 / 交付失败: {exc}")
            return
        # Delivery provenance: a run records the handoff WITHOUT mutating the
        # immutable OUTPUT version.
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
        except Exception:
            recorded = False
        page._set_action_status(
            f"已导出 / 交付: {destination.name} ({'已记录交付元数据' if recorded else '未记录交付元数据'})"
        )

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
        if isinstance(asset, ResourceItem):
            if tag_name not in asset.tags:
                asset.tags.append(tag_name)
                self.mirror_tag_to_catalog(asset, tag_name, add=True)
                page._refresh()
                page._set_action_status(f"已添加标签 #{tag_name}")

    def handle_tag_removed(self, asset: object, tag_name: str) -> None:
        page = self.page
        asset = unwrap_asset(asset)
        if isinstance(asset, ResourceItem):
            if tag_name in asset.tags:
                asset.tags.remove(tag_name)
                self.mirror_tag_to_catalog(asset, tag_name, add=False)
                page._refresh()
                page._set_action_status(f"已移除标签 #{tag_name}")

    def prompt_add_tag_to_assets(self, items: list[object]) -> None:
        page = self.page
        dlg = TagInputDialog(parent=page)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tag = dlg.get_tag_name()
            if not new_tag:
                return
            count = 0
            for it in items:
                it = unwrap_asset(it)
                if isinstance(it, ResourceItem):
                    if new_tag not in it.tags:
                        it.tags.append(new_tag)
                        self.mirror_tag_to_catalog(it, new_tag, add=True)
                        count += 1
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
            count = 0
            for it in items:
                it = unwrap_asset(it)
                if isinstance(it, ResourceItem):
                    if tag_to_remove in it.tags:
                        it.tags.remove(tag_to_remove)
                        self.mirror_tag_to_catalog(it, tag_to_remove, add=False)
                        count += 1
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
            # Re-clicking 校验 while a verify job is finishing must not raise
            # (OwnedWorkerJob owns one thread at a time).
            page._set_action_status("正在校验，请稍候")
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
        )
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

    def register_imported_resources(self, resources: list[ResourceItem]) -> None:
        """Register imported resources as catalog INPUT versions (RAW/EXTERNAL)
        with the legacy bridge so downstream runs can resolve them. Best-effort:
        the catalog seam must never break the import path. Each resource is
        registered independently so one failure doesn't skip the rest."""
        try:
            from paleo_workbench.catalog.lifecycle import register_resource_input

            for resource in resources:
                try:
                    register_resource_input(resource)
                except Exception:
                    pass
        except Exception:
            pass
