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


def canvas_viewport(canvas: QWidget) -> QWidget | None:
    """QgsMapCanvas 视口。桥侧 wrap 成 QWidget，需按 QGraphicsView 再取 viewport。

    比例尺/指北针必须画在视口上，否则会被原生地图窗口盖住。
    """
    getter = getattr(canvas, "viewport", None)
    if callable(getter):
        try:
            viewport = getter()
            if isinstance(viewport, QWidget):
                return viewport
        except Exception:
            pass
    try:
        from PySide6.QtWidgets import QGraphicsView

        view = shiboken6.wrapInstance(int(shiboken6.getCppPointer(canvas)[0]), QGraphicsView)
        viewport = view.viewport()
        if isinstance(viewport, QWidget) and hasattr(view, "viewport"):
            return viewport
    except Exception:
        pass
    for child in canvas.findChildren(QWidget):
        if child.objectName() == "qt_scrollarea_viewport":
            return child
    return None


def as_tree_view(widget: QWidget):
    """QgsLayerTreeView wrap 成 QTreeView（展开/装饰根节点）。"""
    from PySide6.QtWidgets import QTreeView

    if isinstance(widget, QTreeView):
        return widget
    try:
        view = shiboken6.wrapInstance(int(shiboken6.getCppPointer(widget)[0]), QTreeView)
        if callable(getattr(view, "setRootIsDecorated", None)):
            return view
    except Exception:
        return None
    return None


def _layer_tree_branch_qss() -> str:
    from pathlib import Path

    icon_dir = Path(__file__).resolve().parents[1] / "assets" / "icons" / "map"
    closed = (icon_dir / "tree-branch-closed.svg").as_posix()
    opened = (icon_dir / "tree-branch-open.svg").as_posix()
    return (
        "QTreeView { show-decoration-selected: 1; }\n"
        "QTreeView::branch { background: transparent; }\n"
        "QTreeView::branch:has-children:!has-siblings:closed,"
        "QTreeView::branch:closed:has-children:has-siblings {"
        f' border-image: none; image: url("{closed}"); }}\n'
        "QTreeView::branch:open:has-children:!has-siblings,"
        "QTreeView::branch:open:has-children:has-siblings {"
        f' border-image: none; image: url("{opened}"); }}\n'
    )


def configure_layer_tree_view(widget: QWidget) -> None:
    """展开箭头 + 展开全部组（wrap 成 QWidget 时走属性和 QGIS expandAllNodes）。"""
    if widget is None:
        return
    widget.setProperty("rootIsDecorated", True)
    widget.setProperty("itemsExpandable", True)
    widget.setProperty("expandsOnDoubleClick", True)
    widget.setProperty("indentation", 20)
    widget.setStyleSheet(_layer_tree_branch_qss())
    from PySide6.QtCore import QMetaObject, Qt

    QMetaObject.invokeMethod(
        widget, "expandAllNodes", Qt.ConnectionType.DirectConnection)


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
        self.tree_view = wrap_widget(self.tree_view_address)
        configure_layer_tree_view(self.tree_view)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tree_view)
