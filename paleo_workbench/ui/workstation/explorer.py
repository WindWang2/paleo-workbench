from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import (
    QItemSelectionModel,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QToolButton,
    QTreeView,
    QVBoxLayout,
)

from paleo_workbench.ui.workstation.common import workstation_icon

OBJECT_ROLE = Qt.ItemDataRole.UserRole + 1
NAVIGATION_ROLE = Qt.ItemDataRole.UserRole + 2
# 稳定差分 key（kind + 业务 id）：refresh 按它对比新旧树做增量更新，
# 不再 clear + 全量重建（B3）。
KEY_ROLE = Qt.ItemDataRole.UserRole + 3
ICON_ROLE = Qt.ItemDataRole.UserRole + 4

# 搜索过滤防抖：击键只重置定时器，200ms 后才真正过滤（B3）。
_SEARCH_DEBOUNCE_MS = 200
# 单组行数上限：超大目录靠搜索/分页承载，不在树里全铺（B3）。
_GROUP_ROW_LIMIT = 5000

_USER_LAYER_KIND_ICONS = {
    "point": "map/add_point.svg",
    "line": "map/add_line.svg",
    "polygon": "map/add_polygon.svg",
}
_USER_LAYER_KIND_LABELS = {"point": "点", "line": "线", "polygon": "面"}

# 编图文档（PaleoMapDocument）里可计数的图层类别。
_MAP_LAYER_CATEGORY_LABELS = {
    "line_features": "线要素",
    "facies_polygons": "相区面",
    "label_features": "标注",
    "reference_layers": "参考图层",
}


@dataclass
class _TreeNode:
    """一次刷新产出的树规格节点。

    ``refresh`` 先把当前工程组装成 ``_TreeNode`` 树，再与现有
    ``QStandardItem`` 树按 ``key`` 差分：新增行 append、消失行 remove、
    变化行只更新文本/图标/payload——展开、选中与滚动位置保持不变。
    """

    key: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    icon: str = ""
    tooltip: str = ""
    navigation: tuple[int, str] | None = None
    check_state: Qt.CheckState | None = None
    children: list["_TreeNode"] = field(default_factory=list)


