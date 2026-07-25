"""Qt platform session policy (Wayland default, no forced xcb)."""

from __future__ import annotations

import os

import pytest


def test_clears_xcb_on_wayland_session(monkeypatch):
    from paleo_workbench import qt_platform as mod

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.delenv("PALEO_FORCE_XCB", raising=False)

    assert mod.configure_qt_platform_for_session(warn=False) is None
    assert "QT_QPA_PLATFORM" not in os.environ


def test_preserves_offscreen(monkeypatch):
    from paleo_workbench import qt_platform as mod

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    assert mod.configure_qt_platform_for_session(warn=False) == "offscreen"
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"


def test_force_xcb_opt_in(monkeypatch):
    from paleo_workbench import qt_platform as mod

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.setenv("PALEO_FORCE_XCB", "1")

    assert mod.configure_qt_platform_for_session(warn=False) == "xcb"
    assert os.environ.get("QT_QPA_PLATFORM") == "xcb"
