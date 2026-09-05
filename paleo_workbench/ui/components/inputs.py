"""输入组件（V5-U2）：搜索框与表单行助手。"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from paleo_workbench import tokens
from paleo_workbench.ui.theme import theme_manager
from paleo_workbench.ui.workstation.common import workstation_icon


class PwbSearchBox(QLineEdit):
    """带清除动作的搜索框（复用全局 ``SearchBox`` QSS 词汇）。

    空文本时隐藏清除动作；清除动作用仓库 ``rb-clear`` 图标，替代此前
    叠放 "✕" QLabel 的手写实现。
    """

    def __init__(
        self,
        placeholder: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SearchBox")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(False)
        self._clear = None
        self._refresh_clear_action()
        self.textChanged.connect(lambda _t: self._refresh_clear_action())

    def _refresh_clear_action(self) -> None:
        from PySide6.QtGui import QAction

        has_text = bool(self.text())
        if has_text and self._clear is None:
            self._clear = QAction(self)
            self._clear.setIcon(workstation_icon("rb-clear.svg"))
            self._clear.setToolTip("清除")
            self._clear.triggered.connect(self.clear)
            self.addAction(self._clear, QLineEdit.ActionPosition.TrailingPosition)
        elif not has_text and self._clear is not None:
            self.removeAction(self._clear)
            self._clear = None


def current_density() -> str:
    """当前密度（组件 metrics 订阅用；未知态回落 comfortable）。"""
    try:
        return theme_manager.density.value
    except Exception:  # noqa: BLE001 — 无 app 环境回落 comfortable
        return "comfortable"


def make_form_row(
    label: str,
    editor: QWidget,
    *,
    label_w: QLabel | None = None,
    unit: str = "",
    stretch_editor: bool = True,
) -> QWidget:
    """标准表单行：WorkFieldLabel + 编辑器（+ 可选单位后缀标签）。

    统一此前 TaskPanelBase._add_value / factor Row / geo3d 配置行三种方言。
    """
    row = QWidget()
    form = QHBoxLayout(row)
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(tokens.SPACE_M)
    lab = label_w or QLabel(label, row)
    if label_w is None:
        lab.setObjectName("WorkFieldLabel")
    form.addWidget(lab, 0)
    form.addWidget(editor, 1 if stretch_editor else 0)
    if unit:
        unit_label = QLabel(unit, row)
        unit_label.setObjectName("WorkFieldLabel")
        form.addWidget(unit_label, 0)
    return row
