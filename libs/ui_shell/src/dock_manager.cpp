#include "pwb/ui_shell/dock_manager.hpp"

#include <stdexcept>
#include <utility>

#include "pwb/ui_shell/layout_presets.hpp"

namespace pwb::ui_shell {

const char* workspace_preset_value(WorkspacePreset preset) {
    switch (preset) {
        case WorkspacePreset::WellLogInterpretation:
            return "well_log";
        case WorkspacePreset::MapAuthoring:
            return "map_authoring";
        case WorkspacePreset::WorkstationComposite:
            return "workstation_composite";
        case WorkspacePreset::WorkstationInterpretation:
            return "workstation_interpretation";
    }
    return "map_authoring";
}

DockManager::DockManager() {
    register_default_presets();
}

const WorkspaceLayout* DockManager::get_layout(WorkspacePreset preset) const {
    const auto it = layouts_.find(preset);
    return it == layouts_.end() ? nullptr : &it->second;
}

bool DockManager::set_active_preset(WorkspacePreset preset) {
    if (layouts_.find(preset) == layouts_.end()) {
        return false;
    }
    active_preset_ = preset;
    return true;
}

const WorkspaceLayout& DockManager::active_layout() const {
    const auto* layout = get_layout(active_preset_);
    if (layout == nullptr) {
        throw std::out_of_range("active preset has no layout");
    }
    return *layout;
}

DockPanelConfig& DockManager::seed_panel(DockPanelConfig config) {
    // Preset-seeded ids: first registration wins on collision.
    const auto it = panels_.find(config.id);
    if (it != panels_.end()) {
        return *it->second;
    }
    owned_panels_.push_back(std::move(config));
    DockPanelConfig* stored = &owned_panels_.back();
    panels_[stored->id] = stored;
    panel_order_.push_back(stored->id);
    return *stored;
}

DockPanelConfig& DockManager::register_panel(const std::string& panel_id,
                                             const std::string& title,
                                             const std::string& area,
                                             bool visible) {
    const auto it = panels_.find(panel_id);
    if (it != panels_.end()) {
        // Alias semantics: retitle propagates to the shared config (preset
        // layouts keep their own DockPanelConfig — see note below), while
        // area/visible are ignored.
        if (!title.empty()) {
            it->second->title = title;
        }
        return *it->second;
    }
    DockPanelConfig config;
    config.id = panel_id;
    config.title = title;
    config.visible = visible;
    config.area = area;
    return seed_panel(std::move(config));
}

const DockPanelConfig* DockManager::panel(const std::string& panel_id) const {
    const auto it = panels_.find(panel_id);
    return it == panels_.end() ? nullptr : it->second;
}

std::string DockManager::panel_title(const std::string& panel_id) const {
    const DockPanelConfig* config = panel(panel_id);
    if (config == nullptr) {
        // Suffix after the last ':' fallback (namespaced ids).
        const auto pos = panel_id.rfind(':');
        if (pos != std::string::npos && pos + 1 < panel_id.size()) {
            config = panel(panel_id.substr(pos + 1));
        }
    }
    return config == nullptr ? std::string() : config->title;
}

bool DockManager::has_panel(const std::string& panel_id) const {
    return panels_.find(panel_id) != panels_.end();
}

std::vector<std::string> DockManager::panel_ids() const {
    return panel_order_;
}

void DockManager::register_default_presets() {
    // The preset docks seed the panel-id registry: ids are unique across
    // presets (first registration wins on collision). The registry points
    // INTO the layout vectors so a register_panel retitle propagates to the
    // preset layout exactly like Python's shared object identity.
    auto seed_layout = [&](WorkspacePreset preset, std::string name,
                           std::vector<DockPanelConfig> docks) {
        auto [it, inserted] =
            layouts_.emplace(preset, WorkspaceLayout{preset, std::move(name),
                                                     std::move(docks)});
        if (!inserted) {
            return;
        }
        for (auto& dock : it->second.docks) {
            if (panels_.find(dock.id) == panels_.end()) {
                panels_[dock.id] = &dock;
                panel_order_.push_back(dock.id);
            }
        }
    };

    seed_layout(WorkspacePreset::MapAuthoring, "古地理综合编图工作区",
                {{"layer_tree", "图层管理树", true, false, "left"},
                 {"map_tools", "制图工具箱", true, false, "left"},
                 {"property_inspector", "图斑属性检查器", true, false, "right"},
                 {"history_panel", "拓扑操作历史", true, false, "right"},
                 {"qa_audit", "合规质检报告", false, false, "bottom"}});

    seed_layout(WorkspacePreset::WellLogInterpretation,
                "测井解释与地层对比工作区",
                {{"well_tree", "井目录与道模板", true, false, "left"},
                 {"correlation_panel", "井间对比与拉平", true, false, "right"},
                 {"crossplot", "岩性交会图", true, false, "bottom"}});

    // Workstation V3 Light presets — mirror layout_presets visibility.
    seed_layout(WorkspacePreset::WorkstationComposite, "默认综合编修",
                {{"workstation:explorer", "资源管理器", true, false, "left"},
                 {"workstation:inspector", "检查器", true, false, "right"},
                 {"workstation:agent", "Agent", false, false, "bottom"},
                 {"workstation:tasks", "任务中心", false, false, "bottom"},
                 {"workstation:composite_layer", "图层管理", true, false,
                  "right"},
                 {"workstation:composite_input", "输入与结果", false, false,
                  "left"},
                 {"workstation:composite_linked", "联动视图", false, false,
                  "bottom"}});

    seed_layout(WorkspacePreset::WorkstationInterpretation, "解释工作区",
                {{"workstation:explorer", "资源管理器", true, false, "left"},
                 {"workstation:inspector", "检查器", true, false, "right"},
                 {"workstation:agent", "Agent", true, false, "bottom"},
                 {"workstation:tasks", "任务中心", true, false, "bottom"},
                 {"workstation:composite_layer", "图层管理", false, false,
                  "right"},
                 {"workstation:composite_input", "输入与结果", false, false,
                  "left"},
                 {"workstation:composite_linked", "联动视图", false, false,
                  "bottom"}});

    // Keep layout_presets panel vocabulary in sync (Python lazy-import
    // parity: seeds workstation:* titles used by FloatController lookup).
    register_with_dock_manager(*this);
}

DockManager& dock_manager() {
    static DockManager manager;
    return manager;
}

}  // namespace pwb::ui_shell
