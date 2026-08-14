"""Navigation Tree 2.0: Smart-group tree for Data Manager IA 2.0.

Presents structured smart groups for:
- 全部数据 (All Data)
- 生命阶段 (Lifecycle: RAW, DERIVED, INTERMEDIATE, OUTPUT)
- 数据类型 (Data Types: seismic, well_log, horizon, etc.)
- 标签 (Dynamic Tag List with counts)
- 状态与完整性 (Integrity: Verified, Modified, Missing, External)
- 治理 (Governance: dynamic review-status leaves with counts)

Emits ``category_changed(str)`` and ``filter_query_changed(FilterQuery)``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_view_models import DataStage, IntegrityState
from paleo_workbench.ui.pages.filter_index import (
    CATEGORIES,
    CatalogCounts,
    FilterQuery,
    compute_catalog_counts,
)

TYPE_LEAVES = [
    ("测井", "well_log"),
    ("地震", "seismic"),
    ("层位", "horizon"),
    ("井分层", "well_stratification"),
    ("时深", "time_depth"),
    ("表格", "tabular"),
    ("文档", "document"),
    ("影像", "image_reference"),
    ("参考图", "reference_map"),
    ("测井参考", "well_reference"),
    ("未知", "unknown"),
]

STAGE_LEAVES = [
    ("🔒 原始输入", DataStage.RAW.value, "RAW"),
    ("🌿 派生数据", DataStage.DERIVED.value, "DERIVED"),
    ("⚡ 中间结果", DataStage.INTERMEDIATE.value, "INTERMEDIATE"),
    ("📦 输出成果", DataStage.OUTPUT.value, "OUTPUT"),
]

INTEGRITY_LEAVES = [
    ("✅ 已校验", IntegrityState.VERIFIED.value, "VERIFIED"),
    ("⚠️ 已修改", IntegrityState.MODIFIED.value, "MODIFIED"),
    ("❌ 缺失", IntegrityState.MISSING.value, "MISSING"),
    ("🔗 外部链接", IntegrityState.UNMANAGED.value, "UNMANAGED"),
]

REVIEW_STATUS_LABELS = {
    "draft": "草稿",
    "pending_review": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
}


class NavigationTree(QTreeWidget):
    category_changed = Signal(str)
    filter_query_changed = Signal(object)  # FilterQuery
    # Right-click "管理标签" on the 标签 group header (Tag Manager entry).
    manage_tags_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavigationTree")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setStyleSheet(
            f"QTreeWidget#NavigationTree {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self.setMinimumWidth(200)
        self.tag_parent_item: QTreeWidgetItem | None = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.currentItemChanged.connect(self._on_current_changed)
        self._build_tree()

    def _build_tree(self) -> None:
        self.clear()

        # 1. 全部数据
        all_item = QTreeWidgetItem(self, ["全部数据 0"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="all", node_value="全部"))
        all_item.setData(0, Qt.ItemDataRole.UserRole + 1, "全部")

        # 1b. 回收站 (trashed catalog assets — recoverable)
        trash_item = QTreeWidgetItem(self, ["回收站 0"])
        trash_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            FilterQuery(node_type="trash", node_value="trash"),
        )
        trash_item.setData(0, Qt.ItemDataRole.UserRole + 1, "回收站")
        self._trash_item = trash_item

        # 2. 生命阶段 (Group)
        stage_group = QTreeWidgetItem(self, ["生命阶段"])
        stage_group.setFlags(stage_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, stage_val, _name in STAGE_LEAVES:
            item = QTreeWidgetItem(stage_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="stage", node_value=stage_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, stage_val)
        stage_group.setExpanded(True)

        # 3. 数据类型 (Group)
        type_group = QTreeWidgetItem(self, ["数据类型"])
        type_group.setFlags(type_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, type_val in TYPE_LEAVES:
            item = QTreeWidgetItem(type_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="type", node_value=type_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, label)
        type_group.setExpanded(True)

        # 4. 标签 (Group - Dynamic Children)
        self.tag_parent_item = QTreeWidgetItem(self, ["标签 0"])
        self.tag_parent_item.setFlags(self.tag_parent_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tag_parent_item.setExpanded(True)

        # 5. 状态与完整性 (Group)
        integrity_group = QTreeWidgetItem(self, ["状态与完整性"])
        integrity_group.setFlags(integrity_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, int_val, _name in INTEGRITY_LEAVES:
            item = QTreeWidgetItem(integrity_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="integrity", node_value=int_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, int_val)
        integrity_group.setExpanded(False)

        # 6. 治理 (Governance: dynamic review-status leaves)
        self.review_parent_item = QTreeWidgetItem(self, ["治理 · 审核状态 0"])
        self.review_parent_item.setFlags(
            self.review_parent_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        self.review_parent_item.setExpanded(False)

        self.setCurrentItem(None)

    def update_counts(
        self,
        resources: list,
        artifacts: list,
        project_root: Path | None = None,
        *,
        extra_assets: list | None = None,
        enricher=None,
    ) -> None:
        counts = compute_catalog_counts(
            resources,
            artifacts,
            project_root=project_root,
            extra_assets=extra_assets,
            enricher=enricher,
        )
        self._update_tree_counts(counts)

    def set_trash_count(self, count: int) -> None:
        """Update the 回收站 leaf count (trashed catalog assets)."""
        if self._trash_item is not None:
            self._trash_item.setText(0, f"回收站 {count}")

    def _update_tree_counts(self, counts: CatalogCounts) -> None:
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            self._update_node_recursive(top, counts)

        # Update dynamic tags list
        if self.tag_parent_item is not None:
            self._update_tag_nodes(counts.tags)
        # Update dynamic review-status leaves (governance group)
        if getattr(self, "review_parent_item", None) is not None:
            self._update_review_nodes(counts.review_status)

    def _update_review_nodes(self, review_counts: dict[str, int]) -> None:
        parent = self.review_parent_item
        current = self.currentItem()
        selected_value = None
        if current is not None and current.parent() is parent:
            query = current.data(0, Qt.ItemDataRole.UserRole)
            if query and query.node_type == "review_status":
                selected_value = query.node_value

        parent.takeChildren()
        total = sum(review_counts.values())
        parent.setText(0, f"治理 · 审核状态 {total}")

        target_to_reselect = None
        for value in sorted(review_counts):
            label = REVIEW_STATUS_LABELS.get(value, value)
            child = QTreeWidgetItem(parent, [f"{label} {review_counts[value]}"])
            child.setData(
                0,
                Qt.ItemDataRole.UserRole,
                FilterQuery(node_type="review_status", node_value=value),
            )
            child.setData(0, Qt.ItemDataRole.UserRole + 1, value)
            if selected_value and value == selected_value:
                target_to_reselect = child
        if target_to_reselect is not None:
            self.setCurrentItem(target_to_reselect)

    def _update_node_recursive(self, item: QTreeWidgetItem, counts: CatalogCounts) -> None:
        query: FilterQuery | None = item.data(0, Qt.ItemDataRole.UserRole)
        label_base = self._label_of(item)

        if query is not None:
            count = 0
            if query.node_type == "all":
                count = counts.total
            elif query.node_type == "stage" and query.node_value:
                count = counts.stages.get(query.node_value, 0)
            elif query.node_type == "type" and query.node_value:
                count = counts.types.get(query.node_value, 0)
            elif query.node_type == "integrity" and query.node_value:
                count = counts.integrity.get(query.node_value, 0)
            elif query.node_type == "tag" and query.node_value:
                count = counts.tags.get(query.node_value, 0)
            elif query.node_type == "review_status" and query.node_value:
                count = counts.review_status.get(query.node_value, 0)

            item.setText(0, f"{label_base} {count}")

        for j in range(item.childCount()):
            self._update_node_recursive(item.child(j), counts)

    def _update_tag_nodes(self, tag_counts: dict[str, int]) -> None:
        if self.tag_parent_item is None:
            return

        total_tag_instances = sum(tag_counts.values())
        self.tag_parent_item.setText(0, f"标签 {total_tag_instances}")

        # Preserve selection if on a tag
        current = self.currentItem()
        selected_tag = None
        if current and current.parent() == self.tag_parent_item:
            query = current.data(0, Qt.ItemDataRole.UserRole)
            if query and query.node_type == "tag":
                selected_tag = query.node_value

        # Clear existing tag items
        self.tag_parent_item.takeChildren()

        # Populate sorted tags
        target_to_reselect = None
        for tag_name in sorted(tag_counts.keys()):
            count = tag_counts[tag_name]
            tag_query = FilterQuery(node_type="tag", node_value=tag_name)
            child = QTreeWidgetItem(self.tag_parent_item, [f"#{tag_name} {count}"])
            child.setData(0, Qt.ItemDataRole.UserRole, tag_query)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, f"tag:{tag_name}")

            if selected_tag and tag_name == selected_tag:
                target_to_reselect = child

        if target_to_reselect:
            self.setCurrentItem(target_to_reselect)

    @staticmethod
    def _label_of(item: QTreeWidgetItem) -> str:
        return item.text(0).rsplit(" ", 1)[0]

    def find_group(self, label: str) -> QTreeWidgetItem | None:
        return self.find_category_item(label)

    def find_category_item(self, label: str) -> QTreeWidgetItem | None:
        return self._search_node(self.invisibleRootItem(), label)

    def _search_node(self, parent: QTreeWidgetItem, label: str) -> QTreeWidgetItem | None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            if self._label_of(child) == label or child.text(0).startswith(label):
                return child
            res = self._search_node(child, label)
            if res:
                return res
        return None

    def selected_category(self) -> str:
        current = self.currentItem()
        if current is None:
            return "全部"
        key = current.data(0, Qt.ItemDataRole.UserRole + 1)
        if key is not None:
            return str(key)
        query: FilterQuery | None = current.data(0, Qt.ItemDataRole.UserRole)
        if query and query.node_value:
            return query.node_value
        return "全部"

    def current_filter_query(self) -> FilterQuery:
        current = self.currentItem()
        if current is None:
            return FilterQuery(node_type="all")
        query: FilterQuery | None = current.data(0, Qt.ItemDataRole.UserRole)
        return query or FilterQuery(node_type="all")

    def _on_context_menu(self, pos) -> None:
        """Right-click menu on the 标签 group header → 管理标签 (Tag Manager)."""
        item = self.itemAt(pos)
        if item is None or item is not self.tag_parent_item:
            return
        menu = QMenu(self)
        manage_action = menu.addAction("管理标签")
        action = menu.exec(self.viewport().mapToGlobal(pos))
        if action is manage_action:
            self.manage_tags_requested.emit()

    def _on_current_changed(
        self, current: QTreeWidgetItem, _previous: QTreeWidgetItem
    ) -> None:
        if current is None:
            return
        query: FilterQuery | None = current.data(0, Qt.ItemDataRole.UserRole)
        legacy_key = current.data(0, Qt.ItemDataRole.UserRole + 1)

        if query is not None:
            self.filter_query_changed.emit(query)
            emit_str = legacy_key or query.node_value or "全部"
            if emit_str in ("全部数据", "all"):
                emit_str = "全部"
            self.category_changed.emit(str(emit_str))
