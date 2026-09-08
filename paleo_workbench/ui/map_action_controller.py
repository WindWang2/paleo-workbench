"""Central QAction state for the GIS authoring workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import QToolBar, QWidget

from paleo_workbench.ui.workstation.tool_surface import ToolAvailability

__all__ = ["MapActionController", "MapActionState"]

_MAP_ICONS_DIR = Path(__file__).parent / "assets" / "icons" / "map"
_ICONS_DIR = Path(__file__).parent / "assets" / "icons"


def _map_icon(action_id: str, *, fallback: str = "") -> QIcon:
    """Load a toolbar icon (map/ 优先，assets 根目录兜底)，缺失返回空 QIcon。"""
    for name in (action_id, fallback):
        if not name:
            continue
        for directory in (_MAP_ICONS_DIR, _ICONS_DIR):
            path = directory / f"{name}.svg"
            if path.exists():
                return QIcon(str(path))
    return QIcon()


@dataclass(frozen=True, slots=True)
class MapActionState:
    has_active_vector_layer: bool = False
    vector_layer_writable: bool = False
    editing: bool = False
    selected_count: int = 0
    compatible_polygon_count: int = 0
    can_undo: bool = False
    can_redo: bool = False
    can_previous_extent: bool = False
    can_next_extent: bool = False


class MapActionController(QObject):
    """One source of QAction checked/enabled state across menus and toolbars."""

    tool_requested = Signal(str)
    command_requested = Signal(str)

    _TOOL_IDS = (
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon", "move_feature", "vertex",
        "reshape",
    )

    _LABELS = {
        "pan": "平移", "zoom_in": "放大", "zoom_out": "缩小",
        "full_extent": "全图", "previous_extent": "上一视图", "next_extent": "下一视图",
        "refresh": "刷新", "identify": "识别", "select": "选择",
        "select_rectangle": "框选", "measure_distance": "测距",
        "clear_selection": "清除选择", "select_all": "全选", "invert_selection": "反选",
        "toggle_editing": "开始编辑", "save_edits": "保存编辑", "rollback": "回滚",
        "add_point": "添加点", "add_line": "添加线", "add_polygon": "添加面",
        "move_feature": "移动要素", "vertex": "节点编辑", "delete_selected": "删除所选",
        "reshape": "重塑",
        "undo": "撤销", "redo": "重做", "split": "分割", "merge": "合并",
        "snapping": "捕捉", "topology": "拓扑编辑", "cancel": "取消",
        # V7 专业分组扩展（goal §6 Layer/Symbology/Factor/QA/Layout·Export）
        "layer_new": "新建图层", "reference_import": "导入参考图层",
        "layer_properties": "图层属性", "attribute_table": "属性表",
        "layer_zoom": "缩放到图层", "layer_export": "导出图层",
        "symbology": "符号系统", "style_manager": "样式库",
        "factor_workbench": "单因素工作台", "factor_overlay": "叠加等值线",
        "qa_run": "运行 QC", "map_product_assemble": "生成成果",
        "map_export": "导出图面",
    }

    #: 扩展面动作的图标（id → map/ 或 assets 根目录下的 svg 名）。
    _SURFACE_ICONS = {
        "layer_new": "tree-add-layer", "reference_import": "btn-import",
        "layer_properties": "tree-properties", "attribute_table": "attribute_table",
        "layer_zoom": "tree-zoom", "layer_export": "tree-export",
        "symbology": "rb-colorbar", "style_manager": "rb-settings",
        "factor_workbench": "rb-grid", "factor_overlay": "btn-contour-draft",
        "qa_run": "rb-qc", "map_product_assemble": "rb-finalize",
        "map_export": "rb-export",
    }

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._build_actions()
        self.update_state(MapActionState())

    def _action(self, action_id: str, *, checkable: bool = False, shortcut: str = "") -> QAction:
        icon_name = self._SURFACE_ICONS.get(action_id, action_id)
        action = QAction(_map_icon(icon_name), self._LABELS[action_id], self)
        action.setObjectName(f"MapAction:{action_id}")
        action.setCheckable(checkable)
        action.setToolTip(self._LABELS[action_id])
        action.setStatusTip(self._LABELS[action_id])
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            # The window also binds Ctrl+S to project save. Keep this mapping
            # action's shortcut confined to the editing widget tree so the two
            # don't collide into an ambiguous "Ctrl+S" shortcut.
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.actions[action_id] = action
        return action

    def _build_actions(self) -> None:
        for action_id in self._TOOL_IDS:
            action = self._action(action_id, checkable=True)
            self._tool_group.addAction(action)
            action.triggered.connect(lambda checked=False, name=action_id: checked and self.tool_requested.emit(name))
        for action_id, shortcut in (
            ("full_extent", ""), ("previous_extent", ""), ("next_extent", ""), ("refresh", ""),
            ("clear_selection", ""), ("select_all", ""), ("invert_selection", ""), ("toggle_editing", ""),
            ("save_edits", "Ctrl+S"), ("rollback", ""), ("delete_selected", "Delete"),
            ("undo", "Ctrl+Z"), ("redo", "Ctrl+Shift+Z"), ("split", ""), ("merge", ""),
            ("snapping", ""), ("topology", ""), ("cancel", "Esc"),
        ):
            action = self._action(action_id, checkable=action_id in {"snapping", "topology", "toggle_editing"}, shortcut=shortcut)
            action.triggered.connect(lambda checked=False, name=action_id: self.command_requested.emit(name))
        self.actions["pan"].setChecked(True)
        # V7 专业分组扩展（Layer / Symbology / Factor / QA / Layout·Export）。
        for action_id in self._SURFACE_ICONS:
            action = self._action(action_id)
            action.triggered.connect(lambda checked=False, name=action_id: self.command_requested.emit(name))

    def update_state(self, state: MapActionState) -> None:
        vector = state.has_active_vector_layer
        editable = vector and state.vector_layer_writable
        editing = editable and state.editing
        for action_id in ("identify", "select", "select_rectangle", "clear_selection", "select_all", "invert_selection"):
            self.actions[action_id].setEnabled(vector)
        self.actions["toggle_editing"].setEnabled(editable)
        if self.actions["toggle_editing"].isChecked() != editing:
            self.actions["toggle_editing"].blockSignals(True)
            self.actions["toggle_editing"].setChecked(editing)
            self.actions["toggle_editing"].blockSignals(False)
        for action_id in ("save_edits", "rollback", "add_point", "add_line", "add_polygon", "move_feature", "vertex", "snapping", "topology"):
            self.actions[action_id].setEnabled(editing)
        self.actions["undo"].setEnabled(editing and state.can_undo)
        self.actions["redo"].setEnabled(editing and state.can_redo)
        self.actions["delete_selected"].setEnabled(editing and state.selected_count > 0)
        self.actions["split"].setEnabled(editing and state.selected_count > 0)
        self.actions["merge"].setEnabled(editing and state.compatible_polygon_count >= 2)
        self.actions["previous_extent"].setEnabled(state.can_previous_extent)
        self.actions["next_extent"].setEnabled(state.can_next_extent)
        self.actions["cancel"].setEnabled(True)

    def apply_availability(self, availability) -> None:
        """Apply ``{tool_id: ToolAvailability}`` from the V7 evaluator.

        Supersedes :meth:`update_state` on the workstation path: enabled state
        and checkmarks come from the single evaluator, and every disabled
        action carries its human-readable reason in the tooltip/status tip
        (Goal V7 §3: never a bare ``setEnabled(False)``). ``update_state``
        remains for the legacy authoring page host.
        """
        for tool_id, result in dict(availability).items():
            action = self.actions.get(tool_id)
            if action is None:
                continue  # evaluator may cover tools this host has no action for
            label = self._LABELS.get(tool_id, tool_id)
            action.setEnabled(bool(result.enabled))
            action.setVisible(bool(result.visible))
            reason = getattr(result, "reason", None) or getattr(result, "disabled_reason", "") or ""
            if reason:
                action.setToolTip(f"{label}\n{reason}")
                action.setStatusTip(f"{label}（{reason}）")
            else:
                action.setToolTip(label)
                action.setStatusTip(label)
            checked = getattr(result, "checked", None)
            if checked is not None and action.isCheckable() and action.isChecked() != bool(checked):
                action.blockSignals(True)
                action.setChecked(bool(checked))
                action.blockSignals(False)

    def toolbar(
        self,
        title: str,
        action_ids: tuple[str | tuple[str, ...], ...],
        parent: QWidget | None = None,
    ) -> QToolBar:
        """Build an icon-only toolbar.

        ``action_ids`` entries are either a single action id or a nested tuple
        of ids forming a logical group; a separator is inserted between groups.
        Flat tuples of ids remain supported for compatibility.
        """
        toolbar = QToolBar(title, parent)
        toolbar.setObjectName(f"MapToolbar:{title.replace(' ', '')}")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(18, 18))
        for index, entry in enumerate(action_ids):
            ids = entry if isinstance(entry, tuple) else (entry,)
            if index and isinstance(entry, tuple):
                toolbar.addSeparator()
            for action_id in ids:
                toolbar.addAction(self.actions[action_id])
        return toolbar
