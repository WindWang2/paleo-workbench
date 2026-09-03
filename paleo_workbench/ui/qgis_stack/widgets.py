"""桥地址 ↔ PySide6 控件的唯一转换点（No QWidget crosses the boundary 的落地）。"""
from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import QVBoxLayout, QWidget


def cpp_pointer(widget: QWidget) -> int:
    """PySide6 控件 → C++ QWidget 地址。"""
    return int(shiboken6.getCppPointer(widget)[0])


def wrap_widget(address: int) -> QWidget:
    """C++ QWidget 地址 → PySide6 控件（所有权移交，随父对象销毁）。"""
    return shiboken6.wrapInstance(address, QWidget)


class QgisCanvasHost(QWidget):
    """把 QgsMapCanvas 嵌进 PySide6 布局的宿主。"""

    def __init__(self, stack, parent=None):
        super().__init__(parent)
        self.stack = stack
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas_address: int = stack.create_canvas()
        self.canvas = wrap_widget(self.canvas_address)
        layout.addWidget(self.canvas)
