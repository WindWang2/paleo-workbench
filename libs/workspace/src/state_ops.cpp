// V14 workspace state operations — see state_ops.hpp.
#include "pwb/workspace/state_ops.hpp"

#include "pwb/workspace/mutations.hpp"

#include <algorithm>

namespace pwb::workspace {

StageViewState& view_state(MappingWorkspaceState& state,
                           const std::string& stage_value) {
    auto it = state.stage_states.find(stage_value);
    if (it == state.stage_states.end()) {
        StageViewState view;
        view.stage = stage_value;
        it = state.stage_states.emplace(stage_value, std::move(view)).first;
    }
    return it->second;
}

const StageViewState* find_view_state(const MappingWorkspaceState& state,
                                      const std::string& stage_value) {
    auto it = state.stage_states.find(stage_value);
    return it == state.stage_states.end() ? nullptr : &it->second;
}

std::map<std::string, bool> effective_group_visibility(
    const StageViewState& view,
    const std::map<std::string, bool>& defaults) {
    std::map<std::string, bool> effective = defaults;
    for (const auto& [group_id, override] : view.group_visibility) {
        if (override.has_value()) effective[group_id] = *override;
    }
    return effective;
}

void record_group_visibility(StageViewState& view,
                             const std::string& group_id, bool visible) {
    view.group_visibility[group_id] = visible;
    view.customized = true;
}

void record_layer_visibility(StageViewState& view,
                             const std::string& layer_id, bool visible) {
    view.layer_visibility[layer_id] = visible;
    view.customized = true;
}

void record_layer_opacity(StageViewState& view, const std::string& layer_id,
                          double opacity) {
    view.layer_opacity[layer_id] = std::max(0.05, std::min(1.0, opacity));
    view.customized = true;
}

void reset_stage_view_to_defaults(StageViewState& view) {
    view.group_visibility.clear();
    view.group_locked.clear();
    view.layer_visibility.clear();
    view.layer_opacity.clear();
    view.active_layer_id.reset();
    view.active_tool.reset();
    view.customized = false;
}

const LayerBinding* membership(const MappingWorkspaceState& state,
                               const std::string& layer_id) {
    auto it = state.memberships.find(layer_id);
    return it == state.memberships.end() ? nullptr : &it->second;
}

void set_membership(MappingWorkspaceState& state, LayerBinding binding) {
    if (binding.layer_id.empty()) return;
    const std::string layer_id = binding.layer_id;
    state.memberships[layer_id] = std::move(binding);
}

void drop_membership(MappingWorkspaceState& state,
                     const std::string& layer_id) {
    // Delegates to the conv-26 mutation so the per-stage view-state purge
    // (and its active-layer reset) stays single-sourced.
    remove_layer_binding(state, layer_id);
}

std::vector<std::string> layers_with_role(const MappingWorkspaceState& state,
                                          const std::string& role_value) {
    std::vector<std::string> out;
    for (const auto& [layer_id, record] : state.memberships) {
        if (record.role == role_value) out.push_back(layer_id);
    }
    return out;
}

std::vector<LayerBinding> catalog_bindings_of(
    const MappingWorkspaceState& state) {
    return state.catalog_bindings();
}

}  // namespace pwb::workspace
