#include "pwb/ui_shell/screen_inventory.hpp"

#include <pwb/ui_shell/navigation.hpp>

namespace pwb::ui_shell {

const ScreenInventory& screen_inventory() {
    static const ScreenInventory inventory = [] {
        ScreenInventory inv;
        inv.source = "navigation.hpp（唯一权威）";
        for (int index = 0; index < kHubCount; ++index) {
            inv.hubs.push_back(ScreenHubEntry{
                index, hub_names().at(static_cast<size_t>(index)),
                submodule_keys(index)});
        }
        inv.central_document = "composite";
        inv.docks = {"nav",        "inspector",  "agent",  "task",
                     "logs",       "console",    "composite_layer",
                     "composite_input",          "composite_linked",
                     "well",       "seismic",    "hub",    "mapping_stage"};
        return inv;
    }();
    return inventory;
}

}  // namespace pwb::ui_shell
