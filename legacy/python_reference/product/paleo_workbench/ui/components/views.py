"""视图与命令条组件（V5-U2）：密度感知表格/树与统一 context 工具条。

PwbTableView / PwbTreeView 的行高从密度访问器实时取值，并在
theme_changed（携带 density）时重算——修掉「切密度行高不缩」的系统病。
"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QTreeView,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.ui.components.buttons import PwbToolButton
from paleo_workbench.ui.components.inputs import current_density
from paleo_workbench.ui.theme import theme_manager


class _DensityRowDelegate(QStyledItemDelegate):
    """行高 = tokens.row_height(density)（每 paint 取当前密度）。"""

    def sizeHint(self, option, index) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), tokens.row_height(current_density())))


class _DensityViewMixin:
    """公共装配：密度 delegate + theme_changed 订阅 + 头部语义。"""

    _delegate: QStyledItemDelegate

    def _install_density(self, view) -> None:
        self._delegate = _DensityRowDelegate(view)
        view.setItemDelegate(self._delegate)
        view.setAlternatingRowColors(True)
        view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        view.setWordWrap(False)
        theme_manager.theme_changed.connect(self._on_density_changed)

    def _on_density_changed(self, _theme: str, _density: str) -> None:
        view = getattr(self, "_view", None) or self
        model = view.model()
        if model is None:
            return
        # 让所有行重新询问 delegate 的 sizeHint（新密度）
        if hasattr(view, "resizeRowsToContents"):
            view.resizeRowsToContents()
        view.viewport().update()


class PwbTableView(QTableView, _DensityViewMixin):
    """统一表格：密度感知行高、交替行、行选择、隐藏竖直头。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = self
        hh = self.horizontalHeader()
        hh.setDefaultSectionSize(120)
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(tokens.row_height(current_density()))
        self.setShowGrid(False)
        self._install_density(self)


class PwbTreeView(QTreeView, _DensityViewMixin):
    """统一树：密度感知行高、交替行、紧凑缩进。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = self
        self.setUniformRowHeights(True)
        self.setIndentation(14)
        self.setHeaderHidden(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._install_density(self)


class PwbCommandBar(QFrame):
    """统一 context 工具条（V3 context bar 视觉，hairline 底边）。

    用 ``add_button`` 建钮 / ``add_separator`` 分簇 / ``add_widget``
    放自定义控件；不自带业务。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PwbCommandBar")
        self.setFixedHeight(tokens.toolbar_height(current_density()))
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 2)
        self._layout.setSpacing(2)
        theme_manager.theme_changed.connect(self._on_theme_changed_bar)

    def _on_theme_changed_bar(self, _theme: str, _density: str) -> None:
        self.setFixedHeight(tokens.toolbar_height(current_density()))

    def add_button(
        self,
        icon_name: str,
        text: str = "",
        *,
        tooltip: str = "",
        checkable: bool = False,
        slot=None,
    ) -> QToolButton:
        btn = PwbToolButton(icon_name, text, checkable=checkable, chrome=True, parent=self)
        if tooltip:
            btn.setToolTip(tooltip)
        if slot is not None:
            btn.clicked.connect(slot)
        self._layout.addWidget(btn)
        return btn

    def add_separator(self) -> QFrame:
        sep = QFrame(self)
        sep.setObjectName("PwbCommandSeparator")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        sep.setFixedWidth(1)
        sep.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(sep)
        return sep

    def add_widget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._layout.addWidget(widget, stretch)
        return widget

    def add_stretch(self) -> None:
        self._layout.addStretch(1)
