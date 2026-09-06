"""标题 / 检查器分区 / 属性编辑器（V5-U2）。

PwbSectionHeader 统一 25+ 处复制的「accent 左条 + 标题」QLabel 样板；
PwbPropertyEditor / PwbInspectorSection 沿用检查器既有的
WorkstationInspectorValue / WorkstationPanelTitle 词汇。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui.components.buttons import PwbToolButton


class PwbSectionHeader(QLabel):
    """区块标题（accent 左条），全局 QSS ``QLabel#PwbSectionHeader``。"""

    def __init__(self, text: str = "", *, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("PwbSectionHeader")


class PwbInspectorSection(QFrame):
    """检查器/面板内可折叠分区：标题行（含可选折叠钮）+ 内容容器。

    标题沿用 WorkstationPanelTitle 词汇；折叠钮为仓库 chevron 图标。
    """

    def __init__(self, title: str = "", *, collapsible: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PwbInspectorSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        header = QWidget(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._title = QLabel(title, header)
        self._title.setObjectName("WorkstationPanelTitle")
        row.addWidget(self._title)
        row.addStretch(1)
        self._toggle: QToolButton | None = None
        if collapsible:
            self._toggle = PwbToolButton("chevron-down.svg", chrome=False, parent=header)
            self._toggle.setFixedSize(22, 22)
            self._toggle.clicked.connect(self.toggle_collapsed)
            row.addWidget(self._toggle)
        outer.addWidget(header)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        outer.addWidget(self._content)
        self._collapsed = False

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._content.setVisible(not collapsed)
        if self._toggle is not None:
            icon = "chevron-right.svg" if collapsed else "chevron-down.svg"
            from paleo_workbench.ui.workstation.common import workstation_icon

            self._toggle.setIcon(workstation_icon(icon))


class PwbPropertyEditor(QWidget):
    """label / value 属性行集合（检查器语义）。

    值行为只读可选取的 QLineEdit（``WorkstationInspectorValue`` 词汇）；
    ``value`` 为 None/空串 → ``missing`` 属性（dimmed italic em-dash）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)

    def add_header(self, text: str) -> PwbSectionHeader:
        header = PwbSectionHeader(text, parent=self)
        self._layout.addWidget(header)
        return header

    def add_row(self, label: str, value, *, unit: str = "", placeholder: str = "") -> QLineEdit:
        row = QWidget(self)
        form = QHBoxLayout(row)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        label_w = QLabel(label, row)
        label_w.setObjectName("WorkFieldLabel")
        editor = QLineEdit(row)
        editor.setObjectName("WorkstationInspectorValue")
        editor.setReadOnly(True)  # QLineEdit 只读态原生支持鼠标/键盘选取
        if value is None or (isinstance(value, str) and not value.strip()):
            editor.setProperty("missing", True)
            editor.setText("—" if not placeholder else placeholder)
        else:
            text = f"{value} {unit}".strip() if unit else f"{value}"
            editor.setProperty("missing", False)
            editor.setText(text)
        form.addWidget(label_w, 0)
        form.addWidget(editor, 1)
        self._layout.addWidget(row)
        return editor

    def add_widget_row(self, label: str, widget: QWidget) -> QWidget:
        row = QWidget(self)
        form = QHBoxLayout(row)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        label_w = QLabel(label, row)
        label_w.setObjectName("WorkFieldLabel")
        form.addWidget(label_w, 0)
        form.addWidget(widget, 1)
        self._layout.addWidget(row)
        return row

    def add_stretch(self) -> None:
        self._layout.addStretch(1)


def section_header(text: str, parent: QWidget | None = None) -> QLabel:
    """便捷函数：与新组件同视觉的标题 QLabel（迁移旧 ``MapDockTitle`` 样板）。"""
    return PwbSectionHeader(text, parent=parent)
