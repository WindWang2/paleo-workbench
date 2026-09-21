// V14 layer stage controller — port of the layer subset of
// controller.py (see layer_stage_controller.hpp).
#include "pwb/ui_composite/layer_stage_controller.hpp"

#include "pwb/ui_composite/stage_profiles.hpp"
#include "pwb/workspace/state_ops.hpp"

namespace pwb::ui_composite {

LayerStageController::LayerStageController(
    pwb::workspace::MappingWorkspaceState& state,
    LayerGroupController& groups)
    : state_(state), groups_(groups) {}

void LayerStageController::set_target_validator(
    std::function<bool(const std::string&)> validator) {
    // V13 W-P: the user's explicit per-stage active edit target
    // (StageViewState.active_layer_id) is restored first when the layer
    // still exists. Without a probe, membership existence is the
    // conservative approximation.
    target_validator_ = std::move(validator);
}

void LayerStageController::set_target_resolver(
    std::function<std::optional<std::string>(const std::string& role)>
        resolver) {
    target_resolver_ = std::move(resolver);
}

bool LayerStageController::target_layer_exists(
    const std::string& layer_id) const {
    if (target_validator_) {
        // Python parity: a throwing validator resolves to "layer gone"
        // (fail-closed), never escapes into the stage switch.
        try {
            return target_validator_(layer_id);
        } catch (...) {
            return false;
        }
    }
    return pwb::workspace::membership(state_, layer_id) != nullptr;
}

bool LayerStageController::set_stage(MappingStage stage) {
    const std::string target = tool_policy::stage_value(stage);
    if (target.empty()) return false;  // unknown stage requested
    if (target == state_.current_stage) return false;
    state_.current_stage = target;
    // V11 (D11-ws): materialize the new stage's empty system groups
    // (minimal diff: empty-group creation only). R2-P1: a bridge throw
    // must not break the stage switch (visibility/signals continue).
    try {
        groups_.rematerialize_for_stage();
    } catch (const std::exception&) {
        // host logs; the switch itself proceeds
    }
    // Group visibility delta (profile defaults + user overlays, full
    // push).
    groups_.apply_stage_visibility(stage);
    // Edit-target reassignment: NEVER inherited across stages (P0/P1
    // business risk, V5 §88).
    reassign_active_target();
    if (current_stage_changed) {
        try {
            current_stage_changed(target);
        } catch (...) {
        }
    }
    return true;
}

void LayerStageController::reassign_active_target() {
    // Resolution order (V13 W-P):
    // 1. this stage's persisted active_layer_id (the user's explicit
    //    choice or last activity), restored when the layer still exists —
    //    reading the stage's OWN view state keeps "no cross-stage
    //    inheritance" intact;
    // 2. the first of profile.active_editing_roles with an existing
    //    layer;
    // 3. all missing -> none (edit actions disable with a reason — never
    //    silently point at some other editable layer).
    std::optional<std::string> target_id;
    const std::optional<MappingStage> stage =
        tool_policy::stage_from_value(state_.current_stage);
    if (!stage.has_value()) return;  // unknown persisted stage: no reassign
    const StageProfile& profile = stage_profile(*stage);
    pwb::workspace::StageViewState& view =
        pwb::workspace::view_state(state_, state_.current_stage);
    if (view.active_layer_id.has_value() &&
        !view.active_layer_id->empty() &&
        target_layer_exists(*view.active_layer_id)) {
        target_id = view.active_layer_id;
    }
    if (!target_id.has_value() && target_resolver_) {
        for (const std::string& role : profile.active_editing_roles) {
            const std::optional<std::string> resolved = target_resolver_(role);
            if (resolved.has_value() && !resolved->empty()) {
                target_id = resolved;
                break;
            }
        }
    }
    if (target_id != active_target_layer_id_) {
        active_target_layer_id_ = target_id;
        pwb::workspace::view_state(state_, state_.current_stage)
            .active_layer_id = target_id;
        if (active_target_changed) {
            try {
                active_target_changed(target_id);
            } catch (...) {
            }
        }
    }
}

void LayerStageController::set_active_target(const std::string& layer_id) {
    const std::optional<std::string> target =
        layer_id.empty() ? std::optional<std::string>{}
                         : std::optional<std::string>(layer_id);
    pwb::workspace::view_state(state_, state_.current_stage).active_layer_id =
        target;
    if (target != active_target_layer_id_) {
        active_target_layer_id_ = target;
        if (active_target_changed) {
            try {
                active_target_changed(target);
            } catch (...) {
            }
        }
    }
}

void LayerStageController::restore_stage_view() {
    // Project-reopen restore: visibility + expand states + edit target.
    auto stage = tool_policy::stage_from_value(state_.current_stage);
    if (stage.has_value()) {
        groups_.apply_stage_visibility(*stage);
    }
    auto expanded_it = groups_.expand_states.find(state_.current_stage);
    if (expanded_it != groups_.expand_states.end()) {
        groups_.apply_group_expanded(expanded_it->second);
    }
    reassign_active_target();
}

}  // namespace pwb::ui_composite
