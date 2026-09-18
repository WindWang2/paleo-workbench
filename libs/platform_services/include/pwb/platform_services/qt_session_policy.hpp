#pragma once

// Qt session policy — port of paleo_workbench/qt_platform.py + the Wayland
// fractional-scale guard in main.py. Pure environment logic; every function
// must run BEFORE the QApplication/QgsApplication is constructed.
//
// Policy (qt_platform.py docstring):
//   * headless platforms (offscreen/minimal/...) pass through untouched;
//   * never default to X11: a forced QT_QPA_PLATFORM=xcb on a Wayland
//     session is cleared unless PALEO_FORCE_XCB=1 (XWayland debug);
//   * on Wayland sessions EGL is pinned to the Mesa glvnd vendor (NVIDIA
//     EGL segfaults when docking GL panels) unless PALEO_ALLOW_NVIDIA_EGL=1;
//     a pre-set __EGL_VENDOR_LIBRARY_FILENAMES is always respected.

#include <string>
#include <vector>

namespace pwb::platform_services {

// True when WAYLAND_DISPLAY is set or XDG_SESSION_TYPE=wayland.
bool session_is_wayland();

// Pins glvnd to the first existing Mesa vendor JSON. Returns the pinned
// path, or "" when untouched (not Wayland / opted out / already pinned).
// The candidate list is injectable for tests.
extern const char* const kMesaEglVendorCandidates[3];
std::string pin_mesa_egl_on_wayland(
    const std::vector<std::string>& candidates = {});

// Normalizes QT_QPA_PLATFORM for the session. Returns the effective
// platform override ("" = leave the choice to Qt).
std::string configure_qt_platform_for_session();

// Read-only description of the platform policy for diagnostics.
std::string effective_qt_platform_hint();

// Opt-in integer-scale rounding for Wayland fractional-scale sessions
// (PALEO_WAYLAND_INTEGER_SCALE=1): rounds the device scale so canvas
// annotations stay vector-crisp. Must run before QApplication.
void apply_wayland_fractional_scale_guard();

}  // namespace pwb::platform_services
