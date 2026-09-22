#include <pwb/platform_services/theme_tokens.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <stdexcept>
#include <string_view>
#include <utility>

namespace pwb::platform_services {
namespace {

// Light palette = the Workstation base globals of paleo_workbench/tokens.py
// (frozen by tools/oracle/generate_platform_services_fixtures.py; the C++
// parity test replays the JSON, so drift in either direction fails CTest).
constexpr auto kLightBase = std::to_array<std::pair<std::string_view, std::string_view>>({
    {"PRIMARY", "#0b5563"},
    {"ACCENT", "#a65313"},
    {"SUCCESS", "#15803d"},
    {"WARNING", "#b45309"},
    {"ERROR", "#d31f1f"},
    {"ERROR_RED", "#b91c1c"},
    {"TEAL", "#0f766e"},
    {"BG_BODY", "#f4f6f8"},
    {"BG_HEADER", "#ffffff"},
    {"BG_SIDEBAR", "#ffffff"},
    {"BG_SEARCH", "#edf1f4"},
    {"BG_RAIL", "#ffffff"},
    {"BG_RAIL_GRADIENT", "#ffffff"},
    {"BG_RAIL_TOP", "#ffffff"},
    {"BG_RAIL_BOTTOM", "#ffffff"},
    {"TEXT_PRIMARY", "#18232d"},
    {"TEXT_SECONDARY", "#53616c"},
    {"TEXT_DARK", "#101820"},
    {"TEXT_ON_RAIL", "#53616c"},
    {"TEXT_ON_RAIL_ACTIVE", "#0b5563"},
    {"BORDER", "#d6dde3"},
    {"BORDER_STRONG", "#b8c3cc"},
    {"BORDER_LIGHT", "#e6ebef"},
    {"BG_CANVAS", "#f3f5f7"},
    {"BG_CANVAS_PANEL", "rgba(255, 255, 255, 0.94)"},
    {"TEXT_ON_CANVAS", "#18232d"},
    {"BORDER_CANVAS", "rgba(83, 97, 108, 0.42)"},
    {"BG_NAV_ACTIVE", "#e1eef1"},
    {"BG_MENU_HOVER", "#edf2f4"},
    {"BG_SELECTION", "#d8ebef"},
    {"BADGE_WARNING", "#92400e"},
    {"BADGE_SUCCESS", "#166534"},
    {"BADGE_PRIMARY", "#134e4a"},
    {"PRIMARY_HOVER", "#084b58"},
    {"PRIMARY_PRESSED", "#063d48"},
    {"PRIMARY_DISABLED", "#8c99a3"},
    {"ON_PRIMARY", "#ffffff"},
    {"BG_DISABLED", "#edf1f4"},
    {"TEXT_DISABLED", "#8c99a3"},
    {"STATUS_DEGRADED", "#b45309"},
    {"BG_CHART", "#ffffff"},
    {"CANVAS_INK", "#343a40"},
    {"CANVAS_CHROME_BG", "rgba(248, 249, 250, 0.92)"},
    {"CANVAS_CHROME_BORDER", "#dfe6ee"},
    {"CANVAS_SELECTION", "#ffe066"},
    {"CANVAS_SNAP", "#53d8fb"},
    {"CANVAS_EDIT", "#ff6b6b"},
    {"CANVAS_CURSOR", "#7c3aed"},
    {"BG_RAIL_HOVER", "#edf2f4"},
    {"BG_RAIL_ACTIVE", "#e1eef1"},
    {"RAIL_SEPARATOR", "rgba(83, 97, 108, 0.25)"},
    {"TOOLTIP_BG", "#18232d"},
    {"TOOLTIP_TEXT", "#ffffff"},
    {"SPLITTER_HANDLE", "rgba(83, 97, 108, 0.28)"},
    {"SPLITTER_HANDLE_HOVER", "rgba(11, 85, 99, 0.55)"},
    {"FOCUS_RING", "#a65313"},
    {"BG_GLASS", "rgba(255, 255, 255, 0.92)"},
    {"BG_GLASS_BORDER", "rgba(255, 255, 255, 0.55)"},
    {"SHADOW_SOFT", "0 4px 16px rgba(24, 35, 45, 0.10)"},
    {"SHADOW_CARD", "0 2px 8px rgba(24, 35, 45, 0.06)"},
    {"SHADOW_CARD_HOVER", "0 6px 20px rgba(11, 85, 99, 0.14)"},
    {"HOVER_GLOW", "#edf2f4"},
    {"FONT_FAMILY", "\"Inter\", \"SF Pro Text\", \"PingFang SC\", \"Microsoft YaHei UI\", \"Microsoft YaHei\", \"Segoe UI\", system-ui, sans-serif"},
    {"FONT_SIZE_BASE", "13px"},
    {"FONT_SIZE_STATUS", "11px"},
    {"FONT_SIZE_SIDEBAR_SECONDARY", "11px"},
    {"FONT_SIZE_NAV_LABEL", "9px"},
    {"FONT_WEIGHT_NAV_LABEL", "600"},
    {"FONT_SIZE_TITLE", "14px"},
    {"FONT_WEIGHT_TITLE", "700"},
    {"FONT_SIZE_MINOR", "12px"},
    {"FONT_SIZE_MICRO", "10px"},
    {"ON_SOLID", "#ffffff"},
    {"MENU_BAR_HEIGHT", "40"},
    {"HEADER_TOOLBAR_HEIGHT", "40"},
    {"ICON_RAIL_WIDTH", "54"},
    {"TEXT_SIDEBAR_WIDTH", "256"},
    {"STATUS_BAR_HEIGHT", "26"},
    {"ICON_RAIL_ITEM_SIZE", "48"},
    {"RADIUS_BUTTON", "4"},
    {"RADIUS_CARD", "4"},
    {"RADIUS_BADGE", "4"},
    {"RADIUS_PANEL", "4"},
    {"RADIUS_NAV_ITEM", "4"},
    {"SPACE_XS", "2"},
    {"SPACE_S", "4"},
    {"SPACE_M", "8"},
    {"SPACE_L", "12"},
    {"SPACE_XL", "16"},
    {"SPACE_2XL", "24"},
    {"SPACE_1", "4"},
    {"SPACE_2", "8"},
    {"SPACE_3", "12"},
    {"SPACE_4", "20"},
    {"PAGE_MARGIN", "16"},
    {"PANEL_PADDING", "12"},
    {"SURFACE", "#f4f6f8"},
    {"SURFACE_RAISED", "#ffffff"},
    {"SURFACE_PANEL", "rgba(255, 255, 255, 0.94)"},
    {"TEXT_MUTED", "#53616c"},
    {"SELECTION_TOKEN", "#e1eef1"},
    {"HOVER_TOKEN", "#edf2f4"},
    {"ACCENT_TOKEN", "#a65313"},
    {"FONT_FAMILY_MONO", "\"JetBrains Mono\", \"Cascadia Mono\", Consolas, \"Courier New\", monospace"},
    {"CONTROL_HEIGHT", "30"},
    {"CONTROL_HEIGHT_LG", "34"},
});

// Curated per-theme overrides of the same token names (never a second
// vocabulary) — tokens.py _DARK_OVERRIDES / _HIGH_CONTRAST_OVERRIDES.
constexpr auto kDarkOverrides = std::to_array<std::pair<std::string_view, std::string_view>>({
    {"ACCENT", "#e8863d"},
    {"BADGE_PRIMARY", "#0f766e"},
    {"BADGE_SUCCESS", "#15803d"},
    {"BADGE_WARNING", "#b45309"},
    {"BG_BODY", "#0e1514"},
    {"BG_CANVAS", "#0b1110"},
    {"BG_CANVAS_PANEL", "rgba(9, 14, 13, 0.9)"},
    {"BG_CHART", "#141c1b"},
    {"BG_DISABLED", "#161d1c"},
    {"BG_GLASS", "rgba(21, 29, 28, 0.90)"},
    {"BG_GLASS_BORDER", "rgba(60, 71, 68, 0.55)"},
    {"BG_HEADER", "#141c1b"},
    {"BG_MENU_HOVER", "#1d2624"},
    {"BG_NAV_ACTIVE", "#24302d"},
    {"BG_RAIL", "#0a1211"},
    {"BG_RAIL_ACTIVE", "#1c3a36"},
    {"BG_RAIL_BOTTOM", "#0a1211"},
    {"BG_RAIL_GRADIENT", "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f1a18, stop:1 #0a1211)"},
    {"BG_RAIL_HOVER", "#16221f"},
    {"BG_RAIL_TOP", "#0f1a18"},
    {"BG_SEARCH", "#1d2624"},
    {"BG_SELECTION", "#1f403c"},
    {"BG_SIDEBAR", "#151d1c"},
    {"BORDER", "#2b3432"},
    {"BORDER_CANVAS", "rgba(78, 94, 90, 0.60)"},
    {"BORDER_LIGHT", "#202927"},
    {"BORDER_STRONG", "#3c4744"},
    {"CANVAS_CHROME_BG", "rgba(20, 28, 27, 0.92)"},
    {"CANVAS_CHROME_BORDER", "#3c4744"},
    {"CANVAS_CURSOR", "#a78bfa"},
    {"CANVAS_EDIT", "#ff8787"},
    {"CANVAS_INK", "#c9d2ce"},
    {"CANVAS_SELECTION", "#ffd43b"},
    {"CANVAS_SNAP", "#53d8fb"},
    {"FOCUS_RING", "#e8863d"},
    {"ON_PRIMARY", "#06201d"},
    {"PRIMARY", "#2dd4bf"},
    {"PRIMARY_DISABLED", "#455350"},
    {"PRIMARY_HOVER", "#5adcc9"},
    {"PRIMARY_PRESSED", "#1fa898"},
    {"RAIL_SEPARATOR", "rgba(169, 195, 189, 0.30)"},
    {"SPLITTER_HANDLE", "rgba(120, 140, 134, 0.45)"},
    {"SPLITTER_HANDLE_HOVER", "rgba(232, 134, 61, 0.50)"},
    {"STATUS_DEGRADED", "#d97706"},
    {"TEXT_DARK", "#f2f5f2"},
    {"TEXT_DISABLED", "#64716c"},
    {"TEXT_ON_CANVAS", "#e8ece9"},
    {"TEXT_ON_RAIL", "#a9c3bd"},
    {"TEXT_ON_RAIL_ACTIVE", "#e8f4f1"},
    {"TEXT_PRIMARY", "#e8ece9"},
    {"TEXT_SECONDARY", "#a8b5b0"},
    {"TOOLTIP_BG", "#0a1211"},
    {"TOOLTIP_TEXT", "#e8ece9"},
    {"WARNING", "#d97706"},
});

constexpr auto kHighContrastOverrides =
    std::to_array<std::pair<std::string_view, std::string_view>>({
    {"ACCENT", "#005fd0"},
    {"BG_BODY", "#ffffff"},
    {"BG_CANVAS", "#000000"},
    {"BG_CANVAS_PANEL", "rgba(0, 0, 0, 0.95)"},
    {"BG_CHART", "#ffffff"},
    {"BG_DISABLED", "#f0f0f0"},
    {"BG_GLASS", "rgba(255, 255, 255, 0.96)"},
    {"BG_GLASS_BORDER", "rgba(0, 0, 0, 0.80)"},
    {"BG_HEADER", "#ffffff"},
    {"BG_MENU_HOVER", "#f0f0f0"},
    {"BG_NAV_ACTIVE", "#e0e0e0"},
    {"BG_RAIL", "#000000"},
    {"BG_RAIL_ACTIVE", "#ffffff"},
    {"BG_RAIL_BOTTOM", "#000000"},
    {"BG_RAIL_GRADIENT", "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #000000, stop:1 #000000)"},
    {"BG_RAIL_HOVER", "#e6e6e6"},
    {"BG_RAIL_TOP", "#000000"},
    {"BG_SEARCH", "#ffffff"},
    {"BG_SELECTION", "#e0e0e0"},
    {"BG_SIDEBAR", "#ffffff"},
    {"BORDER", "#000000"},
    {"BORDER_CANVAS", "rgba(255, 255, 255, 0.90)"},
    {"BORDER_LIGHT", "#000000"},
    {"BORDER_STRONG", "#000000"},
    {"CANVAS_CHROME_BG", "rgba(0, 0, 0, 0.85)"},
    {"CANVAS_CHROME_BORDER", "#ffffff"},
    {"CANVAS_CURSOR", "#c5b3ff"},
    {"CANVAS_EDIT", "#ff5252"},
    {"CANVAS_INK", "#ffffff"},
    {"CANVAS_SELECTION", "#ffd43b"},
    {"CANVAS_SNAP", "#00e0ff"},
    {"FOCUS_RING", "#005fd0"},
    {"ON_PRIMARY", "#ffffff"},
    {"PRIMARY", "#000000"},
    {"PRIMARY_DISABLED", "#757575"},
    {"PRIMARY_HOVER", "#262626"},
    {"PRIMARY_PRESSED", "#404040"},
    {"RAIL_SEPARATOR", "rgba(255, 255, 255, 0.60)"},
    {"SPLITTER_HANDLE", "rgba(0, 0, 0, 0.60)"},
    {"SPLITTER_HANDLE_HOVER", "rgba(0, 95, 208, 0.80)"},
    {"STATUS_DEGRADED", "#b45309"},
    {"TEXT_DARK", "#000000"},
    {"TEXT_DISABLED", "#595959"},
    {"TEXT_ON_CANVAS", "#ffffff"},
    {"TEXT_ON_RAIL", "#ffffff"},
    {"TEXT_ON_RAIL_ACTIVE", "#000000"},
    {"TEXT_PRIMARY", "#000000"},
    {"TEXT_SECONDARY", "#1a1a1a"},
    {"TOOLTIP_BG", "#ffffff"},
    {"TOOLTIP_TEXT", "#000000"},
    });

std::map<std::string, std::string> merged(
    const auto& base, const auto& overrides) {
    std::map<std::string, std::string> palette;
    for (const auto& [name, value] : base) {
        palette.emplace(name, value);
    }
    for (const auto& [name, value] : overrides) {
        palette.insert_or_assign(std::string(name), std::string(value));
    }
    return palette;
}

std::string normalize_theme_key(std::string raw) {
    std::transform(raw.begin(), raw.end(), raw.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    std::replace(raw.begin(), raw.end(), '-', '_');
    return raw;
}

}  // namespace

std::string to_string(ThemeMode mode) {
    switch (mode) {
        case ThemeMode::Light: return "light";
        case ThemeMode::Dark: return "dark";
        case ThemeMode::HighContrast: return "high_contrast";
    }
    return "light";
}

std::string to_string(Density density) {
    return density == Density::Compact ? "compact" : "comfortable";
}

ThemeMode theme_from_string(const std::string& value) {
    if (value == "dark") return ThemeMode::Dark;
    if (value == "high_contrast") return ThemeMode::HighContrast;
    return ThemeMode::Light;  // Python _coerce_theme: anything else -> LIGHT
}

Density density_from_string(const std::string& value) {
    if (value == "compact") return Density::Compact;
    return Density::Comfortable;  // Python _coerce_density fallback
}

ThemeMode theme_from_normalized(const std::string& raw) {
    return theme_from_string(normalize_theme_key(raw));
}

std::map<std::string, std::string> palette_for(ThemeMode mode) {
    switch (mode) {
        case ThemeMode::Light:
            return merged(kLightBase, std::array<std::pair<std::string_view, std::string_view>, 0>{});
        case ThemeMode::Dark:
            return merged(kLightBase, kDarkOverrides);
        case ThemeMode::HighContrast:
            return merged(kLightBase, kHighContrastOverrides);
    }
    return merged(kLightBase, std::array<std::pair<std::string_view, std::string_view>, 0>{});
}

DensityMetrics density_for(Density density) {
    if (density == Density::Compact) {
        return {/*padding_y=*/3, /*padding_x=*/8, /*btn_height=*/24,
                /*row_height=*/22, /*toolbar_height=*/30, /*app_bar_height=*/40,
                /*rail_width=*/48, /*rail_item_size=*/44, /*font_delta=*/0,
                /*tab_padding=*/"6px 12px", /*menu_padding=*/"4px 18px 4px 8px",
                /*item_padding=*/"3px 6px", /*combo_item_height=*/22};
    }
    return {/*padding_y=*/6, /*padding_x=*/12, /*btn_height=*/30,
            /*row_height=*/28, /*toolbar_height=*/36, /*app_bar_height=*/46,
            /*rail_width=*/54, /*rail_item_size=*/48, /*font_delta=*/0,
            /*tab_padding=*/"8px 16px", /*menu_padding=*/"6px 24px 6px 12px",
            /*item_padding=*/"4px 6px", /*combo_item_height=*/26};
}

DensityMetrics density_for(const std::string& density) {
    return density_for(density_from_string(density));
}

const std::string& app_version() {
    static const std::string version = "0.2.17a0";  // paleo_workbench.__version__
    return version;
}

std::string build_platform_qss(ThemeMode mode, Density density) {
    const auto palette = palette_for(mode);
    const auto metrics = density_for(density);
    const auto token = [&palette](std::string_view name) -> std::string {
        const auto it = palette.find(std::string(name));
        return it != palette.end() ? it->second : std::string();
    };

    // The platform shell's native sheet: chrome surfaces, menus, toolbars,
    // docks, status bar, inputs, tooltips. Rendered from the token palette —
    // theme switches re-render the same sheet with different token values.
    return std::string("QMainWindow, QDialog { background: ") +
           token("BG_BODY") + "; }\n"
           "QMenuBar { background: " + token("BG_HEADER") +
           "; color: " + token("TEXT_PRIMARY") +
           "; padding: 2px " + std::to_string(metrics.padding_x) + "px; }\n"
           "QMenuBar::item { padding: " + std::to_string(metrics.padding_y) +
           "px " + std::to_string(metrics.padding_x) + "px; border-radius: 4px; }\n"
           "QMenuBar::item:selected { background: " + token("BG_MENU_HOVER") + "; }\n"
           "QMenu { background: " + token("BG_HEADER") +
           "; color: " + token("TEXT_PRIMARY") +
           "; border: 1px solid " + token("BORDER") + "; }\n"
           "QMenu::item { padding: " + metrics.menu_padding + "; border-radius: 4px; }\n"
           "QMenu::item:selected { background: " + token("BG_SELECTION") + "; }\n"
           "QMenu::separator { height: 1px; background: " + token("BORDER_LIGHT") +
           "; margin: 4px 8px; }\n"
           "QToolBar { background: " + token("BG_HEADER") +
           "; border-bottom: 1px solid " + token("BORDER") +
           "; padding: " + std::to_string(std::max(0, metrics.padding_y - 2)) + "px; spacing: " +
           std::to_string(metrics.padding_x) + "px; }\n"
           "QToolButton { background: transparent; color: " + token("TEXT_PRIMARY") +
           "; border: 1px solid transparent; border-radius: 4px; padding: " +
           std::to_string(metrics.padding_y) + "px; }\n"
           "QToolButton:hover { background: " + token("BG_MENU_HOVER") + "; }\n"
           "QToolButton:checked { background: " + token("BG_NAV_ACTIVE") +
           "; color: " + token("TEXT_ON_RAIL_ACTIVE") + "; }\n"
           "QToolButton:disabled { color: " + token("TEXT_DISABLED") + "; }\n"
           "QToolBar#MapNavigationToolBar { background: " + token("SURFACE") +
           "; border: 1px solid " + token("BORDER_LIGHT") +
           "; border-left: none; border-right: none; padding: 3px 8px; spacing: 2px; }\n"
           "QToolBar#MapNavigationToolBar QToolButton { min-width: 24px; min-height: 24px;"
           " padding: 3px; }\n"
           "QToolBar#MapNavigationToolBar::separator { width: 1px; background: " +
           token("BORDER_LIGHT") + "; margin: 5px 4px; }\n"
           "QWidget#layer-tree-panel { background: " + token("SURFACE") + "; }\n"
           "QLabel#LayerTreeTitle { color: " + token("TEXT_PRIMARY") +
           "; font-weight: 600; }\n"
           "QToolBar#LayerTreeToolBar { background: transparent; border: none;"
           " padding: 0; spacing: 1px; }\n"
           "QToolBar#LayerTreeToolBar QToolButton { min-width: 22px; min-height: 22px;"
           " padding: 2px; }\n"
           "QLineEdit#LayerTreeFilter { background: " + token("BG_SEARCH") + "; }\n"
           "QTreeView#QgisLayerTreeView { background: " + token("BG_HEADER") +
           "; border: 1px solid " + token("BORDER_LIGHT") +
           "; border-radius: 4px; outline: none; }\n"
           "QTreeView#QgisLayerTreeView::item { padding: 2px 4px; }\n"
           "QTreeView#QgisLayerTreeView::item:hover { background: " +
           token("BG_MENU_HOVER") + "; }\n"
           "QLabel#LayerOpacityLabel { color: " + token("TEXT_SECONDARY") + "; }\n"
           "QWidget#CompositeDocument #session-map-canvas { border: 1px solid " +
           token("BORDER_LIGHT") + "; }\n"
           "QDockWidget { color: " + token("TEXT_PRIMARY") +
           "; titlebar-close-icon: none; }\n"
           "QDockWidget::title { background: " + token("BG_HEADER") +
           "; padding: " + std::to_string(metrics.padding_y) + "px " +
           std::to_string(metrics.padding_x) + "px; border-bottom: 1px solid " +
           token("BORDER_LIGHT") + "; }\n"
           "QStatusBar { background: " + token("BG_HEADER") +
           "; color: " + token("TEXT_SECONDARY") + "; }\n"
           "QStatusBar::item { border: none; }\n"
           "QToolTip { background: " + token("TOOLTIP_BG") +
           "; color: " + token("TOOLTIP_TEXT") +
           "; border: 1px solid " + token("BORDER_STRONG") + "; padding: 4px; }\n"
           "QPushButton { background: " + token("BG_HEADER") +
           "; color: " + token("TEXT_PRIMARY") +
           "; border: 1px solid " + token("BORDER_STRONG") +
           "; border-radius: 4px; min-height: " + std::to_string(metrics.btn_height - 8) +
           "px; padding: " + std::to_string(metrics.padding_y) + "px " +
           std::to_string(metrics.padding_x) + "px; }\n"
           "QPushButton:hover { border-color: " + token("PRIMARY") + "; }\n"
           "QPushButton:pressed { background: " + token("BG_SELECTION") + "; }\n"
           "QPushButton:disabled { color: " + token("TEXT_DISABLED") +
           "; border-color: " + token("BORDER_LIGHT") + "; }\n"
           "QPushButton#primary-action { background: " + token("PRIMARY") +
           "; color: " + token("ON_PRIMARY") + "; border: none; }\n"
           "QPushButton#primary-action:hover { background: " + token("PRIMARY_HOVER") + "; }\n"
           "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: " +
           token("BG_SEARCH") + "; color: " + token("TEXT_PRIMARY") +
           "; border: 1px solid " + token("BORDER_STRONG") +
           "; border-radius: 4px; min-height: " + std::to_string(metrics.btn_height - 10) +
           "px; padding: 0 " + std::to_string(metrics.padding_x) + "px; }\n"
           "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: " +
           token("FOCUS_RING") + "; }\n"
           "QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { background: " +
           token("BG_DISABLED") + "; color: " + token("TEXT_DISABLED") + "; }\n"
           "QListWidget, QTreeView, QTableView { background: " + token("BG_HEADER") +
           "; color: " + token("TEXT_PRIMARY") +
           "; alternate-background-color: " + token("BG_SEARCH") + "; }\n"
           "QTreeView::item, QListWidget::item { min-height: " +
           std::to_string(metrics.row_height) + "px; }\n"
           "QTreeView::item:selected, QListWidget::item:selected { background: " +
           token("BG_SELECTION") + "; color: " + token("TEXT_PRIMARY") + "; }\n"
           "QSplitter::handle { background: " + token("SPLITTER_HANDLE") + "; }\n"
           "QSplitter::handle:hover { background: " + token("SPLITTER_HANDLE_HOVER") + "; }\n"
           "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }\n"
           "QScrollBar::handle:vertical { background: " + token("BORDER_STRONG") +
           "; border-radius: 5px; min-height: 24px; }\n"
           "QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }\n"
           "QScrollBar::handle:horizontal { background: " + token("BORDER_STRONG") +
           "; border-radius: 5px; min-width: 24px; }\n"
           "QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }\n"
           // Pwb state surfaces (ui_widgets states/badges vocabulary —
           // V14-THREE-STAGE-UX): the components carried these objectNames
           // with no C++-side selectors to match them; the unified
           // busy/empty/error/stale presentation needs them themed.
           "QFrame#PwbStateSurface { background: " + token("SURFACE") +
           "; border: 1px solid " + token("BORDER_LIGHT") +
           "; border-radius: " + token("RADIUS_PANEL") + "px; }\n"
           "QLabel#PwbStateTitle { color: " + token("TEXT_PRIMARY") +
           "; font-size: " + token("FONT_SIZE_TITLE") + "px; font-weight: 600; }\n"
           "QLabel#PwbStateHint { color: " + token("TEXT_SECONDARY") +
           "; font-size: " + token("FONT_SIZE_BASE") + "px; }\n"
           "QProgressBar#PwbProgress { background: " + token("BG_DISABLED") +
           "; border: none; border-radius: 3px; max-height: 6px; }\n"
           "QProgressBar#PwbProgress::chunk { background: " + token("PRIMARY") +
           "; border-radius: 3px; }\n"
           "QProgressBar#PwbProgress[progressState=\"running\"]::chunk { background: " +
           token("WARNING") + "; }\n"
           "QProgressBar#PwbProgress[progressState=\"failed\"]::chunk { background: " +
           token("ERROR") + "; }\n"
           "QProgressBar#PwbProgress[progressState=\"done\"]::chunk { background: " +
           token("SUCCESS") + "; }\n"
           "QLabel#PwbBadge { background: " + token("BG_HEADER") +
           "; border-radius: " + token("RADIUS_BADGE") + "px; padding: 1px 8px; }\n"
           "QLabel#PwbBadge { color: " + token("TEXT_PRIMARY") +
           "; font-size: " + token("FONT_SIZE_MICRO") + "px; }\n"
           "QLabel#PwbBadge[tone=\"success\"] { background: " +
           token("BADGE_SUCCESS") + "; }\n"
           "QLabel#PwbBadge[tone=\"warning\"] { background: " +
           token("BADGE_WARNING") + "; }\n"
           "QLabel#PwbBadge[tone=\"error\"] { background: " +
           token("ERROR_RED") + "; }\n"
           "QLabel#PwbBadge[tone=\"primary\"] { background: " +
           token("BADGE_PRIMARY") + "; }\n"
           "QWidget#PwbInlineStatus { background: transparent; }\n"
           "QLabel#PwbInlineStatusText { color: " + token("TEXT_SECONDARY") +
           "; font-size: " + token("FONT_SIZE_BASE") + "px; }\n";
}

}  // namespace pwb::platform_services
