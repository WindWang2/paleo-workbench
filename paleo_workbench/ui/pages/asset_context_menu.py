"""AssetContextMenu 2.0: Dynamic stage-aware and bulk-operation context menu for Data Manager UI 2.0.
"""
from __future__ import annotations

from typing import Sequence

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.exporters import get_available_formats
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    DataStage,
    asset_view_from_object,
)
from paleo_workbench.ui.pages.filter_index import CATEGORIES


class AssetContextMenu(QMenu):
    """Dynamic context menu adapting to asset stage (RAW vs DERIVED vs OUTPUT) and single/multi selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._action_registry: dict[str, QAction] = {}
        self._export_actions: list[tuple[str, QAction]] = []

    def build(
        self,
        target: object | Sequence[object] | None,
        viz_supported: bool = False,
    ) -> None:
        self.clear()
        self._action_registry = {}
        self._export_actions = []

        if target is None:
            return

        if isinstance(target, (list, tuple)):
            if len(target) == 1:
                items = list(target)
            else:
                self._build_multi_selection_menu(list(target))
                return
        else:
            items = [target]

        asset = items[0]
        view = asset_view_from_object(asset)

        # 1. 预览 (Preview)
        preview = self._add_action("ctx_preview", "预览")

        # 2. RAW vs DERIVED vs INTERMEDIATE vs OUTPUT stage-specific actions
        if view.stage == DataStage.RAW:
            # Create derived copy action
            create_derived = self._add_action("ctx_create_derived", "创建派生副本 (Create Derived Copy)")
            create_derived.setToolTip("从锁定原始输入创建可编辑派生数据")

            # Direct edit disabled for RAW
            edit_raw = self._add_action("ctx_edit_original", "编辑原始数据 (已锁定 🔒)")
            edit_raw.setEnabled(False)
            edit_raw.setToolTip("原始数据已锁定，不能直接编辑。请创建派生副本。")

        elif view.stage == DataStage.DERIVED:
            # Reserved for a future version-workflow backend; disabled until
            # wired (like ctx_edit_original) so clicking never confuses.
            new_ver = self._add_action("ctx_new_version", "新建版本 / 工作副本 (New Version)")
            new_ver.setEnabled(False)
            new_ver.setToolTip("版本工作流后端尚未接入 (reserved)")

        elif view.stage == DataStage.INTERMEDIATE:
            promote = self._add_action("ctx_promote", "提升为正式数据 (Promote)")
            promote.setEnabled(False)
            promote.setToolTip("提升工作流后端尚未接入 (reserved)")

        elif view.stage == DataStage.OUTPUT:
            export_open = self._add_action("ctx_export_open", "导出 / 交付")
            export_open.setEnabled(False)
            export_open.setToolTip("交付工作流后端尚未接入 (reserved)")

        # External item action (enabled by DataPage when bridged to an
        # unmanaged catalog version; disabled otherwise).
        if not view.managed:
            materialize = self._add_action("ctx_materialize", "纳管至项目 (Import into Project)")
            materialize.setEnabled(False)
            materialize.setToolTip("需连接数据目录后端以纳管外部数据")

        # 3. 校验完整性 (Verify Integrity)
        verify = self._add_action("ctx_verify", "校验完整性 (Verify Integrity)")

        # 4. 标签 (Tags)
        add_tag = self._add_action("ctx_add_tag", "添加标签...")

        # 5. 重新扫描 (ResourceItem only)
        if isinstance(asset, ResourceItem):
            self._add_action("ctx_rescan", "重新扫描")

            # 归类为 Submenu
            classify_menu = QMenu("归类为", self)
            current_type = asset.type
            for label, rtype in CATEGORIES.items():
                if rtype is None or rtype == current_type:
                    continue
                sub = QAction(label, classify_menu)
                sub.setObjectName(f"ctx_classify_{rtype}")
                classify_menu.addAction(sub)
                self._export_actions.append((f"classify_{rtype}", sub))
            classify_action = QAction("归类为", self)
            classify_action.setMenu(classify_menu)
            self.addAction(classify_action)

        # 6. 导出 Submenu
        formats = get_available_formats(asset)
        if formats:
            export_menu = QMenu("导出", self)
            for label, _fn in formats:
                sub = QAction(label, export_menu)
                sub.setObjectName(f"ctx_export_{label}")
                export_menu.addAction(sub)
                self._export_actions.append((label, sub))
            if isinstance(asset, ResourceItem):
                inv = QAction("工程清单 (JSON)", export_menu)
                inv.setObjectName("ctx_export_INVENTORY")
                export_menu.addAction(inv)
                self._export_actions.append(("INVENTORY", inv))
            export_action = QAction("导出", self)
            export_action.setMenu(export_menu)
            self.addAction(export_action)

        # 7. 打开目录 (Open Folder)
        self._add_action("ctx_open_folder", "打开目录")

        # 8. 在可视化页面打开 (Visualize)
        if viz_supported:
            self._add_action("ctx_visualize", "在可视化页面打开")

        self.addSeparator()

        # 9. 移出项目 (Remove from Project)
        remove = self._add_action("ctx_remove", "移出项目")
        self._style_destructive(remove)

    def _build_multi_selection_menu(self, items: list[object]) -> None:
        count = len(items)

        hdr = QAction(f"已选择 {count} 项数据资产", self)
        hdr.setEnabled(False)
        self.addAction(hdr)
        self.addSeparator()

        self._add_action("ctx_bulk_add_tag", f"批量添加标签 ({count} 项)...")
        self._add_action("ctx_bulk_remove_tag", f"批量移除标签 ({count} 项)...")
        self._add_action("ctx_bulk_verify", f"批量校验完整性 ({count} 项)")

        self.addSeparator()

        remove = self._add_action("ctx_bulk_remove", f"批量移出项目 ({count} 项)")
        self._style_destructive(remove)

    def _add_action(self, name: str, label: str) -> QAction:
        action = QAction(label, self)
        action.setObjectName(name)
        self.addAction(action)
        self._action_registry[name] = action
        return action

    def _style_destructive(self, action: QAction) -> None:
        remove_style = (
            f"QMenu {{ color: {tokens.TEXT_PRIMARY}; }}"
            f" QAction#ctx_remove {{ color: {tokens.ERROR_RED}; }}"
            f" QAction#ctx_bulk_remove {{ color: {tokens.ERROR_RED}; }}"
        )
        self.setStyleSheet(remove_style)

    def find_action(self, object_name: str) -> QAction | None:
        if object_name in self._action_registry:
            return self._action_registry[object_name]
        for action in self.actions():
            if action.objectName() == object_name:
                return action
        return None

    def find_export_action(self, label: str) -> QAction | None:
        for lbl, action in self._export_actions:
            if lbl == label:
                return action
        return None
