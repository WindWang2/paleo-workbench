"""Regression — 打开/切换工程报错：迟到的 shutdown 在已销毁部件上崩溃.

失败停止后的 restore 路径（``_restore_current_shell_after_failed_stop``
→ ``_refresh_shell``）会对 ``app_shell._all_pages`` 里的页面包装器再跑
一遍 ``shutdown_workers``。若页面的 C++ 树已被 ``DeferredDelete`` 销毁
（包装器仍是 Python 活对象），``DataPage._set_import_running`` 一碰
``import_btn`` 就抛 ``RuntimeError: Internal C++ object already deleted``
——用户看到的就是「打开工程报错」。关闭协议必须容忍迟到的二次调用。

注意：刻意不复用 ``qtbot.addWidget``——其拆卸回调会对已被本测试销毁的
C++ 对象再调 ``close()``，恰是本测试要隔离的竞态本身。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("shiboken6")

import shiboken6

from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.data_page import DataPage


def _project() -> ProjectDocument:
    project = ProjectDocument.new("关机竞态", region="HZ26")
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0, project_x=1.0, project_y=2.0)
    )
    return project


def test_shutdown_after_deferred_delete_does_not_raise(qtbot):
    page = DataPage(_project())
    page.show()
    qtbot.waitExposed(page)

    page.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(page))

    # app_shell._all_pages 持有的包装器此时就是这种状态：Python 活对象、
    # C++ 已销毁。协议级 shutdown 不得抛 RuntimeError。
    assert page.shutdown_workers() is True


def test_set_import_running_with_dead_toolbar_is_state_only(qtbot):
    page = DataPage(_project())
    page.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(page))

    # 状态位仍要如实更新；只允许跳过对死按钮的 Qt 调用。
    page._set_import_running(False)
    assert page._import_in_progress is False


def test_dead_log_handler_does_not_crash_logging(qtbot):
    """死壳未走 shutdown 时，包 logger 上遗留的 QtLogHandler 已随壳销毁；
    下一次壳构建记日志（如「QGIS 画布栈初始化失败」）绝不能被死 handler
    的 signal emit 炸掉——那正是「打开工程报错」的直接根因。"""
    import logging

    from paleo_workbench.ui.workstation.process_hub import LogViewer

    viewer = LogViewer()
    source = logging.getLogger("paleo_workbench")
    assert viewer._log_handler in source.handlers

    viewer.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(viewer))
    assert viewer._log_handler in source.handlers, "死壳路径不会摘 handler（前提）"

    # 不应抛 RuntimeError（handler 的 C++ 对象已随壳销毁）
    source.warning("死 handler 探针")

    # 测试卫生：把死 handler 从包 logger 上摘掉，不污染后续用例
    source.removeHandler(viewer._log_handler)
