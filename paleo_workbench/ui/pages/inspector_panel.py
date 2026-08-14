"""InspectorPanel 2.0: Tabbed Data Asset Inspector for Data Manager UI 2.0.

Provides 6 structured inspector tabs / sections:
1. 概要 (Overview)
2. 元数据 (Metadata)
3. 标签 (Tags)
4. 版本 (Versions)
5. 血缘 (Lineage)
6. 完整性 (Integrity)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_view_models import (
    AssetView,
    IntegrityState,
    VersionView,
    asset_view_from_object,
    stage_icon,
    stage_label,
)
from paleo_workbench.ui.pages.preview_widgets import TablePreviewWidget
from paleo_workbench.ui.pages.tag_widgets import TagContainerWidget, TagInputDialog


class InspectorPanel(QFrame):
    """Rich tabbed inspector for data assets."""

    tag_added = Signal(object, str)       # (asset, tag_name)
    tag_removed = Signal(object, str)     # (asset, tag_name)
    verify_requested = Signal(object)     # (asset)
    create_derived_requested = Signal(object)
    # Version-level tags (F6): (version_id, tag_name)
    version_tag_added = Signal(str, str)
    version_tag_removed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setStyleSheet(
            f"QFrame#InspectorPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self._current_asset: object | None = None
        self._current_view: AssetView | None = None
        self._selected_version: VersionView | None = None
        # Version tag editing is only meaningful with an active catalog (the
        # page enables it once the asset is catalog-bridged).
        self._version_tags_enabled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        layout.setSpacing(tokens.SPACE_1)

        self.title_label = QLabel("数据资产检查器")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600; font-size: {tokens.FONT_SIZE_BASE};"
        )
        layout.addWidget(self.title_label)

        self.empty_label = QLabel("请从列表中选择数据资产")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px; margin: 20px;")
        layout.addWidget(self.empty_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("InspectorTabs")
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {tokens.BORDER}; border-radius: {tokens.RADIUS_CARD}px; background: {tokens.BG_BODY}; }}"
            f" QTabBar::tab {{ padding: 4px 10px; font-size: 11px; font-weight: 500; color: {tokens.TEXT_SECONDARY}; }}"
            f" QTabBar::tab:selected {{ color: {tokens.PRIMARY}; border-bottom: 2px solid {tokens.PRIMARY}; font-weight: 600; }}"
        )

        # Tab 1: 概要 Overview
        self.overview_table = TablePreviewWidget()
        self.tabs.addTab(self.overview_table, "概要")

        # Tab 2: 元数据 Metadata
        self.metadata_table = TablePreviewWidget()
        self.tabs.addTab(self.metadata_table, "元数据")

        # Tab 3: 标签 Tags
        self.tags_widget = QWidget()
        tags_layout = QVBoxLayout(self.tags_widget)
        tags_layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        tags_layout.setSpacing(tokens.SPACE_2)
        tags_hdr = QLabel("资产关联标签:")
        tags_hdr.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;")
        tags_layout.addWidget(tags_hdr)

        self.tag_container = TagContainerWidget(removable=True)
        self.tag_container.tag_added.connect(self._on_tag_added)
        self.tag_container.tag_removed.connect(self._on_tag_removed)
        tags_layout.addWidget(self.tag_container)
        tags_layout.addStretch()
        self.tabs.addTab(self.tags_widget, "标签")

        # Tab 4: 版本 Versions
        version_tab = QWidget()
        version_layout = QVBoxLayout(version_tab)
        version_layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1)
        version_layout.setSpacing(tokens.SPACE_1)

        self.versions_table = QTableWidget()
        self.versions_table.setColumnCount(5)
        self.versions_table.setHorizontalHeaderLabels(
            ["版本", "生命阶段", "校验和", "时间", "标签"]
        )
        self.versions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.versions_table.verticalHeader().setVisible(False)
        self.versions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.versions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.versions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.versions_table.itemSelectionChanged.connect(self._on_version_selection_changed)
        version_layout.addWidget(self.versions_table)

        # Version tag editor (F6): +/- on the selected version row.
        self.version_tags_bar = QWidget()
        tag_row = QHBoxLayout(self.version_tags_bar)
        tag_row.setContentsMargins(0, 0, 0, 0)
        tag_row.setSpacing(tokens.SPACE_1)
        self.version_tags_hint = QLabel("版本标签:")
        self.version_tags_hint.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        tag_row.addWidget(self.version_tags_hint)
        self.version_tag_add_btn = QPushButton("+")
        self.version_tag_add_btn.setObjectName("SecondaryButton")
        self.version_tag_add_btn.setFixedSize(22, 22)
        self.version_tag_add_btn.setToolTip("为选中版本添加标签")
        self.version_tag_add_btn.clicked.connect(self._on_version_tag_add)
        tag_row.addWidget(self.version_tag_add_btn)
        self.version_tag_remove_btn = QPushButton("−")
        self.version_tag_remove_btn.setObjectName("SecondaryButton")
        self.version_tag_remove_btn.setFixedSize(22, 22)
        self.version_tag_remove_btn.setToolTip("移除选中版本的标签")
        self.version_tag_remove_btn.clicked.connect(self._on_version_tag_remove)
        tag_row.addWidget(self.version_tag_remove_btn)
        tag_row.addStretch()
        version_layout.addWidget(self.version_tags_bar)

        self.tabs.addTab(version_tab, "版本")

        # Tab 5: 血缘 Lineage
        self.lineage_table = TablePreviewWidget()
        self.tabs.addTab(self.lineage_table, "血缘")

        # Tab 6: 完整性 Integrity
        self.integrity_widget = QWidget()
        int_layout = QVBoxLayout(self.integrity_widget)
        int_layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        int_layout.setSpacing(tokens.SPACE_2)

        self.integrity_status_lbl = QLabel("状态: 未校验")
        self.integrity_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {tokens.TEXT_PRIMARY};")
        int_layout.addWidget(self.integrity_status_lbl)

        hash_box = QHBoxLayout()
        self.hash_label = QLabel("SHA-256: —")
        self.hash_label.setWordWrap(True)
        self.hash_label.setStyleSheet(f"font-family: monospace; font-size: 11px; color: {tokens.TEXT_SECONDARY};")
        hash_box.addWidget(self.hash_label, 1)

        self.copy_hash_btn = QPushButton("复制 Hash")
        self.copy_hash_btn.setObjectName("SecondaryButton")
        self.copy_hash_btn.setFixedHeight(22)
        self.copy_hash_btn.clicked.connect(self._copy_hash)
        hash_box.addWidget(self.copy_hash_btn)
        int_layout.addLayout(hash_box)

        self.verify_btn = QPushButton("立即校验完整性")
        self.verify_btn.setObjectName("PrimaryButton")
        self.verify_btn.clicked.connect(self._on_verify_clicked)
        int_layout.addWidget(self.verify_btn)
        int_layout.addStretch()
        self.tabs.addTab(self.integrity_widget, "完整性")

        layout.addWidget(self.tabs, 1)
        self.tabs.hide()

    def update_asset(self, asset: object | None) -> None:
        self._current_asset = asset
        if asset is None:
            self._current_view = None
            self._selected_version = None
            self.tabs.hide()
            self.empty_label.show()
            self.title_label.setText("数据资产检查器")
            return

        self.empty_label.hide()
        self.tabs.show()

        view = asset_view_from_object(asset)
        self._current_view = view
        self.title_label.setText(f"{stage_icon(view.stage)} {view.name}")

        self._populate_overview(view)
        self._populate_metadata(view)
        self._populate_tags(view)
        self._populate_versions(view)
        self._populate_lineage(view)
        self._populate_integrity(view)

    def _populate_overview(self, view: AssetView) -> None:
        rows = [
            ("逻辑名称", view.name),
            ("类型", view.type_label),
            ("格式", view.format),
            ("生命阶段", f"{stage_icon(view.stage)} {stage_label(view.stage)}"),
            ("当前版本", view.current_version),
            ("管理方式", "受管 (Managed)" if view.managed else "外部 (External)"),
            ("完整性状态", f"{view.integrity_state.icon_symbol} {view.integrity_state.label}"),
            ("路径", view.path),
            ("大小", view.size_formatted),
            ("修改时间", view.modified_at),
            ("数据源", view.source),
        ]
        if view.trashed:
            rows.insert(1, ("回收站状态", view.trashed_label))
        if view.crs:
            rows.append(("CRS", view.crs))
        self.overview_table.load_table(("属性", "值"), tuple(rows))

    def _populate_metadata(self, view: AssetView) -> None:
        rows: list[tuple[str, str]] = []
        if view.parsed_summary:
            for k, v in view.parsed_summary.items():
                rows.append((str(k), str(v)))
        if not rows:
            rows = [("提示", "暂无附加解析元数据")]
        self.metadata_table.load_table(("属性", "值"), tuple(rows))

    def _populate_tags(self, view: AssetView) -> None:
        self.tag_container.set_tags(view.tags)

    def _populate_versions(self, view: AssetView) -> None:
        self._selected_version = None
        self.versions_table.setRowCount(len(view.versions))
        for r, ver in enumerate(view.versions):
            curr_str = f"★ {ver.version_id}" if ver.is_current else ver.version_id
            self.versions_table.setItem(r, 0, QTableWidgetItem(curr_str))
            self.versions_table.setItem(r, 1, QTableWidgetItem(stage_label(ver.stage)))
            self.versions_table.setItem(r, 2, QTableWidgetItem(ver.checksum_display))
            self.versions_table.setItem(r, 3, QTableWidgetItem(ver.created_at))
            tags_text = "、".join(ver.tags) if ver.tags else "—"
            self.versions_table.setItem(r, 4, QTableWidgetItem(tags_text))
        # Re-filling the table does not emit itemSelectionChanged when the
        # same row index stays current — re-derive the selection so the
        # version-tag controls keep working after a refresh.
        row = self.versions_table.currentRow()
        if 0 <= row < len(view.versions):
            self._selected_version = view.versions[row]
        self._sync_version_tag_controls()

    # --- Version tags (F6) ---------------------------------------------------

    def set_version_tags_enabled(self, enabled: bool) -> None:
        """Enable/hide the version tag editor (needs an active catalog)."""
        self._version_tags_enabled = bool(enabled)
        self._sync_version_tag_controls()

    def version_tags_enabled(self) -> bool:
        return self._version_tags_enabled

    def _on_version_selection_changed(self) -> None:
        row = self.versions_table.currentRow()
        view = self._current_view
        if view is None or row < 0 or row >= len(view.versions):
            self._selected_version = None
        else:
            self._selected_version = view.versions[row]
        self._sync_version_tag_controls()

    def _sync_version_tag_controls(self) -> None:
        visible = self._version_tags_enabled
        self.version_tags_bar.setVisible(visible)
        has_version = self._selected_version is not None
        self.version_tag_add_btn.setEnabled(has_version)
        self.version_tag_remove_btn.setEnabled(
            has_version and bool(self._selected_version.tags)
        )

    def _on_version_tag_add(self) -> None:
        version = self._selected_version
        if version is None:
            return
        dlg = TagInputDialog(existing_tags=list(version.tags), parent=self)
        dlg.setWindowTitle("添加版本标签")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.get_tag_name()
        if name:
            self.version_tag_added.emit(version.version_id, name)

    def _on_version_tag_remove(self) -> None:
        version = self._selected_version
        if version is None or not version.tags:
            return
        menu = QMenu(self)
        for tag in version.tags:
            menu.addAction(tag)
        action = menu.exec(QCursor.pos())
        if action is not None and action.text():
            self.version_tag_removed.emit(version.version_id, action.text())

    def _populate_lineage(self, view: AssetView) -> None:
        rows: list[tuple[str, str]] = []
        lineage = view.lineage
        if lineage.parent_ids:
            rows.append(("父节点 / 上游资产", ", ".join(lineage.parent_names or lineage.parent_ids)))
        if lineage.run_id:
            rows.append(("生成 Runs / 任务", lineage.run_id))
        if lineage.workflow_step:
            rows.append(("工作流步骤", lineage.workflow_step))
        if lineage.child_ids:
            rows.append(("子节点 / 下游衍生", ", ".join(lineage.child_names or lineage.child_ids)))

        if not rows:
            rows = [("血缘关系", "原始导入资产 / 无上游依赖")]

        self.lineage_table.load_table(("关系类型", "详细信息"), tuple(rows))

    def _populate_integrity(self, view: AssetView) -> None:
        st = view.integrity_state
        self.integrity_status_lbl.setText(f"完整性状态: {st.icon_symbol} {st.label}")
        self.integrity_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {st.color_token};")

        checksum = view.checksum or "未生成校验和"
        self.hash_label.setText(f"SHA-256: {checksum}")
        self.copy_hash_btn.setEnabled(bool(view.checksum))

    def _copy_hash(self) -> None:
        if self._current_view and self._current_view.checksum:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self._current_view.checksum)

    def _on_verify_clicked(self) -> None:
        if self._current_asset:
            self.verify_requested.emit(self._current_asset)

    def _on_tag_added(self, tag_name: str) -> None:
        if self._current_asset:
            self.tag_added.emit(self._current_asset, tag_name)

    def _on_tag_removed(self, tag_name: str) -> None:
        if self._current_asset:
            self.tag_removed.emit(self._current_asset, tag_name)
