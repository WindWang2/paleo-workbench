"""按钮组件（V5-U2）。

变体经 objectName 映射到全局 QSS 中已有的按钮词汇（PrimaryButton /
SecondaryButton / WorkstationTertiaryButton / PwbDangerButton），
不自带样式表——主题切换由全局样式表重载自然生效。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from paleo_workbench.ui.workstation.common import workstation_icon

#: variant → 全局 QSS objectName（existing vocabulary, zero duplication）
VARIANT_OBJECT_NAMES = {
    "primary": "PrimaryButton",
    "secondary": "SecondaryButton",
    "tertiary": "WorkstationTertiaryButton",
    "danger": "PwbDangerButton",
}


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    for w in (widget,):
        style.unpolish(w)
        style.polish(w)


class PwbButton(QPushButton):
    """语义变体按钮。

    variant: primary（主命令）/ secondary（常规）/ tertiary（低强调）/
    danger（破坏性动作，红描边、hover 反白）。
    """

    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "secondary",
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if icon_name:
            self.setIcon(workstation_icon(icon_name))
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        if variant not in VARIANT_OBJECT_NAMES:
            variant = "secondary"
        self.setObjectName(VARIANT_OBJECT_NAMES[variant])
        self._variant = variant
        _repolish(self)

    @property
    def variant(self) -> str:
        return getattr(self, "_variant", "secondary")


class PwbToolButton(QToolButton):
    """图标（+可选文字）工具按钮，走全局 QToolButton QSS。

    ``chrome=True`` 时使用 WorkstationContextButton 词汇（app bar /
    context bar 中的扁平 chrome 按钮）。图标由仓库 SVG 经主题感知
    染色工厂提供（DPR 感知）。
    """

    def __init__(
        self,
        icon_name: str | None = None,
        text: str = "",
        *,
        checkable: bool = False,
        chrome: bool = False,
        icon_color: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setCheckable(checkable)
        if chrome:
            self.setObjectName("WorkstationContextButton")
        if icon_name:
            self.setIcon(workstation_icon(icon_name, icon_color))
        if text:
            self.setText(text)
            self.setToolButtonStyle(
                Qt.ToolButtonStyle.TextBesideIcon if icon_name else Qt.ToolButtonStyle.TextOnly
            )
        elif icon_name:
            self.setToolButtonStyle(Qt.ToolButtonStyle.IconOnly)


class PwbSplitButton(QFrame):
    """主动作 + 下拉菜单的分段按钮。

    左段为 SecondaryButton 语义的普通按钮（``clicked``），右段为仅承载
    菜单的箭头段（InstantPopup，不触发 clicked）。
    """

    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        *,
        icon_name: str | None = None,
        menu: QMenu | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PwbSplitButton")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._main = PwbButton(text, variant="secondary", icon_name=icon_name)
        self._main.clicked.connect(self.clicked)
        self._arrow = QToolButton(self)
        self._arrow.setObjectName("PwbSplitArrow")
        self._arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._arrow.setIcon(workstation_icon("chevron-down.svg"))
        self._arrow.setAutoRaise(True)
        layout.addWidget(self._main)
        layout.addWidget(self._arrow)
        if menu is not None:
            self.set_menu(menu)

    def set_menu(self, menu: QMenu) -> None:
        self._arrow.setMenu(menu)

    def menu(self) -> QMenu | None:
        return self._arrow.menu()

    def set_enabled_all(self, enabled: bool) -> None:
        self._main.setEnabled(enabled)
        self._arrow.setEnabled(enabled)

    def connect_main(self, slot) -> None:
        """主动作槽位（等价 ``clicked.connect``，供调用方少引一个信号）。"""
        self.clicked.connect(slot)


def repolish_tree(widget: QObject) -> None:  # pragma: no cover - 便利函数
    """对 *widget* 子树做 unpolish/polish（动态属性变化后手动触发）。"""
    for child in widget.findChildren(QWidget):
        _repolish(child)
