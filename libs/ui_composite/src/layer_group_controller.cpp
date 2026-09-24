// Layer group/membership policy — see layer_group_controller.hpp.
// Membership lifecycle ported from the V14 controller; tree execution
// (reconcile/diff/keys/observe) retired with the second layer tree.
#include "pwb/ui_composite/layer_group_controller.hpp"

#include "pwb/ui_composite/layer_groups.hpp"
#include "pwb/ui_composite/stage_profiles.hpp"
#include "pwb/workspace/mutations.hpp"
#include "pwb/workspace/state_ops.hpp"

#include <set>

namespace pwb::ui_composite {

// -- membership & migration ----------------------------------------------------

std::vector<std::string> LayerGroupController::ensure_memberships(
    const std::vector<LayerSnapshotInput>& snapshots,
    bool full_composition) {
    std::vector<std::string> added;
    if (full_composition && !snapshots.empty()) {
        std::set<std::string> live_ids;
        for (const LayerSnapshotInput& layer : snapshots) {
            if (!layer.id.empty()) live_ids.insert(layer.id);
        }
        // Ghost cleanup targets only "real layers gone from the
        // composition" — descriptor-only members (factor grids /
        // uncertainty, non-composite analysis aids) must survive or their
        // registrations would be dropped on the next create_layer pass.
        std::vector<std::string> stale;
        for (const auto& [layer_id, record] : state_.memberships) {
            if (layer_id.empty() || live_ids.count(layer_id) != 0) continue;
            if (record.role == "factor_grid" ||
                record.role == "factor_uncertainty") {
                continue;
            }
            if (record.role == "analysis_aid" &&
                layer_id.rfind("composite:", 0) != 0) {
                continue;
            }
            stale.push_back(layer_id);
        }
        for (const std::string& layer_id : stale) {
            pwb::workspace::drop_membership(state_, layer_id);
        }
    }
    for (const LayerSnapshotInput& layer : snapshots) {
        if (layer.id.empty() ||
            pwb::workspace::membership(state_, layer.id) != nullptr) {
            continue;
        }
        const LayerClassification classified =
            classify_layer_for_migration(layer.id, layer.metadata,
                                         layer.template_key,
                                         layer.geometry_type);
        pwb::workspace::LayerBinding binding;
        binding.layer_id = layer.id;
        binding.role = classified.role;
        binding.constraint_kind = classified.constraint_kind;
        binding.created_stage = state_.current_stage;
        pwb::workspace::set_membership(state_, std::move(binding));
        added.push_back(layer.id);
    }
    return added;
}

void LayerGroupController::register_layer(
    const std::string& layer_id, const std::string& role,
    const std::string& factor_task_id, const std::string& constraint_kind,
    const std::string& source_version_id, const std::string& source_asset_id,
    const std::string& binding_kind, const std::string& bound_at) {
    // V13 W-I: a pinned version without an explicit kind defaults to
    // catalog_version (the pre-V13 writer's only meaning); constraint
    // layers pass content_fingerprint explicitly.
    std::string kind = binding_kind;
    if (!source_version_id.empty() && kind.empty()) {
        kind = std::string(pwb::workspace::kBindingCatalogVersion);
    }
    const pwb::workspace::LayerBinding* existing =
        pwb::workspace::membership(state_, layer_id);
    pwb::workspace::LayerBinding binding;
    binding.layer_id = layer_id;
    binding.role = role;
    binding.factor_task_id = factor_task_id;
    binding.constraint_kind = constraint_kind;
    binding.created_stage =
        existing != nullptr && !existing->created_stage.empty()
            ? existing->created_stage
            : state_.current_stage;
    binding.source_version_id = source_version_id;
    binding.created_at =
        existing != nullptr ? existing->created_at : std::string();
    binding.source_asset_id = source_asset_id;
    binding.binding_kind = kind;
    binding.bound_at = bound_at;
    pwb::workspace::set_layer_binding(state_, std::move(binding));
}

void LayerGroupController::unregister_layer(const std::string& layer_id) {
    pwb::workspace::drop_membership(state_, layer_id);
}

// -- stage view-state policy ------------------------------------------------------

std::map<std::string, bool> LayerGroupController::effective_stage_visibility(
    MappingStage stage) {
    const StageProfile& profile = stage_profile(stage);
    pwb::workspace::StageViewState& view =
        pwb::workspace::view_state(state_, tool_policy::stage_value(stage));
    // Lock semantics: evidence groups default-locked in locked stages
    // (user may unlock).
    for (const std::string& group_id : profile.locked_groups) {
        if (system_group_template(group_id) != nullptr) {
            auto locked = view.group_locked.find(group_id);
            if (locked == view.group_locked.end() ||
                !locked->second.has_value()) {
                view.group_locked[group_id] = true;
            }
        }
    }
    return pwb::workspace::effective_group_visibility(
        view, profile.group_visibility);
}

void LayerGroupController::record_group_visibility_event(
    const std::string& group_id, bool visible) {
    pwb::workspace::record_group_visibility(
        pwb::workspace::view_state(state_, state_.current_stage), group_id,
        visible);
}

void LayerGroupController::record_layer_visibility_event(
    const std::string& layer_id, bool visible) {
    pwb::workspace::record_layer_visibility(
        pwb::workspace::view_state(state_, state_.current_stage), layer_id,
        visible);
}

void LayerGroupController::record_layer_opacity_event(
    const std::string& layer_id, double opacity) {
    pwb::workspace::record_layer_opacity(
        pwb::workspace::view_state(state_, state_.current_stage), layer_id,
        opacity);
}

// -- routing queries -----------------------------------------------------------------

std::string LayerGroupController::home_group_of(
    const std::string& layer_id) const {
    const pwb::workspace::LayerBinding* record =
        pwb::workspace::membership(state_, layer_id);
    if (record == nullptr) return std::string(kLegacyGroupId);
    return effective_home_group(record->role, record->created_stage,
                                record->factor_task_id);
}

bool LayerGroupController::placement_allowed(
    const std::string& layer_id, const std::string& group_id) const {
    const pwb::workspace::LayerBinding* record =
        pwb::workspace::membership(state_, layer_id);
    const std::string role =
        record != nullptr ? record->role : std::string();
    return movable_into_system_group(role, group_id);
}

}  // namespace pwb::ui_composite
