// LayerStageController — the layer-side policy of stage switching.
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
// QGIS-native convergence: the controller computes WHAT should change
// (visibility policy from the profile + per-stage overlay) and applies it
// through host-wired execution hooks onto the real QgsLayerTree
// (pwb::qgis::LayerTreeComposer). No layer objects are touched, no tree
// state is kept here. Qt-free, std::function hooks.
#pragma once

#include "pwb/ui_composite/layer_group_controller.hpp"

#include <functional>
#include <map>
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

    // Tree execution hooks onto the real QGIS layer tree (host wires
    // these to pwb::qgis::LayerTreeComposer; a null hook degrades
    // honestly — the stage still switches, the tree just is not told).
    // ensure_groups: create the union-tree system groups missing from
    // the live tree (create-only, idempotent).
    void set_tree_execution(
        std::function<void()> ensure_groups,
        std::function<void(const std::map<std::string, bool>&)>
            apply_group_visibility);

    // Switch the stage (transient). Returns false for unknown/duplicate
    // requests. Order: write current stage -> ensure the new stage's
    // system groups exist on the live tree (hook failures never break
    // the switch) -> full-push effective group visibility -> reassign
    // the active edit target (stored -> profile roles -> none; NEVER
    // inherited across stages) -> notify.
    bool set_stage(MappingStage stage);
    // Restore the stage context after project reopen: visibility +
    // edit target.
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
    void push_stage_visibility();

    pwb::workspace::MappingWorkspaceState& state_;
    LayerGroupController& groups_;
    std::optional<std::string> active_target_layer_id_;
    std::function<bool(const std::string&)> target_validator_;
    std::function<std::optional<std::string>(const std::string& role)>
        target_resolver_;
    std::function<void()> ensure_groups_;
    std::function<void(const std::map<std::string, bool>&)>
        apply_group_visibility_;

    bool target_layer_exists(const std::string& layer_id) const;
};

}  // namespace pwb::ui_composite
