#include "pwb/ui_shell/layout_presets.hpp"

#include "pwb/ui_shell/dock_manager.hpp"

namespace pwb::ui_shell {

const std::vector<WorkstationLayoutPreset>& workstation_layout_presets() {
    static const std::vector<WorkstationLayoutPreset> presets = {
        {"composite_default",
         "编图 · 默认",
         "Variant C full-bleed map; only the layer dock open among composite "
         "panels.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .composite_layer = true,
                              .explorer_expanded = true}},
        {"well_interpretation",
         "测井解释",
         "Explorer + inspector + well tracks + layer dock; no "
         "agent/tasks/seismic.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .composite_layer = true,
                              .explorer_expanded = true,
                              .well = true}},
        {"seismic_interpretation",
         "地震解释",
         "Explorer + inspector + seismic sections + layer dock.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .composite_layer = true,
                              .explorer_expanded = true,
                              .seismic = true}},
        {"well_seismic_joint",
         "井震联合",
         "Well tracks + seismic sections side by side with the linked view.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .composite_layer = false,
                              .composite_linked = true,
                              .explorer_expanded = true,
                              .well = true,
                              .seismic = true}},
        {"integrated",
         "综合",
         "Everything on: agent, tasks, wells, seismic and the linked view.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .agent = true,
                              .tasks = true,
                              .composite_layer = true,
                              .composite_input = true,
                              .composite_linked = true,
                              .explorer_expanded = true,
                              .well = true,
                              .seismic = true}},
        {"review",
         "审核",
         "Inputs and results dock open next to the layer dock for review.",
         DockVisibilityMatrix{.nav = true,
                              .inspector = true,
                              .composite_layer = true,
                              .composite_input = true,
                              .explorer_expanded = true}},
    };
    return presets;
}

const WorkstationLayoutPreset* get_preset(const std::string& preset_id) {
    for (const auto& preset : workstation_layout_presets()) {
        if (preset.id == preset_id) {
            return &preset;
        }
    }
    return nullptr;
}

std::vector<std::pair<std::string, std::string>> preset_labels() {
    std::vector<std::pair<std::string, std::string>> out;
    out.reserve(workstation_layout_presets().size());
    for (const auto& p : workstation_layout_presets()) {
        out.emplace_back(p.id, p.label);
    }
    return out;
}

std::map<std::string, bool> visibility_dict(const DockVisibilityMatrix& m) {
    return {
        {"nav", m.nav},
        {"inspector", m.inspector},
        {"agent", m.agent},
        {"tasks", m.tasks},
        {"logs", m.logs},
        {"console", m.console},
        {"composite_layer", m.composite_layer},
        {"composite_input", m.composite_input},
        {"composite_linked", m.composite_linked},
        {"explorer_expanded", m.explorer_expanded},
        {"well", m.well},
        {"seismic", m.seismic},
        {"hub", m.hub},
        {"mapping_stage", m.mapping_stage},
    };
}

void register_with_dock_manager(DockManager& dock_manager) {
    struct Row {
        const char* id;
        const char* title;
        const char* area;
    };
    static const Row panels[] = {
        {"workstation:explorer", "资源管理器", "left"},
        {"workstation:inspector", "检查器", "right"},
        {"workstation:agent", "Agent", "bottom"},
        {"workstation:tasks", "任务中心", "bottom"},
        {"workstation:logs", "日志", "bottom"},
        {"workstation:console", "控制台", "bottom"},
        {"workstation:composite_layer", "图层管理", "right"},
        {"workstation:composite_input", "输入与结果", "left"},
        {"workstation:composite_linked", "联动视图", "bottom"},
        {"workstation:well", "测井轨道", "bottom"},
        {"workstation:seismic", "地震剖面", "bottom"},
        {"workstation:hub", "功能页", "right"},
    };
    for (const auto& row : panels) {
        dock_manager.register_panel(row.id, row.title, row.area);
    }
}

}  // namespace pwb::ui_shell
