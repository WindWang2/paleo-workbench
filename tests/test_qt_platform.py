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


@pytest.fixture(autouse=True)
def _clean_egl_vendor_env(monkeypatch):
    # Keep the pinning side effect out of the process env / other tests, and
    # make sure the headless early-return does not mask the pinning branch.
    monkeypatch.delenv("__EGL_VENDOR_LIBRARY_FILENAMES", raising=False)
    monkeypatch.delenv("PALEO_ALLOW_NVIDIA_EGL", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)


def test_pins_mesa_egl_on_wayland_session(monkeypatch, tmp_path):
    from paleo_workbench import qt_platform as mod

    vendor_json = tmp_path / "50_mesa.json"
    vendor_json.write_text("{}\n")
    monkeypatch.setattr(mod, "_MESA_EGL_VENDOR_CANDIDATES", (str(vendor_json),))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    assert mod.configure_qt_platform_for_session(warn=False) is None
    assert os.environ["__EGL_VENDOR_LIBRARY_FILENAMES"] == str(vendor_json)


def test_nvidia_egl_opt_out_skips_pinning(monkeypatch, tmp_path):
    from paleo_workbench import qt_platform as mod

    vendor_json = tmp_path / "50_mesa.json"
    vendor_json.write_text("{}\n")
    monkeypatch.setattr(mod, "_MESA_EGL_VENDOR_CANDIDATES", (str(vendor_json),))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("PALEO_ALLOW_NVIDIA_EGL", "1")

    mod.configure_qt_platform_for_session(warn=False)
    assert "__EGL_VENDOR_LIBRARY_FILENAMES" not in os.environ


def test_existing_egl_vendor_env_is_respected(monkeypatch):
    from paleo_workbench import qt_platform as mod

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("__EGL_VENDOR_LIBRARY_FILENAMES", "/custom/vendor.json")

    mod.configure_qt_platform_for_session(warn=False)
    assert (
        os.environ["__EGL_VENDOR_LIBRARY_FILENAMES"] == "/custom/vendor.json"
    )


def test_no_pinning_outside_wayland(monkeypatch, tmp_path):
    from paleo_workbench import qt_platform as mod

    vendor_json = tmp_path / "50_mesa.json"
    vendor_json.write_text("{}\n")
    monkeypatch.setattr(mod, "_MESA_EGL_VENDOR_CANDIDATES", (str(vendor_json),))
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    mod.configure_qt_platform_for_session(warn=False)
    assert "__EGL_VENDOR_LIBRARY_FILENAMES" not in os.environ
