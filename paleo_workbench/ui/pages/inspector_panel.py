"""InspectorPanel 2.0: Tabbed Data Asset Inspector for Data Manager UI 2.0.

Provides 6 structured inspector tabs / sections:
1. 概要 (Overview)
2. 元数据 (Metadata: 治理信息 + 目录元数据 + 解析摘要)
3. 标签 (Tags)
4. 版本 (Versions)
5. 血缘 (Lineage: full upstream-to-RAW / downstream tree with run nodes)
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
    QTreeWidget,
    QTreeWidgetItem,
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


class LineageTreeWidget(QWidget):
    """Full-chain lineage view: 上游追溯 (to RAW) + 下游衍生 as a tree with
    interleaved run nodes; selection shows version/run details."""

    version_activated = Signal(str, str)  # (version_id, asset_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1)
        layout.setSpacing(tokens.SPACE_1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("血缘链")
        self.tree.setColumnCount(1)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.tree, 1)

        self.detail_label = QLabel("点击节点查看版本 / 运行详情（双击版本定位数据行）")
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.detail_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " padding: 4px; border: 1px solid rgba(0,0,0,0);"
        )
        self.detail_label.setMinimumHeight(56)
        layout.addWidget(self.detail_label)
        self._selected_payload: tuple[str, dict] | None = None

    # -- population -----------------------------------------------------------

    def clear_chain(self, message: str = "") -> None:
        self.tree.clear()
        self._selected_payload = None
        self.detail_label.setText(message or "原始导入资产 / 无上游依赖")

    def load_chains(self, view: AssetView, upstream, downstream) -> None:
        """Populate from :class:`LineageChain` objects (upstream ancestors +
        downstream descendants), with producing runs interleaved.

        The upstream chain's ROOT is the current version (its producing run
        and inputs hang below it), so the current asset appears exactly once.
        """
        self.tree.clear()
        if upstream is not None:
            up_top = QTreeWidgetItem(self.tree, ["⬆ 上游追溯 (至 RAW 输入)"])
            up_top.setFlags(up_top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._append_version_node(up_top, upstream.root, "up")
            up_top.setExpanded(True)
            if getattr(upstream, "truncated", False):
                note = QTreeWidgetItem(up_top, ["… (层级/节点数达上限，已截断)"])
                note.setFlags(note.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        else:
            current = QTreeWidgetItem(
                self.tree,
                [f"■ 当前: {view.name} ({view.current_version})"],
            )
            current.setFlags(current.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        if downstream is not None:
            down_top = QTreeWidgetItem(self.tree, ["⬇ 下游衍生"])
            down_top.setFlags(down_top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for child in downstream.root.children:
                self._append_version_node(down_top, child, "down")
            # Stay collapsed: downstream trees can be wide; upstream is the
            # primary question and gets fully expanded below.
            down_top.setExpanded(False)
            if getattr(downstream, "truncated", False):
                note = QTreeWidgetItem(down_top, ["… (已截断)"])
                note.setFlags(note.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        if upstream is not None:
            self._expand_recursive(self.tree.topLevelItem(0))
        self.detail_label.setText("点击节点查看版本 / 运行详情（双击版本定位数据行）")

    @staticmethod
    def _expand_recursive(item: QTreeWidgetItem) -> None:
        item.setExpanded(True)
        for i in range(item.childCount()):
            LineageTreeWidget._expand_recursive(item.child(i))

    def _append_version_node(
        self, parent: QTreeWidgetItem, node, direction: str
    ) -> QTreeWidgetItem:
        label = f"{stage_icon(node.stage)} {node.asset_name} · {stage_label(node.stage)} v{node.version_number}"
        if node.trashed:
            label += " 🗑"
        item = QTreeWidgetItem(parent, [label])
        payload = {
            "kind": "version",
            "version_id": node.version_id,
            "asset_id": node.asset_id,
            "asset_name": node.asset_name,
            "stage": node.stage.value,
            "version_number": node.version_number,
            "path": node.path,
            "sha256": node.sha256,
            "created_at": node.created_at,
            "managed": node.managed,
            "trashed": node.trashed,
            "tags": list(node.tags),
            "run_id": node.run_id,
            "run_operation": node.run_operation,
            "run_status": node.run_status,
            "run_generator": node.run_generator,
        }
        item.setData(0, Qt.ItemDataRole.UserRole, ("version", payload))
        # Children: the producing run (when known) sits between the version
        # and its linked versions, mirroring OUTPUT → Run → INPUT semantics.
        holders = [item]
        if node.run_operation:
            run_item = QTreeWidgetItem(item, [f"⚙ {node.run_operation} (run)"])
            run_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                (
                    "run",
                    {
                        "kind": "run",
                        "run_id": node.run_id,
                        "operation": node.run_operation,
                        "status": node.run_status,
                        "generator": node.run_generator,
                        "output_version_id": node.version_id,
                    },
                ),
            )
            holders = [run_item, item]
        for child in node.children:
            self._append_version_node(holders[0], child, direction)
        return item

    # -- interaction ------------------------------------------------------------

    def _on_selection(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self._selected_payload = None
            return
        payload = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            self.detail_label.setText("")
            return
        self._selected_payload = payload
        kind, data = payload
        if kind == "version":
            checksum = data.get("sha256") or "无"
            if len(str(checksum)) > 16:
                checksum = f"{str(checksum)[:12]}…"
            tags = "、".join(data.get("tags") or []) or "—"
            run = data.get("run_operation") or "—"
            self.detail_label.setText(
                f"版本 {data.get('asset_name')} v{data.get('version_number')} · "
                f"阶段 {data.get('stage')}\n"
                f"路径: {data.get('path') or '—'}\n"
                f"校验和: {checksum} · 标签: {tags} · 生成 Run: {run}"
            )
        else:
            self.detail_label.setText(
                f"Run {data.get('operation')} · 状态 {data.get('status') or '—'} · "
                f"generator {data.get('generator') or '—'}\n"
                f"id: {data.get('run_id')}"
            )

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        kind, data = payload
        if kind == "version":
            self.version_activated.emit(data["version_id"], data["asset_id"])

    def selected_payload(self) -> tuple[str, dict] | None:
        return self._selected_payload


class InspectorPanel(QFrame):
    """Rich tabbed inspector for data assets."""

    tag_added = Signal(object, str)       # (asset, tag_name)
    tag_removed = Signal(object, str)     # (asset, tag_name)
    verify_requested = Signal(object)     # (asset)
    create_derived_requested = Signal(object)
    # Version-level tags (F6): (version_id, tag_name)
    version_tag_added = Signal(str, str)
    version_tag_removed = Signal(str, str)
    # Governance metadata editing: (AssetView) — the page resolves the
    # catalog asset id (legacy bridge or catalog-only row).
    governance_edit_requested = Signal(object)
    # Lineage navigation: double-clicked (version_id, asset_id) from the tree.
    lineage_version_activated = Signal(str, str)

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

        # Tab 2: 元数据 Metadata (治理信息 + 目录元数据 + 解析摘要)
        metadata_tab = QWidget()
        metadata_layout = QVBoxLayout(metadata_tab)
        metadata_layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1)
        metadata_layout.setSpacing(tokens.SPACE_1)

        gov_hdr = QLabel("治理信息 (来源 / 区域 / 负责人 / 学科 / 可信等级 / 审核状态):")
        gov_hdr.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        metadata_layout.addWidget(gov_hdr)
        self.governance_table = TablePreviewWidget()
        metadata_layout.addWidget(self.governance_table)
        self.governance_edit_btn = QPushButton("编辑治理信息")
        self.governance_edit_btn.setObjectName("SecondaryButton")
        self.governance_edit_btn.setFixedHeight(24)
        self.governance_edit_btn.setToolTip("编辑标准治理字段（写入数据目录，受控词表校验）")
        self.governance_edit_btn.clicked.connect(self._on_governance_edit_clicked)
        metadata_layout.addWidget(self.governance_edit_btn)

        cat_hdr = QLabel("目录元数据 (Catalog):")
        cat_hdr.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        metadata_layout.addWidget(cat_hdr)
        self.catalog_metadata_table = TablePreviewWidget()
        metadata_layout.addWidget(self.catalog_metadata_table)

        parsed_hdr = QLabel("解析摘要 (Parsed Summary):")
        parsed_hdr.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
        metadata_layout.addWidget(parsed_hdr)
        self.metadata_table = TablePreviewWidget()
        metadata_layout.addWidget(self.metadata_table)
        self.tabs.addTab(metadata_tab, "元数据")

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

        # Tab 5: 血缘 Lineage (full upstream/downstream tree)
        self.lineage_tree = LineageTreeWidget()
        self.lineage_tree.version_activated.connect(self.lineage_version_activated.emit)
        self.tabs.addTab(self.lineage_tree, "血缘")

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

    def update_asset(
        self,
        asset: object | None,
        lineage_up: object | None = None,
        lineage_down: object | None = None,
    ) -> None:
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
        self._populate_lineage(view, lineage_up, lineage_down)
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
        from paleo_workbench.catalog.governance import (
            GOVERNANCE_FIELDS,
            GOVERNANCE_KEYS,
            governance_display,
        )

        gov_rows: list[tuple[str, str]] = []
        for key in GOVERNANCE_KEYS:
            value = view.governance.get(key)
            if value:
                gov_rows.append(
                    (GOVERNANCE_FIELDS[key].label, governance_display(key, value))
                )
        if not gov_rows:
            gov_rows = [("提示", "未填写（点击下方按钮编辑）")]
        self.governance_table.load_table(("字段", "值"), tuple(gov_rows))

        catalog_rows: list[tuple[str, str]] = []
        for key in sorted(view.catalog_metadata or {}):
            if key in GOVERNANCE_KEYS:
                continue
            catalog_rows.append((str(key), str(view.catalog_metadata[key])))
        if not catalog_rows:
            catalog_rows = [("提示", "暂无目录扩展元数据")]
        self.catalog_metadata_table.load_table(("属性", "值"), tuple(catalog_rows))

        rows: list[tuple[str, str]] = []
        if view.parsed_summary:
            for k, v in view.parsed_summary.items():
                rows.append((str(k), str(v)))
        if not rows:
            rows = [("提示", "暂无附加解析元数据")]
        self.metadata_table.load_table(("属性", "值"), tuple(rows))

    def set_governance_enabled(self, enabled: bool) -> None:
        """Governance editing needs an active catalog (page toggles it)."""
        self.governance_edit_btn.setEnabled(bool(enabled))
        self.governance_edit_btn.setVisible(True)

    def _on_governance_edit_clicked(self) -> None:
        if self._current_view is not None:
            self.governance_edit_requested.emit(self._current_view)

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

    def _populate_lineage(
        self,
        view: AssetView,
        lineage_up: object | None = None,
        lineage_down: object | None = None,
    ) -> None:
        if lineage_up is None and lineage_down is None:
            lineage = view.lineage
            if lineage.has_lineage:
                # Un-enriched legacy view: keep the one-hop summary as text.
                rows: list[tuple[str, str]] = []
                if lineage.parent_ids:
                    rows.append(
                        ("父节点 / 上游资产", ", ".join(lineage.parent_names or lineage.parent_ids))
                    )
                if lineage.run_id:
                    rows.append(("生成 Runs / 任务", lineage.run_id))
                if lineage.workflow_step:
                    rows.append(("工作流步骤", lineage.workflow_step))
                if lineage.child_ids:
                    rows.append(
                        ("子节点 / 下游衍生", ", ".join(lineage.child_names or lineage.child_ids))
                    )
                self.lineage_tree.clear_chain("；".join(f"{k}: {v}" for k, v in rows))
            else:
                self.lineage_tree.clear_chain()
            return
        self.lineage_tree.load_chains(view, lineage_up, lineage_down)

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
