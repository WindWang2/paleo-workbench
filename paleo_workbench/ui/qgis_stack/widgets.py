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


class QgisLayerTreeHost(QWidget):
    """承载 QGIS 原生 QgsLayerTreeView 的 Qt 宿主（地址边界单点还原）。"""

    def __init__(self, stack, canvas_address: int, parent=None) -> None:
        super().__init__(parent)
        self.stack = stack
        self.canvas_address = canvas_address
        self.tree_view_address = stack.create_layer_tree_view(canvas_address)
        self.tree_view = shiboken6.wrapInstance(self.tree_view_address, QWidget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tree_view)
