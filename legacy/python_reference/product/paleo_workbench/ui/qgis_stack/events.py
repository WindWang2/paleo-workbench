"""桥回调 → Qt Signal。桥回调在 GUI 线程但直接回 Python 层，统一经
QTimer.singleShot(0, …) 重排队，避免在桥调用栈深处触发槽函数。

V8 M9（#951 根因类）：singleShot 必须带 QObject context——裸 lambda 在
本对象析构后仍会被定时器唤醒，向已销毁的 C++ 对象 emit 即崩溃
（QTimerInfoList::activateTimers → notifyInternal2 路径）。带 context
的重载在 context 销毁时取消投递；防御性再包一层 RuntimeError 守卫，
任何时序下都不向死对象发信号。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class StackEvents(QObject):
    extent_changed = Signal(float, float, float, float)
    map_position_changed = Signal(float, float)

    def attach(self, stack, canvas_address: int) -> None:
        stack.set_extent_callback(
            canvas_address,
            lambda xmin, ymin, xmax, ymax: self._requeue(
                lambda: self.extent_changed.emit(xmin, ymin, xmax, ymax)
            ),
        )
        stack.set_xy_callback(
            canvas_address,
            lambda x, y: self._requeue(
                lambda: self.map_position_changed.emit(x, y)
            ),
        )

    def _requeue(self, emit) -> None:
        context = self
        QTimer.singleShot(
            0, context,
            lambda: _safe_emit(context, emit),
        )


def _safe_emit(context: QObject, emit) -> None:
    """在投递时刻校验对象存活；shiboken 已销毁对象直接放弃（不崩溃）。"""
    try:
        emit()
    except RuntimeError:
        # C++ 对象在 singleShot 排队与触发之间被销毁——丢弃这次投递。
        pass