class WorkstationExplorer(QFrame):
    """Project-scoped objects with explicit Data and Layer modes."""

    object_selected = Signal(object)
    object_activated = Signal(object)
    navigation_requested = Signal(int, str)
    joint_workspace_requested = Signal()

    _MODE_TITLES: ClassVar[dict[str, str]] = {
        "project": "资源管理器",
        "data": "数据目录",
        "layers": "图层管理器",
        "search": "全局搜索",
        "history": "历史与成果",
        "workspaces": "工作区",
    }

    def __init__(self, project=None, parent=None):
        super().__init__(parent)
        self.setObjectName("WorkstationExplorer")
        self.setMinimumWidth(210)
        # 不设最大宽度：dock 加宽或浮动放大时内容要占满面板。
        self._project = project
        self._mode = "project"
        # 视图状态（差分刷新的保持目标）：展开 key 集合 + 结构重置标志。
        self._expanded_keys: set[str] = set()
        self._structure_dirty = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel("资源管理器", self)
        self.title_label.setObjectName("WorkstationPanelTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)
        refresh = QToolButton(self)
        refresh.setObjectName("WorkstationChromeButton")
        refresh.setIcon(workstation_icon("refresh-cw.svg"))
        refresh.setToolTip("刷新")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        outer.addLayout(header)

        self.search_box = QLineEdit(self)
        self.search_box.setObjectName("WorkstationExplorerSearch")
        self.search_box.setPlaceholderText("筛选当前对象...")
        self.search_box.setClearButtonEnabled(True)
        outer.addWidget(self.search_box)

        self.model = QStandardItemModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setRecursiveFilteringEnabled(True)
        # 防抖：textChanged 只重启定时器，到点才把文本交给代理过滤。
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._apply_search_filter)
        self.search_box.textChanged.connect(lambda _text: self._search_timer.start())

        self.tree = QTreeView(self)
        self.tree.setObjectName("WorkstationExplorerTree")
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        # 所有节点统一右键菜单（B3）：构建集中在 _build_context_menu。
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.doubleClicked.connect(self._on_activated)
        outer.addWidget(self.tree, 1)

        self.footer_label = QLabel("", self)
        self.footer_label.setObjectName("WorkstationPanelFootnote")
        outer.addWidget(self.footer_label)

        self.refresh()

    def set_project(self, project) -> None:
        self._project = project
        # 工程切换属于结构变化：恢复默认展开（用户对旧树的展开不再有意义）。
        self._structure_dirty = True
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in self._MODE_TITLES else "project"
        self.title_label.setText(self._MODE_TITLES[self._mode])
        self.search_box.setPlaceholderText(
            "搜索项目数据..." if self._mode in {"data", "search"} else "筛选当前对象..."
        )
        # 模式切换同样走增量路径；但展开状态按新树默认展开重置。
        self._structure_dirty = True
        self.refresh()
        if self._mode in {"search", "data"}:
            self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def focus_search(self) -> None:
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()

    def notify_project_mutated(self) -> None:
        """工程文档变化后的增量刷新入口（宿主接线用，保持视图状态）。"""
        self.refresh()

    def refresh(self) -> None:
        """增量刷新：按稳定 key 差分更新，不清空重建。"""
        spec = self._build_spec()
        self._reconcile(spec)

    # ------------------------------------------------------------------
    # 树规格（真实数据 → _TreeNode 树）
    # ------------------------------------------------------------------

    def _build_spec(self) -> list[_TreeNode]:
        builders = {
            "project": self._spec_project,
            "data": self._spec_data,
            "layers": self._spec_layers,
            "search": self._spec_data,
            "history": self._spec_history,
            "workspaces": self._spec_workspaces,
        }
        return builders.get(self._mode, self._spec_project)()

    def _project_root_node(self) -> _TreeNode:
        name = str(getattr(getattr(self._project, "meta", None), "name", "") or "未命名工程")
        return _TreeNode("project", name, {"kind": "project", "object": self._project}, icon="folder-open.svg")

    def _spec_project(self) -> list[_TreeNode]:
        root = self._project_root_node()
        project = self._project
        if project is None:
            self.footer_label.setText("未打开工程")
            return [root]
        root.children.append(
            _TreeNode("overview", "概览", {"kind": "overview"}, navigation=(0, "overview"))
        )
        area_name = str(getattr(getattr(project, "workarea", None), "name", "") or "未命名工区")
        area = _TreeNode(
            "area",
            f"工区 · {area_name}",
            {"kind": "area", "object": getattr(project, "workarea", None)},
        )
        area.children.append(self._well_group_node())
        area.children.append(self._seismic_group_node())
        area.children.append(self._horizon_group_node())
        area.children.append(self._interpretation_group_node())
        area.children.append(
            self._group_node(
                "group/results",
                "成果",
                [
                    _TreeNode(f"result/{key}", label, {"kind": "result", "result_type": key})
                    for label, key in (("剖面", "section"), ("平面图", "map"), ("数据导出", "export"))
                ],
            )
        )
        user_group = self._user_layer_group_node()
        if user_group is not None:
            area.children.append(user_group)
        root.children.append(area)

        wells = list(getattr(project, "wells", None) or [])
        seismic = [r for r in self._visible_resources() if getattr(r, "type", "") == "seismic"]
        horizons = self._horizon_objects()
        self.footer_label.setText(
            f"{len(wells)} 口井 · {len(seismic)} 个地震体 · {len(horizons)} 个层位"
        )
        return [root]

    def _spec_data(self) -> list[_TreeNode]:
        root = self._project_root_node()
        grouped: dict[str, list[Any]] = defaultdict(list)
        for resource in self._visible_resources():
            grouped[str(getattr(resource, "type", "") or "unknown")].append(resource)
        labels = {
            "well_log": "测井",
            "seismic": "地震",
            "well_head": "井位",
            "well_stratification": "分层",
            "horizon": "层位",
            "geojson": "矢量",
            "raster": "栅格",
            "tabular": "表格",
            "document": "参考资料",
            "image_reference": "参考图像",
            "unknown": "其他",
        }
        ordered = sorted(grouped, key=lambda key: (labels.get(key, key), key))
        count = 0
        for key in ordered:
            resources = grouped[key]
            root.children.append(
                self._group_node(
                    f"group/data/{key}",
                    f"{labels.get(key, key)} ({len(resources)})",
                    [self._resource_node(resource) for resource in resources],
                )
            )
            count += len(resources)
        user_group = self._user_layer_group_node()
        if user_group is not None:
            root.children.append(user_group)
            count += len(user_group.children)
        self.footer_label.setText(f"{count} 个项目数据对象；存储缓存默认隐藏")
        return [root]

    def _spec_layers(self) -> list[_TreeNode]:
        """图层管理器：真实图层清单（编修图层 + 编图文档），无数据给空态。"""
        root = _TreeNode("layers-root", "解释图层", {"kind": "document"})
        layers = list(getattr(self._project, "user_vector_layers", None) or [])
        documents = list(getattr(self._project, "paleomap_documents", None) or [])
        if not layers and not documents:
            root.children.append(
                _TreeNode("layers-empty", "暂无图层 — 在编图文档中创建", {"kind": "empty"})
            )
            self.footer_label.setText("暂无图层 — 在编图文档中创建")
            return [root]
        root.children.extend(self._user_layer_node(layer) for layer in layers)
        for document in documents:
            categories = [
                _TreeNode(
                    f"mapdoc/{document.id}/{category}",
                    f"{label} ({len(getattr(document, category, None) or [])})",
                    {"kind": "layer", "layer_type": category, "object": document},
                )
                for category, label in _MAP_LAYER_CATEGORY_LABELS.items()
                if getattr(document, category, None)
            ]
            root.children.append(
                _TreeNode(
                    f"mapdoc/{document.id}",
                    str(getattr(document, "name", "") or "未命名文档"),
                    {
                        "kind": "layer",
                        "layer_type": "map_document",
                        "object": document,
                        "map_document_id": str(getattr(document, "id", "") or ""),
                    },
                    children=categories,
                )
            )
        self.footer_label.setText(
            f"{len(layers)} 个编修图层 · {len(documents)} 个编图文档；图层仅影响当前文档"
        )
        return [root]

    def _spec_history(self) -> list[_TreeNode]:
        root = self._project_root_node()
        project = self._project
        interpretations = list(getattr(project, "horizon_interpretations", None) or [])
        if interpretations:
            version_children = []
            for ref in interpretations:
                version = str(getattr(ref, "current_version_id", "") or "")
                label = str(getattr(ref, "name", "") or "未命名解释")
                if version:
                    label = f"{label} · {version}"
                version_children.append(
                    _TreeNode(
                        f"interp/{getattr(ref, 'id', '') or label}",
                        label,
                        {"kind": "version", "name": version or label, "object": ref},
                    )
                )
        else:
            version_children = [
                _TreeNode("group/history-versions/empty", "尚无解释版本", {"kind": "empty"})
            ]
        root.children.append(self._group_node("group/history-versions", "解释版本", version_children))
        exports = self._group_node(
            "group/history-exports",
            "成果输出",
            [
                _TreeNode(
                    f"export/{getattr(artifact, 'id', '')}",
                    str(
                        getattr(artifact, "name", "")
                        or Path(str(getattr(artifact, "output_path", "") or "")).name
                        or "导出成果"
                    ),
                    {"kind": "export", "object": artifact},
                    tooltip=str(getattr(artifact, "output_path", "") or ""),
                )
                for artifact in list(getattr(project, "export_artifacts", None) or [])
            ],
        )
        if not exports.children:
            exports.children.append(
                _TreeNode("group/history-exports/empty", "尚无导出成果", {"kind": "empty"})
            )
        root.children.append(exports)
        self.footer_label.setText("解释、校验与导出历史")
        return [root]

    def _spec_workspaces(self) -> list[_TreeNode]:
        joint = _TreeNode(
            "workspace/joint",
            "井震联合解释",
            {"kind": "workspace", "workspace": "joint"},
            icon="visualization.svg",
        )
        entries = (
            ("项目概述", 0, "overview"),
            ("数据管理", 0, "management"),
            ("测井预测", 1, "well_log"),
            ("层序格架", 1, "sequence"),
            ("地层对比", 1, "stratigraphy"),
            ("地震预测", 2, "seismic"),
            ("井震联合 3D", 2, "geomodel"),
            ("编图画布", 3, "canvas"),
            ("数据制备", 3, "preparation"),
            ("成图审核", 3, "review"),
        )
        modules = self._group_node(
            "group/workspaces-modules",
            "兼容工作流",
            [
                _TreeNode(
                    f"module/{key}",
                    label,
                    {"kind": "module"},
                    navigation=(hub, key),
                )
                for label, hub, key in entries
            ],
        )
        self.footer_label.setText("工作区保存文档、分屏、面板与联动状态")
        return [joint, modules]

    def _well_group_node(self) -> _TreeNode:
        wells = list(getattr(self._project, "wells", None) or [])
        children = [
            _TreeNode(
                f"well/{getattr(well, 'id', '') or index}",
                str(getattr(well, "name", "") or "未命名井"),
                {
                    "kind": "well",
                    "object": well,
                    "well_name": getattr(well, "name", ""),
                },
            )
            for index, well in enumerate(wells)
        ]
        return self._group_node("group/wells", f"井数据 ({len(wells)})", children)

    def _seismic_group_node(self) -> _TreeNode:
        seismic = [r for r in self._visible_resources() if getattr(r, "type", "") == "seismic"]
        children = [self._resource_node(resource) for resource in seismic]
        return self._group_node("group/seismic", f"地震数据 ({len(seismic)})", children)

    def _horizon_group_node(self) -> _TreeNode:
        horizons = self._horizon_objects()
        children = [
            _TreeNode(
                f"horizon/{name}",
                name,
                {"kind": "horizon", "object": obj, "name": name},
            )
            for name, obj in horizons
        ]
        return self._group_node("group/horizons", f"层位 / 地层 ({len(horizons)})", children)

    def _interpretation_group_node(self) -> _TreeNode:
        # 目标层位只来自 stratigraphy.target_horizon；空则空态，不再回落 "D63"。
        active_name = self._active_horizon_name()
        if active_name:
            child = _TreeNode(
                f"interpretation/{active_name}",
                active_name,
                {"kind": "interpretation", "name": active_name},
            )
        else:
            child = _TreeNode(
                "interpretation/empty", "未设置目标层位", {"kind": "empty"}
            )
        return self._group_node("group/interpretation", "解释", [child])

    def _user_layer_group_node(self) -> _TreeNode | None:
        """人工编修图层（综合编修数字化成果），纳入数据管理。"""
        layers = list(getattr(self._project, "user_vector_layers", None) or [])
        if not layers:
            return None
        return self._group_node(
            "group/user-layers",
            f"编修数据 ({len(layers)})",
            [self._user_layer_node(layer) for layer in layers],
        )

    def _user_layer_node(self, layer) -> _TreeNode:
        kind = str(getattr(layer, "geometry_kind", "") or "")
        kind_label = _USER_LAYER_KIND_LABELS.get(kind, "矢量")
        feature_count = len(list(getattr(layer, "features", None) or []))
        return _TreeNode(
            f"uvlayer/{getattr(layer, 'id', '')}",
            f"{getattr(layer, 'name', '') or '编修图层'} · {kind_label} · {feature_count} 要素",
            {
                "kind": "user_vector_layer",
                "object": layer,
                "layer_id": str(getattr(layer, "id", "") or ""),
            },
            icon=_USER_LAYER_KIND_ICONS.get(kind, ""),
            check_state=(
                Qt.CheckState.Checked
                if getattr(layer, "visible", True)
                else Qt.CheckState.Unchecked
            ),
        )

    def _group_node(self, key: str, label: str, children: list[_TreeNode]) -> _TreeNode:
        return _TreeNode(
            key,
            label,
            {"kind": "group"},
            icon="folder.svg",
            children=self._cap_children(key, children),
        )

    @staticmethod
    def _cap_children(parent_key: str, children: list[_TreeNode]) -> list[_TreeNode]:
        """单组超过行数上限时截断，尾行提示剩余数量（B3 行数上限）。"""
        if len(children) <= _GROUP_ROW_LIMIT:
            return children
        remaining = len(children) - _GROUP_ROW_LIMIT
        tail = _TreeNode(
            f"{parent_key}/truncated",
            f"… 还有 {remaining} 项（用搜索过滤）",
            {"kind": "empty", "truncated": remaining},
        )
        return children[:_GROUP_ROW_LIMIT] + [tail]

    def _resource_node(self, resource) -> _TreeNode:
        return _TreeNode(
            f"resource/{getattr(resource, 'id', '')}",
            str(getattr(resource, "name", "") or "未命名数据"),
            {
                "kind": "resource",
                "object": resource,
                "resource_type": getattr(resource, "type", ""),
            },
            tooltip=str(getattr(resource, "path", "") or ""),
        )

    def _visible_resources(self) -> list[Any]:
        resources = list(getattr(self._project, "resources", None) or [])
        visible = []
        for resource in resources:
            path = str(getattr(resource, "path", "") or "")
            name = str(getattr(resource, "name", "") or "")
            if path.startswith(".preview_cache/") or name in {"meta.json", "payload.npz"}:
                continue
            visible.append(resource)
        return visible

    def _horizon_objects(self) -> list[tuple[str, Any]]:
        results: list[tuple[str, Any]] = []
        for entity in list(getattr(self._project, "geological_entities", None) or []):
            name = str(getattr(entity, "name", "") or "")
            if name:
                results.append((Path(name).stem, entity))
        if not results:
            for resource in self._visible_resources():
                if getattr(resource, "type", "") in {"horizon", "well_stratification"}:
                    results.append((Path(str(getattr(resource, "name", "") or "")).stem, resource))
        unique: dict[str, Any] = {}
        for name, obj in results:
            unique.setdefault(name, obj)
        return sorted(unique.items())

    def _active_horizon_name(self) -> str:
        stratigraphy = getattr(self._project, "stratigraphy", None)
        return str(getattr(stratigraphy, "target_horizon", "") or "")

    # ------------------------------------------------------------------
    # 差分更新（_TreeNode 树 ↔ QStandardItem 树）
    # ------------------------------------------------------------------

    def _reconcile(self, spec: list[_TreeNode]) -> None:
        scroll_bar = self.tree.verticalScrollBar()
        scroll_position = scroll_bar.value()
        selected_key = self._current_key()
        expanded_before = self._expanded_keys_from_view()
        selection = self.tree.selectionModel()
        view_blocked = self.tree.blockSignals(True)
        selection_blocked = selection.blockSignals(True) if selection is not None else False
        try:
            structure_changed = self._reconcile_children(self.model.invisibleRootItem(), spec)
            if self._structure_dirty:
                self._apply_default_expansion()
            else:
                self._restore_expansion(expanded_before)
            self._restore_selection(selected_key)
        finally:
            if selection is not None:
                selection.blockSignals(selection_blocked)
            self.tree.blockSignals(view_blocked)
        if structure_changed:
            self.tree.resizeColumnToContents(0)
        scroll_bar.setValue(scroll_position)

    def _reconcile_children(self, parent: QStandardItem, nodes: list[_TreeNode]) -> bool:
        """按 key 差分更新一层子行；返回结构是否变化（有增删行）。"""
        structure_changed = False
        spec_keys = {node.key for node in nodes}
        for row in range(parent.rowCount() - 1, -1, -1):
            child = parent.child(row)
            if child.data(KEY_ROLE) not in spec_keys:
                parent.removeRow(row)
                structure_changed = True
        existing: dict[str, QStandardItem] = {}
        for row in range(parent.rowCount()):
            child = parent.child(row)
            key = child.data(KEY_ROLE)
            if key is not None:
                existing[str(key)] = child
        for node in nodes:
            item = existing.get(node.key)
            if item is None:
                item = self._create_item(node)
                parent.appendRow(item)
                structure_changed = True
            else:
                self._update_item(item, node)
            if self._reconcile_children(item, node.children):
                structure_changed = True
        return structure_changed

    def _create_item(self, node: _TreeNode) -> QStandardItem:
        item = QStandardItem(node.label)
        item.setData(node.payload, OBJECT_ROLE)
        item.setData(node.key, KEY_ROLE)
        if node.icon:
            item.setData(node.icon, ICON_ROLE)
            item.setIcon(workstation_icon(node.icon))
        if node.tooltip:
            item.setToolTip(node.tooltip)
        if node.navigation is not None:
            item.setData(tuple(node.navigation), NAVIGATION_ROLE)
        if node.check_state is not None:
            item.setCheckable(True)
            item.setCheckState(node.check_state)
        return item

    def _update_item(self, item: QStandardItem, node: _TreeNode) -> None:
        if item.text() != node.label:
            item.setText(node.label)
        item.setData(node.payload, OBJECT_ROLE)
        tooltip = item.toolTip() if item.toolTip() else ""
        if tooltip != node.tooltip:
            item.setToolTip(node.tooltip)
        if node.navigation is not None:
            item.setData(tuple(node.navigation), NAVIGATION_ROLE)
        else:
            item.setData(None, NAVIGATION_ROLE)
        if node.icon != str(item.data(ICON_ROLE) or ""):
            if node.icon:
                item.setData(node.icon, ICON_ROLE)
                item.setIcon(workstation_icon(node.icon))
            else:
                item.setData(None, ICON_ROLE)
                item.setIcon(QIcon())
        if node.check_state is None:
            if item.isCheckable():
                item.setCheckable(False)
        else:
            if not item.isCheckable():
                item.setCheckable(True)
            if item.checkState() != node.check_state:
                item.setCheckState(node.check_state)

    def _apply_default_expansion(self) -> None:
        """结构重置（模式/工程切换）：默认展开到深度 1（与旧行为一致）。"""
        self._structure_dirty = False
        expanded: set[str] = set()

        def walk(item: QStandardItem, depth: int) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                if depth <= 1:
                    index = self.proxy_index_for_item(child)
                    if index.isValid():
                        self.tree.setExpanded(index, True)
                    key = child.data(KEY_ROLE)
                    if key is not None:
                        expanded.add(str(key))
                walk(child, depth + 1)

        walk(self.model.invisibleRootItem(), 0)
        self._expanded_keys = expanded

    def _restore_expansion(self, keys: set[str]) -> None:
        self._expanded_keys = set(keys)
        for key in keys:
            item = self._find_item_by_key(key)
            if item is None:
                continue
            index = self.proxy_index_for_item(item)
            if index.isValid():
                self.tree.setExpanded(index, True)

    def _restore_selection(self, key: str | None) -> None:
        index = None
        if key is not None:
            item = self._find_item_by_key(key)
            if item is not None:
                index = self.proxy_index_for_item(item)
        selection = self.tree.selectionModel()
        if index is not None and index.isValid():
            selection.setCurrentIndex(
                index, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        else:
            selection.clearSelection()
            selection.clearCurrentIndex()

    def _expanded_keys_from_view(self) -> set[str]:
        keys: set[str] = set()

        def walk(item: QStandardItem) -> None:
            for row in range(item.rowCount()):
                child = item.child(row)
                index = self.proxy_index_for_item(child)
                key = child.data(KEY_ROLE)
                if key is not None and index.isValid() and self.tree.isExpanded(index):
                    keys.add(str(key))
                walk(child)

        walk(self.model.invisibleRootItem())
        return keys

    def _current_key(self) -> str | None:
        selection = self.tree.selectionModel()
        if selection is None:
            return None
        item = self._source_item(selection.currentIndex())
        if item is None:
            return None
        key = item.data(KEY_ROLE)
        return str(key) if key is not None else None

    def _find_item_by_key(self, key: str) -> QStandardItem | None:
        def walk(item: QStandardItem) -> QStandardItem | None:
            for row in range(item.rowCount()):
                child = item.child(row)
                if child.data(KEY_ROLE) == key:
                    return child
                found = walk(child)
                if found is not None:
                    return found
            return None

        return walk(self.model.invisibleRootItem())

    def find_item(self, key: str) -> QStandardItem | None:
        """按稳定 key 查找行（测试/接线用）。"""
        return self._find_item_by_key(key)

    def proxy_index_for_item(self, item: QStandardItem):
        """source item → 代理视图索引（测试/接线用）。"""
        return self.proxy.mapFromSource(self.model.indexFromItem(item))

    # ------------------------------------------------------------------
    # 搜索与右键菜单
    # ------------------------------------------------------------------

    def _apply_search_filter(self) -> None:
        self.proxy.setFilterFixedString(self.search_box.text())

    def _show_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        menu = self._build_context_menu(index)
        if menu is None:
            return
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _build_context_menu(self, proxy_index) -> QMenu | None:
        """所有节点统一的上下文菜单（唯一构建点，B3）。"""
        item = self._source_item(proxy_index)
        if item is None:
            return None
        payload = dict(item.data(OBJECT_ROLE) or {})
        kind = str(payload.get("kind") or "")
        label = item.text()
        menu = QMenu(self.tree)
        open_action = menu.addAction("打开")
        open_action.triggered.connect(
            lambda _checked=False, idx=proxy_index: self._on_activated(idx)
        )
        copy_action = menu.addAction("复制名称")
        copy_action.triggered.connect(
            lambda _checked=False, text=label: QApplication.clipboard().setText(text)
        )
        if kind == "well":
            joint_action = menu.addAction("井震联合解释")
            joint_action.triggered.connect(
                lambda _checked=False: self.joint_workspace_requested.emit()
            )
        elif kind in {"resource", "layer", "user_vector_layer"}:
            activate_action = menu.addAction("激活")
            activate_action.triggered.connect(
                lambda _checked=False, p=payload: self.object_activated.emit(p)
            )
        return menu

    # ------------------------------------------------------------------
    # 选择/激活（与旧行为一致）
    # ------------------------------------------------------------------

    def _source_item(self, proxy_index) -> QStandardItem | None:
        if not proxy_index.isValid():
            return None
        return self.model.itemFromIndex(self.proxy.mapToSource(proxy_index))

    def _on_current_changed(self, current, _previous) -> None:
        item = self._source_item(current)
        if item is not None:
            self.object_selected.emit(item.data(OBJECT_ROLE))

    def _on_activated(self, index) -> None:
        item = self._source_item(index)
        if item is None:
            return
        navigation = item.data(NAVIGATION_ROLE)
        if navigation:
            self.navigation_requested.emit(int(navigation[0]), str(navigation[1]))
            return
        payload = item.data(OBJECT_ROLE) or {}
        if payload.get("kind") == "workspace" and payload.get("workspace") == "joint":
            self.joint_workspace_requested.emit()
            return
        self.object_activated.emit(payload)
