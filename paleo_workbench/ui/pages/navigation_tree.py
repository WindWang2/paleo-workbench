"""Navigation Tree 3.0: WorkArea-entity-first smart tree for Data Manager.

Top-level order (IA 3.0, when a WorkArea exists):

- 全部数据 / 回收站
- 工区概览 (project overview panel node)
- 井 (per-well leaves → canonical Well.id entity filters)
- 地震 (per-survey leaves)
- 地质解释 / 辅助资料 / 工作数据 / 成果
- Legacy smart views stay available as secondary navigation:
  生命阶段 · 数据类型 · 标签 · 状态与完整性 · 治理

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

# Domain-node vocabulary (FilterQuery.node_type values owned by this tree).
ENTITY_NODE = "entity"
ENTITY_GROUP_NODE = "entity_group"
OVERVIEW_NODE = "overview"
AUXILIARY_NODE = "auxiliary"
WORKING_DATA_NODE = "stage_any"

# Entity-type → (group label, icon prefix)
_ENTITY_GROUPS = {
    "well": ("井", "🛢"),
    "seismic_survey": ("地震", "🌊"),
}

# Non-linked auxiliary material types shown under 辅助资料.
AUXILIARY_TYPES = {"document", "image_reference", "reference_map", "tabular"}

# Well asset-role sub-leaves (§14): label → EntityAssetLink.role
_WELL_ROLE_LEAVES = [
    ("测井", "well_log"),
    ("井轨迹", "trajectory"),
    ("分层", "tops"),
    ("时深", "time_depth"),
    ("解释", "interpretation"),
    ("其他", "other"),
]

# Tree rendering cap (§24): the DATA MANAGER tree is a navigation surface,
# not a registry browser — beyond this many wells users navigate via search
# in the 井位地图 page.  Prevents 50k QTreeWidgetItem allocations.
MAX_ENTITY_CHILDREN = 500


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
        # WorkArea domain state (None until a project with entities arrives).
        self._domain_project = None
        self._entity_counts: dict[tuple[str, str], int] = {}
        self._overview_item: QTreeWidgetItem | None = None
        self._well_group_item: QTreeWidgetItem | None = None
        self._survey_group_item: QTreeWidgetItem | None = None
        self._geo_group_item: QTreeWidgetItem | None = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.currentItemChanged.connect(self._on_current_changed)
        self._build_tree()

    def _build_tree(self) -> None:
        self.clear()
        self._overview_item = None
        self._well_group_item = None
        self._survey_group_item = None
        self._geo_group_item = None

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

        # 2. 工区 (WorkArea entity-first section — populated by set_project)
        overview_item = QTreeWidgetItem(self, ["工区概览"])
        overview_item.setData(
            0, Qt.ItemDataRole.UserRole, FilterQuery(node_type=OVERVIEW_NODE)
        )
        overview_item.setData(0, Qt.ItemDataRole.UserRole + 1, "工区概览")
        self._overview_item = overview_item

        for entity_type, (label, icon) in _ENTITY_GROUPS.items():
            group = QTreeWidgetItem(self, [f"{icon} {label}"])
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            group.setData(0, Qt.ItemDataRole.UserRole + 1, label)
            if entity_type == "well":
                self._well_group_item = group
            else:
                self._survey_group_item = group

        # 2b. 地质解释 (dynamic children from geological_entities) /
        # 辅助资料 / 工作数据 / 成果 smart views.
        self._geo_group_item = QTreeWidgetItem(self, ["地质解释"])
        self._geo_group_item.setFlags(
            self._geo_group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        self._geo_group_item.setData(0, Qt.ItemDataRole.UserRole + 1, "地质解释")

        aux_item = QTreeWidgetItem(self, ["辅助资料 0"])
        aux_item.setData(
            0, Qt.ItemDataRole.UserRole, FilterQuery(node_type=AUXILIARY_NODE)
        )
        aux_item.setData(0, Qt.ItemDataRole.UserRole + 1, "辅助资料")

        working_item = QTreeWidgetItem(self, ["工作数据 0"])
        working_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            FilterQuery(
                node_type=WORKING_DATA_NODE,
                node_value=f"{DataStage.DERIVED.value},{DataStage.INTERMEDIATE.value}",
            ),
        )
        working_item.setData(0, Qt.ItemDataRole.UserRole + 1, "工作数据")

        output_item = QTreeWidgetItem(self, ["成果 0"])
        output_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            FilterQuery(node_type="stage", node_value=DataStage.OUTPUT.value),
        )
        output_item.setData(0, Qt.ItemDataRole.UserRole + 1, "成果")

        # 3. 生命阶段 (Group)
        stage_group = QTreeWidgetItem(self, ["生命阶段"])
        stage_group.setFlags(stage_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, stage_val, _name in STAGE_LEAVES:
            item = QTreeWidgetItem(stage_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="stage", node_value=stage_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, stage_val)
        stage_group.setExpanded(False)

        # 4. 数据类型 (Group)
        type_group = QTreeWidgetItem(self, ["数据类型"])
        type_group.setFlags(type_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, type_val in TYPE_LEAVES:
            item = QTreeWidgetItem(type_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="type", node_value=type_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, label)
        type_group.setExpanded(False)

        # 5. 标签 (Group - Dynamic Children)
        self.tag_parent_item = QTreeWidgetItem(self, ["标签 0"])
        self.tag_parent_item.setFlags(self.tag_parent_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tag_parent_item.setExpanded(True)

        # 6. 状态与完整性 (Group)
        integrity_group = QTreeWidgetItem(self, ["状态与完整性"])
        integrity_group.setFlags(integrity_group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for label, int_val, _name in INTEGRITY_LEAVES:
            item = QTreeWidgetItem(integrity_group, [f"{label} 0"])
            item.setData(0, Qt.ItemDataRole.UserRole, FilterQuery(node_type="integrity", node_value=int_val))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, int_val)
        integrity_group.setExpanded(False)

        # 7. 治理 (Governance: dynamic review-status leaves)
        self.review_parent_item = QTreeWidgetItem(self, ["治理 · 审核状态 0"])
        self.review_parent_item.setFlags(
            self.review_parent_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        self.review_parent_item.setExpanded(False)

        self.setCurrentItem(None)

    # ------------------------------------------------------------------
    # WorkArea domain section (IA 3.0)
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Bind the WorkArea document and rebuild the entity-first groups.

        Deterministic ordering (wells/surveys sorted by name); preserves the
        current selection when the same entity stays present.
        """
        self._domain_project = project
        current_query = self.current_filter_query()
        self._rebuild_entity_groups()
        if current_query.node_type in (ENTITY_NODE, ENTITY_GROUP_NODE):
            restored = self._find_entity_item(current_query.node_value or "")
            if restored is not None:
                self.setCurrentItem(restored)

    def _rebuild_entity_groups(self) -> None:
        project = self._domain_project
        wells = list(getattr(project, "wells", None) or []) if project else []
        surveys = list(getattr(project, "seismic_surveys", None) or []) if project else []
        links = list(getattr(project, "entity_asset_links", None) or []) if project else []

        well_counts: dict[str, int] = {}
        survey_counts: dict[str, int] = {}
        unresolved_wells: set[str] = set()
        invalid_coord_wells: set[str] = set()
        # Single O(L) pass over links; per-(entity, role) counts precomputed
        # so role sub-leaves never rescan the link list (review finding #7).
        well_role_counts: dict[tuple[str, str], int] = {}
        for link in links:
            if link.entity_type == "well":
                well_counts[link.entity_id] = well_counts.get(link.entity_id, 0) + 1
                if link.unresolved:
                    unresolved_wells.add(link.entity_id)
                key = (link.entity_id, link.role)
                well_role_counts[key] = well_role_counts.get(key, 0) + 1
            elif link.entity_type == "seismic_survey":
                survey_counts[link.entity_id] = survey_counts.get(link.entity_id, 0) + 1
        for well in wells:
            from paleo_workbench.project.domain import CoordinateStatus

            if well.coordinate_status in (
                CoordinateStatus.UNTRANSFORMED,
                CoordinateStatus.INVALID,
            ):
                invalid_coord_wells.add(well.id)

        self._entity_counts = {}
        for well in wells:
            self._entity_counts[("well", well.id)] = well_counts.get(well.id, 0)
        for survey in surveys:
            self._entity_counts[("seismic_survey", survey.id)] = survey_counts.get(
                survey.id, 0
            )
        for entity in getattr(project, "geological_entities", None) or []:
            self._entity_counts[("geological_entity", entity.id)] = sum(
                1 for link in links if link.entity_id == entity.id
            )

        # 地质解释 children (same membership-filter mechanics as wells).
        if self._geo_group_item is not None:
            group = self._geo_group_item
            group.takeChildren()
            entities = list(getattr(project, "geological_entities", None) or [])
            for entity in sorted(entities, key=lambda item: (item.name, item.id))[
                :MAX_ENTITY_CHILDREN
            ]:
                count = self._entity_counts.get(("geological_entity", entity.id), 0)
                child = QTreeWidgetItem(group, [f"⛰ {entity.name} {count}"])
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    FilterQuery(node_type=ENTITY_NODE, node_value=entity.id),
                )
                child.setData(0, Qt.ItemDataRole.UserRole + 1, f"entity:{entity.id}")
                child.setToolTip(0, entity.entity_kind or entity.name)
            if not entities:
                empty = QTreeWidgetItem(group, ["暂无地质解释，导入层位数据后自动识别"])
                empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                empty.setDisabled(True)
            group.setExpanded(0 < len(entities) <= 200)

        for group, entities, entity_type in (
            (self._well_group_item, wells, "well"),
            (self._survey_group_item, surveys, "seismic_survey"),
        ):
            if group is None:
                continue
            selected_key = None
            current = self.currentItem()
            if current is not None and current.parent() is group:
                query = current.data(0, Qt.ItemDataRole.UserRole)
                if query and query.node_type == ENTITY_NODE:
                    selected_key = query.node_value
            group.takeChildren()
            icon = _ENTITY_GROUPS[entity_type][1]
            ordered = sorted(entities, key=lambda item: (item.name, item.id))
            rendered = ordered[:MAX_ENTITY_CHILDREN]
            for entity in rendered:
                flags = ""
                if entity.id in unresolved_wells:
                    flags = " ⚠"
                elif entity.id in invalid_coord_wells:
                    flags = " ⚠坐标"
                count = self._entity_counts.get((entity_type, entity.id), 0)
                child = QTreeWidgetItem(
                    group, [f"{icon} {entity.name}{flags} {count}"]
                )
                child.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    FilterQuery(node_type=ENTITY_NODE, node_value=entity.id),
                )
                child.setData(0, Qt.ItemDataRole.UserRole + 1, f"entity:{entity.id}")
                child.setToolTip(0, getattr(entity, "uwi", "") or entity.name)
                if entity_type == "well":
                    for role_label, role in _WELL_ROLE_LEAVES:
                        role_count = well_role_counts.get((entity.id, role), 0)
                        if role_count == 0:
                            continue
                        role_child = QTreeWidgetItem(child, [f"{role_label} {role_count}"])
                        role_child.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            FilterQuery(
                                node_type=ENTITY_NODE,
                                node_value=entity.id,
                                entity_role=role,
                            ),
                        )
                        role_child.setData(
                            0, Qt.ItemDataRole.UserRole + 1, f"entity:{entity.id}:{role}"
                        )
                if selected_key == entity.id:
                    self.setCurrentItem(child)
            if len(ordered) > MAX_ENTITY_CHILDREN:
                overflow = QTreeWidgetItem(
                    group,
                    [f"…另有 {len(ordered) - MAX_ENTITY_CHILDREN} 口井，请在井位地图中查看"],
                )
                overflow.setFlags(overflow.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                overflow.setDisabled(True)
            empty_label = "暂无井，导入井位文件后自动识别" if entity_type == "well" else "暂无地震工区"
            if not entities:
                empty = QTreeWidgetItem(group, [empty_label])
                empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                empty.setDisabled(True)
            group.setExpanded(entity_type == "well" and 0 < len(rendered) <= 200)

    def _find_entity_item(self, entity_id: str) -> QTreeWidgetItem | None:
        stack = [self.invisibleRootItem()]
        while stack:
            node = stack.pop()
            for i in range(node.childCount()):
                child = node.child(i)
                query = child.data(0, Qt.ItemDataRole.UserRole)
                if (
                    query is not None
                    and query.node_type == ENTITY_NODE
                    and query.node_value == entity_id
                ):
                    return child
                stack.append(child)
        return None

    def highlight_well(self, well_id: str) -> bool:
        """Select the tree leaf of ``well_id`` (Map → Data direction)."""
        item = self._find_entity_item(well_id)
        if item is None:
            return False
        self.setCurrentItem(item)
        self.scrollToItem(item)
        return True

    def update_counts(
        self,
        resources: list,
        artifacts: list,
        project_root: Path | None = None,
        *,
        extra_assets: list | None = None,
        enricher=None,
        views: list | None = None,
    ) -> None:
        counts = compute_catalog_counts(
            resources,
            artifacts,
            project_root=project_root,
            extra_assets=extra_assets,
            enricher=enricher,
            views=views,
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

        # Domain smart-view counts (not covered by _update_node_recursive).
        auxiliary_total = sum(
            counts.types.get(aux_type, 0) for aux_type in AUXILIARY_TYPES
        )
        working_total = sum(
            counts.stages.get(stage_value, 0)
            for stage_value in (DataStage.DERIVED.value, DataStage.INTERMEDIATE.value)
        )
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            query = item.data(0, Qt.ItemDataRole.UserRole)
            if query is None:
                continue
            if query.node_type == AUXILIARY_NODE:
                item.setText(0, f"辅助资料 {auxiliary_total}")
            elif query.node_type == WORKING_DATA_NODE:
                item.setText(0, f"工作数据 {working_total}")

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
        elif selected_value is not None:
            self._reset_filter_to_all()

    def _reset_filter_to_all(self) -> None:
        """Re-select 全部 when the active tag/review leaf was deleted (#656)."""
        all_item = self.topLevelItem(0)
        if all_item is not None:
            self.setCurrentItem(all_item)

    def _update_node_recursive(self, item: QTreeWidgetItem, counts: CatalogCounts) -> None:
        query: FilterQuery | None = item.data(0, Qt.ItemDataRole.UserRole)
        label_base = self._label_of(item)

        if query is not None and query.node_type not in (
            ENTITY_NODE,
            ENTITY_GROUP_NODE,
            OVERVIEW_NODE,
            AUXILIARY_NODE,
            WORKING_DATA_NODE,
        ):
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
        elif selected_tag is not None:
            self._reset_filter_to_all()

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
