#pragma once

// Port of paleo_workbench/ui/layout_presets.py (UI-01).
// Named workstation layout presets: pure data + visibility matrices — no Qt
// widgets. The shell applies these through QMainWindow dock show/hide and
// optional saveState snapshots.
// Qt-free.

#include <map>
#include <string>
#include <vector>

namespace pwb::ui_shell {

class DockManager;

// Visibility flags for the top-level workstation dock set. Composite docks
// only matter when the composite document is active; the shell still applies
// the flags so switching back to 编图 restores them.
struct DockVisibilityMatrix {
    bool nav = true;
    bool inspector = true;
    bool agent = false;
    bool tasks = false;
    bool logs = false;
    bool console = false;
    bool composite_layer = true;
    bool composite_input = false;
    bool composite_linked = false;
    bool explorer_expanded = true;
    bool well = false;
    bool seismic = false;
    bool hub = false;
    bool mapping_stage = true;
};

struct WorkstationLayoutPreset {
    std::string id;
    std::string label;
    std::string description;
    DockVisibilityMatrix visibility;
};

// Canonical registry — order is menu order (app bar「工作区」下拉同序).
const std::vector<WorkstationLayoutPreset>& workstation_layout_presets();

// Alias used by the 面板 menu "恢复默认布局" action.
inline constexpr char kResetLayoutPresetId[] = "composite_default";

const WorkstationLayoutPreset* get_preset(const std::string& preset_id);

// (id, label) pairs for UI menus, in menu order.
std::vector<std::pair<std::string, std::string>> preset_labels();

// Flat dock-key -> visible map (stable keys for tests / persistence notes).
std::map<std::string, bool> visibility_dict(const DockVisibilityMatrix& m);

// Register workstation panel titles into the shared DockManager vocabulary.
// Does not replace existing presets; only seeds panel ids used by the V3
// shell and FloatController title lookup.
void register_with_dock_manager(DockManager& dock_manager);

}  // namespace pwb::ui_shell
