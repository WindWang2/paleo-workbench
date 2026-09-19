#pragma once

// Port of paleo_workbench/ui/screen_inventory.py (UI-01).
// 屏幕清单（V7 D13 重写）：从 navigation 权威派生，不再手抄第二份。
// 唯一消费者是模型测试——诚实反映当前可达表面（hub/submodule 派生 +
// workstation 中央文档面）。

#include <string>
#include <vector>

namespace pwb::ui_shell {

struct ScreenHubEntry {
    int index;
    std::string name;
    std::vector<std::string> submodules;  // submodule keys in hub order
};

struct ScreenInventory {
    std::string source;  // "navigation.hpp（唯一权威）"
    std::vector<ScreenHubEntry> hubs;
    // Workstation resident surfaces (non-hub pages): central composite
    // document + resident docks.
    std::string central_document;          // "composite"
    std::vector<std::string> docks;
};

// Derive the inventory from the navigation module's authoritative tables.
const ScreenInventory& screen_inventory();

}  // namespace pwb::ui_shell
