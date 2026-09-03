"""桥回调 → Qt Signal。桥回调在 GUI 线程但直接回 Python 层，统一经
QTimer.singleShot(0, …) 重排队，避免在桥调用栈深处触发槽函数。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class StackEvents(QObject):
    extent_changed = Signal(float, float, float, float)
    map_position_changed = Signal(float, float)

    def attach(self, stack, canvas_address: int) -> None:
        stack.set_extent_callback(
            canvas_address,
            lambda xmin, ymin, xmax, ymax: QTimer.singleShot(
                0, lambda: self.extent_changed.emit(xmin, ymin, xmax, ymax)
            ),
        )
        stack.set_xy_callback(
            canvas_address,
            lambda x, y: QTimer.singleShot(
                0, lambda: self.map_position_changed.emit(x, y)
            ),
        )
