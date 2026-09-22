"""QGIS 原生地图栈的 PySide6 嵌入层（M1）。"""
from paleo_workbench.ui.qgis_stack.display_canvas import (
    QgisDisplayCanvas,
    create_display_canvas,
)
from paleo_workbench.ui.qgis_stack.widgets import QgisCanvasHost

__all__ = ["QgisCanvasHost", "QgisDisplayCanvas", "create_display_canvas"]
