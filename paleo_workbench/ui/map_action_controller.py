"""Central QAction state for the GIS authoring workspace."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import QToolBar, QWidget

from paleo_workbench.mapping.action_registry import ACTION_SPECS
from paleo_workbench.mapping.tool_help import (
    TOOL_LABELS,
    TOOL_SHORTCUTS,
)

__all__ = ["MapActionController"]


def _map_icon(action_id: str, *, fallback: str = "") -> QIcon:
    """Load a toolbar icon (map/ 优先，assets 根目录兜底)，缺失返回空 QIcon。

    E2：经主题感知 tint 工厂加载——中性灰色字形按当前主题 TEXT_SECONDARY
    重染；多色/语义色 SVG 原样返回（拉平会破坏图义）。tint 工厂懒加载：
    workstation 包 init 经 composite_document 模块级导入本模块，顶层
    import common 会成环。
    """
    from paleo_workbench.ui.workstation.common import tinted_map_icon

    for name in (action_id, fallback):
        if not name:
            continue
        icon = tinted_map_icon(name)
        if not icon.isNull():
            return icon
    return QIcon()


class MapActionController(QObject):
    """One source of QAction checked/enabled state across menus and toolbars."""

    tool_requested = Signal(str)
    command_requested = Signal(str)

    _TOOL_IDS = (
        "pan", "zoom_in", "zoom_out", "identify", "select", "select_rectangle",
        "measure_distance", "add_point", "add_line", "add_polygon", "move_feature", "vertex",
        "reshape", "add_ring", "add_part",
    )

    #: 命令面动作（区别于画布 MapTool：触发一次命令，不置 current_tool）。
    #: V10（#1256）：提为类常量——图标资产完整性与"无 surface-only 幽灵
    #: 动作"两条断言都要枚举这份清单，内联在 _build_actions 里无法审计。
    _COMMAND_IDS = (
        "full_extent", "previous_extent", "next_extent", "refresh",
        "clear_selection", "select_all", "invert_selection", "toggle_editing",
        "save_edits", "rollback", "delete_selected",
        "undo", "redo", "split", "merge",
        "duplicate_selected", "explode_multipart", "collect_multipart",
        "snapping", "topology", "cancel",
    )

    #: 词表单一来源（V8 M4：action_help.TOOL_LABELS；帮助/QAction 同名）。
    _LABELS = dict(TOOL_LABELS)

    #: 工具条第三段动作（layer/symbology/factor/qa/layout 组的扩展面命令
    #: + geometry 组的 repair_geometry）。V10 Milestone B：图标/身份登记
    #: 单一来源 = mapping.action_registry；此处只保留**构建顺序**。
    _SURFACE_EXTENSION_IDS = (
        "layer_new", "reference_import", "layer_properties", "attribute_table",
        "layer_zoom", "layer_export", "symbology", "style_manager",
        "factor_workbench", "factor_overlay", "qa_run", "map_product_assemble",
        "map_export", "repair_geometry",
    )

    #: id → svg 名（登记处派生；缺省回落 id 本名）。
    _SURFACE_ICONS = {
        tool_id: spec.icon for tool_id, spec in ACTION_SPECS.items()
    }

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._build_actions()

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
        # 快捷键单一来源（V8 M4：action_help.TOOL_SHORTCUTS；帮助镜像同源）。
        shortcut_registry = dict(TOOL_SHORTCUTS)
        for action_id in self._COMMAND_IDS:
            shortcut = shortcut_registry.get(action_id, "")
            action = self._action(action_id, checkable=action_id in {"snapping", "topology", "toggle_editing"}, shortcut=shortcut)
            action.triggered.connect(lambda checked=False, name=action_id: self.command_requested.emit(name))
        self.actions["pan"].setChecked(True)
        # V7 专业分组扩展（Layer / Symbology / Factor / QA / Layout·Export）。
        for action_id in self._SURFACE_EXTENSION_IDS:
            action = self._action(action_id)
            action.triggered.connect(lambda checked=False, name=action_id: self.command_requested.emit(name))

    def apply_availability(self, availability, *, help_texts=None) -> None:
        """Apply ``{tool_id: ToolAvailability}`` from the canonical evaluator.

        V8 M1：输入是 ``mapping.tool_availability.ToolAvailability``（唯一
        契约）——enabled/visible/checked 与禁用原因全部来自单一求值器，
        本方法只做 Qt 呈现（图标/tooltip/statusTip/勾选），不做业务判断。

        V8 M4：``help_texts`` 为 ``{tool_id: (tooltip, statusTip)}`` 覆盖
        （宿主用 ``action_help`` 从同一契约派生的解释文本）；缺省回落
        名称+原因两行式。
        """
        for tool_id, result in dict(availability).items():
            action = self.actions.get(tool_id)
            if action is None:
                continue  # evaluator may cover tools this host has no action for
            label = self._LABELS.get(tool_id, tool_id)
            action.setEnabled(bool(result.enabled))
            action.setVisible(bool(result.visible))
            override = (help_texts or {}).get(tool_id)
            if override is not None:
                tooltip, status_tip = override
                action.setToolTip(tooltip)
                action.setStatusTip(status_tip)
            else:
                reason = result.disabled_reason
                if reason:
                    action.setToolTip(f"{label}\n{reason}")
                    action.setStatusTip(f"{label}（{reason}）")
                else:
                    action.setToolTip(label)
                    action.setStatusTip(label)
            if action.isCheckable() and action.isChecked() != bool(result.checked):
                action.blockSignals(True)
                action.setChecked(bool(result.checked))
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
