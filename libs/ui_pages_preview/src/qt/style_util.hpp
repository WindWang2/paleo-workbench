#pragma once

// Internal helpers for the qt shell — palette tokens with the light-theme
// fallback (tokens.py), spacing/radius/font constants and the style_bind
// convenience pass-through. Not exported.

#include <QString>
#include <map>
#include <string>

#include <pwb/ui_shell/style_registry.hpp>

namespace pwb::ui_pages_preview::qt_internal {

// tokens.py metric constants used by these widgets.
inline constexpr int SPACE_1 = 4;
inline constexpr int SPACE_2 = 8;
inline constexpr int SPACE_3 = 12;
inline constexpr int RADIUS_BUTTON = 4;
inline constexpr int RADIUS_CARD = 4;
inline constexpr const char* FONT_FAMILY_MONO =
    "\"JetBrains Mono\", \"Cascadia Mono\", Consolas, \"Courier New\", monospace";

// Light-theme fallback for the tokens these widgets read (tokens.py values).
// style_palette() returns {} until a ThemeService is bound — tests and
// standalone widgets must still render the base palette.
inline const std::map<std::string, std::string>& fallback_palette() {
    static const std::map<std::string, std::string> palette = {
        {"PRIMARY", "#0b5563"},
        {"PRIMARY_HOVER", "#084b58"},
        {"PRIMARY_DISABLED", "#8c99a3"},
        {"ON_PRIMARY", "#ffffff"},
        {"TEAL", "#0f766e"},
        {"SUCCESS", "#15803d"},
        {"TEXT_PRIMARY", "#18232d"},
        {"TEXT_SECONDARY", "#53616c"},
        {"BG_SEARCH", "#edf1f4"},
        {"BG_SELECTION", "#d8ebef"},
        {"BG_HEADER", "#ffffff"},
        {"BG_SIDEBAR", "#ffffff"},
        {"BORDER", "#d6dde3"},
    };
    return palette;
}

// Token lookup: live themed palette first, light fallback second.
inline QString token(const std::string& name) {
    const auto pal = pwb::ui_shell::style_palette();
    if (auto it = pal.find(name); it != pal.end()) {
        return QString::fromStdString(it->second);
    }
    const auto& fb = fallback_palette();
    if (auto it = fb.find(name); it != fb.end()) {
        return QString::fromStdString(it->second);
    }
    return QString();
}

}  // namespace pwb::ui_pages_preview::qt_internal
