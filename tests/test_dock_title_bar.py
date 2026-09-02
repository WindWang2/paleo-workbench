"""Offscreen coverage for custom Workstation dock title bars."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow

from paleo_workbench.ui.workstation.dock_title_bar import (
    DockTitleBar,
    install_dock_title_bar,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_host(qapp):
    host = QMainWindow()
    host.resize(800, 600)
    dock = QDockWidget("检查器", host)
    dock.setWidget(QLabel("body"))
    host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    bar = install_dock_title_bar(dock, "检查器")
    return host, dock, bar


def test_install_dock_title_bar_sets_widget(qapp):
    host, dock, bar = _make_host(qapp)
    assert isinstance(bar, DockTitleBar)
    assert dock.titleBarWidget() is bar
    assert bar.title() == "检查器"
    # offscreen 未 show 时 isVisible() 恒 False；断言「未被显式隐藏」。
    assert bar._float_btn.isVisibleTo(bar)
    assert bar._close_btn.isVisibleTo(bar)


def test_float_toggle_via_title_bar(qapp):
    host, dock, bar = _make_host(qapp)
    assert not dock.isFloating()
    bar._toggle_float()
    assert dock.isFloating()
    bar._toggle_float()
    assert not dock.isFloating()


def _press(bar, pos=QPoint(10, 10)):
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        bar.mapToGlobal(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _move(bar, pos, global_pos):
    return QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        global_pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_docked_drag_tears_off_floating_window(qapp, qtbot):
    """#1122: 停靠态拖动标题栏超过阈值应撕出为浮动窗。"""
    host, dock, bar = _make_host(qapp)
    host.show()
    qtbot.waitForWindowShown(host)
    assert not dock.isFloating()

    bar.mousePressEvent(_press(bar))
    threshold = QApplication.startDragDistance() + 4
    far = QPoint(bar.width() // 2 + threshold, bar.height() // 2)
    bar.mouseMoveEvent(_move(bar, far, bar.mapToGlobal(far)))
    assert dock.isFloating()

    # 继续拖动移动浮动窗位置。
    before = dock.pos()
    further = QPoint(far.x() + 40, far.y() + 30)
    bar.mouseMoveEvent(_move(bar, further, bar.mapToGlobal(further)))
    assert dock.pos() != before

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        further,
        bar.mapToGlobal(further),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    bar.mouseReleaseEvent(release)
    assert dock.isFloating()


def test_docked_drag_below_threshold_stays_docked(qapp, qtbot):
    host, dock, bar = _make_host(qapp)
    host.show()
    qtbot.waitForWindowShown(host)
    bar.mousePressEvent(_press(bar, QPoint(10, 10)))
    near = QPoint(13, 12)  # 距按下点 manhattan 距离 5 < startDragDistance(10)
    bar.mouseMoveEvent(_move(bar, near, bar.mapToGlobal(near)))
    assert not dock.isFloating()


def test_features_changed_syncs_button_visibility(qapp):
    """features 去掉 Closable 后关闭按钮应隐藏（featuresChanged 接线）。"""
    host, dock, bar = _make_host(qapp)
    assert bar._close_btn.isVisibleTo(bar)
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    assert not bar._close_btn.isVisibleTo(bar)
    assert bar._float_btn.isVisibleTo(bar)
