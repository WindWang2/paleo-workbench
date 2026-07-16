from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.exporters import get_available_formats
from paleo_workbench.ui import tokens


class AssetContextMenu(QMenu):
    """Right-click context menu for the data page asset table.

    The menu exposes 6 logical items (预览, 重新扫描, 导出, 打开目录,
    在可视化页面打开, 移出项目) whose visibility is driven by the selected
    asset and the ``viz_supported`` flag. DataPage connects each action's
    ``triggered`` signal to its handler; actions are located via
    :meth:`find_action` / :meth:`find_export_action` using stable objectNames.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._export_actions: list[tuple[str, QAction]] = []

    def build(self, asset: ResourceItem | ExportArtifact | None, viz_supported: bool) -> None:
        """Populate menu items based on the selected asset."""
        self.clear()
        self._export_actions = []
        if asset is None:
            return

        # 预览
        preview = QAction("预览", self)
        preview.setObjectName("ctx_preview")
        self.addAction(preview)

        # 重新扫描 (ResourceItem only)
        if isinstance(asset, ResourceItem):
            rescan = QAction("重新扫描", self)
            rescan.setObjectName("ctx_rescan")
            self.addAction(rescan)

            # 归类为 (ResourceItem only) - 手动修改文件类型
            classify_menu = QMenu("归类为", self)
            current_type = asset.type
            from paleo_workbench.ui.pages.filter_index import CATEGORIES
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

        # 导出 (converters + always-available inventory when on a resource)
        formats = get_available_formats(asset)
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
        if formats or isinstance(asset, ResourceItem):
            export_action = QAction("导出", self)
            export_action.setMenu(export_menu)
            self.addAction(export_action)

        # 打开目录
        open_folder = QAction("打开目录", self)
        open_folder.setObjectName("ctx_open_folder")
        self.addAction(open_folder)

        # 在可视化页面打开 (viz supported)
        if viz_supported:
            visualize = QAction("在可视化页面打开", self)
            visualize.setObjectName("ctx_visualize")
            self.addAction(visualize)

        # Separator
        self.addSeparator()

        # 移出项目 (styled in ERROR_RED to signal a destructive action)
        remove = QAction("移出项目", self)
        remove.setObjectName("ctx_remove")
        self.addAction(remove)
        remove_style = f"QMenu {{ color: {tokens.TEXT_PRIMARY}; }} QAction#ctx_remove {{ color: {tokens.ERROR_RED}; }}"
        self.setStyleSheet(remove_style)

    def find_action(self, object_name: str) -> QAction | None:
        """Find a top-level action by objectName."""
        for action in self.actions():
            if action.objectName() == object_name:
                return action
        return None

    def find_export_action(self, label: str) -> QAction | None:
        """Find a sub-menu export action by label."""
        for lbl, action in self._export_actions:
            if lbl == label:
                return action
        return None
