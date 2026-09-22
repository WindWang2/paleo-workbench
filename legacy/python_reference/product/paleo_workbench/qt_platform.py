"""Qt platform plugin selection for desktop sessions.

Policy
------
- **Interactive app / local GUI tests**: do **not** force a platform. On modern
  Linux sessions Qt defaults to **Wayland** when ``WAYLAND_DISPLAY`` is set.
- **CI / headless**: callers may set ``QT_QPA_PLATFORM=offscreen`` (or
  ``minimal``). That is intentional and is left alone.
- **Never default to X11 (``xcb``)**. An accidental ``QT_QPA_PLATFORM=xcb`` on a
  Wayland session is cleared unless ``PALEO_FORCE_XCB=1`` (XWayland debug only).
- **On Wayland sessions EGL is pinned to the Mesa vendor** unless
  ``PALEO_ALLOW_NVIDIA_EGL=1``. glvnd prefers NVIDIA's vendor JSON, and in that
  configuration docking a GL-bearing panel (测井轨道 / 地震剖面) segfaults inside
  ``libnvidia-eglcore``; see :func:`_pin_mesa_egl_on_wayland`.

``DISPLAY`` may still be set under XWayland; that does **not** mean the session
is X11-native.
"""

from __future__ import annotations

import os
import sys
import warnings


_HEADLESS_PLATFORMS = frozenset(
    {"offscreen", "minimal", "minimalegl", "vnc", "null"}
)
_X11_PLATFORMS = frozenset({"xcb", "x11"})
_OPT_IN_FLAGS = frozenset({"1", "true", "yes"})
_MESA_EGL_VENDOR_CANDIDATES = (
    "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
    "/etc/glvnd/egl_vendor.d/50_mesa.json",
)


def _session_is_wayland() -> bool:
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland"


def _pin_mesa_egl_on_wayland(*, warn: bool = True) -> str | None:
    """Pin glvnd to the Mesa EGL vendor on Wayland sessions.

    PySide6's Qt resolves EGL through glvnd, whose vendor list prefers NVIDIA
    (``10_nvidia.json`` sorts before ``50_mesa.json``). In that configuration,
    docking a GL-bearing panel (测井轨道 / 地震剖面) delivers a synchronous paint
    to an embedded pyqtgraph GLViewWidget while dock teardown is still
    reparenting it between top-levels; ``paintGL`` then calls into
    ``libnvidia-eglcore`` with a dead context and the process dies with
    SIGSEGV (core-dump forensics 2026-09-06: two crashes, identical stacks).
    ``LIBGL_ALWAYS_SOFTWARE`` cannot prevent this — it is a Mesa-internal
    variable and never reaches the NVIDIA vendor library. Pinning glvnd to the
    Mesa vendor JSON keeps the crashing driver out of the process entirely;
    GL views fall back to llvmpipe. ``PALEO_ALLOW_NVIDIA_EGL=1`` keeps
    hardware GL (at the cost of the crash), and a pre-set
    ``__EGL_VENDOR_LIBRARY_FILENAMES`` is always respected.

    Returns the vendor JSON pinned, or ``None`` when untouched.
    """
    if not _session_is_wayland():
        return None
    if (
        os.environ.get("PALEO_ALLOW_NVIDIA_EGL", "").strip().lower()
        in _OPT_IN_FLAGS
    ):
        return None
    if os.environ.get("__EGL_VENDOR_LIBRARY_FILENAMES"):
        return None
    for candidate in _MESA_EGL_VENDOR_CANDIDATES:
        if os.path.isfile(candidate):
            os.environ["__EGL_VENDOR_LIBRARY_FILENAMES"] = candidate
            if warn:
                print(
                    "paleo_workbench: pinned EGL to Mesa ("
                    f"{candidate}) — NVIDIA EGL segfaults when docking GL panels "
                    "on Wayland (PALEO_ALLOW_NVIDIA_EGL=1 overrides).",
                    file=sys.stderr,
                )
            return candidate
    return None


def configure_qt_platform_for_session(*, warn: bool = True) -> str | None:
    """Normalize ``QT_QPA_PLATFORM`` for the current session.

    Returns the effective platform override after adjustment, or ``None`` if
    unset (Qt chooses: Wayland on Wayland sessions, etc.).

    Must run **before** the first ``QApplication`` / ``QGuiApplication`` is
    constructed.
    """
    raw = os.environ.get("QT_QPA_PLATFORM", "")
    plat = raw.strip().lower()

    if plat in _HEADLESS_PLATFORMS:
        return plat or None

    _pin_mesa_egl_on_wayland(warn=warn)

    if plat in _X11_PLATFORMS and _session_is_wayland():
        if os.environ.get("PALEO_FORCE_XCB", "").strip() in {"1", "true", "yes"}:
            return plat
        # Drop forced X11 so Qt can load the native Wayland plugin.
        os.environ.pop("QT_QPA_PLATFORM", None)
        if warn:
            print(
                "paleo_workbench: cleared QT_QPA_PLATFORM=xcb on a Wayland session "
                "(use PALEO_FORCE_XCB=1 only for XWayland debugging).",
                file=sys.stderr,
            )
        return None

    if not plat:
        return None
    return plat


def effective_qt_platform_hint() -> str:
    """Human-readable platform policy for docs / diagnostics (read-only)."""
    plat = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if plat in _HEADLESS_PLATFORMS:
        return plat
    if plat in _X11_PLATFORMS and _session_is_wayland():
        if os.environ.get("PALEO_FORCE_XCB", "").strip() in {"1", "true", "yes"}:
            return f"{plat} (forced via PALEO_FORCE_XCB)"
        return "wayland preferred (QT_QPA_PLATFORM=xcb would be cleared at startup)"
    if plat:
        return plat
    if _session_is_wayland():
        return "wayland (session default; QT_QPA_PLATFORM unset)"
    if os.environ.get("DISPLAY"):
        return "xcb/x11 likely (DISPLAY set, no Wayland)"
    return "unset (Qt default / headless may need offscreen)"
