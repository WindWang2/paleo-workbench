"""Offscreen coverage for custom Workstation dock title bars."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
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


def test_install_dock_title_bar_sets_widget(qapp):
    host = QMainWindow()
    dock = QDockWidget("检查器", host)
    dock.setWidget(QLabel("body"))
    bar = install_dock_title_bar(dock, "检查器")
    assert isinstance(bar, DockTitleBar)
    assert dock.titleBarWidget() is bar
    assert bar.title() == "检查器"
    assert bar._float_btn.isVisible()
    assert bar._close_btn.isVisible()


def test_float_toggle_via_title_bar(qapp):
    host = QMainWindow()
    host.resize(800, 600)
    dock = QDockWidget("图层管理", host)
    dock.setWidget(QLabel("layers"))
    host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    bar = install_dock_title_bar(dock)
    assert not dock.isFloating()
    bar._toggle_float()
    assert dock.isFloating()
    bar._toggle_float()
    assert not dock.isFloating()
