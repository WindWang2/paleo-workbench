# -*- coding: utf-8 -*-
"""相/亚相/微相三级级联选择器 + 选择/词表管理对话框。

同一选择器组件三处复用（grill 共识 Q3-d）：绘制相带面完成弹窗、
属性表/检查器的相字段级联、选中要素「指定相带…」。任一级可停
（Q4-b：解释到哪填到哪，不逼假数据）；取消一律保留几何、属性留空
（Q6-a）。
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.facies_taxonomy import (
    FACIES_LEVEL_KEYS,
    LEVEL_LABELS,
    FaciesTaxonomy,
)

_EMPTY = ""  # 子级「不填/清空」哨兵


class FaciesBrushContext(QObject):
    """当前相带画刷（M2）：数字化捕获后自动赋值的持续装备状态。

    语义（00-decisions D10/D11）：装备四元组 = 词表选择 {facies,
    sub_facies, micro_facies} + 派生 level；未装备（未 armed）时捕获走
    既有模态对话框路径——本类只是新增的快路径，不改变旧路径行为。
    幂等装备（同值重复 equip）不重复广播，杜绝回环放大。
    """

    equipped_changed = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._selection: dict[str, str] | None = None

    @property
    def is_armed(self) -> bool:
        return self._selection is not None

    def selection(self) -> dict[str, str]:
        values = dict(self._selection or {})
        values.setdefault("facies", "")
        values.setdefault("sub_facies", "")
        values.setdefault("micro_facies", "")
        return values

    def equip(self, selection: Mapping[str, Any]) -> None:
        values = self.selection()
        values.update({
            "facies": str(selection.get("facies") or ""),
            "sub_facies": str(selection.get("sub_facies") or ""),
            "micro_facies": str(selection.get("micro_facies") or ""),
        })
        values.pop("level", None)
        values["level"] = FaciesTaxonomy.selection_level(values)
        if values == self._selection:
            return
        self._selection = values
        self.equipped_changed.emit(dict(values))

    def clear(self) -> None:
        if self._selection is None:
            return
        self._selection = None
        self.equipped_changed.emit({})


class FaciesCascadeSelector(QWidget):
    """三级级联选择器：相 → 亚相 → 微相，子级列表随父级过滤。

    子级组合框首项为空（不填）——选了相即可停；改父级时清空已选的
    更细级别（词表里子级身份依赖父链）。
    """

    def __init__(self, taxonomy: FaciesTaxonomy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._taxonomy = taxonomy
        self.setObjectName("FaciesCascadeSelector")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._combos: dict[str, QComboBox] = {}
        for level in FACIES_LEVEL_KEYS:
            row = QHBoxLayout()
            label = QLabel(f"{LEVEL_LABELS[level]}：", self)
            label.setMinimumWidth(48)
            combo = QComboBox(self)
            combo.setObjectName(f"FaciesLevel_{level}")
            row.addWidget(label)
            row.addWidget(combo, 1)
            layout.addLayout(row)
            self._combos[level] = combo

        self._combos["facies"].currentTextChanged.connect(
            lambda _text: self._on_parent_changed("facies"))
        self._combos["sub_facies"].currentTextChanged.connect(
            lambda _text: self._on_parent_changed("sub_facies"))
        self._repopulate()

    # -- 选项装配 -----------------------------------------------------------

    def _on_parent_changed(self, level: str) -> None:
        if level != "micro_facies":
            self._repopulate_level(FACIES_LEVEL_KEYS[FACIES_LEVEL_KEYS.index(level) + 1])

    def _repopulate(self) -> None:
        for level in FACIES_LEVEL_KEYS:
            self._repopulate_level(level)

    def _repopulate_level(self, level: str) -> None:
        combo = self._combos[level]
        parents = tuple(
            self._combos[FACIES_LEVEL_KEYS[idx]].currentText().strip()
            for idx in range(FACIES_LEVEL_KEYS.index(level))
        )
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        if level != "facies":
            combo.addItem(_EMPTY, _EMPTY)  # 不填：任一级可停
        for name in self._taxonomy.names(level, parents):
            combo.addItem(name, name)
        # 父链变化后原值可能不在候选里（词表覆盖/父变更）——保不住就清空
        index = combo.findText(current) if current else -1
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        # 子级联动清理由 currentTextChanged 在取消阻塞后统一触发
        child = FACIES_LEVEL_KEYS[FACIES_LEVEL_KEYS.index(level) + 1] \
            if level != "micro_facies" else None
        if child is not None and combo.currentText() != current:
            self._repopulate_level(child)

    # -- 选择读写 -----------------------------------------------------------

    def selection(self) -> dict[str, str]:
        return {
            level: self._combos[level].currentText().strip()
            for level in FACIES_LEVEL_KEYS
        }

    def set_selection(self, attributes: Mapping[str, Any]) -> None:
        """按要素三字段恢复选择（非法组合尽量保上级，保不住清空）。"""
        values = FaciesTaxonomy.selection_from_attributes(attributes)
        self._combos["facies"].setCurrentText(values["facies"])
        self._repopulate_level("sub_facies")
        self._combos["sub_facies"].setCurrentText(values["sub_facies"])
        self._repopulate_level("micro_facies")
        self._combos["micro_facies"].setCurrentText(values["micro_facies"])

    def set_default_depth(self, level: str) -> None:
        """按图层级别预选到目标深度（不动已选值，仅作为弹窗默认提示）。"""
        _ = level  # 深度锚定由对话框标题呈现；组合框保持全三段可见


class FaciesSelectionDialog(QDialog):
    """绘制完成/指定相带共用的选择对话框（模态）。

    确定返回三字段 + ``level``（最细已选）；取消/关闭/Esc 返回 None
    （调用方保留几何、属性留空——Q6-a）。
    """

    def __init__(
        self,
        taxonomy: FaciesTaxonomy,
        current: Mapping[str, Any] | None = None,
        *,
        title: str = "指定相带",
        anchor_level: str = "facies",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FaciesSelectionDialog")
        depth_hint = {
            "facies": "（本图层为相图：一般选到相即可）",
            "sub_facies": "（本图层为亚相图：建议选到亚相）",
            "micro_facies": "（本图层为微相图：建议选到微相）",
        }.get(anchor_level, "")
        self.setWindowTitle(f"{title} {depth_hint}")
        layout = QVBoxLayout(self)
        self._selector = FaciesCascadeSelector(taxonomy, self)
        if current:
            self._selector.set_selection(current)
        layout.addWidget(self._selector)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> dict[str, str]:
        values = self._selector.selection()
        values["level"] = FaciesTaxonomy.selection_level(values)
        return values


class FaciesChangeDialog(QDialog):
    """编辑期换相对话框（**列表形态**）：搜索 + 相列表 + 确定/取消。

    用户诉求：弹窗是相的列表，支持选择，然后确定，从而更换相图 feature
    的特性/label。与 :class:`FaciesSelectionDialog`（三级下拉）的差别只在
    呈现面——写入契约完全一致（``selection()`` 三字段 + ``level``），宿主
    两处入口共用同一消费模式。

    列表列的是**该图层的锚定级别**（相图列相、亚相图列亚相）；更细级别
    用可选细化行指定，未指定时按「新相生效即清空亚相/微相」处理（与右键
    快捷换相同一语义）。
    """

    def __init__(
        self,
        taxonomy: FaciesTaxonomy,
        current: Mapping[str, Any] | None = None,
        *,
        title: str = "更改相",
        count: int = 1,
        anchor_level: str = "facies",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FaciesChangeDialog")
        self._taxonomy = taxonomy
        anchor = anchor_level if anchor_level in FACIES_LEVEL_KEYS else "facies"
        self._anchor = anchor
        self._lower = list(FACIES_LEVEL_KEYS[FACIES_LEVEL_KEYS.index(anchor) + 1:])
        self._all_names = list(taxonomy.names(anchor))
        values = FaciesTaxonomy.selection_from_attributes(dict(current or {}))
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        scope = QLabel(
            (f"将修改 {count} 个要素的{LEVEL_LABELS[anchor]}属性"
             if count > 1 else f"修改该要素的{LEVEL_LABELS[anchor]}属性"), self)
        scope.setObjectName("FaciesChangeScope")
        layout.addWidget(scope)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText(f"搜索{LEVEL_LABELS[anchor]}…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self._refill())
        layout.addWidget(self._search)

        self._list = QListWidget(self)
        self._list.setObjectName("FaciesChangeList")
        self._list.setMinimumHeight(220)
        self._list.currentTextChanged.connect(self._on_list_changed)
        layout.addWidget(self._list, 1)

        self._refine_rows: dict[str, QComboBox] = {}
        if self._lower:
            refine = QHBoxLayout()
            hint = QLabel("细化（可选）：", self)
            hint.setMinimumWidth(84)
            refine.addWidget(hint)
            for level in self._lower:
                combo = QComboBox(self)
                combo.setObjectName(f"FaciesRefine_{level}")
                combo.currentTextChanged.connect(
                    lambda _text, lv=level: self._repopulate_lower(lv))
                refine.addWidget(combo, 1)
                self._refine_rows[level] = combo
            refine.addStretch(1)
            layout.addLayout(refine)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refill(str(values.get(anchor) or ""))

    # -- 列表装配 -----------------------------------------------------------

    def _refill(self, preselected: str = "") -> None:
        needle = self._search.text().strip()
        keep = preselected or self.selected_facies()
        self._list.blockSignals(True)
        self._list.clear()
        for name in self._all_names:
            if needle and needle not in name:
                continue
            self._list.addItem(QListWidgetItem(name))
        self._list.blockSignals(False)
        target = keep or (self._list.item(0).text() if self._list.count() else "")
        if target:
            self.select_facies(target)
        self._repopulate_lower(self._lower[0] if self._lower else "")

    def _on_list_changed(self, name: str) -> None:
        self._repopulate_lower(self._lower[0] if self._lower else "")
        _ = name

    def _repopulate_lower(self, level: str) -> None:
        if not level or level not in self._refine_rows:
            return
        index = FACIES_LEVEL_KEYS.index(level)
        parents = tuple(self._selection_chain()[:index])
        combo = self._refine_rows[level]
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_EMPTY, _EMPTY)  # 任一级可停（不逼假数据）
        for name in self._taxonomy.names(level, parents):
            combo.addItem(name, name)
        found = combo.findText(current) if current else -1
        combo.setCurrentIndex(found if found >= 0 else 0)
        combo.blockSignals(False)
        nxt = self._lower[self._lower.index(level) + 1:] if level in self._lower else []
        if nxt:
            self._repopulate_lower(nxt[0])

    def _selection_chain(self) -> list[str]:
        chain = [self.selected_facies()]
        for level in self._lower:
            combo = self._refine_rows.get(level)
            chain.append(combo.currentText().strip() if combo is not None else "")
        return chain

    # -- 读写面（宿主/测试共用）---------------------------------------------

    def listed_facies(self) -> list[str]:
        return [self._list.item(row).text() for row in range(self._list.count())]

    def selected_facies(self) -> str:
        item = self._list.currentItem()
        return item.text() if item is not None else ""

    def select_facies(self, name: str) -> None:
        for row in range(self._list.count()):
            if self._list.item(row).text() == str(name):
                self._list.setCurrentRow(row)
                return

    def set_search_text(self, text: str) -> None:
        self._search.setText(str(text))

    def selection(self) -> dict[str, str]:
        chain = self._selection_chain()
        values = dict(zip(FACIES_LEVEL_KEYS, chain))
        # 锚定级别以下才允许细化：锚定级别以上保持空（不是本图层语义）。
        for level in FACIES_LEVEL_KEYS[:FACIES_LEVEL_KEYS.index(self._anchor)]:
            values[level] = ""
        values["level"] = FaciesTaxonomy.selection_level(values)
        return values


class FaciesTaxonomyDialog(QDialog):
    """词表管理（grill 共识 Q8-b）：三级树查看 + GeoJSON 导入 + 恢复内置。"""

    taxonomy_accepted = False  # True = 用户确认了新词表（覆盖/恢复）

    def __init__(self, taxonomy: FaciesTaxonomy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FaciesTaxonomyDialog")
        self.setWindowTitle("相分类词表")
        self._incoming: FaciesTaxonomy | None = None
        self.taxonomy_accepted = False

        layout = QVBoxLayout(self)
        n_f, n_s, n_m = taxonomy.counts()
        self._summary = QLabel(
            f"当前词表（{self._source_label(taxonomy)}）："
            f"相 {n_f} · 亚相 {n_s} · 微相 {n_m}", self)
        layout.addWidget(self._summary)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["名称", "子级数"])
        self._tree.setColumnWidth(0, 260)
        layout.addWidget(self._tree, 1)
        self._fill_tree(taxonomy)

        actions = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton
        self._import_button = QPushButton("从 GeoJSON 导入…", self)
        self._import_button.clicked.connect(self._on_import)
        reset_button = QPushButton("恢复内置默认", self)
        reset_button.clicked.connect(self._on_reset)
        actions.addWidget(self._import_button)
        actions.addWidget(reset_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # 初始尺寸：树区直接可见（伸展内容不被 sizeHint 压扁）。
        self._tree.setMinimumHeight(300)
        self.resize(560, 560)

    @staticmethod
    def _source_label(taxonomy: FaciesTaxonomy) -> str:
        return "工程覆盖" if taxonomy.source == "project" else "内置默认"

    def _fill_tree(self, taxonomy: FaciesTaxonomy) -> None:
        self._tree.clear()
        tree = taxonomy.to_project_dict().get("tree") or {}

        def walk(node: Mapping[str, Any], parent: QTreeWidgetItem | None) -> None:
            for name, children in node.items():
                item = QTreeWidgetItem([str(name), str(len(children or {}))])
                (parent.addChild(item) if parent is not None
                 else self._tree.addTopLevelItem(item))
                walk(children or {}, item)

        walk(tree, None)
        self._tree.expandToDepth(0)

    def _on_import(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "导入参考相图 GeoJSON（相/亚相/微相兄弟组，可多选）", "",
            "GeoJSON (*.geojson *.json)")
        if not paths:
            return
        features: list[dict] = []
        for path in paths:
            try:
                with open(path, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, "导入失败", f"{path}：{exc}")
                return
            if isinstance(payload, Mapping):
                features.extend(payload.get("features") or [])
        taxonomy = FaciesTaxonomy.from_geojson_features(features)
        n_f, n_s, n_m = taxonomy.counts()
        if not n_f:
            QMessageBox.warning(
                self, "导入失败",
                "所选文件没有带 level/parent_id 属性的相图要素——"
                "无法重建三级词表")
            return
        self._incoming = taxonomy
        self._fill_tree(taxonomy)
        self._summary.setText(
            f"待应用（{self._source_label(taxonomy)}·导入预览）："
            f"相 {n_f} · 亚相 {n_s} · 微相 {n_m} —— 点「确定」生效")

    def _on_reset(self) -> None:
        taxonomy = FaciesTaxonomy.builtin()
        self._incoming = taxonomy
        self._fill_tree(taxonomy)
        n_f, n_s, n_m = taxonomy.counts()
        self._summary.setText(
            f"待应用（内置默认·恢复预览）：相 {n_f} · 亚相 {n_s} · 微相 {n_m}"
            " —— 点「确定」生效")

    def _on_accept(self) -> None:
        self.taxonomy_accepted = True
        self.accept()

    def result_taxonomy(self) -> FaciesTaxonomy | None:
        """用户确认的新词表（未改动/取消返回 None）。"""
        return self._incoming if self.taxonomy_accepted else None
