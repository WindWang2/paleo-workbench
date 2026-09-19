// UI-06 — asset context menu model (asset_context_menu.py :: build).
//
// The menu is fully determined by the AssetView + capability flags +
// available export formats. The core emits an ordered MenuEntry list;
// the Qt shell renders it into a QMenu 1:1 (submenus nested by key).
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_pages_data/asset_view.hpp>

namespace pwb::ui_pages_data {

// Menu entry kinds — mirrors the Python imperative construction order.
struct MenuEntry {
    enum class Kind {
        Action,      // leaf QAction
        Separator,
        Submenu,     // owns `children`
    };
    Kind kind = Kind::Action;
    std::string object_name;   // QAction objectName ("" for separators/submenu labels)
    std::string label;
    std::string tooltip;
    bool enabled = true;
    bool destructive = false;  // Python applies the red delete icon
    // For ctx_open_system: the local path captured at build time ("" when disabled).
    std::string open_local_path;
    std::vector<MenuEntry> children;  // Submenu only
};

// Capabilities the host page advertises (build()'s keyword args).
struct MenuCapabilities {
    bool viz_supported = false;
    bool well_prediction_supported = false;
    bool seismic_prediction_supported = false;
    // get_available_formats(asset) → ordered (label, fn) pairs; labels only.
    std::vector<std::string> export_formats;
    // Raw-edit lock tooltip. Python calls
    // tool_availability.raw_layer_gate_reason() — injected so tool_policy
    // owns the vocabulary ("不可用：{reason}").
    std::string raw_gate_reason;
};

// Single-selection build. `kind` selects the ResourceItem-only branches
// (ctx_rescan + 归类为 submenu + INVENTORY export).
std::vector<MenuEntry>
build_asset_menu_model(const AssetView& view, AssetKind kind,
                       const MenuCapabilities& caps);

// Multi-selection build (已选择 N 项数据资产 header + 3 bulk + remove).
std::vector<MenuEntry> build_multi_menu_model(int count);

// The open-with-system-app rule (shared by trashed and normal paths):
// enabled only for a non-empty non-remote path; remote schemes are
// http:// https:// ftp:// (Python's explicit tuple).
std::pair<bool, std::string> open_system_target(const std::string& path);

}  // namespace pwb::ui_pages_data
