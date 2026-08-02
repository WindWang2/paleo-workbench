"""Smoke tests for Well Log Workstation L-shell (#216)."""

from __future__ import annotations

import os

import pytest

# Platform must be set before any QApplication in this process when possible.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from well_log_workstation.qt_platform import (  # noqa: E402
    configure_qt_platform_for_session,
    effective_qt_platform_hint,
)
from well_log_workstation.shell import WellLogWorkstationWindow  # noqa: E402


def test_configure_clears_xcb_on_wayland(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.delenv("WLWS_FORCE_XCB", raising=False)
    monkeypatch.delenv("PALEO_FORCE_XCB", raising=False)
    result = configure_qt_platform_for_session(warn=False)
    assert result is None
    assert "QT_QPA_PLATFORM" not in os.environ


def test_configure_keeps_offscreen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert configure_qt_platform_for_session(warn=False) == "offscreen"


def test_force_xcb_on_wayland(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.setenv("WLWS_FORCE_XCB", "1")
    assert configure_qt_platform_for_session(warn=False) == "xcb"


def test_shell_has_l_chrome(qtbot) -> None:
    win = WellLogWorkstationWindow()
    qtbot.addWidget(win)
    win.show()

    assert win.objectName() == "WellLogWorkstationWindow"
    assert win.workspace_tree.objectName() == "WorkspaceTree"
    assert win.document_tabs.objectName() == "DocumentTabs"
    assert win.template_list.objectName() == "TemplateList"
    assert win.tops_list.objectName() == "TopsList"

    menu_titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    for expected in ("文件", "图件", "图版", "导出", "帮助"):
        assert expected in menu_titles

    from PySide6.QtWidgets import QSplitter

    sp = win.findChild(QSplitter, "ShellSplitter")
    assert sp is not None
    assert sp.count() == 3

    assert win.document_tabs.count() >= 1
    msg = win.statusBar().currentMessage() or ""
    assert "Qt platform" in msg


def test_effective_hint_nonempty() -> None:
    assert len(effective_qt_platform_hint()) > 0
