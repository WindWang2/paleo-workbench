"""Qt platform plugin selection for desktop sessions.

Policy
------
- **Interactive app / local GUI tests**: do **not** force a platform. On modern
  Linux sessions Qt defaults to **Wayland** when ``WAYLAND_DISPLAY`` is set.
- **CI / headless**: callers may set ``QT_QPA_PLATFORM=offscreen`` (or
  ``minimal``). That is intentional and is left alone.
- **Never default to X11 (``xcb``)**. An accidental ``QT_QPA_PLATFORM=xcb`` on a
  Wayland session is cleared unless ``PALEO_FORCE_XCB=1`` (XWayland debug only).

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


def _session_is_wayland() -> bool:
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    return os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "wayland"


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
