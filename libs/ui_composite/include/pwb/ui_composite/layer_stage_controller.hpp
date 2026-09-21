// V14 LayerStageController — the layer-side policy of stage switching.
// Port of the layer-relevant subset of
// paleo_workbench/mapping_workspace/controller.py (MappingStageController:
// set_stage / restore_stage_view / active-target reassignment, V13 W-P).
//
// Stage is a workflow context, never a page: the same QGIS project /
// canvas / layer authority spans all stages; switching only changes tool
// sets, group visibility and edit targets — and it is INSTANTANEOUS:
// never triggers recomputation, never recreates layers, never rewrites
// order (contracts 03 §6).
//
// The layer manager UI / page composition (Prompt 2) consumes the
// signals; this controller stays Qt-free with std::function hooks.
#pragma once

#include "pwb/ui_composite/layer_group_controller.hpp"

#include <functional>
#include <optional>
#include <string>

namespace pwb::ui_composite {

class LayerStageController {
public:
    LayerStageController(pwb::workspace::MappingWorkspaceState& state,
                         LayerGroupController& groups);

    // Existence probe for the persisted active layer (V13 W-P: probe
    // first; without one, membership existence is the conservative
    // approximation).
    void set_target_validator(
        std::function<bool(const std::string&)> validator);
    // Role -> layer resolver for the profile's active_editing_roles.
    void set_target_resolver(
        std::function<std::optional<std::string>(const std::string& role)>
            resolver);

    // Switch the stage (transient). Returns false for unknown/duplicate
    // requests. Order: write current stage -> rematerialize empty system
    // groups of the new stage (bridge failures never break the switch) ->
    // full-push effective group visibility -> reassign the active edit
    // target (stored -> profile roles -> none; NEVER inherited across
    // stages) -> notify.
    bool set_stage(MappingStage stage);
    // Restore the stage context after project reopen: visibility +
    // expand states + edit target.
    void restore_stage_view();

    const std::string& current_stage() const { return state_.current_stage; }
    const std::optional<std::string>& active_target_layer_id() const {
        return active_target_layer_id_;
    }
    // User's explicit active-layer choice (recorded into the CURRENT
    // stage's view state; signal only on change).
    void set_active_target(const std::string& layer_id);

    // Host hooks (wire to the panel/status surface).
    std::function<void(const std::optional<std::string>&)>
        active_target_changed;
    std::function<void(const std::string&)> current_stage_changed;

private:
    void reassign_active_target();

    pwb::workspace::MappingWorkspaceState& state_;
    LayerGroupController& groups_;
    std::optional<std::string> active_target_layer_id_;
    std::function<bool(const std::string&)> target_validator_;
    std::function<std::optional<std::string>(const std::string& role)>
        target_resolver_;

    bool target_layer_exists(const std::string& layer_id) const;
};

}  // namespace pwb::ui_composite
