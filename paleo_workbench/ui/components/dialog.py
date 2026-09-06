"""对话框基类（V5-U4）：统一标题层级、内容布局与标准按钮盒。

此前 12 个 QDialog 各自维护手工按钮与近似重复的"玻璃拟态"局部样式表；
V5 统一为：全局 QSS 承载外观（QDialog/QPushButton 已有规则），本基类
只负责结构 —— 内容区 + QDialogButtonBox（主命令可为 primary/danger）。
破坏性动作确认 = ``danger=True``（红描边按钮）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens


class PwbDialog(QDialog):
    """统一对话框。

    用法::

        dlg = PwbDialog("导出图件")
        dlg.add_content(...)
        dlg.add_buttons(ok_text="导出")
        if dlg.exec() == QDialog.DialogCode.Accepted: ...

    或在构造时直接给出按钮（给出任一按钮参数即自动装配按钮盒）::

        dlg = PwbDialog("删除图层?", ok_text="删除", danger=True)

    ``buttons`` 传 QDialogButtonBox.StandardButton 组合；``danger=True``
    时确认按钮使用 PwbDangerButton 词汇（破坏性动作）。
    """

    def __init__(
        self,
        title: str,
        *,
        parent: QWidget | None = None,
        buttons: QDialogButtonBox.StandardButton | None = None,
        ok_text: str | None = None,
        cancel_text: str | None = None,
        danger: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("PwbDialog")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(tokens.SPACE_2XL, tokens.SPACE_XL, tokens.SPACE_2XL, tokens.SPACE_L)
        self._outer.setSpacing(tokens.SPACE_L)
        # 注意：按钮盒默认加在内容**之后**——先 add_content 再给出按钮参数，
        # 或构造时给出参数（按钮盒已就位，内容 add 到其上方）。
        if buttons is not None or ok_text is not None or cancel_text is not None or danger:
            if buttons is None:
                buttons = (
                    QDialogButtonBox.StandardButton.Ok
                    | QDialogButtonBox.StandardButton.Cancel
                )
            self.add_buttons(buttons, ok_text=ok_text, cancel_text=cancel_text, danger=danger)

    # -- content -------------------------------------------------------------

    @property
    def content_layout(self) -> QVBoxLayout:
        """内容区布局（按钮盒之上）。"""
        return self._outer

    def add_content(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._outer.addWidget(widget, stretch)
        return widget

    def add_content_spacing(self, height: int = tokens.SPACE_M) -> None:
        self._outer.addSpacerItem(QSpacerItem(height, height))

    # -- buttons ---------------------------------------------------------------

    def add_buttons(
        self,
        buttons: QDialogButtonBox.StandardButton = (
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        ),
        *,
        ok_text: str | None = None,
        cancel_text: str | None = None,
        danger: bool = False,
    ) -> QDialogButtonBox:
        box = QDialogButtonBox(buttons, parent=self)
        if ok_text is not None:
            ok = box.button(QDialogButtonBox.StandardButton.Ok)
            if ok is not None:
                ok.setText(ok_text)
                ok.setObjectName("PwbDangerButton" if danger else "PrimaryButton")
        if cancel_text is not None:
            cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel is not None:
                cancel.setText(cancel_text)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._outer.addWidget(box)
        self.button_box = box
        return box

    def button(self, role: QDialogButtonBox.StandardButton):
        return self.button_box.button(role) if hasattr(self, "button_box") else None
