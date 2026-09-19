#pragma once

// Port of paleo_workbench/ui/dock_manager.py (UI-01).
// Workspace and dock panel layout manager: preset layouts + the panel-id
// registry (canonical id -> title vocabulary consulted by FloatController).
// Qt-free.

#include <deque>
#include <map>
#include <string>
#include <vector>

namespace pwb::ui_shell {

enum class WorkspacePreset {
    WellLogInterpretation,      // "well_log"
    MapAuthoring,               // "map_authoring"
    // Workstation V3 Light named layouts (design-qa P3); coexist with the
    // mapping/well presets — the shell applies them via QMainWindow docks.
    WorkstationComposite,       // "workstation_composite"
    WorkstationInterpretation,  // "workstation_interpretation"
};

// Python WorkspacePreset.value strings.
const char* workspace_preset_value(WorkspacePreset preset);

struct DockPanelConfig {
    std::string id;
    std::string title;
    bool visible = true;
    bool floating = false;
    std::string area = "left";  // left, right, top, bottom
};

struct WorkspaceLayout {
    WorkspacePreset preset;
    std::string name;
    std::vector<DockPanelConfig> docks;
};

class DockManager {
public:
    DockManager();

    const WorkspaceLayout* get_layout(WorkspacePreset preset) const;
    bool set_active_preset(WorkspacePreset preset);
    const WorkspaceLayout& active_layout() const;

    // --- panel-id registry (FloatController vocabulary) -------------------
    // Register (or retitle) a panel id and return its config. Existing ids
    // are ALIASED, not replaced: the registry shares the preset layout's own
    // DockPanelConfig, so a retitle propagates to the preset layout (Python
    // object-identity parity); ``area``/``visible`` are ignored for existing
    // ids.
    DockPanelConfig& register_panel(const std::string& panel_id,
                                    const std::string& title,
                                    const std::string& area = "left",
                                    bool visible = true);
    // Exact id first, then the suffix after the last ':'.
    const DockPanelConfig* panel(const std::string& panel_id) const;
    // Empty string when unresolved (Python None -> "" boundary).
    std::string panel_title(const std::string& panel_id) const;
    bool has_panel(const std::string& panel_id) const;
    // Insertion order (Python dict parity).
    std::vector<std::string> panel_ids() const;

private:
    void register_default_presets();
    DockPanelConfig& seed_panel(DockPanelConfig config);

    std::map<WorkspacePreset, WorkspaceLayout> layouts_;
    // id -> config. Preset-seeded entries point INTO layouts_ vectors (shared
    // identity); ad-hoc registrations point into owned_panels_ (deque keeps
    // addresses stable across growth).
    std::map<std::string, DockPanelConfig*> panels_;
    std::deque<DockPanelConfig> owned_panels_;
    std::vector<std::string> panel_order_;
    WorkspacePreset active_preset_ = WorkspacePreset::MapAuthoring;
};

// Process-level registry (Python module-global `dock_manager` parity).
DockManager& dock_manager();

}  // namespace pwb::ui_shell
