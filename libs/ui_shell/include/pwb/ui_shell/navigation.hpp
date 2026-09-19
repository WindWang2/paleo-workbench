#pragma once

// Port of paleo_workbench/ui/navigation.py (UI-01).
// Hub page model for the UI-v2 Ribbon shell (4+1 pages): five hubs, each
// hosting one or more sub-modules behind an in-page switcher.
// Pure data — Qt-free.

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_shell {

// Hub page indices (0 ~ 4).
inline constexpr int kPageIndexData = 0;
inline constexpr int kPageIndexWell = 1;
inline constexpr int kPageIndexSeismic = 2;
inline constexpr int kPageIndexMapping = 3;
inline constexpr int kPageIndexVisualization = 4;
inline constexpr int kHubCount = 5;

// "数据", "井", "地震", "编图", "可视化" — order is hub order.
const std::vector<std::string>& hub_names();

struct Submodule {
    std::string key;
    std::string title;
};

// Sub-module registry: hub index -> entries in switcher order.
// Hubs with a single entry render no switcher.
const std::vector<Submodule>& submodules(int hub_index);

// Sub-module keys of a hub in switcher order (empty for unknown hub).
std::vector<std::string> submodule_keys(int hub_index);

// Display title of a sub-module (empty string when unknown).
std::string submodule_title(int hub_index, const std::string& key);

// Default sub-module per hub (数据 opens on the 项目概述 home surface).
const std::string& default_submodule(int hub_index);

// Pre-v2 flat page index (0~10) -> (hub index, sub-module key). The home
// page's module-relationship cards still emit the legacy ordinals.
std::optional<std::pair<int, std::string>> legacy_page_to_hub(int legacy_index);

}  // namespace pwb::ui_shell
