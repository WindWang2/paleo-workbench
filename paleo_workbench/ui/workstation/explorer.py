from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QTreeView,
    QVBoxLayout,
)

from paleo_workbench.ui.workstation.common import workstation_icon

OBJECT_ROLE = Qt.ItemDataRole.UserRole + 1
NAVIGATION_ROLE = Qt.ItemDataRole.UserRole + 2


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
        self.setMaximumWidth(420)
        self._project = project
        self._mode = "project"

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
        self.search_box.textChanged.connect(self.proxy.setFilterFixedString)

        self.tree = QTreeView(self)
        self.tree.setObjectName("WorkstationExplorerTree")
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.doubleClicked.connect(self._on_activated)
        outer.addWidget(self.tree, 1)

        self.footer_label = QLabel("", self)
        self.footer_label.setObjectName("WorkstationPanelFootnote")
        outer.addWidget(self.footer_label)

        self.refresh()

    def set_project(self, project) -> None:
        self._project = project
        self.refresh()

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in self._MODE_TITLES else "project"
        self.title_label.setText(self._MODE_TITLES[self._mode])
        self.search_box.setPlaceholderText(
            "搜索项目数据..." if self._mode in {"data", "search"} else "筛选当前对象..."
        )
        self.refresh()
        if self._mode in {"search", "data"}:
            self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def focus_search(self) -> None:
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()

    def refresh(self) -> None:
        self.model.clear()
        builders = {
            "project": self._build_project,
            "data": self._build_data,
            "layers": self._build_layers,
            "search": self._build_data,
            "history": self._build_history,
            "workspaces": self._build_workspaces,
        }
        builders.get(self._mode, self._build_project)()
        self.tree.expandToDepth(1)
        self.tree.resizeColumnToContents(0)

    def _root(self) -> QStandardItem:
        name = str(getattr(getattr(self._project, "meta", None), "name", "") or "未命名工程")
        root = self._item(name, {"kind": "project", "object": self._project})
        root.setIcon(workstation_icon("folder-open.svg"))
        self.model.appendRow(root)
        return root

    def _build_project(self) -> None:
        root = self._root()
        project = self._project
        if project is None:
            self.footer_label.setText("未打开工程")
            return
        root.appendRow(self._item("概览", {"kind": "overview"}, navigation=(0, "overview")))
        area_name = str(getattr(getattr(project, "workarea", None), "name", "") or "未命名工区")
        area = self._item(f"工区 · {area_name}", {"kind": "area", "object": getattr(project, "workarea", None)})
        root.appendRow(area)

        wells = list(getattr(project, "wells", None) or [])
        well_group = self._group(f"井数据 ({len(wells)})")
        for well in wells:
            well_group.appendRow(
                self._item(
                    str(getattr(well, "name", "") or "未命名井"),
                    {"kind": "well", "object": well, "well_name": getattr(well, "name", "")},
                )
            )
        area.appendRow(well_group)

        seismic = [r for r in self._visible_resources() if getattr(r, "type", "") == "seismic"]
        seismic_group = self._group(f"地震数据 ({len(seismic)})")
        for resource in seismic:
            seismic_group.appendRow(self._resource_item(resource))
        area.appendRow(seismic_group)

        horizons = self._horizon_objects()
        horizon_group = self._group(f"层位 / 地层 ({len(horizons)})")
        for horizon in horizons:
            horizon_group.appendRow(
                self._item(
                    horizon[0],
                    {"kind": "horizon", "object": horizon[1], "name": horizon[0]},
                )
            )
        area.appendRow(horizon_group)

        interpretation_group = self._group("解释")
        active_name = self._active_horizon_name() or "D63"
        interpretation_group.appendRow(
            self._item(
                active_name,
                {"kind": "interpretation", "name": active_name},
            )
        )
        area.appendRow(interpretation_group)

        results = self._group("成果")
        for label, key in (("剖面", "section"), ("平面图", "map"), ("数据导出", "export")):
            results.appendRow(self._item(label, {"kind": "result", "result_type": key}))
        area.appendRow(results)
        self.footer_label.setText(f"{len(wells)} 口井 · {len(seismic)} 个地震体 · {len(horizons)} 个层位")

    def _build_data(self) -> None:
        root = self._root()
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
            group = self._group(f"{labels.get(key, key)} ({len(resources)})")
            for resource in resources:
                group.appendRow(self._resource_item(resource))
            root.appendRow(group)
            count += len(resources)
        self.footer_label.setText(f"{count} 个项目数据对象；存储缓存默认隐藏")

    def _build_layers(self) -> None:
        root = self._item("井震联合剖面: A12 - D63", {"kind": "document"})
        self.model.appendRow(root)
        layers = (
            ("D63 层位解释", "horizon", True),
            ("断层解释", "fault", True),
            ("井位 (A1-A20)", "wells", True),
            ("A12 测井轨道", "well_log", True),
            ("同步拾取光标", "cursor", True),
        )
        for label, layer_type, checked in layers:
            item = self._item(label, {"kind": "layer", "layer_type": layer_type})
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            root.appendRow(item)
        self.footer_label.setText("图层仅影响当前文档，不删除项目数据")

    def _build_history(self) -> None:
        root = self._root()
        versions = self._group("解释版本")
        versions.appendRow(self._item("D63 · v1_current", {"kind": "version", "name": "v1_current"}))
        root.appendRow(versions)
        exports = self._group("成果输出")
        for artifact in list(getattr(self._project, "export_artifacts", None) or []):
            exports.appendRow(self._item(str(getattr(artifact, "name", "") or "导出成果"), {"kind": "export", "object": artifact}))
        if exports.rowCount() == 0:
            exports.appendRow(self._item("尚无导出成果", {"kind": "empty"}))
        root.appendRow(exports)
        self.footer_label.setText("解释、校验与导出历史")

    def _build_workspaces(self) -> None:
        joint = self._item("井震联合解释", {"kind": "workspace", "workspace": "joint"})
        joint.setIcon(workstation_icon("visualization.svg"))
        self.model.appendRow(joint)
        modules = self._group("兼容工作流")
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
        for label, hub, key in entries:
            modules.appendRow(self._item(label, {"kind": "module"}, navigation=(hub, key)))
        self.model.appendRow(modules)
        self.footer_label.setText("工作区保存文档、分屏、面板与联动状态")

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

    def _resource_item(self, resource) -> QStandardItem:
        item = self._item(
            str(getattr(resource, "name", "") or "未命名数据"),
            {"kind": "resource", "object": resource, "resource_type": getattr(resource, "type", "")},
        )
        item.setToolTip(str(getattr(resource, "path", "") or ""))
        return item

    def _group(self, label: str) -> QStandardItem:
        item = self._item(label, {"kind": "group"})
        item.setIcon(workstation_icon("folder.svg"))
        return item

    def _item(self, label: str, payload: dict[str, Any], navigation=None) -> QStandardItem:
        item = QStandardItem(label)
        item.setData(payload, OBJECT_ROLE)
        if navigation is not None:
            item.setData(tuple(navigation), NAVIGATION_ROLE)
        return item

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
