#include <pwb/platform_services/qt_session_policy.hpp>

#include <QGuiApplication>
#include <QtGlobal>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <filesystem>

namespace pwb::platform_services {
namespace {

constexpr const char* kHeadlessPlatforms[] = {
    "offscreen", "minimal", "minimalegl", "vnc", "null"};
constexpr const char* kX11Platforms[] = {"xcb", "x11"};

std::string env_value(const char* name) {
    const char* raw = std::getenv(name);
    return raw != nullptr ? std::string(raw) : std::string();
}

std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) {
                       return static_cast<char>(std::tolower(c));
                   });
    return value;
}

std::string trim(const std::string& value) {
    std::string out = value;
    const auto not_space = [](unsigned char c) { return !std::isspace(c); };
    out.erase(out.begin(), std::find_if(out.begin(), out.end(), not_space));
    out.erase(std::find_if(out.rbegin(), out.rend(), not_space).base(),
              out.end());
    return out;
}

bool is_opt_in(const std::string& value) {
    const std::string v = lower(trim(value));
    return v == "1" || v == "true" || v == "yes";
}

bool is_headless(const std::string& platform) {
    for (const char* candidate : kHeadlessPlatforms) {
        if (platform == candidate) return true;
    }
    return false;
}

bool is_x11(const std::string& platform) {
    for (const char* candidate : kX11Platforms) {
        if (platform == candidate) return true;
    }
    return false;
}

}  // namespace

const char* const kMesaEglVendorCandidates[3] = {
    "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
    "/etc/glvnd/egl_vendor.d/50_mesa.json",
    nullptr,
};

bool session_is_wayland() {
    if (!env_value("WAYLAND_DISPLAY").empty()) return true;
    return lower(trim(env_value("XDG_SESSION_TYPE"))) == "wayland";
}

std::string pin_mesa_egl_on_wayland(
    const std::vector<std::string>& candidates) {
    std::vector<std::string> effective = candidates;
    if (effective.empty()) {
        for (int i = 0;
             i < 3 && kMesaEglVendorCandidates[i] != nullptr; ++i) {
            effective.emplace_back(kMesaEglVendorCandidates[i]);
        }
    }
    if (!session_is_wayland()) return "";
    if (is_opt_in(env_value("PALEO_ALLOW_NVIDIA_EGL"))) return "";
    if (!env_value("__EGL_VENDOR_LIBRARY_FILENAMES").empty()) return "";
    for (const std::string& candidate : effective) {
        std::error_code ec;
        if (std::filesystem::is_regular_file(candidate, ec)) {
#if defined(Q_OS_UNIX)
            setenv("__EGL_VENDOR_LIBRARY_FILENAMES", candidate.c_str(), 1);
            std::fprintf(
                stderr,
                "paleo-workbench: pinned EGL to Mesa (%s) — NVIDIA EGL "
                "segfaults when docking GL panels on Wayland "
                "(PALEO_ALLOW_NVIDIA_EGL=1 overrides).\n",
                candidate.c_str());
            return candidate;
#endif
        }
    }
    return "";
}

std::string configure_qt_platform_for_session() {
    const std::string plat = lower(trim(env_value("QT_QPA_PLATFORM")));
    if (is_headless(plat)) return plat;

    pin_mesa_egl_on_wayland();

    if (is_x11(plat) && session_is_wayland()) {
        const std::string forced = trim(env_value("PALEO_FORCE_XCB"));
        if (forced == "1" || forced == "true" || forced == "yes") {
            return plat;
        }
#if defined(Q_OS_UNIX)
        unsetenv("QT_QPA_PLATFORM");
#else
        _putenv_s("QT_QPA_PLATFORM", "");
#endif
        std::fprintf(
            stderr,
            "paleo-workbench: cleared QT_QPA_PLATFORM=xcb on a Wayland "
            "session (use PALEO_FORCE_XCB=1 only for XWayland debugging).\n");
        return "";
    }
    return plat;
}

std::string effective_qt_platform_hint() {
    const std::string plat = lower(trim(env_value("QT_QPA_PLATFORM")));
    if (is_headless(plat)) return plat;
    if (is_x11(plat) && session_is_wayland()) {
        const std::string forced = trim(env_value("PALEO_FORCE_XCB"));
        if (forced == "1" || forced == "true" || forced == "yes") {
            return plat + " (forced via PALEO_FORCE_XCB)";
        }
        return "wayland preferred (QT_QPA_PLATFORM=xcb would be cleared at "
               "startup)";
    }
    if (!plat.empty()) return plat;
    if (session_is_wayland()) {
        return "wayland (session default; QT_QPA_PLATFORM unset)";
    }
    if (!env_value("DISPLAY").empty()) {
        return "xcb/x11 likely (DISPLAY set, no Wayland)";
    }
    return "unset (Qt default / headless may need offscreen)";
}

void apply_wayland_fractional_scale_guard() {
    const std::string flag = lower(trim(env_value("PALEO_WAYLAND_INTEGER_SCALE")));
    if (!(flag == "1" || flag == "true" || flag == "yes" || flag == "on")) {
        return;
    }
    const std::string session = lower(env_value("XDG_SESSION_TYPE"));
    const std::string platform = lower(env_value("QT_QPA_PLATFORM"));
    if (session != "wayland" && platform != "wayland" && !platform.empty()) {
        return;
    }
    QGuiApplication::setHighDpiScaleFactorRoundingPolicy(
        Qt::HighDpiScaleFactorRoundingPolicy::Round);
}

}  // namespace pwb::platform_services
